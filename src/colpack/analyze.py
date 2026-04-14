import os
import json
import numpy as np
import freud
import rowan
import gsd.hoomd
from colpack.analyze_plot import analyze_plot
from colpack.config_reading import get_analyze_config as _load_analyze_config


def _normalize_run_dir(run_dir):
    if not run_dir:
        raise ValueError("run_dir must be provided.")
    return os.path.abspath(os.path.expanduser(run_dir))


def _resolve_dimension(simulation_config):
    dimension = simulation_config.get("dimension")
    if dimension is None:
        dimension = simulation_config.get("dimensions")
    if dimension is None:
        return None
    return int(dimension)


def analyze_main(run_dir):
    """
    Main function to analyze the compressed system.
    It will read the compress_summary.json and sample_trajectory.gsd from the system_dir,
    then perform analysis based on the particle types and shapes, and save the results to analysis_results.json
    """
    run_dir = _normalize_run_dir(run_dir)

    # 0 some error handling and check the required files
    simulation_config_path = os.path.join(run_dir, "simulation_config_sample.json")
    if not os.path.exists(simulation_config_path):
        raise FileNotFoundError(f"Missing simulation_config_sample.json in {run_dir}. Cannot perform analysis.")

    with open(simulation_config_path, "r") as f:
        simulation_config = json.load(f)

    # 1. compute and save the analysis results
    analyze_compute(run_dir, simulation_config)

    # 2.0 find the post analysis simulation config path
    simulation_config_path = os.path.join(run_dir, "simulation_config_analysis.json")
    if not os.path.exists(simulation_config_path):
        raise FileNotFoundError(f"Missing simulation_config_analysis.json in {run_dir}. Cannot perform plotting.")

    with open(simulation_config_path, "r") as f:
        simulation_config = json.load(f)
    # 2. plot the analysis results and save the figures
    plot_summary = analyze_plot(run_dir, simulation_config)

    # 3. validate plotting outputs so workflow status does not silently pass on partial analysis.
    generated_files = plot_summary.get("generated_files", []) if isinstance(plot_summary, dict) else []
    if not generated_files:
        raise RuntimeError(f"No analysis plots were generated for {run_dir}.")

    missing_files = [path for path in generated_files if not os.path.exists(path)]
    if missing_files:
        raise FileNotFoundError(f"Expected analysis plot files were not created: {missing_files}")

    return {
        "generated_plot_files": generated_files,
        "n_generated_plot_files": len(generated_files),
    }


def analyze_compute(run_dir, simulation_config):
    run_dir = _normalize_run_dir(run_dir)
    particle_list = simulation_config.get("particle_list")
    if not particle_list:
        raise ValueError(f"No particle_list found in simulation_config_sample.json in {run_dir}. Cannot perform analysis.")

    print(f"--- Starting Analysis for {run_dir} --- ")

    trajectory_gsd_path = os.path.join(run_dir, "sample_trajectory.gsd")
    if not os.path.exists(trajectory_gsd_path):
        raise FileNotFoundError(f"Missing sample_trajectory.gsd in {run_dir}. Cannot perform analysis.")

    traj = gsd.hoomd.open(trajectory_gsd_path)

    # 1. load analysis config
    dimension = _resolve_dimension(simulation_config)
    analysis_config = get_analyze_config(dimension)

    results = {}

    # 2 analysis loop: type-specific and global
    # 2.1 type specific analysis loop
    for p_info in particle_list:
        pType = p_info["pType"]
        pTypeShape = pType.split("_")[0]  # e.g. "disk" from "disk_1"
        if pTypeShape in analysis_config:
            instructions = analysis_config[pTypeShape]
            # Execute all configured order parameters
            type_results = _compute_shape_orders(traj, p_info, instructions["order_params"])
            results[f"{pType}"] = type_results
        else:
            print(f"Warning: No analysis config found for shape {pType}")

    # 2.2. rdf analysis loop
    if len(particle_list) > 1:
        # Simple loop for pairs
        for i in range(len(particle_list)):
            for j in range(i, len(particle_list)):
                t1 = particle_list[i]["pType"]
                t2 = particle_list[j]["pType"]
                key = f"rdf_{t1}_{t2}"
                results[key] = _compute_rdf(traj, query_type=t1, target_type=t2)

    # save results to json
    result_path = os.path.abspath(os.path.join(run_dir, "analysis_results.json"))
    with open(result_path, "w") as f:
        json.dump(_make_serializable(results), f, indent=4)

    simulation_config_analysis = simulation_config.copy()
    simulation_config_analysis["analysis_results_path"] = result_path

    with open(os.path.join(run_dir, "simulation_config_analysis.json"), "w") as f:
        json.dump(simulation_config_analysis, f, indent=4)

    return results


def get_analyze_config(dimension=None):
    """
    Builds analysis config from colpack_config.json, instantiating freud objects.
    """
    if dimension is not None and int(dimension) not in (2, 3):
        raise ValueError(f"Unsupported dimension for analysis: {dimension}")

    _freud_order_classes = {
        "Hexatic": lambda p: freud.order.Hexatic(**p),
        "Nematic": lambda p: freud.order.Nematic(**p),
        "Steinhardt": lambda p: freud.order.Steinhardt(**p),
    }

    raw = _load_analyze_config()
    shape_order_params = raw.get("shape_order_params", {})

    config = {}
    for shape, param_list in shape_order_params.items():
        order_params = []
        for entry in param_list:
            cls_name = entry["type"]
            if cls_name not in _freud_order_classes:
                raise ValueError(f"Unknown freud order class '{cls_name}' in analysis config.")
            func = _freud_order_classes[cls_name](entry.get("params", {}))
            order_params.append({"name": entry["name"], "func": func})
        config[shape] = {"order_params": order_params}

    return config


def _determine_rdf_r_max(traj):
    rdf_defaults = _load_analyze_config().get("rdf_defaults", {})
    max_cap = rdf_defaults.get("max_cap", 5.0)
    min_dim = None
    for frame in traj:
        valid_dims = [d for d in frame.configuration.box[:3] if d > 0]
        if not valid_dims:
            continue
        frame_min_dim = min(valid_dims)
        min_dim = frame_min_dim if min_dim is None else min(min_dim, frame_min_dim)

    if min_dim is None:
        print("Skipping RDF: invalid box dimensions across trajectory.")
        return None

    r_max = min(max_cap, min_dim / 2.0 * 0.99)
    if r_max <= 0:
        print("Skipping RDF: computed non-positive r_max.")
        return None

    print(f"Auto-determined r_max for RDF: {r_max:.3f}")
    return r_max


def analyze_compute_old(system_dir, density=None):
    """
    Wrapper function that directs the analysis based on the number of particle components.
    """

    # 1. Load Metadata and Trajectory
    if density is not None:
        summary_path = os.path.join(system_dir, f"compress_summary_n{density:.3f}.json")
        gsd_path = os.path.join(system_dir, f"sample_trajectory_n{density:.3f}.gsd")
    else:
        summary_path = os.path.join(system_dir, "compress_summary.json")
        gsd_path = os.path.join(system_dir, "sample_trajectory.gsd")

    if not os.path.exists(summary_path) or not os.path.exists(gsd_path):
        print(f"Error: Missing data in {system_dir}")
        return

    with open(summary_path, "r") as f:
        summary = json.load(f)

    particle_list = summary["particle_list"]

    print(f"--- Starting Analysis for {system_dir} ---")

    traj = gsd.hoomd.open(gsd_path)

    # 1.1. load analysis config
    dimensions = summary.get("dimensions", 3)  # default to 3D if not specified
    analysis_config = get_analyze_config(dimensions)

    results = {}
    # 2 analysis loop: type-specific and global
    # 2.1 type specific analysis loop
    for p_info in particle_list:
        pType = p_info["pType"]
        pTypeShape = pType.split("_")[0]  # e.g. "disk" from "disk_1"
        if pTypeShape in analysis_config:
            instructions = analysis_config[pTypeShape]
            # Execute all configured order parameters
            type_results = _compute_shape_orders(traj, p_info, instructions["order_params"])
            results[f"{pType}"] = type_results
        else:
            print(f"Warning: No analysis config found for shape {pType}")

    # 2.2. rdf analysis loop
    if len(particle_list) > 1:
        # Simple loop for pairs
        for i in range(len(particle_list)):
            for j in range(i, len(particle_list)):
                t1 = particle_list[i]["pType"]
                t2 = particle_list[j]["pType"]
                key = f"rdf_{t1}_{t2}"
                results[key] = _compute_rdf(traj, query_type=t1, target_type=t2)

    # save results to json
    if density is not None:
        result_path = os.path.join(system_dir, f"analysis_results_n{density:.3f}.json")
    else:
        result_path = os.path.join(system_dir, "analysis_results.json")

    with open(result_path, "w") as f:
        json.dump(_make_serializable(results), f, indent=4)

    return results


def _compute_shape_orders(traj, p_info, order_params_list):
    """
    Generic runner for shape-specific order parameters.
    """
    # Initialize Freud Compute Objects
    # We instantiate them ONCE before the loop to save overhead
    computers = []
    for op_config in order_params_list:
        # Dynamic instantiation: freud.order.Hexatic(k=6)
        computers.append({"name": op_config["name"], "obj": op_config["func"]})

    # Loop over trajectory
    frame_results = {comp["name"]: [] for comp in computers}

    for frame in traj:
        box = frame.configuration.box
        positions = frame.particles.position
        orientations_0 = frame.particles.orientation
        # Update orientation based on the long axis from p_info.
        director = p_info.get("pDirector")
        if director is None:
            director = [1, 0, 0]
        orientations = rowan.rotate(orientations_0, director)  # default long axis along z

        # Filter for just this particle type
        # (Assuming you have a helper or logic to get type indices)
        type_ids = frame.particles.typeid
        type_names = frame.particles.types
        target_idx = type_names.index(p_info["pType"])

        # Slicing: Only analyze particles of 'type_name'
        subset_pos = positions[type_ids == target_idx]
        subset_ort = orientations[type_ids == target_idx]

        if len(subset_pos) == 0:
            continue

        for comp in computers:
            calc = comp["obj"]
            name = comp["name"]

            # --- EXECUTION LOGIC ---
            # Some Freud computes need orientations (Nematic), some don't (Steinhardt)
            # We try/except or inspect arguments to be robust.
            if name == "nematic":
                calc.compute(orientations=subset_ort)
            else:
                # General neighbor-based compute (Steinhardt, Hexatic)
                # Heuristic: 6 neighbors for 2D, 12 neighbors for 3D
                is_2d = box[2] == 0
                n_neighbors = 6 if is_2d else 12
                calc.compute(system=(box, subset_pos), neighbors={"num_neighbors": n_neighbors})

            if hasattr(calc, "particle_order"):
                avg_order = np.mean(calc.particle_order)
            elif hasattr(calc, "order"):
                avg_order = calc.order  # Nematic returns a scalar 'order' directly
            else:
                avg_order = 0.0  # Fallback

            frame_results[name].append(avg_order)

    return frame_results


def _compute_rdf(traj, r_max=None, bins=None, query_type=None, target_type=None):
    """
    Computes RDF using Freud.
    If types are None, computes Global RDF.
    If types are specified, computes Partial RDF.
    """
    rdf_defaults = _load_analyze_config().get("rdf_defaults", {})
    if bins is None:
        bins = rdf_defaults.get("bins", 100)
    r_min = rdf_defaults.get("r_min", 0.1)
    if r_max is None:
        r_max = _determine_rdf_r_max(traj)
        if r_max is None:
            return {"r": [], "g_r": []}

    rdf = freud.density.RDF(bins=bins, r_max=r_max, r_min=r_min)
    computed_frames = 0
    skipped_frames = 0

    for frame in traj:
        box = frame.configuration.box
        points = frame.particles.position
        type_ids = frame.particles.typeid
        type_names = frame.particles.types  # List of type strings

        # Filter points if specific types are requested
        query_points = points
        target_points = points

        if query_type and target_type:
            # Map string type to integer ID
            # Note: This assumes type definitions don't change frame-to-frame (standard HOOMD)
            try:
                q_id = type_names.index(query_type)
                t_id = type_names.index(target_type)
            except ValueError:
                continue  # Type not found in this frame

            query_points = points[type_ids == q_id]
            target_points = points[type_ids == t_id]

        if len(query_points) == 0 or len(target_points) == 0:
            continue

        # Double check box constraints for safety
        valid_dims = [d for d in box[:3] if d > 0]
        if not valid_dims:
            continue
        box_min_dim = min(valid_dims)
        if r_max > box_min_dim / 2.0:
            skipped_frames += 1
            continue

        rdf.compute(system=(box, target_points), query_points=query_points, reset=False)
        computed_frames += 1

    if computed_frames == 0:
        if skipped_frames:
            print(
                f"Skipping RDF: no frames satisfied the box-size requirement for r_max={r_max:.3f}."
            )
        return {"r": [], "g_r": []}

    if skipped_frames:
        print(f"Skipped {skipped_frames} frame(s) for RDF because the box became smaller than r_max={r_max:.3f}.")

    return {"r": rdf.bin_centers.tolist(), "g_r": rdf.rdf.tolist()}


def _make_serializable(obj):
    """Recursively convert numpy types to standard python types for JSON dump"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, (np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, (np.int32, np.int64)):
        return int(obj)
    elif isinstance(obj, (complex, np.complex64, np.complex128)):
        return {"real": float(obj.real), "imag": float(obj.imag)}
    return obj
