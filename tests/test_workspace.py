"""Integration tests for the workspace tools (set_session, describe_workspace)."""

from __future__ import annotations

import json
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
def mcp_with_workspace(tmp_path, tmp_path_factory):
    mcp = FastMCP("test-cdp-workspace")
    # cache_root lives OUTSIDE tmp_path because tmp_path is the sessions
    # root and list_sessions() returns every subdir of it — a cache subdir
    # nested under tmp_path would show up as a phantom session.
    cache_root = tmp_path_factory.mktemp("cache").resolve()
    sessions = SessionManager(tmp_path, lambda: _fake_cdp())
    latest_tracker = LatestTracker()
    workspace.register(
        mcp,
        sessions,
        latest_tracker=latest_tracker,
        cdp_config_provider=lambda: _fake_cdp(),
        cache_root=cache_root,
    )
    return mcp, sessions, tmp_path, latest_tracker, cache_root


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


async def test_both_tools_registered(mcp_with_workspace):
    mcp, _, _, _, _ = mcp_with_workspace
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert {"set_session", "describe_workspace"} <= names


# ---------------------------------------------------------------------------
# set_session
# ---------------------------------------------------------------------------


async def test_set_session_happy_path_returns_expected_keys(mcp_with_workspace):
    mcp, _, tmp_path, _, _ = mcp_with_workspace
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
    mcp, _, _, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    payload = await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    assert payload["created"] is False


async def test_set_session_invalid_name_raises_tool_error(mcp_with_workspace):
    mcp, _, _, _, _ = mcp_with_workspace
    with pytest.raises(ToolError, match="Invalid session name"):
        await _call_raw(mcp, "set_session", {"name": "foo bar"})


async def test_set_session_clears_latest_tracker(mcp_with_workspace):
    """set_session() resets the conversational state (latest, prev_1..) so
    each session activation starts fresh — design-doc Rule 2."""
    mcp, _, _, tracker, _ = mcp_with_workspace

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
    mcp, _, _, tracker, _ = mcp_with_workspace
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
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

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
        cache_root=cache_root,
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
        cache_root=cache_root,
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
    mcp, _, _, _, _ = mcp_with_workspace
    payload = await _call_raw(mcp, "describe_workspace", {})
    assert payload["active_session"] is None
    assert payload["available_sessions"] == []
    assert "Call set_session" in payload["hint"]


async def test_describe_workspace_active_session_minimal(mcp_with_workspace):
    mcp, _, tmp_path, _, _ = mcp_with_workspace
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
    mcp, _, tmp_path, _, _ = mcp_with_workspace
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
    mcp, _, _, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "a"})
    await _call_raw(mcp, "set_session", {"name": "b"})
    desc = await _call_raw(mcp, "describe_workspace", {})
    # set_session doesn't return available_sessions itself, but describe_workspace
    # should list both newly-created sessions sorted.
    assert desc["available_sessions"] == ["a", "b"]
    assert desc["active_session"] == "b"


# ---------------------------------------------------------------------------
# read_envelope + envelope_files in describe_workspace
# ---------------------------------------------------------------------------


async def test_describe_workspace_lists_envelope_files(mcp_with_workspace):
    mcp, _, tmp_path, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "envs"})
    envelopes = tmp_path / "envs" / "envelopes"
    (envelopes / "shift.brk").write_text("0 5\n5 25\n")
    (envelopes / "ramp.brk").write_text("0 1\n10 100\n")
    # Subdirectory inside envelopes/ is skipped (flat listing convention).
    (envelopes / "subdir").mkdir()
    desc = await _call_raw(mcp, "describe_workspace", {})
    assert desc["envelope_files"] == ["ramp.brk", "shift.brk"]
    assert desc["envelope_count"] == 2


async def test_read_envelope_happy_path(mcp_with_workspace):
    mcp, _, tmp_path, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "envs"})
    contents = "0 5\n5 25\n10 50\n"
    (tmp_path / "envs" / "envelopes" / "shift.brk").write_text(contents)
    payload = await _call_raw(mcp, "read_envelope", {"name": "shift.brk"})
    assert payload["name"] == "shift.brk"
    assert payload["content"] == contents
    assert payload["size_bytes"] == len(contents.encode("utf-8"))
    assert payload["truncated"] is False
    assert payload["path"].endswith("/envelopes/shift.brk")


async def test_read_envelope_requires_active_session(mcp_with_workspace):
    mcp, _, _, _, _ = mcp_with_workspace
    # No set_session called yet.
    with pytest.raises(ToolError, match="No active session"):
        await _call_raw(mcp, "read_envelope", {"name": "shift.brk"})


async def test_read_envelope_rejects_path_separators(mcp_with_workspace):
    mcp, _, _, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "envs"})
    with pytest.raises(ToolError, match="bare basename"):
        await _call_raw(mcp, "read_envelope", {"name": "sub/foo.brk"})
    with pytest.raises(ToolError, match="bare basename"):
        await _call_raw(mcp, "read_envelope", {"name": "../escape.brk"})


async def test_read_envelope_rejects_unsupported_extension(
    mcp_with_workspace,
):
    mcp, _, tmp_path, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "envs"})
    # Even if a wav happens to live in envelopes/, the tool refuses.
    (tmp_path / "envs" / "envelopes" / "foo.wav").write_bytes(b"riff stub")
    with pytest.raises(ToolError, match="Unsupported envelope extension"):
        await _call_raw(mcp, "read_envelope", {"name": "foo.wav"})


async def test_read_envelope_truncates_large_files(mcp_with_workspace):
    mcp, _, tmp_path, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "envs"})
    # 100 KiB > 64 KiB cap.
    big = "x" * (100 * 1024)
    (tmp_path / "envs" / "envelopes" / "big.brk").write_text(big)
    payload = await _call_raw(mcp, "read_envelope", {"name": "big.brk"})
    assert payload["truncated"] is True
    assert payload["size_bytes"] == 100 * 1024
    assert len(payload["content"]) == 64 * 1024


# ---------------------------------------------------------------------------
# Task 10 — Cache block in describe_workspace
# ---------------------------------------------------------------------------


async def test_describe_workspace_reports_cache_sizes(mcp_with_workspace):
    """The ``cache`` block in describe_workspace mirrors
    :func:`cache_size_bytes` and includes a derived ``total_bytes``."""
    mcp, _, _, _, cache_root = mcp_with_workspace
    # Seed each tier with known sizes.
    (cache_root / "pvoc").mkdir()
    (cache_root / "pvoc" / "abc.ana").write_bytes(b"x" * 1000)
    (cache_root / "analysis").mkdir()
    (cache_root / "analysis" / "a.json").write_text("y" * 250)
    (cache_root / "visualizations").mkdir()
    (cache_root / "visualizations" / "v.png").write_bytes(b"z" * 500)

    await _call_raw(mcp, "set_session", {"name": "s1"})
    desc = await _call_raw(mcp, "describe_workspace", {})
    cache = desc["cache"]
    assert cache["pvoc_bytes"] == 1000
    assert cache["analysis_bytes"] == 250
    assert cache["visualizations_bytes"] == 500
    assert cache["audition_bytes"] == 0  # populated by Task 11
    assert cache["total_bytes"] == 1750


async def test_describe_workspace_no_session_includes_cache_block(
    mcp_with_workspace,
):
    """Even before a session is active, the cache block is reported so
    the LLM can see disk pressure from prior sessions."""
    mcp, _, _, _, cache_root = mcp_with_workspace
    (cache_root / "pvoc").mkdir()
    (cache_root / "pvoc" / "abc.ana").write_bytes(b"x" * 100)
    desc = await _call_raw(mcp, "describe_workspace", {})
    assert desc["active_session"] is None
    assert desc["cache"]["pvoc_bytes"] == 100
    assert desc["cache"]["total_bytes"] == 100


# ---------------------------------------------------------------------------
# describe_workspace: history (design-doc commitment, added Phase 2)
# ---------------------------------------------------------------------------


async def test_describe_workspace_history_maps_graphs_to_primary_outputs(
    mcp_with_workspace,
):
    mcp, _, tmp_path, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    graphs = tmp_path / "frog_v1" / "graphs"

    # Graph A: auto-PVOC node (n1) + main op (n2) → primary is n2's file.
    a = graphs / "20260101T000000-blur-blur"
    a.mkdir(parents=True)
    (a / "node_index.json").write_text(
        '{"n1": "n1_pvoc-anal.ana", "n2": "n2_blur-blur.ana"}'
    )
    # Graph B: ten nodes — numeric ordering must pick n10, not n9.
    b = graphs / "20260101T000001-graph"
    b.mkdir()
    index = {f"n{i}": f"n{i}_op.wav" for i in range(1, 11)}
    (b / "node_index.json").write_text(json.dumps(index))
    # Graph C: empty index (validation-stage failure) → None.
    c = graphs / "20260101T000002-failed"
    c.mkdir()
    (c / "node_index.json").write_text("{}")
    # Graph D: corrupt index → None, not a crash.
    d = graphs / "20260101T000003-corrupt"
    d.mkdir()
    (d / "node_index.json").write_text("{nope")

    payload = await _call_raw(mcp, "describe_workspace", {})
    assert payload["history"] == {
        "20260101T000000-blur-blur": "n2_blur-blur.ana",
        "20260101T000001-graph": "n10_op.wav",
        "20260101T000002-failed": None,
        "20260101T000003-corrupt": None,
    }
    assert payload["graph_count"] == 4


async def test_describe_workspace_history_empty_session(mcp_with_workspace):
    mcp, _, _, _, _ = mcp_with_workspace
    await _call_raw(mcp, "set_session", {"name": "frog_v1"})
    payload = await _call_raw(mcp, "describe_workspace", {})
    assert payload["history"] == {}
