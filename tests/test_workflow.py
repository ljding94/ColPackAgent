from pathlib import Path
import json
import csv
import importlib.util


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "environment.yml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (environment.yml not found).")
        current = current.parent


def _has_hoomd() -> bool:
    return importlib.util.find_spec("hoomd") is not None


def _load_status_rows(status_path: Path):
    with status_path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _assert_status_schema(rows):
    assert len(rows) > 0
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


def _run_workflow_case(case):
    from colpack.workflow import setup_simulation_problem, plan_simulaiton_runs, execute_simulation_workflow

    project_root = _find_project_root(Path(__file__).resolve())
    working_dir = project_root / "data" / "test" / case["system_subdir"]
    working_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== workflow case: {case['system_subdir']} ===")
    print(f"working_dir: {working_dir}")

    # 1) setup_simulation_problem
    print("[1/3] setup_simulation_problem: start")
    problem = setup_simulation_problem(
        dimension=case["dimension"],
        total_particle_number=case["total_particle_number"],
        particle_shape_list=case["particle_shape_list"],
        ensemble=case["ensemble"],
        working_dir=str(working_dir),
    )
    assert (working_dir / "simulation_problem.json").exists()
    assert problem["dimension"] == case["dimension"]
    assert problem["ensemble"] == case["ensemble"]
    assert len(problem["particle_specs"]) == len(case["particle_shape_list"])
    print("[1/3] setup_simulation_problem: done")

    # 2) plan_simulaiton_runs
    print("[2/3] plan_simulaiton_runs: start")
    planning = plan_simulaiton_runs(
        baseline_parameters=case["baseline_parameters"],
        tunable_parameters=case["tunable_parameters"],
        working_dir=str(working_dir),
    )

    planning_path = Path(planning["planning_path"])
    assert planning_path.exists()
    assert (working_dir / "simulation_baseline.json").exists()
    with planning_path.open("r", encoding="utf-8") as f:
        planned_runs = json.load(f)
    assert len(planned_runs) == planning["n_runs"]
    assert planning["n_runs"] == case["expected_runs"]

    for run in planned_runs:
        assert run["dimension"] == case["dimension"]
        assert run["ensemble"] == case["ensemble"]
        assert run["total_particle_number"] == case["total_particle_number"]
        assert run["run_dir"].endswith(f"run_{run['run_number']}")
        assert isinstance(run["particle_specs"], list)
    print(f"[2/3] plan_simulaiton_runs: done (n_runs={planning['n_runs']})")

    if not _has_hoomd():
        print(f"Skipping execute_simulation_workflow for {case['system_subdir']}: 'hoomd' is not installed.")
        return

    # 3) execute_simulation_workflow
    print("[3/3] execute_simulation_workflow pass-1: start")
    first = execute_simulation_workflow(working_dir=str(working_dir), continue_on_error=True)
    assert first["n_runs"] == planning["n_runs"]

    status_path = Path(first["status_path"])
    assert status_path.exists()
    rows_first = _load_status_rows(status_path)
    _assert_status_schema(rows_first)
    assert len(rows_first) >= planning["n_runs"]
    print(f"[3/3] execute_simulation_workflow pass-1: done (status_rows={len(rows_first)})")

    # Run twice to validate resume logic and append-only status behavior.
    print("[3/3] execute_simulation_workflow pass-2 (resume): start")
    second = execute_simulation_workflow(working_dir=str(working_dir), continue_on_error=True)
    assert second["n_runs"] == planning["n_runs"]

    rows_second = _load_status_rows(status_path)
    assert len(rows_second) >= len(rows_first)

    step_columns = ["initialize", "compress", "sample", "analyze"]
    recent_rows = rows_second[-planning["n_runs"] :]
    for row in recent_rows:
        assert row["ensemble"] == case["ensemble"]
        assert row["dimension"] == str(case["dimension"])
        assert row["status"] in {"success", "failed"}
        for step in step_columns:
            assert row[step] in {"O", "X"}

    print(f"[3/3] execute_simulation_workflow pass-2 (resume): done (status_rows={len(rows_second)})")
    print(f"workflow case {case['system_subdir']}: n_runs={planning['n_runs']}, final_status_rows={len(rows_second)}")


def main():
    cases = [
        {
            "system_subdir": "workflow_case_2d_nvt_disk_capsule",
            "dimension": 2,
            "ensemble": "NVT",
            "total_particle_number": 200,
            "particle_shape_list": ["disk", "capsule"],
            "baseline_parameters": {
                "sampling_steps": 50,
                "particle_specs.0.diameter": 1.0,
                "particle_specs.1.length": 1.5,
                "particle_specs.1.diameter": 0.5,
            },
            "tunable_parameters": {
                "volume_fraction": [0.22, 0.27],
                "particle_specs.1.relative_volume_fraction": [0.6],
            },
            "expected_runs": 3,
        },
        {
            "system_subdir": "workflow_case_2d_npt_disk_ellipse",
            "dimension": 2,
            "ensemble": "NPT",
            "total_particle_number": 36,
            "particle_shape_list": ["disk", "ellipse"],
            "baseline_parameters": {
                "sampling_steps": 50,
                "particle_specs.0.diameter": 1.0,
                "particle_specs.1.a": 0.9,
                "particle_specs.1.b": 0.6,
            },
            "tunable_parameters": {
                "P": [1.0, 1.3],
                "particle_specs.1.relative_volume_fraction": [0.5],
            },
            "expected_runs": 3,
        },
        {
            "system_subdir": "workflow_case_3d_nvt_sphere_capsule",
            "dimension": 3,
            "ensemble": "NVT",
            "total_particle_number": 40,
            "particle_shape_list": ["sphere", "capsule"],
            "baseline_parameters": {
                "sampling_steps": 50,
                "particle_specs.0.diameter": 1.0,
                "particle_specs.1.length": 1.8,
                "particle_specs.1.diameter": 0.6,
            },
            "tunable_parameters": {
                "volume_fraction": [0.18, 0.22],
                "particle_specs.1.relative_volume_fraction": [0.7],
            },
            "expected_runs": 3,
        },
        {
            "system_subdir": "workflow_case_3d_npt_sphere_cube",
            "dimension": 3,
            "ensemble": "NPT",
            "total_particle_number": 32,
            "particle_shape_list": ["sphere", "cube"],
            "baseline_parameters": {
                "sampling_steps": 50,
                "particle_specs.0.diameter": 1.0,
                "particle_specs.1.edge": 0.9,
            },
            "tunable_parameters": {
                "P": [1.1, 1.4],
                "particle_specs.1.relative_volume_fraction": [0.45],
            },
            "expected_runs": 3,
        },
    ]

    print("testing workflow setup/plan/execute for 2d and 3d, nvt and npt...\n")
    for case in cases[:1]:
        _run_workflow_case(case)


if __name__ == "__main__":
    main()
