from pathlib import Path
import importlib.util
import json
from colpack.analyze import analyze_main


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


def run_analyze(output_subdir, expected_order_params=None, extra_order_params=None):
    project_root = _find_project_root(Path(__file__).resolve())
    run_dir = project_root / "data" / "test" / output_subdir / "run_0"
    print(f"run_analyze: run_dir: {run_dir}")
    summary = analyze_main(run_dir=str(run_dir), extra_order_params=extra_order_params)

    assert (run_dir / "simulation_config_analysis.json").exists()
    assert (run_dir / "analysis_results.json").exists()
    assert summary["n_generated_plot_files"] > 0
    for path in summary["generated_plot_files"]:
        assert Path(path).exists()

    with (run_dir / "simulation_config_analysis.json").open("r", encoding="utf-8") as f:
        analyzed_config = json.load(f)

    assert analyzed_config["analysis_results_path"].endswith("analysis_results.json")

    # Validate expected order parameter keys and equilibrium info in results
    if expected_order_params:
        with (run_dir / "analysis_results.json").open("r", encoding="utf-8") as f:
            results = json.load(f)
        for ptype, param_names in expected_order_params.items():
            assert ptype in results, f"Missing particle type '{ptype}' in analysis_results.json"
            for param in param_names:
                assert param in results[ptype], (
                    f"Missing order param '{param}' for '{ptype}' in analysis_results.json"
                )
                assert len(results[ptype][param]) > 0, (
                    f"Order param '{param}' for '{ptype}' has no data"
                )
            # Validate equilibrium block structure
            eq = results[ptype].get("equilibrium")
            assert eq is not None, f"Missing 'equilibrium' block for '{ptype}'"
            assert "equilibrated" in eq
            assert "eq_start_index" in eq
            assert "per_parameter" in eq
            for param in param_names:
                peq = eq["per_parameter"].get(param)
                assert peq is not None, f"Missing equilibrium info for param '{param}' in '{ptype}'"
                assert "equilibrated" in peq
                assert "eq_mean" in peq
                assert "eq_std" in peq


def main():
    if not _has_hoomd():
        print("Skipping test_analyze_3d.py: 'hoomd' is not installed in the current Python environment.")
        return

    print("testing analysis of 3d systems...\n")

    run_analyze(
        output_subdir="3d_sphere",
        expected_order_params={"sphere_0": ["steinhardt_q6", "steinhardt_q4", "solid_liquid_q6"]},
    )
    print("test_analyze_3d_sphere: OK\n")

    run_analyze(
        output_subdir="3d_sphere_capsule",
        expected_order_params={
            "sphere_0": ["steinhardt_q6", "steinhardt_q4", "solid_liquid_q6"],
            "capsule_0": ["nematic"],
        },
    )
    print("test_analyze_3d_sphere_capsule: OK\n")

    run_analyze(output_subdir="3d_sphere_capsule_npt")
    print("test_analyze_3d_npt: OK\n")

    # Test with custom extra order params
    run_analyze(
        output_subdir="3d_sphere",
        expected_order_params={"sphere_0": ["steinhardt_q6", "steinhardt_q4", "solid_liquid_q6", "steinhardt_q3", "continuous_coord"]},
        extra_order_params=[
            {"name": "steinhardt_q3", "type": "Steinhardt", "params": {"l": 3}},
            {"name": "continuous_coord", "type": "ContinuousCoordination", "params": {}},
        ],
    )
    print("test_analyze_3d_sphere_extra_params: OK\n")

    # Restore default (no extras) so test data is clean
    run_analyze(
        output_subdir="3d_sphere",
        expected_order_params={"sphere_0": ["steinhardt_q6", "steinhardt_q4", "solid_liquid_q6"]},
    )
    print("test_analyze_3d_sphere_restore: OK\n")


if __name__ == "__main__":
    main()
