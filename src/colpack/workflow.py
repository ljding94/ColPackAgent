import os
import json
import copy
from datetime import datetime, timezone
from colpack.initialize import create_initial_config
from colpack.compress import compress_system
from colpack.sample import sample_system
from colpack.analyze import analyze_main
from colpack.config_reading import get_allowed_shapes, canonicalize_shape, get_shape_defaults, get_workflow_config
from colpack.workflow_helper import (
    _set_by_path,
    _get_by_path,
    _build_baseline_with_defaults,
    _append_status,
    _initialize_status_csv,
    _build_run_status_record,
)


# generate the simulation config for a base simulation run: dimension, particle number, ensemble, particle shapes
def setup_simulation_problem(dimension: int, total_particle_number: int, particle_shape_list: list, ensemble: str, working_dir: str):
    """
    define the dimension, total particle number, particle type (shapes) for the simulation problem to study, output a json file for the set up.

    for particle type:
    when dimension==2:
        shape can be disk, ellipse,triangle, square, rectangle, capsule.
    when dimension==3:
        shape can be sphere, ellipsoid, cube, octahedron, tetrahedron, capsule
    """
    if dimension not in (2, 3):
        raise ValueError("dimension must be 2 or 3.")

    total_particle_number = int(total_particle_number)
    if total_particle_number <= 0:
        raise ValueError("total_particle_number must be a positive integer.")

    if not isinstance(particle_shape_list, list) or len(particle_shape_list) == 0:
        raise ValueError("particle_shape_list must be a non-empty list.")

    if not isinstance(ensemble, str) or not ensemble.strip():
        raise ValueError("ensemble must be a non-empty string.")
    ensemble = ensemble.strip().upper()
    if ensemble not in {"NVT", "NPT"}:
        raise ValueError("ensemble must be either 'NVT' or 'NPT'.")

    workflow_config = get_workflow_config()
    placeholder = workflow_config.get("placeholder", "Nan")
    particle_required_fields = workflow_config.get("particle_required_fields", ["relative_volume_fraction"])
    relative_volume_fraction_first_particle = workflow_config.get("relative_volume_fraction_first_particle", 1)
    relative_volume_fraction_other_particles = workflow_config.get("relative_volume_fraction_other_particles", placeholder)
    common_system_fields = workflow_config.get("common_system_fields", {})
    ensemble_requirements = workflow_config.get("ensemble_requirements", {})

    allowed_shapes = get_allowed_shapes(dimension)

    normalized_particle_specs = []
    for type_index, item in enumerate(particle_shape_list):
        if isinstance(item, str):
            shape = canonicalize_shape(dimension, item)
            if shape not in allowed_shapes:
                allowed_text = ", ".join(sorted(allowed_shapes))
                raise ValueError(f"Invalid shape '{shape}' for dimension {dimension}. Allowed shapes: {allowed_text}.")

            # Required fields are ensemble-dependent and may be populated later.
            particle_spec = {
                "type": type_index,
                "shape": shape,
            }

            for field_name in particle_required_fields:
                if field_name == "relative_volume_fraction" and type_index == 0:
                    particle_spec[field_name] = relative_volume_fraction_first_particle
                elif field_name == "relative_volume_fraction":
                    particle_spec[field_name] = relative_volume_fraction_other_particles
                else:
                    particle_spec[field_name] = placeholder

            defaults = get_shape_defaults(dimension, shape)
            for param_name in defaults:
                particle_spec[param_name] = placeholder

            normalized_particle_specs.append(particle_spec)
            continue

        raise ValueError("Each entry in particle_shape_list must be a string")

    os.makedirs(working_dir, exist_ok=True)

    # save the simulation problem json to file
    simulation_problem = {
        "dimension": dimension,
        "total_particle_number": total_particle_number,
        "ensemble": ensemble,
        "working_dir": working_dir,
    }

    for key, value in common_system_fields.items():
        simulation_problem[key] = value

    system_fields = ensemble_requirements.get(ensemble, {}).get("system_fields", {})
    for key, value in system_fields.items():
        simulation_problem[key] = value

    simulation_problem["particle_specs"] = normalized_particle_specs

    output_path = os.path.join(working_dir, "simulation_problem.json")
    with open(output_path, "w") as f:
        json.dump(simulation_problem, f, indent=4)

    return simulation_problem


# planning all of the simulation run, based on variation of the base simulation run, tunable parameter will be determined based on the base config
def plan_simulaiton_runs(baseline_parameters: dict, tunable_parameters: dict, working_dir: str | None = None):
    """
    Build one-parameter-at-a-time simulation runs from a baseline.

    Inputs:
    - baseline_parameters: dict containing fixed parameters and base structure
    - tunable_parameters: dict mapping parameter-path -> list of values

    Missing baseline values are backfilled from colpack_config defaults.

    output will be json file containing a list of planned simulation runs, with parameters the same as the ones in the simulation_problem.json, but with varied parameter values. The json file will be saved in the run_dir defined in the baseline_parameters.
    """
    if not isinstance(baseline_parameters, dict):
        raise TypeError("baseline_parameters must be a dictionary.")

    if not working_dir:
        raise ValueError("baseline_parameters must include 'working_dir' to save baseline and planned runs.")

    os.makedirs(working_dir, exist_ok=True)

    # 1) Resolve simulation_problem source and apply baseline overrides.
    simulation_problem_path = os.path.join(working_dir, "simulation_problem.json")

    if os.path.exists(simulation_problem_path):
        with open(simulation_problem_path, "r") as f:
            simulation_problem = json.load(f)
    else:
        simulation_problem = {}

    workflow_config = get_workflow_config()
    placeholder = workflow_config.get("placeholder", "Nan")

    merged_baseline = copy.deepcopy(simulation_problem)
    for key, value in baseline_parameters.items():
        if key in {"simulation_problem_path", "run_dir"}:
            continue

        # If the key/path exists in simulation_problem and is already non-placeholder,
        # reject attempts to override it and keep the original value.
        exists_in_problem, current_value = _get_by_path(simulation_problem, key)
        if exists_in_problem and current_value != placeholder and current_value != value:
            print(f"Warning: baseline override '{key}={value}' rejected because " f"simulation_problem already sets '{key}={current_value}'.")
            continue

        # Allow nested baseline overrides via dot paths, e.g. particle_specs.0.diameter
        if isinstance(key, str) and "." in key:
            _set_by_path(merged_baseline, key, value)
        else:
            merged_baseline[key] = value

    # 2) Fill placeholders/missing values from baseline + config defaults.
    base = _build_baseline_with_defaults(merged_baseline)

    # 3) Save the resolved baseline setup.
    baseline_path = os.path.join(working_dir, "simulation_baseline.json")
    with open(baseline_path, "w") as f:
        json.dump(base, f, indent=4)

    # 4) Read baseline from disk and copy it for each tuned run.
    with open(baseline_path, "r") as f:
        baseline_from_file = json.load(f)

    if not isinstance(tunable_parameters, dict) or len(tunable_parameters) == 0:
        raise ValueError("tunable_parameters must be a non-empty dictionary.")

    simulation_runs = []
    run_number = 0
    for parameter_path, values in tunable_parameters.items():
        if not isinstance(values, list) or len(values) == 0:
            raise ValueError(f"Tunable parameter '{parameter_path}' must map to a non-empty list of values.")

        for value in values:
            run = copy.deepcopy(baseline_from_file)
            _set_by_path(run, parameter_path, value)

            run_folder = os.path.join(working_dir, f"run_{run_number}")
            os.makedirs(run_folder, exist_ok=True)

            run["run_number"] = run_number
            run["run_dir"] = run_folder

            run_config_path = os.path.join(run_folder, "simulation_config.json")
            with open(run_config_path, "w") as run_config_file:
                json.dump(run, run_config_file, indent=4)

            simulation_runs.append(run)
            run_number += 1

    os.makedirs(working_dir, exist_ok=True)
    planning_path = os.path.join(working_dir, "simulation_plan.json")
    with open(planning_path, "w") as f:
        json.dump(simulation_runs, f, indent=4)

    return {
        "baseline": base,
        "baseline_path": baseline_path,
        "simulation_runs": simulation_runs,
        "planning_path": planning_path,
        "n_runs": len(simulation_runs),
    }


# TODO: only drafted version, needs lots of checking and refining
# excute simulation workflow for each simulation run
def excute_simulation_workflow(working_dir: str | None = None, continue_on_error: bool = True):
    """
    this function will excute the simulation workflow for every entry of the planned simulation parameters,
    1. read the planned simulation json files, create a status csv file to keep track of the simulation run.
    2. for each simulation set up, create a new folder under the woking folder, excute the simulation workflow, including initial config generation, compress, sampling, and analyze. simulation results will be saved in corresponding folder.
    3. after each run, append the status (success or failure, error message if any) to the status file, along with corresponding simulation json infomation
    """
    # 1) read the planned simulation json files, create a status csv file to keep track of the simulation run.
    if not working_dir:
        raise ValueError("Unable to resolve working_dir from inputs or planned runs.")

    simulation_plan_path = os.path.join(working_dir, "simulation_plan.json") if working_dir else None
    if simulation_plan_path is None:
        if working_dir is None:
            raise ValueError("Provide either simulation_plan_path or working_dir.")
        simulation_plan_path = os.path.join(working_dir, "simulation_plan.json")

    if not os.path.exists(simulation_plan_path):
        raise FileNotFoundError(f"Simulation plan file not found: {simulation_plan_path}")

    with open(simulation_plan_path, "r") as f:
        planned_runs = json.load(f)

    if not isinstance(planned_runs, list) or len(planned_runs) == 0:
        raise ValueError("simulation_plan_path must contain a non-empty list of simulation runs.")

    status_path = os.path.join(working_dir, "workflow_status.csv")
    workflow_config = get_workflow_config()
    status_fieldnames = workflow_config.get("status_fieldnames")
    if not isinstance(status_fieldnames, list) or len(status_fieldnames) == 0:
        raise ValueError("workflow.status_fieldnames must be configured as a non-empty list in colpack_config.json.")

    # initialize status file
    status_records = []
    _initialize_status_csv(status_path, status_fieldnames)

    for idx, run in enumerate(planned_runs):
        run_number = run.get("run_number", idx)
        run_dir = run.get("run_dir")
        if not run_dir:
            run_dir = os.path.join(working_dir, f"run_{run_number}")
        os.makedirs(run_dir, exist_ok=True)

        run_record = _build_run_status_record(run, run_number, run_dir)

        try:
            # Required run parameters for current lower-level APIs.
            if "particle_specs" not in run:
                raise ValueError("Missing 'particle_specs' in run configuration.")
            if "dimension" not in run:
                raise ValueError("Missing 'dimension' in run configuration.")

            target_number_density = run.get("target_number_density", run.get("number_density", run.get("n")))
            if target_number_density is None:
                raise ValueError("Missing compression target density. Provide 'target_number_density' (or alias 'number_density'/'n') in planned runs.")

            sampling_steps = int(run.get("sampling_steps", 200000))
            seed = int(run.get("seed", 0))

            # 1. initialize
            create_initial_config(run_dir=run_dir)
            run_record["initialize"] = "O"

            # 2. compress
            compress_system(run_dir=run_dir)
            run_record["compress"] = "O"

            # 3. sample
            sample_system(
                sample_steps=sampling_steps,
                system_dir=run_dir,
                density=float(target_number_density),
                seed=seed,
            )
            run_record["sample"] = "O"

            # 4. analyze
            analyze_main(
                system_dir=run_dir,
                density=float(target_number_density),
            )
            run_record["analyze"] = "O"

            run_record["status"] = "success"
            run_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            _append_status(status_path, status_records, status_fieldnames, run_record)

        except Exception as exc:
            run_record["status"] = "failed"
            run_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            run_record["error"] = str(exc)
            _append_status(status_path, status_records, status_fieldnames, run_record)
            if not continue_on_error:
                break

    return {
        "status_path": status_path,
        "n_runs": len(planned_runs),
        "n_success": sum(1 for r in status_records if r.get("status") == "success"),
        "n_failed": sum(1 for r in status_records if r.get("status") == "failed"),
    }
