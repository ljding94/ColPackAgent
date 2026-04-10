from pathlib import Path
import importlib.util
import math
import json
import shutil
from colpack.visualize_ovito import visualize_gsd


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
    summary = compress_system(run_dir=str(run_dir))

    visualize_gsd(
        gsd_path=run_dir / "compress.gsd",
        output_path=run_dir / "compress_render.png",
        frame_index=-1,
        preview=False,
        debug=False,
    )

    assert (run_dir / "simulation_config_initial.json").exists()
    assert (run_dir / "compress.gsd").exists()
    assert (run_dir / "simulation_config_compress.json").exists()
    assert (run_dir / "compress_render.png").exists()

    with (run_dir / "simulation_config_compress.json").open("r", encoding="utf-8") as f:
        compress_config = json.load(f)

    assert summary["ensemble"] == ensemble
    assert summary["compress_gsd_path"].endswith("compress.gsd")
    assert compress_config["compress_gsd_path"].endswith("compress.gsd")
    if ensemble == "NVT":
        assert math.isclose(float(summary["final_volume_fraction"]), float(target_volume_fraction), rel_tol=1e-6, abs_tol=1e-8)
    else:
        assert float(summary["final_volume_fraction"]) > 0
        assert math.isclose(float(summary["target_pressure"]), float(target_pressure), rel_tol=1e-6, abs_tol=1e-8)


def main():
    if not _has_hoomd():
        print("Skipping test_compress_2d.py: 'hoomd' is not installed in the current Python environment.")
        return

    print("testing compression of 2d systems...\n")

    test_run(
        total_particle_number=100,
        particle_shape_list=["disk"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
        },
        output_subdir="2d_disk",
        seed=42,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_compress_2d_disk: OK\n")

    test_run(
        total_particle_number=50,
        particle_shape_list=["disk", "disk"],
        baseline_parameters={
            "particle_specs.0.diameter": 2.0,
            "particle_specs.1.diameter": 1.0,
            "particle_specs.1.relative_volume_fraction": 1.0,
        },
        output_subdir="2d_disk_disk",
        seed=42,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_compress_2d_disk_disk: OK\n")

    test_run(
        total_particle_number=30,
        particle_shape_list=["ellipse", "ellipse"],
        baseline_parameters={
            "particle_specs.0.a": 1.0,
            "particle_specs.0.b": 0.8,
            "particle_specs.1.a": 1.0,
            "particle_specs.1.b": 0.4,
            "particle_specs.1.relative_volume_fraction": 0.5,
        },
        output_subdir="2d_ellipse_ellipse",
        seed=42,
        ensemble="NVT",
        target_volume_fraction=0.25,
    )
    print("test_compress_2d_ellipse_ellipse: OK\n")

    test_run(
        total_particle_number=30,
        particle_shape_list=["disk", "ellipse"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.2,
            "particle_specs.1.a": 1.0,
            "particle_specs.1.b": 0.6,
            "particle_specs.1.relative_volume_fraction": 0.5,
        },
        output_subdir="2d_disk_ellipse",
        seed=123,
        ensemble="NVT",
        target_volume_fraction=0.25,
    )
    print("test_compress_2d_disk_ellipse: OK\n")

    test_run(
        total_particle_number=30,
        particle_shape_list=["disk", "rectangle"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.length": 2.0,
            "particle_specs.1.width": 1.0,
            "particle_specs.1.relative_volume_fraction": 0.5,
        },
        output_subdir="2d_disk_rectangle",
        seed=321,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_compress_2d_disk_rectangle: OK\n")

    test_run(
        total_particle_number=50,
        particle_shape_list=["capsule"],
        baseline_parameters={
            "particle_specs.0.length": 2.0,
            "particle_specs.0.diameter": 1.0,
        },
        output_subdir="2d_capsule",
        seed=456,
        ensemble="NVT",
        target_volume_fraction=0.25,
    )
    print("test_compress_2d_capsule: OK\n")

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
    print("test_compress_2d_disk_capsule: OK\n")

    test_run(
        total_particle_number=30,
        particle_shape_list=["disk", "triangle"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.side": 1.5,
            "particle_specs.1.relative_volume_fraction": 1.0,
        },
        output_subdir="2d_disk_triangle",
        seed=654,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_compress_2d_disk_triangle: OK\n")

    test_run(
        total_particle_number=40,
        particle_shape_list=["disk", "rectangle", "capsule", "triangle"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.5,
            "particle_specs.1.length": 2.0,
            "particle_specs.1.width": 1.0,
            "particle_specs.2.length": 2.0,
            "particle_specs.2.diameter": 0.6,
            "particle_specs.3.side": 1.5,
            "particle_specs.1.relative_volume_fraction": 1.0,
            "particle_specs.2.relative_volume_fraction": 1.0,
            "particle_specs.3.relative_volume_fraction": 1.0,
        },
        output_subdir="2d_multi_shapes",
        seed=789,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_compress_2d_multi_shapes: OK\n")

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
    print("test_compress_2d_npt: OK\n")


if __name__ == "__main__":
    main()
