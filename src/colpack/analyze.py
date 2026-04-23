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


def analyze_main(run_dir, extra_order_params=None):
    """
    Main function to analyze the compressed system.
    It will read the compress_summary.json and sample_trajectory.gsd from the system_dir,
    then perform analysis based on the particle types and shapes, and save the results to analysis_results.json

    Parameters
    ----------
    run_dir : str
        Path to the run directory.
    extra_order_params : list[dict], optional
        Additional order parameters to measure for every particle type,
        on top of the shape-specific defaults.  Each entry is a dict with:
          - ``"name"`` (str): result key name (e.g. ``"hexatic_8"``).
          - ``"type"`` (str): freud.order class name (e.g. ``"Hexatic"``).
          - ``"params"`` (dict): constructor keyword arguments
            (e.g. ``{"k": 8}``).
        Example::

            extra_order_params=[
                {"name": "hexatic_8", "type": "Hexatic", "params": {"k": 8}},
                {"name": "steinhardt_q10", "type": "Steinhardt", "params": {"l": 10}},
            ]

        Available types and their required/optional parameters are listed in
        ``available_analysis_params.order`` in colpack_config.json.
    """
    run_dir = _normalize_run_dir(run_dir)

    # 0 some error handling and check the required files
    simulation_config_path = os.path.join(run_dir, "simulation_config_sample.json")
    if not os.path.exists(simulation_config_path):
        raise FileNotFoundError(f"Missing simulation_config_sample.json in {run_dir}. Cannot perform analysis.")

    with open(simulation_config_path, "r") as f:
        simulation_config = json.load(f)

    # 1. compute and save the analysis results
    analyze_compute(run_dir, simulation_config, extra_order_params=extra_order_params)

    # 2.0 find the post analysis simulation config path
    simulation_config_path = os.path.join(run_dir, "simulation_config_analysis.json")
    if not os.path.exists(simulation_config_path):
        raise FileNotFoundError(f"Missing simulation_config_analysis.json in {run_dir}. Cannot perform plotting.")

    # 1.5 analyze analysis time series results, find if the simulation reached equilibrium if so what the equilibrium steps can be used
    analyze_process_time_series(run_dir)

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


def analyze_compute(run_dir, simulation_config, extra_order_params=None):
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

    # 1.1 resolve extra order params from config catalog
    extra_ops = _resolve_extra_order_params(extra_order_params) if extra_order_params else []

    results = {}

    # 2 analysis loop: type-specific and global
    # 2.1 type specific analysis loop
    for p_info in particle_list:
        pType = p_info["pType"]
        pTypeShape = pType.split("_")[0]  # e.g. "disk" from "disk_1"
        if pTypeShape in analysis_config:
            instructions = analysis_config[pTypeShape]
            # Merge shape defaults with extra params (skip duplicates by name)
            merged_ops = list(instructions["order_params"])
            existing_names = {op["name"] for op in merged_ops}
            for op in extra_ops:
                if op["name"] not in existing_names:
                    merged_ops.append(op)
            # Execute all configured order parameters
            type_results = _compute_shape_orders(traj, p_info, merged_ops)
            results[f"{pType}"] = type_results
        else:
            if extra_ops:
                type_results = _compute_shape_orders(traj, p_info, extra_ops)
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


def analyze_process_time_series(run_dir):
    """
    Post-process analysis time series to detect equilibrium and compute
    equilibrium averages.

    For each order parameter time series, we start from an accepted tail
    window at the end of the trajectory (assumed equilibrated), then walk
    backward one frame at a time. Each newly added point is checked against
    the current window mean/std (sigma gate). If accepted, the window is
    extended and the reference statistics are updated dynamically.

    Updates analysis_results.json in-place, adding an ``"equilibrium"``
    block per particle type with per-parameter equilibrium info.
    """
    run_dir = _normalize_run_dir(run_dir)
    result_path = os.path.join(run_dir, "analysis_results.json")
    if not os.path.exists(result_path):
        print(f"No analysis_results.json in {run_dir}, skipping time-series processing.")
        return

    with open(result_path, "r") as f:
        results = json.load(f)

    for key, data in results.items():
        # Skip RDF entries and non-dict entries
        if key.startswith("rdf_") or not isinstance(data, dict):
            continue

        eq_info = {}
        for param_name, values in data.items():
            if param_name == "equilibrium":
                continue
            eq_info[param_name] = _detect_equilibrium(values)

        # Determine overall equilibrium status for this particle type:
        # equilibrated if ALL parameters are equilibrated.
        all_eq = all(info["equilibrated"] for info in eq_info.values()) if eq_info else False
        # The overall equilibrium start is the latest (max) start among params.
        eq_starts = [info["eq_start_index"] for info in eq_info.values() if info["equilibrated"]]
        overall_start = max(eq_starts) if eq_starts else None

        # Rebuild dict with equilibrium at the top
        eq_block = {
            "equilibrated": all_eq,
            "eq_start_index": overall_start,
            "per_parameter": eq_info,
        }
        reordered = {"equilibrium": eq_block}
        reordered.update({k: v for k, v in data.items() if k != "equilibrium"})
        results[key] = reordered

    with open(result_path, "w") as f:
        json.dump(results, f, indent=4)

    print(f"Equilibrium analysis written to {result_path}")


def _detect_equilibrium(values, n_sigma=2.0, min_eq_fraction=0.1):
    """
    Detect equilibrium onset in a 1-D time series using a reverse,
    pointwise sigma gate with a dynamically updated reference window.

    Algorithm:
      1. Convert complex-valued entries (``{"real", "imag"}``) to magnitudes.
      2. Initialize an accepted equilibrium window as the last
         ``min_eq_fraction`` of frames.
      3. Walk backwards one frame at a time; for each newly added point,
         test whether it lies within ``n_sigma * current_std`` of the
         current accepted-window mean.
      4. If the point is within tolerance, include it and recompute
         mean/std on the extended window (dynamic reference).
         If not, stop and set ``eq_start_index`` to the next frame.
      5. Report equilibrium stats over ``arr[eq_start_index:]``.

    Returns a dict with:
      - equilibrated (bool)
      - eq_start_index (int or None)
      - eq_mean (float or None) — mean over the equilibrated portion
      - eq_std (float or None) — std dev over the equilibrated portion
    """
    if not values or len(values) < 4:
        return {"equilibrated": False, "eq_start_index": None, "eq_mean": None, "eq_std": None}

    # Convert to float array (handle complex dicts)
    arr = _values_to_float_array(values)
    n = len(arr)

    # Initial accepted window: last min_eq_fraction of frames
    tail_len = max(2, int(n * min_eq_fraction))
    tail_len = min(tail_len, n)
    accepted_start = n - tail_len
    current_window = arr[accepted_start:]
    current_mean = np.mean(current_window)
    current_std = np.std(current_window)

    # Walk backwards from the frame before the accepted window.
    # Gate each newly added point against current window statistics,
    # then update the reference dynamically after acceptance.
    eq_start = accepted_start
    for i in range(accepted_start - 1, -1, -1):
        tol = 1e-8 if current_std < 1e-12 else n_sigma * current_std
        if abs(arr[i] - current_mean) > tol:
            eq_start = i + 1
            break
        accepted_start = i
        current_window = arr[accepted_start:]
        current_mean = np.mean(current_window)
        current_std = np.std(current_window)
    else:
        eq_start = 0

    # Clamp to valid range
    eq_start = min(eq_start, n - 1)

    eq_portion = arr[eq_start:]
    equilibrated = len(eq_portion) >= max(2, int(n * min_eq_fraction))

    return {
        "equilibrated": equilibrated,
        "eq_start_index": int(eq_start),
        "eq_mean": float(np.mean(eq_portion)),
        "eq_std": float(np.std(eq_portion)),
    }


def _values_to_float_array(values):
    """Convert a list of values (possibly complex dicts) to a float numpy array."""
    if isinstance(values[0], dict) and "real" in values[0] and "imag" in values[0]:
        return np.array([np.hypot(v["real"], v["imag"]) for v in values])
    return np.array(values, dtype=float)


_FREUD_ORDER_CLASSES = {
    "Hexatic": lambda p: freud.order.Hexatic(**p),
    "Nematic": lambda p: freud.order.Nematic(**p),
    "Steinhardt": lambda p: freud.order.Steinhardt(**p),
    "ContinuousCoordination": lambda p: freud.order.ContinuousCoordination(**p),
    "Cubatic": lambda p: freud.order.Cubatic(**p),
    "SolidLiquid": lambda p: freud.order.SolidLiquid(**p),
    "RotationalAutocorrelation": lambda p: freud.order.RotationalAutocorrelation(**p),
}


def _resolve_extra_order_params(param_specs):
    """
    Resolve a list of order parameter specifications into instantiated
    freud objects.

    Each element of *param_specs* is a dict with:
      - ``"name"`` (str): result key name.
      - ``"type"`` (str): freud.order class name.
      - ``"params"`` (dict): constructor keyword arguments.

    Validates that:
      1. The ``type`` is a supported freud.order class.
      2. All required constructor parameters are provided.
      3. No unknown parameters are passed.

    Returns a list of ``{"name": ..., "func": ...}`` dicts ready for
    ``_compute_shape_orders``.
    """
    import inspect

    resolved = []
    for spec in param_specs:
        # --- basic structure check ---
        if not isinstance(spec, dict):
            raise TypeError(
                f"Each extra_order_params entry must be a dict, got {type(spec).__name__}."
            )
        for required_key in ("name", "type"):
            if required_key not in spec:
                raise ValueError(f"Extra order param entry missing required key '{required_key}': {spec}")

        name = spec["name"]
        cls_name = spec["type"]
        params = dict(spec.get("params", {}))

        # --- validate class name ---
        if cls_name not in _FREUD_ORDER_CLASSES:
            raise ValueError(
                f"Unknown freud order class '{cls_name}'. "
                f"Supported: {list(_FREUD_ORDER_CLASSES.keys())}"
            )

        # --- validate constructor params ---
        freud_cls = getattr(freud.order, cls_name)
        sig = inspect.signature(freud_cls.__init__)
        valid_params = {k for k in sig.parameters if k != "self"}
        required_params = {
            k for k, v in sig.parameters.items()
            if k != "self" and v.default is inspect.Parameter.empty
        }

        unknown = set(params) - valid_params
        if unknown:
            raise ValueError(
                f"Unknown parameter(s) {unknown} for {cls_name}. "
                f"Valid: {valid_params}"
            )

        missing = required_params - set(params)
        if missing:
            raise ValueError(
                f"Missing required parameter(s) {missing} for {cls_name}. "
                f"Required: {required_params}"
            )

        # Filter out None values
        params = {k: v for k, v in params.items() if v is not None}
        func = _FREUD_ORDER_CLASSES[cls_name](params)
        resolved.append({"name": name, "func": func})
    return resolved


def get_analyze_config(dimension=None):
    """
    Builds analysis config from colpack_config.json, instantiating freud objects.
    """
    if dimension is not None and int(dimension) not in (2, 3):
        raise ValueError(f"Unsupported dimension for analysis: {dimension}")

    raw = _load_analyze_config()
    shape_order_params = raw.get("shape_order_params", {})

    config = {}
    for shape, param_list in shape_order_params.items():
        order_params = []
        for entry in param_list:
            cls_name = entry["type"]
            if cls_name not in _FREUD_ORDER_CLASSES:
                raise ValueError(f"Unknown freud order class '{cls_name}' in analysis config.")
            func = _FREUD_ORDER_CLASSES[cls_name](entry.get("params", {}))
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


def _compute_shape_orders(traj, p_info, order_params_list):
    """
    Generic runner for shape-specific order parameters.
    Supports all freud.order classes:
      - Hexatic, Steinhardt: system + neighbors
      - Nematic: orientation vectors (3D)
      - Cubatic: raw quaternions (4D)
      - ContinuousCoordination: system (uses Voronoi internally)
      - SolidLiquid: system + neighbors
      - RotationalAutocorrelation: ref quaternions + current quaternions
    """
    # Initialize Freud Compute Objects
    # We instantiate them ONCE before the loop to save overhead
    computers = []
    for op_config in order_params_list:
        computers.append({"name": op_config["name"], "obj": op_config["func"]})

    # Loop over trajectory
    frame_results = {comp["name"]: [] for comp in computers}
    ref_quaternions = {}  # for RotationalAutocorrelation: name -> first-frame quaternions

    for frame in traj:
        box = frame.configuration.box
        positions = frame.particles.position
        orientations_0 = frame.particles.orientation
        # Update orientation based on the long axis from p_info.
        director = p_info.get("pDirector")
        if director is None:
            director = [1, 0, 0]
        orientations = rowan.rotate(orientations_0, director)  # direction vectors (N, 3)

        # Filter for just this particle type
        type_ids = frame.particles.typeid
        type_names = frame.particles.types
        target_idx = type_names.index(p_info["pType"])

        # Slicing: Only analyze particles of 'type_name'
        subset_pos = positions[type_ids == target_idx]
        subset_ort = orientations[type_ids == target_idx]
        subset_quat = orientations_0[type_ids == target_idx]

        if len(subset_pos) == 0:
            continue

        for comp in computers:
            calc = comp["obj"]
            name = comp["name"]

            # --- COMPUTE DISPATCH ---
            if isinstance(calc, freud.order.Nematic):
                calc.compute(orientations=subset_ort)
            elif isinstance(calc, freud.order.Cubatic):
                calc.compute(subset_quat)
            elif isinstance(calc, freud.order.RotationalAutocorrelation):
                if name not in ref_quaternions:
                    ref_quaternions[name] = subset_quat.copy()
                calc.compute(ref_quaternions[name], subset_quat)
            elif isinstance(calc, freud.order.ContinuousCoordination):
                calc.compute(system=(box, subset_pos))
            else:
                # Hexatic, Steinhardt, SolidLiquid
                # Heuristic: 6 neighbors for 2D, 12 neighbors for 3D
                is_2d = box[2] == 0
                n_neighbors = 6 if is_2d else 12
                calc.compute(system=(box, subset_pos), neighbors={"num_neighbors": n_neighbors})

            # --- RESULT EXTRACTION ---
            if isinstance(calc, freud.order.SolidLiquid):
                avg_order = np.mean(calc.num_connections)
            elif hasattr(calc, "particle_order"):
                avg_order = np.mean(calc.particle_order)
            elif hasattr(calc, "order"):
                avg_order = calc.order  # Nematic, Cubatic, RotationalAutocorrelation
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
