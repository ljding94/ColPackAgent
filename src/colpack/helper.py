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
            #return {"type": "Polygon", "vertices": vertices, "rounding_radius": shape_dict["sweep_radius"]}
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
    print("shape_metadata", shape_metadata)

    return frame


def save_state(sim, particle_list, output_path):

    shape_metadata = get_shape_meta_data(particle_list)

    snapshot = sim.state.get_snapshot()

    frame = create_gsd_frame(snapshot, shape_metadata, sim.timestep)

    with gsd.hoomd.open(name=output_path, mode="w") as gsd_file:
        gsd_file.append(frame)
    print(f"Saved system state to {output_path}")


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


# TODO: add measurement functions here


class MeasureLiquidCrystalOrder(hoomd.custom.Action):
    """Compute nematic order parameter S, smectic order parameter τ, and optimal layer spacing d."""

    def __init__(self, subfolder, system_params, label, num_d=100):
        self.filename = f"{subfolder}/{label}_LC_order.csv"
        self.meanL = system_params["meanL"]  # For d range; D=1 fixed
        self.num_d = num_d  # Resolution for d optimization
        data = np.load(f"{subfolder}/particle_data.npz")
        self.total_volume = data["total_V"]
        self._header_written = False
        self.nematicS = []
        self.smecticTau = []
        self.opt_d = []
        self.phi = []

        # other simulation info
        self.system_params = system_params  # e.g., {'pd_type': "uniform", 'N': 100, 'phi': 0.5, 'mean_ld': 2.0, 'sigma': 0.1}

    def act(self, timestep):
        snap = self._state.get_snapshot()
        if snap.communicator.rank != 0:
            return

        orientation = snap.particles.orientation
        # Transform to quaternion [x, y, z, w] for scipy
        quat_scipy = orientation[:, [1, 2, 3, 0]]
        rot = Rotation.from_quat(quat_scipy)

        # Rod directors (body-frame axis along z)
        local_axis = np.array([0.0, 0.0, 1.0])  # TODO: need to generalize for different particle types, currently assume the local director is along z axis and
        # TODO: also need to generalize to 2d
        directors = rot.apply(local_axis)

        # Nematic tensor Q
        N = directors.shape[0]
        Q = (3.0 / (2.0 * N)) * directors.T @ directors - 0.5 * np.eye(3)

        # Nematic order S (largest eigenvalue)
        S = np.linalg.eigvalsh(Q).max()

        # Global director n (largest eigenvector)
        eigvals, eigvecs = np.linalg.eigh(Q)
        n = eigvecs[:, np.argmax(eigvals)]

        # Project positions along n for smectic order
        positions = snap.particles.position
        s = positions @ n

        # Optimize d over plausible range (around mean total length ± margin)
        d_min = 0.5 * self.meanL + 1
        d_max = 1.5 * self.meanL + 1
        d_values = np.linspace(d_min, d_max, self.num_d)

        tau_max = 0.0
        d_opt = 0.0
        for d in d_values:
            phase = np.exp(1j * 2 * np.pi * s / d)
            tau = np.abs(np.mean(phase))
            if tau > tau_max:
                tau_max = tau
                d_opt = d

        # Compute current phi
        box = snap.configuration.box
        box_volume = box[0] * box[1] * box[2]
        phi = self.total_volume / box_volume

        # Append to file
        mode = "w" if not self._header_written else "a"
        with open(f"{self.filename}", mode) as f:
            if not self._header_written:
                f.write("pd_type," + f"{self.system_params['pd_type']}\n")
                f.write("N," + f"{self.system_params['N']}\n")
                f.write("phi," + f"{self.system_params['phi']}\n")
                f.write("meanL," + f"{self.system_params['meanL']}\n")
                f.write("sigmaL," + f"{self.system_params['sigmaL']}\n")
                f.write("sigmaD," + f"{self.system_params['sigmaD']}\n")
                f.write("step,S,tau,d,phi\n")
                self._header_written = True
            f.write(f"{timestep},{S},{tau_max},{d_opt},{phi}\n")

        # add to list
        self.nematicS.append(S)
        self.smecticTau.append(tau_max)
        self.opt_d.append(d_opt)
        self.phi.append(phi)

    def act_end(self):
        # append statistics, mean, std, to file
        if self.nematicS and self.smecticTau:
            mean_S = np.mean(self.nematicS)
            std_S = np.std(self.nematicS)
            mean_tau = np.mean(self.smecticTau)
            std_tau = np.std(self.smecticTau)
            mean_d = np.mean(self.opt_d)
            std_d = np.std(self.opt_d)

            with open(f"{self.filename}", "a") as f:
                f.write(f"Mean, {mean_S}, {mean_tau}, {mean_d}, {self.phi[-1]} \n")
                f.write(f"Std, {std_S}, {std_tau}, {std_d}, 0 \n")
