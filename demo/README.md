# ColPack Demo Runs

This folder provides two demonstration runs that reuse the `eval` runner while using the production ColPack skill under `agent/skills/colpack/`.

- Interactive staged demo: `demo/specs/interactive_demo.json`
- Autonomous end-to-end demo: `demo/specs/autonomous_demo.json`

Both demos write simulation artifacts under `demo/data/` and run outputs under `demo/runs/`.

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

## Notes

- Add `--limit N` to cap planned runs.
- Add `--no-bootstrap-skill` to disable startup capability bootstrap.
- You can inspect generated manifests and summaries in `demo/runs/<interactive|autonomous>/`.
