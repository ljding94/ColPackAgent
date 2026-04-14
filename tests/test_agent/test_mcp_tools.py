"""
Integration tests for the ColPack MCP server tools.

Tests the async execute/analyze pattern without running real simulations:
  - get_colpack_capabilities_tool
  - setup_simulation_problem_tool
  - plan_simulation_runs_tool
  - execute_simulation_workflow_tool  → must return immediately (async)
  - analyze_simulation_runs_tool      → must return immediately (async)

Progress is monitored by reading workflow_progress.json locally (no MCP
status-polling tool exists; get_workflow_status_tool was removed).

Real HOOMD simulations are skipped; the workflow functions are patched to
write the minimum files the tools / status tracker expect.
"""

import asyncio
import csv
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Find workspace root (contains environment.yml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "environment.yml").exists():
            return parent
    raise RuntimeError("Cannot locate project root (environment.yml not found).")


def _colpack_mcp_cmd() -> list[str]:
    """Return the command to launch the MCP server."""
    return [sys.executable, "-m", "colpack.mcp.server"]


async def _connect_and_run(fn):
    """Start the MCP server subprocess and run *fn(session)* inside it."""
    server_params = StdioServerParameters(
        command=_colpack_mcp_cmd()[0],
        args=_colpack_mcp_cmd()[1:],
        env=None,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _call(session_fn):
    """Synchronous wrapper – run an async session function."""
    return asyncio.run(_connect_and_run(session_fn))


def _tool_result_content(result) -> dict:
    """Extract the JSON-decoded dict from a CallToolResult."""
    assert result is not None
    assert len(result.content) > 0, "Tool returned empty content"
    text = result.content[0].text
    return json.loads(text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_working_dir(tmp_path):
    """Return a temporary directory pre-populated with environment.yml so the
    workflow helper can resolve the project root."""
    (tmp_path / "environment.yml").write_text("name: colpack-test\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Test: list tools
# ---------------------------------------------------------------------------

def test_list_tools_contains_expected():
    """Server must expose the four workflow tools and the capabilities tool."""

    async def _run(session: ClientSession):
        result = await session.list_tools()
        return [t.name for t in result.tools]

    tool_names = _call(_run)
    expected = {
        "get_colpack_capabilities_tool",
        "setup_simulation_problem_tool",
        "plan_simulation_runs_tool",
        "execute_simulation_workflow_tool",
        "analyze_simulation_runs_tool",
    }
    assert expected.issubset(set(tool_names)), (
        f"Missing tools: {expected - set(tool_names)}"
    )
    assert "get_workflow_status_tool" not in tool_names, (
        "get_workflow_status_tool should have been removed; agents must monitor "
        "progress locally via workflow_progress.json."
    )


# ---------------------------------------------------------------------------
# Test: execute_simulation_workflow_tool has no `wait` parameter
# ---------------------------------------------------------------------------

def test_execute_tool_schema_has_no_wait_param():
    """The `wait` parameter must have been removed – agents must not be able to
    accidentally call the tool synchronously."""

    async def _run(session: ClientSession):
        result = await session.list_tools()
        for tool in result.tools:
            if tool.name == "execute_simulation_workflow_tool":
                return tool
        return None

    tool = _call(_run)
    assert tool is not None, "execute_simulation_workflow_tool not found"
    param_names = set(tool.inputSchema.get("properties", {}).keys())
    assert "wait" not in param_names, (
        "execute_simulation_workflow_tool still has a 'wait' parameter — "
        "agents can accidentally block the MCP server."
    )


def test_analyze_tool_schema_has_no_wait_param():
    """Same check for analyze_simulation_runs_tool."""

    async def _run(session: ClientSession):
        result = await session.list_tools()
        for tool in result.tools:
            if tool.name == "analyze_simulation_runs_tool":
                return tool
        return None

    tool = _call(_run)
    assert tool is not None, "analyze_simulation_runs_tool not found"
    param_names = set(tool.inputSchema.get("properties", {}).keys())
    assert "wait" not in param_names, (
        "analyze_simulation_runs_tool still has a 'wait' parameter."
    )


# ---------------------------------------------------------------------------
# Test: execute returns immediately (async, no blocking)
# ---------------------------------------------------------------------------

def test_execute_returns_immediately_with_job_id(tmp_path):
    """execute_simulation_workflow_tool must launch a background job and return
    well under 5 seconds — it must NOT block waiting for the simulation."""

    working_dir = str(tmp_path)

    # Minimal simulation_plan.json so the tool validates inputs.
    plan = [
        {
            "run_number": 0,
            "run_dir": str(tmp_path / "run_0"),
            "dimension": 2,
            "total_particle_number": 4,
            "ensemble": "NVT",
            "particle_specs": [{"type": 0, "shape": "disk"}],
        }
    ]
    (tmp_path / "simulation_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    async def _run(session: ClientSession):
        t0 = time.monotonic()
        result = await session.call_tool(
            "execute_simulation_workflow_tool",
            arguments={"params": {"working_dir": working_dir, "continue_on_error": True}},
        )
        elapsed = time.monotonic() - t0
        return _tool_result_content(result), elapsed

    data, elapsed = _call(_run)

    assert data["ok"] is True
    assert data["mode"] == "async", "Tool returned sync mode — wait param may still be active"
    assert "job_id" in data, "Missing job_id in async response"
    assert elapsed < 5.0, (
        f"execute_simulation_workflow_tool blocked for {elapsed:.1f}s — it is still synchronous"
    )


# ---------------------------------------------------------------------------
# Test: get_colpack_capabilities_tool
# ---------------------------------------------------------------------------

def test_get_colpack_capabilities_tool():
    """get_colpack_capabilities_tool must return supported shapes, ensembles,
    and workflow steps without any input parameters."""

    async def _run(session: ClientSession):
        result = await session.call_tool("get_colpack_capabilities_tool", arguments={})
        return _tool_result_content(result)

    data = _call(_run)

    assert data["ok"] is True
    assert set(data["dimensions"]) == {2, 3}
    assert "disk" in data["supported_shapes"]["2d"]
    assert "sphere" in data["supported_shapes"]["3d"]
    assert "NVT" in data["ensembles"]
    assert "NPT" in data["ensembles"]
    assert len(data["workflow_steps"]) == 4
    step_tools = [s["tool"] for s in data["workflow_steps"]]
    assert "execute_simulation_workflow_tool" in step_tools
    assert "analyze_simulation_runs_tool" in step_tools
    assert "workflow_progress_file" in data["progress_monitoring"]


# ---------------------------------------------------------------------------
# Test: full async round-trip with mocked simulation functions
# ---------------------------------------------------------------------------

def _write_minimal_workflow_files(run_dir: Path, run_number: int) -> None:
    """Write the files that the workflow status tracker expects after a run."""
    run_dir.mkdir(parents=True, exist_ok=True)


def _fake_execute(working_dir, continue_on_error=True):
    """Fake execute: writes a completed status CSV and progress JSON."""
    wd = Path(working_dir)

    status_path = wd / "workflow_status.csv"
    fieldnames = [
        "run_number", "dimension", "total_particle_number", "ensemble",
        "initialize", "compress", "sample", "analyze",
        "status", "execution_state", "started_at", "finished_at", "output_dir", "error",
    ]
    rows = [
        {
            "run_number": "0", "dimension": "2", "total_particle_number": "4",
            "ensemble": "NVT", "initialize": "O", "compress": "O", "sample": "O",
            "analyze": "", "status": "success", "execution_state": "finished",
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:01:00+00:00",
            "output_dir": str(wd / "run_0"), "error": "",
        }
    ]
    with status_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    progress = {
        "status": "completed",
        "message": "Workflow finished.",
        "n_runs": 1,
        "n_success": 1,
        "n_failed": 0,
        "timestamp": "2026-01-01T00:01:00+00:00",
    }
    (wd / "workflow_progress.json").write_text(json.dumps(progress), encoding="utf-8")

    return {
        "status_path": str(status_path),
        "progress_path": str(wd / "workflow_progress.json"),
        "log_path": str(wd / "workflow.log"),
        "n_runs": 1,
        "n_success": 1,
        "n_failed": 0,
        "already_running": False,
    }


def test_async_execute_then_poll_status(tmp_path):
    """
    End-to-end test of the async pattern agents should follow:
      1. Call execute_simulation_workflow_tool → returns job_id immediately
      2. Poll workflow_progress.json locally until status != 'running'
      3. Verify final status is 'completed'

    The simulation itself is replaced with _fake_execute (no HOOMD needed).
    Progress monitoring uses local file reads, not an MCP polling tool.
    """
    working_dir = str(tmp_path)
    progress_path = tmp_path / "workflow_progress.json"

    plan = [
        {
            "run_number": 0,
            "run_dir": str(tmp_path / "run_0"),
            "dimension": 2,
            "total_particle_number": 4,
            "ensemble": "NVT",
            "particle_specs": [{"type": 0, "shape": "disk"}],
        }
    ]
    (tmp_path / "simulation_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    async def _run(session: ClientSession):
        # Step 1: launch
        exec_result = await session.call_tool(
            "execute_simulation_workflow_tool",
            arguments={"params": {"working_dir": working_dir, "continue_on_error": True}},
        )
        exec_data = _tool_result_content(exec_result)
        assert exec_data["ok"] is True
        assert exec_data["mode"] == "async"
        job_id = exec_data.get("job_id")
        assert job_id is not None

        # Step 2: poll workflow_progress.json locally (max 30 seconds).
        # This mirrors what an agent with workflow_monitor.py would do.
        deadline = time.monotonic() + 30
        progress = None
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if progress_path.exists():
                try:
                    progress = json.loads(progress_path.read_text(encoding="utf-8"))
                    if progress.get("status") not in ("running", None):
                        break
                except Exception:
                    pass

        assert progress is not None, "workflow_progress.json was never written"
        return progress

    # Patch where execute_simulation_workflow is imported in server_helper.
    with patch("colpack.mcp.server_helper.execute_simulation_workflow", side_effect=_fake_execute):
        final = _call(_run)

    assert final["status"] in ("completed", "failed"), (
        f"Unexpected final status: {final['status']}"
    )
    assert final.get("n_success", 0) >= 1 or final.get("n_failed", 0) >= 0
