---
name: colpack
description: "End-to-end ColPack colloidal packing simulation workflow. Use for setting up, planning, executing, and analyzing hard-particle NVT/NPT Monte Carlo simulations using HOOMD-blue. Triggers on requests like 'run a packing simulation', 'simulate colloidal particles', 'sweep volume fractions', 'compress hard spheres', 'set up an NVT/NPT simulation', or 'plan a parameter sweep for disks and capsules'."
---

# Operating Rules
1. **At the start of every session**, call `get_colpack_capabilities_tool` (no parameters) to retrieve supported dimensions, shapes, ensembles, key parameters, and workflow step descriptions from the live config. Use this output as ground truth — never hard-code shape names or ensemble keys.
2. Follow the workflow sequence exactly: Setup -> Plan -> Execute -> Analyze.
3. Never skip a step when creating a new workflow from scratch.
4. Before each tool call, read the corresponding reference file in `references/` and follow its schema and examples.
5. Use one shared `working_dir` for the full workflow; keep it unchanged across all three tool calls. Let `setup_simulation_problem_tool` determine the canonical path; reuse the returned value verbatim in planning and execution.
6. Keep tool payloads strict and minimal: only include required keys and valid values.
7. If execution returns `n_failed > 0`, read `workflow_status.csv` before responding.
8. Use ColPack MCP tools directly for simulation requests. Do not start with `glob`, `read`, or `bash` unless diagnosing a failure or answering a codebase question.

# Mode Contract
Two execution modes exist. Pick the mode from the explicit wrapper flag when present, otherwise from prompt specificity (see "Prompt Specificity Heuristic" below).

The wrapper may append `AGENT_MODE = interactive` or `AGENT_MODE = autonomous`.

- **Interactive** (default when no mode is set, OR when the prompt is ambiguous):
  - Handle one workflow stage at a time. **One stage per turn, strictly.** After setup is confirmed, move on to planning in a new turn — never ask setup and planning questions in the same message.
  - Ask only the missing inputs needed for the current stage — do not ask for later-stage parameters (see each reference file for what belongs to that stage). Volume fraction, pressure sweeps, and sampling steps are **planning-stage**, never setup.
  - Do not ask for `working_dir` at any stage; setup resolves it from its inputs (see `references/1_setup_problem.md`).
  - Merge incremental follow-up replies into the active workflow context instead of restarting the checklist.
  - Show the intended payload and wait for explicit approval before each tool call.
  - After each stage completes, ask whether to continue to the next stage, revise, or redo — then wait.
- **Autonomous**:
  - Use only when the user asks for an end-to-end run AND supplies enough detail for the current stage (or explicitly authorizes defaults).
  - Complete all stages end-to-end without per-stage approval.
  - Ask only blocking clarification questions.

## Prompt Specificity Heuristic

Before acting, classify the user prompt:

- **Specific / end-to-end**: names a full workflow intent (e.g. "run an end-to-end sweep", "compress and analyze", "do the whole pipeline") AND supplies the required inputs for the stages it covers, OR explicitly says "use defaults" / "pick reasonable values". → Run autonomously.
- **Ambiguous / partial**: mentions only a shape, a goal, or a stage ("set up a simulation for cubes", "run a packing simulation", "simulate some disks") without specifying the stage-required inputs. → Treat as interactive, even if no `AGENT_MODE` flag is set. Ask for the missing setup-stage inputs before calling any tool.

## No-Silent-Defaults Rule

**Never fill setup-required parameters with defaults silently.** The setup stage requires `dimension`, `total_particle_number`, `particle_shape_list`, and `ensemble`. If any of these is missing from the user's prompt and not inferable, ask a single consolidated clarification question listing the missing fields with suggested common choices, then wait. Inferable exceptions:

- `dimension` is inferable when every named shape is dimension-locked (e.g. "cube", "tetrahedron", "octahedron" → 3D; "disk", "triangle", "square", "rectangle", "ellipse" → 2D). `capsule` and `ellipsoid` alone are not inferable. When inferring, state the inference in the clarification message so the user can override.
- `particle_shape_list` is taken verbatim from the user's named shape(s).

`ensemble` and `total_particle_number` are never inferable — always ask if absent.

The same principle extends to later stages: do not silently pick sweep ranges, volume fractions, pressures, or sampling steps. Ask or show a proposed plan for approval first.

# Workflow Steps

| Step | Tool | Reference | Output |
|------|------|-----------|--------|
| Capabilities | `get_colpack_capabilities_tool` | — | Supported shapes, ensembles, key parameters (call once at session start) |
| Setup | `setup_simulation_problem_tool` | `references/1_setup_problem.md` | `simulation_problem.json` in `working_dir` |
| Plan | `plan_simulation_runs_tool` | `references/2_plan_runs.md` | `simulation_baseline.json`, `simulation_plan.json`, `run_*/` |
| Execute | `execute_simulation_workflow_tool` | `references/3_execute_simulation.md` | Completed initialize/compress/sample steps; `workflow_status.csv` |
| Analyze | `analyze_simulation_runs_tool` | `references/4_analyze_simulation.md` | Order parameters, RDF, plots per run; `workflow_status.csv` updated |

Before each step, read the reference file listed above and follow its rules for payload construction, validation, and error handling.

# Progress Monitoring

Async execute/analyze jobs write progress to `workflow_progress.json` and `workflow_events.log` in `working_dir`. The standalone wrapper auto-runs `scripts/workflow_monitor.py` in the background; it tails those files and prints `[workflow] completed: N/N success, M failed` to the user's terminal when the job ends — independent of the agent's turn. **Do not roll your own polling, `tail -f`, or `while/sleep` loops.**

The same script exposes two CLI subcommands for the agent to invoke via `Bash`:

```bash
# One-shot — JSON on stdout, exit 0 if present, 1 if missing.
python agent/skills/colpack/scripts/workflow_monitor.py status --working-dir <WD>

# Blocks until terminal state — exit 0 = completed, 1 = failed / timeout.
python agent/skills/colpack/scripts/workflow_monitor.py wait --working-dir <WD> [--timeout N]
```

- **"Let me know when it's done" / "run analysis when it finishes"** → call `wait`, tell the user you're blocking on it, then chain the next action on exit 0.
- **"What's the status?"** → call `status` once; report `status`, `n_success/n_runs`, `n_failed`, `current_step`. Do not loop.
- On `n_failed > 0`, read `workflow_status.csv` before responding.

# Response Style
1. Confirm current workflow step and target directory.
2. Show the exact tool call payload before execution when helpful.
3. After each tool call, summarize what files were created or updated.
4. For failures, provide diagnosis first, then remediation.
