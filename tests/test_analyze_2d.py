from pathlib import Path
from colpack.visualize_ovito import visualize_gsd
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
    print("testing analysis of 2d systems...\n")

    # test_analyze_2d_disk
    run_analyze(system_subdir="2d_disk", number_density=0.5)
    print("test_analyze_2d_disk: OK\n")

    run_analyze(system_subdir="2d_disk_disk", number_density=0.5)
    print("test_analyze_2d_disk_disk: OK\n")

    # test_analyze_2d_ellipsoid
    run_analyze(system_subdir="2d_ellipse_ellipse", number_density=0.3)
    print("test_analyze_2d_ellipse_ellipse: OK\n")

    run_analyze(system_subdir="2d_disk_ellipse", number_density=0.3)
    print("test_analyze_2d_disk_ellipse: OK\n")

    # test_analyze_2d_sphere_rectangle
    run_analyze(system_subdir="2d_disk_rectangle", number_density=0.5)
    print("test_analyze_2d_disk_rectangle: OK\n")

    run_analyze(system_subdir="2d_capsule", number_density=0.2)
    print("test_analyze_2d_capsule (n=0.2): OK\n")

    run_analyze(system_subdir="2d_capsule", number_density=0.25)
    print("test_analyze_2d_capsule (n=0.25): OK\n")

    run_analyze(system_subdir="2d_capsule", number_density=0.3)
    print("test_analyze_2d_capsule (n=0.3): OK\n")

    run_analyze(system_subdir="2d_capsule", number_density=0.35)
    print("test_analyze_2d_capsule (n=0.35): OK\n")

    # test_analyze_2d_sphere_capsule
    run_analyze(system_subdir="2d_disk_capsule", number_density=0.4)
    print("test_analyze_2d_disk_capsule: OK\n")

    # test_analyze_2d_sphere_triangle
    run_analyze(system_subdir="2d_disk_triangle", number_density=0.3)
    print("test_analyze_2d_disk_triangle: OK\n")

    # test_analyze_2d_multi_shapes
    run_analyze(system_subdir="2d_multi_shapes", number_density=0.3)
    print("test_analyze_2d_multi_shapes: OK\n")


if __name__ == "__main__":
    main()
