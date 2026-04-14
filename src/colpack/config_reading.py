import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_config() -> dict:
    settings_path = Path(__file__).with_name("colpack_config.json")
    with settings_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_workflow_config() -> dict:
    return dict(load_config().get("workflow", {}))


def get_initialize_config() -> dict:
    return dict(load_config().get("workflow", {}).get("initialize_defaults", {}))


def get_analyze_config() -> dict:
    return dict(load_config().get("analysis", {}))


def _get_dimension_block(dimension: int) -> dict:
    dim_key = str(int(dimension))
    settings = load_config()
    dim_block = settings.get("dimensions", {}).get(dim_key)
    if dim_block is None:
        raise ValueError(f"Unsupported dimension '{dimension}'.")
    return dim_block


def get_allowed_shapes(dimension: int) -> set[str]:
    dim_block = _get_dimension_block(dimension)
    return set(dim_block.get("allowed_shapes", []))


def canonicalize_shape(dimension: int, shape: str) -> str:
    if not isinstance(shape, str) or not shape.strip():
        raise ValueError("shape must be a non-empty string.")

    normalized_shape = shape.strip().lower()
    aliases = _get_dimension_block(dimension).get("aliases", {})
    return aliases.get(normalized_shape, normalized_shape)


def get_shape_defaults(dimension: int, shape: str) -> dict:
    canonical_shape = canonicalize_shape(dimension, shape)
    shape_parameters = _get_dimension_block(dimension).get("shape_parameters", {})
    defaults = shape_parameters.get(canonical_shape, {}).get("defaults")
    if defaults is None:
        raise ValueError(
            f"No default shape parameters configured for shape '{canonical_shape}' in dimension {dimension}."
        )
    return dict(defaults)
