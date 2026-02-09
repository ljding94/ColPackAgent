import os
import gsd.hoomd
import hoomd
import numpy as np
import math
import json
from colpack.init import save_system_state_to_gsd


def compress_system(target_number_density, system_dir, seed=0):
    """
    particle_list_json, init_gsd files are expected in system_dir
    will read the particle list from json file for the particle_list information
    and read the init_gsd for the position and orientation information
    then perform compression to reach a target number density
    finally save the compressed system to system_dir/compressed.gsd
    """

    # step 1: load particle list and initial gsd
    init_gsd_path = os.path.join(system_dir, "init.gsd")
    init_summary_path = os.path.join(system_dir, "init_summary.json")
    with open(init_summary_path, "r") as f:
        init_summary = json.load(f)
        # particle_specs, particle_list, total_particles, number_density, box_length, overlaps
    particle_list = init_summary["particle_list"]
    init_number_density = init_summary["number_density"]
    init_box_length = init_summary["box_length"]
    total_N = init_summary["total_particles"]

    print("system initial number density:", init_number_density, "target number density:", target_number_density, "total particles:", total_N, "initial box length:", init_box_length)

    # step 2: set up hoomd system
    device = hoomd.device.GPU() if hoomd.device.GPU.is_available() else hoomd.device.CPU()
    sim = hoomd.Simulation(device=device, seed=seed)
    sim.create_state_from_gsd(filename=init_gsd_path)

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

    # step 4 run the compression
    pre_compress_snapshot = sim.state.get_snapshot()

    # define some parameters for compression
    max_steps_per_stage = 2000
    randomization_steps = 1000

    # 1. some randomization before compression
    sim.run(randomization_steps)
    print(f"Before compression, overlaps: {mc.overlaps}")
    print(f"translation move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")
    print("translate acceptance rate:", mc.translate_moves[0] / sum(mc.translate_moves))
    print("rotation acceptance rate:", mc.rotate_moves[0] / max(sum(mc.rotate_moves), 1))  # sphere has no rotation move, so the acceptance rate can be NaN, we can add a max to prevent that

    # 2. compression loop
    n_stage = 5
    x = np.linspace(0, 1.0, num=n_stage)  # example compression schedule
    n_progress = 2 * x - x**2  # Quadratic progression: faster increase early, slower later
    n_steps = init_number_density + (target_number_density - init_number_density) * n_progress
    n_steps[-1] = target_number_density  # ensure exact final target
    for i, target_n in enumerate(n_steps[1:]):
        print(f"state {i}/{n_stage}, compressing to n={target_n}, with final target {n_steps[-1]}")
        target_box_vol = total_N / target_n
        final_box = hoomd.Box.from_box(sim.state.box)
        final_box.volume = target_box_vol
        compresser = hoomd.hpmc.update.QuickCompress(
            trigger=hoomd.trigger.Periodic(10),
            target_box=final_box,
        )
        sim.operations.updaters.append(compresser)

        # compression loop with a max step limit to prevent infinite loops
        step_counter = 0
        while (not compresser.complete) and (step_counter < max_steps_per_stage):
            sim.run(randomization_steps)
            step_counter += randomization_steps

        print(f"current overlaps: {mc.overlaps}, timestep: {sim.timestep}")
        if not compresser.complete:
            print(f"Compression to n={target_n} incomplete")
        else:
            print(f"Reached n={target_n}, running equilibration...")
            sim.run(randomization_steps)  # Equilibrate at this density
        sim.operations.updaters.remove(compresser)
        gsd_path = os.path.join(system_dir, f"compressed_{i}.gsd")
        save_system_state_to_gsd(sim, particle_list, gsd_path)

    # some post compression randomization
    sim.run(randomization_steps)
    print(f"After compression, overlaps: {mc.overlaps}")
    print(f"translation move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")
    print("translate acceptance rate:", mc.translate_moves[0] / sum(mc.translate_moves))
    print("rotation acceptance rate:", mc.rotate_moves[0] / max(sum(mc.rotate_moves), 1))  # sphere has no rotation move, so the acceptance rate can be NaN, we can add a max to prevent that

    # step 5: save the compressed system
    gsd_path = os.path.join(system_dir, "compressed.gsd")
    save_system_state_to_gsd(sim, particle_list, gsd_path)

    summary = {"particle_list": particle_list, "total_particles": total_N, "number_density": target_number_density, "box_length": sim.state.box.Lx, "overlaps": mc.overlaps}

    summary_path = os.path.join(system_dir, "compress_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    return summary


# TODO: need to test the compress script
