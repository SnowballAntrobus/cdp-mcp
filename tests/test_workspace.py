"""Integration tests for the workspace tools (set_session, describe_workspace)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import workspace

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_cdp() -> CDPConfig:
    return CDPConfig(
        cdp_path=Path("/tmp/fake"),
        version="8.0.1-fake",
        detected_binaries=["blur"],
    )


@pytest.fixture
def mcp_with_workspace(tmp_path):
    mcp = FastMCP("test-cdp-workspace")
    sessions = SessionManager(tmp_path, lambda: _fake_cdp())
    latest_tracker = LatestTracker()
    workspace.register(
        mcp,
        sessions,
        latest_tracker=latest_tracker,
        cdp_config_provider=lambda: _fake_cdp(),
    )
    return mcp, sessions, tmp_path, latest_tracker


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


async def test_both_tools_registered(mcp_with_workspace):
    mcp, _, _, _ = mcp_with_workspace
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert {"set_session", "describe_workspace"} <= names


# ---------------------------------------------------------------------------
# set_session
# ---------------------------------------------------------------------------


async def test_set_session_happy_path_returns_expected_keys(mcp_with_workspace):
    mcp, _, tmp_path, _ = mcp_with_workspace
    payload = await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    assert payload["name"] == "frog_v1"
    assert payload["created"] is True
    assert payload["cdp_version"] == "8.0.1-fake"
    assert payload["graphs_count"] == 0
    assert payload["path"] == str(tmp_path / "frog_v1")
    assert payload["inputs_dir"] == str(tmp_path / "frog_v1" / "inputs")
    assert (tmp_path / "frog_v1" / "config.json").is_file()
    assert payload["warnings"] == []


async def test_set_session_second_call_returns_created_false(mcp_with_workspace):
    mcp, _, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    payload = await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    assert payload["created"] is False


async def test_set_session_invalid_name_raises_tool_error(mcp_with_workspace):
    mcp, _, _, _ = mcp_with_workspace
    with pytest.raises(ToolError, match="Invalid session name"):
        await _call_raw(mcp, "set_session", {"name": "foo bar"})


async def test_set_session_clears_latest_tracker(mcp_with_workspace):
    """set_session() resets the conversational state (latest, prev_1..) so
    each session activation starts fresh — design-doc Rule 2."""
    mcp, _, _, tracker = mcp_with_workspace

    # Activate a session, then push two entries onto the tracker.
    await _call_raw(mcp, "set_session", {"name": "sess_a"})
    tracker.update("g1", "n1")
    tracker.update("g2", "n1")
    assert tracker.latest == "g2:n1"
    assert len(tracker.recent_entries()) == 2

    # Re-activate (same name or different) → tracker is wiped.
    await _call_raw(mcp, "set_session", {"name": "sess_a"})
    assert tracker.latest is None
    assert tracker.recent_entries() == []


async def test_set_session_failure_does_not_clear_tracker(mcp_with_workspace):
    """Invalid name → ToolError, tracker stays intact (the previous
    conversational state shouldn't be lost on a typo)."""
    mcp, _, _, tracker = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "sess_a"})
    tracker.update("g1", "n1")
    assert tracker.latest == "g1:n1"

    with pytest.raises(ToolError):
        await _call_raw(mcp, "set_session", {"name": "foo bar"})  # invalid

    # Tracker survived the failed activation.
    assert tracker.latest == "g1:n1"


async def test_set_session_warns_on_cdp_version_mismatch(tmp_path):
    """Reactivating a session under a different CDP version surfaces a
    warning naming both versions. Verifies the full path from on-disk
    config.json through cdp_version_mismatch_warning into the response
    envelope, including simulated server-restart-after-CDP-upgrade."""
    sessions_root = tmp_path / "sessions"

    # First activation: create the session under "r7".
    mcp1 = FastMCP("test-1")
    config_v7 = CDPConfig(
        cdp_path=tmp_path / "fake_cdp",
        version="r7",
        detected_binaries=["fake"],
    )
    sessions1 = SessionManager(sessions_root, lambda: config_v7)
    workspace.register(
        mcp1,
        sessions1,
        latest_tracker=LatestTracker(),
        cdp_config_provider=lambda: config_v7,
    )
    create_payload = await _call_raw(mcp1, "set_session", {"name": "frog"})
    assert create_payload["created"] is True
    assert create_payload["cdp_version"] == "r7"
    assert create_payload["warnings"] == []

    # Second activation: same session on disk, different detected CDP.
    # Fresh MCP/SessionManager simulates a server restart after a CDP
    # upgrade.
    mcp2 = FastMCP("test-2")
    config_v8 = CDPConfig(
        cdp_path=tmp_path / "fake_cdp",
        version="r8",
        detected_binaries=["fake"],
    )
    sessions2 = SessionManager(sessions_root, lambda: config_v8)
    workspace.register(
        mcp2,
        sessions2,
        latest_tracker=LatestTracker(),
        cdp_config_provider=lambda: config_v8,
    )
    reactivate_payload = await _call_raw(mcp2, "set_session", {"name": "frog"})
    assert reactivate_payload["created"] is False
    assert reactivate_payload["cdp_version"] == "r7"  # provenance preserved
    assert len(reactivate_payload["warnings"]) == 1
    msg = reactivate_payload["warnings"][0]
    assert "r7" in msg
    assert "r8" in msg
    assert "frog" in msg


# ---------------------------------------------------------------------------
# describe_workspace
# ---------------------------------------------------------------------------


async def test_describe_workspace_no_active_session(mcp_with_workspace):
    mcp, _, _, _ = mcp_with_workspace
    payload = await _call_raw(mcp, "describe_workspace", {})
    assert payload["active_session"] is None
    assert payload["available_sessions"] == []
    assert "Call set_session" in payload["hint"]


async def test_describe_workspace_active_session_minimal(mcp_with_workspace):
    mcp, _, tmp_path, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    payload = await _call_raw(mcp, "describe_workspace", {})
    assert payload["active_session"] == "frog_v1"
    assert payload["session_path"] == str(tmp_path / "frog_v1")
    assert payload["cdp_version_at_creation"] == "8.0.1-fake"
    assert payload["input_files"] == []
    assert payload["input_count"] == 0
    assert payload["graph_count"] == 0
    assert payload["available_sessions"] == ["frog_v1"]
    # disk_usage > 0 because config.json + tags.json + journal.md exist.
    assert payload["disk_usage_bytes"] > 0


async def test_describe_workspace_counts_input_files(mcp_with_workspace):
    mcp, _, tmp_path, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    inputs = tmp_path / "frog_v1" / "inputs"
    (inputs / "frog.wav").write_bytes(b"riffstub")
    (inputs / "frog2.wav").write_bytes(b"riffstub2")
    # A subdirectory in inputs/ is ignored (input_files is flat).
    (inputs / "subdir").mkdir()
    payload = await _call_raw(mcp, "describe_workspace", {})
    assert payload["input_files"] == ["frog.wav", "frog2.wav"]
    assert payload["input_count"] == 2


async def test_available_sessions_consistent_across_tools(mcp_with_workspace):
    mcp, _, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "a"})
    await _call_raw(mcp, "set_session", {"name": "b"})
    desc = await _call_raw(mcp, "describe_workspace", {})
    # set_session doesn't return available_sessions itself, but describe_workspace
    # should list both newly-created sessions sorted.
    assert desc["available_sessions"] == ["a", "b"]
    assert desc["active_session"] == "b"
