# Guide: Setup Simulation Problem

When calling `setup_simulation_problem_tool`, your payload must exactly match this shape:

```json
{
  "dimension": 2,
  "total_particle_number": 200,
  "particle_shape_list": ["disk", "capsule"],
  "ensemble": "NVT",
  "working_dir": "/absolute/or/user/provided/path"
}
```

## Required Rules
- `dimension` must be `2` or `3`.
- `total_particle_number` must be a positive integer.
- `particle_shape_list` must be a non-empty list of strings.
- `ensemble` must be `NVT` or `NPT`.
- `working_dir` must be a writable path string.
- Treat this `working_dir` as the workflow anchor directory and reuse the exact same value in planning and execution.

## Default Folder Rule
If the user does not specify `working_dir`, suggest one under project root `data/`.

Naming template:
- `working_dir = data/{dimension}d_{ensemble}_{shape_slug}`
- `ensemble` must be lowercase (`nvt` or `npt`).
- `shape_slug` is `particle_shape_list` joined by `_`, preserving order.

Examples:
- `data/2d_nvt_disk_capsule`
- `data/3d_npt_sphere_ellipsoid`

If folder exists, append `_v2` or date suffix (for example `_20260405`).

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

## Valid Example: Binary 2D NVT
```json
{
  "dimension": 2,
  "total_particle_number": 256,
  "particle_shape_list": ["disk", "capsule"],
  "ensemble": "NVT",
  "working_dir": "data/2d_nvt_disk_capsule"
}
```

## Valid Example: 3D NPT Mixture
```json
{
  "dimension": 3,
  "total_particle_number": 512,
  "particle_shape_list": ["sphere", "ellipsoid"],
  "ensemble": "NPT",
  "working_dir": "data/3d_npt_sphere_ellipsoid"
}
```

## Invalid Example: Wrong Dimension
```json
{
  "dimension": 4,
  "total_particle_number": 200,
  "particle_shape_list": ["sphere"],
  "ensemble": "NVT",
  "working_dir": "/data/bad_case"
}
```

Reason: `dimension` must be `2` or `3`.

## Invalid Example: Empty Shape List
```json
{
  "dimension": 2,
  "total_particle_number": 200,
  "particle_shape_list": [],
  "ensemble": "NVT",
  "working_dir": "/data/bad_case"
}
```

Reason: `particle_shape_list` must be non-empty.

## Expected Result
On success, `simulation_problem.json` is written to `working_dir`.

## Path State Rule
After setup, store this as workflow state:

```json
{
  "WORKING_DIR": "data/2d_nvt_disk_capsule"
}
```

Then pass this exact same `WORKING_DIR` in step 2 and step 3.