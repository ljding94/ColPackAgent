# ColPackAgent

ColPackAgent is an AI agent for Hard Particle Monte Carlo simulations.

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

This project relies on `hoomd-blue`, which is installed via conda.
Install and run everything from the conda environment first, then install the local `colpack` package.

### 1. Create the conda environment

From the project root:

```bash
conda env create -f environment.yml
```

If the environment already exists:

```bash
conda env update -f environment.yml --prune
```

### 2. Activate the environment

```bash
conda activate hoomd-env
```

### 3. Install local package (editable)

Install from `src` so CLI commands and imports are available in the active environment.

```bash
python -m pip install -e ./src --no-deps
```

Notes:

- `hoomd-blue` is managed by conda, not pip.
- Use `python -m pip ...` to ensure install goes to the active interpreter.

### 4. Install agent dependencies

```bash
pip install -r agent/requirements.txt
```

### 5. Verify installation

```bash
python -c "import sys, colpack; print(sys.executable); print(colpack.__file__)"
which colpack-mcp
```

`which colpack-mcp` should point to your active conda environment path.

## Run MCP Server

```bash
colpack-mcp
```

The command is expected to stay quiet in terminal because MCP stdio servers wait for a client connection.

## Quick Troubleshooting

- Symptom: `ModuleNotFoundError: No module named 'colpack'`
- Fix: reinstall with active env interpreter.
- Command: `python -m pip install -e ./src --no-deps --force-reinstall`

- Symptom: `which colpack-mcp` points to wrong python environment
- Fix: reactivate env and reinstall package as above.
