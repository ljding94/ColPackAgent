import asyncio
import contextlib
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


WORKFLOW_PROGRESS_FILE = "workflow_progress.json"
WORKFLOW_LOG_FILE = "workflow_events.log"

# When quiet, the background monitor suppresses per-event terminal prints and
# only announces a one-line start + one-line end. The workflow itself still
# writes every event to <working_dir>/workflow_events.log on disk.
QUIET_MONITOR = True


def set_quiet_monitor(quiet: bool) -> None:
    global QUIET_MONITOR
    QUIET_MONITOR = quiet


@dataclass
class BackgroundMonitorState:
    task: asyncio.Task[None] | None = None
    stop_event: asyncio.Event | None = None
    working_dir: str | None = None


def _tool_name_matches(tool_name: str, suffix: str) -> bool:
    return tool_name == suffix or tool_name.endswith(f"_{suffix}")


def _tool_supports_local_monitor(tool_name: str) -> bool:
    return any(
        _tool_name_matches(tool_name, suffix)
        for suffix in (
            "setup_simulation_problem_tool",
            "plan_simulation_runs_tool",
            "execute_simulation_workflow_tool",
            "analyze_simulation_runs_tool",
        )
    )


def _read_workflow_progress(working_dir: str) -> dict[str, Any] | None:
    progress_path = Path(working_dir).expanduser().resolve() / WORKFLOW_PROGRESS_FILE
    if not progress_path.exists():
        return None

    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_workflow_log_lines(working_dir: str, offset: int) -> tuple[list[str], int]:
    log_path = Path(working_dir).expanduser().resolve() / WORKFLOW_LOG_FILE
    if not log_path.exists():
        return [], offset

    try:
        with log_path.open("r", encoding="utf-8") as log_file:
            log_file.seek(offset)
            lines = [line.rstrip() for line in log_file.readlines()]
            return lines, log_file.tell()
    except Exception:
        return [], offset


def _workflow_progress_signature(progress: dict[str, Any]) -> tuple[Any, ...]:
    return (
        progress.get("status"),
        progress.get("current_run_index"),
        progress.get("current_run_number"),
        progress.get("current_step"),
        progress.get("completed_steps"),
        progress.get("n_success"),
        progress.get("n_failed"),
        progress.get("message"),
    )


def _format_workflow_progress(progress: dict[str, Any]) -> str:
    status = progress.get("status", "unknown")
    n_runs = progress.get("n_runs", 0)
    current_run_index = progress.get("current_run_index")
    current_run_number = progress.get("current_run_number")
    current_step = progress.get("current_step")
    completed_steps = progress.get("completed_steps", 0)
    total_steps = progress.get("total_steps", 0)
    percent = progress.get("progress_percent", 0.0)
    n_success = progress.get("n_success", 0)
    n_failed = progress.get("n_failed", 0)
    message = progress.get("message", "")

    if status == "running" and current_run_index is not None and current_step:
        return (
            f"run {current_run_index}/{n_runs} (run_{current_run_number}) | "
            f"step={current_step} | {completed_steps}/{total_steps} steps | "
            f"{percent:.1f}% | success={n_success} failed={n_failed}"
        )

    if message:
        return (
            f"{message} | {completed_steps}/{total_steps} steps | "
            f"{percent:.1f}% | success={n_success} failed={n_failed}"
        )

    return (
        f"status={status} | {completed_steps}/{total_steps} steps | "
        f"{percent:.1f}% | success={n_success} failed={n_failed}"
    )


def _display_path(path: str) -> str:
    """Render `path` relative to the current cwd (with ./ prefix) when it's
    inside cwd; otherwise return it unchanged. Terminal-only — does not affect
    paths sent to tools or persisted to the session log."""
    try:
        cwd = Path.cwd().resolve()
        rel = Path(path).resolve().relative_to(cwd)
        return f"./{rel}"
    except (ValueError, OSError):
        return path


def _announce_workflow_end(progress: dict[str, Any], working_dir: str) -> None:
    status = progress.get("status", "unknown")
    n_runs = progress.get("n_runs", 0)
    n_success = progress.get("n_success", 0)
    n_failed = progress.get("n_failed", 0)
    print(
        f"\n[workflow] {status}: {n_success}/{n_runs} success, "
        f"{n_failed} failed (events: {_display_path(working_dir)}/{WORKFLOW_LOG_FILE})"
    )


async def _monitor_workflow_progress(working_dir: str, stop_event: asyncio.Event) -> None:
    last_signature: tuple[Any, ...] | None = None
    log_offset = 0
    end_announced = False

    while not stop_event.is_set():
        log_lines, log_offset = _read_workflow_log_lines(working_dir, log_offset)
        if not QUIET_MONITOR:
            for line in log_lines:
                print(f"\n[log] {line}")

        progress = _read_workflow_progress(working_dir)
        if progress:
            signature = _workflow_progress_signature(progress)
            if signature != last_signature:
                if not QUIET_MONITOR:
                    print(f"\n[workflow] {_format_workflow_progress(progress)}")
                last_signature = signature
            if progress.get("status") in {"completed", "failed"}:
                _announce_workflow_end(progress, working_dir)
                end_announced = True
                return

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            continue

    log_lines, log_offset = _read_workflow_log_lines(working_dir, log_offset)
    if not QUIET_MONITOR:
        for line in log_lines:
            print(f"\n[log] {line}")

    progress = _read_workflow_progress(working_dir)
    if progress:
        signature = _workflow_progress_signature(progress)
        if signature != last_signature and not QUIET_MONITOR:
            print(f"\n[workflow] {_format_workflow_progress(progress)}")
        if not end_announced and progress.get("status") in {"completed", "failed"}:
            _announce_workflow_end(progress, working_dir)


async def _stop_background_monitor(background_state: BackgroundMonitorState) -> BackgroundMonitorState:
    if background_state.stop_event is not None:
        background_state.stop_event.set()
    if background_state.task is not None:
        with contextlib.suppress(Exception):
            await background_state.task
    return BackgroundMonitorState()


async def _maybe_start_background_monitor(
    background_state: BackgroundMonitorState,
    working_dir: str,
) -> BackgroundMonitorState:
    resolved_dir = str(Path(working_dir).expanduser().resolve())
    if background_state.working_dir == resolved_dir:
        return background_state

    background_state = await _stop_background_monitor(background_state)
    stop_event = asyncio.Event()
    task = asyncio.create_task(_monitor_workflow_progress(resolved_dir, stop_event))
    display_dir = _display_path(resolved_dir)
    if QUIET_MONITOR:
        print(f"[workflow] running in background — tail {display_dir}/{WORKFLOW_LOG_FILE} for live events")
    else:
        print(f"[workflow] Local progress/log monitor started for {display_dir}")
    return BackgroundMonitorState(task=task, stop_event=stop_event, working_dir=resolved_dir)


async def _cleanup_completed_background_monitor(background_state: BackgroundMonitorState) -> BackgroundMonitorState:
    if background_state.task is None or not background_state.task.done():
        return background_state

    with contextlib.suppress(Exception):
        await background_state.task
    return BackgroundMonitorState()
