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


def test_sample_2d_disk():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_disk"
    print("test_sample_2d_disk: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=42)

    # visualize the sampled system
    sampled_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )

    visualize_gsd(
        gsd_path=system_dir / "sampling" / "trajectory.gsd",
        output_path=system_dir / "sampling" / "trajectory.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_2d_ellipsoid():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_ellipsoid"
    print("test_sample_2d_ellipsoid: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=42)

    # visualize the sampled system
    sampled_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_2d_sphere_ellipsoid():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_ellipsoid"
    print("test_sample_2d_sphere_ellipsoid: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=123)

    # visualize the sampled system
    sampled_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_2d_sphere_rectangle():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_rectangle"
    print("test_sample_2d_sphere_rectangle: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=321)

    # visualize the sampled system
    sampled_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_2d_sphere_capsule():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_capsule"
    print("test_sample_2d_sphere_capsule: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=456)

    # visualize the sampled system
    sampled_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_2d_sphere_triangle():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_sphere_triangle"
    print("test_sample_2d_sphere_triangle: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=654)

    # visualize the sampled system
    sampled_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_2d_multi_shapes():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_2d_multi_shapes"
    print("test_sample_2d_multi_shapes: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=789)

    # visualize the sampled system
    sampled_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sampled_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing thermalization of 2d systems...")

    test_sample_2d_disk()
    print("test_sample_2d_disk: OK")

    test_sample_2d_ellipsoid()
    print("test_sample_2d_ellipsoid: OK")

    test_sample_2d_sphere_ellipsoid()
    print("test_sample_2d_sphere_ellipsoid: OK")

    test_sample_2d_sphere_rectangle()
    print("test_sample_2d_sphere_rectangle: OK")

    test_sample_2d_sphere_capsule()
    print("test_sample_2d_sphere_capsule: OK")

    test_sample_2d_sphere_triangle()
    print("test_sample_2d_sphere_triangle: OK")

    test_sample_2d_multi_shapes()
    print("test_sample_2d_multi_shapes: OK")


if __name__ == "__main__":
    main()
