from pathlib import Path
from colpack.visualize_ovito import visualize_gsd
from colpack.sample import sample_system


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def test_run(system_subdir, number_density, seed):
    sample_steps = 300000
    project_root = _find_project_root(Path(__file__).resolve())
    system_dir = project_root / "data" / "test" / system_subdir
    print(f"test_run: system_dir: {system_dir}")

    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), density=number_density, seed=seed)

    # visualize the sampled system
    sampled_gsd_path = system_dir / f"sample_final_n{number_density:.3f}.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / f"sample_final_render_n{number_density:.3f}.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing thermalization of 2d systems...\n")

    # test_sample_2d_disk
    test_run(system_subdir="2d_disk", number_density=0.5, seed=42)
    print("test_sample_2d_disk: OK\n")

    test_run(system_subdir="2d_disk_disk", number_density=0.5, seed=42)
    print("test_sample_2d_disk_disk: OK\n")

    # test_sample_2d_ellipsoid (renamed to 2d_ellipse_ellipse)
    test_run(system_subdir="2d_ellipse_ellipse", number_density=0.3, seed=42)
    print("test_sample_2d_ellipse_ellipse: OK\n")

    test_run(system_subdir="2d_disk_ellipse", number_density=0.3, seed=123)
    print("test_sample_2d_disk_ellipse: OK\n")

    # test_sample_2d_sphere_rectangle (renamed to 2d_disk_rectangle)
    test_run(system_subdir="2d_disk_rectangle", number_density=0.5, seed=321)
    print("test_sample_2d_disk_rectangle: OK\n")

    test_run(system_subdir="2d_capsule", number_density=0.2, seed=456)
    print("test_sample_2d_capsule (n=0.2): OK\n")

    test_run(system_subdir="2d_capsule", number_density=0.25, seed=456)
    print("test_sample_2d_capsule (n=0.25): OK\n")

    test_run(system_subdir="2d_capsule", number_density=0.3, seed=456)
    print("test_sample_2d_capsule (n=0.3): OK\n")

    test_run(system_subdir="2d_capsule", number_density=0.35, seed=456)
    print("test_sample_2d_capsule (n=0.35): OK\n")

    # test_sample_2d_sphere_capsule (renamed to 2d_disk_capsule)
    test_run(system_subdir="2d_disk_capsule", number_density=0.4, seed=456)
    print("test_sample_2d_disk_capsule: OK\n")

    # test_sample_2d_sphere_triangle (renamed to 2d_disk_triangle)
    test_run(system_subdir="2d_disk_triangle", number_density=0.3, seed=654)
    print("test_sample_2d_disk_triangle: OK\n")

    # test_sample_2d_multi_shapes
    test_run(system_subdir="2d_multi_shapes", number_density=0.3, seed=789)
    print("test_sample_2d_multi_shapes: OK\n")


if __name__ == "__main__":
    main()
