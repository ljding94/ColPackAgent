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


def test_compress_3d_sphere():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere"
    print("test_compress_3d_sphere: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=42)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )


def test_compress_3d_ellipsoid():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_ellipsoid"
    print("test_compress_3d_ellipsoid: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=42)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )

def test_compress_3d_sphere_capsule():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_capsule"
    print("test_compress_3d_sphere_capsule: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=202)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )

def test_compress_3d_sphere_cube():
    target_number_density = 0.3
    system_dir = _find_project_root(Path(__file__).resolve()) / "data" / "test" / "init_3d_sphere_cube"
    print("test_compress_3d_sphere_cube: system_dir:", system_dir)
    compress_system(target_number_density=target_number_density, system_dir=str(system_dir), seed=303)

    # visualize the compressed system
    compressed_gsd_path = system_dir / "compressed.gsd"
    visualize_gsd(
        gsd_path=compressed_gsd_path,
        output_path=system_dir / "compressed_render.png",
        frame_index=-1,
        preview=False,
    )



def main():
    print("testing compression of 3d systems...")
    #test_compress_3d_sphere()
    #print("test_compress_3d_sphere: OK")

    #test_compress_3d_ellipsoid()
    #print("test_compress_3d_ellipsoid: OK")

    #test_compress_3d_sphere_capsule()
    #print("test_compress_3d_sphere_capsule: OK")

    test_compress_3d_sphere_cube()
    print("test_compress_3d_sphere_cube: OK")

if __name__ == "__main__":
    main()
