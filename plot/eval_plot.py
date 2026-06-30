import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter


STAGES = ("setup", "planning", "analysis")
STAGE_COLORS = {
    "setup": "#4E79A7",
    "planning": "#F28E2B",
    "analysis": "#59A14F",
}
STAGE_LABELS = {
    "setup": "setup",
    "planning": "planning",
    "analysis": "analysis",
}

METRIC_KEYS = (
    "n_runs",
    "n_success",
    "success_rate",
    "total_effective_input_tokens",
    "total_output_tokens",
    "total_cost_usd",
)


def _default_runs_dir():
    return Path(__file__).resolve().parents[1] / "eval" / "runs"


def _load_eval_summaries(runs_dir=None):
    runs_dir = Path(runs_dir) if runs_dir is not None else _default_runs_dir()
    if not runs_dir.exists():
        raise FileNotFoundError(f"Eval runs dir does not exist: {runs_dir}")

    summaries = {}
    for model_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        per_stage = {}
        for stage in STAGES:
            summary_path = model_dir / stage / "summary.json"
            if not summary_path.exists():
                continue
            with summary_path.open("r", encoding="utf-8") as handle:
                per_stage[stage] = json.load(handle)
        if per_stage:
            summaries[model_dir.name] = per_stage
    return summaries


def _stage_metric(summaries, model, stage, key, default=0.0):
    return summaries.get(model, {}).get(stage, {}).get(key, default)


def _two_line_label(name):
    hyphens = [i for i, ch in enumerate(name) if ch == "-"]
    if not hyphens:
        return name
    split_at = min(hyphens, key=lambda i: max(i, len(name) - i - 1))
    return name[:split_at] + "\n" + name[split_at + 1 :]


def plot_llm_eval(runs_dir=None, show=True):
    """
    4 subplot,
    1. successful run count bar chart across tasks: horizontal are different LLMs, vertical is the number of successful runs of three kinds of tasks (setup, planning, analysis) stacked together, with different color. Dashed line marks the total possible run count.
    2. total cost usd
    3. total effective input tokens bar plot
    4. total effective output tokens bar plot

    there for subplot should be stacked vertically, sharing the x-axis
    """
    summaries = _load_eval_summaries(runs_dir)
    if not summaries:
        raise RuntimeError("No eval summaries found under eval/runs/.")

    models = sorted(
        summaries.keys(),
        key=lambda m: sum(_stage_metric(summaries, m, s, "n_success", 0) for s in STAGES),
        reverse=True,
    )
    x = np.arange(len(models))
    bar_width = 0.65

    fig, axes = plt.subplots(4, 1, figsize=(3.3, 3.3 * 1.5), sharex=True)
    axes = np.asarray(axes).reshape(-1)

    metric_specs = [
        ("n_success", r"successful runs"),
        ("total_cost_usd", r"cost (USD)"),
        ("total_effective_input_tokens", r"input tokens"),
        ("total_output_tokens", r"output tokens"),
    ]

    total_runs_per_model = [
        sum(_stage_metric(summaries, m, s, "n_runs", 0) for s in STAGES) for m in models
    ]
    total_runs_ceiling = max(total_runs_per_model) if total_runs_per_model else 0

    for ax, (metric_key, ylabel) in zip(axes, metric_specs):
        bottoms = np.zeros(len(models), dtype=float)
        for stage in STAGES:
            values = np.array(
                [_stage_metric(summaries, m, stage, metric_key, 0.0) for m in models],
                dtype=float,
            )
            ax.bar(
                x,
                values,
                bottom=bottoms,
                width=bar_width,
                color=STAGE_COLORS[stage],
                edgecolor="black",
                linewidth=0.4,
                label=STAGE_LABELS[stage],
            )
            bottoms += values

        ax.set_ylabel(ylabel, fontsize=9, labelpad=2)
        ax.tick_params(axis="both", which="both", direction="in", top=True, right=True, labelsize=7)
        ax.margins(x=0.02)

    axes[0].axhline(total_runs_ceiling, color="black", linestyle="--", linewidth=0.6)
    axes[0].set_ylim(0, total_runs_ceiling * 1.08)

    for ax in (axes[2], axes[3]):
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e3:.0f}k" if v >= 1e3 else f"{v:.0f}"))

    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels([_two_line_label(m) for m in models], rotation=45, ha="right", va="top", fontsize=7)

    panel_labels = [r"$(a)$", r"$(b)$", r"$(c)$", r"$(d)$"]
    for i, ax in enumerate(axes):
        ax.text(0.9, 0.45, panel_labels[i], fontsize=9, transform=ax.transAxes, ha="left", va="top")

    for ax in axes:
        ax.legend(
            frameon=False,
            fontsize=7,
            loc="upper right",
            ncol=3,
            columnspacing=0.6,
            handlelength=0.8,
            handletextpad=0.3,
            labelspacing=0.2,
        )

    fig.tight_layout(pad=0.1)

    fig.savefig("./figures/llm_eval.png", dpi=600)
    fig.savefig("./figures/llm_eval.pdf", format="pdf")
    if show:
        plt.show()
    plt.close(fig)
