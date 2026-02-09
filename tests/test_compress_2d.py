from pathlib import Path
from colpack.init import create_initial_config
from colpack.visualize_fresnel import visualize_gsd
from colpack.compress import compress_system


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def test_compress_2d_disk():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_disk"
    print("test_compress_2d_disk: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=42)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def test_compress_2d_ellipsoid():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_ellipsoid"
    print("test_compress_2d_ellipsoid: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=42)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def test_compress_2d_sphere_ellipsoid():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_ellipsoid"
    print("test_compress_2d_sphere_ellipsoid: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=123)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def test_compress_2d_sphere_rectangle():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_rectangle"
    print("test_compress_2d_sphere_rectangle: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=321)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def test_compress_2d_sphere_capsule():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_capsule"
    print("test_compress_2d_sphere_capsule: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=456)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def test_compress_2d_sphere_triangle():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_triangle"
    print("test_compress_2d_sphere_triangle: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=654)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def test_compress_2d_multi_shapes():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_multi_shapes"
    print("test_compress_2d_multi_shapes: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=789)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing compression of 2d systems...")

    test_compress_2d_disk()
    print("test_compress_2d_disk: OK")

    test_compress_2d_ellipsoid()
    print("test_compress_2d_ellipsoid: OK")

    test_compress_2d_sphere_ellipsoid()
    print("test_compress_2d_sphere_ellipsoid: OK")

    test_compress_2d_sphere_rectangle()
    print("test_compress_2d_sphere_rectangle: OK")

    test_compress_2d_sphere_capsule()
    print("test_compress_2d_sphere_capsule: OK")

    test_compress_2d_sphere_triangle()
    print("test_compress_2d_sphere_triangle: OK")

    test_compress_2d_multi_shapes()
    print("test_compress_2d_multi_shapes: OK")


if __name__ == "__main__":
    main()
