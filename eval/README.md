# Eval Scaffold

This folder is the experiment harness for comparing prompt variants, LLMs, and skill versions without changing `agent/app.py`.

> **What this framework tests — and what it doesn't.** The eval harness measures **agent behavior**: how an LLM + skill combo navigates the ColPack workflow. It does **not** test the ColPack Python package itself; that's covered separately by `tests/test_colpack/`. Fixtures, tool implementations, and underlying simulation results are infrastructure assumed correct — they are not subjects of evaluation. For adversarial tasks (HPMC-incompatible mixtures, dimension mismatches, ensemble/parameter mismatches, inappropriate order parameters), score on whether the agent refused or clarified — *not* on whether the underlying tool happened to error or return numbers. If a ColPack bug causes a run to fail, that's noise in the agent score, to be discounted by inspecting the conversation transcript.

Skills used by eval are built into `eval/skills/<variant_id>/colpack/` from the production `agent/skills/colpack/` tree via `build_skill_variant.py`. This keeps experiment artifacts out of git (the directory is gitignored) and lets ablations omit specific reference files without touching the production skill.

## Building a Skill Variant

Run the builder before any experiment that references the variant:

```bash
# Full skill, no ablation
python eval/build_skill_variant.py --variant-id full

# Ablation: drop a single reference file
python eval/build_skill_variant.py --variant-id no_setup_ref \
    --exclude references/1_setup_problem.md

# Ablation: drop multiple reference files
python eval/build_skill_variant.py --variant-id minimal \
    --exclude references/1_setup_problem.md \
    --exclude references/2_plan_runs.md
```

Each variant's `SKILL.md` then lives at `eval/skills/<variant_id>/colpack/SKILL.md`, which is what the experiment spec's `skills[*].skill_path` should point to.

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
- `results.jsonl` (JSON Lines; trailing `l` is the letter ell)
- `summary.json`
- `conversations/<run_id>.md` (user/assistant transcript per run)

under the experiment `output_dir`.

## Two Evaluation Tracks

The eval runs two parallel studies. Both use the same JSON spec format and runner; they differ in which axis of the run matrix they vary.

| Track | Varies | Held fixed | Question being asked |
| --- | --- | --- | --- |
| **1 — LLM Evaluation** | `models` | `skills` = `full` | Which LLM reasons best at each isolated workflow stage? |
| **2 — Skill Ablation** | `skills` | `models` = one chosen LLM | How does removing parts of the skill affect end-to-end behavior? |

Both tracks share the difficulty + user-persona convention defined below, but apply it differently: Track 1 isolates each stage and uses adversarial prompts at the top of the ladder; Track 2 runs end-to-end and stays constructive across the ladder (the variable is the skill, not the prompt).

## Difficulty Ladder & User Personas

Each task carries a numeric `difficulty_level` (1–5) and a `user_profile_id` naming the prompt style. The two axes are tightly correlated — easier problems are usually expressed in plain language, and adversarial problems usually arrive in noisier or contradictory ones — so we treat them as a single ladder, with the persona naming the prompt style at each level:

| Level | Persona (`user_profile_id`) | Prompt style | What the level tests |
| --- | --- | --- | --- |
| 1 | `novice_workflow_user` | Plain language, complete request | Single shape, single sweep axis; clean parsing |
| 2 | `partially_specified_user` | Some parameters omitted; agent should ask the right follow-ups | Same-shape mixtures (bidisperse), basic dot-path use |
| 3 | `expert_operator` | Domain-specific terms, concise | Multi-component mixtures, multi-axis sweeps |
| 4 | `noisy_or_ambiguous_user` | Slightly inconsistent or under-specified | **Adversarial**: physically/mechanically impossible (e.g., HPMC-incompatible 2D mix, P on NVT) |
| 5 | `noisy_or_ambiguous_user` | Contradictory premises | **Adversarial**: dimension mismatch or other internal contradictions |

`analysis_focused_user` is reserved for analysis-stage questions — it cuts across difficulty levels because analysis questions can be easy or hard regardless of prompt phrasing.

For levels 4–5, tasks carry `metadata.adversarial: true` and `metadata.expected_failure_mode` so reviewers can score on the agent's refusal / clarification behavior rather than tool-call success. Track 2 (ablation) typically stays at levels 1–3 (constructive only); levels 4–5 are primarily a Track 1 concern.

The mapping is typical, not strict — a task author can pair any persona with any difficulty when it makes sense.

## Track 1 — LLM Evaluation (Three Dimensions, Full Skill)

Compare LLMs on **isolated workflow stages** using the production skill in full. Each workflow stage is treated as an independent evaluation axis to isolate that stage's reasoning without confounding from the others.

### Dimensions

1. **Setup** — given a user prompt, extract dimension / ensemble / shape list / particle count and call `setup_simulation_problem_tool` with the right arguments. Higher difficulty introduces multi-component mixtures and prompts that are physically or mechanically impossible (e.g., HPMC-incompatible 2D mix of ellipse + capsule, or a 2D shape mixed with a 3D shape).
2. **Planning** — given a setup, translate sweep intent into the correct `baseline_parameters` and `tunable_parameters` for `plan_simulation_runs_tool`. Higher difficulty covers per-component shape parameters, relative volume fractions, multi-axis sweeps, and adversarial requests like a pressure sweep on an NVT setup.
3. **Analysis** — given a completed simulation, answer questions about packing fraction, order parameters, RDF, etc., and call `analyze_simulation_runs_tool` with appropriate `extra_order_params` when needed. *(Suite to be authored.)*

**Execution is intentionally excluded** as a separate dimension. Once a plan is in place the agent's role in execution is mechanical (call the tool, wait, surface failures from `workflow_status.csv`) rather than reasoning-driven; a dedicated suite would test wait/poll behavior, not agent intelligence. Execution is exercised implicitly by any analysis task that needs a finished run.

### Suites

| Dimension | Tasks file | Spec | Difficulty | Status |
| --- | --- | --- | --- | --- |
| Setup | [tasks/setup_tasks.json](tasks/setup_tasks.json) | [specs/setup_eval.json](specs/setup_eval.json) | 1–5 (incl. 2 adversarial) | Authored |
| Planning | [tasks/planning_tasks.json](tasks/planning_tasks.json) | [specs/planning_eval.json](specs/planning_eval.json) | 1–4 (incl. 1 adversarial) | Authored |
| Analysis | [tasks/analysis_tasks.json](tasks/analysis_tasks.json) | [specs/analysis_eval.json](specs/analysis_eval.json) | 1–5 (incl. 1 adversarial) | Authored, fixture-backed |

The bare-bones `experiment_spec.example.json` (one `setup_only` task) is kept as a smoke test of the runner.

### Suite dependencies (avoiding redundant simulation work)

The three Track 1 dimensions are intentionally **chained via shared fixtures** so we don't re-run expensive simulation work for every analysis task. The dependency chain is:

```text
Setup suite       ──→ run all setup tasks (cheap; one tool call each)
                            │
                            ▼  pick 1–2 setup outputs as fixture working_dirs
Planning suite    ──→ each task starts from a fixture working_dir
                            (skips re-doing setup)
                            │
                            ▼  pick 2 of the resulting plans
[Execution]       ──→ execute exactly those 2 plans
                            │
                            ▼  yields 2 simulation-data fixtures
Analysis suite    ──→ every task reads one of the 2 pre-executed working_dirs
                       and calls only analyze_simulation_runs_tool
```

A full Track 1 pass therefore incurs:

- **N** setup tool calls (one per setup task, no execution).
- **M** planning tool calls (each starts from a fixture setup, no re-setup).
- **Exactly 2 simulation executions** — the expensive step, shared across the entire analysis suite.
- **K** analysis tool calls (each reads pre-existing data; no setup/plan/execute redo).

Without this dependency, every analysis task would redo setup + plan + execute end-to-end — costing K full pipelines instead of 2.

#### Bootstrapping fixtures

`eval/bootstrap_fixtures.py` builds the 2 simulation fixtures by calling `setup_simulation_problem` → `plan_simulaiton_runs` → `execute_simulation_workflow` directly (no agent in the loop), so fixtures are deterministic and decoupled from the LLM under test:

```bash
python eval/bootstrap_fixtures.py                       # build any missing fixtures
python eval/bootstrap_fixtures.py --force               # rebuild all fixtures from scratch
python eval/bootstrap_fixtures.py --only 2d_nvt_disk    # build a single fixture
```

The two default fixtures (chosen for single-shape vs mixture coverage):

| Fixture id | System | Sweep |
| --- | --- | --- |
| `2d_nvt_disk` | 2D NVT, 100 hard disks | `volume_fraction` ∈ {0.3, 0.5, 0.7, 0.8} (spans the freezing transition) |
| `2d_nvt_disk_capsule` | 2D NVT, 100 particles in a disk+capsule mixture | `volume_fraction` ∈ {0.4, 0.6} |

Outputs land at `eval/data/fixtures/<fixture_id>/` (gitignored under `eval/data/`). Each fixture directory holds the standard `simulation_problem.json`, `simulation_baseline.json`, `simulation_plan.json`, per-run trajectories (`init.gsd`, `compress.gsd`, `sample_trajectory.gsd`, `sample_final.gsd`), `workflow_status.csv`, and a fresh `analyze=X` column ready to be filled in by the analysis suite.

A combined `eval/data/fixtures/_index.json` records the mapping from fixture id → absolute `working_dir` plus the params used to build it. Tasks reference fixtures via the placeholder `{{fixture:<fixture_id>}}` in their `user_messages`; the spec loader substitutes the absolute `working_dir` from the index at load time. Missing fixtures fail loudly with a hint to run the bootstrap script.

> **Current state.** The analysis suite is fully fixture-backed: each of its 5 tasks contains a single user message that references a fixture and exercises only the analyze stage. The planning suite (`tasks/planning_tasks.json`) still redoes setup within each task; migrating it to start from a fixture setup is the next step.

### Running the LLM evaluation

```bash
python eval/build_skill_variant.py --variant-id full        # one-time: skill snapshot
python eval/bootstrap_fixtures.py                           # one-time: 2 simulation fixtures (~2 min)
python -m eval.run_experiments run --spec eval/specs/setup_eval.json
python -m eval.run_experiments run --spec eval/specs/planning_eval.json
python -m eval.run_experiments run --spec eval/specs/analysis_eval.json
```

Vary `models` in each spec to add LLMs to the matrix. The two prerequisite commands (skill build + fixture bootstrap) run once per environment; thereafter each analysis run only exercises the analyze stage and is near-instant. The planning suite still redoes setup per task and will get faster once it's migrated to fixtures.

## Track 2 — Skill Ablation Study (End-to-End, Fixed LLM)

Compare **skill variants** on a fixed LLM using a single end-to-end task per level (setup → plan → execute → analyze in one conversation). The question is whether removing parts of the skill — a single reference, all references, or the SKILL.md body itself — materially degrades the agent's ability to complete the workflow.

### Skill variants

`build_skill_variant.py` produces six pre-defined variants for ablation:

| Variant | What's removed | What it tests |
| --- | --- | --- |
| `full` | nothing | Baseline; full skill |
| `no_analysis` | `references/4_analyze_simulation.md` | Can the agent still run analysis? |
| `no_analysis_execution` | + `references/3_execute_simulation.md` | + Can it still execute? |
| `no_analysis_execution_plan` | + `references/2_plan_runs.md` | + Can it still plan? |
| `no_references` | entire `references/` directory | Can SKILL.md alone carry the workflow? |
| `no_skill` | `references/`, `scripts/`; SKILL.md body stripped to frontmatter | Lower bound: agent has zero procedural guidance |

Build commands for each variant are listed in the [Building a Skill Variant](#building-a-skill-variant) section above.

### End-to-end task ladder

Each level is a constructive (non-adversarial) end-to-end prompt of increasing problem complexity. The prompt phrasing is held fixed as `expert_operator` style at all levels — the level varies the underlying *problem*, not the *prompt*, so any degradation is attributable to the missing skill content rather than prompt difficulty:

| Level | Underlying task |
| --- | --- |
| 1 | Single shape, single-axis sweep (e.g., 2D NVT disks, sweep `volume_fraction` at 3 values, then analyze). |
| 2 | Bidisperse / same-shape mixture, single-axis sweep. |
| 3 | Multi-component mixture (different shapes), single-axis sweep. |
| 4 | Multi-component mixture, multi-axis sweep (one-at-a-time). |
| 5 | Multi-component mixture, multi-axis sweep with non-default analysis (extra `extra_order_params`). |

### Suite

| Tasks file | Spec | Status |
| --- | --- | --- |
| `tasks/ablation_tasks.json` | `specs/ablation_eval.json` | Not yet authored |

### Running the ablation study

```bash
# Build all variants once (see "Building a Skill Variant" for the per-variant args)
python eval/build_skill_variant.py --variant-id full
python eval/build_skill_variant.py --variant-id no_analysis --exclude references/4_analyze_simulation.md
# ... (build the rest of the variants) ...

# Run the suite — spec varies skills, holds model fixed
python -m eval.run_experiments run --spec eval/specs/ablation_eval.json
```

## Spec Structure

Key fields in the JSON spec:

- `experiment_id`
- `description`
- `output_dir`
- `working_dir_root`
- `repeats`
- `bootstrap_skill`
- `user_profiles`
- `tasks` (inline) **or** `tasks_file` (path to a JSON array of tasks)
- `models`
- `skills`

`tasks_file` lets multiple specs share the same task collection (e.g. swap out the model list while keeping the same task ladder). Specifying both `tasks` and `tasks_file` is an error.

The runner supports:

- LLM benchmarking by varying `models`
- skill ablation by varying `skills`
- task difficulty benchmarking by varying `tasks`

By default, eval-generated ColPack workflow directories are rooted under `eval/data/` via environment variable `COLPACK_WORKING_DIR_ROOT`. That keeps simulation artifacts separate from the standalone agent's default `data/` tree.

## Notes

- The runner reuses the same prompt loading and MCP connection logic as the standalone wrapper.
- Skill bootstrap is enabled by default to mirror `app.py`.
- Success scoring is intentionally simple in the scaffold: a run is marked successful when no turn reports a query error or system error. More detailed rubric-based scoring can be added later.
