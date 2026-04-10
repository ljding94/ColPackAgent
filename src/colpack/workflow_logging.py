from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


WORKFLOW_LOG_FILE = "workflow_events.log"


def resolve_workflow_log_path(working_dir: str) -> Path:
    return Path(working_dir).expanduser().resolve() / WORKFLOW_LOG_FILE


def append_workflow_log(working_dir: str, message: str, *, source: str) -> Path:
    log_path = resolve_workflow_log_path(working_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] [{source}] {message}\n")
    return log_path
