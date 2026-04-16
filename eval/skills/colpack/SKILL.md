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

# Wrapper Contract
- Handle one workflow stage at a time.
- Ask only the missing inputs needed for the current stage — do not ask for later-stage parameters (see each reference file for what belongs to that stage).
- Merge incremental follow-up replies into the active workflow context instead of restarting the checklist.
- Show the intended payload and wait for explicit approval before each tool call.
- After each stage, ask whether to continue, revise, or redo.

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
Async execute and analyze jobs write progress to `workflow_progress.json` and `workflow_events.log` in the `working_dir`. The agent wrapper polls these files automatically via `scripts/workflow_monitor.py`. Do not poll status with MCP tools in a loop — let the local monitor surface updates.

# Response Style
1. Confirm current workflow step and target directory.
2. Show the exact tool call payload before execution when helpful.
3. After each tool call, summarize what files were created or updated.
4. For failures, provide diagnosis first, then remediation.
