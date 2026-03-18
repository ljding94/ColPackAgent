To configure your ColPackAgent project for seamless development on your local machine (with HOOMD-blue already installed in a conda environment) and deployment to a DGX remote machine with 8 A100 GPUs, focus on reproducibility, minimal manual setup on the remote, and leveraging the existing HPC Agent in your OpenCode architecture. Since HOOMD-blue is primarily distributed via conda-forge (not pip/venv), we'll stick to conda for environment management. This avoids compatibility issues with GPU acceleration (CUDA support is baked into the conda package).

The goal is to make the remote "pick up" the setup easily: automate environment replication, code transfer, and job execution via your agents, without requiring you to manually SSH in every time. We'll build on the project structure from our discussions (e.g., `./src/.opencode/` for agents, generated HOOMD scripts, etc.), and enhance the HPC Agent's skills for DGX-specific handling.

### Step 1: Local Development Setup (What You Already Have + Enhancements)
- **Conda Environment**: You're good here—assume your local env is named `colpack` (or similar) with HOOMD-blue installed (`conda install -c conda-forge hoomd freud matplotlib paramiko` for core deps like analysis, plotting, and SSH).
  - Export it for reproducibility: Run `conda env export --name colpack > environment.yml` in your project root. This creates a YAML file listing all packages (including HOOMD-blue with CUDA support).
  - Add any project-specific deps (e.g., OpenCode CLI if not global) to `requirements.txt` for pip-installed items, but keep HOOMD conda-only.
- **Project Structure Refinements**: Stick to the recommended layout, but add remote-friendly elements:
  ```
  mixed-colloids-project/  # Or rename to colpack-agent/
  ├── src/
  │   ├── .opencode/
  │   │   ├── agents/  # Update HPCAgent.md/json with DGX specifics (see below)
  │   │   └── ...      # Other agents (ColloidSimCoordinator, etc.)
  │   └── hoomd_scripts/  # Templates or generated .py files
  ├── benchmark/  # As before
  ├── environment.yml     # Exported conda env for remote replication
  ├── setup_remote.sh     # One-time remote setup script (see Step 2)
  ├── README.md           # Add a "Deployment to DGX" section
  └── .gitignore          # Ignore conda env dirs, GSD files, etc.
  ```
- **Test Locally**: Develop and iterate agents in OpenCode locally (e.g., `opencode run --agent ColloidSimCoordinator --autonomous "Simulate binary colloid mixture at phi=0.55"`). Use your local conda env for HOOMD executions—agents can activate it via shell commands in tools (e.g., `conda activate colpack && python script.py`).

### Step 2: One-Time Remote DGX Setup (Minimal Manual Step)
DGX systems (NVIDIA's) typically have conda pre-installed, CUDA drivers, and Slurm for job scheduling. To make it "easy to pick up," create a simple bash script (`setup_remote.sh`) that you run once via SSH on the DGX. This replicates the env and clones your repo—no ongoing manual work needed.

```bash
#!/bin/bash

# Run this once on DGX via SSH: scp setup_remote.sh user@dgx-host:~ && ssh user@dgx-host ./setup_remote.sh

# Clone project (assume GitHub repo; replace with your URL)
git clone https://github.com/yourusername/colpack-agent.git ~/colpack-agent
cd ~/colpack-agent

# Create conda env from yml (HOOMD-blue will install with CUDA support automatically)
conda env create -f environment.yml

# Install OpenCode CLI if not global (adjust if using a virtualenv for OpenCode)
conda activate colpack
pip install opencode-interpreter  # Or your OpenCode install method

# Optional: Set up persistent storage for outputs (e.g., trajectories)
mkdir -p ~/colpack-agent/outputs

# Test: Run a simple HOOMD script to verify GPU accel (8 A100s should auto-detect)
conda activate colpack
python -c "import hoomd; print(hoomd.device.GPU().get_num_available())"  # Should print 8 or similar

echo "Setup complete. Agents can now handle runs via HPC Agent."
```

- **Why this is easy**: You SCP and run this script once. It handles env creation (HOOMD-blue pulls CUDA libs via conda-forge), repo clone, and a quick GPU test. No venv needed—conda manages everything.
- **If DGX lacks conda**: Rare, but install Miniconda first (`wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && bash Miniconda3-latest-Linux-x86_64.sh`).
- **Security**: Use SSH keys for passwordless access (set up with `ssh-keygen` and `ssh-copy-id user@dgx-host`).

### Step 3: Configure Agents for Remote Deployment
Enhance your OpenCode agents (in `./src/.opencode/agents/`) to handle local vs. remote execution intelligently. The **HPC Agent** is perfect for this—extend its skills to detect/choose local (for dev) vs. DGX (for production/GPU speed).

- **Update HPC Agent Config** (e.g., in `HPCAgent.md` or JSON):
  - Add a tool/skill for environment checks: Use paramiko (Python SSH lib, already in your deps) to verify remote env on-the-fly.
  - Support local fallback: If prompt includes "run local" or env var `RUN_LOCAL=1`, execute in your local conda env instead of remote.
  - DGX-specific params: Hardcode or prompt for host (`dgx-host.yourdomain.com`), username, Slurm partition (e.g., `gpu`), GPUs (e.g., `--gpus-per-node=8`), modules (e.g., `module load cuda/12.0` if needed—DGX often has it default).
  - Example tool invocation flow (in agent prompt/description):
    ```
    If remote: Use SSH to SCP generated HOOMD script + inputs to ~/colpack-agent on DGX.
    Generate Slurm script: #SBATCH --nodes=1 --ntasks=1 --gpus-per-node=8 --time=48:00:00 --partition=gpu
    Activate env: source ~/miniconda3/etc/profile.d/conda.sh && conda activate colpack
    Run: python your_script.py
    Submit: sbatch job.slurm
    Poll: squeue -u $USER; on complete, SCP back outputs (GSD, plots, logs) to local.
    ```
  - Handle errors: If remote env missing, agent can auto-run a "setup" command via SSH (e.g., clone repo and create env from yml—embed the logic in a remote_setup.py tool).

- **ColloidSimCoordinator Agent Updates**: As the orchestrator, add logic to delegate to HPC Agent for production runs:
  - Prompt example: "For large systems (>10k particles) or speed, use remote DGX."
  - Use OpenCode's MCP servers or custom tools for SSH/SCP (paramiko-based; example code:
    ```python
    import paramiko
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect('dgx-host', username='youruser')
    # Exec commands or SCP files
    ```).
  - Autonomous mode: Default to remote for benchmarks/case studies; interactive mode: Ask user "Local or DGX?"

- **Environment Handling in Agents**:
  - Always activate conda env in generated scripts: `conda activate colpack` (or equivalent).
  - For GPU accel: HOOMD auto-detects A100s—use `hoomd.device.GPU()` in scripts. Agents can scale `--gpus-per-node` based on system size (e.g., 1-2 for small tests, 8 for large mixtures).

### Step 4: Deployment Workflow
1. **Develop Locally**: Code agents, test prompts, run small sims in your conda env. Git commit/push changes.
2. **One-Time Remote Setup**: Run `setup_remote.sh` via SSH—clones repo, creates matching env.
3. **Run via Agents**: From local, invoke OpenCode (e.g., `opencode run --agent ColloidSimCoordinator --autonomous "Sweep packing fractions in ternary colloid mixture"`). It delegates to HPC Agent, which:
   - SCPs updated code/scripts if needed (detect via git hash or timestamp).
   - Submits Slurm job on DGX (using the replicated env).
   - Polls and retrieves results back to local.
4. **Update Project**: If you tweak agents or env (e.g., add a dep), update `environment.yml`, git push, and have HPC Agent pull changes on remote before runs.
5. **Benchmarking**: From `./benchmark/run_benchmark.sh`, invoke agents as before— they'll handle local/remote based on flags (e.g., add `--remote` for DGX runs).

### Pros/Cons and Tips
- **Pros**: Minimal remote intervention (one-time setup); agents automate the rest. Leverages DGX GPUs for 10-100x speedups on large MC sweeps. Fully reproducible (yml + git).
- **Cons**: Initial SSH for setup; potential network latency for large file transfers (mitigate with compressed GSDs or remote storage mounts like NFS).
- **Tips**:
  - Test SSH tools locally first (e.g., paramiko to a loopback).
  - For security: Use SSH keys, avoid hardcoding passwords.
  - If DGX uses PBS instead of Slurm, swap submission commands in HPC Agent.
  - Scaling: For massive sims, agents can request more nodes (`--nodes=2` for 16 GPUs).
  - Costs: DGX is power-hungry—monitor usage if shared.

This config keeps development local/fast while offloading heavy compute to DGX effortlessly. If you need code snippets (e.g., paramiko tool or updated agent JSON), the full `setup_remote.sh`, or tweaks for your specific DGX setup (e.g., custom modules), let me know! 🚀