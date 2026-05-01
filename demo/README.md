# ColPack Demo Runs

This folder provides three demonstration runs that reuse the `eval` runner while using the production ColPack skill under `agent/skills/colpack/`.

- Interactive staged demo: `demo/specs/interactive_demo.json`
- Autonomous end-to-end demo: `demo/specs/autonomous_demo.json`
- ColPackAgent-assisted scientific study: `demo/specs/assisted_study_demo.json`

All three demos write simulation artifacts under `demo/data/` and run outputs under `demo/runs/`.

## Interactive Demo

Dry run:

```bash
./demo/run_interactive_demo.sh --dry-run
```

Execute:

```bash
./demo/run_interactive_demo.sh
```

## Autonomous Demo

Dry run:

```bash
./demo/run_autonomous_demo.sh --dry-run
```

Execute:

```bash
./demo/run_autonomous_demo.sh
```

## Assisted Study Demo

Open scientific goal driven by a Karpathy-style **research program**
(`demo/specs/assisted_study_program.md`) that fixes the methodology — system
size, sample-step floor, sweep resolution, order-parameter rules, reporting
format — while leaving the scientific choices (composition, pressure range,
hypotheses) to the agent. The shipped scenario is the phase transition of 2D
hard disks and hard squares in the NPT ensemble.

Unlike the interactive and autonomous demos above, this one **bypasses the
eval/opencode-SDK runner** and goes through the native Claude Code CLI via
`run_colpack.sh claude`, so the agent runs with the production MCP + skill
stack exactly as an end-user would, just with the initial prompt prefilled
to point at the research program.

Prerequisites:

- `./run_colpack.sh setup` has been run at least once (registers the colpack
  skill into `~/.claude/skills/`).
- `claude` CLI is on PATH and you're authenticated.

Execute (interactive Claude Code session; allow ~30–60 min):

```bash
./demo/run_assisted_study_demo.sh
```

Pass extra flags through to `claude` after the wrapper if you need them, e.g.:

```bash
./demo/run_assisted_study_demo.sh --permission-mode acceptEdits
```

## Notes

- Add `--limit N` to cap planned runs.
- Add `--no-bootstrap-skill` to disable startup capability bootstrap.
- You can inspect generated outputs in `demo/runs/<interactive|autonomous>/`: `planned_runs.json`, `results.jsonl`, `summary.json`, and `conversations/<run_id>.md`.
