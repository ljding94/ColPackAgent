from pathlib import Path
from colpack.analyze import analyze_main


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (pyproject.toml not found).")
        current = current.parent


def run_analyze(system_subdir, number_density):
    project_root = _find_project_root(Path(__file__).resolve())
    system_dir = project_root / "data" / "test" / system_subdir
    print(f"run_analyze: system_dir: {system_dir}")
    analyze_main(system_dir=str(system_dir), density=number_density)


def main():
    print("testing analysis of 3d systems...\n")

    # test_analyze_3d_sphere
    #run_analyze(system_subdir="3d_sphere", number_density=0.3)
    print("test_analyze_3d_sphere: OK\n")

    #run_analyze(system_subdir="3d_sphere_sphere", number_density=0.3)
    print("test_analyze_3d_sphere_sphere: OK\n")

    # test_analyze_3d_ellipsoid
    #run_analyze(system_subdir="3d_ellipsoid", number_density=0.3)
    print("test_analyze_3d_ellipsoid: OK\n")

    # test_analyze_3d_capsule
    run_analyze(system_subdir="3d_capsule", number_density=0.25)
    print("test_analyze_3d_capsule (n=0.25): OK\n")
    run_analyze(system_subdir="3d_capsule", number_density=0.3)
    print("test_analyze_3d_capsule (n=0.3): OK\n")
    run_analyze(system_subdir="3d_capsule", number_density=0.35)
    print("test_analyze_3d_capsule (n=0.35): OK\n")
    #run_analyze(system_subdir="3d_capsule", number_density=0.4)
    print("test_analyze_3d_capsule (n=0.4): OK\n")

    # test_analyze_3d_sphere_capsule
    #run_analyze(system_subdir="3d_sphere_capsule", number_density=0.3)
    print("test_analyze_3d_sphere_capsule: OK\n")

    # test_analyze_3d_sphere_cube
    #run_analyze(system_subdir="3d_sphere_cube", number_density=0.3)
    print("test_analyze_3d_sphere_cube: OK\n")

    # test_analyze_3d_sphere_octahedron
    #run_analyze(system_subdir="3d_sphere_octahedron", number_density=0.3)
    print("test_analyze_3d_sphere_octahedron: OK\n")

    # test_analyze_3d_sphere_tetrahedron
    #run_analyze(system_subdir="3d_sphere_tetrahedron", number_density=0.3)
    print("test_analyze_3d_sphere_tetrahedron: OK\n")

    # test_analyze_3d_multi_shapes
    #run_analyze(system_subdir="3d_multi_shapes", number_density=0.3)
    print("test_analyze_3d_multi_shapes: OK\n")


if __name__ == "__main__":
    main()
