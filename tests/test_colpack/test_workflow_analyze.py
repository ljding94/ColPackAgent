"""
Tests for analyze_simulation_runs as a standalone workflow step.

Unit tests (no HOOMD required): mock analyze_main to verify status/progress
tracking, skip logic, and error handling in isolation.

Integration tests (HOOMD required): run the full setup → plan → execute →
analyze pipeline using small particle counts.
"""

from pathlib import Path
import json
import csv
import sys
import types
import shutil
import importlib.util
from tempfile import TemporaryDirectory
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

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


def _make_plan(working_dir: Path, runs: list[dict]) -> None:
    (working_dir / "simulation_plan.json").write_text(
        json.dumps(runs, indent=4), encoding="utf-8"
    )


def _minimal_run(run_number: int, run_dir: str) -> dict:
    return {
        "run_number": run_number,
        "run_dir": run_dir,
        "dimension": 2,
        "total_particle_number": 16,
        "ensemble": "NVT",
        "particle_specs": [
            {"type": 0, "shape": "disk", "relative_volume_fraction": 1, "diameter": 1.0}
        ],
    }


# ---------------------------------------------------------------------------
# Unit tests — mock analyze_main, no HOOMD needed
# ---------------------------------------------------------------------------

def test_analyze_simulation_runs_calls_analyze_main_for_each_run() -> None:
    from colpack.workflow import analyze_simulation_runs

    with TemporaryDirectory() as tmp:
        working_dir = Path(tmp)
        run_dirs = [working_dir / f"run_{i}" for i in range(3)]
        for rd in run_dirs:
            rd.mkdir()

        _make_plan(working_dir, [_minimal_run(i, str(run_dirs[i])) for i in range(3)])

        called = []
        fake_analyze = types.ModuleType("colpack.analyze")
        fake_analyze.analyze_main = lambda run_dir: called.append(run_dir) or {"plots": []}

        with patch.dict(sys.modules, {"colpack.analyze": fake_analyze}):
            result = analyze_simulation_runs(working_dir=str(working_dir))

        assert len(called) == 3
        assert result["n_runs"] == 3
        assert result["n_success"] == 3
        assert result["n_failed"] == 0


def test_analyze_simulation_runs_skips_already_analyzed_runs() -> None:
    from colpack.workflow import analyze_simulation_runs

    with TemporaryDirectory() as tmp:
        working_dir = Path(tmp)
        run_dirs = [working_dir / f"run_{i}" for i in range(3)]
        for rd in run_dirs:
            rd.mkdir()

        _make_plan(working_dir, [_minimal_run(i, str(run_dirs[i])) for i in range(3)])

        # Pre-populate status CSV with run_0 already analyzed.
        status_path = working_dir / "workflow_status.csv"
        fieldnames = [
            "run_number", "dimension", "total_particle_number", "ensemble",
            "initialize", "compress", "sample", "analyze",
            "status", "execution_state", "started_at", "finished_at", "output_dir", "error",
        ]
        with status_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow({
                "run_number": "0", "dimension": "2", "total_particle_number": "16",
                "ensemble": "NVT", "initialize": "O", "compress": "O", "sample": "O",
                "analyze": "O", "status": "success", "execution_state": "finished",
                "started_at": "", "finished_at": "", "output_dir": str(run_dirs[0]), "error": "",
            })

        called = []
        fake_analyze = types.ModuleType("colpack.analyze")
        fake_analyze.analyze_main = lambda run_dir: called.append(run_dir) or {"plots": []}

        with patch.dict(sys.modules, {"colpack.analyze": fake_analyze}):
            result = analyze_simulation_runs(working_dir=str(working_dir))

        # Only run_1 and run_2 should be analyzed (run_0 skipped).
        assert len(called) == 2
        assert result["n_runs"] == 3


def test_analyze_simulation_runs_continue_on_error_true() -> None:
    from colpack.workflow import analyze_simulation_runs

    with TemporaryDirectory() as tmp:
        working_dir = Path(tmp)
        run_dirs = [working_dir / f"run_{i}" for i in range(3)]
        for rd in run_dirs:
            rd.mkdir()

        _make_plan(working_dir, [_minimal_run(i, str(run_dirs[i])) for i in range(3)])

        call_count = [0]

        def _analyze(run_dir):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("simulated failure on run_1")
            return {"plots": []}

        fake_analyze = types.ModuleType("colpack.analyze")
        fake_analyze.analyze_main = _analyze

        with patch.dict(sys.modules, {"colpack.analyze": fake_analyze}):
            result = analyze_simulation_runs(working_dir=str(working_dir), continue_on_error=True)

        # All 3 attempted; 1 failure but continued.
        assert call_count[0] == 3
        assert result["n_success"] == 2
        assert result["n_failed"] == 1


def test_analyze_simulation_runs_continue_on_error_false_stops_early() -> None:
    from colpack.workflow import analyze_simulation_runs

    with TemporaryDirectory() as tmp:
        working_dir = Path(tmp)
        run_dirs = [working_dir / f"run_{i}" for i in range(3)]
        for rd in run_dirs:
            rd.mkdir()

        _make_plan(working_dir, [_minimal_run(i, str(run_dirs[i])) for i in range(3)])

        call_count = [0]

        def _analyze(run_dir):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated failure on run_0")
            return {"plots": []}

        fake_analyze = types.ModuleType("colpack.analyze")
        fake_analyze.analyze_main = _analyze

        with patch.dict(sys.modules, {"colpack.analyze": fake_analyze}):
            result = analyze_simulation_runs(working_dir=str(working_dir), continue_on_error=False)

        # Stopped after the first failure.
        assert call_count[0] == 1
        assert result["n_failed"] >= 1


def test_analyze_simulation_runs_writes_status_csv_and_progress() -> None:
    from colpack.workflow import analyze_simulation_runs

    with TemporaryDirectory() as tmp:
        working_dir = Path(tmp)
        run_dir = working_dir / "run_0"
        run_dir.mkdir()

        _make_plan(working_dir, [_minimal_run(0, str(run_dir))])

        fake_analyze = types.ModuleType("colpack.analyze")
        fake_analyze.analyze_main = lambda run_dir: {"plots": []}

        with patch.dict(sys.modules, {"colpack.analyze": fake_analyze}):
            result = analyze_simulation_runs(working_dir=str(working_dir))

        # Status CSV must exist and contain the completed run.
        status_path = Path(result["status_path"])
        assert status_path.exists()
        rows = _load_status_rows(status_path)
        assert len(rows) == 1
        assert rows[0]["analyze"] == "O"
        assert rows[0]["status"] == "success"
        assert rows[0]["execution_state"] == "finished"

        # Progress JSON must exist and report completed.
        progress_path = Path(result["progress_path"])
        assert progress_path.exists()
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        assert progress["status"] == "completed"
        assert progress["n_success"] == 1


def test_analyze_simulation_runs_marks_execution_state_finished_on_completion() -> None:
    from colpack.workflow import analyze_simulation_runs

    with TemporaryDirectory() as tmp:
        working_dir = Path(tmp)
        run_dirs = [working_dir / f"run_{i}" for i in range(2)]
        for rd in run_dirs:
            rd.mkdir()

        _make_plan(working_dir, [_minimal_run(i, str(run_dirs[i])) for i in range(2)])

        fake_analyze = types.ModuleType("colpack.analyze")
        fake_analyze.analyze_main = lambda run_dir: {"plots": []}

        with patch.dict(sys.modules, {"colpack.analyze": fake_analyze}):
            analyze_simulation_runs(working_dir=str(working_dir))

        status_path = working_dir / "workflow_status.csv"
        rows = _load_status_rows(status_path)
        assert all(row["execution_state"] == "finished" for row in rows)


# ---------------------------------------------------------------------------
# Integration tests — full pipeline with real HOOMD simulation
# ---------------------------------------------------------------------------

def _run_workflow_analyze_case(case: dict) -> None:
    from colpack.workflow import (
        setup_simulation_problem,
        plan_simulaiton_runs,
        execute_simulation_workflow,
        analyze_simulation_runs,
    )

    project_root = _find_project_root(Path(__file__).resolve())
    case_root = project_root / "data" / "test" / case["system_subdir"]
    shutil.rmtree(case_root, ignore_errors=True)
    case_root.mkdir(parents=True, exist_ok=True)
    print(f"\n=== workflow analyze case: {case['system_subdir']} ===")

    # 1) setup
    with patch("colpack.workflow.resolve_working_dir_from_setup", return_value=str(case_root)):
        problem = setup_simulation_problem(
            dimension=case["dimension"],
            total_particle_number=case["total_particle_number"],
            particle_shape_list=case["particle_shape_list"],
            ensemble=case["ensemble"],
        )
    working_dir = Path(problem["working_dir"])
    print("[1/4] setup_simulation_problem: done")

    # 2) plan
    planning = plan_simulaiton_runs(
        baseline_parameters=case["baseline_parameters"],
        tunable_parameters=case["tunable_parameters"],
        working_dir=str(working_dir),
    )
    assert planning["n_runs"] == case["expected_runs"]
    print(f"[2/4] plan_simulaiton_runs: done (n_runs={planning['n_runs']})")

    # 3) execute (initialize + compress + sample only — no analyze)
    exec_result = execute_simulation_workflow(
        working_dir=str(working_dir),
        continue_on_error=True,
    )
    assert exec_result["n_runs"] == planning["n_runs"]
    print(f"[3/4] execute_simulation_workflow: done (n_success={exec_result['n_success']})")

    # 4) analyze as a separate step
    analyze_result = analyze_simulation_runs(
        working_dir=str(working_dir),
        continue_on_error=True,
    )
    assert analyze_result["n_runs"] == planning["n_runs"]
    assert analyze_result["n_success"] == planning["n_runs"]
    assert analyze_result["n_failed"] == 0
    print(f"[4/4] analyze_simulation_runs: done (n_success={analyze_result['n_success']})")

    # Validate per-run outputs.
    with (working_dir / "simulation_plan.json").open("r", encoding="utf-8") as f:
        planned_runs = json.load(f)

    for run in planned_runs:
        run_dir = Path(run["run_dir"])
        assert (run_dir / "analysis_results.json").exists(), f"Missing analysis_results.json in {run_dir}"
        assert (run_dir / "simulation_config_analysis.json").exists(), f"Missing simulation_config_analysis.json in {run_dir}"

    # Validate status CSV shows analyze=O for all runs.
    status_path = Path(analyze_result["status_path"])
    rows = _load_status_rows(status_path)
    for row in rows:
        assert row["analyze"] == "O", f"Expected analyze=O, got {row['analyze']} for run {row.get('run_number')}"

    # Re-running analyze should skip all (already done) and return cleanly.
    rerun = analyze_simulation_runs(working_dir=str(working_dir), continue_on_error=True)
    assert rerun["n_failed"] == 0
    print("[4/4] analyze_simulation_runs re-run (idempotency): OK")


def _run_workflow_analyze_case_from_existing_trajectories() -> None:
    """Use pre-existing trajectory data in workflow_execute_nvt to test analyze step."""
    from colpack.workflow import analyze_simulation_runs

    project_root = _find_project_root(Path(__file__).resolve())
    working_dir = project_root / "data" / "test" / "workflow_execute_nvt"

    if not (working_dir / "simulation_plan.json").exists():
        print(f"Skipping existing-data analyze test: simulation_plan.json not found in {working_dir}")
        return

    # Clear any previous analyze outputs so we test a fresh run.
    with (working_dir / "simulation_plan.json").open("r", encoding="utf-8") as f:
        planned_runs = json.load(f)

    for run in planned_runs:
        run_dir = Path(run["run_dir"])
        for fname in ["analysis_results.json", "simulation_config_analysis.json"]:
            (run_dir / fname).unlink(missing_ok=True)

    # Clear analyze column in status CSV if present.
    status_path = working_dir / "workflow_status.csv"
    if status_path.exists():
        rows = _load_status_rows(status_path)
        for row in rows:
            row["analyze"] = "X"
        fieldnames = list(rows[0].keys()) if rows else []
        if fieldnames:
            with status_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    result = analyze_simulation_runs(working_dir=str(working_dir), continue_on_error=True)

    assert result["n_runs"] == len(planned_runs)
    assert result["n_success"] == len(planned_runs)
    assert result["n_failed"] == 0

    for run in planned_runs:
        run_dir = Path(run["run_dir"])
        assert (run_dir / "analysis_results.json").exists()
        assert (run_dir / "simulation_config_analysis.json").exists()

    print(f"analyze from existing trajectories (workflow_execute_nvt): OK (n_success={result['n_success']})")


def main():
    # --- Unit tests (no HOOMD required) ---
    test_analyze_simulation_runs_calls_analyze_main_for_each_run()
    print("test_analyze_simulation_runs_calls_analyze_main_for_each_run: OK")

    test_analyze_simulation_runs_skips_already_analyzed_runs()
    print("test_analyze_simulation_runs_skips_already_analyzed_runs: OK")

    test_analyze_simulation_runs_continue_on_error_true()
    print("test_analyze_simulation_runs_continue_on_error_true: OK")

    test_analyze_simulation_runs_continue_on_error_false_stops_early()
    print("test_analyze_simulation_runs_continue_on_error_false_stops_early: OK")

    test_analyze_simulation_runs_writes_status_csv_and_progress()
    print("test_analyze_simulation_runs_writes_status_csv_and_progress: OK")

    test_analyze_simulation_runs_marks_execution_state_finished_on_completion()
    print("test_analyze_simulation_runs_marks_execution_state_finished_on_completion: OK")

    # --- Integration tests (HOOMD + freud required) ---
    if not _has_hoomd():
        print("\nSkipping integration tests: 'hoomd' is not installed.")
        return

    print("\ntesting analyze from pre-existing trajectory data...")
    _run_workflow_analyze_case_from_existing_trajectories()

    cases = [
        {
            "system_subdir": "workflow_analyze_2d_nvt_disk",
            "dimension": 2,
            "ensemble": "NVT",
            "total_particle_number": 64,
            "particle_shape_list": ["disk"],
            "baseline_parameters": {
                "sample_steps": 500,
                "particle_specs.0.diameter": 1.0,
            },
            "tunable_parameters": {
                "volume_fraction": [0.20, 0.30],
            },
            "expected_runs": 2,
        },
        {
            "system_subdir": "workflow_analyze_2d_nvt_disk_capsule",
            "dimension": 2,
            "ensemble": "NVT",
            "total_particle_number": 64,
            "particle_shape_list": ["disk", "capsule"],
            "baseline_parameters": {
                "sample_steps": 500,
                "particle_specs.0.diameter": 1.0,
                "particle_specs.1.length": 1.5,
                "particle_specs.1.diameter": 0.5,
            },
            "tunable_parameters": {
                "volume_fraction": [0.20, 0.25],
            },
            "expected_runs": 2,
        },
    ]

    print("\ntesting full workflow pipeline with separate analyze step...")
    for case in cases:
        _run_workflow_analyze_case(case)
        print(f"workflow analyze case {case['system_subdir']}: OK")


if __name__ == "__main__":
    main()
