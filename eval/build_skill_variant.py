#!/usr/bin/env python3
"""Build a skill variant under eval/skills/<variant_id>/ for ablation experiments.

Copies the production skill at agent/skills/colpack/ to
eval/skills/<variant_id>/colpack/, optionally omitting one or more files
(typically reference markdown files) so the agent runs without them.

Examples:
  # Full skill, no ablation
  python eval/build_skill_variant.py --variant-id full

  # Drop a single reference file
  python eval/build_skill_variant.py --variant-id no_analysis \\
      --exclude references/4_analyze_simulation.md

  # Drop a whole directory
  python eval/build_skill_variant.py --variant-id no_references \\
      --exclude references

  # Empty skill body (frontmatter only) plus no references/scripts —
  # represents "skill registered but agent gets no instructions"
  python eval/build_skill_variant.py --variant-id no_skill \\
      --exclude references --exclude scripts --strip-skill-body
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / "agent" / "skills" / "colpack"
DEFAULT_DEST_ROOT = REPO_ROOT / "eval" / "skills"
ALWAYS_SKIP_PARTS = {"__pycache__"}


def _is_excluded(rel_posix: str, excludes: set[str]) -> bool:
    if rel_posix in excludes:
        return True
    return any(rel_posix.startswith(exc + "/") for exc in excludes)


def _strip_skill_body(skill_md: Path) -> None:
    text = skill_md.read_text()
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SystemExit(
            f"--strip-skill-body: {skill_md} has no YAML frontmatter to preserve."
        )
    skill_md.write_text(f"---{parts[1]}---\n")


def build_variant(
    *,
    source: Path,
    dest: Path,
    excludes: set[str],
    strip_skill_body: bool = False,
) -> list[Path]:
    if not source.is_dir():
        raise SystemExit(f"Source skill directory not found: {source}")

    missing = [exc for exc in excludes if not (source / exc).exists()]
    if missing:
        raise SystemExit(
            "These --exclude targets do not exist in the source skill: "
            + ", ".join(sorted(missing))
        )

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    copied: list[Path] = []
    for src_path in sorted(source.rglob("*")):
        rel = src_path.relative_to(source)
        if any(part in ALWAYS_SKIP_PARTS for part in rel.parts):
            continue
        if _is_excluded(rel.as_posix(), excludes):
            continue
        out_path = dest / rel
        if src_path.is_dir():
            out_path.mkdir(parents=True, exist_ok=True)
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, out_path)
            copied.append(rel)

    if strip_skill_body:
        skill_md = dest / "SKILL.md"
        if not skill_md.exists():
            raise SystemExit(
                "--strip-skill-body requires SKILL.md in the variant; "
                "do not exclude it."
            )
        _strip_skill_body(skill_md)

    return copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--variant-id",
        required=True,
        help="Variant directory name under eval/skills/.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Source skill root (default: {DEFAULT_SOURCE.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument(
        "--dest-root",
        type=Path,
        default=DEFAULT_DEST_ROOT,
        help=f"Output root (default: {DEFAULT_DEST_ROOT.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="REL_PATH",
        help=(
            "Skill-relative path to omit from the variant. May target a file "
            "(e.g. 'references/1_setup_problem.md') or a directory "
            "(e.g. 'references' to drop the whole folder). Repeatable."
        ),
    )
    parser.add_argument(
        "--strip-skill-body",
        action="store_true",
        help=(
            "After copying, rewrite the variant's SKILL.md to keep only its "
            "YAML frontmatter (name + description). Use for the 'no skill at "
            "all' baseline so the harness path resolves but no instructions "
            "are conveyed."
        ),
    )
    args = parser.parse_args()

    source = args.source.resolve()
    dest = (args.dest_root / args.variant_id / source.name).resolve()
    excludes = set(args.exclude)

    copied = build_variant(
        source=source,
        dest=dest,
        excludes=excludes,
        strip_skill_body=args.strip_skill_body,
    )

    rel_dest = dest.relative_to(REPO_ROOT) if dest.is_relative_to(REPO_ROOT) else dest
    print(f"Built variant '{args.variant_id}' at {rel_dest}")
    print(f"  source: {args.source}")
    print(f"  files copied: {len(copied)}")
    if excludes:
        print(f"  excluded: {sorted(excludes)}")
    if args.strip_skill_body:
        print("  SKILL.md body stripped to frontmatter only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
