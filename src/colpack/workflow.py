import os
import json
import copy
import csv
from datetime import datetime, timezone
from colpack.config_reading import get_allowed_shapes, canonicalize_shape, get_shape_defaults, get_workflow_config
from colpack.workflow_helper import (
    _set_by_path,
    _get_by_path,
    _build_baseline_with_defaults,
    _is_immutable_planning_path,
    _initialize_status_csv,
    _load_and_extend_simulation_plan,
    _build_run_status_record,
    _validate_planning_parameter_paths,
    _write_workflow_progress,
    resolve_working_dir_from_setup,
    _write_status_snapshot,
)
from colpack.workflow_logging import append_workflow_log, resolve_workflow_log_path


STEP_SEQUENCE = ["initialize", "compress", "sample", "analyze"]
EXECUTION_STATE_FIELD = "execution_state"
EXECUTION_STATE_RUNNING = "running"
EXECUTION_STATE_FINISHED = "finished"


# generate the simulation config for a base simulation run: dimension, particle number, ensemble, particle shapes
def setup_simulation_problem(
    dimension: int,
    total_particle_number: int,
    particle_shape_list: list,
    ensemble: str,
):
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

    resolved_working_dir = resolve_working_dir_from_setup(
        dimension=dimension,
        ensemble=ensemble,
        particle_shape_list=[spec["shape"] for spec in normalized_particle_specs],
    )

    os.makedirs(resolved_working_dir, exist_ok=True)

    # save the simulation problem json to file
    simulation_problem = {
        "dimension": dimension,
        "total_particle_number": total_particle_number,
        "ensemble": ensemble,
        "working_dir": resolved_working_dir,
    }

    for key, value in common_system_fields.items():
        simulation_problem[key] = value

    system_fields = ensemble_requirements.get(ensemble, {}).get("system_fields", {})
    for key, value in system_fields.items():
        simulation_problem[key] = value

    simulation_problem["particle_specs"] = normalized_particle_specs

    output_path = os.path.join(resolved_working_dir, "simulation_problem.json")
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

    if not os.path.exists(simulation_problem_path):
        raise FileNotFoundError(
            f"simulation_problem.json not found in working_dir: {simulation_problem_path}. "
            "Run setup_simulation_problem before planning runs."
        )

    with open(simulation_problem_path, "r") as f:
        simulation_problem = json.load(f)

    if not isinstance(simulation_problem, dict) or len(simulation_problem) == 0:
        raise ValueError("simulation_problem.json must contain a non-empty JSON object.")

    _validate_planning_parameter_paths(simulation_problem, baseline_parameters, "baseline_parameters")
    _validate_planning_parameter_paths(simulation_problem, tunable_parameters, "tunable_parameters")

    merged_baseline = copy.deepcopy(simulation_problem)
    for key, value in baseline_parameters.items():
        if key in {"simulation_problem_path", "run_dir"}:
            continue

        if _is_immutable_planning_path(str(key)):
            exists_in_problem, current_value = _get_by_path(simulation_problem, key)
            if exists_in_problem and current_value != value:
                print(f"Warning: baseline override '{key}={value}' rejected because " f"simulation_problem fixes '{key}={current_value}'.")
                continue

        # Mutable planning parameters from simulation_problem.json may be overridden here.
        if _is_immutable_planning_path(str(key)):
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

    planning_path = os.path.join(working_dir, "simulation_plan.json")
    existing_runs, combined_runs = _load_and_extend_simulation_plan(
        planning_path=planning_path,
        baseline_from_file=baseline_from_file,
        tunable_parameters=tunable_parameters,
        working_dir=working_dir,
    )
    simulation_runs = combined_runs[len(existing_runs) :]

    with open(planning_path, "w") as f:
        json.dump(combined_runs, f, indent=4)

    return {
        "baseline": base,
        "baseline_path": baseline_path,
        "simulation_runs": simulation_runs,
        "planning_path": planning_path,
        "n_runs": len(simulation_runs),
        "n_existing_runs": len(existing_runs),
        "n_total_runs": len(combined_runs),
    }


def execute_simulation_workflow(
    working_dir: str | None = None,
    continue_on_error: bool = True,
):
    """
    this function will excute the simulation workflow for every entry of the planned simulation parameters,
    1. read the planned simulation json files, create a status csv file to keep track of the simulation run.
    2. for each simulation set up, create a new folder under the woking folder, excute the simulation workflow, including initial config generation, compress, sampling, and analyze. simulation results will be saved in corresponding folder.
    3. after each run, append the status (success or failure, error message if any) to the status file, along with corresponding simulation json infomation
    """
    # 1) read the planned simulation json files, create a status csv file to keep track of the simulation run.
    if not working_dir:
        raise ValueError("Unable to resolve working_dir from inputs or planned runs.")

    append_workflow_log(
        working_dir,
        f"execute_simulation_workflow started with continue_on_error={continue_on_error}",
        source="workflow",
    )

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
    status_fieldnames = list(status_fieldnames)
    if EXECUTION_STATE_FIELD not in status_fieldnames:
        status_fieldnames.append(EXECUTION_STATE_FIELD)

    # Initialize or resume status tracking (one latest row per run).
    existing_records_by_run = {}
    if os.path.exists(status_path) and os.path.getsize(status_path) > 0:
        with open(status_path, "r", newline="") as status_file:
            reader = csv.DictReader(status_file)
            for row in reader:
                if not row:
                    continue
                run_number_key = str(row.get("run_number", ""))
                row[EXECUTION_STATE_FIELD] = str(row.get(EXECUTION_STATE_FIELD, "")).strip() or EXECUTION_STATE_FINISHED
                existing_records_by_run[run_number_key] = row
    else:
        _initialize_status_csv(status_path, status_fieldnames)

    if any(record.get(EXECUTION_STATE_FIELD) == EXECUTION_STATE_RUNNING for record in existing_records_by_run.values()):
        already_running_message = "Workflow execution is already running for this working_dir. Skipping duplicate execute request."
        append_workflow_log(working_dir, already_running_message, source="workflow")
        _write_workflow_progress(
            working_dir=working_dir,
            n_runs=max(len(planned_runs), 1),
            records_by_run=existing_records_by_run,
            status="already_running",
            message=already_running_message,
        )
        latest_records = list(existing_records_by_run.values())
        return {
            "status_path": status_path,
            "progress_path": os.path.join(working_dir, "workflow_progress.json"),
            "log_path": str(resolve_workflow_log_path(working_dir)),
            "n_runs": len(planned_runs),
            "n_success": sum(1 for r in latest_records if r.get("status") == "success"),
            "n_failed": sum(1 for r in latest_records if r.get("status") == "failed"),
            "already_running": True,
        }

    # Keep heavy simulation imports lazy so setup/guard logic can run without HOOMD.
    from colpack.initialize import create_initial_config
    from colpack.compress import compress_system
    from colpack.sample import sample_system

    _write_workflow_progress(
        working_dir=working_dir,
        n_runs=len(planned_runs),
        records_by_run=existing_records_by_run,
        status="running",
        message=f"Loaded {len(planned_runs)} planned run(s).",
    )

    # TODO: make the following for loop parallel? and degree of paralleization depends on available cpu/gpu
    for idx, run in enumerate(planned_runs):
        run_number = run.get("run_number", idx)
        run_dir = run.get("run_dir")
        if not run_dir:
            run_dir = os.path.join(working_dir, f"run_{run_number}")
        os.makedirs(run_dir, exist_ok=True)

        run_record = _build_run_status_record(run, run_number, run_dir)
        previous_record = existing_records_by_run.get(str(run_number))
        if previous_record:
            for step_name in ["initialize", "compress", "sample", "analyze"]:
                if previous_record.get(step_name) == "O":
                    run_record[step_name] = "O"

        # Emit an immediate row so status CSV reflects in-progress runs.
        run_record["status"] = "running"
        run_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_RUNNING
        existing_records_by_run[str(run_number)] = run_record.copy()
        _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
        _write_workflow_progress(
            working_dir=working_dir,
            n_runs=len(planned_runs),
            records_by_run=existing_records_by_run,
            status="running",
            message=f"Starting run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
        )

        try:
            # Required run parameters for current lower-level APIs.
            if "particle_specs" not in run:
                raise ValueError("Missing 'particle_specs' in run configuration.")
            if "dimension" not in run:
                raise ValueError("Missing 'dimension' in run configuration.")

            # 1. initialize
            if run_record["initialize"] != "O":
                _write_workflow_progress(
                    working_dir=working_dir,
                    n_runs=len(planned_runs),
                    records_by_run=existing_records_by_run,
                    status="running",
                    message=f"Running initialize for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
                )
                create_initial_config(run_dir=run_dir)
                run_record["initialize"] = "O"
                run_record["status"] = "running"
                run_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_RUNNING
                existing_records_by_run[str(run_number)] = run_record.copy()
                _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
                _write_workflow_progress(
                    working_dir=working_dir,
                    n_runs=len(planned_runs),
                    records_by_run=existing_records_by_run,
                    status="running",
                    message=f"Completed initialize for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
                )

            # 2. compress
            if run_record["compress"] != "O":
                _write_workflow_progress(
                    working_dir=working_dir,
                    n_runs=len(planned_runs),
                    records_by_run=existing_records_by_run,
                    status="running",
                    message=f"Running compress for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
                )
                compress_system(run_dir=run_dir)
                run_record["compress"] = "O"
                run_record["status"] = "running"
                run_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_RUNNING
                existing_records_by_run[str(run_number)] = run_record.copy()
                _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
                _write_workflow_progress(
                    working_dir=working_dir,
                    n_runs=len(planned_runs),
                    records_by_run=existing_records_by_run,
                    status="running",
                    message=f"Completed compress for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
                )

            # 3. sample
            if run_record["sample"] != "O":
                _write_workflow_progress(
                    working_dir=working_dir,
                    n_runs=len(planned_runs),
                    records_by_run=existing_records_by_run,
                    status="running",
                    message=f"Running sample for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
                )
                sample_system(run_dir=run_dir)
                run_record["sample"] = "O"
                run_record["status"] = "running"
                run_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_RUNNING
                existing_records_by_run[str(run_number)] = run_record.copy()
                _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
                _write_workflow_progress(
                    working_dir=working_dir,
                    n_runs=len(planned_runs),
                    records_by_run=existing_records_by_run,
                    status="running",
                    message=f"Completed sample for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
                )

            run_record["status"] = "success"
            run_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_RUNNING
            run_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            existing_records_by_run[str(run_number)] = run_record.copy()
            _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
            _write_workflow_progress(
                working_dir=working_dir,
                n_runs=len(planned_runs),
                records_by_run=existing_records_by_run,
                status="running" if idx < len(planned_runs) - 1 else "completed",
                message=f"Finished run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
            )

        except Exception as exc:
            run_record["status"] = "failed"
            run_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_RUNNING
            run_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            run_record["error"] = str(exc)
            existing_records_by_run[str(run_number)] = run_record.copy()
            _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
            _write_workflow_progress(
                working_dir=working_dir,
                n_runs=len(planned_runs),
                records_by_run=existing_records_by_run,
                status="failed" if not continue_on_error else "running",
                message=f"Run {idx + 1}/{len(planned_runs)} (run_{run_number}) failed during workflow execution.",
                error=str(exc),
            )
            if not continue_on_error:
                break

    latest_records = list(existing_records_by_run.values())
    final_status = "completed"
    final_message = f"Workflow finished: {len(planned_runs)} planned run(s) processed."
    if any(r.get("status") == "failed" for r in latest_records):
        final_status = "completed"
        final_message = "Workflow finished with one or more failed runs."

    for run_key in list(existing_records_by_run.keys()):
        updated_record = existing_records_by_run[run_key].copy()
        updated_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_FINISHED
        existing_records_by_run[run_key] = updated_record
    _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
    latest_records = list(existing_records_by_run.values())

    _write_workflow_progress(
        working_dir=working_dir,
        n_runs=len(planned_runs),
        records_by_run=existing_records_by_run,
        status=final_status,
        message=final_message,
    )

    return {
        "status_path": status_path,
        "progress_path": os.path.join(working_dir, "workflow_progress.json"),
        "log_path": str(resolve_workflow_log_path(working_dir)),
        "n_runs": len(planned_runs),
        "n_success": sum(1 for r in latest_records if r.get("status") == "success"),
        "n_failed": sum(1 for r in latest_records if r.get("status") == "failed"),
        "already_running": False,
    }


def analyze_simulation_runs(
    working_dir: str | None = None,
    continue_on_error: bool = True,
    extra_order_params: list | None = None,
):
    """
    Analyze simulation results for all planned runs in working_dir.

    Reads simulation_plan.json to find run directories, skips runs where
    the analyze step is already marked complete, and updates workflow_status.csv
    and workflow_progress.json to track progress.

    Intended to be called after execute_simulation_workflow has completed the
    initialize, compress, and sample steps.
    """
    if not working_dir:
        raise ValueError("working_dir must be provided.")

    append_workflow_log(
        working_dir,
        f"analyze_simulation_runs started with continue_on_error={continue_on_error}",
        source="workflow",
    )

    simulation_plan_path = os.path.join(working_dir, "simulation_plan.json")
    if not os.path.exists(simulation_plan_path):
        raise FileNotFoundError(f"Simulation plan file not found: {simulation_plan_path}")

    with open(simulation_plan_path, "r") as f:
        planned_runs = json.load(f)

    if not isinstance(planned_runs, list) or len(planned_runs) == 0:
        raise ValueError("simulation_plan.json must contain a non-empty list of simulation runs.")

    status_path = os.path.join(working_dir, "workflow_status.csv")
    workflow_config = get_workflow_config()
    status_fieldnames = workflow_config.get("status_fieldnames")
    if not isinstance(status_fieldnames, list) or len(status_fieldnames) == 0:
        raise ValueError("workflow.status_fieldnames must be configured as a non-empty list in colpack_config.json.")
    status_fieldnames = list(status_fieldnames)
    if EXECUTION_STATE_FIELD not in status_fieldnames:
        status_fieldnames.append(EXECUTION_STATE_FIELD)

    # Load existing status records.
    existing_records_by_run = {}
    if os.path.exists(status_path) and os.path.getsize(status_path) > 0:
        with open(status_path, "r", newline="") as status_file:
            reader = csv.DictReader(status_file)
            for row in reader:
                if not row:
                    continue
                run_number_key = str(row.get("run_number", ""))
                row[EXECUTION_STATE_FIELD] = str(row.get(EXECUTION_STATE_FIELD, "")).strip() or EXECUTION_STATE_FINISHED
                existing_records_by_run[run_number_key] = row
    else:
        _initialize_status_csv(status_path, status_fieldnames)

    from colpack.analyze import analyze_main

    _write_workflow_progress(
        working_dir=working_dir,
        n_runs=len(planned_runs),
        records_by_run=existing_records_by_run,
        status="running",
        message=f"analyze_simulation_runs: loaded {len(planned_runs)} planned run(s).",
    )

    for idx, run in enumerate(planned_runs):
        run_number = run.get("run_number", idx)
        run_dir = run.get("run_dir")
        if not run_dir:
            run_dir = os.path.join(working_dir, f"run_{run_number}")

        run_record = existing_records_by_run.get(str(run_number))
        if run_record is None:
            run_record = _build_run_status_record(run, run_number, run_dir)
        else:
            run_record = dict(run_record)

        # Skip runs already analyzed.
        if run_record.get("analyze") == "O":
            continue

        run_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_RUNNING
        existing_records_by_run[str(run_number)] = run_record.copy()
        _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
        _write_workflow_progress(
            working_dir=working_dir,
            n_runs=len(planned_runs),
            records_by_run=existing_records_by_run,
            status="running",
            message=f"Running analyze for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
        )

        try:
            analyze_main(run_dir=run_dir, extra_order_params=extra_order_params)
            run_record["analyze"] = "O"
            run_record["status"] = "success"
            run_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            existing_records_by_run[str(run_number)] = run_record.copy()
            _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
            _write_workflow_progress(
                working_dir=working_dir,
                n_runs=len(planned_runs),
                records_by_run=existing_records_by_run,
                status="running",
                message=f"Completed analyze for run {idx + 1}/{len(planned_runs)} (run_{run_number}).",
            )

        except Exception as exc:
            run_record["status"] = "failed"
            run_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            run_record["error"] = str(exc)
            existing_records_by_run[str(run_number)] = run_record.copy()
            _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
            _write_workflow_progress(
                working_dir=working_dir,
                n_runs=len(planned_runs),
                records_by_run=existing_records_by_run,
                status="failed" if not continue_on_error else "running",
                message=f"Run {idx + 1}/{len(planned_runs)} (run_{run_number}) failed during analyze.",
                error=str(exc),
            )
            if not continue_on_error:
                break

    latest_records = list(existing_records_by_run.values())
    final_status = "completed"
    final_message = f"analyze_simulation_runs finished: {len(planned_runs)} planned run(s) processed."
    if any(r.get("status") == "failed" for r in latest_records):
        final_message = "analyze_simulation_runs finished with one or more failed runs."

    for run_key in list(existing_records_by_run.keys()):
        updated_record = existing_records_by_run[run_key].copy()
        updated_record[EXECUTION_STATE_FIELD] = EXECUTION_STATE_FINISHED
        existing_records_by_run[run_key] = updated_record
    _write_status_snapshot(status_path, status_fieldnames, existing_records_by_run)
    latest_records = list(existing_records_by_run.values())

    _write_workflow_progress(
        working_dir=working_dir,
        n_runs=len(planned_runs),
        records_by_run=existing_records_by_run,
        status=final_status,
        message=final_message,
    )

    return {
        "status_path": status_path,
        "progress_path": os.path.join(working_dir, "workflow_progress.json"),
        "log_path": str(resolve_workflow_log_path(working_dir)),
        "n_runs": len(planned_runs),
        "n_success": sum(1 for r in latest_records if r.get("status") == "success"),
        "n_failed": sum(1 for r in latest_records if r.get("status") == "failed"),
    }
