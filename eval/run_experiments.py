"""ColPack agent evaluation runner.

Quickstart — typical commands, all run from the repo root
(``cd /Users/ldq/Work/ColPackAgent`` if you're not there). Requires
``OPENROUTER_API_KEY`` (or the matching key for whichever provider the
spec's ``models`` list points at) to be exported in the shell.

    # ──────────────────────────────────────────────────────────────────────
    # 0. One-time setup (skip if already done locally)
    # ──────────────────────────────────────────────────────────────────────

    # Build the skill variant referenced by every spec (~few seconds).
    python eval/build_skill_variant.py --variant-id full

    # Build the simulation + setup-only fixtures referenced by planning
    # and analysis specs (~2 minutes total; only the 2 full-sim fixtures
    # actually run simulations, the 3 setup-only fixtures are millisecond).
    python eval/bootstrap_fixtures.py

    # ──────────────────────────────────────────────────────────────────────
    # 1. Inspect the matrix without calling any LLM
    # ──────────────────────────────────────────────────────────────────────

    python -m eval.run_experiments plan --spec eval/specs/setup_eval.json
    # Prints: experiment_id, task/model/skill/repeat counts,
    #         and the full list of run_ids that will be generated.

    # ──────────────────────────────────────────────────────────────────────
    # 2. Dry-run — write planned_runs.json manifest, no execution
    # ──────────────────────────────────────────────────────────────────────

    python -m eval.run_experiments run --spec eval/specs/setup_eval.json --dry-run

    # ──────────────────────────────────────────────────────────────────────
    # 3. Smoke test — execute exactly one real run (a few cents, ~1 min)
    # ──────────────────────────────────────────────────────────────────────

    python -m eval.run_experiments run --spec eval/specs/setup_eval.json --limit 1
    # Outputs land in eval/runs/colpack_setup_eval/ :
    #     planned_runs.json   the expanded matrix
    #     results.jsonl       one record per run
    #     summary.json        aggregates: n_success, success_rate, tokens, cost
    #     conversations/      human-readable .md transcript per run

    # ──────────────────────────────────────────────────────────────────────
    # 4. Full suite — run every (task × model × skill × repeat) cell
    # ──────────────────────────────────────────────────────────────────────

    python -m eval.run_experiments run --spec eval/specs/setup_eval.json
    python -m eval.run_experiments run --spec eval/specs/planning_eval.json
    python -m eval.run_experiments run --spec eval/specs/analysis_eval.json

    # ──────────────────────────────────────────────────────────────────────
    # 5. Pre-run cleanup of stale agent-generated working_dirs
    # ──────────────────────────────────────────────────────────────────────

    # Removes everything under spec.working_dir_root EXCEPT 'fixtures/'
    # before executing. Useful between multi-LLM passes so each run starts
    # from a clean eval/data/.
    python -m eval.run_experiments run --spec eval/specs/setup_eval.json --clean-data

    # Or run cleanup standalone — preview first, then confirm:
    python -m eval.run_experiments clean --spec eval/specs/setup_eval.json
    python -m eval.run_experiments clean --spec eval/specs/setup_eval.json --yes

    # ──────────────────────────────────────────────────────────────────────
    # 6. Compare more LLMs
    # ──────────────────────────────────────────────────────────────────────

    # Add entries to a spec's "models" array — no code changes needed.
    # Example (in eval/specs/setup_eval.json):
    #   "models": [
    #     { "model_id": "openrouter/google/gemini-3-flash-preview", "label": "gemini" },
    #     { "model_id": "openrouter/anthropic/claude-sonnet-4-6",   "label": "claude" },
    #     { "model_id": "openrouter/openai/gpt-4o",                 "label": "gpt4o"  }
    #   ]
    # Then re-run step 4. The runner expands the matrix to N_tasks × N_models
    # runs and writes a separate transcript per (task, model) pair.

    # ──────────────────────────────────────────────────────────────────────
    # NOTE on scoring
    # ──────────────────────────────────────────────────────────────────────
    #
    # ``success_rate`` in summary.json is currently a LIVENESS check only —
    # a run is marked success if no turn reported a query/system error. It
    # does NOT verify tool-call correctness, adversarial refusal, or
    # interpretation quality. For L4–L5 adversarial tasks and the L2
    # analysis interpretation task, read the conversation transcripts in
    # eval/runs/<id>/conversations/ rather than trusting success_rate.
    # See eval/README.md "Scoring" section for the planned hybrid upgrade.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opencode_agent_sdk.types import AssistantMessage, ResultMessage, SystemMessage

from agent import app as agent_app
from colpack.workflow_helper import WORKING_DIR_ROOT_ENV_VAR
from eval.experiment_types import (
    ExperimentSpec,
    PlannedRun,
    RunResult,
    TokenUsageRecord,
    TurnResult,
    dataclass_to_json,
    expand_planned_runs,
    load_experiment_spec,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or run ColPack agent evaluation experiments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Expand an experiment spec into a run matrix.")
    plan_parser.add_argument("--spec", type=Path, required=True, help="Path to the experiment JSON spec.")
    plan_parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Write the planned run manifest into the experiment output directory.",
    )

    run_parser = subparsers.add_parser("run", help="Execute an experiment spec.")
    run_parser.add_argument("--spec", type=Path, required=True, help="Path to the experiment JSON spec.")
    run_parser.add_argument("--limit", type=int, default=0, help="Optional cap on the number of planned runs to execute.")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the planned runs for the experiment; do not execute them.",
    )
    run_parser.add_argument(
        "--no-bootstrap-skill",
        action="store_true",
        help="Disable the ColPack capability bootstrap even if the spec enables it.",
    )
    run_parser.add_argument(
        "--clean-data",
        action="store_true",
        help="Before running, remove eval-generated working_dirs from spec.working_dir_root (preserving fixtures/).",
    )
    run_parser.add_argument(
        "--sdk-trace",
        action="store_true",
        help="Enable verbose opencode_agent_sdk transport logs (disabled by default).",
    )

    clean_parser = subparsers.add_parser(
        "clean",
        help="Remove eval-generated working_dirs from a spec's working_dir_root, preserving fixtures/.",
    )
    clean_parser.add_argument("--spec", type=Path, required=True, help="Path to the experiment JSON spec.")
    clean_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation step and delete immediately.",
    )

    return parser


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_eval_logging(sdk_trace: bool) -> None:
    logging.basicConfig(level=logging.WARNING)
    if sdk_trace:
        return

    noisy_loggers = (
        "opencode_agent_sdk",
        "opencode_agent_sdk.client",
        "opencode_agent_sdk._internal.transport",
        "opencode_agent_sdk._internal.acp",
    )
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.ERROR)


def _ensure_output_dir(spec: ExperimentSpec) -> Path:
    spec.output_dir.mkdir(parents=True, exist_ok=True)
    return spec.output_dir


def _ensure_working_dir_root(spec: ExperimentSpec) -> Path:
    spec.working_dir_root.mkdir(parents=True, exist_ok=True)
    return spec.working_dir_root


# Names under spec.working_dir_root that must NOT be deleted by clean operations.
# 'fixtures' holds the bootstrap-built simulation/setup fixtures (expensive
# to rebuild) referenced by planning and analysis specs via {{fixture:...}}.
_PRESERVE_NAMES = frozenset({"fixtures"})


def _clean_working_dir_root(
    working_dir_root: Path,
    *,
    preserve: frozenset[str] = _PRESERVE_NAMES,
) -> list[str]:
    """Remove eval-generated content under working_dir_root, preserving the
    named entries (by default, 'fixtures'). Returns a list of removed entry names.
    """
    if not working_dir_root.exists():
        return []
    removed: list[str] = []
    for child in sorted(working_dir_root.iterdir()):
        if child.name in preserve:
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            continue
        removed.append(child.name)
    return removed


def _manifest_path(spec: ExperimentSpec) -> Path:
    return _ensure_output_dir(spec) / "planned_runs.json"


def _results_path(spec: ExperimentSpec) -> Path:
    return _ensure_output_dir(spec) / "results.jsonl"


def _legacy_results_path(spec: ExperimentSpec) -> Path:
    return _ensure_output_dir(spec) / "results.json"


def _summary_path(spec: ExperimentSpec) -> Path:
    return _ensure_output_dir(spec) / "summary.json"


def _conversation_dir(spec: ExperimentSpec) -> Path:
    path = _ensure_output_dir(spec) / "conversations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _conversation_path(spec: ExperimentSpec, run_id: str) -> Path:
    safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id)
    return _conversation_dir(spec) / f"{safe_run_id}.md"


def _write_manifest(spec: ExperimentSpec, planned_runs: tuple[PlannedRun, ...]) -> Path:
    payload = {
        "experiment": dataclass_to_json(spec),
        "planned_runs": [dataclass_to_json(run) for run in planned_runs],
        "generated_at": _utc_now(),
    }
    manifest_path = _manifest_path(spec)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def _append_result(result_path: Path, result: RunResult) -> None:
    with result_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclass_to_json(result), ensure_ascii=True) + "\n")


def _write_conversation_transcript(spec: ExperimentSpec, result: RunResult) -> Path:
    transcript_path = _conversation_path(spec, result.run_id)
    lines: list[str] = [
        f"# Conversation Transcript: {result.run_id}",
        "",
        f"- experiment_id: `{result.experiment_id}`",
        f"- task_id: `{result.task_id}`",
        f"- model_id: `{result.model_id}`",
        f"- skill_id: `{result.skill_id}`",
        f"- repeat_index: `{result.repeat_index}`",
        f"- success: `{result.success}`",
        "",
    ]

    for turn in result.turn_results:
        lines.extend(
            [
                f"## Turn {turn.turn_index}",
                "",
                "**User**",
                "",
                turn.user_input if turn.user_input else "[empty]",
                "",
                "**Assistant**",
                "",
                turn.assistant_text if turn.assistant_text else "[no text response]",
                "",
            ]
        )
        if turn.system_errors:
            lines.append("**System Errors**")
            lines.append("")
            for error in turn.system_errors:
                lines.append(f"- {error}")
            lines.append("")

    transcript_path.write_text("\n".join(lines), encoding="utf-8")
    return transcript_path


def _sum_usage(left: TokenUsageRecord, right: TokenUsageRecord) -> TokenUsageRecord:
    return TokenUsageRecord(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cache_creation_input_tokens=(left.cache_creation_input_tokens or 0) + (right.cache_creation_input_tokens or 0),
        cache_read_input_tokens=(left.cache_read_input_tokens or 0) + (right.cache_read_input_tokens or 0),
    )


def _usage_field(usage: Any, *keys: str, default: Any = None) -> Any:
    """Read the first matching key from ResultMessage.usage.

    The usage payload may be a dict or a typed object depending on the
    underlying SDK build; key names also vary across providers (Anthropic
    uses input_tokens/output_tokens; OpenAI/OpenRouter use
    prompt_tokens/completion_tokens). Try each candidate in order.
    """
    if usage is None:
        return default
    for key in keys:
        if isinstance(usage, dict):
            if key in usage and usage[key] is not None:
                return usage[key]
        else:
            value = getattr(usage, key, None)
            if value is not None:
                return value
    return default


def _usage_from_result_message(message: ResultMessage) -> TokenUsageRecord:
    """Build a TokenUsageRecord from ResultMessage.usage.

    The usage payload's shape varies by provider/SDK build:
      - Anthropic: input_tokens, output_tokens, cache_creation_input_tokens,
        cache_read_input_tokens (snake_case attrs).
      - OpenAI/OpenRouter generic: prompt_tokens, completion_tokens,
        cached_tokens (snake_case dict).
      - Gemini via the agent SDK: inputTokens, outputTokens, cachedReadTokens,
        thoughtTokens (camelCase dict).
    Try each naming convention in order so we capture tokens regardless of model.
    """
    usage = getattr(message, "usage", None)
    return TokenUsageRecord(
        input_tokens=int(_usage_field(usage, "input_tokens", "inputTokens", "prompt_tokens", default=0) or 0),
        output_tokens=int(_usage_field(usage, "output_tokens", "outputTokens", "completion_tokens", default=0) or 0),
        cache_creation_input_tokens=_usage_field(usage, "cache_creation_input_tokens"),
        cache_read_input_tokens=_usage_field(usage, "cache_read_input_tokens", "cachedReadTokens", "cached_tokens"),
    )


async def _collect_turn_result(
    client,
    background_state,
    workflow_session_active: bool,
) -> tuple[TurnResult, Any, bool]:
    response_state = agent_app.QueryResponseState()
    seen_tool_ids: set[str] = set()
    session_id = ""
    sdk_turn_count = 0
    usage = TokenUsageRecord()
    total_cost_usd = 0.0
    response_duration_ms = 0.0

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            response_state.had_assistant_message = True
            for tool_use in agent_app._extract_tool_uses(message):
                if tool_use.id in seen_tool_ids:
                    continue
                seen_tool_ids.add(tool_use.id)
                background_state, response_state, workflow_session_active = await agent_app._handle_tool_use(
                    tool_use=tool_use,
                    background_state=background_state,
                    response_state=response_state,
                    workflow_session_active=workflow_session_active,
                    show_output=False,
                )

            extracted = agent_app._extract_assistant_text(message)
            if extracted:
                response_state.final_text = extracted
        elif isinstance(message, SystemMessage):
            system_error = agent_app._extract_system_error(message)
            if system_error:
                response_state.system_errors.append(system_error)
        elif isinstance(message, ResultMessage):
            if message.is_error:
                response_state.query_had_error = True
            usage = _sum_usage(usage, _usage_from_result_message(message))
            total_cost_usd += message.total_cost_usd
            response_duration_ms += message.duration_ms
            session_id = message.session_id or session_id
            sdk_turn_count = max(sdk_turn_count, message.num_turns)

    background_state = await agent_app._finalize_query_monitoring(
        background_state=background_state,
        response_state=response_state,
        show_status_output=False,
    )

    turn_result = TurnResult(
        turn_index=0,
        user_input="",
        routed_user_input="",
        route_kind=None,
        assistant_text=response_state.final_text,
        system_errors=tuple(response_state.system_errors),
        query_had_error=response_state.query_had_error,
        response_duration_ms=response_duration_ms,
        total_cost_usd=total_cost_usd,
        usage=usage,
        session_id=session_id,
        sdk_turn_count=sdk_turn_count,
    )
    return turn_result, background_state, workflow_session_active


async def _execute_run_case(
    spec: ExperimentSpec,
    planned_run: PlannedRun,
    *,
    bootstrap_skill: bool,
) -> RunResult:
    normalized_model, provider_id = agent_app._resolve_model_and_provider(planned_run.model.model_id)
    agent_definition = agent_app.load_agent_definition(
        spec.agent_path,
        skill_path_override=planned_run.skill.skill_path,
    )

    started_at = _utc_now()
    wall_start = time.perf_counter()
    background_state = agent_app.BackgroundMonitorState()
    workflow_session_active = False
    turn_results: list[TurnResult] = []
    total_usage = TokenUsageRecord()
    total_cost_usd = 0.0
    client = None

    try:
        client = await agent_app._connect_client(
            agent_path=agent_definition.source_path,
            skill_path=agent_definition.skill_path,
            mcp_command=spec.mcp_command,
            normalized_model=normalized_model,
            provider_id=provider_id,
            mcp_env={WORKING_DIR_ROOT_ENV_VAR: str(spec.working_dir_root)},
        )
        if bootstrap_skill:
            background_state = await agent_app._bootstrap_skill_session(client, background_state)

        agent_mode_suffix = f"\n\nAGENT_MODE = {spec.agent_mode}" if spec.agent_mode else ""

        for index, user_message in enumerate(planned_run.task.user_messages, start=1):
            routed_message = user_message + agent_mode_suffix
            attempt = 0
            while attempt < 2:
                try:
                    await client.query(routed_message)
                    turn_result, background_state, workflow_session_active = await _collect_turn_result(
                        client=client,
                        background_state=background_state,
                        workflow_session_active=workflow_session_active,
                    )
                    turn_result = replace(
                        turn_result,
                        turn_index=index,
                        user_input=user_message,
                        routed_user_input=routed_message,
                        route_kind=("agent_mode_" + spec.agent_mode) if spec.agent_mode else None,
                    )
                    turn_results.append(turn_result)
                    total_usage = _sum_usage(total_usage, turn_result.usage)
                    total_cost_usd += turn_result.total_cost_usd
                    break
                except Exception as exc:
                    if attempt == 0 and agent_app._is_timeout_like_error(str(exc)):
                        await client.disconnect()
                        client = await agent_app._connect_client(
                            agent_path=agent_definition.source_path,
                            skill_path=agent_definition.skill_path,
                            mcp_command=spec.mcp_command,
                            normalized_model=normalized_model,
                            provider_id=provider_id,
                            mcp_env={WORKING_DIR_ROOT_ENV_VAR: str(spec.working_dir_root)},
                        )
                        attempt += 1
                        continue
                    turn_results.append(
                        TurnResult(
                            turn_index=index,
                            user_input=user_message,
                            routed_user_input=routed_message,
                            route_kind=("agent_mode_" + spec.agent_mode) if spec.agent_mode else None,
                            assistant_text="",
                            system_errors=(str(exc),),
                            query_had_error=True,
                            response_duration_ms=0.0,
                            total_cost_usd=0.0,
                            usage=TokenUsageRecord(),
                        )
                    )
                    break
    finally:
        background_state = await agent_app._stop_background_monitor(background_state)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    success = all(not turn.query_had_error and not turn.system_errors for turn in turn_results)
    completed_at = _utc_now()
    wall_time_seconds = time.perf_counter() - wall_start
    return RunResult(
        run_id=planned_run.run_id,
        experiment_id=spec.experiment_id,
        task_id=planned_run.task.task_id,
        model_id=planned_run.model.model_id,
        skill_id=planned_run.skill.skill_id,
        repeat_index=planned_run.repeat_index,
        user_profile_id=planned_run.user_profile.profile_id if planned_run.user_profile is not None else None,
        success=success,
        started_at=started_at,
        completed_at=completed_at,
        wall_time_seconds=wall_time_seconds,
        total_cost_usd=total_cost_usd,
        usage=total_usage,
        turn_results=tuple(turn_results),
        metadata={
            "agent_path": str(spec.agent_path),
            "resolved_skill_path": str(planned_run.skill.skill_path),
            "working_dir_root": str(spec.working_dir_root),
            "bootstrap_skill": bootstrap_skill,
        },
    )


def _summarize_results(spec: ExperimentSpec, run_results: list[RunResult]) -> dict[str, Any]:
    success_count = sum(1 for result in run_results if result.success)
    return {
        "experiment_id": spec.experiment_id,
        "generated_at": _utc_now(),
        "n_runs": len(run_results),
        "n_success": success_count,
        "success_rate": (success_count / len(run_results)) if run_results else 0.0,
        "total_cost_usd": sum(result.total_cost_usd for result in run_results),
        "total_wall_time_seconds": sum(result.wall_time_seconds for result in run_results),
        "total_input_tokens": sum(result.usage.input_tokens for result in run_results),
        "total_output_tokens": sum(result.usage.output_tokens for result in run_results),
    }


async def _run_experiment(spec: ExperimentSpec, *, limit: int, dry_run: bool, bootstrap_skill: bool) -> int:
    planned_runs = expand_planned_runs(spec)
    if limit > 0:
        planned_runs = planned_runs[:limit]

    _ensure_working_dir_root(spec)
    manifest_path = _write_manifest(spec, planned_runs)
    print(f"Manifest written to {manifest_path}")
    print(f"Planned runs: {len(planned_runs)}")

    if dry_run:
        for planned_run in planned_runs:
            print(f"- {planned_run.run_id}")
        return 0

    result_path = _results_path(spec)
    legacy_result_path = _legacy_results_path(spec)
    if legacy_result_path.exists() and legacy_result_path != result_path:
        legacy_result_path.unlink()
    if result_path.exists():
        result_path.unlink()

    run_results: list[RunResult] = []
    for index, planned_run in enumerate(planned_runs, start=1):
        print(
            f"[{index}/{len(planned_runs)}] "
            f"task={planned_run.task.task_id} "
            f"model={planned_run.model.model_id} "
            f"skill={planned_run.skill.skill_id}"
        )
        run_result = await _execute_run_case(
            spec,
            planned_run,
            bootstrap_skill=bootstrap_skill,
        )
        _append_result(result_path, run_result)
        _write_conversation_transcript(spec, run_result)
        run_results.append(run_result)

    summary = _summarize_results(spec, run_results)
    summary_path = _summary_path(spec)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Results written to {result_path}")
    print(f"Summary written to {summary_path}")
    return 0


def _print_plan(spec: ExperimentSpec, *, write_manifest: bool) -> int:
    planned_runs = expand_planned_runs(spec)
    print(f"Experiment: {spec.experiment_id}")
    print(f"Description: {spec.description}")
    print(f"Tasks: {len(spec.tasks)} | Models: {len(spec.models)} | Skills: {len(spec.skills)} | Repeats: {spec.repeats}")
    print(f"Planned runs: {len(planned_runs)}")
    for planned_run in planned_runs:
        print(
            f"- {planned_run.run_id} "
            f"(task={planned_run.task.task_id}, model={planned_run.model.model_id}, skill={planned_run.skill.skill_id}, repeat={planned_run.repeat_index})"
        )
    if write_manifest:
        manifest_path = _write_manifest(spec, planned_runs)
        print(f"Manifest written to {manifest_path}")
    return 0


def _do_clean(spec: ExperimentSpec, *, confirmed: bool) -> int:
    root = spec.working_dir_root
    if not root.exists():
        print(f"[clean] {root} does not exist; nothing to do.")
        return 0
    candidates = sorted(c.name for c in root.iterdir() if c.name not in _PRESERVE_NAMES)
    if not candidates:
        print(f"[clean] {root} is already clean (only preserved entries remain: {sorted(_PRESERVE_NAMES)}).")
        return 0
    if not confirmed:
        print(f"[clean] would remove {len(candidates)} entries from {root}:")
        for name in candidates:
            print(f"    {name}")
        print(f"[clean] preserving: {sorted(_PRESERVE_NAMES)}")
        print("[clean] re-run with --yes to proceed.")
        return 0
    removed = _clean_working_dir_root(root)
    print(f"[clean] removed {len(removed)} entries from {root}: {removed}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    _configure_eval_logging(sdk_trace=getattr(args, "sdk_trace", False))
    spec = load_experiment_spec(args.spec)

    if args.command == "plan":
        return _print_plan(spec, write_manifest=args.write_manifest)

    if args.command == "clean":
        return _do_clean(spec, confirmed=args.yes)

    if getattr(args, "clean_data", False):
        removed = _clean_working_dir_root(spec.working_dir_root)
        if removed:
            print(f"[clean] removed {len(removed)} entries from {spec.working_dir_root} (preserving {sorted(_PRESERVE_NAMES)})")

    return asyncio.run(
        _run_experiment(
            spec,
            limit=args.limit,
            dry_run=args.dry_run,
            bootstrap_skill=(False if args.no_bootstrap_skill else spec.bootstrap_skill),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
