from pathlib import Path
from colpack.visualize_ovito import visualize_gsd
from colpack.init import create_initial_config
from colpack.compress import compress_system
from colpack.sample import sample_system as sample_system_core
from colpack.analyze import analyze_main

__all__ = [
    "initialize_system",
    "create_initial_config",
    "compress_system",
    "sample_system",
    "analyze_system",
    "analyze_main",
    "visualize_gsd",
]


def initialize_system(config_dict):
    """
    Initialize and compress a simulation system from a config dictionary.

    Workflow:
    1. Build an initial low-density non-overlapping configuration.
    2. Compress to the desired target number density.
    3. Return summaries and output paths for both stages.

        Required config keys:
        - dimension: 2 or 3
        - particle_specs: list[dict]
        - target_number_density (alias: target_density, n, n_target): float > 0

        particle_specs schema (what the agent should output)
        -----------------------------------------------------
        particle_specs must be a non-empty list of particle component dictionaries.
        Each dictionary must contain:

        - shape (or type): str
        - number (or n or count): int > 0

        Additional shape parameters by shape type:

        2D shapes
        - disk/circle/sphere:
            keys: diameter (or radius or sigma)
            defaults: diameter=1.0
        - ellipse:
            keys: a, b, optional c
            defaults: a=1.0, b=0.5, c=0.25
        - triangle:
            keys: side (or length)
            defaults: side=1.0
        - square:
            keys: side (or length)
            defaults: side=1.0
        - rectangle:
            keys: length (or L), width (or W)
            defaults: length=2.0, width=1.0
        - capsule:
            keys: length, diameter
            defaults: length=2.0, diameter=0.5
        - polygon:
            keys: vertices, optional sweep_radius
            defaults: sweep_radius=0.0

        3D shapes
        - sphere:
            keys: diameter (or radius or sigma)
            defaults: diameter=1.0
        - ellipsoid:
            keys: a, b, c
            defaults: a=1.0, b=0.5, c=0.25
        - capsule:
            keys: length, diameter
            defaults: length=2.0, diameter=0.5
        - tetrahedron:
            keys: side
            defaults: side=1.0
        - cube:
            keys: side
            defaults: side=1.0
        - octahedron:
            keys: side
            defaults: side=1.0

        Agent generation guidelines:
        - Prefer explicit "shape" and "number" keys for consistency.
        - Keep all geometric values numeric and positive.
        - Use one dict per component species in the mixture.

        Example (2D):
        {
                "dimension": 2,
                "particle_specs": [
                        {"shape": "disk", "number": 300, "diameter": 1.0},
                        {"shape": "capsule", "number": 200, "length": 2.0, "diameter": 0.6},
                ],
            "target_number_density": 0.35,
            "initial_number_density": 0.03,
                "output_dir": "data/test/2d_disk_capsule",
                "seed": 42,
        }

        Example (3D):
        {
                "dimension": 3,
                "particle_specs": [
                        {"shape": "sphere", "number": 400, "diameter": 1.0},
                        {"shape": "ellipsoid", "number": 100, "a": 1.0, "b": 0.6, "c": 0.4},
                ],
                "target_density": 0.20,
                "initial_density": 0.01,
                "system_dir": "data/test/3d_sphere_ellipsoid",
                "seed": 7,
        }

    Optional config keys (with aliases):
            - initial_number_density (alias: initial_density, n0), default=min(0.05, 0.2 * target_number_density)
    - output_dir (alias: system_dir), default="data/run"
    - seed, default=0

            Notes for agent output:
            - For robust initialization, keep initial_number_density much smaller than target_number_density.
            - If initial_number_density is omitted, it is auto-chosen and forced to be < target.
    """
    if not isinstance(config_dict, dict):
        raise TypeError("config_dict must be a dictionary.")

    # Required fields
    if "dimension" not in config_dict:
        raise ValueError("Missing required config key: 'dimension'.")
    if "particle_specs" not in config_dict:
        raise ValueError("Missing required config key: 'particle_specs'.")

    target_number_density = config_dict.get(
        "target_number_density",
        config_dict.get("target_density", config_dict.get("n_target", config_dict.get("n"))),
    )
    if target_number_density is None:
        raise ValueError(
            "Missing required config key: 'target_number_density' (or 'target_density'/'n_target'/'n')."
        )
    target_number_density = float(target_number_density)
    if target_number_density <= 0:
        raise ValueError("'target_number_density' must be > 0.")

    dimension = int(config_dict["dimension"])
    if dimension not in (2, 3):
        raise ValueError("'dimension' must be either 2 or 3.")

    particle_specs = config_dict["particle_specs"]
    if not isinstance(particle_specs, list) or len(particle_specs) == 0:
        raise ValueError("'particle_specs' must be a non-empty list.")

    # Optional fields
    initial_density_raw = config_dict.get(
        "initial_number_density",
        config_dict.get("initial_density", config_dict.get("n0")),
    )
    if initial_density_raw is None:
        initial_number_density = min(0.05, 0.2 * target_number_density)
    else:
        initial_number_density = float(initial_density_raw)

    if initial_number_density <= 0:
        raise ValueError("'initial_number_density' must be > 0.")
    if initial_number_density >= target_number_density:
        raise ValueError(
            "'initial_number_density' must be smaller than 'target_number_density'."
        )

    output_dir = config_dict.get("output_dir", config_dict.get("system_dir", "data/run"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    seed = int(config_dict.get("seed", 0))

    init_summary = create_initial_config(
        dimension=dimension,
        particle_specs=particle_specs,
        initial_number_density=initial_number_density,
        output_dir=str(output_dir),
        seed=seed,
    )

    compress_summary = compress_system(
        target_number_density=target_number_density,
        system_dir=str(output_dir),
        seed=seed,
    )

    compressed_gsd_name = f"compressed_n{target_number_density:.3f}.gsd"
    compress_summary_name = f"compress_summary_n{target_number_density:.3f}.json"

    return {
        "summary": {
            "init": init_summary,
            "compress": compress_summary,
        },
        "density": {
            "initial_number_density": initial_number_density,
            "target_number_density": target_number_density,
        },
        "paths": {
            "system_dir": str(output_dir),
            "particle_list": str(output_dir / "particle_list.json"),
            "init_gsd": str(output_dir / "init.gsd"),
            "init_summary": str(output_dir / "init_summary.json"),
            "compressed_gsd": str(output_dir / compressed_gsd_name),
            "compress_summary": str(output_dir / compress_summary_name),
        },
    }


def sample_system(config_dict):
    """
    Run sampling (production MC) on a compressed system.

    This wrapper expects a system that has already been initialized and compressed,
    typically by `initialize_system(...)`.

    Required config keys:
    - sample_steps: int > 0

    System location / source (choose one):
    - Option A: provide `system_dir` (or `output_dir`) and `density`
    - Option B: provide `initialize_result` returned by `initialize_system`
      and this function will infer `system_dir` + target density

    Density keys (aliases):
    - density
    - number_density
    - target_number_density
    - target_density
    - n

    Optional:
    - seed: int, default=0

    Example:
    {
        "sample_steps": 300000,
        "system_dir": "data/test/2d_disk_capsule",
        "density": 0.4,
        "seed": 42,
    }
    """
    if not isinstance(config_dict, dict):
        raise TypeError("config_dict must be a dictionary.")

    if "sample_steps" not in config_dict:
        raise ValueError("Missing required config key: 'sample_steps'.")

    sample_steps = int(config_dict["sample_steps"])
    if sample_steps <= 0:
        raise ValueError("'sample_steps' must be > 0.")

    seed = int(config_dict.get("seed", 0))

    init_result = config_dict.get("initialize_result", config_dict.get("init_result"))

    # Resolve system directory
    system_dir = config_dict.get("system_dir", config_dict.get("output_dir"))
    if system_dir is None and isinstance(init_result, dict):
        system_dir = init_result.get("paths", {}).get("system_dir")

    if system_dir is None:
        raise ValueError(
            "Missing system location. Provide 'system_dir'/'output_dir' or 'initialize_result'."
        )

    system_dir = Path(system_dir)
    if not system_dir.exists():
        raise FileNotFoundError(f"System directory does not exist: {system_dir}")

    # Resolve density (required for initialize_system output naming)
    density = config_dict.get(
        "density",
        config_dict.get(
            "number_density",
            config_dict.get(
                "target_number_density",
                config_dict.get("target_density", config_dict.get("n")),
            ),
        ),
    )
    if density is None and isinstance(init_result, dict):
        density = init_result.get("density", {}).get("target_number_density")

    if density is None:
        raise ValueError(
            "Missing density. Provide 'density' (or alias) or pass 'initialize_result' with target density."
        )

    density = float(density)
    if density <= 0:
        raise ValueError("'density' must be > 0.")

    summary = sample_system_core(
        sample_steps=sample_steps,
        system_dir=str(system_dir),
        density=density,
        seed=seed,
    )

    density_tag = f"{density:.3f}"
    return {
        "summary": summary,
        "sampling": {
            "sample_steps": sample_steps,
            "density": density,
            "seed": seed,
        },
        "paths": {
            "system_dir": str(system_dir),
            "sample_trajectory": str(system_dir / f"sample_trajectory_n{density_tag}.gsd"),
            "sample_final": str(system_dir / f"sample_final_n{density_tag}.gsd"),
            "sample_summary": str(system_dir / f"sample_summary_n{density_tag}.json"),
        },
    }


def analyze_system(config_dict):
    """
    Analyze a sampled system and generate plots/results files.

    This wrapper expects sampling to have already been completed, typically by
    `sample_system(...)`.

    Required:
    - config_dict: dict

    System location / source (choose one):
    - Option A: provide `system_dir` (or `output_dir`) and `density`
    - Option B: provide `sample_result` returned by `sample_system`
    - Option C: provide `initialize_result` and explicit `density`

    Density keys (aliases):
    - density
    - number_density
    - target_number_density
    - target_density
    - n

    Example:
    {
        "system_dir": "data/test/2d_disk_capsule",
        "density": 0.4,
    }
    """
    if not isinstance(config_dict, dict):
        raise TypeError("config_dict must be a dictionary.")

    sample_result = config_dict.get("sample_result")
    init_result = config_dict.get("initialize_result", config_dict.get("init_result"))

    # Resolve system directory
    system_dir = config_dict.get("system_dir", config_dict.get("output_dir"))
    if system_dir is None and isinstance(sample_result, dict):
        system_dir = sample_result.get("paths", {}).get("system_dir")
    if system_dir is None and isinstance(init_result, dict):
        system_dir = init_result.get("paths", {}).get("system_dir")

    if system_dir is None:
        raise ValueError(
            "Missing system location. Provide 'system_dir'/'output_dir', or 'sample_result', or 'initialize_result'."
        )

    system_dir = Path(system_dir)
    if not system_dir.exists():
        raise FileNotFoundError(f"System directory does not exist: {system_dir}")

    # Resolve density
    density = config_dict.get(
        "density",
        config_dict.get(
            "number_density",
            config_dict.get(
                "target_number_density",
                config_dict.get("target_density", config_dict.get("n")),
            ),
        ),
    )

    if density is None and isinstance(sample_result, dict):
        density = sample_result.get("sampling", {}).get("density")

    if density is None and isinstance(init_result, dict):
        density = init_result.get("density", {}).get("target_number_density")

    if density is None:
        raise ValueError(
            "Missing density. Provide 'density' (or alias), or pass 'sample_result'/'initialize_result' that includes density."
        )

    density = float(density)
    if density <= 0:
        raise ValueError("'density' must be > 0.")

    analyze_main(system_dir=str(system_dir), density=density)

    density_tag = f"{density:.3f}"
    analysis_json = system_dir / f"analysis_results_n{density_tag}.json"

    order_plot_png = sorted(system_dir.glob(f"plot_order_n{density_tag}_*.png"))
    order_plot_pdf = sorted(system_dir.glob(f"plot_order_n{density_tag}_*.pdf"))
    rdf_png = system_dir / f"plot_rdf_n{density_tag}.png"
    rdf_pdf = system_dir / f"plot_rdf_n{density_tag}.pdf"

    return {
        "analysis": {
            "density": density,
            "analysis_results_exists": analysis_json.exists(),
        },
        "paths": {
            "system_dir": str(system_dir),
            "analysis_results": str(analysis_json),
            "plot_order_png": [str(p) for p in order_plot_png],
            "plot_order_pdf": [str(p) for p in order_plot_pdf],
            "plot_rdf_png": str(rdf_png),
            "plot_rdf_pdf": str(rdf_pdf),
        },
    }
