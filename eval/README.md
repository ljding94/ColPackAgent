# Eval Scaffold

This folder is the experiment harness for comparing prompt variants, LLMs, and skill versions without changing `agent/app.py`.

The baseline skill used by eval lives under `eval/skills/colpack/`. This keeps experiment-specific skill edits and ablations separate from the production `agent/skills/colpack/` tree.

## Current Scope

The first version is meant to set the stage:

- define experiment specs in JSON
- expand specs into a run matrix over tasks, models, skills, and repeats
- run multi-turn task conversations against the standalone agent stack
- capture wall time, token usage, cost, and raw turn outputs
- keep result files separate from the interactive wrapper

## Entry Point

Use the module entry point from the repository root:

```bash
python -m eval.run_experiments plan --spec eval/experiment_spec.example.json
python -m eval.run_experiments run --spec eval/experiment_spec.example.json --dry-run
```

`plan` expands the matrix and can write a manifest.

`run` executes the planned runs sequentially and writes:

- `planned_runs.json`
- `results.jsonl`
- `summary.json`

under the experiment `output_dir`.

## Suggested User Types

These are the user archetypes worth covering as you build out the task set:

1. `novice_workflow_user`
   Asks for a simulation in plain language and relies on the agent to structure the workflow.
2. `partially_specified_user`
   Knows some simulation parameters but omits others, forcing the agent to ask targeted follow-up questions.
3. `expert_operator`
   Uses domain-specific language and expects concise workflow handling with minimal handholding.
4. `analysis_focused_user`
   Cares more about interpreting outputs, order parameters, and summary conclusions than setup details.
5. `noisy_or_ambiguous_user`
   Uses incomplete, slightly inconsistent, or poorly phrased requests to test robustness.

The scaffold already lets each task point at a `user_profile_id` so you can grow this later without changing the runner.

## Suggested Task Ladder

Your planned difficulty ladder fits the schema, but the current example spec is intentionally narrower and only exercises setup:

1. setup only
2. setup + planning
3. setup + planning + execution
4. setup + planning + execution + analysis
5. setup + planning + execution + analysis + result summary

The example spec currently includes only `setup_only` and uses a single user message so the run stops after setup. Add follow-up messages like `yes` only when you intentionally want later workflow stages to execute.

## Spec Structure

Key fields in the JSON spec:

- `experiment_id`
- `description`
- `output_dir`
- `working_dir_root`
- `repeats`
- `bootstrap_skill`
- `user_profiles`
- `tasks`
- `models`
- `skills`

The runner supports:

- LLM benchmarking by varying `models`
- skill ablation by varying `skills`
- task difficulty benchmarking by varying `tasks`

By default, eval-generated ColPack workflow directories are rooted under `eval/data/` via environment variable `COLPACK_WORKING_DIR_ROOT`. That keeps simulation artifacts separate from the standalone agent's default `data/` tree.

## Notes

- The runner reuses the same prompt loading and MCP connection logic as the standalone wrapper.
- Skill bootstrap is enabled by default to mirror `app.py`.
- Success scoring is intentionally simple in the scaffold: a run is marked successful when no turn reports a query error or system error. More detailed rubric-based scoring can be added later.
