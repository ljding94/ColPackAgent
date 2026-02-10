from pathlib import Path

# from colpack.visualize_fresnel import visualize_gsd
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


def test_sample_3d_sphere():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere"
    print("test_sample_3d_sphere: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=42)

    # visualize the sample system

    sample_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sample_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_3d_ellipsoid():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_ellipsoid"
    print("test_sample_3d_ellipsoid: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=42)

    # visualize the sample system

    sample_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sample_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_3d_sphere_capsule():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_capsule"
    print("test_sample_3d_sphere_capsule: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=202)

    # visualize the sample system

    sample_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sample_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_3d_sphere_cube():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_cube"
    print("test_sample_3d_sphere_cube: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=303)

    # visualize the sample system
    sample_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sample_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_3d_sphere_octahedron():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_octahedron"
    print("test_sample_3d_sphere_octahedron: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=101)

    # visualize the sample system
    sample_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sample_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_3d_sphere_tetrahedron():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_tetrahedron"
    print("test_sample_3d_sphere_tetrahedron: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=101)

    # visualize the sample system
    sample_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sample_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def test_sample_3d_multi_shapes():
    sample_steps = 30000
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_multi_shapes"
    print("test_sample_3d_multi_shapes: system_dir:", system_dir)
    sample_system(sample_steps=sample_steps, system_dir=str(system_dir), seed=202)

    # visualize the sample system
    sample_gsd_path = system_dir / "sample_final.gsd"
    visualize_gsd(
        gsd_path=sample_gsd_path,
        output_path=system_dir / "sample_final_render.png",
        frame_index=-1,
        preview=False,
    )


def main():
    print("testing sample of 3d systems...")

    test_sample_3d_sphere()
    print("test_sample_3d_sphere: OK")

    test_sample_3d_ellipsoid()
    print("test_sample_3d_ellipsoid: OK")

    test_sample_3d_sphere_capsule()
    print("test_sample_3d_sphere_capsule: OK")

    test_sample_3d_sphere_cube()
    print("test_sample_3d_sphere_cube: OK")

    test_sample_3d_sphere_octahedron()
    print("test_sample_3d_sphere_octahedron: OK")

    test_sample_3d_sphere_tetrahedron()
    print("test_sample_3d_sphere_tetrahedron: OK")

    test_sample_3d_multi_shapes()
    print("test_sample_3d_multi_shapes: OK")


if __name__ == "__main__":
    main()
