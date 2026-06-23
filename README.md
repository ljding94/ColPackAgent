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

`colpack` depends on `hoomd-blue` and `ovito`, which are not on PyPI and must
come from conda-forge. The recommended setup is a conda environment for those
two, then `pip install colpack` on top.

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
