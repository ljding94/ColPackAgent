import csv
import json
import multiprocessing
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

from colpack.workflow import analyze_simulation_runs, execute_simulation_workflow
from colpack.workflow_logging import append_workflow_log


# ---------------------------------------------------------------------------
# Module-level job registries
# ---------------------------------------------------------------------------

_workflow_jobs: dict[str, dict[str, Any]] = {}
_workflow_processes: dict[str, multiprocessing.Process] = {}
_jobs_by_working_dir: dict[str, str] = {}
_jobs_lock = threading.Lock()

_analyze_jobs: dict[str, dict[str, Any]] = {}
_analyze_processes: dict[str, multiprocessing.Process] = {}
_analyze_jobs_by_working_dir: dict[str, str] = {}
_analyze_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _normalize_working_dir(working_dir: str) -> str:
    """Return a normalized absolute path for workflow working directories."""
    return str(Path(working_dir).expanduser().resolve())


def _read_workflow_progress(working_dir: str) -> dict[str, Any] | None:
    progress_path = Path(working_dir) / "workflow_progress.json"
    if not progress_path.exists():
        return None

    try:
        return json.loads(progress_path.read_text())
    except Exception:
        return None


async def _safe_context_info(context: Context | None, message: str) -> None:
    if context is None:
        return
    try:
        await context.info(message)
    except Exception:
        pass


def _count_status_from_csv(working_dir: str) -> dict[str, int]:
    status_path = Path(working_dir) / "workflow_status.csv"
    if not status_path.exists():
        return {
            "n_total_records": 0,
            "n_runs_seen": 0,
            "n_success": 0,
            "n_failed": 0,
        }

    n_total = 0
    latest_by_run: dict[str, dict[str, Any]] = {}
    with status_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            n_total += 1
            run_key = str(row.get("run_number", "")).strip()
            latest_by_run[run_key] = row

    n_success = 0
    n_failed = 0
    for row in latest_by_run.values():
        status = (row.get("status") or "").strip().lower()
        if status == "success":
            n_success += 1
        elif status == "failed":
            n_failed += 1

    return {
        "n_total_records": n_total,
        "n_runs_seen": len(latest_by_run),
        "n_success": n_success,
        "n_failed": n_failed,
    }


def _workflow_marked_running_in_csv(working_dir: str) -> bool:
    status_path = Path(working_dir) / "workflow_status.csv"
    if not status_path.exists() or status_path.stat().st_size == 0:
        return False

    with status_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            execution_state = str(row.get("execution_state", "")).strip().lower()
            if execution_state == "running":
                return True
    return False


# ---------------------------------------------------------------------------
# Workflow job management
# ---------------------------------------------------------------------------

def _run_workflow_job_process(working_dir: str, continue_on_error: bool) -> None:
    try:
        execute_simulation_workflow(
            working_dir=working_dir,
            continue_on_error=continue_on_error,
        )
        append_workflow_log(working_dir, "workflow job completed", source="mcp")
    except Exception as exc:
        append_workflow_log(working_dir, f"workflow job failed: {exc}", source="mcp")
        raise


def _refresh_job_record(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        current = _workflow_jobs.get(job_id)
        process = _workflow_processes.get(job_id)
        if current is None:
            return None
        if process is None:
            return dict(current)

    if process.is_alive():
        return dict(current)

    process.join(timeout=0)
    with _jobs_lock:
        current = _workflow_jobs.get(job_id)
        if current is None:
            return None

        if current.get("status") == "running":
            current["finished_at"] = datetime.now(timezone.utc).isoformat()
            if process.exitcode == 0:
                current["status"] = "completed"
            else:
                current["status"] = "failed"
                current["error"] = current.get("error") or f"Workflow process exited with code {process.exitcode}."

        _workflow_processes.pop(job_id, None)
        return dict(current)


def _start_workflow_job(working_dir: str, continue_on_error: bool) -> dict[str, Any]:
    with _jobs_lock:
        existing_job_id = _jobs_by_working_dir.get(working_dir)

    if existing_job_id:
        existing = _refresh_job_record(existing_job_id)
        if existing and existing.get("status") == "running":
            append_workflow_log(
                working_dir,
                f"async workflow request reused running job {existing_job_id}",
                source="mcp",
            )
            return {
                "started": False,
                "job_id": existing_job_id,
                "status": "running",
            }

    with _jobs_lock:
        job_id = f"wf_{uuid.uuid4().hex[:12]}"
        job_record = {
            "job_id": job_id,
            "working_dir": working_dir,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
            "result": None,
        }
        _workflow_jobs[job_id] = job_record
        _jobs_by_working_dir[working_dir] = job_id

    append_workflow_log(
        working_dir,
        f"started async workflow job {job_id} with continue_on_error={continue_on_error}",
        source="mcp",
    )

    process = multiprocessing.get_context("spawn").Process(
        target=_run_workflow_job_process,
        args=(working_dir, continue_on_error),
        name=f"colpack-workflow-{job_id}",
        daemon=False,
    )
    process.start()
    with _jobs_lock:
        _workflow_processes[job_id] = process

    return {
        "started": True,
        "job_id": job_id,
        "status": "running",
    }


# ---------------------------------------------------------------------------
# Analyze job management
# ---------------------------------------------------------------------------

def _run_analyze_job_process(working_dir: str, continue_on_error: bool, extra_order_params: list | None = None) -> None:
    try:
        analyze_simulation_runs(
            working_dir=working_dir,
            continue_on_error=continue_on_error,
            extra_order_params=extra_order_params,
        )
        append_workflow_log(working_dir, "analyze job completed", source="mcp")
    except Exception as exc:
        append_workflow_log(working_dir, f"analyze job failed: {exc}", source="mcp")
        raise


def _refresh_analyze_job_record(job_id: str) -> dict[str, Any] | None:
    with _analyze_lock:
        current = _analyze_jobs.get(job_id)
        process = _analyze_processes.get(job_id)
        if current is None:
            return None
        if process is None:
            return dict(current)

    if process.is_alive():
        return dict(current)

    process.join(timeout=0)
    with _analyze_lock:
        current = _analyze_jobs.get(job_id)
        if current is None:
            return None

        if current.get("status") == "running":
            current["finished_at"] = datetime.now(timezone.utc).isoformat()
            if process.exitcode == 0:
                current["status"] = "completed"
            else:
                current["status"] = "failed"
                current["error"] = current.get("error") or f"Analyze process exited with code {process.exitcode}."

        _analyze_processes.pop(job_id, None)
        return dict(current)


def _start_analyze_job(working_dir: str, continue_on_error: bool, extra_order_params: list | None = None) -> dict[str, Any]:
    with _analyze_lock:
        existing_job_id = _analyze_jobs_by_working_dir.get(working_dir)

    if existing_job_id:
        existing = _refresh_analyze_job_record(existing_job_id)
        if existing and existing.get("status") == "running":
            append_workflow_log(
                working_dir,
                f"async analyze request reused running job {existing_job_id}",
                source="mcp",
            )
            return {
                "started": False,
                "job_id": existing_job_id,
                "status": "running",
            }

    with _analyze_lock:
        job_id = f"az_{uuid.uuid4().hex[:12]}"
        job_record = {
            "job_id": job_id,
            "working_dir": working_dir,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
            "result": None,
        }
        _analyze_jobs[job_id] = job_record
        _analyze_jobs_by_working_dir[working_dir] = job_id

    append_workflow_log(
        working_dir,
        f"started async analyze job {job_id} with continue_on_error={continue_on_error}",
        source="mcp",
    )

    process = multiprocessing.get_context("spawn").Process(
        target=_run_analyze_job_process,
        args=(working_dir, continue_on_error, extra_order_params),
        name=f"colpack-analyze-{job_id}",
        daemon=False,
    )
    process.start()
    with _analyze_lock:
        _analyze_processes[job_id] = process

    return {
        "started": True,
        "job_id": job_id,
        "status": "running",
    }
