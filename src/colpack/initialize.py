import os
import hoomd
import numpy as np
import math
import json
from colpack.helper import save_state
from colpack.config_reading import canonicalize_shape, get_allowed_shapes, get_initialize_config
from colpack.visualize_ovito import visualize_gsd


def create_initial_config(run_dir):
    """
    Create initial configuration from simulation_config.json in run_dir.
    """

    # 0) check necessary input files
    if not run_dir:
        raise ValueError("run_dir must be provided.")

    simulation_config_path = os.path.join(run_dir, "simulation_config.json")
    if not os.path.exists(simulation_config_path):
        raise FileNotFoundError(f"simulation_config.json not found in run_dir: {run_dir}")

    with open(simulation_config_path, "r") as f:
        simulation_config = json.load(f)

    dimension = simulation_config.get("dimension")
    particle_specs = simulation_config.get("particle_specs")

    if dimension not in (2, 3):
        raise ValueError("dimension must be either 2 or 3.")
    if not isinstance(particle_specs, list) or len(particle_specs) == 0:
        raise ValueError("particle_specs must be a non-empty list of dictionaries.")

    # 1) enhance simulation config, add per-shape volume, calculate realized particle relative volume fraction, particle number, and particle_list (hoomd-blue ready)
    simulation_config_enhanced = simulation_config.copy()  # shallow copy to avoid modifying the original config
    simulation_config_enhanced = enhance_simulation_config_particle_specs(simulation_config_enhanced)
    # save enhanced config for debugging and downstream use
    enhanced_config_path = os.path.join(run_dir, "simulation_config_enhanced.json")
    with open(enhanced_config_path, "w") as f:
        json.dump(simulation_config_enhanced, f, indent=4)

    particle_specs = simulation_config_enhanced["particle_specs"]

    # 2) get particle list
    total_N, particle_list = create_minimal_particle_list(dimension, particle_specs)
    # particle_list include particle_volume, particle number, realized_relative_volume_fraction,
    # and the shape parameters needed for initializing the HPMC integrator

    # set up HPMC integrator
    integrator, resolved_particle_list = resolve_hpmc_integrator_and_shapes(dimension=dimension, particle_list=particle_list)
    particle_list = resolved_particle_list  # update particle list accordingly
    if integrator is None:
        raise ValueError("No compatible HPMC integrator found for the given particle specifications.")
    initialize_config = get_initialize_config()
    mc = integrator(
        default_d=initialize_config.get("default_d", 1.0),
        default_a=initialize_config.get("default_a", 0.1),
    )

    # insert particles
    for particle in particle_list:
        mc.shape[particle["pType"]] = particle["pShape"]

    # 3 ) Initial box: keep low density to minimize initial overlaps before compression.
    initial_volume_fraction = initialize_config.get("initial_volume_fraction", 0.02)
    overlap = 1
    max_overlap_reduction_iters = initialize_config.get("max_overlap_reduction_iters", 10)
    for _ in range(max_overlap_reduction_iters):
        initial_volume_fraction *= 0.5  # make it smaller to avoid overlaps
        initial_box_volume = simulation_config_enhanced["total_particle_volume"] / initial_volume_fraction
        initial_box_L = initial_box_volume ** (1 / dimension)

        # Initialize HOOMD
        if hoomd.device.GPU.is_available():
            print("GPU is available. Using GPU for initialization.")

        device = hoomd.device.GPU() if hoomd.device.GPU.is_available() else hoomd.device.CPU()
        sim = hoomd.Simulation(device=device)

        # Create snapshot
        snapshot = hoomd.Snapshot()
        snapshot.particles.N = total_N
        snapshot.particles.types = [particle["pType"] for particle in particle_list]
        snapshot.particles.typeid[:] = np.concatenate([np.full(particle["pNum"], i, dtype=np.int32) for i, particle in enumerate(particle_list)])  # create a map from id to type

        if dimension == 2:
            snapshot.configuration.box = [initial_box_L, initial_box_L, 0, 0, 0, 0]

        elif dimension == 3:
            snapshot.configuration.box = [initial_box_L, initial_box_L, initial_box_L, 0, 0, 0]

        # initialize positions on a simple cubic for dim=3, square for dim 2 lattice
        grid_size = math.ceil(total_N ** (1 / dimension))
        spacing = initial_box_L / grid_size
        positions = []
        for i in range(total_N):
            x = (i % grid_size + 0.5) * spacing - initial_box_L / 2
            y = ((i // grid_size) % grid_size + 0.5) * spacing - initial_box_L / 2
            z = (i // (grid_size**2) + 0.5) * spacing - initial_box_L / 2 if dimension == 3 else 0
            positions.append([x, y, z])

        # Shuffle positions
        rng = np.random.default_rng()
        rng.shuffle(positions)
        snapshot.particles.position[:] = positions

        snapshot.particles.orientation[:] = [[1, 0, 0, 0]] * total_N  # default orientation (no rotation)
        sim.create_state_from_snapshot(snapshot)

        sim.operations.integrator = mc

        # run 0 step to initialize
        sim.run(0)
        print(f"Initial configuration created with {total_N} particles in a box of size {initial_box_L:.3f}. \n with overlap {mc.overlaps}")
        overlap = mc.overlaps  # read overlap for checking
        if not overlap:
            break

    if overlap:
        raise RuntimeError(
            f"Failed to generate a non-overlapping initial configuration after {max_overlap_reduction_iters} attempts. " f"Final overlap={overlap}, initial_volume_fraction={initial_volume_fraction}."
        )

    print("Particle list:")
    for particle in particle_list:
        print(f"  Type: {particle['pType']}, Number: {particle['pNum']}, Integrator: {particle['pIntegrator']}, Shape: {particle['pShape']}")

    simulation_config_initial = simulation_config_enhanced.copy()
    simulation_config_initial["initial_box_length"] = initial_box_L
    simulation_config_initial["initial_volume_fraction"] = initial_volume_fraction
    simulation_config_initial["initial_overlaps"] = overlap
    simulation_config_initial["particle_list"] = particle_list
    simulation_config_initial["initial_gsd_path"] = os.path.join(run_dir, "initial.gsd")

    # Save the resolved definition of particles to a json file
    simulation_config_initial_path = os.path.join(run_dir, "simulation_config_initial.json")
    with open(simulation_config_initial_path, "w") as f:
        json.dump(simulation_config_initial, f, indent=4)

    # save the state to gsd
    gsd_path = os.path.join(run_dir, "initial.gsd")
    save_state(sim, resolved_particle_list, gsd_path)

    visualize_gsd(
        gsd_path=gsd_path,
        output_path=os.path.join(run_dir, "initial_render.png"),
        frame_index=-1,
    )

    return simulation_config_initial


############################
# pre processing of simulation config, add necessary infor such as particle number, particle volume, and realized relative volume fraction based on target relative volume fraction and total particle number
###########################
def enhance_simulation_config_particle_specs(simulation_config):
    """
    enhance the simulation config particle specs by adding per-shape volume, find the optimal particle number to have closest match to relative particle volume fraction, and add the realized particle volume fraction,
    """
    if not isinstance(simulation_config, dict):
        raise ValueError("simulation_config must be a dictionary.")

    dimension = simulation_config.get("dimension")
    if dimension not in (2, 3):
        raise ValueError("simulation_config.dimension must be either 2 or 3.")

    particle_specs = simulation_config.get("particle_specs")
    if not isinstance(particle_specs, list) or len(particle_specs) == 0:
        raise ValueError("simulation_config.particle_specs must be a non-empty list.")

    # 1) find particle volume
    enhanced_specs = []
    for idx, spec in enumerate(particle_specs):
        if not isinstance(spec, dict):
            raise ValueError(f"particle_specs[{idx}] must be a dictionary.")
        spec_enhanced = dict(spec)
        spec_enhanced["particle_volume"] = calculate_particle_volume(dimension, spec_enhanced)
        enhanced_specs.append(spec_enhanced)

    # 2) find particle number and realized relative volume fraction based on target relative volume fraction and total particle number
    counts, target_relative, realized_relative = find_optimal_particle_numbers(
        total_particle_number=simulation_config.get("total_particle_number"),
        particle_specs=enhanced_specs,
    )

    for idx, spec_enhanced in enumerate(enhanced_specs):
        spec_enhanced["relative_volume_fraction"] = 1.0 if idx == 0 else float(target_relative[idx])
        spec_enhanced["number"] = int(counts[idx])
        spec_enhanced["realized_relative_volume_fraction"] = float(realized_relative[idx])

    enhanced_config = dict(simulation_config)
    enhanced_config["particle_specs"] = enhanced_specs
    enhanced_config["total_particle_number"] = int(sum(counts))

    # add total particle volumes
    total_volume = sum(spec["number"] * spec["particle_volume"] for spec in enhanced_specs)
    enhanced_config["total_particle_volume"] = total_volume

    return enhanced_config


def calculate_particle_volume(dimension, particle_spec):
    """Return single-particle area (2D) or volume (3D) from shape parameters."""
    if dimension not in (2, 3):
        raise ValueError("dimension must be either 2 or 3.")
    if not isinstance(particle_spec, dict):
        raise ValueError("particle_spec must be a dictionary.")

    def _require_float(keys, parameter_name):
        for key in keys:
            if key in particle_spec and particle_spec.get(key) is not None:
                return float(particle_spec.get(key))
        raise ValueError(f"Missing required parameter '{parameter_name}' for shape '{shape}' in {dimension}D particle spec.")

    shape = particle_spec.get("shape", particle_spec.get("type"))
    if shape is None:
        raise ValueError("Each particle spec must include a 'shape' (or 'type') key.")
    shape = canonicalize_shape(dimension, str(shape).lower())
    allowed_shapes = get_allowed_shapes(dimension)
    if shape not in allowed_shapes:
        raise ValueError(f"Unsupported {dimension}D shape '{shape}'. Allowed shapes: {sorted(allowed_shapes)}")

    if dimension == 2:
        if shape == "disk":
            if particle_spec.get("radius") is not None:
                diameter = 2.0 * float(particle_spec.get("radius"))
            else:
                diameter = _require_float(["diameter", "sigma"], "diameter")
            radius = 0.5 * diameter
            return math.pi * radius * radius

        if shape == "ellipse":
            a = _require_float(["a"], "a")
            b = _require_float(["b"], "b")
            return math.pi * a * b

        if shape == "triangle":
            side = _require_float(["side", "length"], "side")
            return (math.sqrt(3.0) / 4.0) * side * side

        if shape == "square":
            side = _require_float(["side", "length"], "side")
            return side * side

        if shape == "rectangle":
            length = _require_float(["length", "L"], "length")
            width = _require_float(["width", "W"], "width")
            return length * width

        if shape == "capsule":
            length = _require_float(["length", "L"], "length")
            diameter = _require_float(["diameter", "D"], "diameter")
            radius = 0.5 * diameter
            # Stadium area = rectangle + circle.
            return length * diameter + math.pi * radius * radius

        raise ValueError(f"Unsupported 2D shape '{shape}'.")

    elif dimension == 3:
        if shape == "sphere":
            if particle_spec.get("radius") is not None:
                diameter = 2.0 * float(particle_spec.get("radius"))
            else:
                diameter = _require_float(["diameter", "sigma"], "diameter")
            radius = 0.5 * diameter
            return (4.0 / 3.0) * math.pi * radius**3

        if shape == "ellipsoid":
            a = _require_float(["a"], "a")
            b = _require_float(["b"], "b")
            c = _require_float(["c"], "c")
            return (4.0 / 3.0) * math.pi * a * b * c

        if shape == "capsule":
            length = _require_float(["length", "L"], "length")
            diameter = _require_float(["diameter", "D"], "diameter")
            radius = 0.5 * diameter
            return math.pi * radius * radius * length + (4.0 / 3.0) * math.pi * radius**3

        if shape == "tetrahedron":
            side = _require_float(["side", "length"], "side")
            return side**3 / (6.0 * math.sqrt(2.0))

        if shape == "cube":
            side = _require_float(["side", "length"], "side")
            return side**3

        if shape == "octahedron":
            side = _require_float(["side", "length"], "side")
            return (math.sqrt(2.0) / 3.0) * side**3

        raise ValueError(f"Unsupported 3D shape '{shape}'.")
    else:
        raise ValueError("dimension must be either 2 or 3.")


def find_optimal_particle_numbers(total_particle_number, particle_specs):
    """Find integer particle counts from total N and relative volume-fraction targets.

    Constraints:
    - Sum_i N_i = total_particle_number
    - N_i = (V_0 / V_i) * relative_i * N_0
    where relative_0 is fixed to 1.
    """

    # 1) read necessary inputs and validate, particle volumes and relative volume fraction targets are required to solve the equations.
    if not isinstance(particle_specs, list) or len(particle_specs) == 0:
        raise ValueError("particle_specs must be a non-empty list.")

    if total_particle_number is None:
        total_particle_number = sum(int(spec.get("number", 0)) for spec in particle_specs)
    total_particle_number = int(total_particle_number)
    if total_particle_number <= 0:
        raise ValueError("total_particle_number must be provided and positive.")

    volumes = [float(spec.get("particle_volume", 0.0)) for spec in particle_specs]
    if any(v <= 0 for v in volumes):
        raise ValueError("All particle specs must contain positive particle_volume values.")

    # Read target relative volume fractions directly from particle_specs.
    # relative_volume_fraction is defined relative to type 0 and fixed to 1.0.
    if any(spec.get("relative_volume_fraction") is None for spec in particle_specs[1:]):
        raise ValueError("Each non-first particle spec must define relative_volume_fraction (relative to particle type 0).")
    target_relative = [1.0] + [float(spec["relative_volume_fraction"]) for spec in particle_specs[1:]]
    if any(rel <= 0 for rel in target_relative[1:]):
        raise ValueError("All non-first relative_volume_fraction values must be positive.")

    # 2) Solve continuous counts from equations.
    weights = [1.0] + [target_relative[i] * volumes[0] / volumes[i] for i in range(1, len(particle_specs))]
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise ValueError("Invalid relative_volume_fraction and volume combination.")

    n0_float = total_particle_number / weight_sum
    raw_counts = [n0_float * w for w in weights]

    # 3) Round to nearest integers, then minimally balance by +-1 to hit exact total.
    counts = [max(1, int(round(x))) for x in raw_counts]
    diff = total_particle_number - sum(counts)

    def plus_cost(i):
        cur = counts[i]
        return abs((cur + 1) - raw_counts[i]) - abs(cur - raw_counts[i])

    def minus_cost(i):
        cur = counts[i]
        return abs((cur - 1) - raw_counts[i]) - abs(cur - raw_counts[i])

    while diff > 0:
        idx = min(range(len(counts)), key=plus_cost)
        counts[idx] += 1
        diff -= 1

    while diff < 0:
        candidates = [i for i in range(len(counts)) if counts[i] > 1]
        if not candidates:
            raise ValueError("Cannot reduce counts further while keeping all species present (>=1).")
        idx = min(candidates, key=minus_cost)
        counts[idx] -= 1
        diff += 1

    # 4) Calculate realized relative volume fractions from final integer counts and print summary.
    n0 = counts[0]
    v0 = volumes[0]
    realized_relative = [(counts[i] * volumes[i]) / (n0 * v0) for i in range(len(counts))]

    print("Particle count allocation summary (relative to type 0):")
    for i, (count, target, realized) in enumerate(zip(counts, target_relative, realized_relative)):
        print(f"  type {i}: N={count}, target={target:.6g}, realized={realized:.6g}")

    return counts, target_relative, realized_relative


############################
# make particle-list to be Hoomd-blue ready, with pType, pNum, pShape, and pIntegrator
############################
def create_minimal_particle_list(dimension, particle_specs):
    """
    dispatch to 2d or 3d version
    """
    if dimension == 2:
        return create_minimal_particle_list_2d(particle_specs)
    elif dimension == 3:
        return create_minimal_particle_list_3d(particle_specs)
    else:
        raise ValueError("Dimension must be either 2 or 3.")


def create_minimal_particle_list_2d(particle_specs):
    """
    only need to translate particle specs to hoomd shape parameters, use the minimal shape for each particle.

    for now let's define some standard particle_specs format

    2d examples for Pshape
    particle_specs[i] = {shape:"disk", diameter:1.0, number:50} -> {Ptype:"disk_0", Pnum:50, Pintegratpr: "Sphere", Pshape:{diameter:1.0}}
    particle_specs[i+1] = {shape:"disk", diameter:2.0, number:50} -> {Ptype:"disk_1", Pnum:50,Pintegratpr: "Sphere", Pshape:{diameter:2.0}} # different type since different size

    particle_specs[i] = {shape:"ellipse", a:1.0, b:0.5, number:50} -> {Ptype:"ellipse_0", Pnum:50, Pintegratpr: "Ellipsoid", Pshape:{a:1.0, b:0.5,}}

    particle_specs[i] = {shape:"triangle", side:l, number:50} -> {Ptype:"triangle_0", Pnum:50, Pintegratpr: "ConvexPolygon", Pshape:{vertices:[[0,0],[l,0],[0.5*l,0.5*1.7320508076*l]], sweep_radius:0}}

    particle_specs[i] = {shape:"square", side:l, number:50} -> {Ptype:"square_0", Pnum:50, Pintegratpr: "ConvexPolygon", Pshape:{vertices:[[0,0],[l,0],[l,l],[0,l]], sweep_radius:0}}

    particle_specs[i] = {shape:"rectangle", length:L, width:W, number:50} -> {Ptype:"rectangle_0", Pnum:50, Pintegratpr: "ConvexPolygon", Pshape:{vertices:[[0,0],[L,0],[L,W],[0,W]], sweep_radius:0}}

    particle_specs[i] = {shape:"capsule", length:L, diameter:D, number:50} -> {Ptype:"capsule_0", Pnum:50, Pintegratpr: "ConvexSphereopolygon", Pshape:{vertices:[[0,0],[L,0]], sweep_radius:D/2}}

    default shape values:
    disk: diameter=1.0
    ellipse: a=1.0, b=0.5
    triangle: side=1.0
    square: side=1.0
    rectangle: length=2.0, width=1.0
    capsule: length=2.0, diameter=0.5
    """

    if not isinstance(particle_specs, list) or len(particle_specs) == 0:
        raise ValueError("particle_specs must be a non-empty list of dictionaries.")

    particle_list = []
    total_N = 0
    name_counts = {}

    def _next_name(base):
        count = name_counts.get(base, 0)
        name_counts[base] = count + 1
        return f"{base}_{count}"

    for spec in particle_specs:
        if not isinstance(spec, dict):
            raise ValueError("Each particle spec must be a dictionary.")

        shape = spec.get("shape", spec.get("type"))
        if shape is None:
            raise ValueError("Each particle spec must include a 'shape' (or 'type') key.")
        shape = str(shape).lower()

        number = spec.get("number", spec.get("n", spec.get("count")))
        if number is None:
            raise ValueError(f"Missing 'number' for shape '{shape}'.")
        number = int(number)
        if number <= 0:
            raise ValueError(f"'number' must be positive for shape '{shape}'.")

        ptype = _next_name(shape)
        pintegrator = None
        pshape = None
        pdirector = None

        if shape in {"disk", "circle", "sphere"}:
            diameter = spec.get("diameter", spec.get("sigma"))
            if diameter is None and "radius" in spec:
                diameter = 2.0 * spec["radius"]
            if diameter is None:
                diameter = 1.0
            pintegrator = "Sphere"
            pshape = {"diameter": float(diameter)}

        elif shape in {"ellipse", "ellipsoid"}:
            a = spec.get("a", 1.0)
            b = spec.get("b", 0.5)
            # Default c to 0.25 (total thickness 0.5) for proper 2D visualization
            c = spec.get("c", 0.25)
            # make sure a>b>c
            a, b, c = sorted([float(a), float(b), float(c)], reverse=True)
            pintegrator = "Ellipsoid"
            pshape = {"a": float(a), "b": float(b), "c": float(c)}  # define long axis along x direction for consistent orientation
            pdirector = [1, 0, 0]  # default director along x-axis

        elif shape in {"triangle"}:
            side = spec.get("side", spec.get("length", 1.0))
            side = float(side)
            h = math.sqrt(3.0) * side / 2.0
            vertices = [
                [-side / 2.0, -h / 3.0],
                [side / 2.0, -h / 3.0],
                [0.0, 2.0 * h / 3.0],
            ]
            pintegrator = "ConvexSpheropolygon"
            pshape = {"vertices": vertices, "sweep_radius": 0.0}

        elif shape in {"square"}:
            side = spec.get("side", spec.get("length", 1.0))
            side = float(side)
            half = side / 2.0
            vertices = [
                [-half, -half],
                [half, -half],
                [half, half],
                [-half, half],
            ]
            pintegrator = "ConvexSpheropolygon"
            pshape = {"vertices": vertices, "sweep_radius": 0.0}

        elif shape in {"rectangle"}:
            length = spec.get("length", spec.get("L", 2.0))
            width = spec.get("width", spec.get("W", 1.0))
            length = float(length)
            width = float(width)
            length, width = max(length, width), min(length, width)  # ensure length is the longer side
            hl = length / 2.0
            hw = width / 2.0
            vertices = [
                [-hl, -hw],
                [hl, -hw],
                [hl, hw],
                [-hl, hw],
            ]
            pintegrator = "ConvexSpheropolygon"
            pshape = {"vertices": vertices, "sweep_radius": 0.0}  # define long axis along x direction
            pdirector = [1, 0, 0]  # default director along x-axis

        elif shape in {"capsule", "rod"}:
            length = spec.get("length", spec.get("L", 2.0))
            diameter = spec.get("diameter", spec.get("D", 0.5))
            length = float(length)
            diameter = float(diameter)
            vertices = [[-length / 2.0, 0.0], [length / 2.0, 0.0]]
            pintegrator = "ConvexSpheropolygon"
            pshape = {"vertices": vertices, "sweep_radius": diameter / 2.0}  # define long axis along x direction for consistent orientation
            pdirector = [1, 0, 0]  # default director along x-axis
        else:
            raise ValueError(f"Unsupported 2D shape '{shape}'.")

        particle_entry = {
            "pType": ptype,
            "pNum": number,
            "pIntegrator": pintegrator,
            "pShape": pshape,
            "pDirector": pdirector,
        }

        particle_list.append(particle_entry)
        total_N += number

    return total_N, particle_list


def create_minimal_particle_list_3d(particle_specs):
    """

    some standard particle_specs format for 3D particles

    3d examples
    particle_specs[i] = {shape:"sphere", diameter:1.0, number:50} -> {Ptype:"sphere_0", Pnum:50, Pintegratpr: "Sphere", Pshape:{diameter:1.0}}
    particle_specs[i+1] = {shape:"sphere", diameter:2.0, number:50} -> {Ptype:"sphere_1", Pnum:50, Pintegratpr: "Sphere", Pshape:{diameter:2.0}}

    particle_specs[i] = {shape:"ellipsoid", a:1.0, b:0.5, c:0.5, number:50} -> {Ptype:"ellipsoid_0", Pnum:50, Pintegratpr: "Ellipsoid", Pshape:{a:1.0, b:0.5, c:0.5}}

    particle_specs[i] = {shape:"capsule", length:L, diameter:D, number:50} -> {Ptype:"capsule_0", Pnum:50, Pintegratpr: "ConvexSpheropolyhedron", Pshape:{vertices:[[0,0,0],[L,0,0]], sweep_radius:D/2}}

    particle_specs[i] = {shape:"tetrahedron", side:l, number:50} -> {Ptype:"tetrahedron_0", Pnum:50, Pintegratpr: "ConvexPolyhedron", Pshape:{vertices:[[...],[...],[...],[...]], sweep_radius:0}}

    particle_specs[i] = {shape:"cube", side:l, number:50} -> {Ptype:"cube_0", Pnum:50, Pintegratpr: "ConvexPolyhedron", Pshape:{vertices:[[...],[...],...,[...]], sweep_radius:0}}

    particle_specs[i] = {shape:"octahedron", side:l, number:50} -> {Ptype:"octahedron_0", Pnum:50, Pintegratpr: "ConvexPolyhedron", Pshape:{vertices:[[...],[...],...,[...]], sweep_radius:0}}

    """

    if not isinstance(particle_specs, list) or len(particle_specs) == 0:
        raise ValueError("particle_specs must be a non-empty list of dictionaries.")

    particle_list = []
    total_N = 0
    name_counts = {}

    def _next_name(base):
        count = name_counts.get(base, 0)
        name_counts[base] = count + 1
        return f"{base}_{count}"

    for spec in particle_specs:
        if not isinstance(spec, dict):
            raise ValueError("Each particle spec must be a dictionary.")

        shape = spec.get("shape", spec.get("type"))
        if shape is None:
            raise ValueError("Each particle spec must include a 'shape' (or 'type') key.")
        shape = str(shape).lower()

        number = spec.get("number", spec.get("n", spec.get("count")))
        if number is None:
            raise ValueError(f"Missing 'number' for shape '{shape}'.")
        number = int(number)
        if number <= 0:
            raise ValueError(f"'number' must be positive for shape '{shape}'.")

        ptype = _next_name(shape)
        pintegrator = None
        pshape = None
        pdirector = None

        if shape in {"sphere", "ball"}:
            diameter = spec.get("diameter", spec.get("sigma"))
            if diameter is None and "radius" in spec:
                diameter = 2.0 * spec["radius"]
            if diameter is None:
                diameter = 1.0
            pintegrator = "Sphere"
            pshape = {"diameter": float(diameter)}

        elif shape in {"ellipsoid"}:
            a = float(spec.get("a", 1.0))
            b = float(spec.get("b", 0.5))
            c = float(spec.get("c", 0.5))
            # make sure a>b>c
            a, b, c = sorted([a, b, c], reverse=True)
            pintegrator = "Ellipsoid"
            pshape = {"a": a, "b": b, "c": c}
            pdirector = [1, 0, 0]  # default director along x-axis

        elif shape in {"capsule", "rod"}:
            length = float(spec.get("length", spec.get("L", 2.0)))
            diameter = float(spec.get("diameter", spec.get("D", 0.5)))
            vertices = [[-length / 2.0, 0.0, 0.0], [length / 2.0, 0.0, 0.0]]
            pintegrator = "ConvexSpheropolyhedron"
            pshape = {"vertices": vertices, "sweep_radius": diameter / 2.0}
            pdirector = [1, 0, 0]  # default director along x-axis

        elif shape in {"tetrahedron", "tetra"}:
            side = float(spec.get("side", spec.get("length", 1.0)))
            a = side
            vertices = [
                [0.0, 0.0, 0.0],
                [a, 0.0, 0.0],
                [a / 2.0, math.sqrt(3.0) * a / 2.0, 0.0],
                [a / 2.0, math.sqrt(3.0) * a / 6.0, math.sqrt(2.0 / 3.0) * a],
            ]
            centroid = [sum(v[i] for v in vertices) / 4.0 for i in range(3)]
            vertices = [[v[i] - centroid[i] for i in range(3)] for v in vertices]
            pintegrator = "ConvexSpheropolyhedron"
            pshape = {"vertices": vertices, "sweep_radius": 0.0}

        elif shape in {"cube"}:
            side = float(spec.get("side", spec.get("length", 1.0)))
            half = side / 2.0
            vertices = [
                [-half, -half, -half],
                [half, -half, -half],
                [half, half, -half],
                [-half, half, -half],
                [-half, -half, half],
                [half, -half, half],
                [half, half, half],
                [-half, half, half],
            ]
            pintegrator = "ConvexSpheropolyhedron"
            pshape = {"vertices": vertices, "sweep_radius": 0.0}

        elif shape in {"octahedron"}:
            side = float(spec.get("side", spec.get("length", 1.0)))
            r = side / math.sqrt(2.0)
            vertices = [
                [r, 0.0, 0.0],
                [-r, 0.0, 0.0],
                [0.0, r, 0.0],
                [0.0, -r, 0.0],
                [0.0, 0.0, r],
                [0.0, 0.0, -r],
            ]
            pintegrator = "ConvexSpheropolyhedron"
            pshape = {"vertices": vertices, "sweep_radius": 0.0}

        else:
            raise ValueError(f"Unsupported 3D shape '{shape}'.")

        particle_entry = {
            "pType": ptype,
            "pNum": number,
            "pIntegrator": pintegrator,
            "pShape": pshape,
            "pDirector": pdirector,
        }

        particle_list.append(particle_entry)
        total_N += number

    return total_N, particle_list


def select_optimal_integrator(dimension, particle_list):
    """
    Select the most efficient integrator that can represent all particles.

    Returns (integrator_class, integrator_name).
    """

    integrators = {p.get("pIntegrator") for p in particle_list}
    integrators.discard(None)

    if dimension == 2:
        has_ellipsoid = "Ellipsoid" in integrators
        has_spheropolygon = "ConvexSpheropolygon" in integrators

        if has_ellipsoid and has_spheropolygon:
            raise ValueError("Incompatible 2D shapes: ellipsoids cannot mix with polygon/rod shapes in a single HPMC integrator.")

        if has_spheropolygon:
            return hoomd.hpmc.integrate.ConvexSpheropolygon, "ConvexSpheropolygon"
        if has_ellipsoid:
            return hoomd.hpmc.integrate.Ellipsoid, "Ellipsoid"
        return hoomd.hpmc.integrate.Sphere, "Sphere"

    if dimension == 3:
        has_ellipsoid = "Ellipsoid" in integrators
        has_spheropolyhedron = "ConvexSpheropolyhedron" in integrators

        if has_ellipsoid and has_spheropolyhedron:
            raise ValueError("Incompatible 3D shapes: ellipsoids cannot mix with polyhedron/rod shapes in a single HPMC integrator.")

        if has_spheropolyhedron:
            return hoomd.hpmc.integrate.ConvexSpheropolyhedron, "ConvexSpheropolyhedron"
        if has_ellipsoid:
            return hoomd.hpmc.integrate.Ellipsoid, "Ellipsoid"
        return hoomd.hpmc.integrate.Sphere, "Sphere"

    raise ValueError("Dimension must be either 2 or 3.")


def resolve_hpmc_integrator_and_shapes(dimension, particle_list):
    """
    should return the best integrator

    shared shape parameters:
    default_a: max displacement trial move
    default_d: max rotation trial move
    translation_move_probability: fraction of moves that are translations vs rotations
    nselect: number of particles to select for each step
    kT: temperature set point, irrelevant for hard particle MC

    references for each supported integrator + corresponding unique shape parameters

    dimension irrelevant
    Sphere: diameter, https://hoomd-blue.readthedocs.io/en/v6.0.0/hoomd/hpmc/integrate/sphere.html#hoomd.hpmc.integrate.Sphere
    Ellipsoid: a, b, c (semi-axis lengths), https://hoomd-blue.readthedocs.io/en/v6.0.0/hoomd/hpmc/integrate/ellipsoid.html#hoomd.hpmc.integrate.Ellipsoid

    dimension = 2 (these two shape data structures)
    ConvexSphereopolygon: vertices (list of [x,y] coordinates), sweep_radius, https://hoomd-blue.readthedocs.io/en/v6.0.0/hoomd/hpmc/integrate/convexspherepolygon.html#hoomd.hpmc.integrate.ConvexSpherepolygon

    dimension = 3 ()
    ConvexSpheropolyhedron: vertices (list of [x,y,z] coordinates), sweep_radius https://hoomd-blue.readthedocs.io/en/v6.0.0/hoomd/hpmc/integrate/convexspheropolyhedron.html#hoomd.hpmc.integrate.ConvexSpheropolyhedron


    basically, this function need to translate the more "natural language" shape specifications in particle_specs to the corresponding hoomd shape classes and parameters

    compatability matrix between all integrators for 2D

    + fall back logic

    | 2D                  | Sphere               | Ellipsoid            | ConvexSpheropolygon |
    |---------------------|----------------------|----------------------|---------------------|
    | Sphere              | Sphere               | Ellipsoid            | ConvexSpheropolygon |
    | Ellipse             | Ellipsoid            | Ellipsoid            | ❌                  |
    | Polygon / Rod       | ConvexSpheropolygon  | ❌                   | ConvexSpheropolygon |


    | 3D                  | Sphere               | Ellipsoid            | ConvexSpheropolyhedron |
    |---------------------|----------------------|----------------------|------------------------|
    | Sphere              | Sphere               | Ellipsoid            | ConvexSpheropolyhedron |
    | Ellipsoid           | Ellipsoid            | Ellipsoid            | ❌                     |
    | Polyhedron / Rod    | ConvexSpheropolyhedron | ❌                   | ConvexSpheropolyhedron |

    """

    integrator_class, target = select_optimal_integrator(dimension, particle_list)
    resolved = []

    for particle in particle_list:
        pintegrator = particle.get("pIntegrator")
        pshape = particle.get("pShape")

        if pintegrator is None or pshape is None:
            raise ValueError("Each particle must include pIntegrator and pShape.")

        new_shape = dict(pshape)

        if target == pintegrator:
            pass

        elif target == "Ellipsoid":
            if pintegrator != "Sphere":
                raise ValueError("Only spheres can be promoted to Ellipsoid integrator.")
            diameter = float(pshape.get("diameter"))
            new_shape = {"a": diameter / 2.0, "b": diameter / 2.0, "c": diameter / 2.0}

        elif target == "ConvexSpheropolygon":
            if pintegrator == "Sphere":
                diameter = float(pshape.get("diameter"))
                new_shape = {"vertices": [[0.0, 0.0]], "sweep_radius": diameter / 2.0}
            elif pintegrator == "ConvexSpheropolygon":
                pass
            else:
                raise ValueError("Incompatible particle integrator for ConvexSpheropolygon target.")

        elif target == "ConvexSpheropolyhedron":
            if pintegrator == "Sphere":
                diameter = float(pshape.get("diameter"))
                new_shape = {"vertices": [[0.0, 0.0, 0.0]], "sweep_radius": diameter / 2.0}
            elif pintegrator == "ConvexSpheropolyhedron":
                pass
            else:
                raise ValueError("Incompatible particle integrator for ConvexSpheropolyhedron target.")

        elif target == "Sphere":
            if pintegrator != "Sphere":
                raise ValueError("Sphere target only supports sphere shapes.")

        else:
            raise ValueError(f"Unhandled target integrator '{target}'.")

        resolved_particle = dict(particle)
        resolved_particle["pIntegrator"] = target
        resolved_particle["pShape"] = new_shape
        resolved.append(resolved_particle)

    return integrator_class, resolved
