from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from colpack.workflow import (
    execute_simulation_workflow,
    plan_simulaiton_runs,
    setup_simulation_problem,
)


mcp = FastMCP("ColPackTools")


def _normalize_working_dir(working_dir: str) -> str:
    """Return a normalized absolute path for workflow working directories."""
    return str(Path(working_dir).expanduser().resolve())


class SetupSimulationProblemInput(BaseModel):
    dimension: int = Field(..., description="Simulation dimension, must be 2 or 3.")
    total_particle_number: int = Field(..., gt=0, description="Total number of particles in the simulation.")
    particle_shape_list: list[str] = Field(..., min_length=1, description="List of colloid shapes, e.g. ['sphere', 'capsule'].")
    ensemble: str = Field(..., description="Thermodynamic ensemble, either NVT or NPT.")
    working_dir: str = Field(..., description="Directory where simulation_problem.json is written.")


class PlanSimulationRunsInput(BaseModel):
    baseline_parameters: dict[str, Any] = Field(..., description="Baseline workflow parameters and optional dot-path overrides.")
    tunable_parameters: dict[str, list[Any]] = Field(..., description="Dot-path parameter sweeps, each mapped to a list of values.")
    working_dir: str = Field(..., description="Directory containing simulation_problem.json and output plan files.")


class ExecuteSimulationWorkflowInput(BaseModel):
    working_dir: str = Field(..., description="Directory containing simulation_plan.json.")
    continue_on_error: bool = Field(default=True, description="If true, continue remaining runs when one run fails.")


@mcp.tool()
def setup_simulation_problem_tool(params: SetupSimulationProblemInput) -> dict[str, Any]:
    """Create simulation_problem.json for a workflow directory."""
    resolved_dir = _normalize_working_dir(params.working_dir)
    result = setup_simulation_problem(
        dimension=params.dimension,
        total_particle_number=params.total_particle_number,
        particle_shape_list=params.particle_shape_list,
        ensemble=params.ensemble,
        working_dir=resolved_dir,
    )
    return {
        "ok": True,
        "working_dir": resolved_dir,
        "simulation_problem_path": str(Path(resolved_dir) / "simulation_problem.json"),
        "simulation_problem": result,
    }


@mcp.tool()
def plan_simulation_runs_tool(params: PlanSimulationRunsInput) -> dict[str, Any]:
    """Create simulation_baseline.json, run folders, and simulation_plan.json."""
    resolved_dir = _normalize_working_dir(params.working_dir)
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
        "n_runs": result["n_runs"],
        "simulation_runs": result["simulation_runs"],
    }


@mcp.tool()
def execute_simulation_workflow_tool(params: ExecuteSimulationWorkflowInput) -> dict[str, Any]:
    """Execute initialize/compress/sample/analyze for each planned run in simulation_plan.json."""
    resolved_dir = _normalize_working_dir(params.working_dir)
    result = execute_simulation_workflow(
        working_dir=resolved_dir,
        continue_on_error=params.continue_on_error,
    )
    return {
        "ok": True,
        "working_dir": resolved_dir,
        "status_path": result["status_path"],
        "n_runs": result["n_runs"],
        "n_success": result["n_success"],
        "n_failed": result["n_failed"],
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
