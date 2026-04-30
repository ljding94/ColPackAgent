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
    ModelSpec,
    PlannedRun,
    RunResult,
    TaskSpec,
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
    plan_parser.add_argument("--spec", type=Path, default=None, help="Path to the experiment JSON spec. Mutually exclusive with --all-specs.")
    plan_parser.add_argument(
        "--all-specs",
        action="store_true",
        help="Apply the command to every spec in eval/specs/ (matched as *_eval.json), in stage order: setup → planning → analysis → others.",
    )
    plan_parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Write the planned run manifest into the experiment output directory.",
    )
    plan_parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated list of exact model labels or model_ids to include (e.g. 'claude-haiku-4.5,claude-opus-4.7'). Defaults to all models in the spec.",
    )

    run_parser = subparsers.add_parser("run", help="Execute an experiment spec.")
    run_parser.add_argument("--spec", type=Path, default=None, help="Path to the experiment JSON spec. Mutually exclusive with --all-specs.")
    run_parser.add_argument(
        "--all-specs",
        action="store_true",
        help="Run every spec in eval/specs/ (matched as *_eval.json), in stage order: setup → planning → analysis → others. Same --models / --limit / --task-timeout apply to each.",
    )
    run_parser.add_argument("--limit", type=int, default=0, help="Optional cap on the number of planned runs to execute (per spec).")
    run_parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated list of exact model labels or model_ids to include (e.g. 'claude-haiku-4.5,claude-opus-4.7'). Defaults to all models in the spec.",
    )
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
        "--task-timeout",
        type=float,
        default=None,
        help=(
            "Per-task wall-time budget in seconds, overriding the stage default "
            "(setup/planning/analysis = 180s). Use a small value (e.g. 60) when iterating; "
            "a large one (e.g. 1800) when allowing slow workflow executions."
        ),
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
    clean_parser.add_argument("--spec", type=Path, default=None, help="Path to the experiment JSON spec. Mutually exclusive with --all-specs.")
    clean_parser.add_argument(
        "--all-specs",
        action="store_true",
        help="Apply clean to every spec in eval/specs/ (matched as *_eval.json).",
    )
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


def _ensure_working_dir_root(spec: ExperimentSpec) -> Path:
    spec.working_dir_root.mkdir(parents=True, exist_ok=True)
    return spec.working_dir_root


def _model_working_dir_root(spec: ExperimentSpec, model: ModelSpec) -> Path:
    """Per-model namespace under spec.working_dir_root.

    Each model gets its own subfolder so simulation artifacts (2d_nvt_disk/,
    2d_nvt_disk_capsule/, …) created by setup-stage tasks don't collide or
    pollute one another across models. Fixtures stay at the shared
    spec.working_dir_root / 'fixtures' since tasks reference them by absolute
    path and every model consumes them identically.
    """
    path = spec.working_dir_root / _model_label_for_path(model)
    path.mkdir(parents=True, exist_ok=True)
    return path


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

# The single primary tool a task at each stage is expected to call. If the
# agent never calls this tool (e.g. it stayed waiting for a confirmation that
# wasn't coming despite explicit "no confirmation needed" instruction in the
# prompt), the run is treated as a failure-to-act.
_STAGE_EXPECTED_TOOL: dict[str, str] = {
    "setup": "setup_simulation_problem_tool",
    "planning": "plan_simulation_runs_tool",
    "analysis": "analyze_simulation_runs_tool",
}

# Per-stage default task timeout (seconds). All three stages call a single
# fast tool (write a JSON, read existing data) and should complete in a few
# seconds — three minutes is a generous cap that catches a hung model or an
# off-rail simulation execution before it burns more cost.
_STAGE_TIMEOUT_SECONDS: dict[str, float] = {
    "setup": 50.0,
    "planning": 50.0,
    "analysis": 50.0,
}
_DEFAULT_TASK_TIMEOUT_SECONDS = 50.0


def _task_timeout_seconds(
    spec: ExperimentSpec,
    task: TaskSpec,
    *,
    cli_override: float | None = None,
) -> float:
    """Resolve a task's wall-time budget (seconds).

    Precedence: --task-timeout CLI flag > task.metadata.timeout_seconds >
    spec.metadata.default_timeout_seconds > stage default > global default.
    """
    if cli_override is not None and cli_override > 0:
        return cli_override
    if task.metadata and "timeout_seconds" in task.metadata:
        return float(task.metadata["timeout_seconds"])
    if spec.metadata and "default_timeout_seconds" in spec.metadata:
        return float(spec.metadata["default_timeout_seconds"])
    stage = task.metadata.get("stage") if task.metadata else None
    if stage and stage in _STAGE_TIMEOUT_SECONDS:
        return _STAGE_TIMEOUT_SECONDS[stage]
    return _DEFAULT_TASK_TIMEOUT_SECONDS


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


def _spec_stage(spec: ExperimentSpec) -> str:
    """The stage label (setup / planning / analysis) for a spec, taken from
    spec.metadata.stage. Falls back to spec.experiment_id if missing so the
    runner doesn't crash on a less-conventional spec."""
    stage = (spec.metadata or {}).get("stage")
    return stage if isinstance(stage, str) and stage else spec.experiment_id


def _model_label_for_path(model: ModelSpec) -> str:
    """Filesystem-safe label for a model. Prefers the human label from the
    spec; falls back to the last segment of model_id."""
    label = model.label or model.model_id.rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", label)


def _model_stage_dir(spec: ExperimentSpec, model: ModelSpec) -> Path:
    """<output_dir>/<model_label>/<stage>/ — created on access."""
    path = spec.output_dir / _model_label_for_path(model) / _spec_stage(spec)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(spec: ExperimentSpec) -> Path:
    """Cross-model planning manifest. One per spec, sits alongside the
    per-model output dirs at <output_dir>/<experiment_id>_manifest.json."""
    spec.output_dir.mkdir(parents=True, exist_ok=True)
    return spec.output_dir / f"{spec.experiment_id}_manifest.json"


def _results_path(spec: ExperimentSpec, model: ModelSpec) -> Path:
    return _model_stage_dir(spec, model) / "results.jsonl"


def _summary_path(spec: ExperimentSpec, model: ModelSpec) -> Path:
    return _model_stage_dir(spec, model) / "summary.json"


def _conversation_path(spec: ExperimentSpec, model: ModelSpec, run_id: str) -> Path:
    conv_dir = _model_stage_dir(spec, model) / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id)
    return conv_dir / f"{safe_run_id}.md"


def _filter_models(spec: ExperimentSpec, models_arg: str | None) -> ExperimentSpec:
    """Restrict spec.models to those whose label OR model_id exactly matches
    one of the comma-separated tokens in models_arg. Empty/None returns the
    spec unchanged. Errors loudly if any token matches no model.

    Exact match (not substring) so that ambiguous tokens like "claude" do not
    silently pull in models you didn't intend.
    """
    if not models_arg:
        return spec
    tokens = [t.strip() for t in models_arg.split(",") if t.strip()]
    if not tokens:
        return spec
    by_key: dict[str, ModelSpec] = {}
    for model in spec.models:
        if model.label:
            by_key[model.label] = model
        by_key[model.model_id] = model
    selected: list[ModelSpec] = []
    seen_ids: set[str] = set()
    unmatched: list[str] = []
    for token in tokens:
        match = by_key.get(token)
        if match is None:
            unmatched.append(token)
            continue
        if match.model_id not in seen_ids:
            seen_ids.add(match.model_id)
            selected.append(match)
    if unmatched:
        available = [m.label or m.model_id for m in spec.models]
        raise ValueError(
            f"--models token(s) {unmatched} did not match any model in spec. "
            f"Available labels: {available}"
        )
    return replace(spec, models=tuple(selected))


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


def _write_conversation_transcript(spec: ExperimentSpec, model: ModelSpec, result: RunResult) -> Path:
    transcript_path = _conversation_path(spec, model, result.run_id)
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
    called_tool_suffixes: list[str] = []

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            response_state.had_assistant_message = True
            for tool_use in agent_app._extract_tool_uses(message):
                if tool_use.id in seen_tool_ids:
                    continue
                seen_tool_ids.add(tool_use.id)

                # Track all controlled-colpack-tool calls. Non-colpack tools
                # (Read, Bash, etc.) don't count toward the called/off-rail set.
                matched = _match_controlled_suffix(tool_use.name)
                if matched is not None:
                    if matched not in called_tool_suffixes:
                        called_tool_suffixes.append(matched)
                    # Off-rail detection: controlled tool NOT in the task's allowed set.
                    if allowed_tool_suffixes is not None and matched not in allowed_tool_suffixes:
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
        called_tool_suffixes=tuple(called_tool_suffixes),
    )
    return turn_result, background_state, workflow_session_active


async def _execute_run_case(
    spec: ExperimentSpec,
    planned_run: PlannedRun,
    *,
    bootstrap_skill: bool,
    task_timeout_override: float | None = None,
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

    # Derive task-level scope info up front so it's available even if the
    # SDK/client fails before we get into the conversation loop.
    task_stage = planned_run.task.metadata.get("stage") if planned_run.task.metadata else None
    allowed_tool_suffixes = _allowed_suffixes_for_task_stage(task_stage)
    agent_mode_suffix = f"\n\nAGENT_MODE = {spec.agent_mode}" if spec.agent_mode else ""

    # Wall-time budget for the whole task (all turns combined). Catches the
    # case where a model goes off-rail and triggers a slow simulation, OR
    # silently hangs on a tool call without ever returning a ResultMessage.
    task_timeout = _task_timeout_seconds(spec, planned_run.task, cli_override=task_timeout_override)
    task_deadline = time.monotonic() + task_timeout

    # Per-model namespace for simulation working dirs so artifacts created by
    # one LLM don't pollute another's data folder.
    model_data_root = _model_working_dir_root(spec, planned_run.model)

    try:
        client = await agent_app._connect_client(
            agent_path=agent_definition.source_path,
            skill_path=agent_definition.skill_path,
            mcp_command=spec.mcp_command,
            normalized_model=normalized_model,
            provider_id=provider_id,
            mcp_env={WORKING_DIR_ROOT_ENV_VAR: str(model_data_root)},
        )
        if bootstrap_skill:
            background_state = await agent_app._bootstrap_skill_session(client, background_state)

        run_off_rail = False  # short-circuits the user-message loop on first off-rail turn
        run_timed_out = False  # set when the task wall-time budget is exhausted

        for index, user_message in enumerate(planned_run.task.user_messages, start=1):
            if run_off_rail or run_timed_out:
                break
            routed_message = user_message + agent_mode_suffix
            attempt = 0
            while attempt < 2:
                remaining = task_deadline - time.monotonic()
                if remaining <= 0:
                    turn_results.append(
                        TurnResult(
                            turn_index=index,
                            user_input=user_message,
                            routed_user_input=routed_message,
                            route_kind=("agent_mode_" + spec.agent_mode) if spec.agent_mode else None,
                            assistant_text="",
                            system_errors=(f"task timeout exceeded ({task_timeout:.0f}s) before turn {index} could be sent",),
                            query_had_error=True,
                            response_duration_ms=0.0,
                            total_cost_usd=0.0,
                            usage=TokenUsageRecord(),
                        )
                    )
                    run_timed_out = True
                    print(f"  [timeout] task='{planned_run.task.task_id}' exceeded {task_timeout:.0f}s budget — aborting run")
                    break
                try:
                    assert client is not None  # set above; narrows for the closure below
                    active_client = client
                    async def _do_turn():
                        await active_client.query(routed_message)
                        return await _collect_turn_result(
                            client=active_client,
                            background_state=background_state,
                            workflow_session_active=workflow_session_active,
                            allowed_tool_suffixes=allowed_tool_suffixes,
                        )
                    turn_result, background_state, workflow_session_active = await asyncio.wait_for(
                        _do_turn(), timeout=remaining
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
                except asyncio.TimeoutError:
                    turn_results.append(
                        TurnResult(
                            turn_index=index,
                            user_input=user_message,
                            routed_user_input=routed_message,
                            route_kind=("agent_mode_" + spec.agent_mode) if spec.agent_mode else None,
                            assistant_text="",
                            system_errors=(f"task timeout exceeded ({task_timeout:.0f}s) on turn {index}",),
                            query_had_error=True,
                            response_duration_ms=0.0,
                            total_cost_usd=0.0,
                            usage=TokenUsageRecord(),
                        )
                    )
                    run_timed_out = True
                    print(f"  [timeout] task='{planned_run.task.task_id}' exceeded {task_timeout:.0f}s budget — aborting run")
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
                            mcp_env={WORKING_DIR_ROOT_ENV_VAR: str(model_data_root)},
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

    completed_at = _utc_now()
    wall_time_seconds = time.perf_counter() - wall_start
    # Pull any user-supplied routing documentation from the model spec so it
    # round-trips into results.jsonl (e.g. expected_backend="google-vertex"
    # when the user has set OpenRouter account-level provider preferences).
    model_metadata = dict(planned_run.model.metadata) if planned_run.model.metadata else {}

    # Aggregate off-rail and called-tool sets across every turn for run-level reporting.
    aggregated_off_rail: list[dict[str, str]] = []
    tools_called_set: list[str] = []
    total_output_tokens = 0
    for turn in turn_results:
        aggregated_off_rail.extend(turn.off_rail_tool_calls)
        for suffix in turn.called_tool_suffixes:
            if suffix not in tools_called_set:
                tools_called_set.append(suffix)
        total_output_tokens += turn.usage.output_tokens

    # Was the expected stage tool ever called? Required up front because
    # success now depends on it (see strict success criterion below).
    expected_tool = _STAGE_EXPECTED_TOOL.get(task_stage) if task_stage else None
    expected_tool_called = (expected_tool is None) or (expected_tool in tools_called_set)

    # Strict success — "did the agent do its job?", not "did anything not crash?"
    # Default is FAILURE; the run must produce positive evidence to be marked
    # successful. This catches silent SDK / model-id failures (zero output,
    # no errors raised) which liveness alone would mistakenly call success.
    #
    # Non-adversarial tasks: success requires the expected stage tool to have
    # been called, no drift past the stage, and no errors.
    #
    # Adversarial tasks (L4-L5): the *expected* behavior is for the agent to
    # refuse / clarify, so requiring `expected_tool_called` would invert the
    # criterion. Manual transcript review judges the refusal quality (see
    # README "Scoring" — currently TODO for hybrid scoring). Here we require
    # only liveness + non-silent output, so a silent SDK failure still fails.
    no_errors = all(not t.query_had_error and not t.system_errors for t in turn_results)
    made_progress = (
        total_output_tokens > 0
        or bool(tools_called_set)
        or bool(aggregated_off_rail)
    )
    is_adversarial = bool(planned_run.task.metadata.get("adversarial")) if planned_run.task.metadata else False

    if is_adversarial:
        success = no_errors and made_progress
    else:
        success = no_errors and expected_tool_called and not bool(aggregated_off_rail)

    # If we're going to fail this run because the agent produced literally
    # nothing, append a diagnostic system_error so transcripts and summaries
    # explain *why* without anyone having to dig.
    if not made_progress and turn_results and not any(t.system_errors for t in turn_results):
        no_output_msg = (
            "agent produced no output and called no tools — "
            "likely silent SDK / model_id failure (e.g. invalid slug rejected upstream)"
        )
        last = turn_results[-1]
        turn_results[-1] = replace(
            last,
            system_errors=last.system_errors + (no_output_msg,),
            query_had_error=True,
        )

    return RunResult(
        run_id=planned_run.run_id,
        experiment_id=spec.experiment_id,
        task_id=planned_run.task.task_id,
        model_id=planned_run.model.model_id,
        provider_id=provider_id,
        skill_id=planned_run.skill.skill_id,
        repeat_index=planned_run.repeat_index,
        success=success,
        started_at=started_at,
        completed_at=completed_at,
        wall_time_seconds=wall_time_seconds,
        total_cost_usd=total_cost_usd,
        usage=total_usage,
        turn_results=tuple(turn_results),
        off_rail=bool(aggregated_off_rail),
        off_rail_tool_calls=tuple(aggregated_off_rail),
        tools_called=tuple(tools_called_set),
        expected_tool_called=expected_tool_called,
        metadata={
            "agent_path": str(spec.agent_path),
            "resolved_skill_path": str(planned_run.skill.skill_path),
            "working_dir_root": str(spec.working_dir_root),
            "model_working_dir_root": str(model_data_root),
            "task_timeout_seconds": task_timeout,
            "bootstrap_skill": bootstrap_skill,
            "normalized_model": normalized_model,
            "model_label": planned_run.model.label,
            "model_metadata": model_metadata,
            "task_stage": task_stage,
            "expected_tool": expected_tool,
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
    n_no_call = sum(1 for r in results if not r.expected_tool_called)
    cache_read = sum((r.usage.cache_read_input_tokens or 0) for r in results)
    fresh_input = sum(r.usage.input_tokens for r in results)
    return {
        "n_runs": n,
        "n_success": n_success,
        "success_rate": (n_success / n) if n else 0.0,
        "n_off_rail": n_off_rail,
        "off_rail_rate": (n_off_rail / n) if n else 0.0,
        "n_no_expected_tool_call": n_no_call,
        "no_expected_tool_call_rate": (n_no_call / n) if n else 0.0,
        "total_cost_usd": sum(r.total_cost_usd for r in results),
        "total_wall_time_seconds": sum(r.wall_time_seconds for r in results),
        "total_input_tokens": fresh_input,
        "total_cache_read_input_tokens": cache_read,
        "total_effective_input_tokens": fresh_input + cache_read,
        "total_output_tokens": sum(r.usage.output_tokens for r in results),
    }


def _summarize_one_model(
    spec: ExperimentSpec,
    model: ModelSpec,
    runs: list[RunResult],
    *,
    routing: dict[str, dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    """Build the per-model summary block written to <model>/<stage>/summary.json.

    With model now outermost in the matrix and the output partitioned by
    model, each summary file holds stats for one (model, stage) cell —
    cross-model comparison is done by reading the sibling summary files.
    """
    block = _aggregate_block(runs)
    block["provider_id"] = runs[0].provider_id if runs else ""
    if routing and model.model_id in routing:
        info = routing[model.model_id]
        if info.get("served_by"):
            block["served_by_provider"] = info["served_by"]
        if info.get("error"):
            block["routing_probe_error"] = info["error"]
    off_rail_tools_seen: set[str] = set()
    for r in runs:
        for call in r.off_rail_tool_calls:
            off_rail_tools_seen.add(call["matched_suffix"])
    if off_rail_tools_seen:
        block["off_rail_tools_seen"] = sorted(off_rail_tools_seen)
    if model.label:
        block["label"] = model.label
    if model.metadata:
        block["model_metadata"] = dict(model.metadata)

    return {
        "experiment_id": spec.experiment_id,
        "stage": _spec_stage(spec),
        "model_id": model.model_id,
        "model_label": model.label,
        "generated_at": _utc_now(),
        **block,
    }


async def _run_experiment(
    spec: ExperimentSpec,
    *,
    limit: int,
    dry_run: bool,
    bootstrap_skill: bool,
    task_timeout_override: float | None = None,
) -> int:
    planned_runs = expand_planned_runs(spec)
    if limit > 0:
        planned_runs = planned_runs[:limit]

    _ensure_working_dir_root(spec)
    print(f"Planned runs: {len(planned_runs)}")

    if dry_run:
        for planned_run in planned_runs:
            print(f"- {planned_run.run_id}")
        return 0

    # Truncate per-model results.jsonl files for any model that will be touched
    # this pass, so a re-run starts clean rather than appending.
    models_in_run: list[ModelSpec] = []
    seen_model_ids: set[str] = set()
    for planned_run in planned_runs:
        if planned_run.model.model_id not in seen_model_ids:
            seen_model_ids.add(planned_run.model.model_id)
            models_in_run.append(planned_run.model)
    for model in models_in_run:
        rp = _results_path(spec, model)
        if rp.exists():
            rp.unlink()

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

    # If the probe surfaced a hard error for a model (e.g. invalid slug
    # rejected by OpenRouter), skip every planned run for that model up front.
    # Otherwise the SDK silently produces empty responses for ~all tasks and
    # we end up with N spurious "success" runs that did literally nothing.
    bad_model_ids = {mid for mid, info in routing.items() if info.get("error")}
    if bad_model_ids:
        print(
            f"  Skipping {len(bad_model_ids)} model(s) due to routing-probe failure — "
            f"fix the slug in eval/specs/models.json and re-run."
        )
        skipped_runs = sum(1 for r in planned_runs if r.model.model_id in bad_model_ids)
        planned_runs = tuple(r for r in planned_runs if r.model.model_id not in bad_model_ids)
        models_in_run = [m for m in models_in_run if m.model_id not in bad_model_ids]
        if skipped_runs:
            print(f"  ({skipped_runs} planned runs skipped; {len(planned_runs)} remaining)")
        if not planned_runs:
            print("  All planned runs were filtered out — nothing to do.")
            return 0

    # Group planned runs by model for header printing and per-model summary
    # writes. With model outermost in the matrix, runs for one model are
    # already contiguous, but explicit grouping is robust to future reorderings.
    runs_by_model: dict[str, list[RunResult]] = {}
    runs_by_model_index: dict[str, int] = {}
    for idx, model in enumerate(models_in_run, start=1):
        runs_by_model_index[model.model_id] = idx

    current_model_id: str | None = None
    for index, planned_run in enumerate(planned_runs, start=1):
        if planned_run.model.model_id != current_model_id:
            current_model_id = planned_run.model.model_id
            label = planned_run.model.label or current_model_id
            print(
                f"\n=== Model {runs_by_model_index[current_model_id]}/{len(models_in_run)}: "
                f"{label} ({current_model_id}) ==="
            )
        print(
            f"[{index}/{len(planned_runs)}] "
            f"task={planned_run.task.task_id} "
            f"skill={planned_run.skill.skill_id}"
        )
        run_result = await _execute_run_case(
            spec,
            planned_run,
            bootstrap_skill=bootstrap_skill,
            task_timeout_override=task_timeout_override,
        )
        _append_result(_results_path(spec, planned_run.model), run_result)
        _write_conversation_transcript(spec, planned_run.model, run_result)
        runs_by_model.setdefault(planned_run.model.model_id, []).append(run_result)

    # One summary per (model, stage). Reviewers compare across models by
    # reading the sibling summary.json files at <output_dir>/<model>/<stage>/.
    for model in models_in_run:
        runs = runs_by_model.get(model.model_id, [])
        if not runs:
            continue
        summary = _summarize_one_model(spec, model, runs, routing=routing)
        summary_path = _summary_path(spec, model)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"  [{model.label or model.model_id}] summary → {summary_path}")
    return 0


def _print_plan(spec: ExperimentSpec, *, write_manifest: bool) -> int:
    planned_runs = expand_planned_runs(spec)
    print(f"Experiment: {spec.experiment_id}  (stage: {_spec_stage(spec)})")
    print(f"Description: {spec.description}")
    print(f"Tasks: {len(spec.tasks)} | Models: {len(spec.models)} | Skills: {len(spec.skills)} | Repeats: {spec.repeats}")
    print(f"Planned runs: {len(planned_runs)}")
    current_model_id: str | None = None
    for planned_run in planned_runs:
        if planned_run.model.model_id != current_model_id:
            current_model_id = planned_run.model.model_id
            label = planned_run.model.label or current_model_id
            print(f"\n  Model: {label} ({current_model_id})")
        print(
            f"    - task={planned_run.task.task_id}, "
            f"skill={planned_run.skill.skill_id}, repeat={planned_run.repeat_index} "
            f"({planned_run.run_id})"
        )
    if write_manifest:
        manifest_path = _write_manifest(spec, planned_runs)
        print(f"\nManifest written to {manifest_path}")
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


def _resolve_spec_paths(args: argparse.Namespace) -> list[Path]:
    """Resolve --spec / --all-specs into an ordered list of spec paths.

    Exactly one of --spec and --all-specs must be set. With --all-specs we
    glob `eval/specs/*_eval.json` and order setup → planning → analysis →
    anything else (alphabetical), so multi-spec runs follow the natural
    workflow direction.
    """
    spec_arg = getattr(args, "spec", None)
    all_specs = getattr(args, "all_specs", False)
    if bool(spec_arg) == bool(all_specs):
        raise SystemExit("error: provide exactly one of --spec or --all-specs")
    if spec_arg is not None:
        return [spec_arg]
    specs_dir = Path(__file__).resolve().parent / "specs"
    found = sorted(specs_dir.glob("*_eval.json"))
    if not found:
        raise SystemExit(f"error: --all-specs found no matching files in {specs_dir}")
    stage_priority = {"setup": 0, "planning": 1, "analysis": 2}

    def _key(p: Path) -> tuple[int, str]:
        stem = p.stem.removesuffix("_eval")
        return (stage_priority.get(stem, 99), p.name)

    return sorted(found, key=_key)


def main() -> int:
    args = _build_parser().parse_args()
    _configure_eval_logging(sdk_trace=getattr(args, "sdk_trace", False))

    spec_paths = _resolve_spec_paths(args)
    multi = len(spec_paths) > 1

    # --models filter applies to plan and run; clean ignores it.
    models_arg = getattr(args, "models", None)

    final_status = 0
    for index, spec_path in enumerate(spec_paths, start=1):
        spec = load_experiment_spec(spec_path)
        if models_arg:
            spec = _filter_models(spec, models_arg)

        if multi:
            print(f"\n{'=' * 78}\n[{index}/{len(spec_paths)}] {spec_path.name}  (stage: {_spec_stage(spec)})\n{'=' * 78}")

        if args.command == "plan":
            rc = _print_plan(spec, write_manifest=args.write_manifest)
            final_status = final_status or rc
            continue

        if args.command == "clean":
            rc = _do_clean(spec, confirmed=args.yes)
            final_status = final_status or rc
            continue

        if getattr(args, "clean_data", False):
            removed = _clean_working_dir_root(spec.working_dir_root)
            if removed:
                print(f"[clean] removed {len(removed)} entries from {spec.working_dir_root} (preserving {sorted(_PRESERVE_NAMES)})")

        rc = asyncio.run(
            _run_experiment(
                spec,
                limit=args.limit,
                dry_run=args.dry_run,
                bootstrap_skill=(False if args.no_bootstrap_skill else spec.bootstrap_skill),
                task_timeout_override=getattr(args, "task_timeout", None),
            )
        )
        final_status = final_status or rc

    return final_status


if __name__ == "__main__":
    raise SystemExit(main())
