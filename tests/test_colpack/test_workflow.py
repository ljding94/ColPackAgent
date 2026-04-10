from pathlib import Path
import json
import csv
import shutil
import sys
import types
import importlib.util
from tempfile import TemporaryDirectory
from unittest.mock import patch


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
        "execution_state",
        "started_at",
        "finished_at",
        "output_dir",
        "error",
    }
    assert required_columns.issubset(set(rows[0].keys()))


def test_resolve_working_dir_from_setup_uses_default_template_and_collision_suffix() -> None:
    from colpack.workflow_helper import resolve_working_dir_from_setup

    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        (temp_root / "environment.yml").write_text("name: colpack-test\n", encoding="utf-8")
        base_dir = temp_root / "data" / "2d_npt_rectangle"
        base_dir.mkdir(parents=True, exist_ok=True)

        with patch("colpack.workflow_helper._find_project_root", return_value=temp_root):
            resolved = resolve_working_dir_from_setup(
                dimension=2,
                ensemble="NPT",
                particle_shape_list=["rectangle"],
            )

        assert resolved == str((temp_root / "data" / "2d_npt_rectangle_v2").resolve())


def test_setup_simulation_problem_resolves_default_working_dir_when_omitted() -> None:
    from colpack.workflow import setup_simulation_problem

    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        (temp_root / "environment.yml").write_text("name: colpack-test\n", encoding="utf-8")

        with patch("colpack.workflow_helper._find_project_root", return_value=temp_root):
            problem = setup_simulation_problem(
                dimension=2,
                total_particle_number=32,
                particle_shape_list=["disk", "capsule"],
                ensemble="NVT",
            )

        expected_dir = (temp_root / "data" / "2d_nvt_disk_capsule").resolve()
        assert problem["working_dir"] == str(expected_dir)
        assert (expected_dir / "simulation_problem.json").exists()


def test_plan_simulaiton_runs_appends_without_duplicate_tunable_values() -> None:
    from colpack.workflow import setup_simulation_problem, plan_simulaiton_runs

    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        (temp_root / "environment.yml").write_text("name: colpack-test\n", encoding="utf-8")
        case_dir = temp_root / "data" / "2d_nvt_disk"

        with patch("colpack.workflow_helper.resolve_working_dir_from_setup", return_value=str(case_dir)):
            problem = setup_simulation_problem(
                dimension=2,
                total_particle_number=24,
                particle_shape_list=["disk"],
                ensemble="NVT",
            )

        working_dir = Path(problem["working_dir"])
        status_path = working_dir / "workflow_status.csv"
        status_path.write_text(
            "run_number,dimension,total_particle_number,ensemble,initialize,compress,sample,analyze,status,execution_state,started_at,finished_at,output_dir,error\n"
            "0,2,24,NVT,O,O,O,O,success,finished,2026-01-01T00:00:00+00:00,2026-01-01T00:01:00+00:00,/tmp/run_0,\n",
            encoding="utf-8",
        )

        baseline = {
            "sampling_steps": 20,
            "particle_specs.0.diameter": 1.0,
        }

        first = plan_simulaiton_runs(
            baseline_parameters=baseline,
            tunable_parameters={"volume_fraction": [0.20, 0.25]},
            working_dir=str(working_dir),
        )
        assert first["n_runs"] == 2
        assert first["n_existing_runs"] == 0
        assert first["n_total_runs"] == 2

        second = plan_simulaiton_runs(
            baseline_parameters=baseline,
            tunable_parameters={"volume_fraction": [0.25, 0.30]},
            working_dir=str(working_dir),
        )
        # 0.25 already exists from first batch, only 0.30 should be appended.
        assert second["n_runs"] == 1
        assert second["n_existing_runs"] == 2
        assert second["n_total_runs"] == 3
        assert second["simulation_runs"][0]["run_number"] == 2

        with (working_dir / "simulation_plan.json").open("r", encoding="utf-8") as f:
            plan_rows = json.load(f)
        assert len(plan_rows) == 3
        assert [int(row["run_number"]) for row in plan_rows] == [0, 1, 2]

        # Planning should not rewrite existing workflow status records.
        status_after = status_path.read_text(encoding="utf-8")
        assert "run_number,dimension,total_particle_number" in status_after
        assert "0,2,24,NVT" in status_after


def test_plan_simulaiton_runs_rejects_top_level_shape_parameters() -> None:
    from colpack.workflow import setup_simulation_problem, plan_simulaiton_runs

    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        (temp_root / "environment.yml").write_text("name: colpack-test\n", encoding="utf-8")
        case_dir = temp_root / "data" / "2d_nvt_rectangle"

        with patch("colpack.workflow_helper.resolve_working_dir_from_setup", return_value=str(case_dir)):
            problem = setup_simulation_problem(
                dimension=2,
                total_particle_number=24,
                particle_shape_list=["rectangle"],
                ensemble="NVT",
            )

        working_dir = Path(problem["working_dir"])

        try:
            plan_simulaiton_runs(
                baseline_parameters={"width": 1.0, "volume_fraction": 0.5},
                tunable_parameters={"length": [3.0, 5.0, 7.0]},
                working_dir=str(working_dir),
            )
        except ValueError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected planning to reject top-level rectangle shape parameters.")

        assert "simulation_problem.json" in message
        assert "particle_specs" in message
        assert "particle_specs.0.width" in message or "particle_specs.0.length" in message


def test_plan_simulaiton_runs_applies_mutable_schema_overrides() -> None:
    from colpack.workflow import setup_simulation_problem, plan_simulaiton_runs

    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        (temp_root / "environment.yml").write_text("name: colpack-test\n", encoding="utf-8")
        case_dir = temp_root / "data" / "2d_nvt_rectangle"

        with patch("colpack.workflow_helper.resolve_working_dir_from_setup", return_value=str(case_dir)):
            problem = setup_simulation_problem(
                dimension=2,
                total_particle_number=24,
                particle_shape_list=["rectangle"],
                ensemble="NVT",
            )

        planning = plan_simulaiton_runs(
            baseline_parameters={
                "volume_fraction": 0.5,
                "particle_specs.0.width": 1.0,
            },
            tunable_parameters={"particle_specs.0.length": [3.0, 5.0, 7.0]},
            working_dir=str(problem["working_dir"]),
        )

        assert planning["n_runs"] == 3
        assert {run["particle_specs"][0]["length"] for run in planning["simulation_runs"]} == {3.0, 5.0, 7.0}
        assert all(run["particle_specs"][0]["width"] == 1.0 for run in planning["simulation_runs"])
        assert all(run["volume_fraction"] == 0.5 for run in planning["simulation_runs"])


def test_execute_simulation_workflow_emits_context_feedback_events() -> None:
    from colpack.workflow import execute_simulation_workflow

    with TemporaryDirectory() as temp_dir:
        working_dir = Path(temp_dir) / "workflow_case"
        run_dir = working_dir / "run_0"
        run_dir.mkdir(parents=True, exist_ok=True)

        planned_runs = [
            {
                "run_number": 0,
                "run_dir": str(run_dir),
                "dimension": 2,
                "total_particle_number": 16,
                "ensemble": "NVT",
                "particle_specs": [
                    {
                        "type": 0,
                        "shape": "disk",
                        "relative_volume_fraction": 1,
                        "diameter": 1.0,
                    }
                ],
            }
        ]
        (working_dir / "simulation_plan.json").write_text(json.dumps(planned_runs, indent=4), encoding="utf-8")

        fake_initialize = types.ModuleType("colpack.initialize")
        fake_initialize.create_initial_config = lambda run_dir: {"run_dir": run_dir}

        fake_compress = types.ModuleType("colpack.compress")
        fake_compress.compress_system = lambda run_dir: {"run_dir": run_dir}

        fake_sample = types.ModuleType("colpack.sample")
        fake_sample.sample_system = lambda run_dir: {"run_dir": run_dir}

        fake_analyze = types.ModuleType("colpack.analyze")
        fake_analyze.analyze_main = lambda run_dir: {"run_dir": run_dir}

        with patch.dict(
            sys.modules,
            {
                "colpack.initialize": fake_initialize,
                "colpack.compress": fake_compress,
                "colpack.sample": fake_sample,
                "colpack.analyze": fake_analyze,
            },
        ):
            result = execute_simulation_workflow(
                working_dir=str(working_dir),
                continue_on_error=True,
            )

        assert result["n_runs"] == 1
        progress_path = working_dir / "workflow_progress.json"
        assert progress_path.exists()
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        assert progress.get("status") == "completed"
        assert progress.get("n_success") == 1


def test_execute_simulation_workflow_returns_already_running_when_status_indicates_running() -> None:
    from colpack.workflow import execute_simulation_workflow

    with TemporaryDirectory() as temp_dir:
        working_dir = Path(temp_dir) / "workflow_case"
        run_dir = working_dir / "run_0"
        run_dir.mkdir(parents=True, exist_ok=True)

        planned_runs = [
            {
                "run_number": 0,
                "run_dir": str(run_dir),
                "dimension": 2,
                "total_particle_number": 16,
                "ensemble": "NVT",
                "particle_specs": [{"type": 0, "shape": "disk", "relative_volume_fraction": 1, "diameter": 1.0}],
            }
        ]
        (working_dir / "simulation_plan.json").write_text(json.dumps(planned_runs, indent=4), encoding="utf-8")

        status_path = working_dir / "workflow_status.csv"
        status_row = {
            "run_number": "0",
            "dimension": "2",
            "total_particle_number": "16",
            "ensemble": "NVT",
            "initialize": "O",
            "compress": "X",
            "sample": "X",
            "analyze": "X",
            "status": "running",
            "execution_state": "running",
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "",
            "output_dir": str(run_dir),
            "error": "",
        }
        with status_path.open("w", encoding="utf-8", newline="") as status_file:
            writer = csv.DictWriter(status_file, fieldnames=list(status_row.keys()))
            writer.writeheader()
            writer.writerow(status_row)

        result = execute_simulation_workflow(
            working_dir=str(working_dir),
            continue_on_error=True,
        )

        assert result["already_running"] is True
        progress_path = working_dir / "workflow_progress.json"
        assert progress_path.exists()
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        assert progress.get("status") == "already_running"
        assert "already running" in str(progress.get("message", "")).lower()
        rows = _load_status_rows(status_path)
        assert rows[0]["execution_state"] == "running"


def _run_workflow_case(case):
    from colpack.workflow import setup_simulation_problem, plan_simulaiton_runs, execute_simulation_workflow

    project_root = _find_project_root(Path(__file__).resolve())
    case_root = project_root / "data" / "test" / case["system_subdir"]
    shutil.rmtree(case_root, ignore_errors=True)
    case_root.mkdir(parents=True, exist_ok=True)
    print(f"\n=== workflow case: {case['system_subdir']} ===")
    print(f"case_root: {case_root}")

    # 1) setup_simulation_problem
    print("[1/3] setup_simulation_problem: start")
    with patch("colpack.workflow.resolve_working_dir_from_setup", return_value=str(case_root)):
        problem = setup_simulation_problem(
            dimension=case["dimension"],
            total_particle_number=case["total_particle_number"],
            particle_shape_list=case["particle_shape_list"],
            ensemble=case["ensemble"],
        )
    working_dir = Path(problem["working_dir"])
    assert working_dir == case_root
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
    test_resolve_working_dir_from_setup_uses_default_template_and_collision_suffix()
    print("test_resolve_working_dir_from_setup_uses_default_template_and_collision_suffix: OK")
    test_setup_simulation_problem_resolves_default_working_dir_when_omitted()
    print("test_setup_simulation_problem_resolves_default_working_dir_when_omitted: OK")
    test_plan_simulaiton_runs_appends_without_duplicate_tunable_values()
    print("test_plan_simulaiton_runs_appends_without_duplicate_tunable_values: OK")
    test_plan_simulaiton_runs_rejects_top_level_shape_parameters()
    print("test_plan_simulaiton_runs_rejects_top_level_shape_parameters: OK")
    test_plan_simulaiton_runs_applies_mutable_schema_overrides()
    print("test_plan_simulaiton_runs_applies_mutable_schema_overrides: OK")

    cases = [
        {
            "system_subdir": "workflow_case_2d_npt_multishape",
            "dimension": 2,
            "ensemble": "NPT",
            "total_particle_number": 200,
            "particle_shape_list": ["disk", "capsule", "triangle", "rectangle"],
            "baseline_parameters": {
                "sampling_steps": 50,
                "particle_specs.0.diameter": 1.0,
                "particle_specs.1.length": 1.5,
                "particle_specs.1.diameter": 0.5,
                "particle_specs.2.side": 1.0,
                "particle_specs.3.width": 0.5,
                "particle_specs.3.length": 2.5,
            },
            "tunable_parameters": {
                "P": [1.0, 10.0],
            },
            "expected_runs": 2,
        },
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
