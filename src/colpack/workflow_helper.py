import copy
import csv
from datetime import datetime, timezone

from colpack.config_reading import load_config, get_allowed_shapes, canonicalize_shape, get_shape_defaults


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


def _append_status(status_path: str, status_records: list, status_fieldnames: list, record: dict):
    """Append one status record to in-memory cache and CSV file."""
    status_records.append(record)
    with open(status_path, "a", newline="") as status_file:
        writer = csv.DictWriter(status_file, fieldnames=status_fieldnames)
        writer.writerow(record)


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
        "output_dir": run_output_dir,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "error": "",
    }
