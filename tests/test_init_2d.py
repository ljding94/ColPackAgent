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


def test_create_initial_config_2d_disk():
    particle_specs = [
        {"shape": "disk", "number": 10, "diameter": 2.0},
        {"shape": "disk", "number": 5},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_2d_disk"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.2,
        output_dir=str(output_dir),
        seed=42,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=True,
        debug=True,
    )

    assert summary["total_particles"] == 15
    assert summary["initial_number_density"] == 0.2


def test_create_initial_config_2d_ellipsoid():
    particle_specs = [
        {"shape": "ellipsoid", "number": 10, "a": 1.0, "b": 0.8},
        {"shape": "ellipsoid", "number": 5, "a": 1.0, "b": 0.4},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_2d_ellipsoid"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.1,
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

    assert summary["total_particles"] == 15


def test_create_initial_config_2d_sphere_ellipsoid():
    particle_specs = [
        {"shape": "sphere", "number": 8, "diameter": 1.2},
        {"shape": "ellipsoid", "number": 4, "a": 1.0, "b": 0.6},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_2d_sphere_ellipsoid"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.15,
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

    assert summary["total_particles"] == 12


def test_create_initial_config_2d_sphere_rectangle():
    particle_specs = [
        {"shape": "sphere", "number": 8, "diameter": 1.0},
        {"shape": "rectangle", "number": 4, "length": 2.0, "width": 1.0},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_2d_sphere_rectangle"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.15,
        output_dir=str(output_dir),
        seed=321,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 12


def test_create_initial_config_2d_sphere_capsule():
    particle_specs = [
        {"shape": "sphere", "number": 8, "diameter": 1.0},
        {"shape": "capsule", "number": 4, "length": 2.0, "diameter": 0.6},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_2d_sphere_capsule"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.15,
        output_dir=str(output_dir),
        seed=456,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 12


def test_create_initial_config_2d_sphere_triangle():
    particle_specs = [
        {"shape": "sphere", "number": 8, "diameter": 1.0},
        {"shape": "triangle", "number": 4, "side": 1.5},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_2d_sphere_triangle"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.15,
        output_dir=str(output_dir),
        seed=654,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 12



def test_create_initial_config_2d_multi_shapes():
    particle_specs = [
        {"shape": "disk", "number": 5, "diameter": 1.5},
        {"shape": "rectangle", "number": 5, "length": 2.0, "width": 1.0},
        {"shape": "capsule", "number": 5, "length": 2.0, "diameter": 0.6},
        {"shape": "triangle", "number": 5, "side": 1.5},
    ]

    project_root = _find_project_root(Path(__file__).resolve())
    output_dir = project_root / "data" / "test" / "init_2d_multi_shapes"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = create_initial_config(
        dimension=2,
        particle_specs=particle_specs,
        initial_number_density=0.1,
        output_dir=str(output_dir),
        seed=789,
    )

    gsd_path = output_dir / "init.gsd"
    visualize_gsd(
        gsd_path=gsd_path,
        output_path=output_dir / "init_render.png",
        frame_index=-1,
        preview=False,
    )

    assert summary["total_particles"] == 20


def main():
    test_create_initial_config_2d_disk()
    print("test_create_initial_config_2d_disk: OK")

    test_create_initial_config_2d_ellipsoid()
    print("test_create_initial_config_2d_ellipsoid: OK")

    test_create_initial_config_2d_sphere_ellipsoid()
    print("test_create_initial_config_2d_sphere_ellipsoid: OK")

    test_create_initial_config_2d_sphere_rectangle()
    print("test_create_initial_config_2d_sphere_rectangle: OK")

    test_create_initial_config_2d_sphere_capsule()
    print("test_create_initial_config_2d_sphere_capsule: OK")

    test_create_initial_config_2d_sphere_triangle()
    print("test_create_initial_config_2d_sphere_triangle: OK")

    test_create_initial_config_2d_multi_shapes()
    print("test_create_initial_config_2d_multi_shapes: OK")


if __name__ == "__main__":
    main()

