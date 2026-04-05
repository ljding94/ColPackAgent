# Guide: Plan Simulation Runs

When calling `plan_simulation_runs_tool`, use this exact top-level payload:

```json
{
  "baseline_parameters": {},
  "tunable_parameters": {},
  "working_dir": "/absolute/or/user/provided/path"
}
```

## Required Rules
- `baseline_parameters` must be a dictionary.
- `tunable_parameters` must be a non-empty dictionary.
- Each `tunable_parameters` entry must map to a non-empty list.
- `working_dir` must be exactly the same string used in setup (`WORKING_DIR`).
- Recommended default location is under project root `data/` using setup naming rules.

## Dot-Path Convention
Use dot paths to address nested fields, including particle specs:
- `volume_fraction`
- `P`
- `particle_specs.0.diameter`
- `particle_specs.1.length`
- `particle_specs.1.relative_volume_fraction`

Indexing in `particle_specs.N.*` is zero-based.

## Valid Example: 2D NVT Parameter Sweep
```json
{
  "baseline_parameters": {
    "volume_fraction": 0.35,
    "sampling_steps": 200000,
    "particle_specs.0.diameter": 1.0,
    "particle_specs.1.length": 2.0,
    "particle_specs.1.diameter": 0.5
  },
  "tunable_parameters": {
    "volume_fraction": [0.30, 0.35, 0.40],
    "particle_specs.1.length": [1.5, 2.0, 2.5]
  },
  "working_dir": "data/2d_nvt_disk_capsule"
}
```

## Valid Example: 3D NPT Pressure Sweep
```json
{
  "baseline_parameters": {
    "P": 1.0,
    "sampling_steps": 300000,
    "particle_specs.0.diameter": 1.0,
    "particle_specs.1.a": 1.0,
    "particle_specs.1.b": 0.6,
    "particle_specs.1.c": 0.5
  },
  "tunable_parameters": {
    "P": [0.5, 1.0, 2.0],
    "particle_specs.1.a": [0.8, 1.0, 1.2]
  },
  "working_dir": "data/3d_npt_sphere_ellipsoid"
}
```

## Invalid Example: Empty Tunable Parameters
```json
{
  "baseline_parameters": {
    "volume_fraction": 0.3
  },
  "tunable_parameters": {},
  "working_dir": "/data/bad_case"
}
```

Reason: `tunable_parameters` must be non-empty.

## Invalid Example: Non-List Sweep Values
```json
{
  "baseline_parameters": {
    "volume_fraction": 0.3
  },
  "tunable_parameters": {
    "volume_fraction": 0.4
  },
  "working_dir": "/data/bad_case"
}
```

Reason: each tunable parameter value must be a list.

## Expected Result
On success, the tool writes:
- `simulation_baseline.json`
- `simulation_plan.json`
- `run_0`, `run_1`, ... directories with per-run `simulation_config.json`

## Consistency Check Before Call
Ensure:

```json
{
  "setup_working_dir": "data/2d_nvt_disk_capsule",
  "plan_working_dir": "data/2d_nvt_disk_capsule",
  "match": true
}
```

Only call the tool when `match` is true.