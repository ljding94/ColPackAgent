import os
import json
import numpy as np
import matplotlib

# ColPack plotting runs in batch workflow threads on macOS; GUI backends crash there.
matplotlib.use("Agg", force=True)


def _get_pyplot():
    import matplotlib.pyplot as plt

    return plt


def _resolve_results_path(run_dir, results_path):
    if not results_path:
        return ""
    if os.path.isabs(results_path):
        return results_path

    candidates = [
        os.path.abspath(results_path),
        os.path.abspath(os.path.join(run_dir, results_path)),
        os.path.abspath(os.path.join(run_dir, os.path.basename(results_path))),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[-1]


def analyze_plot(run_dir, simulation_config):
    run_dir = os.path.abspath(os.path.expanduser(run_dir))
    results_path = _resolve_results_path(run_dir, simulation_config.get("analysis_results_path"))
    if not results_path or not os.path.exists(results_path):
        print(f"Analysis results not found at {results_path}. Cannot perform plotting.")
        return {"generated_files": [], "n_generated_files": 0}
    with open(results_path, "r") as f:
        results = json.load(f)

    rdf_data = {}
    generated_files = []

    for key, data in results.items():
        if key.startswith("rdf_"):
            rdf_data[key] = data
        else:
            plot_filename = os.path.join(run_dir, f"plot_order_{key}")
            generated_files.extend(_plot_shape_order(data, f"Order Parameters for {key}", plot_filename))

    if rdf_data:
        plot_filename = os.path.join(run_dir, "plot_rdf")
        generated_files.extend(_plot_rdf(rdf_data, "Radial Distribution Function", plot_filename))

    return {
        "generated_files": generated_files,
        "n_generated_files": len(generated_files),
    }


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
    plt = _get_pyplot()

    # Extract equilibrium info if present
    eq_info = results.get("equilibrium", {})
    per_param_eq = eq_info.get("per_parameter", {})

    # Filter out non-timeseries entries (equilibrium block, empty lists)
    plot_items = [(label, values) for label, values in results.items()
                  if label != "equilibrium" and values]
    if not plot_items:
        return []

    n_params = len(plot_items)

    if n_params == 1:
        # Single parameter: one plot
        fig = plt.figure(figsize=(10.0 / 3 * 1.2, 10.0 / 3 * 1.0))
        ax = fig.add_subplot(111)
        label, values = plot_items[0]
        y_values = _extract_y_values(values)
        x = np.arange(len(y_values))
        ax.plot(x, y_values, label=label)
        _draw_equilibrium(ax, label, per_param_eq, x)
        ax.set_xlabel("Frame", fontsize=9, labelpad=0)
        ax.set_ylabel("Order Parameter", fontsize=9, labelpad=0)
        ax.tick_params(axis="both", which="both", direction="in", labelsize=7)
        ax.set_title(title, fontsize=9)
        ax.legend(frameon=False, fontsize=7, loc="best")
    else:
        # Multiple parameters: vertically stacked subplots
        fig, axes = plt.subplots(n_params, 1, figsize=(10.0 / 3 * 1.2, 10.0 / 3 * 0.7 * n_params), sharex=True)
        if n_params == 2:
            axes = list(axes)
        for ax, (label, values) in zip(axes, plot_items):
            y_values = _extract_y_values(values)
            x = np.arange(len(y_values))
            ax.plot(x, y_values, label=label)
            _draw_equilibrium(ax, label, per_param_eq, x)
            ax.set_ylabel(label, fontsize=8, labelpad=2)
            ax.tick_params(axis="both", which="both", direction="in", labelsize=7)
            ax.legend(frameon=False, fontsize=7, loc="best")
        axes[-1].set_xlabel("Frame", fontsize=9, labelpad=0)
        fig.suptitle(title, fontsize=9, y=1.0)

    plt.tight_layout(pad=0.2)
    png_path = filename + ".png"
    pdf_path = filename + ".pdf"
    plt.savefig(png_path, dpi=300)
    plt.savefig(pdf_path, dpi=300, format="pdf")
    plt.close()
    return [png_path, pdf_path]


def _draw_equilibrium(ax, param_name, per_param_eq, x):
    """Draw equilibrium markers on an axis if equilibrium info exists for param_name."""
    peq = per_param_eq.get(param_name, {})
    if not peq or not peq.get("equilibrated"):
        return
    eq_start = peq["eq_start_index"]
    eq_mean = peq["eq_mean"]
    eq_std = peq.get("eq_std", 0)
    # Vertical line at equilibrium start
    ax.axvline(eq_start, color="gray", linestyle="--", linewidth=0.8, alpha=0.7)
    # Horizontal band for mean ± std over the equilibrated region
    ax.axhline(eq_mean, xmin=(eq_start / max(x[-1], 1)) if len(x) > 1 else 0,
               color="red", linestyle="-", linewidth=0.8, alpha=0.6)
    if eq_std > 0:
        ax.axhspan(eq_mean - eq_std, eq_mean + eq_std,
                    xmin=(eq_start / max(x[-1], 1)) if len(x) > 1 else 0,
                    color="red", alpha=0.08)
    # Annotation
    ax.text(eq_start, ax.get_ylim()[1], f" eq={eq_mean:.4f}",
            fontsize=6, color="red", va="top", ha="left")


def _extract_y_values(values):
    """Convert raw order parameter values to plottable floats.

    Handles complex numbers serialized as ``{"real": ..., "imag": ...}`` by
    returning the magnitude.
    """
    if isinstance(values[0], dict) and "real" in values[0] and "imag" in values[0]:
        return [np.hypot(v["real"], v["imag"]) for v in values]
    return values


def _plot_rdf(results, title, filename):
    plt = _get_pyplot()
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
    png_path = filename + ".png"
    pdf_path = filename + ".pdf"
    plt.savefig(png_path, dpi=600)
    plt.savefig(pdf_path, dpi=600, format="pdf")
    plt.close()
    return [png_path, pdf_path]
