#!/usr/bin/env python3
"""Bootstrap shared simulation fixtures for Track 1 evaluation.

Runs setup → plan → execute deterministically for a small set of baseline
scenarios so that downstream planning and analysis evaluation tasks can
reuse the resulting working_dirs instead of redoing the full pipeline per
task.

Two fixtures are built by default:
  - 2d_nvt_disk         single-shape disk system, vf sweep at [0.4, 0.6]
  - 2d_nvt_disk_capsule disk+capsule mixture,    vf sweep at [0.4, 0.6]

Both land under eval/data/fixtures/<fixture_id>/ (eval/data/ is gitignored,
so the produced GSD trajectories stay out of git). An index file at
eval/data/fixtures/_index.json records the mapping fixture_id → working_dir
and the params used, so planning/analysis specs can resolve fixture paths
without parsing this script.

Examples:
  # Build all fixtures (skip ones that already exist)
  python eval/bootstrap_fixtures.py

  # Rebuild from scratch
  python eval/bootstrap_fixtures.py --force

  # Build only one fixture
  python eval/bootstrap_fixtures.py --only 2d_nvt_disk
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE_ROOT = REPO_ROOT / "eval" / "data" / "fixtures"

FIXTURES: list[dict] = [
    {
        "fixture_id": "2d_nvt_disk",
        "description": "2D NVT, 100 hard disks, volume_fraction sweep at [0.4, 0.6].",
        "setup": {
            "dimension": 2,
            "total_particle_number": 100,
            "particle_shape_list": ["disk"],
            "ensemble": "NVT",
        },
        "baseline_parameters": {
            "sample_steps": 10000,
            "particle_specs.0.diameter": 1.0,
        },
        "tunable_parameters": {
            "volume_fraction": [0.4, 0.6],
        },
    },
    {
        "fixture_id": "2d_nvt_disk_capsule",
        "description": "2D NVT, 100 particles in a disk+capsule mixture, volume_fraction sweep at [0.4, 0.6].",
        "setup": {
            "dimension": 2,
            "total_particle_number": 100,
            "particle_shape_list": ["disk", "capsule"],
            "ensemble": "NVT",
        },
        "baseline_parameters": {
            "sample_steps": 10000,
            "particle_specs.0.diameter": 1.0,
            "particle_specs.0.relative_volume_fraction": 1.0,
            "particle_specs.1.diameter": 1.0,
            "particle_specs.1.length": 3.0,
            "particle_specs.1.relative_volume_fraction": 1.0,
        },
        "tunable_parameters": {
            "volume_fraction": [0.4, 0.6],
        },
    },
]


def _ensure_src_on_path() -> None:
    src_path = str(REPO_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def _build_one(fixture: dict, fixture_root: Path, force: bool) -> Path:
    from colpack.workflow import (
        setup_simulation_problem,
        plan_simulaiton_runs,
        execute_simulation_workflow,
    )

    fixture_id = fixture["fixture_id"]
    expected_path = (fixture_root / fixture_id).resolve()

    if expected_path.exists():
        if not force:
            print(f"[skip]    {fixture_id}: already at {expected_path} (use --force to rebuild)")
            return expected_path
        print(f"[clean]   {fixture_id}: removing existing {expected_path}")
        shutil.rmtree(expected_path)

    os.environ["COLPACK_WORKING_DIR_ROOT"] = str(fixture_root)

    setup = fixture["setup"]
    print(f"[setup]   {fixture_id}: dimension={setup['dimension']}, ensemble={setup['ensemble']}, "
          f"shapes={setup['particle_shape_list']}, N={setup['total_particle_number']}")
    setup_simulation_problem(**setup)

    if not expected_path.exists():
        produced = sorted(p.name for p in fixture_root.iterdir() if p.is_dir())
        raise RuntimeError(
            f"setup_simulation_problem did not produce expected path {expected_path}. "
            f"Existing directories under fixture root: {produced}. "
            "Check that fixture_id matches the canonical setup slug "
            "('<dim>d_<ensemble>_<shape1>_<shape2>...')."
        )

    plan_result = plan_simulaiton_runs(
        baseline_parameters=fixture["baseline_parameters"],
        tunable_parameters=fixture["tunable_parameters"],
        working_dir=str(expected_path),
    )
    n_runs = plan_result.get("n_total_runs", 0)
    print(f"[plan]    {fixture_id}: {n_runs} run(s) planned (tunable={fixture['tunable_parameters']})")

    print(f"[execute] {fixture_id}: running {n_runs} simulation(s)...")
    execute_simulation_workflow(working_dir=str(expected_path))

    print(f"[done]    {fixture_id}: {expected_path}")
    return expected_path


def _write_index(fixture_root: Path, built: dict[str, dict]) -> Path:
    index_path = fixture_root / "_index.json"
    existing: dict = {}
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing.update(built)
    index_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=DEFAULT_FIXTURE_ROOT,
        help=f"Where to write fixtures (default: {DEFAULT_FIXTURE_ROOT.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild fixtures even if their working_dir already exists.",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="FIXTURE_ID",
        help="Only build the named fixture(s). Repeatable.",
    )
    args = parser.parse_args()

    fixture_root = args.fixture_root.resolve()
    fixture_root.mkdir(parents=True, exist_ok=True)

    if args.only:
        known_ids = {f["fixture_id"] for f in FIXTURES}
        unknown = sorted(set(args.only) - known_ids)
        if unknown:
            raise SystemExit(f"Unknown --only fixtures: {unknown}. Known: {sorted(known_ids)}")
        selected = [f for f in FIXTURES if f["fixture_id"] in set(args.only)]
    else:
        selected = list(FIXTURES)

    _ensure_src_on_path()

    built: dict[str, dict] = {}
    for fixture in selected:
        path = _build_one(fixture, fixture_root, args.force)
        built[fixture["fixture_id"]] = {
            "description": fixture["description"],
            "working_dir": str(path),
            "setup": fixture["setup"],
            "baseline_parameters": fixture["baseline_parameters"],
            "tunable_parameters": fixture["tunable_parameters"],
        }

    index_path = _write_index(fixture_root, built)
    print(f"\nIndex updated: {index_path}")
    print(f"Built {len(built)} fixture(s): {sorted(built.keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
