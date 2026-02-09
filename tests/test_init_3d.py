from pathlib import Path
from colpack.init import create_initial_config
from colpack.visualize_fresnel import visualize_gsd


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def test_create_initial_config_3d_sphere():
    particle_specs = [
        {"shape": "sphere", "number": 40, "diameter": 1.0},
        {"shape": "sphere", "number": 20, "diameter": 0.5},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_3d_sphere"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=42,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 60
    assert summary["number_density"] == 0.05


def test_create_initial_config_3d_ellipsoid():
    particle_specs = [
        {"shape": "ellipsoid", "number": 30, "a": 1.0, "b": 0.8, "c": 0.6},
        {"shape": "ellipsoid", "number": 20, "a": 1.0, "b": 0.5, "c": 0.4},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_3d_ellipsoid"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=123,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 50
    assert summary["number_density"] == 0.05


def test_create_initial_config_3d_sphere_tetrahedron():
    particle_specs = [
        {"shape": "sphere", "number": 30, "diameter": 1.0},
        {"shape": "tetrahedron", "number": 20, "side": 1.2},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_3d_sphere_tetrahedron"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=42,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 50
    assert summary["number_density"] == 0.05


def test_create_initial_config_3d_sphere_capsule():
    particle_specs = [
        {"shape": "sphere", "number": 30, "diameter": 1.0},
        {"shape": "capsule", "number": 20, "length": 2.0, "diameter": 0.6},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_3d_sphere_capsule"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=303,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 50
    assert summary["number_density"] == 0.05


def test_create_initial_config_3d_sphere_octahedron():
    particle_specs = [
        {"shape": "sphere", "number": 30, "diameter": 1.0},
        {"shape": "octahedron", "number": 20, "side": 1.2},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_3d_sphere_octahedron"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=101,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 50
    assert summary["number_density"] == 0.05


def test_create_initial_config_3d_sphere_cube():
    particle_specs = [
        {"shape": "sphere", "number": 30, "diameter": 1.0},
        {"shape": "cube", "number": 20, "side": 1.0},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_3d_sphere_cube"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=202,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 50
    assert summary["number_density"] == 0.05


def test_create_initial_config_3d_multi_shapes():
    particle_specs = [
        {"shape": "sphere", "number": 10, "diameter": 1.0},
        {"shape": "capsule", "number": 10, "length": 2.0, "diameter": 0.6},
        {"shape": "tetrahedron", "number": 10, "side": 1.2},
        {"shape": "cube", "number": 10, "side": 1.0},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_3d_multi_shapes"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=3,
        particle_specs=particle_specs,
        initial_number_density=0.05,
        output_dir=str(output_dir),
        seed=555,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
        debug=True,
    )

    assert summary["total_particles"] == 40
    assert summary["number_density"] == 0.05


def main():
    test_create_initial_config_3d_sphere()
    print("test_create_initial_config_3d_sphere: OK")

    test_create_initial_config_3d_ellipsoid()
    print("test_create_initial_config_3d_ellipsoid: OK")

    test_create_initial_config_3d_sphere_capsule()
    print("test_create_initial_config_3d_sphere_capsule: OK")

    test_create_initial_config_3d_sphere_tetrahedron()
    print("test_create_initial_config_3d_sphere_tetrahedron: OK")

    test_create_initial_config_3d_sphere_cube()
    print("test_create_initial_config_3d_sphere_cube: OK")

    test_create_initial_config_3d_sphere_octahedron()
    print("test_create_initial_config_3d_sphere_octahedron: OK")

    test_create_initial_config_3d_multi_shapes()
    print("test_create_initial_config_3d_multi_shapes: OK")


if __name__ == "__main__":
    main()
