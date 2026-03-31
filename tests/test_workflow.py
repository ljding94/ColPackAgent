from pathlib import Path
import json
import csv
from colpack.workflow import setup_simulation_problem, plan_simulaiton_runs, excute_simulation_workflow


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "environment.yml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (environment.yml not found).")
        current = current.parent


def test_setup_problem(system_subdir, dimension, total_particle_number, particle_shape_list, ensemble):
    project_root = _find_project_root(Path(__file__).resolve())
    working_dir = project_root / "data" / "test" / system_subdir
    setup_simulation_problem(dimension=dimension, total_particle_number=total_particle_number, particle_shape_list=particle_shape_list, ensemble=ensemble, working_dir=str(working_dir))

    print(f"test_run: working_dir: {working_dir}")


def test_plan_simulation(system_subdir, dimension, total_particle_number, particle_shape_list, ensemble):
    project_root = _find_project_root(Path(__file__).resolve())
    working_dir = project_root / "data" / "test" / system_subdir
    working_dir.mkdir(parents=True, exist_ok=True)

    setup_simulation_problem(
        dimension=dimension,
        total_particle_number=total_particle_number,
        particle_shape_list=particle_shape_list,
        ensemble=ensemble,
        working_dir=str(working_dir),
    )

    # baseline_parameters = dict(base_problem)
    baseline_parameters = {}
    print(f"Baseline parameters: {baseline_parameters}")

    if ensemble == "NVT":
        tunable_parameters = {
            "volume_fraction": [0.20, 0.30],
            "particle_specs.1.relative_volume_fraction": [0.2, 0.4],
        }
        baseline_parameters["particle_specs.0.diameter"] = 2.0
        expected_runs = 4
    else:
        tunable_parameters = {
            "P": [1.0, 2.0],
            "particle_specs.1.relative_volume_fraction": [0.2, 0.4],
        }
        expected_runs = 4

    planning = plan_simulaiton_runs(
        baseline_parameters=baseline_parameters,
        tunable_parameters=tunable_parameters,
        working_dir=working_dir,
    )

    planning_path = Path(planning["planning_path"])
    assert planning_path.exists()
    assert planning["n_runs"] == expected_runs

    with planning_path.open("r", encoding="utf-8") as f:
        planned_runs = json.load(f)

    assert isinstance(planned_runs, list)
    assert len(planned_runs) == expected_runs

    for run in planned_runs:
        # Planned run should have the same overall schema as simulation_problem.
        assert run["dimension"] == dimension
        assert run["ensemble"] == ensemble
        assert run["total_particle_number"] == total_particle_number
        assert "run_number" in run
        assert "output_dir" in run
        assert run["output_dir"].endswith(f"run_{run['run_number']}")
        assert "particle_specs" in run
        assert isinstance(run["particle_specs"], list)

    print(f"test_plan_simulation: planned {len(planned_runs)} runs in {planning_path}")


def test_execute_simulation_workflow(system_subdir, dimension, total_particle_number, particle_shape_list, ensemble):
    project_root = _find_project_root(Path(__file__).resolve())
    working_dir = project_root / "data" / "test" / system_subdir
    working_dir.mkdir(parents=True, exist_ok=True)

    setup_simulation_problem(
        dimension=dimension,
        total_particle_number=total_particle_number,
        particle_shape_list=particle_shape_list,
        ensemble=ensemble,
        working_dir=str(working_dir),
    )

    # Keep this as a lightweight status-contract test.
    baseline_parameters = {"sampling_steps": 50}
    if ensemble == "NVT":
        tunable_parameters = {"volume_fraction": [0.20, 0.30]}
    else:
        tunable_parameters = {"P": [1.0]}

    planning = plan_simulaiton_runs(
        baseline_parameters=baseline_parameters,
        tunable_parameters=tunable_parameters,
        working_dir=working_dir,
    )

    result = excute_simulation_workflow(working_dir=str(working_dir), continue_on_error=True)
    status_path = Path(result["status_path"])

    assert status_path.exists()
    assert status_path.name == "workflow_status.csv"
    assert result["n_runs"] == planning["n_runs"]

    with status_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == planning["n_runs"]

    required_columns = {
        "run_number",
        "dimension",
        "total_particle_number",
        "ensemble",
        "initialize",
        "compress",
        "sample",
        "analyze",
        "status",
        "started_at",
        "finished_at",
        "output_dir",
        "error",
    }
    assert required_columns.issubset(set(rows[0].keys()))

    step_columns = ["initialize", "compress", "sample", "analyze"]
    for row in rows:
        assert row["ensemble"] == ensemble
        assert row["dimension"] == str(dimension)
        assert row["status"] in {"success", "failed"}
        for step in step_columns:
            assert row[step] in {"O", "X"}

    print(f"test_execute_simulation_workflow: wrote status file {status_path} with {len(rows)} rows")


def main():
    print("testing sample of 3d systems...\n")
    #test_setup_problem(system_subdir="workflow_0", dimension=3, total_particle_number=100, particle_shape_list=["sphere", "capsule"], ensemble="NVT")
    #test_setup_problem(system_subdir="workflow_1", dimension=2, total_particle_number=100, particle_shape_list=["disk", "ellipse"], ensemble="NPT")
    print("testing simulation planning...\n")
    #test_plan_simulation(system_subdir="workflow_plan_nvt", dimension=3, total_particle_number=120, particle_shape_list=["sphere", "capsule"], ensemble="NVT")
    #test_plan_simulation(system_subdir="workflow_plan_npt", dimension=2, total_particle_number=80, particle_shape_list=["disk", "ellipse"], ensemble="NPT")

    print("testing workflow execution status tracking...\n")
    test_execute_simulation_workflow(system_subdir="workflow_execute_nvt", dimension=3, total_particle_number=60, particle_shape_list=["sphere", "capsule"], ensemble="NVT")


if __name__ == "__main__":
    main()
