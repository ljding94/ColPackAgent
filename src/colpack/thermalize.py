import os
import gsd.hoomd
import hoomd
import numpy as np
import math
import json
from colpack.init import save_system_state_to_gsd


def thermalize_system(thermalization_steps, system_dir, seed=0):
    """
    particle_list_json, compressed_gsd files are expected in system_dir
    then perform thermalization for a given number of steps
    finally save the thermalized system to system_dir/thermalized.gsd
    """
    # step 1: load particle list and initial gsd
    gsd_path = os.path.join(system_dir, "compressed.gsd")
    summary_path = os.path.join(system_dir, "compress_summary.json")
    with open(summary_path, "r") as f:
        compress_summary = json.load(f)
        # particle_specs, particle_list, total_particles, number_density, box_length, overlaps
    particle_list = compress_summary["particle_list"]
    number_density = compress_summary["number_density"]
    box_length = compress_summary["box_length"]
    total_N = compress_summary["total_particles"]

    print("system number density:", number_density, "total particles:", total_N, "box length:", box_length)

    # step 2: set up hoomd system
    device = hoomd.device.GPU() if hoomd.device.GPU.is_available() else hoomd.device.CPU()
    sim = hoomd.Simulation(device=device, seed=seed)
    sim.create_state_from_gsd(filename=gsd_path)

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

    # TODO: need to add observables measurement to monitor the thermalization process
    sim.run(thermalization_steps)
    print(f"Thermalization completed after {thermalization_steps} steps.")
    print(f"thermalization overlaps:", mc.overlaps)
    print(f"thermalization move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")

    # step 5: save the compressed system
    gsd_path = os.path.join(system_dir, "thermalized.gsd")
    save_system_state_to_gsd(sim, particle_list, gsd_path)

    summary = {"particle_list": particle_list, "total_particles": total_N, "number_density": number_density, "box_length": sim.state.box.Lx, "overlaps": mc.overlaps}

    summary_path = os.path.join(system_dir, "thermalize_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    return summary
