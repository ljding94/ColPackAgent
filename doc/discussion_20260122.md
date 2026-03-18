Here's the updated **project summary** with the benchmarking section integrated naturally. I've kept the structure clean and professional, suitable for a README, grant proposal, or early draft of your research paper introduction/abstract.

### Project Vision: Democratizing Mixed Colloids Simulations via Agentic AI

**Goal**: Build an **AI-assisted simulation platform** that enables experimentalists without computational or programming background (e.g., chemists, materials scientists, biologists) to perform realistic molecular dynamics simulations of **mixed colloid systems** using natural language prompts — no need to write HOOMD-blue code, manage HPC job scripts, handle SSH/Slurm, or debug trajectories.

- **Core Simulation Engine**: HOOMD-blue (GPU-accelerated, open-source MD package optimized for colloidal and soft matter systems).
- **Scientific Scope**: Phase behavior in binary/higher mixtures, self-assembly, depletion-driven crystallization, rheological response, stability under flow, optical/scattering properties, active colloids, etc. — a highly versatile domain with broad experimental relevance.
- **Ultimate User Experience**: Turn weeks/months of setup and debugging into an “ask-and-get-results” workflow, producing equilibrated snapshots, production trajectories, key observables (RDF, MSD, cluster statistics, energy profiles), visualizations, and interpretable summaries.

### Core Technology Stack: OpenCode + Agent Skills

**Why OpenCode** (opencode.ai) was selected over orchestration-heavy frameworks (CrewAI, AutoGen, LangGraph):

- Native **human-in-the-loop** support via terminal/IDE integration — ideal for scientific iteration, code review, mid-run adjustments, and debugging.
- Built-in **coding agents** (Plan, Build, custom) that generate, modify, and test HOOMD-blue Python scripts on-the-fly with LSP awareness.
- Strong **agent skills extensibility** through subagents, automatic invocation, custom tools, and MCP (Model Context Protocol) servers — perfect for chaining simulation stages and integrating HPC workflows.
- High **project updatability** — the entire system lives in your repository; agents can evolve code, prompts, and tools as new colloid phenomena or analysis needs arise.
- Model-agnostic design (supports 75+ providers including OpenAI, Anthropic, Google, local LLMs) — enables rigorous benchmarking of LLM performance.

This approach prioritizes developer/researcher control and iterative refinement over fully hands-off orchestration, making it especially suitable for evolving scientific codebases.

### Multi-Agent Architecture in OpenCode

A primary **ColloidSimCoordinator** agent orchestrates the workflow, automatically delegating to specialized subagents based on task needs. Runs autonomously (`--autonomous` mode) when trusted, with seamless interactive overrides.

1. **Input / Setup Agent**
   Parses natural-language description → extracts parameters (sizes, ratios, potentials, kT, steps, volume fraction, etc.) → generates templated HOOMD-blue initialization code.

2. **Initial State & Thermalization Agent**
   Creates snapshot (random/hcp/LJ/Yukawa placement) → adds forces → runs equilibration (Langevin/NVT/NPT) → validates stability → outputs equilibrated `.gsd` file.

3. **Simulation Runner Agent**
   Configures production MD parameters → performs short local validation run → delegates large-scale jobs to the HPC Agent.

4. **HPC Agent** (critical for accessibility)
   Skill: Secure SSH/SCP + Slurm/PBS interaction via custom tool or MCP server (using paramiko or similar).
   - Generates cluster-specific submission script (partition, GPUs, walltime, module load hoomd).
   - Submits (`sbatch`), polls status (`squeue/sacct`), retrieves outputs (trajectories, logs) on completion.
   - User-friendly interface: “Run on my cluster with 4 GPUs for up to 48 hours” — no manual commands exposed.

5. **Analysis & Reporting Agent**
   Processes GSD trajectories → computes observables (via freud/matplotlib if integrated) → generates plots, summary statistics, and Markdown/PDF report with plain-language interpretation.

**Execution Flow**: Natural-language prompt → task decomposition → sequential/parallel subagent calls → shared file/context persistence → final report. Autonomous for batch experiments; interactive pauses for scientific oversight.

### Benchmarking LLM Performance (for Research Paper Rigor)

To quantitatively evaluate and strengthen the scientific contribution, the system includes automated **benchmarking of different LLMs** across simulation stages:

- **Supported Models**: GPT-4o, Claude-3.5-Sonnet, Gemini-1.5-Pro, Llama-3.1-405B, local/self-hosted variants, etc.
- **Methodology**:
  - Scripted, non-interactive invocation via `opencode run` CLI (headless, `--autonomous`, `--model`, `--agent` flags).
  - 50–200 test cases per step (varied parameters, potentials, system sizes, intentional edge/malformed prompts).
  - Metrics: per-step and end-to-end **success rate** (% of runs producing valid, executable HOOMD-blue code; no crashes; plausible physical outputs).
  - Additional signals: code validity (sandbox execution), observable accuracy (RDF/MSD vs. reference), hallucination/error frequency, runtime, token cost.
- **Automation**:
  - Bash/Python loop over models × test prompts.
  - Output logging + automated scoring (keyword-based + HOOMD execution checks).
  - Results aggregated into CSV/tables for paper figures (e.g., success rate by model and simulation stage).
- **Research Value**: Enables ablation studies (prompt styles, tool usage, autonomous vs. interactive), cross-LLM comparisons, and insights into which models excel at code generation vs. physical reasoning in soft matter workflows.

This benchmarking component adds empirical depth to the paper, supporting claims about reliability, model choice, and the effectiveness of agentic workflows for computational soft matter research.

### Why This Combination Wins for Target Users

- Zero coding or HPC expertise required — prompt in English → receive trajectories, plots, and explanations.
- Iterative & scientific-friendly — “Rerun with stronger depletion” → agents reuse/adapt prior setup.
- Scales from laptop prototyping to HPC production runs.
- Teaches agent skills hands-on while producing publishable results.
- Positions the work at the intersection of agentic AI and accessible computational materials science.

If you'd like this expanded into a full README.md, LaTeX abstract/intro snippet, or the next concrete step (e.g., initial agent config files or the full benchmarking script with HOOMD validation), just let me know!




## more on the project structure and files


Yes, you can absolutely structure your project that way—putting the simulation-specific OpenCode configs (agents, prompts, etc.) in `./src/.opencode/` while keeping benchmark scripts and figure-plotting logic in `./benchmark/`—and still invoke the OpenCode agents from those benchmark scripts. This keeps things modular: the core simulation agents stay isolated in `./src/`, while benchmarks remain separate for clean organization and easier maintenance/paper reproducibility.

### Recommended Project Structure
Based on OpenCode's config resolution (it searches project-local `.opencode/` dirs, global `~/.config/opencode/`, and custom paths via env vars), here's how it fits:

```
mixed-colloids-project/
├── src/                  # Core simulation code and OpenCode setup
│   ├── .opencode/        # Project-specific OpenCode configs (agents, tools, etc.)
│   │   ├── agents/       # JSON/Markdown files for your agents (e.g., ColloidSimCoordinator.md, HPCAgent.json)
│   │   ├── commands/     # Custom commands if needed (e.g., for HPC submission)
│   │   ├── plugins/      # Any MCP servers or tools (e.g., hpc-tool.ts)
│   │   └── opencode.json # Optional root config for overrides (e.g., default model)
│   ├── hoomd_scripts/    # Generated/templated HOOMD-blue Python files
│   └── main.py           # Entry point for manual sim runs (optional)
├── benchmark/            # Benchmarking and analysis
│   ├── run_benchmark.sh  # Your benchmarking script (invokes OpenCode CLI)
│   ├── evaluate.py       # Scoring/figure plotting (e.g., matplotlib for success rate plots)
│   ├── prompts.json      # Test cases
│   └── results/          # Logs, CSVs, figures (e.g., success_rate_by_model.png)
├── README.md             # Project overview, including the summary we discussed
└── requirements.txt      # Deps (hoomd, freud, paramiko for HPC, etc.)
```

This aligns with OpenCode's conventions: `.opencode/` is per-project (or per-subdir like `./src/`), and it won't interfere with benchmarks since they're in a sibling dir.

### Invoking OpenCode Agents from Benchmark Scripts
OpenCode's CLI (`opencode run`) resolves configs hierarchically (local `.opencode/` first if in cwd, then global), but you can override this in scripts to point to `./src/.opencode/` without manually cd-ing or opening the TUI. Use the `OPENCODE_CONFIG_DIR` env var to specify the custom config path—it's explicitly supported for this kind of flexibility.

In your `./benchmark/run_benchmark.sh` (or Python equivalent), add this before the opencode calls:

```bash
#!/usr/bin/env bash

# Set env var to point to the .opencode dir (use absolute path for reliability)
export OPENCODE_CONFIG_DIR="$(pwd)/../src/.opencode"  # Or hardcode /full/path/to/project/src/.opencode

# Rest of your script...
MODELS=("openai/gpt-4o" "anthropic/claude-3.5-sonnet")
# ...
opencode run --model "$model" --agent ColloidSimCoordinator --autonomous "$prompt" > "$output_file"
```

- **How it works**: When you run the script from `./benchmark/`, OpenCode will search the specified `OPENCODE_CONFIG_DIR` for agents/commands/plugins, treating it like a local `.opencode/`. Your custom agents (e.g., ThermalizationAgent) will load as if you were in `./src/`.
- **Fallback**: If env var isn't set, cd temporarily in the script: `pushd ../src; opencode run ...; popd`.
- **For plotting figures**: In `evaluate.py`, after aggregating CSVs, use matplotlib/seaborn to generate plots (e.g., bar charts of success rates). No OpenCode involvement needed there—it's pure Python.

This setup ensures benchmarks can invoke simulation agents seamlessly, producing data for your paper without duplicating configs.

If you run into path issues (e.g., relative file refs in agents), test with a small script first or add absolute paths in prompts/tools. For more advanced benchmarking (e.g., parallel runs), consider wrapping in Python with `subprocess` for finer control. Let me know if you want tweaks to the script!