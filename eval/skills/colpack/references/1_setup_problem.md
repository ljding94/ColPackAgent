# Guide: Setup Simulation Problem

When calling `setup_simulation_problem_tool`, your payload must match one of these shapes:

```json
{
  "dimension": 2,
  "total_particle_number": 200,
  "particle_shape_list": ["disk", "capsule"],
  "ensemble": "NVT"
}
```

## Required Rules

- `dimension` must be `2` or `3`.
- `total_particle_number` must be a positive integer.
- `particle_shape_list` must be a non-empty list of strings.
- `ensemble` must be `NVT` or `NPT`.
- `setup_simulation_problem_tool` resolves `working_dir` deterministically under project root `data/` from `dimension`, `ensemble`, and `particle_shape_list`.
- If environment variable `COLPACK_WORKING_DIR_ROOT` is set, setup resolves `working_dir` under that directory instead. This is intended for isolated experiment runs.
- Treat this `working_dir` as the workflow anchor directory and reuse the exact same value in planning and execution.
- ColPack packing workflows here are athermal hard-particle simulations. Do not ask for or include temperature unless the user explicitly requests a thermal model outside this workflow.
- In the standalone wrapper, setup-stage questions should be limited to setup-stage requirements only. Do not ask for planning or execution parameters before setup is complete.
- Setup requires `dimension`, `total_particle_number`, `particle_shape_list`, and `ensemble` only. Do not ask the user to provide or confirm `working_dir` during setup.
- Do not ask for or include initial volume fraction, `volume_fraction`, number density, pressure sweeps, sampling steps, boundary conditions, box shape, initial box length, or any other box initialization control in the setup payload.
- For NVT workflows, `volume_fraction` belongs in planning via `plan_simulation_runs_tool`, not in setup. For NPT workflows, pressure belongs in planning, not in setup.
- Boundary conditions are implicit defaults in this workflow and are not a normal user input for setup.

## Default Folder Rule

Do not include `working_dir` in the setup payload. `setup_simulation_problem_tool` is authoritative for computing the canonical workflow directory from the setup inputs.
If the user explicitly asks for the default working directory, the wrapper may show the resolved path before the call, but the setup tool determines the same path itself.

Naming template:

- `working_dir = data/{dimension}d_{ensemble}_{shape_slug}`
- `ensemble` must be lowercase (`nvt` or `npt`).
- `shape_slug` is `particle_shape_list` joined by `_`, preserving order.

If `COLPACK_WORKING_DIR_ROOT` is set, replace the `data/` prefix with that directory.

Examples:

- `data/2d_nvt_disk_capsule`
- `data/3d_npt_sphere_ellipsoid`

If folder exists, append `_v2`, `_v3`, and so on.

## Allowed Shapes

### 2D

- `disk`
- `ellipse`
- `triangle`
- `square`
- `rectangle`
- `capsule`

### 3D

- `sphere`
- `ellipsoid`
- `cube`
- `octahedron`
- `tetrahedron`
- `capsule`

## Valid Example: Binary 2D NVT With Default Working Directory

```json
{
  "dimension": 2,
  "total_particle_number": 256,
  "particle_shape_list": ["disk", "capsule"],
  "ensemble": "NVT"
}
```

The setup tool resolves `working_dir` to `data/2d_nvt_disk_capsule` if that folder is unused.

## Valid Example: 3D NPT Mixture

```json
{
  "dimension": 3,
  "total_particle_number": 512,
  "particle_shape_list": ["sphere", "ellipsoid"],
  "ensemble": "NPT"
}
```

## Expected Result

On success, `simulation_problem.json` is written to `working_dir`.

## Path State Rule

After setup, store the returned `working_dir` from the tool result as workflow state:

```json
{
  "WORKING_DIR": "data/2d_nvt_disk_capsule"
}
```

Then pass this exact same `WORKING_DIR` in step 2 and step 3.
