from pathlib import Path
from colpack.visualize_fresnel import visualize_gsd
from colpack.thermalize import thermalize_system


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def test_thermalize_3d_sphere():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere"
    print("test_thermalize_3d_sphere: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=42)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_3d_ellipsoid():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_ellipsoid"
    print("test_thermalize_3d_ellipsoid: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=42)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_3d_sphere_capsule():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_capsule"
    print("test_thermalize_3d_sphere_capsule: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=202)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_3d_sphere_cube():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_cube"
    print("test_thermalize_3d_sphere_cube: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=303)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_3d_sphere_octahedron():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_octahedron"
    print("test_thermalize_3d_sphere_octahedron: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=101)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_3d_sphere_tetrahedron():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_tetrahedron"
    print("test_thermalize_3d_sphere_tetrahedron: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=101)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_3d_multi_shapes():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_multi_shapes"
    print("test_thermalize_3d_multi_shapes: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=202)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing thermalization of 3d systems...")

    test_thermalize_3d_sphere()
    print("test_thermalize_3d_sphere: OK")

    test_thermalize_3d_ellipsoid()
    print("test_thermalize_3d_ellipsoid: OK")

    test_thermalize_3d_sphere_capsule()
    print("test_thermalize_3d_sphere_capsule: OK")

    test_thermalize_3d_sphere_cube()
    print("test_thermalize_3d_sphere_cube: OK")

    test_thermalize_3d_sphere_octahedron()
    print("test_thermalize_3d_sphere_octahedron: OK")

    test_thermalize_3d_sphere_tetrahedron()
    print("test_thermalize_3d_sphere_tetrahedron: OK")

    test_thermalize_3d_multi_shapes()
    print("test_thermalize_3d_multi_shapes: OK")


if __name__ == "__main__":
    main()
