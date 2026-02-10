import os
import gsd.hoomd
import hoomd
import math
import json
from colpack.helper import read_state, save_state, get_shape_meta_data, GSDSplitter


def sample_system(sample_steps, system_dir, seed=0):
    """
    particle_list_json, compressed_gsd files are expected in system_dir
    then perform thermalization for a given number of steps
    finally save the thermalized system to system_dir/thermalized.gsd
    """
    # load particle list and initial gsd
    compress_summar_path = os.path.join(system_dir, "compress_summary.json")
    compress_gsd_path = os.path.join(system_dir, "compressed.gsd")

    sim, mc, compress_summary = read_state(compress_summar_path, compress_gsd_path)

    # tune the trial size at the begining, before sampling
    tune = hoomd.hpmc.tune.MoveSize.scale_solver(
        moves=["a", "d"],
        target=0.2,
        trigger=hoomd.trigger.And([hoomd.trigger.Periodic(100), hoomd.trigger.Before(sim.timestep + 2000)]),
    )
    sim.operations.tuners.append(tune)
    sim.run(2000)  # run some steps for tuning

    # add shape metadata to sim
    sim.state.type_shapes = get_shape_meta_data(compress_summary["particle_list"])

    # save the sampling trajectories
    sampling_folder = os.path.join(system_dir, "sampling")
    os.makedirs(sampling_folder, exist_ok=True)
    # gsd_writer = hoomd.write.GSD(filename=gsd_writer_path, trigger=hoomd.trigger.Periodic(1000), mode="wb")
    splitter = GSDSplitter(particle_list=compress_summary["particle_list"], directory=sampling_folder, prefix="sample_frame")
    gsd_writer = hoomd.write.CustomWriter(action=splitter, trigger=hoomd.trigger.Periodic(1000))

    sim.operations.writers.append(gsd_writer)

    sim.run(sample_steps)
    print(f"sampling completed after {sample_steps} steps.")
    print(f"sample overlaps:", mc.overlaps)
    print(f"sample move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")

    # remove writer after sampling
    sim.operations.writers.remove(gsd_writer)

    # save final state
    gsd_path = os.path.join(system_dir, "sample_final.gsd")
    save_state(sim, compress_summary["particle_list"], gsd_path)

    summary = compress_summary.copy()
    summary["sample_steps"] = sample_steps
    summary["overlaps"] = mc.overlaps

    summary_path = os.path.join(system_dir, "sample_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    return summary
