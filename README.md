# ColPackAgent

ColPackAgent is a soft-matter simulation workflow package with an MCP server interface.

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
