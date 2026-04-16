import importlib.util
import sys
from pathlib import Path


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = PROJECT_ROOT / "agent"

wrapper_config = _load_module("test_wrapper_config_module", AGENT_DIR / "wrapper_config.py")
workflow_monitor_loader = _load_module(
    "test_workflow_monitor_loader_module",
    AGENT_DIR / "workflow_monitor_loader.py",
)
workflow_routing = _load_module("test_workflow_routing_module", AGENT_DIR / "workflow_routing.py")


def test_default_agent_path_handles_configured_agent_name_case():
    agent_path = wrapper_config.default_agent_path(AGENT_DIR)
    assert agent_path == AGENT_DIR / "agents" / "colpack_agent.md"
    assert agent_path.exists()


def test_wrapper_runtime_defaults_disable_routing_and_enable_skill_bootstrap():
    assert wrapper_config.default_routing_enabled(AGENT_DIR) is False
    assert wrapper_config.default_skill_bootstrap_enabled(AGENT_DIR) is True


def test_build_system_prompt_assembles_agent_skill_and_mode_sections():
    system_prompt = wrapper_config.build_system_prompt(
        agent_path=AGENT_DIR / "agents" / "colpack_agent.md",
        base_dir=AGENT_DIR,
    )

    assert "# ColPack Agent System Prompt" in system_prompt
    assert "Present yourself as **ColPackAgent**." in system_prompt
    assert "Do not say you are `opencode`, `Codex`, or any other generic assistant name." in system_prompt
    assert "# Operating Rules" in system_prompt
    assert "# Mode Contract" in system_prompt
    assert "Prefer the wrapper's local progress monitor" in system_prompt


def test_workflow_monitor_loader_exposes_monitor_helpers():
    assert workflow_monitor_loader._tool_supports_local_monitor("execute_simulation_workflow_tool")
    assert workflow_monitor_loader._tool_supports_local_monitor("colpack_execute_simulation_workflow_tool")
    assert not workflow_monitor_loader._tool_supports_local_monitor("bash")


def test_prepare_user_input_returns_raw_message_when_routing_disabled():
    raw_input = "let's work on the colloidal packing simulation"
    context = workflow_routing.WorkflowRoutingContext()

    prepared_input, workflow_session_active, returned_context, route_kind = workflow_routing._prepare_user_input(
        user_input=raw_input,
        workflow_session_active=False,
        routing_context=context,
        routing_enabled=False,
    )

    assert prepared_input == raw_input
    assert workflow_session_active is False
    assert returned_context == context
    assert route_kind is None
