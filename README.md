# ColPackAgent

[![PyPI version](https://img.shields.io/pypi/v/colpack.svg)](https://pypi.org/project/colpack/)
[![arXiv](https://img.shields.io/badge/arXiv-2605.15625-b31b1b.svg)](https://arxiv.org/abs/2605.15625)

ColPackAgent is an AI agent for Hard Particle Monte Carlo simulations. It is
built on the [`colpack`](https://pypi.org/project/colpack/) simulation package,
which is also available standalone via `pip install colpack` for users who
want the simulation engine and MCP tool surface without the full agent stack.

## Development and Validation

AI coding assistants were used for portions of the implementation and documentation. The generated code was reviewed by the authors before inclusion. Validation tests are included for the core `colpack` simulation package, MCP tool layer, wrapper configuration, and evaluation runner under `tests/`; run them with:

```bash
pytest tests
```

## Manuscript Artifacts and Reproduction Map

The submitted manuscript sources and compiled PDFs are under
`manuscript/ornl_latex/`. The table below maps the main paper figures and
results to the repository artifacts used to prepare them. No new simulations are
required to inspect the submitted results; the listed commands are only for
regenerating plots or rerunning workflows. Large raw trajectory files (`.gsd`)
are not tracked for the manuscript demo and autoresearch runs; the committed
artifacts are the configurations, analysis JSON, logs, generated plots, reports,
and benchmark transcripts needed to inspect the submitted results.

| Paper item | Manuscript asset | Source data / script | Notes |
| --- | --- | --- | --- |
| Agent-platform comparison | `manuscript/ornl_latex/opencode_colpack.pdf` | `plot/figures/opencode_colpack.pdf`, `plot/figures/opencode_colpack.pptx`, screenshots in `plot/figures/opencode/` | Figure assembled from recorded agent-client screenshots. |
| ColPackAgent architecture | `manuscript/ornl_latex/agent_architecture.pdf` | `plot/figures/agent_architecture.pdf`, `plot/figures/agent_architecture.pptx` | Schematic figure. |
| Supported hard-particle shapes | `manuscript/ornl_latex/colpack_illustration.pdf` | `plot/figures/colpack_illustration.pdf`; illustrative setup data in `plot/illustrative_data/2d_building_blocks/` and `plot/illustrative_data/3d_building_blocks/`; generator `plot/run_illustrative_shapes.py` | Small illustrative cases used for the shape catalogue. |
| Interactive cube NPT example | `manuscript/ornl_latex/demo_interactive.pdf` | Archived runs in `plot/illustrative_data/3d_npt_cube_interactive/`; plotting function `plot/demo_plot.py::plot_interactive_demo` | Contains setup/plan/status files and per-run analysis JSON. |
| Autonomous disk-capsule NVT example | `manuscript/ornl_latex/demo_autonomous.pdf` | Archived runs in `plot/illustrative_data/2d_nvt_capsule_disk/`; plotting function `plot/demo_plot.py::plot_autonomous_demo` | Contains setup/plan/status files and per-run analysis JSON. |
| Autoresearch hard-disk transition | `manuscript/ornl_latex/autoresearch.pdf`; SI plots `fig_eta_vs_P.png`, `fig_psi6_vs_P.png`, `fig_rdf.png`, `fig_eta_traces.png` | Research program `demo/specs/assisted_study_program.md`; archived run output in `demo/data/autoresearch_0629/`; agent report `demo/data/autoresearch_0629/freezing_transition_report.md`; analysis script `demo/data/autoresearch_0629/analyze_freezing.py` | This is the revised run reported in the manuscript. |
| LLM benchmark figure | `manuscript/ornl_latex/llm_eval.pdf` | Benchmark summaries in `eval/runs/<model>/<stage>/summary.json`; raw records in `results.jsonl`; transcripts in `conversations/`; task/spec files in `eval/tasks/` and `eval/specs/`; plotter `plot/eval_plot.py` | Regenerate the figure from archived summaries with `cd plot && python -c "from eval_plot import plot_llm_eval; plot_llm_eval(show=False)"`. |

The benchmark runner itself is documented in `eval/README.md`. For example,
`python -m eval.run_experiments plan --all-specs --models qwen3-next-80b-instruct`
prints the planned run matrix without making LLM calls, while `run` executes the
same specs and writes `planned_runs.json`, `results.jsonl`, `summary.json`, and
conversation transcripts under `eval/runs/`.

## 🚀 How to Use ColPackAgent

All launch modes are managed by `run_colpack.sh`. Run it without arguments to see available options:

```bash
./run_colpack.sh
# Usage: ./run_colpack.sh [standalone|opencode|claude|gemini|codex|setup]
```

### One-time setup

After cloning or when the skill path changes, register the ColPack skill with your AI clients:

```bash
./run_colpack.sh setup
```

This symlinks `agent/skills/colpack` into the skill directories of Claude Code, Gemini CLI, and Codex.

### Route 1: Standalone Terminal App

Runs the AI agent directly from the terminal using the OpenCode SDK runner (`agent/app.py`):

```bash
./run_colpack.sh standalone
```

### Route 2: AI IDE / Coding Assistant

Launch ColPackAgent inside your preferred AI client. Each mode loads the MCP tool server, agent prompt, and ColPack skill automatically:

| Command | Client |
|---------|--------|
| `./run_colpack.sh opencode` | OpenCode (`agent/opencode.json`) |
| `./run_colpack.sh claude` | Claude Code (`agent/claude_mcp.json`) |
| `./run_colpack.sh gemini` | Gemini CLI (`agent/.gemini/settings.json`) |
| `./run_colpack.sh codex` | Codex (`~/.codex/config.toml`) |

## Setup

`colpack` depends on `hoomd-blue` and `ovito`, which are not on PyPI and are
distributed through conda-forge. The commercial Anaconda distribution is not
required; Miniforge, Mamba, micromamba, or another conda-forge-compatible
environment manager is sufficient. The recommended setup is a conda-forge
environment for those two dependencies, then `pip install colpack` on top.

### 1. Create and activate the conda environment

```bash
conda create -n colpack python=3.11
conda activate colpack
conda install -c conda-forge hoomd ovito
```

### 2. Install the colpack package

From PyPI (the standard path):

```bash
pip install colpack
```

For development on the package itself, install editable from the cloned repo
instead:

```bash
pip install -e ./src
```

### 3. Install agent dependencies

```bash
pip install -r agent/requirements.txt
```

### 4. Verify installation

```bash
python -c "import sys, colpack; print(sys.executable); print(colpack.__file__)"
which colpack-mcp
```

`which colpack-mcp` should point to your active conda environment path.

### 5. Install opencode (or alternative AI client) and link the skill

```bash
curl -fsSL https://opencode.ai/install | bash
./run_colpack.sh setup
```

## Quick Troubleshooting

- Symptom: `ModuleNotFoundError: No module named 'colpack'`
- Fix: reactivate the conda env and reinstall — `pip install --force-reinstall colpack`
  (or `pip install -e ./src --no-deps --force-reinstall` if you use the editable install).

- Symptom: `which colpack-mcp` points to the wrong python environment
- Fix: reactivate the env and reinstall the package as above.
