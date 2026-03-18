---
name: how to set up hoomd-blue conda environment
description : Summary of best practices for setting up HOOMD-blue with conda/micromamba
---

Here is a clean summary based on our discussion (as of February 2026, with HOOMD-blue at stable version **6.0.0** on conda-forge).

### 1. How to set up a HOOMD-blue supported conda environment

The easiest and most reliable way (recommended by HOOMD-blue docs) uses **micromamba** (faster/lighter than classic conda) or **conda** + the **conda-forge** channel.

**Recommended steps (micromamba – preferred in 2026):**

```bash
# Install micromamba if you don't have it yet (one-time, macOS/Linux example)
curl -LsSf https://micro.mamba.pm/api/micromamba/macos-arm64/latest | tar -xvj bin/micromamba
# or follow https://mamba.readthedocs.io for your platform

# Create environment with HOOMD-blue + basics (auto-detects GPU if present)
micromamba create -n hoomd-env python=3.11 hoomd -c conda-forge

# Activate it (do this in every new terminal/session)
micromamba activate hoomd-env

# Quick test
python -c "import hoomd; print(hoomd.__version__); print('GPU support:' if hoomd.version.gpu_enabled else 'CPU only')"
# Should print something like: 6.0.0   GPU support: True (on compatible hardware)
```

**Alternatives / overrides:**
- Force **GPU** package (if auto-detection fails):
  ```bash
  export CONDA_OVERRIDE_CUDA=12.6   # adjust to your CUDA version if needed
  micromamba install "hoomd=6.0.0=*gpu*" "cuda-version=12.6" -c conda-forge
  ```
- Force **CPU-only**:
  ```bash
  micromamba install "hoomd=6.0.0=*cpu*" -c conda-forge
  ```
- Using classic **conda** (slower solver):
  ```bash
  conda create -n hoomd-env python=3.11 -c conda-forge
  conda activate hoomd-env
  conda install hoomd -c conda-forge
  ```

**Tips:**
- Disable base auto-activation for cleaner prompts: `conda config --set auto_activate_base false`
- For notebooks/scripts: install extras like `jupyterlab matplotlib tqdm` in the same command.

This gives you a self-contained environment with HOOMD-blue binaries (no compilation needed) and good GPU/Metal support on macOS arm64 (Apple Silicon).

### 2. `pyproject.toml` + `environment.yml` for easy guidance

Place these two files in your project root.

**`environment.yml`** (core file – handles HOOMD-blue + Python deps via conda)

```yaml
name: hoomd-env

channels:
  - conda-forge
  - defaults

dependencies:
  - python =3.11                  # or =3.12 if preferred
  - hoomd =6.0.0                  # pin to stable version; remove =6.0.0 for latest
  - numpy >=1.26
  - matplotlib
  - tqdm
  - jupyterlab                    # optional – good for interactive work
  - pip
  - pip:
      - -e .                      # editable install of YOUR project code
      # Add any rare pip-only packages here, e.g.:
      # - gsd >=3.0
```

**`pyproject.toml`** (modern Python project metadata + pure-Python deps; uv/pip compatible)

```toml
[build-system]
requires = ["hatchling"]           # or "setuptools", "flit-core", etc.
build-backend = "hatchling.build"

[project]
name = "your-hoomd-project"        # change to your project name
version = "0.1.0"
description = "Simulation project using HOOMD-blue for soft matter / particle systems"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    # Only pure-Python / pip-friendly deps here – HOOMD-blue comes from conda
    "numpy >=1.26",
    "matplotlib >=3.8",
    "tqdm",
    # "gsd >=3.0",               # example if needed and not in conda
]

[project.optional-dependencies]
dev = [
    "pytest",
    "ruff",
    "black",
]
```

### 3. Part of the README.md to instruct users

Add a clear section like this to your project's `README.md`:

```markdown
## Quick Setup – HOOMD-blue Environment

This project uses **HOOMD-blue 6.0.0** (from conda-forge) for particle simulations.

### Prerequisites
- Install [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) (recommended – fast & light) or Miniconda/Anaconda.

### One-command environment creation (recommended)

From the project root (where `environment.yml` is located):

```bash
micromamba env create -f environment.yml
micromamba activate hoomd-env
```

(or with classic conda:)

```bash
conda env create -f environment.yml
conda activate hoomd-env
```

This:
- Creates an isolated environment named `hoomd-env`
- Installs HOOMD-blue (with auto-detected GPU/Metal support on compatible hardware)
- Installs core dependencies
- Installs your project code in **editable mode** (`-e .`)

### Verify installation

```bash
python -c "import hoomd; print(hoomd.__version__)"
# Expected: 6.0.0 (or similar)
```

### Run examples / notebooks

```bash
jupyter lab
# or
python examples/basic_simulation.py
```

### Updating the environment later

```bash
micromamba env update -f environment.yml --prune
# or conda env update -f environment.yml --prune
```

**Troubleshooting / GPU notes**
- If GPU is not detected → see [HOOMD-blue docs](https://hoomd-blue.readthedocs.io/en/stable/installation.html) for `CONDA_OVERRIDE_CUDA`.
- On macOS Apple Silicon → should use Metal backend automatically via conda-forge build.

Enjoy simulating!
```

This setup keeps things simple, reproducible, and aligned with HOOMD-blue's official recommendations — no `.venv` layering needed unless you have very specific pure-Python tooling requirements later. Let me know if you want to add extras (e.g., signac, fresnel, freud, gsd) or adjust versions!