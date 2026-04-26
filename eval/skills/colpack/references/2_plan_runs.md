# Guide: Plan Simulation Runs

`plan_simulation_runs_tool` payload:

```json
{
  "baseline_parameters": {},
  "tunable_parameters": {},
  "working_dir": "<WORKING_DIR>"
}
```

## Mental Model

`simulation_problem.json` is the source of truth. Planning overlays it to produce per-run configs.

- `baseline_parameters`: single-value overrides applied to **every** run.
- `tunable_parameters`: per-parameter **lists** — each value produces one run. Sweep is one-parameter-at-a-time, not a grid.
- Single run = one `tunable_parameters` entry with a single-element list (e.g. `[1.0]`). `tunable_parameters` must be non-empty.

### Fixed vs Tunable

Fixed at setup, cannot change in planning:

- `dimension`, `ensemble`, `total_particle_number`, `particle_specs[*].shape`

**Everything else in `simulation_problem.json` is tunable** — `volume_fraction`, `P`, `sampling_steps`, every shape parameter, `relative_volume_fraction`, etc. A `"Nan"` placeholder is no more special than a concrete value; both are equally valid as baseline or tunable. `"Nan"` just signals that setup did not pick a default — if left out, the config fallback is used.

## Required Rules

- `baseline_parameters`: dict.
- `tunable_parameters`: non-empty dict; each value is a non-empty list.
- `working_dir`: exact string returned by setup.
- Every key must already exist as a dot-path in `simulation_problem.json` — do not invent top-level keys.
- Shape parameters live under `particle_specs.N.*` (zero-based), not flat. Copy paths verbatim from the JSON.

## Interactive Flow

1. **Read** `working_dir/simulation_problem.json`.
2. **Enumerate** every non-fixed parameter with its dot-path and current value. Example:

   ```text
   Tunable candidates (any can be baseline OR tunable):
     • P                                            current: 1.0
     • sampling_steps                               current: 20000
     • particle_specs.0.side                        Nan
     • particle_specs.0.relative_volume_fraction    current: 1
   ```

3. **Ask** which parameters (if any) to sweep and at what values. A single run is valid. Do not presuppose `P` for NPT or `volume_fraction` for NVT.
4. **Show the draft payload** and wait for approval before calling the tool.

## Example: Single Run, No Sweep

NPT cubes, default pressure, `side = 1.0`:

```json
{
  "baseline_parameters": { "sampling_steps": 200000 },
  "tunable_parameters": { "particle_specs.0.side": [1.0] },
  "working_dir": "data/3d_npt_cube"
}
```

## Example: Multi-Run Sweep

2D NVT disk+capsule, sweep `volume_fraction` with fixed shape geometry:

```json
{
  "baseline_parameters": {
    "sampling_steps": 200000,
    "particle_specs.0.diameter": 1.0,
    "particle_specs.1.length": 2.0,
    "particle_specs.1.diameter": 0.5
  },
  "tunable_parameters": {
    "volume_fraction": [0.30, 0.35, 0.40, 0.45]
  },
  "working_dir": "data/2d_nvt_disk_capsule"
}
```

## Invalid: Flat Shape Keys

```json
{
  "baseline_parameters": { "width": 1.0 },
  "tunable_parameters":  { "length": [3.0, 5.0, 7.0] }
}
```

Shape parameters must use the nested path (`particle_specs.0.width`, `particle_specs.0.length`).

## Expected Result

Writes `simulation_baseline.json`, `simulation_plan.json`, and `run_0`, `run_1`, ... directories each containing `simulation_config.json`.

## Consistency Check

Verify `setup_working_dir == plan_working_dir` before calling. If they differ, stop and reconcile.
