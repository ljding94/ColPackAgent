import os
import gsd.hoomd
import hoomd
import numpy as np
import math
import json
from colpack.helper import save_state


def create_initial_config(dimension, particle_specs, initial_number_density, output_dir, seed=0):
    dim = dimension
    """
    particle_specs is a list of dict, each dict contains keys: "type", "number", "parameters",
    parameters is more "natual language", which is be translated to hoomd shape parameters in generate_particle_list function
    for example:
    type: "sphere", number: 1000, parameters: diameter:1.0 # https://hoomd-blue.readthedocs.io/en/v6.0.0/hoomd/hpmc/integrate/sphere.html#hoomd.hpmc.integrate.Sphere
    """

    # get particle list
    total_N, particle_list = create_minimal_particle_list(dim, particle_specs)

    # set up HPMC integrator
    integrator, resolved_particle_list = resolve_hpmc_integrator_and_shapes(dimension=dim, particle_list=particle_list)
    particle_list = resolved_particle_list  # update particle list accordingly
    mc = integrator(default_d=1.0, default_a=0.1)

    if integrator is None:
        raise ValueError("No compatible HPMC integrator found for the given particle specifications.")

    # insert particles
    for particle in particle_list:
        mc.shape[particle["pType"]] = particle["pShape"]

    # Initial and target box
    initial_n = initial_number_density
    initial_box_A = total_N / initial_n
    initial_box_L = initial_box_A ** (1 / dim)

    # Initialize HOOMD
    device = hoomd.device.GPU() if hoomd.device.GPU.is_available() else hoomd.device.CPU()
    sim = hoomd.Simulation(device=device, seed=seed)

    # Create snapshot
    snapshot = hoomd.Snapshot()
    snapshot.particles.N = total_N
    snapshot.particles.types = [particle["pType"] for particle in particle_list]
    snapshot.particles.typeid[:] = np.concatenate([np.full(particle["pNum"], i, dtype=np.int32) for i, particle in enumerate(particle_list)])  # create a map from id to type

    if dim == 2:
        snapshot.configuration.box = [initial_box_L, initial_box_L, 0, 0, 0, 0]

    elif dim == 3:
        snapshot.configuration.box = [initial_box_L, initial_box_L, initial_box_L, 0, 0, 0]

    # initialize positions on a simple cubic for dim=3, square for dim 2 lattice
    grid_size = math.ceil(total_N ** (1 / dim))
    spacing = initial_box_L / grid_size
    positions = []
    for i in range(total_N):
        x = (i % grid_size) * spacing - initial_box_L / 2
        y = ((i // grid_size) % grid_size) * spacing - initial_box_L / 2
        z = (i // (grid_size**2)) * spacing - initial_box_L / 2 if dim == 3 else 0
        positions.append([x, y, z])

    # Shuffle positions
    rng = np.random.default_rng(seed)
    rng.shuffle(positions)
    snapshot.particles.position[:] = positions

    snapshot.particles.orientation[:] = [[1, 0, 0, 0]] * total_N  # default orientation (no rotation), can be randomized if needed
    # Initialize orientations randomly
    """
    if dim == 2:
        # Random rotation around Z axis
        thetas = rng.uniform(0, 2 * np.pi, total_N)
        orientations = np.zeros((total_N, 4))
        orientations[:, 0] = np.cos(thetas / 2)  # w
        orientations[:, 3] = np.sin(thetas / 2)  # z
        snapshot.particles.orientation[:] = orientations
    elif dim == 3:
        # Uniform random rotations in 3D
        # Generate 4D standard normal samples
        u = rng.standard_normal((total_N, 4))
        # Normalize
        norms = np.linalg.norm(u, axis=1, keepdims=True)
        snapshot.particles.orientation[:] = u / norms
        u = rng.standard_normal((total_N, 4))
        # Normalize
        norms = np.linalg.norm(u, axis=1, keepdims=True)
        snapshot.particles.orientation[:] = u / norms
    """

    sim.create_state_from_snapshot(snapshot)

    sim.operations.integrator = mc

    # run 0 step to initialize
    sim.run(0)
    print(f"Initial configuration created with {total_N} particles in a box of size {initial_box_L:.3f}. \n with overlap {mc.overlaps}")
    print()
    print("Particle list:")
    for particle in particle_list:
        print(f"  Type: {particle['pType']}, Number: {particle['pNum']}, Integrator: {particle['pIntegrator']}, Shape: {particle['pShape']}")

    # some randomization
    # sim.run(1000)
    # print(f"After randomization, overlaps: {mc.overlaps}")

    # save the state to gsd
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Save the resolved definition of particles to a json file
    particle_list_path = os.path.join(output_dir, "particle_list.json")
    with open(particle_list_path, "w") as f:
        json.dump(resolved_particle_list, f, indent=4)

    gsd_path = os.path.join(output_dir, "init.gsd")
    save_state(sim, resolved_particle_list, gsd_path)

    # create initialization summary
    summary = {"particle_specs": particle_specs, "particle_list": particle_list, "total_particles": total_N, "number_density": initial_n, "box_length": initial_box_L, "overlaps": mc.overlaps}

    summary_path = os.path.join(output_dir, "init_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    return summary


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

    particle_specs[i] = {shape:"polygon", vertices:[[0,1],[0.951,0.309],[0.588,-0.809],[-0.588,-0.809],[-0.951,0.309]], sweep_radius:0.1, number:50} -> {Ptype:"polygon_0", Pnum:50, Pintegratpr: "ConvexSphereopolygon", Pshape:{vertices:[[0,1],[0.951,0.309],[0.588,-0.809],[-0.588,-0.809],[-0.951,0.309]], sweep_radius:0.1}}

    default shape values:
    disk: diameter=1.0
    ellipse: a=1.0, b=0.5
    triangle: side=1.0
    square: side=1.0
    rectangle: length=2.0, width=1.0
    capsule: length=2.0, diameter=0.5
    polygon: vertices=[[0,1],[0.951,0.309],[0.588,-0.809],[-0.588,-0.809],[-0.951,0.309]], sweep_radius=0.0
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

        elif shape in {"polygon"}:
            default_vertices = [
                [0.0, 1.0],
                [0.951, 0.309],
                [0.588, -0.809],
                [-0.588, -0.809],
                [-0.951, 0.309],
            ]
            vertices = spec.get("vertices", default_vertices)
            sweep_radius = float(spec.get("sweep_radius", 0.0))
            pintegrator = "ConvexSpheropolygon"
            pshape = {"vertices": vertices, "sweep_radius": sweep_radius}

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
