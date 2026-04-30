# Eval Scaffold

This folder is the experiment harness for comparing prompt variants, LLMs, and skill versions without changing `agent/app.py`.

> **What this framework tests — and what it doesn't.** The eval harness measures **agent behavior**: how an LLM + the production skill navigates the ColPack workflow. It does **not** test the ColPack Python package itself; that's covered separately by `tests/test_colpack/`. Fixtures, tool implementations, and underlying simulation results are infrastructure assumed correct — they are not subjects of evaluation. For adversarial tasks (HPMC-incompatible mixtures, dimension mismatches, ensemble/parameter mismatches, inappropriate order parameters), score on whether the agent refused or clarified — *not* on whether the underlying tool happened to error or return numbers. If a ColPack bug causes a run to fail, that's noise in the agent score, to be discounted by inspecting the conversation transcript.

**Scope (2026-04-27).** This eval is intentionally lean: a few LLMs scored against the production agent skill across three workflow stages (setup, planning, analysis). The more comprehensive benchmark — skill ablation, broader LLM coverage, automated scoring — moved to a separate project, **ColPackBench**, as a follow-up paper.

Specs reference the production skill directly at `agent/skills/colpack/SKILL.md`. There is no per-eval skill build step in this folder. Variant building lives in ColPackBench, where it's actually exercised by ablation experiments.

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
# Print the planned matrix for one spec (no LLM calls)
python -m eval.run_experiments plan --spec eval/specs/setup_eval.json

# Smoke test: 1 real run, all output written
python -m eval.run_experiments run --spec eval/specs/setup_eval.json --limit 1

# All three stages (setup → planning → analysis) for one model in one go
python -m eval.run_experiments run --all-specs --models claude-haiku-4.5
```

`--spec` and `--all-specs` are mutually exclusive — provide exactly one. `--all-specs` globs `eval/specs/*_eval.json` and iterates in stage order (setup → planning → analysis → others). The same `--models` / `--limit` / `--task-timeout` apply to each spec.

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
| --- | --- | --- |
| [`eval/tasks/`](tasks/) | The actual prompts: `user_messages`, `expected_outcomes`, `difficulty_level`, `metadata`. **Pure test cases — no notion of which LLM or skill evaluates them.** | You want to add a new prompt or tweak wording. |
| [`eval/specs/`](specs/) | The experiment recipe: `experiment_id`, `output_dir`, `tasks_file` (pointer to a tasks JSON), `models` array, `skills` array, `agent_mode`, `repeats`. **No prompts inside.** | You want to add an LLM, change repeats, or run the same prompts under a different output dir. |

The split is what lets you reuse a task collection across many experiments (e.g., the same `setup_tasks.json` evaluated against four different model panels) without copy-pasting prompts.

### How the matrix expands

The runner iterates the spec's axes in this nesting order ([experiment_types.py](experiment_types.py)):

```python
for model in models:
    for repeat in range(repeats):
        for task in tasks:
            for skill in skills:
                # ← one planned_run per innermost iteration
```

**Model is outermost** so all of model A's runs happen contiguously before any of model B's. That makes per-model output streaming natural (each model's `results.jsonl` fills before the next one starts) and lets you Ctrl-C cleanly between models.

For [`setup_eval.json`](specs/setup_eval.json) (6 tasks × 6 models × 1 skill × 1 repeat = **36 planned runs**), the list looks like:

```text
With 6 models x 6 tasks x 1 skill x 1 repeat:

   index   model                        task                              skill   repeat
   -----   ---------------------------  --------------------------------  ------  ------
    0      claude-haiku-4.5             setup_2d_disk                     full    r01      <-- --limit 6 stops here
    1      claude-haiku-4.5             setup_3d_sphere                   full    r01          (all 6 tasks on
    2      claude-haiku-4.5             setup_2d_bidisperse_disks         full    r01           the first model)
    3      claude-haiku-4.5             setup_2d_disk_capsule             full    r01
    4      claude-haiku-4.5             setup_2d_incompatible_*           full    r01
    5      claude-haiku-4.5             setup_dim_mismatch_disk_cube      full    r01      <--
    6      gpt-oss-120b                 setup_2d_disk                     full    r01
    7      gpt-oss-120b                 setup_3d_sphere                   full    r01
    ...    ...                          ...                               ...     ...
   35      gemini-3.1-pro-preview       setup_dim_mismatch_disk_cube      full    r01      <-- no --limit runs all 36
```

That's why `--limit N_tasks` is a great smoke test when you add a new task or skill: it gives you "all tasks on model 0" in one shot. To smoke-test a single new LLM instead, use `--models <label>` (next section).

### Selecting models with `--models`

Both `plan` and `run` accept `--models`, a comma-separated list of **exact** labels or `model_id`s. Use it to run a subset of the spec's panel without editing the JSON:

```bash
# Run all setup tasks on just Haiku
python -m eval.run_experiments run --spec eval/specs/setup_eval.json --models claude-haiku-4.5

# Two specific models
python -m eval.run_experiments run --spec eval/specs/setup_eval.json \
  --models claude-haiku-4.5,claude-opus-4.7

# Plan-only preview
python -m eval.run_experiments plan --spec eval/specs/setup_eval.json --models gemini-3-flash-preview
```

Match is exact (full label or full `model_id`), not substring — ambiguous tokens like `claude` won't silently pull in models you didn't intend. Any token that doesn't match a model in the spec causes the runner to error out with the available labels.

### What `--limit N` actually does

It's a slice on the already-expanded matrix:

```python
planned_runs = expand_planned_runs(spec)
if limit > 0:
    planned_runs = planned_runs[:limit]
```

It only changes the **count** of LLM calls, not how prompts are constructed or which prompts get included. With model outermost, `--limit N_tasks` keeps the first N runs of model 0; `--limit (N_tasks * 2)` adds model 1; and so on.

### Adding more LLMs

The model panel is shared across all three specs via a single [`eval/specs/models.json`](specs/models.json). To add or remove an LLM, edit that file once — no spec changes, no code changes:

```json
[
  { "model_id": "openrouter/google/gemini-3-flash-preview",     "label": "gemini-3-flash-preview" },
  { "model_id": "openrouter/anthropic/claude-haiku-4.5",        "label": "claude-haiku-4.5" },
  { "model_id": "openrouter/openai/gpt-oss-120b",               "label": "gpt-oss-120b" }
]
```

Each entry needs `model_id` (the SDK passes this through to the provider router); `label` is optional but recommended — it shows up in run-ids, transcript filenames, the per-model output folder name, and is what `--models` matches against.

The three specs reference the file by `models_file: "eval/specs/models.json"`. If you ever need a one-off panel for a single spec (e.g. a planning-only experiment using a different LLM list), use `models: [...]` inline instead of `models_file` — but not both at once.

### Current panel — tier, lab, cost

The 10-model panel is curated to span **frontier → mid → weak** tiers across **7 labs**, all served via OpenRouter → Google Vertex (see "Provider routing" below). Cost is the OpenRouter list price per million tokens.

| label | lab | tier | $/Mtok in / out | notes |
| --- | --- | --- | --- | --- |
| `claude-opus-4.7` | Anthropic | **frontier** | 5 / 25 | Anthropic flagship; expensive; long-running agentic strength |
| `gemini-3.1-pro-preview` | Google | **frontier** | 2 / 12 | Google flagship; "thinking" reasoning model |
| `deepseek-v3.2` | DeepSeek | **frontier** | 0.56 / 1.68 | Strong reasoning at a fraction of Opus cost; good frontier value |
| `kimi-k2-thinking` | Moonshot | strong (reasoning) | 0.60 / 2.50 | Always-thinking MoE; agentic-tuned — interesting on multi-step tasks |
| `gpt-oss-120b` | OpenAI | mid–strong | 0.09 / 0.36 | OpenAI's open-weights MoE; only OpenAI option on Vertex; very cheap |
| `claude-haiku-4.5` | Anthropic | mid (fast) | 1 / 5 | Cost-efficient Claude; near-Sonnet quality at much lower cost |
| `gemini-3-flash-preview` | Google | mid (fast) | 0.50 / 3 | Cost-efficient Gemini 3; thinking-capable Flash |
| `qwen3-next-80b-instruct` | Qwen | mid | 0.15 / 1.20 | Non-thinking Qwen; instruction-tuned baseline |
| `llama-4-scout` | Meta | mid (open-weights) | 0.25 / 0.70 | Meta's MoE; multimodal; widely-cited open baseline |
| `gemini-2.0-flash` | Google | **older / weak** | 0.10 / 0.40 | Feb 2025 — included as a regression baseline ("how does the agent skill amplify weak vs. strong models?") |

**Coverage at a glance:**

- **3 frontier** from 3 different vendors (Anthropic, Google, DeepSeek) → no single-lab bias on top-end results.
- **6 mid-tier** spanning OpenAI, Anthropic, Google, Moonshot, Qwen, Meta → answers "how do non-frontier models from different houses compare on the same skill?"
- **1 explicit weak baseline** (Gemini 2.0 Flash, ~14 months older) → gives the floor.
- **1 explicit reasoning model** (Kimi K2 Thinking) — useful contrast against non-thinking peers in the same cost class.
- **Open-weights ratio:** 3/10 (gpt-oss-120b, qwen3-next, llama-4-scout) — meaningful representation without dominating.

**Cost envelope.** A full pass on all three suites (17 tasks × 10 models = ~170 runs) lands roughly in the **$5–15** range under current pricing, with `claude-opus-4.7` accounting for the bulk. Use `--models <label>` to subset for cheaper iteration; `--models claude-opus-4.7` alone is the most informative single-model run if you only have budget for one.

**Maintenance.** When adding a model: (1) confirm the slug is on <https://openrouter.ai/provider/google-vertex> (the Vertex pin will fail-closed otherwise — see Gemma 4 incident, 2026-04-28); (2) update this table when you change [`eval/specs/models.json`](specs/models.json) so the docs don't drift.

### Provider routing and the audit trail

Today every model_id of the form `openrouter/<vendor>/<model>` routes through OpenRouter's API; OpenRouter then chooses a sub-backend (Google Vertex, direct Anthropic, AWS Bedrock, etc.) per its account-level **provider preferences** at `https://openrouter.ai/settings/privacy`. Pinning a sub-backend (e.g. routing all traffic through Google Vertex for fairness) is configured there, not in the spec.

> **Pinning Google Vertex (recommended for cross-vendor benchmarking).** OpenRouter's "Google" provider option on the privacy page maps to slug `google-vertex` — that *is* Vertex AI (the slug `google-ai-studio` is the simpler direct API). Setting allowed providers to `["google-vertex"]` with `allow_fallbacks: false` (or just `only: ["google-vertex"]`) forces every request to Vertex; non-Vertex requests hard-fail rather than silently rerouting, which is the right default for paper-grade reproducibility. Vertex hosts both the Gemini family (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-flash-preview`, `gemini-3.1-pro-preview`, …) and Anthropic Claude 4.x (`claude-opus-4.7`, `claude-sonnet-4.6`, `claude-opus-4.6`) via the Vertex Model Garden, so a single Vertex-only setting still gives a useful Gemini-vs-Claude panel. The full live list of Vertex-eligible models is at: <https://openrouter.ai/provider/google-vertex> — check there before adding a new entry to a spec's `models` array.

The eval *records* what we sent to the SDK (`provider_id` from the model_id prefix, e.g. `"openrouter"`) but cannot programmatically read OpenRouter's actual sub-backend choice — that information lives on the OpenRouter activity dashboard at `https://openrouter.ai/activity`. For paper-grade auditability:

1. Pin the desired sub-backend in OpenRouter's privacy settings (allowed/ignored providers).
2. Optionally annotate each model in the spec with `metadata.expected_backend` for documentation:

   ```json
   {
     "model_id": "openrouter/anthropic/claude-opus-4.7",
     "label": "claude-opus-4.7",
     "metadata": { "expected_backend": "google-vertex" }
   }
   ```

   The runner echoes this into `results.jsonl` (`metadata.model_metadata`) and `summary.json` (`per_model[*].model_metadata`). Reviewers can then cross-check the OpenRouter activity dashboard to confirm runs landed on the expected backend.

3. The summary's `per_model` block also exposes the resolved `provider_id` (e.g. `"openrouter"`) per model so you can see the SDK-level routing target at a glance.

### End-to-end pipeline

```text
spec.json ── tasks_file ──→ tasks.json
   │              │
   └── + models, skills, repeats ──→ expand_planned_runs() ──→ [run_0, run_1, …, run_N-1]
                                                                       │
                                                              --models filters models
                                                              --limit K slices
                                                                       │
                                                                       ▼
                                                              [run_0, …, run_K-1]
                                                                       │
                                                                       ▼
                                                  runner executes K LLM-driven runs
                                                                       │
                                                                       ▼
                                            for each (model, stage) cell, writes:
                                              <output_dir>/<model_label>/<stage>/results.jsonl
                                              <output_dir>/<model_label>/<stage>/summary.json
                                              <output_dir>/<model_label>/<stage>/conversations/<run_id>.md
```

### Output layout

`output_dir` is the experiment's base path (e.g. `eval/runs`). The runner partitions outputs by **model first, then stage** so each leaf folder is a self-contained "this LLM on this stage" cell:

```text
eval/runs/
├── claude-haiku-4.5/
│   ├── setup/
│   │   ├── results.jsonl
│   │   ├── summary.json
│   │   └── conversations/<run_id>.md
│   ├── planning/
│   └── analysis/
└── gemini-3-flash-preview/
    └── …
```

Cross-model comparison = read sibling `summary.json` files. Each `<model>/<stage>/summary.json` contains the aggregated stats for that one cell (`n_runs`, `success_rate`, `n_off_rail`, `n_no_expected_tool_call`, costs, served-by provider, etc.) plus the model's label and id at the top of the file. If you want a JSON snapshot of the planned matrix before running, use `python -m eval.run_experiments plan --spec <spec> --write-manifest` — opt-in only.

## Difficulty Ladder

Each task carries a numeric `difficulty_level` (1–5). Higher levels introduce harder reasoning (multi-component mixtures, multi-axis sweeps) and at the top of the ladder become **adversarial** — physically/mechanically impossible requests, or prompts with contradictory premises:

| Level | What the level tests |
| --- | --- |
| 1 | Plain, complete request: single shape, single sweep axis, clean parsing |
| 2 | Same-shape mixtures (bidisperse), basic dot-path use, simple interpretation |
| 3 | Domain-specific terms, multi-component mixtures, multi-axis sweeps |
| 4 | **Adversarial**: physically/mechanically impossible (e.g., HPMC-incompatible 2D mix, P on NVT) |
| 5 | **Adversarial**: dimension mismatch or other internal contradictions |

For levels 4–5, tasks carry `metadata.adversarial: true` and `metadata.expected_failure_mode` so reviewers can score on the agent's refusal / clarification behavior rather than tool-call success.

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
python eval/bootstrap_fixtures.py                           # one-time: 2 simulation + 3 setup-only fixtures (~2 min)

# Full panel × all three stages (the typical paper run)
python -m eval.run_experiments run --all-specs

# All stages for one specific model (cheap iteration / model bring-up)
python -m eval.run_experiments run --all-specs --models claude-haiku-4.5

# Or one stage at a time, full panel
python -m eval.run_experiments run --spec eval/specs/setup_eval.json
python -m eval.run_experiments run --spec eval/specs/planning_eval.json
python -m eval.run_experiments run --spec eval/specs/analysis_eval.json
```

The model panel is shared across all three specs via [`eval/specs/models.json`](specs/models.json) — edit there to add or drop a model from every stage at once. The fixture bootstrap runs once per environment; thereafter each planning / analysis task exercises only its target stage. Specs reference the production skill at `agent/skills/colpack/SKILL.md` directly — no per-eval skill build step.

## Stage scope and off-rail detection

A real concern when benchmarking: with `agent_mode: "interactive"` and a generic confirmation turn ("Yes, please proceed."), some LLMs interpret "proceed" as *the entire workflow* and call setup → plan → execute back-to-back, while others stop at the requested stage. That's both unfair (different work scope per model on the same prompt) and expensive (the off-rail model actually runs simulations).

Rather than fight this with prompt engineering — which biases scoring toward "how well does each LLM parse our hints" — we treat **drift past the requested stage as evaluation signal**. The runner enforces a stage scope per task and records any tool calls that fall outside it.

### How it works

Each task already declares `metadata.stage` (`"setup"` / `"planning"` / `"analysis"`). The runner derives an allowed set of ColPack MCP tools per stage:

| Stage | Allowed ColPack tools |
| --- | --- |
| `setup` | `setup_simulation_problem_tool`, `get_colpack_capabilities_tool` |
| `planning` | `plan_simulation_runs_tool`, `get_colpack_capabilities_tool` |
| `analysis` | `analyze_simulation_runs_tool`, `get_colpack_capabilities_tool` |

`get_colpack_capabilities_tool` is always allowed because `bootstrap_skill: true` calls it once at session start. Non-ColPack tools (Read, Bash, Grep, etc.) pass through unchecked — only the controlled ColPack workflow tools count toward off-rail.

When a turn returns with at least one off-rail tool call, the runner:

1. Logs `[off-rail] task stage='<stage>' but agent called: <suffixes> — stopping run early` to stdout.
2. Marks the run with `off_rail: true` and records the offending tool calls.
3. Breaks the user-message loop for that run — no further turns get sent, so we don't pay for additional drift.

Tool-name matching is suffix-based (`tool_name == suffix or tool_name.endswith("_" + suffix)`) so it handles both bare names (`setup_simulation_problem_tool`) and SDK-prefixed names (`colpack__setup_simulation_problem_tool`).

### Where it shows up in the outputs

**`results.jsonl`** — per run:

```json
{
  "off_rail": true,
  "off_rail_tool_calls": [
    {"tool_name": "plan_simulation_runs_tool",        "matched_suffix": "plan_simulation_runs_tool"},
    {"tool_name": "execute_simulation_workflow_tool", "matched_suffix": "execute_simulation_workflow_tool"}
  ],
  "metadata": {
    "task_stage": "setup",
    "allowed_tool_suffixes": ["get_colpack_capabilities_tool", "setup_simulation_problem_tool"]
  }
}
```

Per-turn detail is also kept in `turn_results[*].off_rail_tool_calls`.

**`summary.json`** — both the grand-total block and each `per_model` entry add:

```json
"n_off_rail":            1,                                              // count of runs that drifted
"off_rail_rate":         0.5,
"off_rail_tools_seen":   ["execute_simulation_workflow_tool",            // deduped per model
                          "plan_simulation_runs_tool"]
```

So a one-line read: *"Opus 0/1 off-rail; Gemini 1/1 off-rail, drove all the way through `execute_simulation_workflow_tool`."*

### Run-outcome quadrants

`success` is **strict by default** — a run is marked successful only on positive evidence the agent did its job, not just on absence of crashes. For non-adversarial tasks the criterion is:

```text
success = no_errors  AND  expected_tool_called  AND  not off_rail
```

Combined with `expected_tool_called` (the stage's primary tool ever fired) and `off_rail` (drift past stage), the four logical outcomes are:

| `success` | `expected_tool_called` | `off_rail` | Interpretation |
| --- | --- | --- | --- |
| ✓ | ✓ | ✗ | **Clean pass** — did exactly the requested stage |
| ✗ | ✓ | ✓ | Did the work but **drifted past the stage** |
| ✗ | ✗ | ✗ | **Confirmation-stuck / failure to act** — agent ran without errors but never called the stage's primary tool |
| ✗ | ✗ | ✓ | Drifted to wrong tools **without ever doing the right one** |

Only the top row counts as `success`. The other three rows surface as distinct failure modes via the secondary flags.

`expected_tool_called` is derived per stage: setup → `setup_simulation_problem_tool`, planning → `plan_simulation_runs_tool`, analysis → `analyze_simulation_runs_tool`. The flag, the per-run `tools_called` list, and the aggregated `n_no_expected_tool_call` / `no_expected_tool_call_rate` (both grand-total and `per_model`) are all written to `results.jsonl` and `summary.json`.

**Adversarial tasks (L4–L5)** use a different success criterion. For those the *correct* behavior is to refuse / clarify, so requiring `expected_tool_called` would invert the verdict. The runner falls back to `no_errors AND made_progress` (made_progress = output tokens > 0 OR any tool call OR any off-rail dispatch) — that catches silent SDK failures while leaving the actual "was the refusal correct?" question for transcript review (see Scoring section below).

**Why strict by default.** With the previous liveness-only criterion, a silent upstream failure (invalid model_id, auth rejection) returned an empty SDK stream with no error raised. Every task came back `success=true` with zero output tokens — actively misleading. The strict criterion requires the agent to demonstrably do *something* before claiming success. As an additional defense, `_run_experiment` checks the pre-flight routing probe and skips models with confirmed errors before any tasks fire.

### Caveat — detection is post-dispatch

The runner sees a tool call after the SDK has already emitted the message containing it. The off-rail tool *will* execute once through the SDK / MCP path before the run terminates — we cannot intercept the dispatch from outside the SDK. The cost-saving is "no further turns after off-rail," not "zero off-rail tool execution." For analysis purposes this is actually a feature (you see the full off-rail behavior in the transcript), but be aware that one off-rail simulation run can still be expensive.

Patching the SDK's tool-dispatch path to deny disallowed calls before they reach MCP would close that gap, but it's a real SDK fork — not worth it for the ColPackAgent paper. Saved as an enhancement candidate if ColPackBench needs it.

## Per-task wall-time timeout

Each task runs with a wall-time budget so a hung model — or one that goes off-rail and triggers a slow simulation execution — can't burn unbounded compute. On exceeding the budget, the runner appends a synthetic `system_error` to the turn, marks the run failed, and moves on to the next planned run.

**Default per stage** (chosen because all three stages call a single fast tool that should return in seconds):

| Stage | Default timeout |
| --- | --- |
| `setup` / `planning` / `analysis` | 180s (3 min) |
| Unknown / no stage | 600s (10 min, fallback) |

**Override precedence** (highest wins):

1. CLI: `--task-timeout 60` on the `run` subcommand — applies to every task this invocation.
2. Per-task: `metadata.timeout_seconds` in the task JSON — for one task that's known to need more (or less) than the stage default.
3. Per-spec: `metadata.default_timeout_seconds` in the spec JSON — applies to every task in that spec unless overridden by task metadata.
4. Stage default (table above).

The resolved budget is recorded as `metadata.task_timeout_seconds` on each `RunResult`, so transcripts are self-describing. A timeout shows up as `success: false` with a system_error like `task timeout exceeded (180s) on turn 1`.

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

## Spec Structure

Key fields in the JSON spec:

- `experiment_id`
- `description`
- `output_dir`
- `working_dir_root`
- `repeats`
- `bootstrap_skill`
- `tasks` (inline) **or** `tasks_file` (path to a JSON array of tasks)
- `models` (inline) **or** `models_file` (path to a JSON array of model entries — the three production specs all point at [`eval/specs/models.json`](specs/models.json) so the panel is controlled in one place)
- `skills`

`tasks_file` and `models_file` let multiple specs share the same task collection / model panel. Specifying both inline and file forms for the same field is an error.

The runner supports:

- LLM benchmarking by varying `models`
- skill ablation by varying `skills`
- task difficulty benchmarking by varying `tasks`

By default, eval-generated ColPack workflow directories are rooted under `eval/data/` via environment variable `COLPACK_WORKING_DIR_ROOT`. That keeps simulation artifacts separate from the standalone agent's default `data/` tree. **The runner namespaces by model**, setting `COLPACK_WORKING_DIR_ROOT=eval/data/<model_label>/` per run, so simulation artifacts created by one LLM (e.g. `eval/data/claude-haiku-4.5/2d_nvt_disk/`) never collide with another's. Fixtures live at the shared `eval/data/fixtures/` and are accessed by absolute path from the index, so they remain visible to every model regardless of the per-model namespace. `clean` and `--clean-data` sweep all per-model folders while preserving `fixtures/`.

## Notes

- The runner reuses the same prompt loading and MCP connection logic as the standalone wrapper.
- Skill bootstrap is enabled by default to mirror `app.py`.
- Success scoring is currently liveness-only — see the [Scoring](#scoring) section above for what that catches and what it doesn't, plus the planned hybrid replacement.
