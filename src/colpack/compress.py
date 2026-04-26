import os
import hoomd
import numpy as np
import json
from colpack.helper import save_state, read_state_from_run
from colpack.config_reading import get_workflow_config
from colpack.visualize_ovito import visualize_gsd


def compress_system(run_dir: str):
    if not run_dir:
        raise ValueError("run_dir must be provided.")

    simulation_config_path = os.path.join(run_dir, "simulation_config_initial.json")
    if not os.path.exists(simulation_config_path):
        raise FileNotFoundError(f"simulation_config_initial.json not found in {run_dir}")

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
    if ensemble == "NVT":
        simulation_config_compress = compress_system_NVT(run_dir, simulation_config)
    elif ensemble == "NPT":
        simulation_config_compress = compress_system_NPT(run_dir, simulation_config)
    else:
        raise ValueError(f"Unsupported ensemble '{ensemble}'. Expected 'NVT' or 'NPT'.")

    visualize_gsd(
        gsd_path=simulation_config_compress["compress_gsd_path"],
        output_path=os.path.join(run_dir, "compress_render.png"),
        frame_index=-1,
    )

    return simulation_config_compress


def compress_system_NVT(run_dir: str, simulation_config: dict):

    target_volume_fraction = float(simulation_config.get("volume_fraction"))
    total_particle_volume = float(simulation_config.get("total_particle_volume"))
    if target_volume_fraction is None or total_particle_volume is None:
        raise ValueError("simulation_config must include volume_fraction and total_particle_volume for NVT compression.")
    if target_volume_fraction <= 0 or total_particle_volume <= 0:
        raise ValueError("volume_fraction and total_particle_volume must be positive.")

    # In 3D this is box volume; in 2D this is box area. Keep the same variable name for consistency.
    initial_volume_fraction = simulation_config.get("initial_volume_fraction")
    target_box_volume = total_particle_volume / target_volume_fraction

    # set up hoomd system from the initial gsd and particle list
    initial_gsd_path = simulation_config.get("initial_gsd_path")
    if not os.path.exists(initial_gsd_path):
        raise FileNotFoundError(f"init.gsd not found in {run_dir}")

    sim, mc = read_state_from_run(simulation_config, initial_gsd_path)

    # compression parameters from the workflow config with fallback to hardcoded defaults
    workflow_config = get_workflow_config()
    compression_defaults = workflow_config.get("compression_defaults", {})
    max_steps_per_stage = int(simulation_config.get("compression_max_steps_per_stage", compression_defaults.get("max_steps_per_stage", 2000)))
    randomization_steps = int(simulation_config.get("compression_randomization_steps", compression_defaults.get("randomization_steps", 1000)))
    n_stage = int(simulation_config.get("compression_stages", compression_defaults.get("stages", 5)))

    if max_steps_per_stage <= 0:
        raise ValueError("compression_max_steps_per_stage must be > 0.")
    if randomization_steps <= 0:
        raise ValueError("compression_randomization_steps must be > 0.")
    if n_stage < 2:
        raise ValueError("compression_stages must be >= 2.")

    # some randomization before compression
    sim.run(randomization_steps)
    print(f"Before compression, overlaps: {mc.overlaps}")
    print(f"translation move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")
    print("translate acceptance rate:", mc.translate_moves[0] / max(sum(mc.translate_moves), 1))
    print("rotation acceptance rate:", mc.rotate_moves[0] / max(sum(mc.rotate_moves), 1))

    # compression stages setup
    x = np.linspace(0, 1.0, num=n_stage)
    n_progress = 2 * x - x**2
    phi_steps = initial_volume_fraction + (target_volume_fraction - initial_volume_fraction) * n_progress
    phi_steps[-1] = target_volume_fraction

    # compression loop
    for i, stage_target_phi in enumerate(phi_steps[1:]):
        print(f"stage {i + 1}/{n_stage - 1}, compressing to volume fraction phi={stage_target_phi}, final target {target_volume_fraction}")
        stage_target_box = hoomd.Box.from_box(sim.state.box)
        stage_target_box.volume = total_particle_volume / stage_target_phi
        compressor = hoomd.hpmc.update.QuickCompress(
            trigger=hoomd.trigger.Periodic(10),
            target_box=stage_target_box,
        )
        sim.operations.updaters.append(compressor)

        # compression loop with a max step limit to prevent infinite loops
        step_counter = 0
        while (not compressor.complete) and (step_counter < max_steps_per_stage):
            sim.run(randomization_steps)
            step_counter += randomization_steps

        print(f"current overlaps: {mc.overlaps}, timestep: {sim.timestep}")
        if not compressor.complete:
            print(f"Compression to phi={stage_target_phi} incomplete")
        else:
            print(f"Reached phi={stage_target_phi}, running equilibration...")
            sim.run(randomization_steps)

        sim.operations.updaters.remove(compressor)

    sim.run(randomization_steps)
    print(f"After compression, overlaps: {mc.overlaps}")
    print(f"translation move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")
    print("translate acceptance rate:", mc.translate_moves[0] / max(sum(mc.translate_moves), 1))
    print("rotation acceptance rate:", mc.rotate_moves[0] / max(sum(mc.rotate_moves), 1))

    achieved_box_volume = float(sim.state.box.volume)
    achieved_volume_fraction = total_particle_volume / achieved_box_volume

    # save the compresses system
    gsd_path = os.path.join(run_dir, "compress.gsd")
    save_state(sim, simulation_config.get("particle_list"), gsd_path)

    simulation_config_compress = simulation_config.copy()
    simulation_config_compress["compress_gsd_path"] = gsd_path
    simulation_config_compress["target_volume_fraction"] = target_volume_fraction
    simulation_config_compress["target_box_volume"] = target_box_volume
    simulation_config_compress["compress_volume_fraction"] = achieved_volume_fraction
    simulation_config_compress["compress_box_volume"] = achieved_box_volume

    simulation_config_compress_path = os.path.join(run_dir, "simulation_config_compress.json")
    with open(simulation_config_compress_path, "w") as f:
        json.dump(simulation_config_compress, f, indent=4)

    return simulation_config_compress


def compress_system_NPT(run_dir: str, simulation_config: dict):
    total_particle_volume_raw = simulation_config.get("total_particle_volume")
    if total_particle_volume_raw is None:
        raise ValueError("simulation_config must include total_particle_volume for NPT compression.")
    total_particle_volume = float(total_particle_volume_raw)
    if total_particle_volume <= 0:
        raise ValueError("total_particle_volume must be positive.")

    initial_volume_fraction = simulation_config.get("initial_volume_fraction")

    target_P_raw = simulation_config.get("P")
    if target_P_raw is None:
        raise ValueError("simulation_config must include target pressure 'P' for NPT compression.")
    target_P = float(target_P_raw)

    initial_gsd_path = simulation_config.get("initial_gsd_path")
    if not initial_gsd_path or not os.path.exists(initial_gsd_path):
        raise FileNotFoundError(f"init.gsd not found in {run_dir}")

    sim, mc = read_state_from_run(simulation_config, initial_gsd_path)

    # read compression parameters from the workflow config with fallback to hardcoded defaults
    workflow_config = get_workflow_config()
    compression_defaults = workflow_config.get("compression_defaults", {})
    max_steps_per_stage = int(simulation_config.get("compression_max_steps_per_stage", compression_defaults.get("max_steps_per_stage", 2000)))
    randomization_steps = int(simulation_config.get("compression_randomization_steps", compression_defaults.get("randomization_steps", 1000)))
    n_stage = int(simulation_config.get("compression_stages", compression_defaults.get("stages", 5)))
    precompress_phi = float(simulation_config.get("npt_precompress_volume_fraction", compression_defaults.get("npt_precompress_volume_fraction", 0.3)))
    boxmc_steps = int(simulation_config.get("npt_boxmc_steps", compression_defaults.get("npt_boxmc_steps", 20000)))
    boxmc_volume_delta = float(simulation_config.get("npt_boxmc_volume_delta", compression_defaults.get("npt_boxmc_volume_delta", 0.01)))
    boxmc_trigger_period = int(simulation_config.get("npt_boxmc_trigger_period", compression_defaults.get("npt_boxmc_trigger_period", 10)))

    # some error handling for the compression parameters
    if max_steps_per_stage <= 0:
        raise ValueError("compression_max_steps_per_stage must be > 0.")
    if randomization_steps <= 0:
        raise ValueError("compression_randomization_steps must be > 0.")
    if n_stage < 2:
        raise ValueError("compression_stages must be >= 2.")
    if precompress_phi <= 0:
        raise ValueError("npt_precompress_volume_fraction must be > 0.")
    if boxmc_steps <= 0:
        raise ValueError("npt_boxmc_steps must be > 0.")
    if boxmc_volume_delta <= 0:
        raise ValueError("npt_boxmc_volume_delta must be > 0.")
    if boxmc_trigger_period <= 0:
        raise ValueError("npt_boxmc_trigger_period must be > 0.")

    # Step 1: quick pre-compression to a moderate target volume fraction.
    target_precompress_phi = max(initial_volume_fraction, precompress_phi)

    sim.run(randomization_steps)
    print(f"Before NPT quickcompress, overlaps: {mc.overlaps}")

    x = np.linspace(0, 1.0, num=n_stage)
    n_progress = 2 * x - x**2
    phi_steps = initial_volume_fraction + (target_precompress_phi - initial_volume_fraction) * n_progress
    phi_steps[-1] = target_precompress_phi

    for i, stage_target_phi in enumerate(phi_steps[1:]):
        print(f"NPT stage 1 quickcompress {i + 1}/{n_stage - 1}, target phi={stage_target_phi}, precompress target {target_precompress_phi}")
        stage_target_box = hoomd.Box.from_box(sim.state.box)
        stage_target_box.volume = total_particle_volume / stage_target_phi
        compressor = hoomd.hpmc.update.QuickCompress(
            trigger=hoomd.trigger.Periodic(10),
            target_box=stage_target_box,
        )
        sim.operations.updaters.append(compressor)

        step_counter = 0
        while (not compressor.complete) and (step_counter < max_steps_per_stage):
            sim.run(randomization_steps)
            step_counter += randomization_steps

        print(f"current overlaps: {mc.overlaps}, timestep: {sim.timestep}")
        if not compressor.complete:
            print(f"Quickcompress to phi={stage_target_phi} incomplete")
        else:
            print(f"Reached phi={stage_target_phi}, running equilibration...")
            sim.run(randomization_steps)

        sim.operations.updaters.remove(compressor)

    # Step 2: pressure equilibration with BoxMC.
    boxmc = hoomd.hpmc.update.BoxMC(trigger=hoomd.trigger.Periodic(boxmc_trigger_period), P=target_P)

    if hasattr(boxmc, "volume"):
        # Isotropic volume moves. Keep mode flexible for different HOOMD versions.
        try:
            boxmc.volume = {"mode": "ln", "weight": 1.0, "delta": boxmc_volume_delta}
        except Exception:
            boxmc.volume = {"weight": 1.0, "delta": boxmc_volume_delta}

    sim.operations.updaters.append(boxmc)
    print(f"Running NPT BoxMC equilibration at target P={target_P} for {boxmc_steps} steps")
    sim.run(boxmc_steps)
    sim.operations.updaters.remove(boxmc)

    final_box_volume = float(sim.state.box.volume)
    final_volume_fraction = total_particle_volume / final_box_volume

    print(f"After NPT compression, overlaps: {mc.overlaps}")
    print(f"translation move size: {mc.translate_moves}, rotation move size: {mc.rotate_moves}")
    print("translate acceptance rate:", mc.translate_moves[0] / max(sum(mc.translate_moves), 1))
    print("rotation acceptance rate:", mc.rotate_moves[0] / max(sum(mc.rotate_moves), 1))

    gsd_path = os.path.join(run_dir, "compress.gsd")
    save_state(sim, simulation_config.get("particle_list"), gsd_path)

    simulation_config_compress = simulation_config.copy()
    simulation_config_compress["compress_gsd_path"] = gsd_path
    simulation_config_compress["final_box_volume"] = final_box_volume
    simulation_config_compress["final_volume_fraction"] = final_volume_fraction
    simulation_config_compress["npt_precompress_volume_fraction"] = target_precompress_phi
    simulation_config_compress["target_pressure"] = target_P

    simulation_config_compress_path = os.path.join(run_dir, "simulation_config_compress.json")
    with open(simulation_config_compress_path, "w") as f:
        json.dump(simulation_config_compress, f, indent=4)

    return simulation_config_compress
