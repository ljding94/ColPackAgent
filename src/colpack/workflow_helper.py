import copy
import csv
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from colpack.config_reading import load_config, get_allowed_shapes, canonicalize_shape, get_shape_defaults
from colpack.workflow_logging import append_workflow_log


STEP_SEQUENCE = ["initialize", "compress", "sample", "analyze"]


def _find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).resolve()
    if current.is_file():
        current = current.parent

    while True:
        if (current / "environment.yml").exists() or (current / "src" / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (environment.yml or src/pyproject.toml not found).")
        current = current.parent


def resolve_working_dir_from_setup(
    dimension: int,
    ensemble: str,
    particle_shape_list: list[str] | tuple[str, ...],
) -> str:
    """Derive the canonical workflow directory from setup inputs."""

    if dimension not in (2, 3):
        raise ValueError("dimension must be 2 or 3.")

    normalized_ensemble = str(ensemble).strip().upper()
    if normalized_ensemble not in {"NVT", "NPT"}:
        raise ValueError("ensemble must be either 'NVT' or 'NPT'.")

    if not isinstance(particle_shape_list, (list, tuple)) or len(particle_shape_list) == 0:
        raise ValueError("particle_shape_list must be a non-empty list.")

    allowed_shapes = get_allowed_shapes(dimension)
    normalized_shapes: list[str] = []
    for item in particle_shape_list:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Each entry in particle_shape_list must be a non-empty string.")

        shape = canonicalize_shape(dimension, item)
        if shape not in allowed_shapes:
            allowed_text = ", ".join(sorted(allowed_shapes))
            raise ValueError(f"Invalid shape '{shape}' for dimension {dimension}. Allowed shapes: {allowed_text}.")
        normalized_shapes.append(shape)

    project_root = _find_project_root()
    shape_slug = "_".join(normalized_shapes)
    base_path = project_root / "data" / f"{dimension}d_{normalized_ensemble.lower()}_{shape_slug}"
    candidate = base_path
    suffix = 2
    while candidate.exists():
        candidate = base_path.with_name(f"{base_path.name}_v{suffix}")
        suffix += 1

    return str(candidate.resolve())


def _set_by_path(data: dict, path: str, value):
    """Set nested dict/list value by dot-separated path like 'a.b.0.c'."""
    parts = str(path).split(".")
    current = data
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1

        if isinstance(current, list):
            idx = int(part)
            if idx < 0 or idx >= len(current):
                raise ValueError(f"List index '{idx}' out of range for path '{path}'.")
            if is_last:
                current[idx] = value
                return
            current = current[idx]
            continue

        if not isinstance(current, dict):
            raise ValueError(f"Invalid intermediate value while setting path '{path}'.")

        if is_last:
            current[part] = value
            return

        if part not in current:
            # Create missing intermediate containers as dict by default.
            current[part] = {}
        current = current[part]


def _get_by_path(data: dict, path: str):
    """Get nested dict/list value by dot-separated path. Returns (exists, value)."""
    parts = str(path).split(".")
    current = data

    for part in parts:
        if isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                return False, None
            if idx < 0 or idx >= len(current):
                return False, None
            current = current[idx]
            continue

        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
            continue

        return False, None

    return True, current


def _collect_simulation_problem_paths(value, prefix: str = "") -> list[str]:
    """Collect leaf dot paths from simulation_problem.json for planning validation."""
    paths: list[str] = []

    if isinstance(value, dict):
        for key, nested_value in value.items():
            current_path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(nested_value, (dict, list)):
                paths.extend(_collect_simulation_problem_paths(nested_value, current_path))
            else:
                paths.append(current_path)
        return paths

    if isinstance(value, list):
        for index, nested_value in enumerate(value):
            current_path = f"{prefix}.{index}" if prefix else str(index)
            if isinstance(nested_value, (dict, list)):
                paths.extend(_collect_simulation_problem_paths(nested_value, current_path))
            else:
                paths.append(current_path)

    return paths


def _is_immutable_planning_path(parameter_path: str) -> bool:
    """Identify setup-time identity fields that planning must not override."""
    if parameter_path in {"dimension", "total_particle_number", "ensemble", "working_dir"}:
        return True

    parts = parameter_path.split(".")
    if len(parts) == 3 and parts[0] == "particle_specs" and parts[1].isdigit() and parts[2] in {"shape", "type"}:
        return True

    return False


def _format_invalid_planning_parameter_message(parameter_path: str, allowed_paths: set[str]) -> str:
    """Build a helpful error for invalid planning parameter paths."""
    leaf_name = parameter_path.split(".")[-1]
    matching_paths = sorted(path for path in allowed_paths if path.split(".")[-1] == leaf_name)

    if matching_paths:
        if any(path.startswith("particle_specs.") for path in matching_paths):
            return (
                f"Invalid planning parameter '{parameter_path}'. Planning only accepts parameter paths that already exist "
                f"in simulation_problem.json. Shape-specific parameters must stay under 'particle_specs.N.*'. "
                f"Use one of these existing paths instead: {', '.join(matching_paths)}."
            )

        return (
            f"Invalid planning parameter '{parameter_path}'. Planning only accepts parameter paths that already exist "
            f"in simulation_problem.json. Use one of these existing paths instead: {', '.join(matching_paths)}."
        )

    allowed_examples = ", ".join(sorted(path for path in allowed_paths if path.count(".") >= 1)[:8])
    if not allowed_examples:
        allowed_examples = ", ".join(sorted(list(allowed_paths))[:8])

    return (
        f"Invalid planning parameter '{parameter_path}'. Planning only accepts parameter paths that already exist "
        f"in simulation_problem.json. Read simulation_problem.json first and use existing paths such as: {allowed_examples}."
    )


def _validate_planning_parameter_paths(simulation_problem: dict, parameters: dict, label: str) -> None:
    """Reject planning parameters that are not present in simulation_problem.json."""
    if not isinstance(parameters, dict):
        raise TypeError(f"{label} must be a dictionary.")

    allowed_paths = set(_collect_simulation_problem_paths(simulation_problem))
    for raw_parameter_path in parameters.keys():
        if not isinstance(raw_parameter_path, str) or not raw_parameter_path.strip():
            raise ValueError(f"{label} keys must be non-empty strings.")

        parameter_path = raw_parameter_path.strip()
        if parameter_path not in allowed_paths:
            raise ValueError(_format_invalid_planning_parameter_message(parameter_path, allowed_paths))


def _build_baseline_with_defaults(baseline_parameters: dict) -> dict:
    """Fill missing baseline fields using defaults from colpack config."""
    if not isinstance(baseline_parameters, dict):
        raise TypeError("baseline_parameters must be a dictionary.")

    base = copy.deepcopy(baseline_parameters)
    cfg = load_config()
    workflow_cfg = cfg.get("workflow", {})

    placeholder = workflow_cfg.get("placeholder", "Nan")
    particle_required_fields = workflow_cfg.get("particle_required_fields", ["relative_volume_fraction"])
    relative_volume_fraction_first_particle = workflow_cfg.get("relative_volume_fraction_first_particle", 1)
    relative_volume_fraction_other_particles = workflow_cfg.get("relative_volume_fraction_other_particles", placeholder)
    common_system_fields = workflow_cfg.get("common_system_fields", {})
    ensemble_requirements = workflow_cfg.get("ensemble_requirements", {})

    if "dimension" not in base:
        raise ValueError("baseline_parameters must include 'dimension'.")
    if "ensemble" not in base:
        raise ValueError("baseline_parameters must include 'ensemble'.")
    if "total_particle_number" not in base or base.get("total_particle_number") == placeholder:
        raise ValueError("baseline_parameters must include 'total_particle_number'.")
    if "particle_specs" not in base:
        raise ValueError("baseline_parameters must include 'particle_specs'.")

    base["dimension"] = int(base["dimension"])
    if base["dimension"] not in (2, 3):
        raise ValueError("'dimension' must be 2 or 3.")

    base["ensemble"] = str(base["ensemble"]).strip().upper()
    if base["ensemble"] not in {"NVT", "NPT"}:
        raise ValueError("'ensemble' must be either 'NVT' or 'NPT'.")

    if not isinstance(base["particle_specs"], list) or len(base["particle_specs"]) == 0:
        raise ValueError("'particle_specs' must be a non-empty list.")

    allowed_shapes = get_allowed_shapes(base["dimension"])
    for idx, spec in enumerate(base["particle_specs"]):
        if not isinstance(spec, dict):
            raise ValueError("Each entry in 'particle_specs' must be a dictionary.")

        if "shape" not in spec:
            raise ValueError(f"particle_specs[{idx}] is missing 'shape'.")
        shape = canonicalize_shape(base["dimension"], spec["shape"])
        if shape not in allowed_shapes:
            allowed_text = ", ".join(sorted(allowed_shapes))
            raise ValueError(f"Invalid shape '{shape}' for dimension {base['dimension']}. Allowed shapes: {allowed_text}.")

        spec["shape"] = shape
        spec.setdefault("type", idx)

        # Fill required workflow particle fields.
        for field_name in particle_required_fields:
            current_value = spec.get(field_name)
            if field_name not in spec or current_value == placeholder:
                if field_name == "relative_volume_fraction" and idx == 0:
                    spec[field_name] = relative_volume_fraction_first_particle
                elif field_name == "relative_volume_fraction":
                    spec[field_name] = relative_volume_fraction_other_particles
                else:
                    spec[field_name] = placeholder

        # Fill shape-specific defaults when missing.
        defaults = get_shape_defaults(base["dimension"], shape)
        for key, default_value in defaults.items():
            current_value = spec.get(key)
            if key not in spec or current_value == placeholder:
                spec[key] = default_value

    # Fill common system defaults.
    for key, value in common_system_fields.items():
        current_value = base.get(key)
        if key not in base or current_value == placeholder:
            base[key] = value

    base["total_particle_number"] = int(base["total_particle_number"])
    if base["total_particle_number"] <= 0:
        raise ValueError("'total_particle_number' must be a positive integer.")

    # Fill ensemble-level defaults.
    system_fields = ensemble_requirements.get(base["ensemble"], {}).get("system_fields", {})
    for key, value in system_fields.items():
        current_value = base.get(key)
        if key not in base or current_value == placeholder:
            base[key] = value

    return base


def _load_and_extend_simulation_plan(
    *,
    planning_path: str,
    baseline_from_file: dict,
    tunable_parameters: dict,
    working_dir: str,
) -> tuple[list[dict], list[dict]]:
    """Load existing planned runs, append new one-parameter sweep runs, and return both lists."""
    existing_runs: list[dict] = []
    if os.path.exists(planning_path):
        with open(planning_path, "r") as f:
            loaded = json.load(f)
        if isinstance(loaded, list):
            existing_runs = loaded
        else:
            raise ValueError("Existing simulation_plan.json must contain a list of simulation runs.")

    def _normalize_for_key(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    parameter_paths = [str(path) for path in tunable_parameters.keys()]

    def _make_tunable_key(run_dict: dict):
        key_parts = []
        for path in parameter_paths:
            exists, value = _get_by_path(run_dict, path)
            key_parts.append((path, exists, _normalize_for_key(value) if exists else ""))
        return tuple(key_parts)

    existing_tunable_keys = set()
    for existing_run in existing_runs:
        if isinstance(existing_run, dict):
            existing_tunable_keys.add(_make_tunable_key(existing_run))

    existing_run_numbers = []
    for index, run in enumerate(existing_runs):
        if not isinstance(run, dict):
            continue
        raw = run.get("run_number", index)
        try:
            existing_run_numbers.append(int(raw))
        except (TypeError, ValueError):
            continue

    simulation_runs: list[dict] = []
    run_number = (max(existing_run_numbers) + 1) if existing_run_numbers else 0
    for parameter_path, values in tunable_parameters.items():
        if not isinstance(values, list) or len(values) == 0:
            raise ValueError(f"Tunable parameter '{parameter_path}' must map to a non-empty list of values.")

        for value in values:
            run = copy.deepcopy(baseline_from_file)
            _set_by_path(run, parameter_path, value)

            tunable_key = _make_tunable_key(run)
            if tunable_key in existing_tunable_keys:
                continue

            run_folder = os.path.join(working_dir, f"run_{run_number}")
            os.makedirs(run_folder, exist_ok=True)

            run["run_number"] = run_number
            run["run_dir"] = run_folder

            run_config_path = os.path.join(run_folder, "simulation_config.json")
            with open(run_config_path, "w") as run_config_file:
                json.dump(run, run_config_file, indent=4)

            simulation_runs.append(run)
            existing_tunable_keys.add(tunable_key)
            run_number += 1

    return existing_runs, existing_runs + simulation_runs


def _append_status(status_path: str, status_records: list, status_fieldnames: list, record: dict):
    """Append one status record to in-memory cache and CSV file."""
    status_records.append(record)
    with open(status_path, "a", newline="") as status_file:
        writer = csv.DictWriter(status_file, fieldnames=status_fieldnames)
        writer.writerow(record)


def _write_status_snapshot(status_path: str, status_fieldnames: list, records_by_run: dict[str, dict]):
    """Rewrite status CSV with one latest row per run_number."""
    rows = list(records_by_run.values())

    def _sort_key(row: dict):
        raw = row.get("run_number", "")
        try:
            return (0, int(raw))
        except Exception:
            return (1, str(raw))

    rows.sort(key=_sort_key)

    with open(status_path, "w", newline="") as status_file:
        writer = csv.DictWriter(status_file, fieldnames=status_fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _initialize_status_csv(status_path: str, status_fieldnames: list):
    """Create or overwrite status CSV with header row."""
    with open(status_path, "w", newline="") as status_file:
        writer = csv.DictWriter(status_file, fieldnames=status_fieldnames)
        writer.writeheader()


def _resolve_total_particle_number(run: dict):
    """Resolve total particle number from explicit field or sum of particle specs."""
    total = run.get("total_particle_number")
    if total is not None:
        try:
            return int(total)
        except Exception:
            pass

    specs = run.get("particle_specs", [])
    if not isinstance(specs, list):
        return ""

    count = 0
    has_any = False
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        number = spec.get("number")
        if number is None:
            continue
        try:
            count += int(number)
            has_any = True
        except Exception:
            continue

    return count if has_any else ""


def _build_run_status_record(run: dict, run_number, run_output_dir: str) -> dict:
    """Build a default status row for one run before execution starts."""
    return {
        "run_number": run_number,
        "dimension": run.get("dimension", ""),
        "total_particle_number": _resolve_total_particle_number(run),
        "ensemble": run.get("ensemble", ""),
        "initialize": "X",
        "compress": "X",
        "sample": "X",
        "analyze": "X",
        "status": "failed",
        "execution_state": "finished",
        "output_dir": run_output_dir,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "error": "",
    }


def _count_workflow_outcomes(records_by_run: dict[str, dict]) -> tuple[int, int, int]:
    rows = list(records_by_run.values())
    n_success = sum(1 for row in rows if row.get("status") == "success")
    n_failed = sum(1 for row in rows if row.get("status") == "failed")
    completed_steps = sum(1 for row in rows for step in STEP_SEQUENCE if row.get(step) == "O")
    return n_success, n_failed, completed_steps


def _write_workflow_progress(
    working_dir: str,
    n_runs: int,
    records_by_run: dict[str, dict],
    *,
    status: str,
    message: str,
    error: str = "",
    write_log: bool = True,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    n_success, n_failed, completed_steps = _count_workflow_outcomes(records_by_run)
    total_steps = max(n_runs * len(STEP_SEQUENCE), 1)
    progress_payload = {
        "working_dir": working_dir,
        "n_runs": n_runs,
        "n_success": n_success,
        "n_failed": n_failed,
        "completed_steps": completed_steps,
        "total_steps": total_steps,
        "progress_percent": round(completed_steps / total_steps * 100.0, 1),
        "status": status,
        "message": message,
        "error": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    progress_path = os.path.join(working_dir, "workflow_progress.json")
    with open(progress_path, "w") as f:
        json.dump(progress_payload, f, indent=4)

    if write_log:
        log_message = message.strip() if isinstance(message, str) else ""
        if log_message:
            append_workflow_log(working_dir, log_message, source="workflow")

    # Best-effort callback hook for external progress consumers (e.g., MCP context).
    if progress_callback is not None:
        try:
            progress_callback(progress_payload)
        except Exception:
            pass

    return progress_payload
