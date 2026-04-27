#!/usr/bin/env python3
"""Bootstrap shared simulation fixtures for Track 1 evaluation.

Two tiers of fixtures:

1. Full simulation fixtures (`setup_only=False`, default).
   Run setup → plan → execute deterministically. Produce executed
   trajectories that downstream analysis tasks read from.

2. Setup-only fixtures (`setup_only=True`).
   Run only `setup_simulation_problem` — no plan, no execute. Cheap
   (millisecond) starting points that planning tasks build on top of
   without redoing setup themselves.

Default fixtures:
  - 2d_nvt_disk                       full;    vf sweep at [0.3, 0.5, 0.7, 0.8]
  - 2d_nvt_disk_capsule               full;    vf sweep at [0.4, 0.6]
  - 2d_nvt_disk_capsule_setup         setup-only (2D NVT mix, 500 particles)
  - 2d_npt_disk_capsule_setup         setup-only (2D NPT mix, 500 particles)
  - 2d_nvt_disk_disk_setup            setup-only (2D NVT bidisperse, 1000 particles)

All fixtures land under eval/data/fixtures/<fixture_id>/ (eval/data/ is
gitignored, so the produced files stay out of git). An index file at
eval/data/fixtures/_index.json records the mapping fixture_id → working_dir
and the params used.

Examples:
  # Build all fixtures (skip ones that already exist)
  python eval/bootstrap_fixtures.py

  # Rebuild from scratch
  python eval/bootstrap_fixtures.py --force

  # Build only one fixture
  python eval/bootstrap_fixtures.py --only 2d_nvt_disk_capsule_setup
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
        "description": "2D NVT, 100 hard disks, volume_fraction sweep at [0.3, 0.5, 0.7, 0.8] — chosen to span the 2D hard-disk freezing transition (~0.7) so analysis tasks can interpret order-parameter trends.",
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
            "volume_fraction": [0.3, 0.5, 0.7, 0.8],
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
    # ---- Setup-only fixtures (planning-suite starting points) ----
    {
        "fixture_id": "2d_nvt_disk_capsule_setup",
        "description": "Setup-only fixture: 2D NVT, 500 particles in a disk+capsule mixture. Planning tasks build sweeps on top of this simulation_problem.json without redoing setup.",
        "setup_only": True,
        "setup": {
            "dimension": 2,
            "total_particle_number": 500,
            "particle_shape_list": ["disk", "capsule"],
            "ensemble": "NVT",
        },
    },
    {
        "fixture_id": "2d_npt_disk_capsule_setup",
        "description": "Setup-only fixture: 2D NPT, 500 particles in a disk+capsule mixture. Used by NPT pressure-sweep planning tasks.",
        "setup_only": True,
        "setup": {
            "dimension": 2,
            "total_particle_number": 500,
            "particle_shape_list": ["disk", "capsule"],
            "ensemble": "NPT",
        },
    },
    {
        "fixture_id": "2d_nvt_disk_disk_setup",
        "description": "Setup-only fixture: 2D NVT, 1000 particles as a bidisperse disk mixture (two disk components). Used by diameter-sweep planning tasks.",
        "setup_only": True,
        "setup": {
            "dimension": 2,
            "total_particle_number": 1000,
            "particle_shape_list": ["disk", "disk"],
            "ensemble": "NVT",
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
    setup_only = bool(fixture.get("setup_only", False))

    if expected_path.exists():
        if not force:
            print(f"[skip]    {fixture_id}: already at {expected_path} (use --force to rebuild)")
            return expected_path
        print(f"[clean]   {fixture_id}: removing existing {expected_path}")
        shutil.rmtree(expected_path)

    setup = fixture["setup"]
    summary = (f"dimension={setup['dimension']}, ensemble={setup['ensemble']}, "
               f"shapes={setup['particle_shape_list']}, N={setup['total_particle_number']}")

    if setup_only:
        # Use a per-fixture scratch sub-root so setup's canonical-slug naming
        # ('<dim>d_<ens>_<shape>...') does not collide with existing full-sim
        # fixtures already at the same slug under fixture_root.
        scratch_root = fixture_root / f"_scratch_{fixture_id}"
        if scratch_root.exists():
            shutil.rmtree(scratch_root)
        scratch_root.mkdir(parents=True)
        try:
            os.environ["COLPACK_WORKING_DIR_ROOT"] = str(scratch_root)
            print(f"[setup]   {fixture_id} (setup-only): {summary}")
            setup_simulation_problem(**setup)

            produced = [p for p in scratch_root.iterdir() if p.is_dir()]
            if len(produced) != 1:
                raise RuntimeError(
                    f"setup_simulation_problem produced unexpected number of dirs in scratch: {produced}"
                )
            shutil.move(str(produced[0]), str(expected_path))
        finally:
            if scratch_root.exists():
                shutil.rmtree(scratch_root)

        # Patch the stale working_dir field that setup baked in (pointed at the
        # scratch path before the move). Without this, agents that Read the
        # simulation_problem.json see a non-existent working_dir.
        problem_path = expected_path / "simulation_problem.json"
        with problem_path.open("r", encoding="utf-8") as f:
            problem = json.load(f)
        problem["working_dir"] = str(expected_path)
        with problem_path.open("w", encoding="utf-8") as f:
            json.dump(problem, f, indent=4)

        print(f"[done]    {fixture_id} (setup-only): {expected_path}")
        return expected_path

    os.environ["COLPACK_WORKING_DIR_ROOT"] = str(fixture_root)

    print(f"[setup]   {fixture_id}: {summary}")
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
        entry: dict = {
            "description": fixture["description"],
            "working_dir": str(path),
            "setup_only": bool(fixture.get("setup_only", False)),
            "setup": fixture["setup"],
        }
        if not fixture.get("setup_only"):
            entry["baseline_parameters"] = fixture["baseline_parameters"]
            entry["tunable_parameters"] = fixture["tunable_parameters"]
        built[fixture["fixture_id"]] = entry

    index_path = _write_index(fixture_root, built)
    print(f"\nIndex updated: {index_path}")
    print(f"Built {len(built)} fixture(s): {sorted(built.keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
