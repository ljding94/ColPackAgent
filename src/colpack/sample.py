import os
import json
from colpack.helper import read_state_from_run, save_state, get_shape_meta_data, CustomGSDWriter
from colpack.config_reading import get_workflow_config
from colpack.visualize_ovito import visualize_gsd


MAX_SAMPLE_TRAJECTORY_TRIGGER_PERIOD = 100
TARGET_SAMPLE_TRAJECTORY_FRAMES = 50


def _resolve_sample_steps(simulation_config: dict, sample_defaults: dict) -> int:
    """Resolve sampling steps with backward compatibility.

    Preferred key is ``sample_steps``. Legacy workflows still set
    ``sampling_steps``; honor that when ``sample_steps`` is absent.
    """
    if "sample_steps" in simulation_config and simulation_config.get("sample_steps") is not None:
        return int(simulation_config["sample_steps"])
    if "sampling_steps" in simulation_config and simulation_config.get("sampling_steps") is not None:
        return int(simulation_config["sampling_steps"])
    return int(sample_defaults.get("sample_steps", 50000))


def _get_sample_trajectory_trigger_period(sample_steps: int) -> int:
    if sample_steps <= 0:
        raise ValueError("sample_steps must be positive.")

    if sample_steps < TARGET_SAMPLE_TRAJECTORY_FRAMES:
        return 1

    return min(
        MAX_SAMPLE_TRAJECTORY_TRIGGER_PERIOD,
        max(1, (sample_steps + TARGET_SAMPLE_TRAJECTORY_FRAMES - 1) // TARGET_SAMPLE_TRAJECTORY_FRAMES),
    )


def _get_move_tune_period(sample_steps: int, configured_period: int, min_move_tune_updates: int) -> int:
    if sample_steps <= 0:
        raise ValueError("sample_steps must be positive.")
    if configured_period <= 0:
        raise ValueError("configured_period must be positive.")
    if min_move_tune_updates <= 0:
        raise ValueError("min_move_tune_updates must be positive.")

    adaptive_period = max(1, (sample_steps + min_move_tune_updates - 1) // min_move_tune_updates)
    return min(configured_period, adaptive_period)


def _get_npt_boxmc_trigger_period(sample_steps: int, configured_period: int, min_npt_boxmc_updates: int) -> int:
    if sample_steps <= 0:
        raise ValueError("sample_steps must be positive.")
    if configured_period <= 0:
        raise ValueError("configured_period must be positive.")
    if min_npt_boxmc_updates <= 0:
        raise ValueError("min_npt_boxmc_updates must be positive.")

    adaptive_period = max(1, (sample_steps + min_npt_boxmc_updates - 1) // min_npt_boxmc_updates)
    return min(configured_period, adaptive_period)


def sample_system(run_dir: str):
    import hoomd

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
    sample_steps = _resolve_sample_steps(simulation_config, sample_defaults)
    configured_move_tune_period = int(simulation_config.get("move_tune_period", sample_defaults.get("move_tune_period", 100)))
    min_move_tune_updates = int(simulation_config.get("min_move_tune_updates", sample_defaults.get("min_move_tune_updates", 10)))
    move_tune_period = _get_move_tune_period(sample_steps, configured_move_tune_period, min_move_tune_updates)
    move_tune_target = float(simulation_config.get("move_tune_target", sample_defaults.get("move_tune_target", 0.2)))
    box_tune_target = float(simulation_config.get("box_tune_target", sample_defaults.get("box_tune_target", 0.3)))
    tune_warmup_steps = int(simulation_config.get("tune_warmup_steps", sample_defaults.get("tune_warmup_steps", 2000)))
    configured_npt_boxmc_trigger_period = int(
        simulation_config.get("npt_boxmc_trigger_period", sample_defaults.get("npt_boxmc_trigger_period", 10))
    )
    min_npt_boxmc_updates = int(
        simulation_config.get("min_npt_boxmc_updates", sample_defaults.get("min_npt_boxmc_updates", 10))
    )
    npt_boxmc_trigger_period = _get_npt_boxmc_trigger_period(
        sample_steps,
        configured_npt_boxmc_trigger_period,
        min_npt_boxmc_updates,
    )
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
    sim, mc = read_state_from_run(simulation_config, gsd_file_path=compress_gsd_path)
    particle_list = simulation_config.get("particle_list")
    # add NPT box updater
    if is_npt:
        box_mc = hoomd.hpmc.update.BoxMC(trigger=hoomd.trigger.Periodic(npt_boxmc_trigger_period), P=P)
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
    trajectory_trigger_period = _get_sample_trajectory_trigger_period(sample_steps)
    gsd_writer_action = CustomGSDWriter(particle_list=particle_list, filename=traj_path, directory=run_dir, mode="w")
    gsd_writer = hoomd.write.CustomWriter(
        action=gsd_writer_action,
        trigger=hoomd.trigger.Periodic(trajectory_trigger_period),
    )

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
    simulation_config_sample["sample_steps"] = sample_steps
    simulation_config_sample["sample_trajectory_trigger_period"] = trajectory_trigger_period
    simulation_config_sample["sample_move_tune_period"] = move_tune_period
    simulation_config_sample["min_move_tune_updates"] = min_move_tune_updates
    if is_npt:
        simulation_config_sample["sample_npt_boxmc_trigger_period"] = npt_boxmc_trigger_period
        simulation_config_sample["min_npt_boxmc_updates"] = min_npt_boxmc_updates
        simulation_config_sample["sample_box_moves"] = getattr(box_mc, "volume_moves", None)
    simulation_config_sample_path = os.path.join(run_dir, "simulation_config_sample.json")
    with open(simulation_config_sample_path, "w") as f:
        json.dump(simulation_config_sample, f, indent=4)

    visualize_gsd(gsd_path=gsd_path, output_path=os.path.join(run_dir, "sample_final_render.png"), frame_index=-1)

    return simulation_config_sample
