import argparse
import asyncio
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import sys
from typing import Any
import contextlib

from opencode_agent_sdk import AgentOptions, SDKClient
from opencode_agent_sdk.types import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

# workflow_monitor lives in the colpack skill's scripts folder
_COLPACK_SCRIPTS_DIR = str(Path(__file__).resolve().parent / "skills" / "colpack" / "scripts")
if _COLPACK_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _COLPACK_SCRIPTS_DIR)

from workflow_monitor import (
    BackgroundMonitorState,
    _cleanup_completed_background_monitor,
    _maybe_start_background_monitor,
    _stop_background_monitor,
    _tool_name_matches,
    _tool_supports_local_monitor,
)

try:
    from .workflow_routing import WorkflowRoutingContext, _route_user_message
except ImportError:
    from workflow_routing import WorkflowRoutingContext, _route_user_message


AGENT_MODES = ("interactive", "autonomous")


@dataclass(frozen=True)
class StandaloneAgentDefinition:
    name: str
    description: str
    prompt: str
    skill_path: Path | None
    source_path: Path


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


def _load_opencode_config() -> dict:
    """Load opencode.json from the same directory as app.py."""
    config_path = Path(__file__).resolve().parent / "opencode.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _default_mcp_command() -> str:
    colpack_mcp = _load_opencode_config().get("mcp", {}).get("colpack", {})
    cmd = colpack_mcp.get("command")
    if isinstance(cmd, list) and cmd:
        return " ".join(cmd)
    if isinstance(cmd, str) and cmd:
        return cmd
    return "colpack-mcp"


def _default_agent_path() -> Path:
    base = Path(__file__).resolve().parent
    agent_name = _load_opencode_config().get("default_agent")
    if agent_name:
        return base / "agents" / f"{agent_name}.md"
    return base / "agents" / "colpack_agent.md"


def _default_skill_path() -> Path:
    base = Path(__file__).resolve().parent
    instructions = _load_opencode_config().get("instructions", [])
    if instructions:
        return (base / instructions[0]).resolve()
    return base / "skills" / "colpack" / "SKILL.md"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ColPackAgent in standalone chat mode.")
    parser.add_argument(
        "--agent-path",
        type=Path,
        default=_default_agent_path(),
        help="Path to the standalone agent definition file (default: agent/agents/colpack_agent.md).",
    )
    parser.add_argument(
        "--skill-path",
        type=Path,
        default=_default_skill_path(),
        help="Optional override for the agent skill markdown file. If omitted, app.py uses the skill_path declared by the agent definition.",
    )
    parser.add_argument(
        "--mcp-command",
        default=_default_mcp_command(),
        help="Command used to start the ColPack FastMCP server (default: from opencode.json or 'colpack-mcp').",
    )
    parser.add_argument(
        "--model",
        default="openrouter/google/gemini-3-flash-preview",
        help="Underlying LLM model name passed to OpenCode (for OpenRouter, use provider-qualified ids like openrouter/google/gemini-3-flash-preview).",
    )
    parser.add_argument(
        "--mode",
        choices=AGENT_MODES,
        default="interactive",
        help="Agent workflow mode: 'interactive' asks for approval at each step, 'autonomous' runs end-to-end from a detailed prompt.",
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


def _load_skill_prompt(skill_path: Path) -> str:
    resolved = skill_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Skill file not found: {resolved}")
    return resolved.read_text(encoding="utf-8")


def _parse_frontmatter(markdown_text: str) -> tuple[dict[str, str], str]:
    if not markdown_text.startswith("---\n"):
        return {}, markdown_text.strip()

    lines = markdown_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown_text.strip()

    frontmatter: dict[str, str] = {}
    end_index = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            end_index = index
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip().strip('"').strip("'")

    if end_index is None:
        return {}, markdown_text.strip()

    body = "\n".join(lines[end_index + 1 :]).strip()
    return frontmatter, body


def _load_agent_definition(agent_path: Path, skill_path_override: Path | None = None) -> StandaloneAgentDefinition:
    resolved = agent_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Agent file not found: {resolved}")

    frontmatter, body = _parse_frontmatter(resolved.read_text(encoding="utf-8"))
    skill_path = skill_path_override
    if skill_path is None:
        skill_path_text = frontmatter.get("skill_path")
        if skill_path_text:
            skill_path = (resolved.parent / skill_path_text).resolve()
        else:
            skill_path = _default_skill_path()

    return StandaloneAgentDefinition(
        name=frontmatter.get("name", resolved.stem),
        description=frontmatter.get("description", ""),
        prompt=body,
        skill_path=skill_path,
        source_path=resolved,
    )


def _build_mode_prompt(mode: str) -> str:
    if mode == "interactive":
        return (
            "# Wrapper Runtime Mode\n"
            "AGENT_MODE = interactive\n\n"
            "Wrapper additions for interactive mode:\n"
            "1. Show the exact MCP payload before each tool call and wait for explicit user approval.\n"
            "2. Stop after each completed workflow stage and ask whether to continue, revise inputs, or redo that stage.\n"
            "3. Never call execute_simulation_workflow_tool until the user explicitly approves execution.\n"
            "4. Merge incremental follow-up replies into the active workflow context instead of restarting setup from scratch.\n"
            "5. Prefer the wrapper's local progress monitor over repeated status-tool polling after async execution.\n"
        )

    return (
        "# Wrapper Runtime Mode\n"
        "AGENT_MODE = autonomous\n\n"
        "Wrapper additions for autonomous mode:\n"
        "1. Prefer async execution for long workflows and rely on the wrapper's local progress monitor rather than repeated status polling.\n"
        "2. If local workflow progress is unavailable, status-tool checks are acceptable.\n"
    )


def _load_system_prompt(agent_path: Path, mode: str, skill_path: Path | None = None) -> str:
    agent_definition = _load_agent_definition(agent_path, skill_path_override=skill_path)
    sections = []
    if agent_definition.prompt:
        sections.append(agent_definition.prompt)
    if agent_definition.skill_path is not None:
        sections.append(_load_skill_prompt(agent_definition.skill_path))
    sections.append(_build_mode_prompt(mode))
    return "\n\n".join(section for section in sections if section.strip())


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


def _print_local_help(current_mode: str) -> None:
    print("Local commands:")
    print("  /help                 Show wrapper commands")
    print("  /mode                 Show current workflow mode")
    print("  /mode interactive     Switch to step-by-step mode")
    print("  /mode autonomous      Switch to end-to-end mode")
    print("  /stop-monitor         Stop local workflow progress monitor")
    print("Local monitor shows workflow progress and workflow_events.log lines when available")
    print("  exit                  Quit the session")
    print(f"Current mode: {current_mode}")


async def _handle_tool_use(
    tool_use: ToolUseBlock,
    background_state: BackgroundMonitorState,
    response_state: QueryResponseState,
    workflow_session_active: bool,
) -> tuple[BackgroundMonitorState, QueryResponseState, bool]:
    tool_params = _extract_tool_params(tool_use.input)

    if _tool_name_matches(tool_use.name, "get_simulation_workflow_status_tool") and background_state.task is not None:
        response_state.suppressed_status_polls += 1
        return background_state, response_state, workflow_session_active

    if _tool_supports_local_monitor(tool_use.name):
        workflow_session_active = True

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
) -> BackgroundMonitorState:
    if response_state.suppressed_status_polls:
        print(
            f"\n[poll] Suppressed {response_state.suppressed_status_polls} repeated status-tool log(s); using local workflow monitor instead."
        )

    if response_state.workflow_monitor_stop is not None and not response_state.workflow_monitor_persistent:
        response_state.workflow_monitor_stop.set()
    if response_state.workflow_monitor_task is not None and not response_state.workflow_monitor_persistent:
        with contextlib.suppress(Exception):
            await response_state.workflow_monitor_task

    return await _cleanup_completed_background_monitor(background_state)


def _print_query_outcome(response_state: QueryResponseState) -> None:
    if response_state.final_text:
        print(f"\nColPackAgent: {response_state.final_text}")
        return

    if response_state.system_errors:
        print(f"\nAgent Error: {response_state.system_errors[-1]}")
        lowered = response_state.system_errors[-1].lower()
        if "request timed out" in lowered or "mcp error -32001" in lowered:
            print("Hint: long simulation calls should use async execution (wait=false) and poll status.")
        return

    if response_state.query_had_error:
        print("\nAgent Error: query failed.")
        return

    if response_state.had_assistant_message:
        print("\nColPackAgent: [Agent returned non-text output]")
        return

    print("\nColPackAgent: [No text response]")
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
    mode: str,
) -> SDKClient:
    system_prompt = _load_system_prompt(agent_path, mode, skill_path=skill_path)

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
    mode: str,
) -> None:
    agent_definition = _load_agent_definition(agent_path, skill_path_override=skill_path)
    normalized_model, provider_id = _resolve_model_and_provider(model)
    current_mode = mode
    client: SDKClient | None = None
    background_monitor_state = BackgroundMonitorState()
    workflow_session_active = False
    routing_context = WorkflowRoutingContext()

    print("Booting ColPackAgent...")
    print(f"Using agent: {agent_definition.name}")
    print(f"Agent definition: {agent_definition.source_path}")
    if agent_definition.skill_path is not None:
        print(f"Agent skill: {agent_definition.skill_path}")
    print(f"Using provider: {provider_id}")
    print(f"Using model: {normalized_model}")
    print(f"Starting mode: {current_mode}")

    try:
        client = await _connect_client(
            agent_path=agent_definition.source_path,
            skill_path=agent_definition.skill_path,
            mcp_command=mcp_command,
            normalized_model=normalized_model,
            provider_id=provider_id,
            mode=current_mode,
        )
        print(f"Attached FastMCP tools using command: {mcp_command}")
    except FileNotFoundError as exc:
        print(f"Error loading skill prompt: {exc}")
        return
    except Exception as exc:
        print("Failed to attach MCP tools.")
        print("Make sure the ColPack package is installed, e.g. `pip install -e ./src`.")
        print(f"Attach error: {exc}")
        return

    print("\n================================================")
    print(" ColPackAgent Ready. Type 'exit' to quit.")
    print(f" Mode: {current_mode}  |  /mode interactive|autonomous  |  /help")
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
                _print_local_help(current_mode)
                continue

            if user_input == "/stop-monitor":
                background_monitor_state = await _stop_background_monitor(background_monitor_state)
                print("Stopped local workflow progress monitor.")
                continue

            if user_input.startswith("/mode"):
                parts = user_input.split(maxsplit=1)
                if len(parts) == 1:
                    print(f"Current mode: {current_mode}")
                    print("Usage: /mode interactive or /mode autonomous")
                    continue

                requested_mode = parts[1].strip().lower()
                if requested_mode not in AGENT_MODES:
                    print(f"Unknown mode: {requested_mode}")
                    print("Usage: /mode interactive or /mode autonomous")
                    continue

                if requested_mode == current_mode:
                    print(f"Already in {current_mode} mode.")
                    continue

                print(f"Switching to {requested_mode} mode...")
                try:
                    new_client = await _connect_client(
                        agent_path=agent_definition.source_path,
                        skill_path=agent_definition.skill_path,
                        mcp_command=mcp_command,
                        normalized_model=normalized_model,
                        provider_id=provider_id,
                        mode=requested_mode,
                    )
                except Exception as exc:
                    print(f"Failed to switch mode: {exc}")
                    continue

                old_client = client
                client = new_client
                current_mode = requested_mode
                workflow_session_active = False
                routing_context = WorkflowRoutingContext()

                if old_client is not None:
                    try:
                        await old_client.disconnect()
                    except Exception:
                        pass

                print(f"Mode switched to {current_mode}.")
                continue

            attempt = 0
            while attempt < 2:
                try:
                    routed_user_input, workflow_session_active, routing_context, route_kind = _route_user_message(
                        user_input=user_input,
                        current_mode=current_mode,
                        workflow_session_active=workflow_session_active,
                        routing_context=routing_context,
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
                    _print_query_outcome(response_state)
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
            mode=args.mode,
        )
    )


if __name__ == "__main__":
    main()
