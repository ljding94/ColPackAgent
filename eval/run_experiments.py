from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
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


# Off-rail detection ----------------------------------------------------------
#
# The set of ColPack MCP tool suffixes the runner watches. Tool names from the
# SDK may arrive prefixed (e.g. ``colpack__setup_simulation_problem_tool``),
# bare, or with other separators — match by suffix.
_COLPACK_CONTROLLED_SUFFIXES: tuple[str, ...] = (
    "get_colpack_capabilities_tool",
    "setup_simulation_problem_tool",
    "plan_simulation_runs_tool",
    "execute_simulation_workflow_tool",
    "analyze_simulation_runs_tool",
    "get_simulation_workflow_status_tool",
)

# Per-stage allowed colpack tools. `get_colpack_capabilities_tool` is always
# allowed — bootstrap_skill calls it once at session start. Tasks at a given
# stage may call only the listed tool plus capabilities; anything else from
# `_COLPACK_CONTROLLED_SUFFIXES` is "off-rail".
_STAGE_ALLOWED_SUFFIXES: dict[str, frozenset[str]] = {
    "setup": frozenset({"get_colpack_capabilities_tool", "setup_simulation_problem_tool"}),
    "planning": frozenset({"get_colpack_capabilities_tool", "plan_simulation_runs_tool"}),
    "analysis": frozenset({"get_colpack_capabilities_tool", "analyze_simulation_runs_tool"}),
}


def _tool_name_matches_suffix(tool_name: str, suffix: str) -> bool:
    return tool_name == suffix or tool_name.endswith(f"_{suffix}")


def _match_controlled_suffix(tool_name: str) -> str | None:
    """Return the controlled-suffix this tool matches, or None if it isn't a
    controlled colpack tool (so non-colpack tools like Read/Bash never count
    as off-rail)."""
    for suffix in _COLPACK_CONTROLLED_SUFFIXES:
        if _tool_name_matches_suffix(tool_name, suffix):
            return suffix
    return None


def _allowed_suffixes_for_task_stage(stage: str | None) -> frozenset[str] | None:
    """Look up the allowed colpack tool suffixes for a task's stage.

    Returns None if the stage is unknown or empty (no constraint enforced).
    """
    if not stage:
        return None
    return _STAGE_ALLOWED_SUFFIXES.get(stage)


def _probe_openrouter_served_by(model_id_full: str, api_key: str) -> tuple[str | None, str | None]:
    """Send a 1-token chat-completion to OpenRouter and read back which
    sub-backend served it (e.g. "Google" for google-vertex, "Amazon Bedrock",
    "Anthropic"). Returns (served_by, error). The agent SDK does not surface
    this field from the actual eval requests, so we probe once per model up
    front to record routing for the run.
    """
    cleaned = model_id_full.strip()
    if cleaned.startswith("openrouter/"):
        cleaned = cleaned[len("openrouter/"):]

    body = json.dumps({
        "model": cleaned,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("provider"), None
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", str(exc))
        except Exception:
            err = f"HTTP {exc.code}"
        return None, err
    except Exception as exc:  # pragma: no cover — surface any transport issue
        return None, f"{type(exc).__name__}: {exc}"


def _probe_provider_routing(spec: ExperimentSpec) -> dict[str, dict[str, str | None]]:
    """Probe each unique model in the spec, return {model_id: {served_by, error}}.

    Skips silently (returns {}) if OPENROUTER_API_KEY is unset, so non-OpenRouter
    setups don't break.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return {}

    seen: dict[str, dict[str, str | None]] = {}
    for model in spec.models:
        if model.model_id in seen:
            continue
        served_by, error = _probe_openrouter_served_by(model.model_id, api_key)
        seen[model.model_id] = {"served_by": served_by, "error": error}
    return seen


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
    allowed_tool_suffixes: frozenset[str] | None = None,
) -> tuple[TurnResult, Any, bool]:
    response_state = agent_app.QueryResponseState()
    seen_tool_ids: set[str] = set()
    session_id = ""
    sdk_turn_count = 0
    usage = TokenUsageRecord()
    total_cost_usd = 0.0
    response_duration_ms = 0.0
    off_rail_tool_calls: list[dict[str, str]] = []

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            response_state.had_assistant_message = True
            for tool_use in agent_app._extract_tool_uses(message):
                if tool_use.id in seen_tool_ids:
                    continue
                seen_tool_ids.add(tool_use.id)

                # Off-rail detection: if this is a controlled colpack tool that
                # is NOT in the task's allowed set, record it. Non-colpack tools
                # (Read, Bash, etc.) and never-controlled tools pass through.
                if allowed_tool_suffixes is not None:
                    matched = _match_controlled_suffix(tool_use.name)
                    if matched is not None and matched not in allowed_tool_suffixes:
                        off_rail_tool_calls.append({
                            "tool_name": tool_use.name,
                            "matched_suffix": matched,
                        })

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
        off_rail_tool_calls=tuple(off_rail_tool_calls),
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

        # Derive allowed colpack tool suffixes from the task's stage so we can
        # detect (and shortcut on) any tool calls that fall outside scope.
        task_stage = planned_run.task.metadata.get("stage") if planned_run.task.metadata else None
        allowed_tool_suffixes = _allowed_suffixes_for_task_stage(task_stage)

        run_off_rail = False  # short-circuits the user-message loop on first off-rail turn

        for index, user_message in enumerate(planned_run.task.user_messages, start=1):
            if run_off_rail:
                break
            routed_message = user_message + agent_mode_suffix
            attempt = 0
            while attempt < 2:
                try:
                    await client.query(routed_message)
                    turn_result, background_state, workflow_session_active = await _collect_turn_result(
                        client=client,
                        background_state=background_state,
                        workflow_session_active=workflow_session_active,
                        allowed_tool_suffixes=allowed_tool_suffixes,
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
                    if turn_result.off_rail_tool_calls:
                        # Don't send any further user messages for this run —
                        # the agent already proceeded out of scope. We log
                        # what was attempted so it shows up in the report.
                        run_off_rail = True
                        offending = ", ".join(c["matched_suffix"] for c in turn_result.off_rail_tool_calls)
                        print(f"  [off-rail] task stage='{task_stage}' but agent called: {offending} — stopping run early")
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
    # Pull any user-supplied routing documentation from the model spec so it
    # round-trips into results.jsonl (e.g. expected_backend="google-vertex"
    # when the user has set OpenRouter account-level provider preferences).
    model_metadata = dict(planned_run.model.metadata) if planned_run.model.metadata else {}

    # Aggregate off-rail tool calls across every turn for run-level reporting.
    aggregated_off_rail: list[dict[str, str]] = []
    for turn in turn_results:
        aggregated_off_rail.extend(turn.off_rail_tool_calls)

    return RunResult(
        run_id=planned_run.run_id,
        experiment_id=spec.experiment_id,
        task_id=planned_run.task.task_id,
        model_id=planned_run.model.model_id,
        provider_id=provider_id,
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
        off_rail=bool(aggregated_off_rail),
        off_rail_tool_calls=tuple(aggregated_off_rail),
        metadata={
            "agent_path": str(spec.agent_path),
            "resolved_skill_path": str(planned_run.skill.skill_path),
            "working_dir_root": str(spec.working_dir_root),
            "bootstrap_skill": bootstrap_skill,
            "normalized_model": normalized_model,
            "model_label": planned_run.model.label,
            "model_metadata": model_metadata,
            "task_stage": planned_run.task.metadata.get("stage") if planned_run.task.metadata else None,
            "allowed_tool_suffixes": sorted(allowed_tool_suffixes) if allowed_tool_suffixes else None,
        },
    )


def _aggregate_block(results: list[RunResult]) -> dict[str, Any]:
    """Aggregate stats across a list of run results.

    `effective_input_tokens` = input_tokens + cache_read_input_tokens — the
    true context the model processed (cache-read tokens are *real* input
    served from the provider's prompt cache at discounted price). The bare
    `input_tokens` counts only the "fresh" portion and is provider-dependent,
    so use `effective_input_tokens` when comparing workload across providers.
    """
    n = len(results)
    n_success = sum(1 for r in results if r.success)
    n_off_rail = sum(1 for r in results if r.off_rail)
    cache_read = sum((r.usage.cache_read_input_tokens or 0) for r in results)
    fresh_input = sum(r.usage.input_tokens for r in results)
    return {
        "n_runs": n,
        "n_success": n_success,
        "success_rate": (n_success / n) if n else 0.0,
        "n_off_rail": n_off_rail,
        "off_rail_rate": (n_off_rail / n) if n else 0.0,
        "total_cost_usd": sum(r.total_cost_usd for r in results),
        "total_wall_time_seconds": sum(r.wall_time_seconds for r in results),
        "total_input_tokens": fresh_input,
        "total_cache_read_input_tokens": cache_read,
        "total_effective_input_tokens": fresh_input + cache_read,
        "total_output_tokens": sum(r.usage.output_tokens for r in results),
    }


def _summarize_results(
    spec: ExperimentSpec,
    run_results: list[RunResult],
    *,
    routing: dict[str, dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    # Group by model_id for the benchmarking breakdown.
    per_model: dict[str, list[RunResult]] = {}
    for r in run_results:
        per_model.setdefault(r.model_id, []).append(r)

    # Pull spec-level model metadata (label, expected_backend, etc.) by id so
    # the per-model summary can surface it without grepping results.jsonl.
    spec_models = {m.model_id: m for m in spec.models}
    routing = routing or {}

    def _per_model_block(model_id: str, runs: list[RunResult]) -> dict[str, Any]:
        block = _aggregate_block(runs)
        # provider_id is fixed per (model_id) since it's resolved from the model id.
        block["provider_id"] = runs[0].provider_id if runs else ""
        # Pre-flight probe result: which OpenRouter sub-backend served this model.
        if model_id in routing:
            info = routing[model_id]
            if info.get("served_by"):
                block["served_by_provider"] = info["served_by"]
            if info.get("error"):
                block["routing_probe_error"] = info["error"]
        # Deduped list of off-rail tool suffixes this model called across all
        # runs, so reviewers can see at a glance "this model drifted to X, Y."
        off_rail_tools_seen: set[str] = set()
        for r in runs:
            for call in r.off_rail_tool_calls:
                off_rail_tools_seen.add(call["matched_suffix"])
        if off_rail_tools_seen:
            block["off_rail_tools_seen"] = sorted(off_rail_tools_seen)
        m = spec_models.get(model_id)
        if m is not None:
            if m.label:
                block["label"] = m.label
            if m.metadata:
                block["model_metadata"] = dict(m.metadata)
        return block

    summary = {
        "experiment_id": spec.experiment_id,
        "generated_at": _utc_now(),
        **_aggregate_block(run_results),
        "per_model": {model_id: _per_model_block(model_id, runs) for model_id, runs in per_model.items()},
    }
    return summary


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

    # Pre-flight probe: capture which OpenRouter sub-backend (e.g. "Google" for
    # google-vertex, "Amazon Bedrock", "Anthropic") will serve each model in
    # this run. The agent SDK does not surface this from the actual eval
    # requests, so we record it once up front. Tiny cost (1-token request per
    # unique model) and extremely useful for paper-grade routing audit.
    routing = _probe_provider_routing(spec)
    if routing:
        print("Provider routing (served-by):")
        for mid, info in routing.items():
            if info["error"]:
                print(f"  ⚠️  {mid}: ERROR — {info['error']}")
            else:
                print(f"  {mid} → {info['served_by']}")

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

    summary = _summarize_results(spec, run_results, routing=routing)
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
