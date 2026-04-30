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

Open scientific goal — the agent designs the parameter sweep itself, executes it,
and interprets the results. The shipped scenario asks the agent to study the phase
transition of 2D hard disks and hard squares in the NPT ensemble; the agent picks
the composition (pure disks, pure squares, or a mixture), the pressure grid, and
the order parameters (e.g. ψ_6 for disks, cubatic P_4 for squares), then
characterizes the disordered-to-ordered transition end to end.

Dry run:

```bash
./demo/run_assisted_study_demo.sh --dry-run
```

Execute (allow ~30–60 min wall time; the agent runs an end-to-end pressure sweep):

```bash
./demo/run_assisted_study_demo.sh
```

## Notes

- Add `--limit N` to cap planned runs.
- Add `--no-bootstrap-skill` to disable startup capability bootstrap.
- You can inspect generated outputs in `demo/runs/<interactive|autonomous>/`: `planned_runs.json`, `results.jsonl`, `summary.json`, and `conversations/<run_id>.md`.
