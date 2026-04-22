import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _default_run_path():
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "demo" / "data" / "2d_nvt_capsule_disk_v2"


def _sorted_run_dirs(run_path):
    run_dirs = [path for path in run_path.glob("run_*") if path.is_dir()]

    def _run_index(path):
        try:
            return int(path.name.split("_")[-1])
        except ValueError:
            return 10**9

    return sorted(run_dirs, key=_run_index)


def _load_run_payload(run_dir):
    config_path = run_dir / "simulation_config_analysis.json"
    if not config_path.exists():
        config_path = run_dir / "simulation_config.json"

    config = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)

    analysis_path = run_dir / "analysis_results.json"
    if not analysis_path.exists():
        candidate = config.get("analysis_results_path", "")
        if candidate:
            analysis_path = Path(candidate).expanduser()

    if not analysis_path.exists():
        raise FileNotFoundError(f"Missing analysis result JSON in {run_dir}")

    with analysis_path.open("r", encoding="utf-8") as handle:
        results = json.load(handle)

    return config, results


def _extract_rdf_capsule_capsule(results):
    if "rdf_capsule_0_capsule_0" in results:
        rdf = results["rdf_capsule_0_capsule_0"]
        return rdf["r"], rdf["g_r"]

    for key, value in results.items():
        if key.startswith("rdf_capsule") and "_capsule" in key:
            return value["r"], value["g_r"]

    raise KeyError("Could not find capsule-capsule RDF in analysis results.")


def _extract_rdf_disk_disk(results):
    if "rdf_disk_0_disk_0" in results:
        rdf = results["rdf_disk_0_disk_0"]
        return rdf["r"], rdf["g_r"]

    for key, value in results.items():
        if key.startswith("rdf_disk") and "_disk" in key:
            return value["r"], value["g_r"]

    raise KeyError("Could not find disk-disk RDF in analysis results.")


def plot_autonomous_demo(run_path=None, output_path=None):
    run_path = Path(run_path).expanduser().resolve() if run_path else _default_run_path()
    if not run_path.exists():
        raise FileNotFoundError(f"Run path does not exist: {run_path}")

    run_dirs = _sorted_run_dirs(run_path)
    if len(run_dirs) != 4:
        raise ValueError(f"Expected exactly 4 run folders under {run_path}, found {len(run_dirs)}")

    run_series = []
    for run_dir in run_dirs:
        config, results = _load_run_payload(run_dir)
        r_capsule, g_r_capsule = _extract_rdf_capsule_capsule(results)
        r_disk, g_r_disk = _extract_rdf_disk_disk(results)
        volume_fraction = config.get("volume_fraction")
        label = run_dir.name if volume_fraction is None else f"{run_dir.name} (phi={volume_fraction})"
        run_series.append(
            {
                "label": label,
                "r_capsule": np.asarray(r_capsule, dtype=float),
                "g_r_capsule": np.asarray(g_r_capsule, dtype=float),
                "r_disk": np.asarray(r_disk, dtype=float),
                "g_r_disk": np.asarray(g_r_disk, dtype=float),
            }
        )

    fig, axes = plt.subplots(2, 2, figsize=(3.3, 3.3*0.8), sharex=True)
    axes = np.asarray(axes).reshape(-1)

    all_x = []
    for series in run_series:
        all_x.extend(series["r_capsule"].tolist())
        all_x.extend(series["r_disk"].tolist())

    x_min, x_max = float(min(all_x)), float(max(all_x))

    for idx, (ax, series) in enumerate(zip(axes, run_series)):
        row, _ = divmod(idx, 2)
        ax.plot(series["r_capsule"], series["g_r_capsule"], linewidth=1, label="capsule")
        ax.plot(series["r_disk"], series["g_r_disk"], linewidth=1, label="disk")
        ax.set_xlim(x_min, x_max)
        ax.set_ylabel(r"$g(r)$", fontsize=9, labelpad=0)
        ax.set_xlabel(r"$r$" if row == 1 else "", fontsize=9, labelpad=0)
        ax.tick_params(axis="both", which="both", direction="in", top=True, right=True, labelsize=7)
        ax.tick_params(axis="x", which="both", labelbottom=(row == 1))
        ax.legend(frameon=False, fontsize=7, loc="upper right", ncol=1, title_fontsize=7, columnspacing=0.5, handlelength=0.5, handletextpad=0.3, labelspacing=0.2)
    axes[0].set_ylim(None, 1.5)

    panel_labels = [r"$(a)$", r"$(b)$", r"$(c)$", r"$(d)$"]
    annotations = [r"$\phi=0.1$", r"$\phi=0.3$", r"$\phi=0.5$", r"$\phi=0.7$"]
    for i, ax in enumerate(axes):
        if i >= len(panel_labels) or not ax.has_data():
            continue
        #ax.text(0.8, 0.15, panel_labels[i], fontsize=9, transform=ax.transAxes)
        ax.text(0.8, 0.35, annotations[i], fontsize=9, transform=ax.transAxes, ha="center")

    fig.tight_layout(pad=0.1)

    fig.savefig("./figures/demo_autonomous.png", dpi=600)
    fig.savefig("./figures/demo_autonomous.pdf", format="pdf")
    plt.show()
    plt.close(fig)




if __name__ == "__main__":
    plot_autonomous_demo()
