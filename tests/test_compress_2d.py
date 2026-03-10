from pathlib import Path
from colpack.visualize_ovito import visualize_gsd
from colpack.compress import compress_system

# TODO: need to consider one initial state may get compressed into different number density, we should somehow allow this in the file naming or in the summary.json


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def test_run(system_subdir, target_number_density, seed):
    project_root = _find_project_root(Path(__file__).resolve())
    system_dir = project_root / "data" / "test" / system_subdir
    print(f"test_run: system_dir: {system_dir}")

    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=seed)

    # visualize the compressed system
    compressed_gsd_path = system_dir / f"compressed_n{target_number_density:.3f}.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / f"compressed_render_n{target_number_density:.3f}.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing compression of 2d systems...\n")

    # test_compress_2d_disk
    test_run(system_subdir="2d_disk", target_number_density=0.5, seed=42)
    print("test_compress_2d_disk: OK\n")

    test_run(system_subdir="2d_disk_disk", target_number_density=0.5, seed=42)
    print("test_compress_2d_disk_disk: OK\n")

    # test_compress_2d_ellipsoid
    test_run(system_subdir="2d_ellipse_ellipse", target_number_density=0.3, seed=42)
    print("test_compress_2d_ellipse_ellipse: OK\n")

    test_run(system_subdir="2d_disk_ellipse", target_number_density=0.3, seed=123)
    print("test_compress_2d_disk_ellipse: OK\n")

    # test_compress_2d_sphere_rectangle
    test_run(system_subdir="2d_disk_rectangle", target_number_density=0.5, seed=321)
    print("test_compress_2d_disk_rectangle: OK\n")

    test_run(system_subdir="2d_capsule", target_number_density=0.2, seed=456)
    print("test_compress_2d_capsule: OK\n")

    test_run(system_subdir="2d_capsule", target_number_density=0.25, seed=456)
    print("test_compress_2d_capsule: OK\n")

    test_run(system_subdir="2d_capsule", target_number_density=0.3, seed=456)
    print("test_compress_2d_capsule: OK\n")

    test_run(system_subdir="2d_capsule", target_number_density=0.35, seed=456)
    print("test_compress_2d_capsule: OK\n")

    # test_compress_2d_sphere_capsule
    test_run(system_subdir="2d_disk_capsule", target_number_density=0.4, seed=456)
    print("test_compress_2d_disk_capsule: OK\n")

    # test_compress_2d_sphere_triangle
    test_run(system_subdir="2d_disk_triangle", target_number_density=0.3, seed=654)
    print("test_compress_2d_disk_triangle: OK\n")

    # test_compress_2d_multi_shapes
    test_run(system_subdir="2d_multi_shapes", target_number_density=0.3, seed=789)
    print("test_compress_2d_multi_shapes: OK\n")


if __name__ == "__main__":
    main()
