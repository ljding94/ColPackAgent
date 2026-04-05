from pathlib import Path
import importlib.util
import json
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

    project_root = _find_project_root(Path(__file__).resolve())
    working_dir = project_root / "data" / "test" / output_subdir
    working_dir.mkdir(parents=True, exist_ok=True)

    setup_simulation_problem(
        dimension=3,
        total_particle_number=total_particle_number,
        particle_shape_list=particle_shape_list,
        ensemble=str(ensemble),
        working_dir=str(working_dir),
    )

    baseline = dict(baseline_parameters)
    baseline["seed"] = int(seed)

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

    visualize_gsd(
        gsd_path=run_dir / "sample_final.gsd",
        output_path=run_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
        debug=False,
    )


def main():
    if not _has_hoomd():
        print("Skipping test_sample_3d.py: 'hoomd' is not installed in the current Python environment.")
        return

    print("testing sample of 3d systems...\n")

    test_run(
        total_particle_number=100,
        particle_shape_list=["sphere"],
        baseline_parameters={"particle_specs.0.diameter": 1.0},
        output_subdir="3d_sphere",
        seed=42,
        ensemble="NVT",
        target_volume_fraction=0.30,
    )
    print("test_sample_3d_sphere: OK\n")

    test_run(
        total_particle_number=50,
        particle_shape_list=["sphere", "capsule"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.length": 2.0,
            "particle_specs.1.diameter": 0.6,
            "particle_specs.1.relative_volume_fraction": 0.8,
        },
        output_subdir="3d_sphere_capsule",
        seed=303,
        ensemble="NVT",
        target_volume_fraction=0.28,
    )
    print("test_sample_3d_sphere_capsule: OK\n")

    test_run(
        total_particle_number=50,
        particle_shape_list=["sphere", "capsule"],
        baseline_parameters={
            "particle_specs.0.diameter": 1.0,
            "particle_specs.1.length": 2.0,
            "particle_specs.1.diameter": 0.6,
            "particle_specs.1.relative_volume_fraction": 0.8,
            "P": 1.5,
        },
        output_subdir="3d_sphere_capsule_npt",
        seed=912,
        ensemble="NPT",
        target_pressure=1.5,
    )
    print("test_sample_3d_npt: OK\n")


if __name__ == "__main__":
    main()
