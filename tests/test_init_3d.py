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
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.01,
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
    assert summary["number_density"] == 0.01


def main():

    test_run(
        particle_specs=[
            {"shape": "sphere", "number": 100, "diameter": 1.0},
        ],
        output_subdir="3d_sphere",
        seed=42,
    )
    print("test_create_initial_config_3d_sphere: OK\n")

    test_run(
        particle_specs=[
            {"shape": "sphere", "number": 40, "diameter": 1.0},
            {"shape": "sphere", "number": 20, "diameter": 0.5},
        ],
        output_subdir="3d_sphere_sphere",
        seed=42,
    )
    print("test_create_initial_config_3d_sphere_sphere: OK\n")

    # test_create_initial_config_3d_ellipsoid
    test_run(
        particle_specs=[
            {"shape": "ellipsoid", "number": 30, "a": 1.0, "b": 0.8, "c": 0.6},
            {"shape": "ellipsoid", "number": 20, "a": 1.0, "b": 0.5, "c": 0.4},
        ],
        output_subdir="3d_ellipsoid",
        seed=123,
    )
    print("test_create_initial_config_3d_ellipsoid: OK\n")

    test_run(
        particle_specs=[
            {"shape": "capsule", "number": 100, "length": 2.0, "diameter": 1.0},
        ],
        output_subdir="3d_capsule",
        seed=303,
    )
    print("test_create_initial_config_3d_capsule: OK\n")

    # test_create_initial_config_3d_sphere_capsule
    test_run(
        particle_specs=[
            {"shape": "sphere", "number": 30, "diameter": 1.0},
            {"shape": "capsule", "number": 20, "length": 2.0, "diameter": 0.6},
        ],
        output_subdir="3d_sphere_capsule",
        seed=303,
    )
    print("test_create_initial_config_3d_sphere_capsule: OK\n")

    # test_create_initial_config_3d_sphere_tetrahedron
    test_run(
        particle_specs=[
            {"shape": "sphere", "number": 30, "diameter": 1.0},
            {"shape": "tetrahedron", "number": 20, "side": 1.2},
        ],
        output_subdir="3d_sphere_tetrahedron",
        seed=42,
    )
    print("test_create_initial_config_3d_sphere_tetrahedron: OK\n")

    # test_create_initial_config_3d_sphere_cube
    test_run(
        particle_specs=[
            {"shape": "sphere", "number": 30, "diameter": 1.0},
            {"shape": "cube", "number": 20, "side": 1.0},
        ],
        output_subdir="3d_sphere_cube",
        seed=202,
    )
    print("test_create_initial_config_3d_sphere_cube: OK\n")

    # test_create_initial_config_3d_sphere_octahedron
    test_run(
        particle_specs=[
            {"shape": "sphere", "number": 30, "diameter": 1.0},
            {"shape": "octahedron", "number": 20, "side": 1.2},
        ],
        output_subdir="3d_sphere_octahedron",
        seed=101,
    )
    print("test_create_initial_config_3d_sphere_octahedron: OK\n")

    # test_create_initial_config_3d_multi_shapes
    test_run(
        particle_specs=[
            {"shape": "sphere", "number": 10, "diameter": 1.0},
            {"shape": "capsule", "number": 10, "length": 2.0, "diameter": 0.6},
            {"shape": "tetrahedron", "number": 10, "side": 1.2},
            {"shape": "cube", "number": 10, "side": 1.0},
        ],
        output_subdir="3d_multi_shapes",
        seed=555,
    )
    print("test_create_initial_config_3d_multi_shapes: OK\n")


if __name__ == "__main__":
    main()
