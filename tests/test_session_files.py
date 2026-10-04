"""Tests for list_session_files(): patterns, tmp/ exclusion, entry cap."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.session import SessionManager
from cdp_mcp.tools import session_files as session_files_module


@pytest.fixture
def harness(tmp_path):
    mcp = FastMCP("test-cdp-session-tools")
    sessions_root = (tmp_path / "sessions").resolve()
    sessions = SessionManager(sessions_root, lambda: None)
    session_files_module.register(mcp, sessions=sessions)
    return mcp, sessions, sessions_root


async def _call(mcp: FastMCP, tool: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        tool, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# list_session_files()
# ---------------------------------------------------------------------------


def _populate(session):
    (session.inputs_dir / "a.wav").write_bytes(b"\x00" * 10)
    (session.inputs_dir / "b.txt").write_bytes(b"\x00" * 20)
    (session.envelopes_dir / "env.brk").write_bytes(b"\x00" * 30)
    nested = session.graphs_dir / "g1"
    nested.mkdir(parents=True)
    (nested / "n1_out.wav").write_bytes(b"\x00" * 40)
    (session.tmp_dir / "scratch.wav").write_bytes(b"\x00" * 50)


async def test_list_session_files_default_excludes_tmp(harness):
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("l1")
    _populate(session)

    payload = await _call(mcp, "list_session_files", {})
    assert payload["status"] == "ok"
    assert payload["truncated"] is False
    paths = [f["path"] for f in payload["files"]]
    assert paths == sorted(paths)
    assert "inputs/a.wav" in paths
    assert "graphs/g1/n1_out.wav" in paths
    assert "config.json" in paths
    assert not any(p.startswith("tmp/") for p in paths)
    sizes = {f["path"]: f["size_bytes"] for f in payload["files"]}
    assert sizes["graphs/g1/n1_out.wav"] == 40


async def test_list_session_files_bare_pattern_matches_all_depths(harness):
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("l1")
    _populate(session)
    payload = await _call(mcp, "list_session_files", {"pattern": "*.wav"})
    paths = [f["path"] for f in payload["files"]]
    assert paths == ["graphs/g1/n1_out.wav", "inputs/a.wav"]


async def test_list_session_files_slash_pattern_used_verbatim(harness):
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("l1")
    _populate(session)
    payload = await _call(
        mcp, "list_session_files", {"pattern": "inputs/*.wav"}
    )
    paths = [f["path"] for f in payload["files"]]
    assert paths == ["inputs/a.wav"]


async def test_list_session_files_invalid_patterns(harness):
    mcp, sessions, _ = harness
    sessions.set_active("l1")
    for bad in ("", "/etc/*", "../*"):
        payload = await _call(mcp, "list_session_files", {"pattern": bad})
        assert payload["status"] == "failed"
        assert any(
            e["type"] == "pattern_invalid" for e in payload["errors"]
        )


async def test_list_session_files_cap_500(harness):
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("l1")
    for i in range(510):
        (session.inputs_dir / f"f{i:04d}.dat").write_bytes(b"\x00")

    payload = await _call(mcp, "list_session_files", {"pattern": "*.dat"})
    assert payload["status"] == "ok"
    assert payload["count"] == 500
    assert len(payload["files"]) == 500
    assert payload["truncated"] is True
