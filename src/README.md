# ColPack

Hard-particle Monte Carlo packing simulations for colloidal systems, built on
[HOOMD-blue](https://glotzerlab.engin.umich.edu/hoomd-blue/)'s HPMC integrator.
ColPack orchestrates the full pipeline — problem setup, parameter sweep
planning, simulation execution, and analysis — and exposes it both as a Python
API and as an MCP tool surface for agent-driven workflows.

## Installation

ColPack depends on **HOOMD-blue** and **OVITO**, which are not available on
PyPI and must be installed from conda-forge. The recommended setup is a conda
environment with those two packages, then `pip install colpack` on top:

```bash
conda create -n colpack python=3.11
conda activate colpack
conda install -c conda-forge hoomd ovito
pip install colpack
```

The remaining dependencies (`numpy`, `gsd`, `freud-analysis`, `matplotlib`,
`pydantic`, `mcp`) are resolved automatically by pip.

## Capabilities

### Dimensions, shapes, and ensembles

| Dimension | Allowed shapes |
|-----------|---------------|
| 2D | `disk`, `ellipse`, `triangle`, `square`, `rectangle`, `capsule` |
| 3D | `sphere`, `ellipsoid`, `cube`, `octahedron`, `tetrahedron`, `capsule` |

| Ensemble | What's fixed | Tunable system parameter |
|----------|-------------|-------------------------|
| NVT | particle count + box volume | `volume_fraction` |
| NPT | particle count + pressure | `P` |

### Variations supported in a sweep

Across the dimension × shape × ensemble grid above, ColPack can express five
kinds of variation. Any combination of these can be specified as a parameter
sweep through the planner.

1. **System volume fraction (NVT)** — sweep `volume_fraction`. With fixed N
   and shape, compress the box to a series of target packing fractions to
   trace an equation-of-state isotherm at fixed composition.

2. **Per-component relative volume fraction** — sweep
   `particle_specs.<i>.relative_volume_fraction`. In a multi-component
   system this controls how the total volume budget is split across particle
   types. The first component is normalized to 1; values for other
   components set their volume share relative to it.

3. **Per-shape geometric parameters** — sweep any shape's intrinsic
   geometry, e.g. `particle_specs.<i>.diameter` (disk, sphere, capsule),
   `particle_specs.<i>.length` (capsule, rectangle), `particle_specs.<i>.width`
   (rectangle), `particle_specs.<i>.a` / `b` / `c` (ellipse, ellipsoid),
   `particle_specs.<i>.side` (triangle, square, cube, octahedron,
   tetrahedron). The full per-shape default set lives in
   [`colpack/colpack_config.json`](colpack/colpack_config.json) under
   `dimensions.<d>.shape_parameters`.

4. **System pressure (NPT)** — sweep `P`. With fixed N, the box volume
   fluctuates to reach a target pressure. Sweeping P traces the
   equation of state at the chosen shape and composition.

5. **Mixtures** — pass a multi-entry `particle_shape_list` at setup to
   build binary or higher-order mixtures in 2D or 3D. Variations 1–4 then
   apply on top of any per-component knob.

   **HPMC compatibility constraint** (inherited from HOOMD-blue):
   - In **2D**, `ellipse` cannot be mixed with polygon/rod shapes
     (`triangle`, `square`, `rectangle`, `capsule`).
   - In **3D**, `ellipsoid` cannot be mixed with polyhedron/rod shapes
     (`cube`, `octahedron`, `tetrahedron`, `capsule`).
   - `disk` (2D) and `sphere` (3D) promote to whichever integrator the
     rest of the mixture needs and are compatible with everything.

   The compatibility matrix and integrator-selection logic live in
   [`colpack/initialize.py`](colpack/initialize.py)
   (`select_optimal_integrator`).

Sweeps are submitted to `plan_simulation_runs_tool` via two arguments:
`baseline_parameters` (fixed overrides on the setup) and `tunable_parameters`
(parameter path → list of values). Both support nested dot-paths
(e.g. `particle_specs.0.diameter`). Tunable entries expand
**one-parameter-at-a-time** over the baseline rather than as a full Cartesian
product.

### Workflow pipeline

A simulation goes through four stages in order. Each stage has both a Python
function in [`colpack/workflow.py`](colpack/workflow.py) and an MCP tool in
[`colpack/mcp/server.py`](colpack/mcp/server.py).

| Stage | MCP tool | Outputs |
|-------|----------|---------|
| 1. Setup | `setup_simulation_problem_tool` | `simulation_problem.json` in a canonical `working_dir` |
| 2. Plan | `plan_simulation_runs_tool` | `simulation_baseline.json`, `simulation_plan.json`, one `run_*/` dir per planned run |
| 3. Execute | `execute_simulation_workflow_tool` | per-run `init.gsd`, `compress.gsd`, `sample.gsd`; updates to `workflow_status.csv` |
| 4. Analyze | `analyze_simulation_runs_tool` | per-run order-parameter time series, RDF, plots; updates to `workflow_status.csv` |

The capabilities tool `get_colpack_capabilities_tool` returns the live config
(supported shapes, ensembles, key parameters, workflow steps) and is the
recommended source of truth for agents.

#### Inside the Execute stage

Each run cycles through three sub-steps before analysis:

1. **Initialize** — generate a low-density configuration and `init.gsd` with
   the integrator and shape definitions selected automatically per shape.
2. **Compress** — drive the system from the initial dilute state to the
   target packing fraction (NVT) or pressure (NPT) via staged
   `QuickCompress` (NVT) or `BoxMC` updaters (NPT).
3. **Sample** — equilibrate and record a trajectory at the target state
   point. Auto-tunes HPMC trial-move sizes; for NPT also auto-tunes the
   `BoxMC` volume move.

Equilibrium is detected on the fly from a pointwise sigma gate over the
sampled time series.

### Analysis

ColPack drives [freud](https://freud.readthedocs.io) for order-parameter and
density analysis. Defaults are shape-aware, and additional parameters can be
added per call.

#### Order parameters (per shape default)

| Shape | Default order params |
|-------|---------------------|
| `disk` | Hexatic ψ₆ |
| `triangle` | Hexatic ψ₃ |
| `square` | Hexatic ψ₄ |
| `rectangle` | Nematic + Hexatic ψ₂ |
| `ellipse`, `ellipsoid`, `capsule` | Nematic |
| `sphere` | Steinhardt q₆, q₄ + SolidLiquid |
| `tetrahedron` | Steinhardt q₃ + SolidLiquid |
| `cube` | Steinhardt q₄ + Cubatic |

Any of the following can be added via the `extra_order_params` argument:

| Type | Notes |
|------|-------|
| `Hexatic` | 2D bond-orientational order; pick `k` to match lattice symmetry |
| `Nematic` | Nematic order from per-particle orientation vectors |
| `Steinhardt` | 3D bond-orientational order; pick `l` per target lattice |
| `SolidLiquid` | Per-particle solid/liquid classification (3D) |
| `Cubatic` | Cubatic order via simulated annealing |
| `ContinuousCoordination` | Voronoi-based continuous coordination |
| `RotationalAutocorrelation` | Rotational time autocorrelation |

#### Density analysis

| Type | Notes |
|------|-------|
| `RDF` | Radial distribution function g(r); auto-computed for multi-component systems |
| `LocalDensity` | Per-particle local number density / packing fraction |
| `GaussianDensity` | Gaussian-smeared density field on a grid |
| `CorrelationFunction` | Spatial correlation of per-particle scalar quantities |

#### System analysis

| Type | Notes |
|------|-------|
| `VolumeFraction` | Per-frame system packing fraction φ from the simulated box volume |

## Outputs

Per `working_dir`:

- `simulation_problem.json`, `simulation_baseline.json`, `simulation_plan.json`
- `run_*/init.gsd`, `compress.gsd`, `sample.gsd` (HOOMD trajectory)
- `run_*/order_params.json`, `rdf.json`, plot images
- `workflow_status.csv` — one row per run, latest state per row
- `workflow_progress.json`, `workflow_events.log` — async progress for the
  agent / monitor CLI to consume

## Programmatic use

```python
from colpack.workflow import (
    setup_simulation_problem,
    plan_simulaiton_runs,         # note: legacy spelling preserved in the API
    execute_simulation_workflow,
    analyze_simulation_runs,
)

setup_simulation_problem(
    dimension=3,
    total_particle_number=500,
    particle_shape_list=["sphere"],
    ensemble="NVT",
)
```

`setup_simulation_problem` resolves and returns the canonical `working_dir`;
pass that same value through to the planner, executor, and analyzer.

## MCP server

The package ships an MCP server exposing the five workflow tools. Launch it
with:

```bash
python -m colpack.mcp.server
```

The wrapper in `agent/app.py` connects to this server when the agent runs
end-to-end workflows.

## Configuration

[`colpack/colpack_config.json`](colpack/colpack_config.json) is the live config: allowed shapes per dimension,
ensemble requirements, default integration / compression / sampling
parameters, analysis catalog, and per-shape order-parameter defaults.
The capabilities tool reads from this file, so editing it propagates to
both the Python API and the agent.

## Dependencies

Provided by conda-forge (system prerequisites, see Installation above):

- [hoomd-blue](https://glotzerlab.engin.umich.edu/hoomd-blue/) (HPMC integrator)
- [ovito](https://www.ovito.org/) (rendering / per-frame visualization)

Resolved automatically by pip:

- [freud](https://freud.readthedocs.io) (analysis)
- [gsd](https://gsd.readthedocs.io) (trajectory I/O)
- [pydantic](https://docs.pydantic.dev/), [mcp](https://modelcontextprotocol.io/),
  numpy, matplotlib
