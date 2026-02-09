







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


def test_thermalize_2d_disk():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_disk"
    print("test_thermalize_2d_disk: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=42)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_2d_ellipsoid():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_ellipsoid"
    print("test_thermalize_2d_ellipsoid: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=42)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_2d_sphere_ellipsoid():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_ellipsoid"
    print("test_thermalize_2d_sphere_ellipsoid: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=123)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_2d_sphere_rectangle():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_rectangle"
    print("test_thermalize_2d_sphere_rectangle: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=321)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_2d_sphere_capsule():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_capsule"
    print("test_thermalize_2d_sphere_capsule: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=456)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_2d_sphere_triangle():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_triangle"
    print("test_thermalize_2d_sphere_triangle: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=654)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def test_thermalize_2d_multi_shapes():
    thermalization_steps = 1000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_multi_shapes"
    print("test_thermalize_2d_multi_shapes: system_dir:", system_dir)
    thermalize_system(thermalization_steps=thermalization_steps, system_dir=str(system_dir), seed=789)

    # visualize the thermalized system
    thermalized_gsd_path = system_dir / "thermalized.gsd"
    visualize_gsd(
        gsd_path=thermalized_gsd_path,
        output_path=system_dir / "thermalized_render.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing thermalization of 2d systems...")

    test_thermalize_2d_disk()
    print("test_thermalize_2d_disk: OK")

    test_thermalize_2d_ellipsoid()
    print("test_thermalize_2d_ellipsoid: OK")

    test_thermalize_2d_sphere_ellipsoid()
    print("test_thermalize_2d_sphere_ellipsoid: OK")

    test_thermalize_2d_sphere_rectangle()
    print("test_thermalize_2d_sphere_rectangle: OK")

    test_thermalize_2d_sphere_capsule()
    print("test_thermalize_2d_sphere_capsule: OK")

    test_thermalize_2d_sphere_triangle()
    print("test_thermalize_2d_sphere_triangle: OK")

    test_thermalize_2d_multi_shapes()
    print("test_thermalize_2d_multi_shapes: OK")


if __name__ == "__main__":
    main()

