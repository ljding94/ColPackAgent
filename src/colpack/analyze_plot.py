import os
import json
import numpy as np
import matplotlib.pyplot as plt


def analyze_plot(run_dir, simulation_config):
    results_path = simulation_config.get("analysis_results_path")
    if not results_path or not os.path.exists(results_path):
        print(f"Analysis results not found at {results_path}. Cannot perform plotting.")
        return
    with open(results_path, "r") as f:
        results = json.load(f)

    rdf_data = {}

    for key, data in results.items():
        if key.startswith("rdf_"):
            rdf_data[key] = data
            plot_filename = os.path.join(run_dir, f"plot_order_{key}")
            _plot_shape_order(data, f"Order Parameters for {key}", plot_filename)

    if rdf_data:
        plot_filename = os.path.join(run_dir, "plot_rdf")
        _plot_rdf(rdf_data, "Radial Distribution Function", plot_filename)


def analyze_plot_old(system_dir, density=None):
    """
    Plots the analysis results stored in analysis_results.json in the system directory.
    """
    if density is not None:
        results_path = os.path.join(system_dir, f"analysis_results_n{density:.3f}.json")
    else:
        results_path = os.path.join(system_dir, "analysis_results.json")

    if not os.path.exists(results_path):
        print(f"Analysis results not found at {results_path}")
        return

    with open(results_path, "r") as f:
        results = json.load(f)

    rdf_data = {}

    for key, data in results.items():
        if key.startswith("rdf_"):
            rdf_data[key] = data
        else:
            # Assume it's shape order data
            if density is not None:
                plot_filename = os.path.join(system_dir, f"plot_order_n{density:.3f}_{key}")
            else:
                plot_filename = os.path.join(system_dir, f"plot_order_{key}")
            _plot_shape_order(data, f"Order Parameters for {key}", plot_filename)

    if rdf_data:
        if density is not None:
            plot_filename = os.path.join(system_dir, f"plot_rdf_n{density:.3f}")
        else:
            plot_filename = os.path.join(system_dir, "plot_rdf")
        _plot_rdf(rdf_data, "Radial Distribution Function", plot_filename)


def _plot_shape_order(results, title, filename):
    fig = plt.figure(figsize=(10.0 / 3 * 1.2, 10.0 / 3 * 1.0))
    ax1 = fig.add_subplot(111)

    for label, values in results.items():
        if not values:
            continue

        # Handle complex numbers serialized as dicts {"real": ..., "imag": ...}
        if isinstance(values[0], dict) and "real" in values[0] and "imag" in values[0]:
            # Compute magnitude for plotting
            y_values = [np.hypot(v["real"], v["imag"]) for v in values]
        else:
            y_values = values

        x = np.arange(len(y_values))
        ax1.plot(x, y_values, label=label)

    ax1.set_xlabel("Frame", fontsize=9, labelpad=0)
    ax1.set_ylabel("Order Parameter", fontsize=9, labelpad=0)
    ax1.tick_params(axis="both", which="both", direction="in", labelsize=7)
    ax1.set_title(title, fontsize=9)
    ax1.legend(frameon=False, fontsize=7, loc="best")

    plt.tight_layout(pad=0.2)
    plt.savefig(filename + ".png", dpi=300)
    plt.savefig(filename + ".pdf", dpi=300, format="pdf")
    plt.close()


def _plot_rdf(results, title, filename):
    fig = plt.figure(figsize=(10.0 / 3 * 1.0, 10.0 / 3 * 0.8))
    ax1 = fig.add_subplot(111)
    for label, data in results.items():
        # data is expected to be {'r': [...], 'g_r': [...]}
        ax1.plot(data["r"], data["g_r"], label=label)
    ax1.set_xlabel(r"$r$", fontsize=9, labelpad=0)
    ax1.set_ylabel(r"$g(r)$", fontsize=9, labelpad=0)
    ax1.tick_params(axis="both", which="both", direction="in", labelsize=7)
    ax1.set_title(title, fontsize=9)
    ax1.legend(frameon=False, fontsize=7, loc="upper left", ncol=2, columnspacing=0.5, handlelength=1, handletextpad=0.2, labelspacing=0.1)
    plt.tight_layout(pad=0.2)
    plt.savefig(filename + ".png", dpi=600)
    plt.savefig(filename + ".pdf", dpi=600, format="pdf")
    plt.close()
