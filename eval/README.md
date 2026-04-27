# Eval Scaffold

This folder is the experiment harness for comparing prompt variants, LLMs, and skill versions without changing `agent/app.py`.

> **What this framework tests — and what it doesn't.** The eval harness measures **agent behavior**: how an LLM + the production skill navigates the ColPack workflow. It does **not** test the ColPack Python package itself; that's covered separately by `tests/test_colpack/`. Fixtures, tool implementations, and underlying simulation results are infrastructure assumed correct — they are not subjects of evaluation. For adversarial tasks (HPMC-incompatible mixtures, dimension mismatches, ensemble/parameter mismatches, inappropriate order parameters), score on whether the agent refused or clarified — *not* on whether the underlying tool happened to error or return numbers. If a ColPack bug causes a run to fail, that's noise in the agent score, to be discounted by inspecting the conversation transcript.

**Scope (2026-04-27).** This eval is intentionally lean: a few LLMs scored against the `full` production skill across three workflow stages (setup, planning, analysis). The more comprehensive benchmark — skill ablation, broader LLM coverage, automated scoring — moved to a separate project, **ColPackBench**, as a follow-up paper. The variant-builder script (`build_skill_variant.py`) and the underlying ablation infra are kept here as reusable plumbing.

Skills used by eval are built into `eval/skills/<variant_id>/colpack/` from the production `agent/skills/colpack/` tree via `build_skill_variant.py`. This keeps experiment artifacts out of git (the directory is gitignored) and lets ablations omit specific reference files without touching the production skill.

## Building a Skill Variant

For this paper's eval we only need the `full` variant. Build it once before running any experiment:

```bash
python eval/build_skill_variant.py --variant-id full
```

The variant lands at `eval/skills/full/colpack/SKILL.md`, which is what the experiment spec's `skills[*].skill_path` points to.

`build_skill_variant.py` also supports `--exclude <ref-or-dir>` (drop a reference file or the whole `references/` directory) and `--strip-skill-body` (replace SKILL.md with frontmatter only). Those flags are used by the ColPackBench ablation study, not here.

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
# Print the planned matrix (no LLM calls)
python -m eval.run_experiments plan --spec eval/specs/setup_eval.json

# Smoke test: 1 real run, all output written
python -m eval.run_experiments run --spec eval/specs/setup_eval.json --limit 1
```

`plan` expands the matrix and can write a manifest.

`run` executes the planned runs sequentially and writes:

- `planned_runs.json`
- `results.jsonl` (JSON Lines; trailing `l` is the letter ell)
- `summary.json`
- `conversations/<run_id>.md` (user/assistant transcript per run)

under the experiment `output_dir`.

## How the Runner Works

The cleanest way to think about this is: **specs are recipes, tasks are the menu, the runner is the kitchen**. Every experiment is just one spec pointing at one task collection plus axes saying "which models / which skills / how many repeats."

### Specs vs. tasks — the conceptual split

| Folder | Holds | Changes when… |
|---|---|---|
| [`eval/tasks/`](tasks/) | The actual prompts: `user_messages`, `expected_outcomes`, `difficulty_level`, `user_profile_id`, `metadata`. **Pure test cases — no notion of which LLM or skill evaluates them.** | You want to add a new prompt or tweak wording. |
| [`eval/specs/`](specs/) | The experiment recipe: `experiment_id`, `output_dir`, `tasks_file` (pointer to a tasks JSON), `models` array, `skills` array, `agent_mode`, `repeats`. **No prompts inside.** | You want to add an LLM, change the skill variant, change repeats, or run the same prompts under a different output dir. |

The split is what lets you reuse a task collection across many experiments (e.g., the same `setup_tasks.json` evaluated against four different model panels) without copy-pasting prompts.

### How a spec becomes a list of runs

The runner expands the matrix in this nesting order ([experiment_types.py:243](experiment_types.py#L243)):

```python
for repeat in range(repeats):
    for task in tasks:
        for model in models:
            for skill in skills:
                # ← one planned_run per innermost iteration
```

So with the current [`setup_eval.json`](specs/setup_eval.json) (6 tasks × 1 model × 1 skill × 1 repeat) the matrix has **6 planned runs**. If you append three more LLMs to `models`, it expands to 6 × 4 × 1 × 1 = **24 planned runs** — same prompts, four times the LLM coverage.

The loop nesting matters when you slice the matrix:

```text
With 4 models x 6 tasks x 1 skill x 1 repeat:

   index   task                  model      skill   repeat
   -----   --------------------  ---------  ------  ------
    0      setup_2d_disk         gemini     full    r01      <-- --limit 1 stops here
    1      setup_2d_disk         claude     full    r01      <-- --limit 4 includes
    2      setup_2d_disk         gpt-4o     full    r01          all four LLMs on task 0
    3      setup_2d_disk         llama      full    r01      <--
    4      setup_3d_sphere       gemini     full    r01
    5      setup_3d_sphere       claude     full    r01
    ...    ...                   ...        ...     ...
   23      setup_dim_mismatch    llama      full    r01      <-- no --limit runs all 24
```

Because `model` is *inside* `task`, all models cycle through before `task` advances. That's why `--limit N_models` is a great smoke test when you add a new LLM: it gives you "task 0 across every model" in one shot.

### What `--limit N` actually does

It's a slice on the already-expanded matrix ([run_experiments.py:574](run_experiments.py#L574)):

```python
planned_runs = expand_planned_runs(spec)
if limit > 0:
    planned_runs = planned_runs[:limit]
```

It only changes the **count** of LLM calls, not how prompts are constructed or which prompts get included. The order is fully determined by the loop nesting above.

### Adding more LLMs

Just append entries to the spec's `models` array — no code changes:

```json
"models": [
  { "model_id": "openrouter/google/gemini-3-flash-preview",   "label": "gemini" },
  { "model_id": "openrouter/anthropic/claude-sonnet-4-6",     "label": "claude-sonnet" },
  { "model_id": "openrouter/openai/gpt-4o",                   "label": "gpt-4o" },
  { "model_id": "openrouter/meta-llama/llama-3.3-70b-instruct", "label": "llama-3.3-70b" }
]
```

Each entry needs `model_id` (the SDK passes this through to the provider router); `label` is optional and shows up in run-ids and transcript filenames. For apples-to-apples comparison, paste the same `models` block into all three specs.

### End-to-end pipeline

```text
spec.json ── tasks_file ──→ tasks.json
   │              │
   └── + models, skills, repeats ──→ expand_planned_runs() ──→ [run_0, run_1, …, run_N-1]
                                                                       │
                                                                  --limit K slices
                                                                       │
                                                                       ▼
                                                              [run_0, …, run_K-1]
                                                                       │
                                                                       ▼
                                                  runner executes K LLM-driven runs
                                                                       │
                                                                       ▼
                                                  writes results.jsonl, summary.json,
                                                  conversations/<run_id>.md
```

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

For levels 4–5, tasks carry `metadata.adversarial: true` and `metadata.expected_failure_mode` so reviewers can score on the agent's refusal / clarification behavior rather than tool-call success.

The mapping is typical, not strict — a task author can pair any persona with any difficulty when it makes sense.

## LLM Evaluation (Three Dimensions, Full Skill)

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
| Planning | [tasks/planning_tasks.json](tasks/planning_tasks.json) | [specs/planning_eval.json](specs/planning_eval.json) | 1–4 (incl. 1 adversarial) | Authored, fixture-backed |
| Analysis | [tasks/analysis_tasks.json](tasks/analysis_tasks.json) | [specs/analysis_eval.json](specs/analysis_eval.json) | 1–5 (incl. 1 adversarial) | Authored, fixture-backed |

For a quick smoke test, run any of these specs with `--limit 1` to execute just the first task.

### Suite dependencies (avoiding redundant simulation work)

The three dimensions are intentionally **chained via shared fixtures** so we don't re-run expensive simulation work for every analysis task. The dependency chain is:

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

A full pass therefore incurs:

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

Two tiers of fixtures:

**Full simulation fixtures** — setup + plan + execute. Used by the analysis suite.

| Fixture id | System | Sweep |
| --- | --- | --- |
| `2d_nvt_disk` | 2D NVT, 100 hard disks | `volume_fraction` ∈ {0.3, 0.5, 0.7, 0.8} (spans the freezing transition) |
| `2d_nvt_disk_capsule` | 2D NVT, 100 particles, disk+capsule mix | `volume_fraction` ∈ {0.4, 0.6} |

**Setup-only fixtures** — only `simulation_problem.json`, no plan/execute. Cheap (millisecond builds) starting points used by the planning suite.

| Fixture id | System |
| --- | --- |
| `2d_nvt_disk_capsule_setup` | 2D NVT, 500 particles, disk+capsule mix |
| `2d_npt_disk_capsule_setup` | 2D NPT, 500 particles, disk+capsule mix |
| `2d_nvt_disk_disk_setup` | 2D NVT, 1000 particles, bidisperse disks |

Outputs land at `eval/data/fixtures/<fixture_id>/` (gitignored under `eval/data/`). A combined `eval/data/fixtures/_index.json` records the mapping fixture_id → absolute `working_dir`. Tasks reference fixtures via the placeholder `{{fixture:<fixture_id>}}` in their `user_messages`; the spec loader substitutes the absolute path at load time and errors loudly with a build hint if the fixture is missing.

> **Note on planning-suite isolation.** Planning tasks call `plan_simulation_runs_tool`, which appends to the fixture's `simulation_plan.json` rather than replacing it. For a single LLM pass this is fine (the agent's tool-call payload is what we score); for a multi-LLM matrix run, `--force` rebuild the setup-only fixtures between full passes if you want clean isolation. The full simulation fixtures are not affected by planning runs.

**Current state.** Both the analysis suite and the planning suite are fully fixture-backed: each task is a single turn that references a fixture and exercises only its target stage. Setup tasks remain self-contained (they have no upstream dependency to optimize away).

### Running the LLM evaluation

```bash
python eval/build_skill_variant.py --variant-id full        # one-time: skill snapshot
python eval/bootstrap_fixtures.py                           # one-time: 2 simulation fixtures (~2 min)
python -m eval.run_experiments run --spec eval/specs/setup_eval.json
python -m eval.run_experiments run --spec eval/specs/planning_eval.json
python -m eval.run_experiments run --spec eval/specs/analysis_eval.json
```

Vary `models` in each spec to add LLMs to the matrix. The two prerequisite commands (skill build + fixture bootstrap) run once per environment; thereafter each analysis run only exercises the analyze stage and is near-instant. The planning suite still redoes setup per task and will get faster once it's migrated to fixtures.

## Scoring

**Current state — liveness only.** A run is marked `success` if no turn reported a query or system error — i.e., the runner did not crash. This is *liveness*, not *correctness*: it does **not** verify that the agent called the right tool with the right arguments, refused adversarial requests, or interpreted analysis results correctly. `n_success` and `success_rate` in `summary.json` inherit this coarseness.

Until proper scoring lands, **score adversarial tasks (L4–L5) and the L2 analysis interpretation task by reading the conversation transcripts** in `eval/runs/<experiment_id>/conversations/`. Do not trust `success_rate` for those tasks.

> [!todo] Future — hybrid scoring (programmatic + LLM-judge)
>
> Plan to layer real scoring on top of liveness in two stages:
>
> 1. **Programmatic assertions per task.** Persist structured tool-use records per turn (currently the runner consumes them but doesn't store them in `TurnResult`), then add an assertion block in each task's metadata — for example `expected_tool_calls: [{name: setup_simulation_problem_tool, args: {dimension: 2, ...}}]` and `assert_no_drift: true`. Runner verifies these post-run. Free, deterministic; catches tool-call payload errors and stage drift.
> 2. **LLM-as-judge for refusal + interpretation.** Where programmatic rules can't help (adversarial refusal quality, the L2 freezing-transition reasoning), ship the conversation transcript + `expected_outcomes` to a judge model and parse a pass/fail + rubric. Invoke via an opt-in `--with-judge` flag on the runner so basic loops stay free.
>
> Open: which judge model (independent strong model vs. self-judge vs. a small mini-judge), and how to design the rubric prompt so it's stable across LLMs being evaluated.

## Skill ablation lives in ColPackBench

`build_skill_variant.py` can produce more than just the `full` variant — it supports `--exclude` (drop reference files) and `--strip-skill-body` (frontmatter-only SKILL.md). That machinery is intentionally retained here, but the **skill ablation study itself** (end-to-end tasks varying the `skills` axis on a fixed LLM) is out of scope for the ColPackAgent paper. It moved to a separate project, **ColPackBench**, along with the broader benchmark scope (more LLMs, automated scoring, additional task dimensions). See your project notes for `ColPackBench` for design and status.

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
- Success scoring is currently liveness-only — see the [Scoring](#scoring) section above for what that catches and what it doesn't, plus the planned hybrid replacement.
