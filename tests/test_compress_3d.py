from pathlib import Path
from colpack.visualize_ovito import visualize_gsd
from colpack.compress import compress_system


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def test_run(system_subdir, number_density, seed):
    project_root = _find_project_root(Path(__file__).resolve())
    system_dir = project_root / "data" / "test" / system_subdir
    print(f"test_run: system_dir: {system_dir}")

    compress_system(target_number_density=number_density, system_dir=str(system_dir), seed=seed)

    # visualize the compressed system
    compressed_gsd_path = system_dir / f"compressed_n{number_density:.3f}.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / f"compressed_render_n{number_density:.3f}.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing compression of 3d systems...\n")

    # test_compress_3d_sphere
    test_run(system_subdir="3d_sphere", number_density=0.3, seed=42)
    print("test_compress_3d_sphere: OK\n")

    test_run(system_subdir="3d_sphere_sphere", number_density=0.3, seed=42)
    print("test_compress_3d_sphere_sphere: OK\n")

    # test_compress_3d_ellipsoid
    test_run(system_subdir="3d_ellipsoid", number_density=0.3, seed=42)
    print("test_compress_3d_ellipsoid: OK\n")

    test_run(system_subdir="3d_capsule", number_density=0.25, seed=202)
    print("test_compress_3d_capsule: OK\n")
    test_run(system_subdir="3d_capsule", number_density=0.3, seed=202)
    print("test_compress_3d_capsule: OK\n")
    test_run(system_subdir="3d_capsule", number_density=0.35, seed=202)
    print("test_compress_3d_capsule: OK\n")
    test_run(system_subdir="3d_capsule", number_density=0.4, seed=202)
    print("test_compress_3d_capsule: OK\n")

    # test_compress_3d_sphere_capsule
    test_run(system_subdir="3d_sphere_capsule", number_density=0.3, seed=202)
    print("test_compress_3d_sphere_capsule: OK\n")

    # test_compress_3d_sphere_cube
    test_run(system_subdir="3d_sphere_cube", number_density=0.3, seed=303)
    print("test_compress_3d_sphere_cube: OK\n")

    # test_compress_3d_sphere_octahedron
    test_run(system_subdir="3d_sphere_octahedron", number_density=0.3, seed=101)
    print("test_compress_3d_sphere_octahedron: OK\n")

    # test_compress_3d_sphere_tetrahedron
    test_run(system_subdir="3d_sphere_tetrahedron", number_density=0.3, seed=101)
    print("test_compress_3d_sphere_tetrahedron: OK\n")

    # test_compress_3d_multi_shapes
    test_run(system_subdir="3d_multi_shapes", number_density=0.3, seed=202)
    print("test_compress_3d_multi_shapes: OK\n")


if __name__ == "__main__":
    main()
