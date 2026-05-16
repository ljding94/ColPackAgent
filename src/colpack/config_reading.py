import copy
import json
from functools import lru_cache
from pathlib import Path


_MIXTURE_COMPATIBILITY_RULES = {
    2: [
        {
            "incompatible_shape_groups": [
                ["ellipse"],
                ["triangle", "square", "rectangle", "capsule"],
            ],
            "reason": (
                "2D ellipses use the HOOMD-blue Ellipsoid HPMC integrator, "
                "while triangles, squares, rectangles, and capsules use "
                "ConvexSpheropolygon; no single HPMC integrator covers both."
            ),
            "agent_action": (
                "Ask the user to remove one incompatible group or substitute a "
                "compatible shape, such as using disk instead of ellipse."
            ),
        }
    ],
    3: [
        {
            "incompatible_shape_groups": [
                ["ellipsoid"],
                ["cube", "octahedron", "tetrahedron", "capsule"],
            ],
            "reason": (
                "3D ellipsoids use the HOOMD-blue Ellipsoid HPMC integrator, "
                "while cubes, octahedra, tetrahedra, and capsules use "
                "ConvexSpheropolyhedron; no single HPMC integrator covers both."
            ),
            "agent_action": (
                "Ask the user to remove one incompatible group or substitute a "
                "compatible shape, such as using sphere instead of ellipsoid."
            ),
        }
    ],
}


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


def get_mixture_compatibility_rules() -> dict[str, list[dict]]:
    rules: dict[str, list[dict]] = {}
    for dimension, entries in _MIXTURE_COMPATIBILITY_RULES.items():
        rules[f"{dimension}d"] = copy.deepcopy(entries)
    return rules


def validate_shape_mixture_compatibility(dimension: int, shapes: list[str]) -> None:
    canonical_shapes = {canonicalize_shape(dimension, shape) for shape in shapes}
    for rule in _MIXTURE_COMPATIBILITY_RULES.get(int(dimension), []):
        groups = [set(group) for group in rule["incompatible_shape_groups"]]
        if all(canonical_shapes & group for group in groups):
            readable_groups = [
                "{" + ", ".join(sorted(canonical_shapes & group)) + "}"
                for group in groups
            ]
            raise ValueError(
                "Incompatible HPMC shape mixture for "
                f"{dimension}D: {' cannot mix with '.join(readable_groups)}. "
                f"{rule['reason']}"
            )


def get_shape_defaults(dimension: int, shape: str) -> dict:
    canonical_shape = canonicalize_shape(dimension, shape)
    shape_parameters = _get_dimension_block(dimension).get("shape_parameters", {})
    defaults = shape_parameters.get(canonical_shape, {}).get("defaults")
    if defaults is None:
        raise ValueError(
            f"No default shape parameters configured for shape '{canonical_shape}' in dimension {dimension}."
        )
    return dict(defaults)
