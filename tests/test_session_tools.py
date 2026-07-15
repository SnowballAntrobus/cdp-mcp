"""Tests for set_config() and list_session_files() — user_config
persistence (round-trip, allowlist, re-activation) and session-tree
listing (patterns, tmp/ exclusion, entry cap)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.session import SessionManager
from cdp_mcp.tools import session_config as session_config_module


@pytest.fixture
def harness(tmp_path):
    mcp = FastMCP("test-cdp-session-tools")
    sessions_root = (tmp_path / "sessions").resolve()
    sessions = SessionManager(sessions_root, lambda: None)
    session_config_module.register(mcp, sessions=sessions)
    return mcp, sessions, sessions_root


async def _call(mcp: FastMCP, tool: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        tool, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# set_config()
# ---------------------------------------------------------------------------


async def test_set_config_roundtrip_and_on_disk(harness):
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("c1")

    payload = await _call(
        mcp, "set_config", {"key": "disk_budget_soft_gb", "value": 2.5}
    )
    assert payload["status"] == "ok"
    assert payload["config"] == {"disk_budget_soft_gb": 2.5}

    payload = await _call(
        mcp, "set_config", {"key": "disk_budget_hard_gb", "value": 10}
    )
    assert payload["config"] == {
        "disk_budget_soft_gb": 2.5,
        "disk_budget_hard_gb": 10.0,
    }

    on_disk = json.loads(session.config_path.read_text())
    assert on_disk["user_config"] == {
        "disk_budget_soft_gb": 2.5,
        "disk_budget_hard_gb": 10.0,
    }
    # The rest of the config contract is untouched.
    assert on_disk["session_name"] == "c1"


async def test_set_config_unknown_key_lists_allowed(harness):
    mcp, sessions, _ = harness
    sessions.set_active("c1")
    payload = await _call(
        mcp, "set_config", {"key": "favourite_colour", "value": 1.0}
    )
    assert payload["status"] == "failed"
    (error,) = payload["errors"]
    assert error["type"] == "config_key_unknown"
    assert "disk_budget_soft_gb" in error["fix"]
    assert "disk_budget_hard_gb" in error["fix"]


async def test_set_config_invalid_values(harness):
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("c1")
    for bad in (0, -1.5):
        payload = await _call(
            mcp, "set_config", {"key": "disk_budget_soft_gb", "value": bad}
        )
        assert payload["status"] == "failed"
        assert any(
            e["type"] == "config_value_invalid" for e in payload["errors"]
        )
    assert json.loads(session.config_path.read_text())["user_config"] == {}


async def test_set_config_no_session(harness):
    mcp, _, _ = harness
    payload = await _call(
        mcp, "set_config", {"key": "disk_budget_soft_gb", "value": 1.0}
    )
    assert payload["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in payload["errors"])


async def test_set_config_persists_across_manager_reactivation(harness):
    """A fresh SessionManager (server restart) re-loads user_config from
    config.json."""
    mcp, sessions, sessions_root = harness
    sessions.set_active("c1")
    await _call(
        mcp, "set_config", {"key": "disk_budget_hard_gb", "value": 4.0}
    )

    fresh = SessionManager(sessions_root, lambda: None)
    session, created = fresh.set_active("c1")
    assert created is False
    assert session.config.user_config == {"disk_budget_hard_gb": 4.0}


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
