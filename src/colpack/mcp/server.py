import multiprocessing
from pathlib import Path
import csv
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field

from colpack.workflow import (
    analyze_simulation_runs,
    execute_simulation_workflow,
    plan_simulaiton_runs,
    setup_simulation_problem,
)
from colpack.workflow_logging import append_workflow_log, resolve_workflow_log_path


mcp = FastMCP("ColPackTools")


_workflow_jobs: dict[str, dict[str, Any]] = {}
_workflow_processes: dict[str, multiprocessing.Process] = {}
_jobs_by_working_dir: dict[str, str] = {}
_jobs_lock = threading.Lock()


def _read_workflow_progress(working_dir: str) -> dict[str, Any] | None:
    progress_path = Path(working_dir) / "workflow_progress.json"
    if not progress_path.exists():
        return None

    try:
        import json

        return json.loads(progress_path.read_text())
    except Exception:
        return None


def _normalize_working_dir(working_dir: str) -> str:
    """Return a normalized absolute path for workflow working directories."""
    return str(Path(working_dir).expanduser().resolve())


async def _safe_context_report_progress(
    context: Context | None,
    *,
    progress: int,
    total: int,
    message: str,
) -> None:
    if context is None:
        return
    try:
        await context.report_progress(progress=progress, total=total, message=message)
    except Exception:
        pass


async def _safe_context_info(context: Context | None, message: str) -> None:
    if context is None:
        return
    try:
        await context.info(message)
    except Exception:
        pass


async def _safe_context_error(context: Context | None, message: str) -> None:
    if context is None:
        return
    try:
        await context.error(message)
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


_analyze_jobs: dict[str, dict[str, Any]] = {}
_analyze_processes: dict[str, multiprocessing.Process] = {}
_analyze_jobs_by_working_dir: dict[str, str] = {}
_analyze_lock = threading.Lock()


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


def _run_analyze_job_process(working_dir: str, continue_on_error: bool) -> None:
    try:
        analyze_simulation_runs(
            working_dir=working_dir,
            continue_on_error=continue_on_error,
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


def _start_analyze_job(working_dir: str, continue_on_error: bool) -> dict[str, Any]:
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
        args=(working_dir, continue_on_error),
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


# TODO: total particle number not necessary for setup_simulation_problem; can be inferred from particle list.
class SetupSimulationProblemInput(BaseModel):
    dimension: int = Field(..., description="Simulation dimension, must be 2 or 3.")
    total_particle_number: int = Field(..., gt=0, description="Total number of particles in the simulation.")
    particle_shape_list: list[str] = Field(..., min_length=1, description="List of colloid shapes, supported shapes are: for dimensions=2: ['disk', 'ellipse', 'capsule', 'triangle', 'square', 'rectangle'] ;for dimensions=2 ['sphere', 'ellipsoid', capsule', 'tethrahedron', 'cube', 'octahedron'].")
    ensemble: str = Field(..., description="Thermodynamic ensemble, either NVT or NPT.")


@mcp.tool()
def setup_simulation_problem_tool(params: SetupSimulationProblemInput) -> dict[str, Any]:
    """Create simulation_problem.json for a workflow directory."""
    result = setup_simulation_problem(
        dimension=params.dimension,
        total_particle_number=params.total_particle_number,
        particle_shape_list=params.particle_shape_list,
        ensemble=params.ensemble,
    )

    resolved_dir = str(result["working_dir"])
    print(f"[mcp] setup_simulation_problem_tool working_dir={resolved_dir}")
    append_workflow_log(resolved_dir, "setup_simulation_problem_tool invoked", source="mcp")

    return {
        "ok": True,
        "working_dir": resolved_dir,
        "simulation_problem_path": str(Path(resolved_dir) / "simulation_problem.json"),
        "log_path": str(resolve_workflow_log_path(resolved_dir)),
        "simulation_problem": result,
    }


class PlanSimulationRunsInput(BaseModel):
    baseline_parameters: dict[str, Any] = Field(..., description="Baseline workflow parameter overrides. Every key must already exist in simulation_problem.json.")
    tunable_parameters: dict[str, list[Any]] = Field(..., description="Dot-path parameter sweeps. Every key must already exist in simulation_problem.json.")
    working_dir: str = Field(..., description="Directory containing simulation_problem.json and output plan files.")


@mcp.tool()
def plan_simulation_runs_tool(params: PlanSimulationRunsInput) -> dict[str, Any]:
    """Create simulation_baseline.json, run folders, and simulation_plan.json from simulation_problem.json-defined paths."""
    resolved_dir = _normalize_working_dir(params.working_dir)
    print(f"[mcp] plan_simulation_runs_tool working_dir={resolved_dir}")
    append_workflow_log(resolved_dir, "plan_simulation_runs_tool invoked", source="mcp")
    result = plan_simulaiton_runs(
        baseline_parameters=params.baseline_parameters,
        tunable_parameters=params.tunable_parameters,
        working_dir=resolved_dir,
    )
    return {
        "ok": True,
        "working_dir": resolved_dir,
        "planning_path": result["planning_path"],
        "baseline_path": result["baseline_path"],
        "log_path": str(resolve_workflow_log_path(resolved_dir)),
        "n_runs": result["n_runs"],
        "simulation_runs": result["simulation_runs"],
    }


class ExecuteSimulationWorkflowInput(BaseModel):
    working_dir: str = Field(..., description="Directory containing simulation_plan.json.")
    continue_on_error: bool = Field(default=True, description="If true, continue remaining runs when one run fails.")


@mcp.tool()
async def execute_simulation_workflow_tool(
    params: ExecuteSimulationWorkflowInput,
    context: Context | None = None,
) -> dict[str, Any]:
    """
    Launch the simulation workflow as a background job and return immediately.

    Simulations can take minutes to hours; this tool always runs asynchronously.
    After calling this tool, poll for completion using get_workflow_status_tool.
    """
    resolved_dir = _normalize_working_dir(params.working_dir)
    print(
        "[mcp] execute_simulation_workflow_tool "
        f"working_dir={resolved_dir} continue_on_error={params.continue_on_error}"
    )
    append_workflow_log(
        resolved_dir,
        f"execute_simulation_workflow_tool invoked with continue_on_error={params.continue_on_error}",
        source="mcp",
    )

    await _safe_context_info(
        context,
        f"Workflow execution requested (async): continue_on_error={params.continue_on_error}.",
    )

    if _workflow_marked_running_in_csv(resolved_dir):
        await _safe_context_info(context, "Workflow execution is already running; duplicate execute call skipped.")
        csv_counts = _count_status_from_csv(resolved_dir)
        return {
            "ok": True,
            "mode": "async",
            "working_dir": resolved_dir,
            "job_id": None,
            "job_status": "running",
            "already_running": True,
            "status_path": str(Path(resolved_dir) / "workflow_status.csv"),
            "log_path": str(resolve_workflow_log_path(resolved_dir)),
            "progress": _read_workflow_progress(resolved_dir),
            **csv_counts,
        }

    launch = _start_workflow_job(
        working_dir=resolved_dir,
        continue_on_error=params.continue_on_error,
    )
    if launch["started"]:
        await _safe_context_info(
            context,
            f"Started background workflow job {launch['job_id']}. "
            "Use get_workflow_status_tool to poll for completion.",
        )
    else:
        await _safe_context_info(
            context,
            f"Workflow job {launch['job_id']} is already running. Reusing existing job.",
        )
    csv_counts = _count_status_from_csv(resolved_dir)
    return {
        "ok": True,
        "mode": "async",
        "working_dir": resolved_dir,
        "job_id": launch["job_id"],
        "job_status": launch["status"],
        "already_running": not launch["started"],
        "status_path": str(Path(resolved_dir) / "workflow_status.csv"),
        "log_path": str(resolve_workflow_log_path(resolved_dir)),
        "progress": _read_workflow_progress(resolved_dir),
        **csv_counts,
    }


class AnalyzeSimulationRunsInput(BaseModel):
    working_dir: str = Field(..., description="Directory containing simulation_plan.json and completed simulation runs.")
    continue_on_error: bool = Field(default=True, description="If true, continue remaining runs when one fails analysis.")


@mcp.tool()
async def analyze_simulation_runs_tool(
    params: AnalyzeSimulationRunsInput,
    context: Context | None = None,
) -> dict[str, Any]:
    """
    Launch analysis of simulation results as a background job and return immediately.

    Analysis can take significant time; this tool always runs asynchronously.
    After calling this tool, poll for completion using get_workflow_status_tool.
    """
    resolved_dir = _normalize_working_dir(params.working_dir)
    print(
        "[mcp] analyze_simulation_runs_tool "
        f"working_dir={resolved_dir} continue_on_error={params.continue_on_error}"
    )
    append_workflow_log(
        resolved_dir,
        f"analyze_simulation_runs_tool invoked with continue_on_error={params.continue_on_error}",
        source="mcp",
    )

    await _safe_context_info(
        context,
        f"Analysis requested (async): continue_on_error={params.continue_on_error}.",
    )

    if _workflow_marked_running_in_csv(resolved_dir):
        await _safe_context_info(context, "A workflow job is already running in this directory; async analyze call skipped.")
        csv_counts = _count_status_from_csv(resolved_dir)
        return {
            "ok": True,
            "mode": "async",
            "working_dir": resolved_dir,
            "job_id": None,
            "job_status": "running",
            "already_running": True,
            "status_path": str(Path(resolved_dir) / "workflow_status.csv"),
            "log_path": str(resolve_workflow_log_path(resolved_dir)),
            "progress": _read_workflow_progress(resolved_dir),
            **csv_counts,
        }

    launch = _start_analyze_job(
        working_dir=resolved_dir,
        continue_on_error=params.continue_on_error,
    )
    if launch["started"]:
        await _safe_context_info(
            context,
            f"Started background analyze job {launch['job_id']}. "
            "Use get_workflow_status_tool to poll for completion.",
        )
    else:
        await _safe_context_info(
            context,
            f"Analyze job {launch['job_id']} is already running. Reusing existing job.",
        )
    csv_counts = _count_status_from_csv(resolved_dir)
    return {
        "ok": True,
        "mode": "async",
        "working_dir": resolved_dir,
        "job_id": launch["job_id"],
        "job_status": launch["status"],
        "already_running": not launch["started"],
        "status_path": str(Path(resolved_dir) / "workflow_status.csv"),
        "log_path": str(resolve_workflow_log_path(resolved_dir)),
        "progress": _read_workflow_progress(resolved_dir),
        **csv_counts,
    }


class GetWorkflowStatusInput(BaseModel):
    working_dir: str = Field(..., description="Workflow directory to check (same directory passed to execute or analyze tools).")


@mcp.tool()
async def get_workflow_status_tool(
    params: GetWorkflowStatusInput,
    context: Context | None = None,
) -> dict[str, Any]:
    """
    Poll the status of a running or completed background workflow/analyze job.

    Call this repeatedly after execute_simulation_workflow_tool or
    analyze_simulation_runs_tool to check whether the job has finished.
    Returns workflow_progress.json content, per-run CSV counts, and job status.
    """
    resolved_dir = _normalize_working_dir(params.working_dir)
    progress = _read_workflow_progress(resolved_dir)
    csv_counts = _count_status_from_csv(resolved_dir)

    # Check both workflow and analyze job registries.
    job_info: dict[str, Any] = {}
    with _jobs_lock:
        job_id = _jobs_by_working_dir.get(resolved_dir)
    if job_id:
        record = _refresh_job_record(job_id)
        if record:
            job_info = {
                "job_type": "workflow",
                "job_id": record["job_id"],
                "job_status": record["status"],
                "job_started_at": record.get("started_at"),
                "job_finished_at": record.get("finished_at"),
                "job_error": record.get("error"),
            }

    if not job_info:
        with _analyze_lock:
            az_job_id = _analyze_jobs_by_working_dir.get(resolved_dir)
        if az_job_id:
            record = _refresh_analyze_job_record(az_job_id)
            if record:
                job_info = {
                    "job_type": "analyze",
                    "job_id": record["job_id"],
                    "job_status": record["status"],
                    "job_started_at": record.get("started_at"),
                    "job_finished_at": record.get("finished_at"),
                    "job_error": record.get("error"),
                }

    # Derive a simple overall status for the agent to act on.
    overall_status = "unknown"
    if progress:
        overall_status = progress.get("status", "unknown")
    if job_info.get("job_status") == "running":
        overall_status = "running"
    elif job_info.get("job_status") in ("completed", "failed") and overall_status == "unknown":
        overall_status = job_info["job_status"]

    return {
        "ok": True,
        "working_dir": resolved_dir,
        "overall_status": overall_status,
        "progress": progress,
        "log_path": str(resolve_workflow_log_path(resolved_dir)),
        "status_path": str(Path(resolved_dir) / "workflow_status.csv"),
        **csv_counts,
        **job_info,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
