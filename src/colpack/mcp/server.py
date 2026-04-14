from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field

from colpack.workflow import plan_simulaiton_runs, setup_simulation_problem
from colpack.workflow_logging import append_workflow_log, resolve_workflow_log_path
from colpack.config_reading import load_config
from colpack.mcp.server_helper import (
    _count_status_from_csv,
    _normalize_working_dir,
    _read_workflow_progress,
    _safe_context_info,
    _start_analyze_job,
    _start_workflow_job,
    _workflow_marked_running_in_csv,
)


mcp = FastMCP("ColPackTools")


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
    Monitor progress locally via workflow_progress.json and workflow_events.log.
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
            "Monitor progress via workflow_progress.json and workflow_events.log.",
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
    Monitor progress locally via workflow_progress.json and workflow_events.log.
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
            "Monitor progress via workflow_progress.json and workflow_events.log.",
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


@mcp.tool()
def get_colpack_capabilities_tool() -> dict[str, Any]:
    """
    Return a structured description of ColPack's simulation capabilities.

    Call this tool at the start of a session or whenever you need to understand
    what dimensions, shapes, ensembles, and workflow steps are supported.
    """
    cfg = load_config()
    dim_cfg = cfg.get("dimensions", {})
    workflow_cfg = cfg.get("workflow", {})
    ensemble_requirements = workflow_cfg.get("ensemble_requirements", {})
    common_fields = workflow_cfg.get("common_system_fields", {})

    # Shapes per dimension from config.
    supported_shapes = {
        f"{dim}d": dim_cfg[str(dim)]["allowed_shapes"]
        for dim in (2, 3)
        if str(dim) in dim_cfg
    }

    # Ensemble descriptions (human-readable) keyed to config-defined ensembles.
    _ensemble_descriptions = {
        "NVT": "Fixed volume; sweep packing fraction by varying box size at constant N.",
        "NPT": "Fixed pressure; box volume fluctuates to reach target pressure.",
    }
    ensembles = {
        name: _ensemble_descriptions.get(name, name)
        for name in ensemble_requirements
    }

    # Key tunable parameters: one entry per ensemble-specific system field +
    # shared fields from common_system_fields.
    key_parameters: dict[str, str] = {}
    for ens_name, ens_block in ensemble_requirements.items():
        for field in ens_block.get("system_fields", {}):
            key_parameters[field] = f"({ens_name}) tunable system-level parameter."
    for field in common_fields:
        key_parameters[field] = "Shared system-level parameter (all ensembles)."
    key_parameters["particle_specs.N.length"] = "Shape-specific length parameter (capsule, ellipse, rectangle)."
    key_parameters["particle_specs.N.width"] = "Shape-specific width parameter (rectangle)."

    return {
        "ok": True,
        "description": "ColPack: hard-particle Monte Carlo packing simulations via HOOMD-blue.",
        "dimensions": [int(d) for d in dim_cfg],
        "supported_shapes": supported_shapes,
        "ensembles": ensembles,
        "workflow_steps": [
            {
                "step": 1,
                "tool": "setup_simulation_problem_tool",
                "description": "Define the simulation problem (dimension, ensemble, shapes, particle count). Returns working_dir.",
            },
            {
                "step": 2,
                "tool": "plan_simulation_runs_tool",
                "description": "Create run folders and simulation_plan.json by specifying baseline and tunable parameter sweeps.",
            },
            {
                "step": 3,
                "tool": "execute_simulation_workflow_tool",
                "description": "Launch simulations as an async background job. Monitor progress via workflow_progress.json and workflow_events.log in working_dir.",
            },
            {
                "step": 4,
                "tool": "analyze_simulation_runs_tool",
                "description": "Launch analysis as an async background job after execution completes. Computes RDF, packing fraction, order parameters, etc.",
            },
        ],
        "progress_monitoring": {
            "workflow_progress_file": "workflow_progress.json",
            "workflow_log_file": "workflow_events.log",
            "workflow_status_csv": "workflow_status.csv",
            "note": "Poll workflow_progress.json locally; no MCP polling tool is needed.",
        },
        "key_parameters": key_parameters,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
