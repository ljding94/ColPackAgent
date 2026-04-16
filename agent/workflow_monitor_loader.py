import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def _load_workflow_monitor_module() -> ModuleType:
    module_path = (
        Path(__file__).resolve().parent
        / "skills"
        / "colpack"
        / "scripts"
        / "workflow_monitor.py"
    )
    if not module_path.exists():
        raise FileNotFoundError(f"Workflow monitor file not found: {module_path}")

    spec = importlib.util.spec_from_file_location("colpack_workflow_monitor", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load workflow monitor module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_workflow_monitor = _load_workflow_monitor_module()

BackgroundMonitorState = _workflow_monitor.BackgroundMonitorState
_cleanup_completed_background_monitor = _workflow_monitor._cleanup_completed_background_monitor
_maybe_start_background_monitor = _workflow_monitor._maybe_start_background_monitor
_stop_background_monitor = _workflow_monitor._stop_background_monitor
_tool_name_matches = _workflow_monitor._tool_name_matches
_tool_supports_local_monitor = _workflow_monitor._tool_supports_local_monitor
