import json
import gsd.hoomd
import hoomd
import numpy as np
from scipy.spatial.transform import Rotation
import os


def mapping_shape_dict_to_gsd(shape_dict):
    if shape_dict["type"] == "Sphere":
        return {"type": "Sphere", "diameter": shape_dict["diameter"]}
    elif shape_dict["type"] == "Ellipsoid":
        return {"type": "Ellipsoid", "a": shape_dict["a"], "b": shape_dict["b"], "c": shape_dict["c"]}
    elif shape_dict["type"] == "ConvexSpheropolygon":
        # make sure there are 4 vertices for gsd, if less than 4, pad with zeros
        vertices = shape_dict["vertices"]
        print("convex spheropolygon vertices:", vertices)
        radius = shape_dict["sweep_radius"]
        if len(vertices) == 1:
            # it's actually disk
            return {"type": "Sphere", "diameter": 2 * radius}
        if len(vertices) == 2:
            # it's actually capsule, we can represent it as a rectangle with rounding radius in gsd
            vertices = vertices + [[0.00, 0.001], [0.00, -0.001]]
            # return {"type": "Polygon", "vertices": vertices, "rounding_radius": shape_dict["sweep_radius"]}
        return {"type": "Polygon", "vertices": vertices, "rounding_radius": shape_dict["sweep_radius"]}

    elif shape_dict["type"] == "ConvexSpheropolyhedron":
        # make sure there are 4 vertices for gsd, if less than 4, pad with zeros
        vertices = shape_dict["vertices"]
        radius = shape_dict["sweep_radius"]
        if len(vertices) == 1:
            # it's actually sphere
            return {"type": "Sphere", "diameter": 2 * radius}

        # FIX: Handle the Capsule (2 vertices) by "inflating" it into a 3D sliver
        if len(vertices) == 2:
            import numpy as np

            v0 = np.array(vertices[0])
            v1 = np.array(vertices[1])

            # Create a tiny offset perpendicular-ish to the bond
            # We add 3 small offsets to ensure 3D volume regardless of orientation
            epsilon = 1e-4 * radius if radius > 0 else 1e-5

            # Add two fake vertices slightly offset from the first vertex
            # This turns the "Line" into a "Tetrahedron" (Needle shape)
            v2 = v0 + [epsilon, epsilon, epsilon]
            v3 = v1 + [epsilon, -epsilon, 0]

            vertices = [v0.tolist(), v1.tolist(), v2.tolist(), v3.tolist()]

        return {"type": "ConvexPolyhedron", "vertices": vertices, "rounding_radius": shape_dict["sweep_radius"]}
    else:
        raise ValueError(f"Unsupported shape type: {shape_dict['type']}")


def get_shape_meta_data(particle_list):
    shape_metadata = []
    for particle in particle_list:
        shape_dict = dict(particle["pShape"])
        shape_dict["type"] = particle["pIntegrator"]
        shape_dict_gsd = mapping_shape_dict_to_gsd(shape_dict)
        shape_metadata.append(shape_dict_gsd)
    return shape_metadata


def create_gsd_frame(hoomd_snapshot, shape_metadata, timestep=0):
    """
    Creates a gsd.hoomd.Frame from a HOOMD snapshot and shape data.
    Reusable by both the Custom Action and save_state.
    """
    frame = gsd.hoomd.Frame()

    # Copy data from the snapshot
    frame.configuration.step = timestep
    frame.configuration.box = hoomd_snapshot.configuration.box
    frame.particles.N = hoomd_snapshot.particles.N
    frame.particles.position = hoomd_snapshot.particles.position
    frame.particles.orientation = hoomd_snapshot.particles.orientation
    frame.particles.types = hoomd_snapshot.particles.types
    frame.particles.typeid = hoomd_snapshot.particles.typeid

    # Inject your calculated shapes
    frame.particles.type_shapes = shape_metadata
    #print("shape_metadata", shape_metadata)

    return frame


def save_state(sim, particle_list, output_path):

    shape_metadata = get_shape_meta_data(particle_list)

    snapshot = sim.state.get_snapshot()

    frame = create_gsd_frame(snapshot, shape_metadata, sim.timestep)

    with gsd.hoomd.open(name=output_path, mode="w") as gsd_file:
        gsd_file.append(frame)
    print(f"Saved system state to {output_path}")


class CustomGSDWriter(hoomd.custom.Action):
    def __init__(self, particle_list, filename="trajectory.gsd", directory=".", mode="w"):
        super().__init__()
        self.directory = directory
        self.filename = filename
        self.path = os.path.join(directory, filename)
        self.shape_metadata = get_shape_meta_data(particle_list)

        # Store user preference ('w' = overwrite start, 'a' = append always)
        self.user_mode = mode

        # Track if this is the very first time act() is called
        self._is_first_call = True

    def act(self, timestep):
        # 1. Get snapshot
        snap = self._state.get_snapshot()

        if snap.communicator.rank == 0:
            # 2. Create the GSD frame (using your helper)
            gsd_frame = create_gsd_frame(snap, self.shape_metadata, timestep)

            # 3. Determine the file mode dynamically
            #    Default is 'r+' (read/write) which allows appending
            file_mode = "r+"

            if self._is_first_call:
                # If user wants to overwrite ('w'), use 'w' mode ONCE to clear file
                if self.user_mode == "w":
                    file_mode = "w"
                # If user wants append ('a') but file doesn't exist, must use 'w' to create it
                elif not os.path.exists(self.path):
                    file_mode = "w"

                self._is_first_call = False

            # Safety check: if file was deleted mid-run, recreate it
            elif not os.path.exists(self.path):
                file_mode = "w"

            # 4. Open, Append, Close
            with gsd.hoomd.open(name=self.path, mode=file_mode) as f:
                f.append(gsd_frame)
                # print(f"Appended frame {timestep} to {self.path}")


class GSDSplitter(hoomd.custom.Action):
    def __init__(self, particle_list, directory=".", prefix="trajectory"):
        super().__init__()
        self.directory = directory
        self.prefix = prefix
        # This assumes particle_list order matches simulation types!
        self.shape_metadata = get_shape_meta_data(particle_list)

    def act(self, timestep):
        # 1. Get the snapshot from the internal state
        snap = self._state.get_snapshot()

        if snap.communicator.rank == 0:
            # REUSE 2: Create the frame using the shared helper
            gsd_frame = create_gsd_frame(snap, self.shape_metadata, timestep)

            # 3. Save to a unique file
            filename = f"{self.prefix}_{timestep}.gsd"
            path = os.path.join(self.directory, filename)

            with gsd.hoomd.open(name=path, mode="w") as f:
                f.append(gsd_frame)
                print(f"Saved split frame: {path}")


def read_state(summary_file_path, gsd_file_path):
    # may put some helper function hereinit_gsd_path = os.path.join(system_dir, "init.gsd")
    with open(summary_file_path, "r") as f:
        summary = json.load(f)
        # particle_specs, particle_list, total_particles, number_density, box_length, overlaps
    particle_list = summary["particle_list"]
    number_density = summary["number_density"]
    box_length = summary["box_length"]
    total_N = summary["total_particles"]

    print("[read] system number density:", number_density, "total particles:", total_N, "box length:", box_length)

    # step 2: set up hoomd system
    device = hoomd.device.GPU() if hoomd.device.GPU.is_available() else hoomd.device.CPU()
    sim = hoomd.Simulation(device=device)
    sim.create_state_from_gsd(filename=gsd_file_path)

    # step 3: step up the integrator and mc
    integrator = particle_list[0]["pIntegrator"]
    if integrator == "Sphere":
        mc = hoomd.hpmc.integrate.Sphere()
    elif integrator == "Ellipsoid":
        mc = hoomd.hpmc.integrate.Ellipsoid()
    elif integrator == "ConvexSpheropolygon":
        mc = hoomd.hpmc.integrate.ConvexSpheropolygon()
    elif integrator == "ConvexSpheropolyhedron":
        mc = hoomd.hpmc.integrate.ConvexSpheropolyhedron()
    else:
        raise ValueError(f"Unsupported integrator type: {integrator}")

    print("Using integrator:", integrator)
    for particle in particle_list:
        print("particle type:", particle["pType"], "shape:", particle["pShape"])
        mc.shape[particle["pType"]] = particle["pShape"]

    sim.operations.integrator = mc

    return sim, mc, summary