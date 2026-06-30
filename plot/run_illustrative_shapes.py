
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


def _find_project_root(start: Path) -> Path:
    current = start.resolve()
    while True:
        if (current / "environment.yml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (environment.yml not found).")
        current = current.parent


PROJECT_ROOT = _find_project_root(Path(__file__).resolve())
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from colpack.config_reading import get_allowed_shapes, get_shape_defaults  # noqa: E402
from colpack.workflow import execute_simulation_workflow, plan_simulaiton_runs, setup_simulation_problem  # noqa: E402


DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "plot" / "illustrative_data"
DEFAULT_TOTAL_PARTICLE_NUMBER = 30
DEFAULT_VOLUME_FRACTION = 0.5
DEFAULT_SAMPLE_STEPS = 10000
DEFAULT_TUNE_WARMUP_STEPS = 2000
DEFAULT_MOVE_TUNE_PERIOD = 50


def _has_hoomd() -> bool:
    return importlib.util.find_spec("hoomd") is not None


def _shape_baseline_parameters(dimension: int, shape: str) -> dict:
    baseline = {"volume_fraction": DEFAULT_VOLUME_FRACTION}
    for parameter_name, value in get_shape_defaults(dimension, shape).items():
        baseline[f"particle_specs.0.{parameter_name}"] = value
    return baseline


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)


def _apply_lightweight_runtime_overrides(run_dir: Path, sample_steps: int) -> None:
    config_path = run_dir / "simulation_config.json"
    simulation_config = _load_json(config_path)
    simulation_config["sampling_steps"] = sample_steps
    simulation_config["sample_steps"] = sample_steps
    simulation_config["tune_warmup_steps"] = DEFAULT_TUNE_WARMUP_STEPS
    simulation_config["move_tune_period"] = DEFAULT_MOVE_TUNE_PERIOD
    _write_json(config_path, simulation_config)


def _run_shape_case(
    *,
    dimension: int,
    shape: str,
    output_root: Path,
    total_particle_number: int,
    sample_steps: int,
    execute: bool,
) -> dict:
    working_dir = output_root / f"{dimension}d_nvt_{shape}"
    shutil.rmtree(working_dir, ignore_errors=True)
    working_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== illustrative case: {dimension}d {shape} ===")
    print(f"working_dir: {working_dir}")

    with patch("colpack.workflow.resolve_working_dir_from_setup", return_value=str(working_dir)):
        problem = setup_simulation_problem(
            dimension=dimension,
            total_particle_number=total_particle_number,
            particle_shape_list=[shape],
            ensemble="NVT",
        )

    planning = plan_simulaiton_runs(
        baseline_parameters=_shape_baseline_parameters(dimension, shape),
        tunable_parameters={"volume_fraction": [DEFAULT_VOLUME_FRACTION]},
        working_dir=problem["working_dir"],
    )

    for run in planning["simulation_runs"]:
        _apply_lightweight_runtime_overrides(Path(run["run_dir"]), sample_steps=sample_steps)

    summary = {
        "shape": shape,
        "dimension": dimension,
        "total_particle_number": total_particle_number,
        "working_dir": problem["working_dir"],
        "planning_path": planning["planning_path"],
        "n_runs": planning["n_runs"],
        "executed": False,
    }

    if execute:
        execution = execute_simulation_workflow(working_dir=problem["working_dir"], continue_on_error=True)
        summary["executed"] = True
        summary["execution"] = execution
        print(
            "execution summary:",
            {
                "n_runs": execution.get("n_runs"),
                "n_success": execution.get("n_success"),
                "n_failed": execution.get("n_failed"),
                "already_running": execution.get("already_running", False),
            },
        )
    else:
        print("planning only; skipped execute_simulation_workflow")

    return summary


def _run_dimension_cases(
    *,
    dimension: int,
    output_root: Path,
    total_particle_number: int,
    sample_steps: int,
    execute: bool,
) -> list[dict]:
    shapes = sorted(get_allowed_shapes(dimension))
    dimension_root = output_root / f"{dimension}d_building_blocks"
    dimension_root.mkdir(parents=True, exist_ok=True)
    results = []
    for shape in shapes:
        results.append(
            _run_shape_case(
                dimension=dimension,
                shape=shape,
                output_root=dimension_root,
                total_particle_number=total_particle_number,
                sample_steps=sample_steps,
                execute=execute,
            )
        )
    return results


def building_block_particles_2d(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> list[dict]:
    """Run small multi-particle NVT illustrative cases for all supported 2D shapes."""

    return _run_dimension_cases(
        dimension=2,
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def building_block_particles_3d(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> list[dict]:
    """Run small multi-particle NVT illustrative cases for all supported 3D shapes."""

    return _run_dimension_cases(
        dimension=3,
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build illustrative small multi-particle ColPack workflow cases.")
    parser.add_argument(
        "--dimensions",
        nargs="+",
        choices=["2", "3", "2d", "3d", "all"],
        default=["all"],
        help="Which illustrative suites to run.",
    )
    parser.add_argument(
        "--total-particle-number",
        type=int,
        default=DEFAULT_TOTAL_PARTICLE_NUMBER,
        help="Total particle count used for each illustrative case.",
    )
    parser.add_argument(
        "--sample-steps",
        type=int,
        default=DEFAULT_SAMPLE_STEPS,
        help="Sampling steps written into each generated run config.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory for generated illustrative workflow cases.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Create setup and plan outputs without executing the workflow.",
    )
    return parser.parse_args()


def _resolve_dimensions(raw_dimensions: list[str]) -> list[int]:
    normalized = {item.lower() for item in raw_dimensions}
    if "all" in normalized:
        return [2, 3]

    resolved = []
    if "2" in normalized or "2d" in normalized:
        resolved.append(2)
    if "3" in normalized or "3d" in normalized:
        resolved.append(3)
    return resolved


def main() -> None:
    args = _parse_args()
    dimensions = _resolve_dimensions(args.dimensions)
    if not dimensions:
        raise ValueError("No valid dimensions were selected.")
    if args.total_particle_number <= 0:
        raise ValueError("--total-particle-number must be positive.")

    execute = not args.plan_only
    if execute and not _has_hoomd():
        print("HOOMD is not installed; switching to plan-only mode.")
        execute = False

    all_results = []
    for dimension in dimensions:
        if dimension == 2:
            all_results.extend(
                building_block_particles_2d(
                    args.output_root,
                    args.total_particle_number,
                    args.sample_steps,
                    execute,
                )
            )
        elif dimension == 3:
            all_results.extend(
                building_block_particles_3d(
                    args.output_root,
                    args.total_particle_number,
                    args.sample_steps,
                    execute,
                )
            )

    summary_path = args.output_root / "illustrative_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(summary_path, all_results)
    print(f"\nSaved illustrative summary to {summary_path}")


if __name__ == "__main__":
    main()
