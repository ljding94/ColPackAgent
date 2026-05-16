# Guide: Setup Simulation Problem

Call `setup_simulation_problem_tool` with **exactly these four fields** — nothing else:

```json
{
  "dimension": 2,
  "total_particle_number": 200,
  "particle_shape_list": ["disk", "capsule"],
  "ensemble": "NVT"
}
```

The tool resolves `working_dir` itself. Do not pass it, do not ask for it.

## Field Rules

- `dimension`: `2` or `3`.
- `ensemble`: `"NVT"` or `"NPT"`.
- `total_particle_number`: positive integer.
- `particle_shape_list`: non-empty list drawn from Allowed Shapes below.

## Allowed Shapes

- **2D**: `disk`, `ellipse`, `triangle`, `square`, `rectangle`, `capsule`
- **3D**: `sphere`, `ellipsoid`, `cube`, `octahedron`, `tetrahedron`, `capsule`

## Mixture Compatibility

Check the capability tool's `mixture_compatibility.incompatible_rules` before calling setup.

- **2D**: `ellipse` cannot be mixed with `triangle`, `square`, `rectangle`, or `capsule`.
- **3D**: `ellipsoid` cannot be mixed with `cube`, `octahedron`, `tetrahedron`, or `capsule`.

If a prompt requests an incompatible mixture, do not call `setup_simulation_problem_tool`. Explain that HOOMD-blue HPMC has no single compatible integrator for that shape combination and ask the user to choose a replacement shape or separate simulations.

## What to Ask (and What NOT to Ask)

Setup collects **only** the four fields above. In interactive mode, ask for every missing field in a single consolidated message with common-choice suggestions.

Inference rules:

- Infer `dimension` only when every named shape is dimension-locked (e.g. "cube" → 3D, "disk" → 2D). State the inference so the user can override.
- `ensemble` and `total_particle_number` are never inferable — always ask if missing.
- `particle_shape_list` is taken verbatim from the user's named shapes.

Do **not** mention, ask about, or include in the payload any of: `working_dir`, `volume_fraction`, pressure, sweep values, sampling steps, temperature, boundary conditions, box shape, or box length. Those either belong to a later stage (planning/execution) or are auto-resolved. Move on to planning in the next turn — after setup is confirmed.

## Anti-Example

Bad — mixes setup + planning + forbidden `working_dir`:

> - Ensemble: NVT or NPT?
> - Number of particles: 512, 1000, 2048?
> - What volume fractions to sweep?        ← planning, wrong stage
> - Where should I set up the simulation?  ← forbidden; setup resolves working_dir

Good — setup-only, consolidated:

> I'll infer 3D from "cube". I need two more setup details:
>
> - **Ensemble**: NVT (fixed volume) or NPT (fixed pressure)?
> - **Number of particles**: e.g. 256 / 512 / 1024?
>
> I'll move on to planning (volume fraction or pressure sweep) after setup.

## Output

On success, `simulation_problem.json` is written to the resolved `working_dir`, and the tool returns that path. Reuse the returned `working_dir` verbatim in planning and execution.
