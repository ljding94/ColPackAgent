from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from unittest.mock import patch

from run_illustrative_shapes import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SAMPLE_STEPS,
    DEFAULT_TOTAL_PARTICLE_NUMBER,
    _apply_lightweight_runtime_overrides,
    _has_hoomd,
    _write_json,
)

from colpack.workflow import execute_simulation_workflow, plan_simulaiton_runs, setup_simulation_problem


def _run_tunable_case(
    *,
    case_name: str,
    dimension: int,
    ensemble: str,
    particle_shape_list: list[str],
    baseline_parameters: dict,
    tunable_parameters: dict,
    output_root: Path,
    total_particle_number: int,
    sample_steps: int,
    execute: bool,
) -> dict:
    working_dir = output_root / case_name
    shutil.rmtree(working_dir, ignore_errors=True)
    working_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== illustrative tunable case: {case_name} ===")
    print(f"working_dir: {working_dir}")

    with patch("colpack.workflow.resolve_working_dir_from_setup", return_value=str(working_dir)):
        problem = setup_simulation_problem(
            dimension=dimension,
            total_particle_number=total_particle_number,
            particle_shape_list=particle_shape_list,
            ensemble=ensemble,
        )

    planning = plan_simulaiton_runs(
        baseline_parameters=baseline_parameters,
        tunable_parameters=tunable_parameters,
        working_dir=problem["working_dir"],
    )

    for run in planning["simulation_runs"]:
        _apply_lightweight_runtime_overrides(Path(run["run_dir"]), sample_steps=sample_steps)

    summary = {
        "case_name": case_name,
        "dimension": dimension,
        "ensemble": ensemble,
        "particle_shape_list": list(particle_shape_list),
        "total_particle_number": total_particle_number,
        "working_dir": problem["working_dir"],
        "baseline_path": planning["baseline_path"],
        "planning_path": planning["planning_path"],
        "tunable_parameters": tunable_parameters,
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

    _write_json(working_dir / "illustrative_case_summary.json", summary)
    return summary


def tune_volume_fraction(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """Generate a 2D triangle sweep over system volume fraction."""

    return _run_tunable_case(
        case_name="tunable_volume_fraction_triangle",
        dimension=2,
        ensemble="NVT",
        particle_shape_list=["triangle"],
        baseline_parameters={
            "particle_specs.0.side": 1.0,
        },
        tunable_parameters={
            "volume_fraction": [0.2, 0.6],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def tune_relative_volume_fraction(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """Generate a 2D bidisperse disk sweep over the second species volume fraction."""

    return _run_tunable_case(
        case_name="tunable_relative_volume_fraction_disks",
        dimension=2,
        ensemble="NVT",
        particle_shape_list=["disk", "disk"],
        baseline_parameters={
            "volume_fraction": 0.6,
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.diameter": 0.5,
            "particle_specs.0.relative_volume_fraction": 1.0,
            "particle_specs.1.relative_volume_fraction": 0.5,
        },
        tunable_parameters={
            "particle_specs.1.relative_volume_fraction": [0.5, 2.0],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def tune_pressure(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """Generate a 2D capsule NPT sweep over pressure."""
    sample_steps = 100000
    return _run_tunable_case(
        case_name="tunable_pressure_square_npt",
        dimension=2,
        ensemble="NPT",
        particle_shape_list=["square"],
        baseline_parameters={
            "particle_specs.0.side": 1.0,
        },
        tunable_parameters={
            "P": [1.0, 10.0],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def tune_mix_1shapes(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """Generate a 2D same-shape disk mixture sweep over the second disk diameter."""

    return _run_tunable_case(
        case_name="tunable_mix_capsul_sizes",
        dimension=2,
        ensemble="NVT",
        particle_shape_list=["capsule", "capsule"],
        baseline_parameters={
            "volume_fraction": 0.5,
            "particle_specs.0.diameter": 1.0,
            "particle_specs.0.length": 3.0,
            "particle_specs.1.diameter": 1.0,
            "particle_specs.1.length": 1.0,
            "particle_specs.0.relative_volume_fraction": 1.0,
            "particle_specs.1.relative_volume_fraction": 1.0,
        },
        tunable_parameters={
            "particle_specs.1.diameter": [1.0],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def tune_mix_2shapes(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """Generate a 2D disk-capsule mixture sweep over capsule composition."""

    return _run_tunable_case(
        case_name="tunable_mix_square_capsule",
        dimension=2,
        ensemble="NVT",
        particle_shape_list=["square", "capsule"],
        baseline_parameters={
            "volume_fraction": 0.5,
            "particle_specs.0.side": 1.0,
            "particle_specs.1.length": 2.5,
            "particle_specs.1.diameter": 1.0,
            "particle_specs.0.relative_volume_fraction": 1.0,
            "particle_specs.1.relative_volume_fraction": 2.0,
        },
        tunable_parameters={
            "particle_specs.1.relative_volume_fraction": [2.0],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def tune_shape(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """Generate a 2D rectangle sweep over aspect-ratio-like length changes."""

    return _run_tunable_case(
        case_name="tunable_rectangle_aspect_ratio",
        dimension=2,
        ensemble="NVT",
        particle_shape_list=["rectangle"],
        baseline_parameters={
            "volume_fraction": 0.5,
            "particle_specs.0.length": 2.0,
            "particle_specs.0.width": 1.0,
        },
        tunable_parameters={
            "particle_specs.0.length": [1.5, 4.0],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def more_mixture_3d(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """
    3d mixture of many shapes
    """
    total_particle_number = 100

    return _run_tunable_case(
        case_name="tunable_multishape_mixture_3d_npt",
        dimension=3,
        ensemble="NPT",
        particle_shape_list=["sphere", "capsule", "tetrahedron", "cube"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.length": 2.0,
            "particle_specs.1.diameter": 0.6,
            "particle_specs.2.side": 1.2,
            "particle_specs.3.side": 1.0,
            "particle_specs.1.relative_volume_fraction": 1.0,
            "particle_specs.2.relative_volume_fraction": 1.0,
            "particle_specs.3.relative_volume_fraction": 1.0,
        },
        tunable_parameters={
            "P": [10.0],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


def more_mixture_2d(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> dict:
    """Generate a 2D NPT multishape mixture pressure sweep."""
    total_particle_number = 100
    return _run_tunable_case(
        case_name="tunable_multishape_mixture_2d_npt",
        dimension=2,
        ensemble="NPT",
        particle_shape_list=["disk", "capsule", "triangle", "rectangle"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.length": 1.5,
            "particle_specs.1.diameter": 0.5,
            "particle_specs.2.side": 1.0,
            "particle_specs.3.width": 0.5,
            "particle_specs.3.length": 2.5,
            "particle_specs.1.relative_volume_fraction": 1.0,
            "particle_specs.2.relative_volume_fraction": 1.0,
            "particle_specs.3.relative_volume_fraction": 1.0,
        },
        tunable_parameters={
            "P": [10.0],
        },
        output_root=(output_root or DEFAULT_OUTPUT_ROOT),
        total_particle_number=total_particle_number,
        sample_steps=sample_steps,
        execute=execute,
    )


CASE_RUNNERS = {
    "volume_fraction": tune_volume_fraction,
    "relative_volume_fraction": tune_relative_volume_fraction,
    "pressure": tune_pressure,
    "mix_1shapes": tune_mix_1shapes,
    "mix_2shapes": tune_mix_2shapes,
    "shape": tune_shape,
    "more_mixture_2d": more_mixture_2d,
    "more_mixture_3d": more_mixture_3d,
}


def run_all_tunable_cases(
    output_root: Path | None = None,
    total_particle_number: int = DEFAULT_TOTAL_PARTICLE_NUMBER,
    sample_steps: int = DEFAULT_SAMPLE_STEPS,
    execute: bool = True,
) -> list[dict]:
    """Run every illustrative tunable case and return the collected summaries."""

    results = []
    for runner in CASE_RUNNERS.values():
        results.append(
            runner(
                output_root=output_root,
                total_particle_number=total_particle_number,
                sample_steps=sample_steps,
                execute=execute,
            )
        )
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build illustrative tunable ColPack workflow cases.")
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=["all", *CASE_RUNNERS.keys()],
        default=["all"],
        help="Which illustrative tunable cases to run.",
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


def _resolve_case_names(raw_cases: list[str]) -> list[str]:
    normalized = [item.lower() for item in raw_cases]
    if "all" in normalized:
        return list(CASE_RUNNERS.keys())
    return normalized


def main() -> None:
    args = _parse_args()
    case_names = _resolve_case_names(args.cases)
    if not case_names:
        raise ValueError("No valid cases were selected.")
    if args.total_particle_number <= 0:
        raise ValueError("--total-particle-number must be positive.")

    execute = not args.plan_only
    if execute and not _has_hoomd():
        print("HOOMD is not installed; switching to plan-only mode.")
        execute = False

    test_run = ["more_mixture_2d", "more_mixture_3d"]
    all_results = []
    print(f"Selected cases to run: {case_names}\n")
    for case_name in case_names:
        if case_name not in test_run:
            continue
        all_results.append(
            CASE_RUNNERS[case_name](
                output_root=args.output_root,
                total_particle_number=args.total_particle_number,
                sample_steps=args.sample_steps,
                execute=execute,
            )
        )

    summary_path = args.output_root / "illustrative_tunable_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(summary_path, all_results)
    print(f"\nSaved illustrative tunable summary to {summary_path}")


if __name__ == "__main__":
    main()
