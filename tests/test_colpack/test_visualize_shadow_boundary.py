from pathlib import Path
import importlib.util


def _find_project_root(start: Path) -> Path:
    current = start
    while True:
        if (current / "environment.yml").exists() or (current / "src" / "pyproject.toml").exists():
            return current
        if current.parent == current:
            raise RuntimeError("Could not locate project root (environment.yml or src/pyproject.toml not found).")
        current = current.parent


def _has_ovito() -> bool:
    return importlib.util.find_spec("ovito") is not None


def _pick_existing_gsd(project_root: Path) -> Path:
    candidates = [
        project_root / "data" / "test" / "3d_sphere" / "run_0" / "compress.gsd",
        project_root / "data" / "test" / "3d_sphere" / "run_0" / "sample_final.gsd",
        project_root / "data" / "test" / "2d_disk_capsule" / "run_0" / "compress.gsd",
        project_root / "data" / "test" / "2d_disk_capsule" / "run_0" / "sample_final.gsd",
        project_root / "data" / "test" / "2d_disk_disk" / "run_0" / "compress.gsd",
        project_root / "data" / "test" / "3d_ellipsoid" / "run_0" / "compress.gsd",
    ]
    for path in candidates:
        if path.exists():
            return path

    pool = sorted((project_root / "data" / "test").glob("**/*.gsd"))
    if not pool:
        raise FileNotFoundError("No .gsd files found under data/test.")
    return pool[0]


def test_visualize_shadow_boundary_variants():
    if not _has_ovito():
        print("Skipping test_visualize_shadow_boundary.py: 'ovito' is not installed in the current Python environment.")
        return

    from colpack.visualize_ovito import visualize_gsd

    project_root = _find_project_root(Path(__file__).resolve())
    gsd_path = _pick_existing_gsd(project_root)
    out_dir = gsd_path.parent
    stem = gsd_path.stem

    variants = [
        {"show_boundary": True, "enable_shadows": True, "suffix": "boundary_on_shadows_on"},
        {"show_boundary": True, "enable_shadows": False, "suffix": "boundary_on_shadows_off"},
        {"show_boundary": False, "enable_shadows": True, "suffix": "boundary_off_shadows_on"},
        {"show_boundary": False, "enable_shadows": False, "suffix": "boundary_off_shadows_off"},
    ]

    print(f"Using input GSD: {gsd_path}")
    for variant in variants:
        output_path = out_dir / f"{stem}_shadow_test_{variant['suffix']}.png"
        visualize_gsd(
            gsd_path=gsd_path,
            output_path=output_path,
            frame_index=-1,
            preview=False,
            debug=True,
            show_boundary=variant["show_boundary"],
            enable_shadows=variant["enable_shadows"],
        )
        assert output_path.exists(), f"Expected output not found: {output_path}"
        print(f"Rendered: {output_path}")


def main():
    test_visualize_shadow_boundary_variants()


if __name__ == "__main__":
    main()
