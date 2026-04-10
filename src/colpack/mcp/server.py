import asyncio
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


class SetupSimulationProblemInput(BaseModel):
    dimension: int = Field(..., description="Simulation dimension, must be 2 or 3.")
    total_particle_number: int = Field(..., gt=0, description="Total number of particles in the simulation.")
    particle_shape_list: list[str] = Field(..., min_length=1, description="List of colloid shapes, e.g. ['sphere', 'capsule'].")
    ensemble: str = Field(..., description="Thermodynamic ensemble, either NVT or NPT.")


class PlanSimulationRunsInput(BaseModel):
    baseline_parameters: dict[str, Any] = Field(..., description="Baseline workflow parameter overrides. Every key must already exist in simulation_problem.json.")
    tunable_parameters: dict[str, list[Any]] = Field(..., description="Dot-path parameter sweeps. Every key must already exist in simulation_problem.json.")
    working_dir: str = Field(..., description="Directory containing simulation_problem.json and output plan files.")


class ExecuteSimulationWorkflowInput(BaseModel):
    working_dir: str = Field(..., description="Directory containing simulation_plan.json.")
    continue_on_error: bool = Field(default=True, description="If true, continue remaining runs when one run fails.")
    wait: bool = Field(
        default=False,
        description="If true, run synchronously and wait for completion. If false, start background job and return immediately.",
    )


class WorkflowExecutionStatusInput(BaseModel):
    working_dir: str | None = Field(default=None, description="Workflow working directory to query.")
    job_id: str | None = Field(default=None, description="Explicit background job id to query.")


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


@mcp.tool()
async def execute_simulation_workflow_tool(
    params: ExecuteSimulationWorkflowInput,
    context: Context | None = None,
) -> dict[str, Any]:
    """Execute planned simulation workflow synchronously or asynchronously."""
    resolved_dir = _normalize_working_dir(params.working_dir)
    print(
        "[mcp] execute_simulation_workflow_tool "
        f"working_dir={resolved_dir} wait={params.wait} continue_on_error={params.continue_on_error}"
    )
    append_workflow_log(
        resolved_dir,
        f"execute_simulation_workflow_tool invoked with wait={params.wait} continue_on_error={params.continue_on_error}",
        source="mcp",
    )

    await _safe_context_info(
        context,
        f"Workflow execution requested: wait={params.wait}, continue_on_error={params.continue_on_error}.",
    )

    if not params.wait:
        if _workflow_marked_running_in_csv(resolved_dir):
            await _safe_context_info(context, "Workflow execution is already running; duplicate async execute call skipped.")
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
                f"Started async workflow job {launch['job_id']}. Use get_simulation_workflow_status_tool to monitor progress.",
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

    await _safe_context_report_progress(context, progress=0, total=1, message="Preparing workflow execution.")

    try:
        result = await asyncio.to_thread(
            execute_simulation_workflow,
            working_dir=resolved_dir,
            continue_on_error=params.continue_on_error,
        )
    except Exception as exc:
        await _safe_context_error(context, f"Workflow execution failed: {exc}")
        raise

    if result.get("already_running"):
        await _safe_context_info(context, "Workflow execution is already running; duplicate execute call skipped.")
    else:
        await _safe_context_report_progress(context, progress=1, total=1, message="Workflow execution completed.")
        await _safe_context_info(context, "Workflow execution completed.")

    return {
        "ok": True,
        "mode": "sync",
        "working_dir": resolved_dir,
        "status_path": result["status_path"],
        "progress_path": result.get("progress_path"),
        "log_path": result.get("log_path"),
        "progress": _read_workflow_progress(resolved_dir),
        "n_runs": result["n_runs"],
        "n_success": result["n_success"],
        "n_failed": result["n_failed"],
        "already_running": bool(result.get("already_running", False)),
    }


@mcp.tool()
def get_simulation_workflow_status_tool(params: WorkflowExecutionStatusInput) -> dict[str, Any]:
    """Get status for an async workflow execution job and current workflow_status.csv counts."""
    resolved_dir = _normalize_working_dir(params.working_dir) if params.working_dir else None

    selected_job_id = None
    with _jobs_lock:
        selected_job = None
        if params.job_id:
            selected_job_id = params.job_id
            selected_job = _workflow_jobs.get(params.job_id)
        elif resolved_dir:
            job_id = _jobs_by_working_dir.get(resolved_dir)
            if job_id:
                selected_job_id = job_id
                selected_job = _workflow_jobs.get(job_id)

    if selected_job_id is not None:
        job_snapshot = _refresh_job_record(selected_job_id)
    else:
        job_snapshot = dict(selected_job) if selected_job else None

    if job_snapshot is None and resolved_dir is None:
        raise ValueError("Provide either job_id or working_dir.")

    working_dir = resolved_dir or str(job_snapshot["working_dir"])
    csv_counts = _count_status_from_csv(working_dir)

    return {
        "ok": True,
        "working_dir": working_dir,
        "job": job_snapshot,
        "status_path": str(Path(working_dir) / "workflow_status.csv"),
        "progress_path": str(Path(working_dir) / "workflow_progress.json"),
        "log_path": str(resolve_workflow_log_path(working_dir)),
        "progress": _read_workflow_progress(working_dir),
        **csv_counts,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
