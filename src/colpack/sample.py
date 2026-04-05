import os
import hoomd
import json
from colpack.helper import read_state, read_state_from_run, save_state, get_shape_meta_data, CustomGSDWriter
from colpack.config_reading import get_workflow_config


def sample_system(run_dir: str):
    if not run_dir:
        raise ValueError("run_dir must be provided.")

    simulation_config_path = os.path.join(run_dir, "simulation_config_compress.json")
    if not os.path.exists(simulation_config_path):
        raise FileNotFoundError(f"simulation_config_compress.json not found in {run_dir}")

    with open(simulation_config_path, "r") as f:
        simulation_config = json.load(f)

    # some sanity checks for the simulation_config
    if not isinstance(simulation_config, dict):
        raise ValueError("simulation_config must be a dictionary.")

    particle_list = simulation_config.get("particle_list")
    if not isinstance(particle_list, list) or len(particle_list) == 0:
        raise ValueError("simulation_config must include a non-empty particle_list.")

    dimension = int(simulation_config.get("dimension", 0))
    if dimension not in (2, 3):
        raise ValueError("simulation_config.dimension must be 2 or 3.")

    total_N = int(simulation_config.get("total_particle_number", 0))
    if total_N <= 0:
        raise ValueError("simulation_config.total_particle_number must be positive.")

    ensemble = simulation_config["ensemble"]

    workflow_config = get_workflow_config()
    sample_defaults = workflow_config.get("sample_defaults", {})
    sample_steps = int(simulation_config.get("sample_steps", sample_defaults.get("sample_steps", 200000)))
    move_tune_period = int(simulation_config.get("move_tune_period", sample_defaults.get("move_tune_period", 100)))
    move_tune_target = float(simulation_config.get("move_tune_target", sample_defaults.get("move_tune_target", 0.2)))
    box_tune_target = float(simulation_config.get("box_tune_target", sample_defaults.get("box_tune_target", 0.3)))
    tune_warmup_steps = int(simulation_config.get("tune_warmup_steps", sample_defaults.get("tune_warmup_steps", 2000)))
    npt_boxmc_volume_weight = float(simulation_config.get("npt_boxmc_volume_weight", sample_defaults.get("npt_boxmc_volume_weight", 1.0)))
    npt_boxmc_volume_mode = simulation_config.get("npt_boxmc_volume_mode", sample_defaults.get("npt_boxmc_volume_mode", "standard"))
    npt_boxmc_volume_delta = float(simulation_config.get("npt_boxmc_volume_delta", sample_defaults.get("npt_boxmc_volume_delta", 0.01)))
    # if ensemble == "NVT":
    #    return sample_system_NVT(run_dir, simulation_config)
    # elif ensemble == "NPT":
    #    return sample_system_NPT(run_dir, simulation_config)
    # else:
    #    raise ValueError(f"Unsupported ensemble '{ensemble}'. Expected 'NVT' or 'NPT'.")

    is_npt = 0
    if ensemble == "NPT":
        is_npt = 1
        P = simulation_config.get("P")
        if P is None:
            raise ValueError("simulation_config for NPT ensemble must include 'betaP'.")
        P = float(P)

    # load simulation status
    compress_gsd_path = os.path.join(run_dir, "compress.gsd")
    if not os.path.exists(compress_gsd_path):
        raise FileNotFoundError(f"compress.gsd not found in {run_dir}")
    sim, mc = read_state_from_run(simulation_config, gsd_file_path=os.path.join(run_dir, compress_gsd_path))
    particle_list = simulation_config.get("particle_list")
    # add NPT box updater
    if is_npt:
        box_mc = hoomd.hpmc.update.BoxMC(trigger=hoomd.trigger.Periodic(10), P=P)
        box_mc.volume = dict(weight=npt_boxmc_volume_weight, mode=npt_boxmc_volume_mode, delta=npt_boxmc_volume_delta)
        sim.operations.updaters.append(box_mc)

    # set up tuner the trial size at the begining, before sampling

    tune_trigger = hoomd.trigger.And([hoomd.trigger.Periodic(move_tune_period), hoomd.trigger.Before(sim.timestep + tune_warmup_steps)])

    move_tune = hoomd.hpmc.tune.MoveSize.scale_solver(moves=["a", "d"], target=move_tune_target, trigger=tune_trigger)
    sim.operations.tuners.append(move_tune)

    if is_npt:
        box_tune = hoomd.hpmc.tune.BoxMCMoveSize.scale_solver(trigger=tune_trigger, boxmc=box_mc, moves=["volume"], target=box_tune_target)
        sim.operations.tuners.append(box_tune)

    # some thermalization steps for tuning
    print(f"Starting thermalization for runing... running {tune_warmup_steps} steps...")
    sim.run(tune_warmup_steps)  # run some steps for tuning

    # freeze tuner for detailed balance sampling
    sim.operations.tuners.clear()

    # add shape metadata to sim
    sim.state.type_shapes = get_shape_meta_data(particle_list)

    # sample and save trajectory
    traj_path = os.path.join(run_dir, "sample_trajectory.gsd")
    gsd_writer_action = CustomGSDWriter(particle_list=particle_list, filename=traj_path, directory=run_dir, mode="w")
    gsd_writer = hoomd.write.CustomWriter(action=gsd_writer_action, trigger=hoomd.trigger.Periodic(1000))

    sim.operations.writers.append(gsd_writer)

    sim.run(sample_steps)
    print(f"sampling completed after {sample_steps} steps.")
    print("sample overlaps:", mc.overlaps)
    print(f"sample move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")

    # remove writer after sampling
    sim.operations.writers.remove(gsd_writer)

    # save final state
    gsd_path = os.path.join(run_dir, "sample_final.gsd")
    save_state(sim, particle_list, gsd_path)

    simulation_config_sample = simulation_config.copy()
    simulation_config_sample["sample_trajectory_path"] = traj_path
    simulation_config_sample["sample_gsd_path"] = gsd_path
    simulation_config_sample["sample_translation_moves"] = mc.translate_moves
    simulation_config_sample["sample_rotation_moves"] = mc.rotate_moves
    simulation_config_sample["sample_overlaps"] = mc.overlaps
    simulation_config_sample_path = os.path.join(run_dir, "simulation_config_sample.json")
    with open(simulation_config_sample_path, "w") as f:
        json.dump(simulation_config_sample, f, indent=4)

    return simulation_config_sample


def sample_system_old(sample_steps, system_dir, density=None, seed=0):
    """
    particle_list_json, compressed_gsd files are expected in system_dir
    then perform thermalization for a given number of steps
    finally save the thermalized system to system_dir/thermalized.gsd
    """
    # load particle list and initial gsd
    if density is not None:
        compress_summar_path = os.path.join(system_dir, f"compress_summary_n{density:.3f}.json")
        compress_gsd_path = os.path.join(system_dir, f"compressed_n{density:.3f}.gsd")
    else:
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
    # sampling_folder = os.path.join(system_dir, "sampling")
    # os.makedirs(sampling_folder, exist_ok=True)
    # gsd_writer = hoomd.write.GSD(filename=gsd_writer_path, trigger=hoomd.trigger.Periodic(1000), mode="wb")
    # splitter = GSDSplitter(particle_list=compress_summary["particle_list"], directory=sampling_folder, prefix="sample_frame")
    # gsd_writer = hoomd.write.CustomWriter(action=splitter, trigger=hoomd.trigger.Periodic(1000))

    if density is not None:
        traj_path = os.path.join(system_dir, f"sample_trajectory_n{density:.3f}.gsd")
    else:
        traj_path = os.path.join(system_dir, "sample_trajectory.gsd")

    gsd_writer_action = CustomGSDWriter(particle_list=compress_summary["particle_list"], filename=traj_path, directory=system_dir, mode="w")
    gsd_writer = hoomd.write.CustomWriter(action=gsd_writer_action, trigger=hoomd.trigger.Periodic(1000))

    sim.operations.writers.append(gsd_writer)

    sim.run(sample_steps)
    print(f"sampling completed after {sample_steps} steps.")
    print("sample overlaps:", mc.overlaps)
    print(f"sample move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")

    # remove writer after sampling
    sim.operations.writers.remove(gsd_writer)

    # save final state
    if density is not None:
        gsd_path = os.path.join(system_dir, f"sample_final_n{density:.3f}.gsd")
    else:
        gsd_path = os.path.join(system_dir, "sample_final.gsd")

    save_state(sim, compress_summary["particle_list"], gsd_path)

    summary = compress_summary.copy()
    summary["sample_steps"] = sample_steps
    summary["overlaps"] = mc.overlaps

    if density is not None:
        summary_path = os.path.join(system_dir, f"sample_summary_n{density:.3f}.json")
    else:
        summary_path = os.path.join(system_dir, "sample_summary.json")

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=4)

    return summary
