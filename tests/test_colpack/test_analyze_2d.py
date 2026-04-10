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


def run_analyze(output_subdir):
    project_root = _find_project_root(Path(__file__).resolve())
    run_dir = project_root / "data" / "test" / output_subdir / "run_0"
    print(f"run_analyze: run_dir: {run_dir}")
    summary = analyze_main(run_dir=str(run_dir))

    assert (run_dir / "simulation_config_analysis.json").exists()
    assert (run_dir / "analysis_results.json").exists()
    assert summary["n_generated_plot_files"] > 0
    for path in summary["generated_plot_files"]:
        assert Path(path).exists()

    with (run_dir / "simulation_config_analysis.json").open("r", encoding="utf-8") as f:
        analyzed_config = json.load(f)

    assert analyzed_config["analysis_results_path"].endswith("analysis_results.json")


def main():
    if not _has_hoomd():
        print("Skipping test_analyze_2d.py: 'hoomd' is not installed in the current Python environment.")
        return

    print("testing analysis of 2d systems...\n")

    run_analyze(output_subdir="2d_disk")
    print("test_analyze_2d_disk: OK\n")

    run_analyze(output_subdir="2d_disk_capsule")
    print("test_analyze_2d_disk_capsule: OK\n")

    run_analyze(output_subdir="2d_disk_ellipse_npt")
    print("test_analyze_2d_npt: OK\n")


if __name__ == "__main__":
    main()
