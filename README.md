# ColPackAgent

ColPackAgent is an AI agent for Hard Particle Monte Carlo simulations.

## 🚀 How to Use ColPackAgent

ColPackAgent provides two ways to run the AI physics assistant: as a standalone terminal app, or as a native skill inside your favorite AI IDE (Claude Code, OpenCode, Cursor, etc.).

### Route 1: Standalone Terminal App (Recommended for standard users)
Run the AI directly from your terminal. The app will automatically connect the physics engine to the AI.
1. Install the physics package and tools: `pip install -e ./src/`
2. Install the agent dependencies: `pip install -r agent/requirements.txt`
3. Launch the agent: `python agent/app.py`

### Route 2: Bring Your Own Agent (For AI IDE users)
If you already use an AI coding assistant, you can give it the ColPack skill directly.
1. Install the tools to your environment: `pip install -e ./src/`
2. Add the FastMCP server to your IDE's tool registry. For example, in OpenCode or Claude Code, run:
   `mcp add colpack-tools command colpack-mcp`
3. Point your AI to the skill instructions: Tell your agent to read `agent/skills/colpack/SKILL.md` and begin the workflow.

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

### 4. Verify installation

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

## Use OpenCode

```bash
opencode --config agent/agent_config.json
```

## Quick Troubleshooting

- Symptom: `ModuleNotFoundError: No module named 'colpack'`
- Fix: reinstall with active env interpreter.
- Command: `python -m pip install -e ./src --no-deps --force-reinstall`

- Symptom: `which colpack-mcp` points to wrong python environment
- Fix: reactivate env and reinstall package as above.
