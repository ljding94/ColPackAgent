from pathlib import Path
from colpack.init import create_initial_config
from colpack.visualize_ovito import visualize_gsd


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def test_run(particle_specs, output_subdir, seed):
    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=seed,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=True,
        debug=True,
    )

    assert summary["total_particles"] == sum(spec["number"] for spec in particle_specs)
    assert summary["number_density"] == 0.05


def main():
    # test_create_initial_config_2d_disk
    test_run(
        particle_specs=[
            {"shape": "disk", "number": 100, "diameter": 1.0},
        ],
        output_subdir="2d_disk",
        seed=42,
    )
    print("test_create_initial_config_2d_disk: OK\n")

    # test_create_initial_config_2d_disk_disk
    test_run(
        particle_specs=[
            {"shape": "disk", "number": 30, "diameter": 2.0},
            {"shape": "disk", "number": 20},
        ],
        output_subdir="2d_disk_disk",
        seed=42,
    )
    print("test_create_initial_config_2d_disk_disk: OK\n")

    # test_create_initial_config_2d_ellipse_ellipse
    test_run(
        particle_specs=[
            {"shape": "ellipse", "number": 20, "a": 1.0, "b": 0.8},
            {"shape": "ellipse", "number": 10, "a": 1.0, "b": 0.4},
        ],
        output_subdir="2d_ellipse_ellipse",
        seed=42,
    )
    print("test_create_initial_config_2d_ellipse_ellipse: OK\n")

    # test_create_initial_config_2d_disk_ellipsoid
    test_run(
        particle_specs=[
            {"shape": "disk", "number": 20, "diameter": 1.2},
            {"shape": "ellipse", "number": 10, "a": 1.0, "b": 0.6},
        ],
        output_subdir="2d_disk_ellipse",
        seed=123,
    )
    print("test_create_initial_config_2d_disk_ellipsoid: OK\n")

    # test_create_initial_config_2d_disk_rectangle
    test_run(
        particle_specs=[
            {"shape": "disk", "number": 20, "diameter": 1.0},
            {"shape": "rectangle", "number": 10, "length": 2.0, "width": 1.0},
        ],
        output_subdir="2d_disk_rectangle",
        seed=321,
    )
    print("test_create_initial_config_2d_disk_rectangle: OK\n")


    # test_create_initial_config_2d_capsule
    test_run(
        particle_specs=[
            {"shape": "capsule", "number": 50, "length": 2.0, "diameter": 1.0},
        ],
        output_subdir="2d_capsule",
        seed=456,
    )

    # test_create_initial_config_2d_disk_capsule
    test_run(
        particle_specs=[
            {"shape": "disk", "number": 10, "diameter": 1.0},
            {"shape": "capsule", "number": 20, "length": 2.0, "diameter": 0.6},
        ],
        output_subdir="2d_disk_capsule",
        seed=456,
    )
    print("test_create_initial_config_2d_disk_capsule: OK\n")

    # test_create_initial_config_2d_disk_triangle
    test_run(
        particle_specs=[
            {"shape": "disk", "number": 10, "diameter": 1.0},
            {"shape": "triangle", "number": 20, "side": 1.5},
        ],
        output_subdir="2d_disk_triangle",
        seed=654,
    )
    print("test_create_initial_config_2d_disk_triangle: OK\n")

    # test_create_initial_config_2d_multi_shapes
    test_run(
        particle_specs=[
            {"shape": "disk", "number": 10, "diameter": 1.5},
            {"shape": "rectangle", "number": 10, "length": 2.0, "width": 1.0},
            {"shape": "capsule", "number": 10, "length": 2.0, "diameter": 0.6},
            {"shape": "triangle", "number": 10, "side": 1.5},
        ],
        output_subdir="2d_multi_shapes",
        seed=789,
    )
    print("test_create_initial_config_2d_multi_shapes: OK\n")


if __name__ == "__main__":
    main()

