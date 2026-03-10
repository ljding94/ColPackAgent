import os
import hoomd
import numpy as np
import json
from colpack.helper import save_state, read_state


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
    sim, mc, init_summary = read_state(init_summary_path, init_gsd_path)
    init_number_density = init_summary["number_density"]
    total_N = init_summary["total_particles"]
    particle_list = init_summary["particle_list"]

    # step 4 run the compression
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

    # some post compression randomization
    sim.run(randomization_steps)
    print(f"After compression, overlaps: {mc.overlaps}")
    print(f"translation move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")
    print("translate acceptance rate:", mc.translate_moves[0] / sum(mc.translate_moves))
    print("rotation acceptance rate:", mc.rotate_moves[0] / max(sum(mc.rotate_moves), 1))  # sphere has no rotation move, so the acceptance rate can be NaN, we can add a max to prevent that

    # step 5: save the compressed system
    gsd_path = os.path.join(system_dir, f"compressed_n{target_number_density:.3f}.gsd")
    save_state(sim, particle_list, gsd_path)

    summary = {"particle_list": particle_list, "total_particles": total_N, "number_density": target_number_density, "box_length": sim.state.box.Lx, "overlaps": mc.overlaps}

    summary_path = os.path.join(system_dir, f"compress_summary_n{target_number_density:.3f}.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    return summary
