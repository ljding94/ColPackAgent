import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
import contextlib
from typing import Any

from opencode_agent_sdk import AgentOptions, SDKClient
from opencode_agent_sdk.types import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

try:
    from .workflow_monitor_loader import (
        BackgroundMonitorState,
        _cleanup_completed_background_monitor,
        _maybe_start_background_monitor,
        _stop_background_monitor,
        _tool_name_matches,
        _tool_supports_local_monitor,
    )
except ImportError:
    from workflow_monitor_loader import (
        BackgroundMonitorState,
        _cleanup_completed_background_monitor,
        _maybe_start_background_monitor,
        _stop_background_monitor,
        _tool_name_matches,
        _tool_supports_local_monitor,
    )

try:
    from .wrapper_config import (
        build_system_prompt,
        default_agent_path,
        default_mcp_command,
        default_routing_enabled,
        default_skill_path,
        default_skill_bootstrap_enabled,
        load_agent_definition,
    )
except ImportError:
    from wrapper_config import (
        build_system_prompt,
        default_agent_path,
        default_mcp_command,
        default_routing_enabled,
        default_skill_path,
        default_skill_bootstrap_enabled,
        load_agent_definition,
    )

try:
    from .workflow_routing import WorkflowRoutingContext, _prepare_user_input
except ImportError:
    from workflow_routing import WorkflowRoutingContext, _prepare_user_input


@dataclass
class QueryResponseState:
    final_text: str = ""
    query_had_error: bool = False
    had_assistant_message: bool = False
    system_errors: list[str] = field(default_factory=list)
    workflow_monitor_task: asyncio.Task[None] | None = None
    workflow_monitor_stop: asyncio.Event | None = None
    workflow_monitor_persistent: bool = False
    suppressed_status_polls: int = 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone ColPack wrapper with MCP tools preloaded.")
    parser.add_argument(
        "--agent-path",
        type=Path,
        default=default_agent_path(),
        help="Path to the standalone agent definition file (default: agent/agents/colpack_agent.md).",
    )
    parser.add_argument(
        "--skill-path",
        type=Path,
        default=default_skill_path(),
        help="Optional override for the agent skill markdown file. If omitted, app.py uses the skill_path declared by the agent definition.",
    )
    parser.add_argument(
        "--mcp-command",
        default=default_mcp_command(),
        help="Command used to start the ColPack FastMCP server (default: from opencode.json or 'colpack-mcp').",
    )
    parser.add_argument(
        "--model",
        default="openrouter/google/gemini-3-flash-preview",
        help="Underlying LLM model name passed to OpenCode (for OpenRouter, use provider-qualified ids like openrouter/google/gemini-3-flash-preview).",
    )
    parser.add_argument(
        "--routing",
        action=argparse.BooleanOptionalAction,
        default=default_routing_enabled(),
        help="Enable wrapper-side ColPack message routing. Disabled by default because the ColPack skill is loaded at session start.",
    )
    parser.add_argument(
        "--bootstrap-skill",
        action=argparse.BooleanOptionalAction,
        default=default_skill_bootstrap_enabled(),
        help="Call get_colpack_capabilities_tool once when the session starts to preload ColPack skill context.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable application-level INFO logs.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="WARNING",
        help="Base log level (default: WARNING). Ignored when --verbose is set.",
    )
    parser.add_argument(
        "--sdk-trace",
        action="store_true",
        help="Enable very verbose opencode_agent_sdk internal transport/ACP logs.",
    )
    return parser


def _extract_assistant_text(msg: AssistantMessage) -> str:
    texts = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            texts.append(block.text)
    return "".join(texts).strip()


def _configure_logging(verbose: bool, log_level: str, sdk_trace: bool) -> None:
    level = logging.INFO if verbose else getattr(logging, log_level.upper(), logging.WARNING)
    logging.basicConfig(level=level)

    noisy_loggers = [
        "opencode_agent_sdk",
        "opencode_agent_sdk.client",
        "opencode_agent_sdk._internal.transport",
        "opencode_agent_sdk._internal.acp",
    ]

    if sdk_trace:
        return

    for logger_name in noisy_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.ERROR)


def _is_timeout_like_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return "request timed out" in lowered or "timed out" in lowered or "mcp error -32001" in lowered


def _extract_system_error(msg: SystemMessage) -> str:
    if msg.subtype not in {"tool_error", "error", "session_error"}:
        return ""

    data = msg.data or {}
    for key in ("error", "message", "name"):
        value = data.get(key)
        if value:
            return str(value)
    return str(data) if data else ""


def _resolve_model_and_provider(model: str) -> tuple[str, str]:
    """Normalize model/provider for SDK: provider_id + provider-local model id.

    SDK subprocess mode builds modelId as "{provider_id}/{model}".
    For OpenRouter-qualified input like "openrouter/google/gemini-2.5-pro",
    we must pass provider_id="openrouter" and model="google/gemini-2.5-pro".
    """
    cleaned = (model or "").strip()
    if cleaned.startswith("openrouter/"):
        return cleaned[len("openrouter/"):], "openrouter"

    # This project environment uses OpenRouter credentials by default.
    return cleaned, "openrouter"


def _format_tool_input(tool_input: dict[str, Any], max_length: int = 160) -> str:
    try:
        compact = json.dumps(tool_input, ensure_ascii=True, separators=(",", ": "))
    except Exception:
        compact = str(tool_input)

    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3] + "..."


def _extract_tool_params(tool_input: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(tool_input, dict):
        return {}

    params = tool_input.get("params")
    if isinstance(params, dict):
        return params

    if isinstance(params, str):
        try:
            parsed = json.loads(params)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}

    return tool_input


def _extract_tool_uses(msg: AssistantMessage) -> list[ToolUseBlock]:
    return [block for block in msg.content if isinstance(block, ToolUseBlock)]


def _print_local_help() -> None:
    print("Local commands:")
    print("  /help                 Show wrapper commands")
    print("  /stop-monitor         Stop local workflow progress monitor")
    print("Local monitor shows workflow progress and workflow_events.log lines when available")
    print("  exit                  Quit the session")


async def _handle_tool_use(
    tool_use: ToolUseBlock,
    background_state: BackgroundMonitorState,
    response_state: QueryResponseState,
    workflow_session_active: bool,
    show_output: bool = True,
) -> tuple[BackgroundMonitorState, QueryResponseState, bool]:
    tool_params = _extract_tool_params(tool_use.input)

    if _tool_name_matches(tool_use.name, "get_simulation_workflow_status_tool") and background_state.task is not None:
        response_state.suppressed_status_polls += 1
        return background_state, response_state, workflow_session_active

    if _tool_supports_local_monitor(tool_use.name):
        workflow_session_active = True

    if show_output:
        print(
            f"\n[tool] Using {tool_use.name} "
            f"with {_format_tool_input(tool_use.input)}"
        )

    working_dir = tool_params.get("working_dir")
    if _tool_supports_local_monitor(tool_use.name) and isinstance(working_dir, str) and working_dir.strip():
        background_state = await _maybe_start_background_monitor(background_state, working_dir)

    if _tool_name_matches(tool_use.name, "execute_simulation_workflow_tool"):
        wait = bool(tool_params.get("wait", False))
        if isinstance(working_dir, str) and working_dir.strip():
            if wait:
                response_state.workflow_monitor_stop = background_state.stop_event
                response_state.workflow_monitor_task = background_state.task
            else:
                response_state.workflow_monitor_persistent = True

    return background_state, response_state, workflow_session_active


async def _collect_query_response(
    client: SDKClient,
    background_state: BackgroundMonitorState,
    workflow_session_active: bool,
    show_tool_use: bool = True,
) -> tuple[QueryResponseState, BackgroundMonitorState, bool]:
    response_state = QueryResponseState()
    seen_tool_ids: set[str] = set()

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            response_state.had_assistant_message = True
            for tool_use in _extract_tool_uses(message):
                if tool_use.id in seen_tool_ids:
                    continue

                seen_tool_ids.add(tool_use.id)
                background_state, response_state, workflow_session_active = await _handle_tool_use(
                    tool_use=tool_use,
                    background_state=background_state,
                    response_state=response_state,
                    workflow_session_active=workflow_session_active,
                    show_output=show_tool_use,
                )

            extracted = _extract_assistant_text(message)
            if extracted:
                response_state.final_text = extracted
        elif isinstance(message, SystemMessage):
            system_error = _extract_system_error(message)
            if system_error:
                response_state.system_errors.append(system_error)
        elif isinstance(message, ResultMessage) and message.is_error:
            response_state.query_had_error = True

    return response_state, background_state, workflow_session_active


async def _finalize_query_monitoring(
    background_state: BackgroundMonitorState,
    response_state: QueryResponseState,
    show_status_output: bool = True,
) -> BackgroundMonitorState:
    if show_status_output and response_state.suppressed_status_polls:
        print(
            f"\n[poll] Suppressed {response_state.suppressed_status_polls} repeated status-tool log(s); using local workflow monitor instead."
        )

    if response_state.workflow_monitor_stop is not None and not response_state.workflow_monitor_persistent:
        response_state.workflow_monitor_stop.set()
    if response_state.workflow_monitor_task is not None and not response_state.workflow_monitor_persistent:
        with contextlib.suppress(Exception):
            await response_state.workflow_monitor_task

    return await _cleanup_completed_background_monitor(background_state)


async def _bootstrap_skill_session(
    client: SDKClient,
    background_state: BackgroundMonitorState,
) -> BackgroundMonitorState:
    bootstrap_prompt = (
        "Internal wrapper bootstrap for the active ColPack skill. "
        "This is not a user turn, and the wrapper pre-approves the required tool call for this bootstrap step. "
        "Before handling user requests, call get_colpack_capabilities_tool exactly once with no parameters. "
        "Treat that tool result as the source of truth for supported shapes, ensembles, workflow steps, and analysis options in this session. "
        "Do not ask the user anything. Reply with exactly READY after the tool call."
    )
    await client.query(bootstrap_prompt)
    response_state, background_state, _ = await _collect_query_response(
        client=client,
        background_state=background_state,
        workflow_session_active=False,
        show_tool_use=False,
    )
    background_state = await _finalize_query_monitoring(
        background_state=background_state,
        response_state=response_state,
        show_status_output=False,
    )
    if response_state.query_had_error or response_state.system_errors:
        error_text = response_state.system_errors[-1] if response_state.system_errors else "bootstrap query failed"
        print(f"Warning: ColPack skill bootstrap failed: {error_text}")
    return background_state


def _print_query_outcome(response_state: QueryResponseState, agent_name: str) -> None:
    if response_state.final_text:
        print(f"\n{agent_name}: {response_state.final_text}")
        return

    if response_state.system_errors:
        print(f"\nAgent Error: {response_state.system_errors[-1]}")
        lowered = response_state.system_errors[-1].lower()
        if "request timed out" in lowered or "mcp error -32001" in lowered:
            print("Hint: long simulation calls should use async execution and rely on the local workflow monitor.")
        return

    if response_state.query_had_error:
        print("\nAgent Error: query failed.")
        return

    if response_state.had_assistant_message:
        print(f"\n{agent_name}: [Agent returned non-text output]")
        return

    print(f"\n{agent_name}: [No text response]")
    print("Hint: the selected model may be unavailable. Try another --model id, for example:")
    print("  openrouter/google/gemini-3-flash-preview")
    print("  openrouter/google/gemini-2.5-flash")
    print('Quick check: opencode run -m <model-id> "hi"')


async def _connect_client(
    agent_path: Path,
    skill_path: Path | None,
    mcp_command: str,
    normalized_model: str,
    provider_id: str,
) -> SDKClient:
    system_prompt = build_system_prompt(agent_path, skill_path=skill_path)

    options_kwargs = {
        "cwd": str(Path(__file__).resolve().parent.parent),
        "system_prompt": system_prompt,
        "mcp_servers": {
            "colpack": {
                "command": mcp_command,
            }
        },
    }
    if normalized_model:
        options_kwargs["model"] = normalized_model
    if provider_id:
        options_kwargs["provider_id"] = provider_id

    client = SDKClient(options=AgentOptions(**options_kwargs))
    await client.connect()
    return client


async def run_agent(
    agent_path: Path,
    skill_path: Path | None,
    mcp_command: str,
    model: str,
    routing: bool,
    bootstrap_skill: bool,
) -> None:
    agent_definition = load_agent_definition(agent_path, skill_path_override=skill_path)
    normalized_model, provider_id = _resolve_model_and_provider(model)
    client: SDKClient | None = None
    background_monitor_state = BackgroundMonitorState()
    workflow_session_active = False
    routing_context = WorkflowRoutingContext()

    print(f"Booting {agent_definition.name}...")
    print(f"Using agent: {agent_definition.name}")
    print(f"Agent definition: {agent_definition.source_path}")
    if agent_definition.skill_path is not None:
        print(f"Agent skill: {agent_definition.skill_path}")
    print(f"Using provider: {provider_id}")
    print(f"Using model: {normalized_model}")
    print(f"Wrapper routing: {'enabled' if routing else 'disabled'}")
    print(f"Skill bootstrap: {'enabled' if bootstrap_skill else 'disabled'}")

    try:
        client = await _connect_client(
            agent_path=agent_definition.source_path,
            skill_path=agent_definition.skill_path,
            mcp_command=mcp_command,
            normalized_model=normalized_model,
            provider_id=provider_id,
        )
        print(f"Attached FastMCP tools using command: {mcp_command}")
        if bootstrap_skill:
            print("Loading ColPack skill context...")
            background_monitor_state = await _bootstrap_skill_session(client, background_monitor_state)
    except FileNotFoundError as exc:
        print(f"Error loading skill prompt: {exc}")
        return
    except Exception as exc:
        print("Failed to attach MCP tools.")
        print("Make sure the ColPack package is installed, e.g. `pip install -e ./src`.")
        print(f"Attach error: {exc}")
        return

    print("\n================================================")
    print(f" {agent_definition.name} Ready. Type 'exit' to quit.")
    print(" Commands: /help | /stop-monitor")
    print("================================================")

    try:
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except EOFError:
                print("\nShutting down ColPackAgent...")
                break

            if user_input.lower() in {"exit", "quit"}:
                print("Shutting down ColPackAgent...")
                break

            if not user_input:
                continue

            if user_input == "/help":
                _print_local_help()
                continue

            if user_input == "/stop-monitor":
                background_monitor_state = await _stop_background_monitor(background_monitor_state)
                print("Stopped local workflow progress monitor.")
                continue

            attempt = 0
            while attempt < 2:
                try:
                    routed_user_input, workflow_session_active, routing_context, route_kind = _prepare_user_input(
                        user_input=user_input,
                        workflow_session_active=workflow_session_active,
                        routing_context=routing_context,
                        routing_enabled=routing,
                    )
                    if route_kind == "follow-up":
                        print("[route] ColPack workflow follow-up detected; preserving active workflow context.")
                    elif route_kind == "request":
                        print("[route] ColPack workflow request detected; prioritizing MCP workflow tools.")

                    await client.query(routed_user_input)

                    response_state, background_monitor_state, workflow_session_active = await _collect_query_response(
                        client=client,
                        background_state=background_monitor_state,
                        workflow_session_active=workflow_session_active,
                    )
                    background_monitor_state = await _finalize_query_monitoring(
                        background_state=background_monitor_state,
                        response_state=response_state,
                    )
                    _print_query_outcome(response_state, agent_definition.name)
                    break
                except Exception as exc:
                    err_text = str(exc)
                    if attempt == 0 and _is_timeout_like_error(err_text):
                        print("\nMCP request timed out. Reconnecting tool session and retrying once...")
                        try:
                            await client.disconnect()
                        except Exception:
                            pass
                        await client.connect()
                        attempt += 1
                        continue

                    print(f"\nAgent Error: {exc}")
                    break
    except KeyboardInterrupt:
        print("\nShutting down ColPackAgent...")
    finally:
        background_monitor_state = await _stop_background_monitor(background_monitor_state)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                # Ignore shutdown errors because user is already exiting.
                pass


def main() -> None:
    args = _build_parser().parse_args()
    _configure_logging(verbose=args.verbose, log_level=args.log_level, sdk_trace=args.sdk_trace)
    asyncio.run(
        run_agent(
            agent_path=args.agent_path,
            skill_path=args.skill_path,
            mcp_command=args.mcp_command,
            model=args.model,
            routing=args.routing,
            bootstrap_skill=args.bootstrap_skill,
        )
    )


if __name__ == "__main__":
    main()
