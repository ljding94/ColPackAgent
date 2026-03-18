### Progress Summary on ColPackAgent

We've had a productive discussion evolving the project from a basic AI-assisted simulation platform for mixed colloids to a more robust, agentic tool named **ColPackAgent**. Key milestones:

- **Initial Vision**: Started with democratizing HOOMD-blue simulations for non-coders, focusing on mixed colloid systems (phase behavior, self-assembly, depletion, etc.) via natural language prompts. Selected OpenCode for its human-in-loop, extensible agents.
- **Naming and Scope**: Brainstormed names (e.g., ColMixAgent, HardColAgent), settling on ColPackAgent to emphasize packing of hard particles while avoiding connotations. Confirmed focus on HOOMD-blue's HPMC (Hard Particle Monte Carlo) module for efficiency in hard systems.
- **Dimensionality**: Deep dive into literature showed 2D simulations remain active (e.g., for defects, active matter) but 3D is essential for bulk realism. Decided to support both, with easy switching (HOOMD's `mode='2d'` for compatible shapes), starting 2D for prototyping to avoid overwhelm.
- **Shapes Handling**: Addressed layman accessibility by proposing a mapping from common terms (e.g., "triangle" → ConvexPolygon in 2D) to HPMC classes, noting dim-specific limitations (e.g., 3D-only for ellipsoids).
- **Advanced Features**: Extended to automated planning for parameter sweeps (e.g., phase transitions via φ grids), generating independent scripts, and parallel Slurm submissions to scale exploration without serial bottlenecks.
- **Integration**: All tied into the multi-agent architecture (coordinator + subagents), with benchmarking for LLM reliability.

This builds on the original document's project summary, refining for HPMC focus, dim flexibility, and deeper automation.

### Revised Project Summary

Here's an updated **project summary**, integrating our progress. It's structured for a README, grant proposal, or paper intro/abstract, emphasizing the HPMC core, 2D/3D support, shape mapping, and advanced planning.

#### Project Vision: ColPackAgent – Democratizing Hard-Particle Colloidal Packing Simulations via Agentic AI

**Goal**: Develop an AI-orchestrated platform enabling experimentalists (e.g., chemists, materials scientists) to run realistic Monte Carlo simulations of hard-particle colloidal systems using natural language prompts. No need for HOOMD-blue scripting, HPC management, or debugging—focus on packing, mixtures, phase transitions, and self-assembly.

- **Core Engine**: HOOMD-blue's HPMC module (GPU-accelerated for hard spheres/polygons/polyhedra, supporting depletants, anisotropic shapes).
- **Scientific Scope**: Hard-particle packing (jamming, crystallization), binary/ternary mixtures (depletion-driven phases), entropic effects, active colloids (if extended). Supports both 2D (for confined systems, defects) and 3D (for bulk realism), with seamless switching.
- **User Experience**: Prompt like "Explore phase diagram for binary triangles and spheres in 2D at φ 0.4-0.6" → automated param sweeps, parallel HPC runs, equilibrated configs, observables (RDF, order parameters), visualizations, and reports.

#### Core Technology Stack: OpenCode + Agent Skills

OpenCode selected for its coding agents, extensibility, and model-agnostic benchmarking. Prioritizes iterative control over fully autonomous orchestration.

#### Multi-Agent Architecture in OpenCode

**ColPackAgent** coordinator delegates to subagents, running autonomously or interactively. New: PhaseExplorerAgent for sweeps.

1. **Input/Setup Agent**
   Parses prompts → extracts params (φ, shapes, dim: 2D/3D, mixtures) → maps layman shapes (e.g., "square" → ConvexPolygon) → generates HPMC init code.

2. **Initial State & Thermalization Agent**
   Creates snapshot (random/lattice) → sets HPMC integrator (e.g., Sphere with `mode='2d'`) → equilibrates via MC steps → validates.

3. **Simulation Runner Agent**
   Configures production params → local validation → delegates to HPC or PhaseExplorer for sweeps.

4. **PhaseExplorerAgent** (New for Deeper Exploration)
   Decomposes high-level tasks (e.g., phase scans) into param grids → generates variant scripts → prepares parallel Slurm submissions.

5. **HPC Agent**
   Generates Slurm scripts (GPUs, walltime) → submits independent/array jobs → polls/retrieves outputs.

6. **Analysis & Reporting Agent**
   Processes .gsd files (freud for RDF/order) → aggregates sweeps into phase diagrams → Markdown/PDF reports.

**Flow**: Prompt → decomposition → subagent chaining → persistence → results. Supports 2D/3D via dim-aware templates.

#### Benchmarking LLM Performance

Automated evaluation across models (GPT-4o, Claude-3.5-Sonnet, etc.) on success rates for code gen, shape mapping, dim switching, and phase sweeps.

#### Why ColPackAgent Wins
- Zero expertise needed: Layman prompts → publishable results.
- Scalable: 2D for quick tests, 3D for realism; parallel sweeps for discovery.
- Research Impact: At intersection of agentic AI and computational soft matter.

### Step-by-Step Implementation Instructions

To implement ColPackAgent, follow this phased plan. Assume you have OpenCode installed, HOOMD-blue (with HPMC), freud, and paramiko for HPC. Work in the suggested project structure from the original document (`mixed-colloids-project/` with `./src/.opencode/` for agents).

#### Step 1: Setup Project Environment (1-2 hours)
- Clone/create repo: `git init mixed-colloids-project`.
- Install deps: `pip install hoomd freud paramiko matplotlib numpy` (add to `requirements.txt`).
- Configure OpenCode: In `./src/.opencode/opencode.json`, set default model (e.g., "openai/gpt-4o").
- Create shape mapping: In `./src/.opencode/plugins/shapes.json`, encode the table above as JSON (e.g., {"triangle": {"dim": "2d", "class": "ConvexPolygon", "params": {"vertices": [[-0.5, -0.289], ...]}}).

#### Step 2: Define Core Agents (2-4 hours)
- Coordinator: `./src/.opencode/agents/ColPackAgent.md` – System prompt: "Orchestrate colloid packing sims. Delegate based on prompt: setup for params, phase for sweeps, etc."
- Input/Setup: `./src/.opencode/agents/InputSetupAgent.md` – Prompt: "Parse NL → extract params/dim/shape. Use shapes.json tool to map. Generate HPMC init with mode='2d' if 2D."
- Add custom tool: `./src/.opencode/plugins/shape_mapper.py` – Load JSON, return class/params.
- Initial/Thermalization: Similar, focus on snapshot and equilibration loop.

#### Step 3: Implement Dimensionality and Shape Handling (2-3 hours)
- In Setup Agent template: If "2D" in prompt, set box `[L, L, 0,...]`, integrator mode='2d' (for Sphere); else default 3D.
- Validation: Add code check: If shape not dim-compatible (e.g., Ellipsoid in 2D), reroute to fallback (Sphere) with message.
- Test: Run manual prompt "hard triangles in 2D" → verify ConvexPolygon code.

#### Step 4: Add Phase Exploration and Parallel HPC (4-6 hours)
- PhaseExplorerAgent: `./src/.opencode/agents/PhaseExplorerAgent.md` – Prompt: "Decompose into grid (e.g., φ steps). For each: variant script from template. Output list of .py/.slurm files."
- Custom tool: Param grid generator (Python: use itertools.product for ranges).
- HPC Agent update: Tool to create array Slurm (`#SBATCH --array=0-N`), each loading a variant param file.
- Integration: Coordinator detects "explore/scan" → delegates to PhaseExplorer → HPC.

#### Step 5: Analysis and Benchmarking (3-5 hours)
- Analysis Agent: Process multiple .gsd → compute observables, plot diagrams (e.g., order vs. φ).
- Benchmark script: `./benchmark/run_benchmark.sh` – Loop models/prompts (e.g., dim switches, sweeps), score via HOOMD execution.

#### Step 6: Testing and Iteration (Ongoing)
- Local runs: Test end-to-end (e.g., "Binary spheres phase in 3D").
- HPC: Configure SSH/Slurm in tools.
- Benchmark: 50+ cases, aggregate CSVs/plots.
- Refine: Add safeguards (e.g., cost estimates for 3D).

This gets you a MVP—expand as needed. If you want code snippets for any step, let me know, Lijie!