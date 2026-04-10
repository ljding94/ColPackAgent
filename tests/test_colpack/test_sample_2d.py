from pathlib import Path
import importlib.util
import json
import shutil


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "environment.yml").exists() or (current / "src" / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (environment.yml or src/pyproject.toml not found).")
        current = current.parent


def _has_hoomd() -> bool:
    return importlib.util.find_spec("hoomd") is not None


def _prepare_single_run_config(output_subdir, total_particle_number, particle_shape_list, baseline_parameters, seed, ensemble="NVT", target_volume_fraction=None, target_pressure=None):
    from colpack.workflow import setup_simulation_problem, plan_simulaiton_runs
    from unittest.mock import patch

    project_root = _find_project_root(Path(__file__).resolve())
    case_root = project_root / "data" / "test" / output_subdir
    shutil.rmtree(case_root, ignore_errors=True)
    case_root.mkdir(parents=True, exist_ok=True)

    with patch("colpack.workflow.resolve_working_dir_from_setup", return_value=str(case_root)):
        problem = setup_simulation_problem(
            dimension=2,
            total_particle_number=total_particle_number,
            particle_shape_list=particle_shape_list,
            ensemble=str(ensemble),
        )
    working_dir = Path(problem["working_dir"])

    baseline = dict(baseline_parameters)

    if ensemble == "NVT":
        if target_volume_fraction is None:
            raise ValueError("target_volume_fraction must be provided for NVT tests.")
        tunable_parameters = {"volume_fraction": [float(target_volume_fraction)]}
    elif ensemble == "NPT":
        if target_pressure is None:
            raise ValueError("target_pressure must be provided for NPT tests.")
        tunable_parameters = {"P": [float(target_pressure)]}
    else:
        raise ValueError("ensemble must be either 'NVT' or 'NPT'.")

    planning = plan_simulaiton_runs(
        baseline_parameters=baseline,
        tunable_parameters=tunable_parameters,
        working_dir=str(working_dir),
    )

    return Path(planning["simulation_runs"][0]["run_dir"])


def test_run(total_particle_number, particle_shape_list, baseline_parameters, output_subdir, seed, ensemble="NVT", target_volume_fraction=None, target_pressure=None):
    from colpack.initialize import create_initial_config
    from colpack.compress import compress_system
    from colpack.sample import sample_system

    run_dir = _prepare_single_run_config(
        output_subdir=output_subdir,
        total_particle_number=total_particle_number,
        particle_shape_list=particle_shape_list,
        baseline_parameters=baseline_parameters,
        seed=seed,
        ensemble=ensemble,
        target_volume_fraction=target_volume_fraction,
        target_pressure=target_pressure,
    )

    create_initial_config(run_dir=str(run_dir))
    compress_system(run_dir=str(run_dir))
    summary = sample_system(run_dir=str(run_dir))

    assert (run_dir / "simulation_config_sample.json").exists()
    assert (run_dir / "sample_trajectory.gsd").exists()
    assert (run_dir / "sample_final.gsd").exists()

    with (run_dir / "simulation_config_sample.json").open("r", encoding="utf-8") as f:
        sample_config = json.load(f)

    assert summary["ensemble"] == ensemble
    assert sample_config["sample_trajectory_path"].endswith("sample_trajectory.gsd")
    assert sample_config["sample_gsd_path"].endswith("sample_final.gsd")
    assert "sample_overlaps" in sample_config
    if ensemble == "NPT":
        assert float(sample_config["P"]) == float(target_pressure)


def test_get_sample_trajectory_trigger_period():
    from colpack.sample import _get_sample_trajectory_trigger_period

    cases = [
        (1, 1),
        (49, 1),
        (50, 1),
        (51, 2),
        (999, 20),
        (49999, 1000),
        (50000, 1000),
        (200000, 1000),
    ]

    for sample_steps, expected_period in cases:
        assert _get_sample_trajectory_trigger_period(sample_steps) == expected_period


def test_get_sample_trajectory_trigger_period_rejects_non_positive_steps():
    from colpack.sample import _get_sample_trajectory_trigger_period

    try:
        _get_sample_trajectory_trigger_period(0)
    except ValueError as exc:
        assert "sample_steps must be positive" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-positive sample_steps.")


def test_get_move_tune_period():
    from colpack.sample import _get_move_tune_period

    cases = [
        ((20000, 100, 10), 100),
        ((1000, 100, 10), 100),
        ((999, 100, 10), 100),
        ((501, 100, 10), 51),
        ((100, 100, 10), 10),
        ((99, 100, 10), 10),
        ((9, 100, 10), 1),
        ((100, 7, 10), 7),
    ]

    for args, expected_period in cases:
        assert _get_move_tune_period(*args) == expected_period


def test_get_move_tune_period_rejects_invalid_inputs():
    from colpack.sample import _get_move_tune_period

    invalid_cases = [
        (0, 100, 10, "sample_steps must be positive"),
        (100, 0, 10, "configured_period must be positive"),
        (100, 100, 0, "min_move_tune_updates must be positive"),
    ]

    for sample_steps, configured_period, min_move_tune_updates, expected_message in invalid_cases:
        try:
            _get_move_tune_period(sample_steps, configured_period, min_move_tune_updates)
        except ValueError as exc:
            assert expected_message in str(exc)
        else:
            raise AssertionError("Expected ValueError for invalid move tune period inputs.")


def test_get_npt_boxmc_trigger_period():
    from colpack.sample import _get_npt_boxmc_trigger_period

    cases = [
        ((20000, 10, 10), 10),
        ((1000, 10, 10), 10),
        ((99, 10, 10), 10),
        ((51, 10, 10), 6),
        ((50, 10, 10), 5),
        ((9, 10, 10), 1),
        ((100, 3, 10), 3),
    ]

    for args, expected_period in cases:
        assert _get_npt_boxmc_trigger_period(*args) == expected_period


def test_get_npt_boxmc_trigger_period_rejects_invalid_inputs():
    from colpack.sample import _get_npt_boxmc_trigger_period

    invalid_cases = [
        (0, 10, 10, "sample_steps must be positive"),
        (100, 0, 10, "configured_period must be positive"),
        (100, 10, 0, "min_npt_boxmc_updates must be positive"),
    ]

    for sample_steps, configured_period, min_npt_boxmc_updates, expected_message in invalid_cases:
        try:
            _get_npt_boxmc_trigger_period(sample_steps, configured_period, min_npt_boxmc_updates)
        except ValueError as exc:
            assert expected_message in str(exc)
        else:
            raise AssertionError("Expected ValueError for invalid NPT BoxMC trigger inputs.")


def main():
    if not _has_hoomd():
        print("Skipping test_sample_2d.py: 'hoomd' is not installed in the current Python environment.")
        return

    print("testing thermalization of 2d systems...\n")

    test_run(
        total_particle_number=100,
        particle_shape_list=["disk"],
        baseline_parameters={"particle_specs.0.diameter": 1.0},
        output_subdir="2d_disk",
        seed=42,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_sample_2d_disk: OK\n")

    test_run(
        total_particle_number=30,
        particle_shape_list=["disk", "capsule"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.length": 2.0,
            "particle_specs.1.diameter": 0.6,
            "particle_specs.1.relative_volume_fraction": 1.0,
        },
        output_subdir="2d_disk_capsule",
        seed=456,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_sample_2d_disk_capsule: OK\n")

    test_run(
        total_particle_number=40,
        particle_shape_list=["disk", "ellipse"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.a": 1.0,
            "particle_specs.1.b": 0.6,
            "particle_specs.1.relative_volume_fraction": 0.7,
            "P": 1.2,
        },
        output_subdir="2d_disk_ellipse_npt",
        seed=911,
        ensemble="NPT",
        target_pressure=1.2,
    )
    print("test_sample_2d_npt: OK\n")


if __name__ == "__main__":
    main()
