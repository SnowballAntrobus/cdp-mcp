"""Integration tests for the execute() tool.

Uses ``fake_subprocess.py`` (Task 4 fixture) via a symlink into a tmp
``CDP_PATH``, so the tool's binary-resolution path works against an
executable that's discoverable by name. Sets
``CDP_MCP_DISABLE_ARCH_X86_64=1`` because the venv's Python is arm64-native
and ``arch -x86_64`` would fail with "Bad CPU type in executable".
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import execute as execute_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_cdp_path(tmp_path, monkeypatch):
    """Tmp CDP_PATH with `fake_cdp` as a real file (not a symlink).

    We deliberately *copy* fake_subprocess.py rather than symlinking because
    the binary security check resolves symlinks — a symlink whose target
    lies outside CDP_PATH gets rejected (correct for production: defends
    against malicious symlinks in CDP_PATH). For the test fixture we want
    the file to look like a genuine CDP-installed binary.
    """
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    fake_binary = cdp / "fake_cdp"
    shutil.copy2(_FAKE_SUBPROCESS, fake_binary)
    fake_binary.chmod(0o755)
    return cdp


def _make_cdp_config(cdp_path: Path) -> CDPConfig:
    return CDPConfig(cdp_path=cdp_path, version="fake", detected_binaries=["fake_cdp"])


@pytest.fixture
def mcp_with_execute(fake_cdp_path, tmp_path):
    """FastMCP with execute() registered against a fake CDP install."""
    mcp = FastMCP("test-cdp-execute")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: _make_cdp_config(fake_cdp_path))
    tracker = LatestTracker()
    execute_module.register(
        mcp,
        sessions=sessions,
        cdp_config_provider=lambda: _make_cdp_config(fake_cdp_path),
        latest_tracker=tracker,
        cache_root=cache_root,
    )
    return mcp, sessions, tracker, fake_cdp_path, cache_root


@pytest.fixture
def mcp_without_cdp(tmp_path):
    """FastMCP with execute() registered but the CDP provider returns None."""
    mcp = FastMCP("test-cdp-execute-nocdp")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: None)
    tracker = LatestTracker()
    execute_module.register(
        mcp,
        sessions=sessions,
        cdp_config_provider=lambda: None,
        latest_tracker=tracker,
        cache_root=cache_root,
    )
    return mcp, sessions


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Pre-flight failure paths (no subprocess)
# ---------------------------------------------------------------------------


async def test_no_active_session(mcp_with_execute, monkeypatch):
    mcp, _sessions, _tracker, _cdp_path, _cache = mcp_with_execute
    # run_cdp_command must NOT be invoked. Patch it to fail loudly if so.
    fake_run = AsyncMock(side_effect=AssertionError("subprocess should not run"))
    monkeypatch.setattr("cdp_mcp.tools.execute.run_cdp_command", fake_run)

    payload = await _call_raw(mcp, "execute", {"command": ["fake_cdp"]})
    assert payload["status"] == "failed"
    types = {e["type"] for e in payload["errors"]}
    assert "no_active_session" in types
    fake_run.assert_not_called()


async def test_cdp_not_configured(mcp_without_cdp, monkeypatch):
    mcp, sessions = mcp_without_cdp
    sessions.set_active("s1")
    fake_run = AsyncMock(side_effect=AssertionError("subprocess should not run"))
    monkeypatch.setattr("cdp_mcp.tools.execute.run_cdp_command", fake_run)

    payload = await _call_raw(mcp, "execute", {"command": ["fake_cdp"]})
    assert payload["status"] == "failed"
    types = {e["type"] for e in payload["errors"]}
    assert "cdp_not_configured" in types
    fake_run.assert_not_called()


async def test_security_violation_skips_subprocess(mcp_with_execute, monkeypatch):
    mcp, sessions, _tracker, _cdp_path, _cache = mcp_with_execute
    sessions.set_active("s1")
    fake_run = AsyncMock(side_effect=AssertionError("subprocess should not run"))
    monkeypatch.setattr("cdp_mcp.tools.execute.run_cdp_command", fake_run)

    payload = await _call_raw(
        mcp, "execute", {"command": ["fake_cdp", "input.wav; rm /tmp"]}
    )
    assert payload["status"] == "failed"
    types = {e["type"] for e in payload["errors"]}
    assert "metacharacter_rejected" in types
    fake_run.assert_not_called()


async def test_binary_outside_cdp_path_rejected(mcp_with_execute, monkeypatch):
    mcp, sessions, _tracker, _cdp_path, _cache = mcp_with_execute
    sessions.set_active("s1")
    fake_run = AsyncMock(side_effect=AssertionError("subprocess should not run"))
    monkeypatch.setattr("cdp_mcp.tools.execute.run_cdp_command", fake_run)

    payload = await _call_raw(mcp, "execute", {"command": ["/bin/echo", "hi"]})
    assert payload["status"] == "failed"
    types = {e["type"] for e in payload["errors"]}
    assert "binary_not_in_cdp_path" in types
    fake_run.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path through to real subprocess
# ---------------------------------------------------------------------------


async def test_happy_path_stdout_captured(mcp_with_execute):
    mcp, sessions, _tracker, _cdp_path, _cache = mcp_with_execute
    sessions.set_active("s1")

    payload = await _call_raw(
        mcp,
        "execute",
        {"command": ["fake_cdp", "--stdout", "hello-execute", "--exit", "0"]},
    )
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert "hello-execute" in payload["stdout"]
    assert payload["errors"] == []
    assert payload["cached"] is False
    # Context block populated.
    assert payload["context"]["active_graph"] is None
    assert payload["context"]["available_sources"] == []


async def test_nonzero_exit_reported_as_subprocess_error(mcp_with_execute):
    mcp, sessions, _tracker, _cdp_path, _cache = mcp_with_execute
    sessions.set_active("s1")
    payload = await _call_raw(
        mcp, "execute", {"command": ["fake_cdp", "--exit", "1"]}
    )
    assert payload["status"] == "failed"
    assert payload["exit_code"] == 1
    types = {e["type"] for e in payload["errors"]}
    assert "subprocess_error" in types


@pytest.mark.timeout(5)
async def test_timeout_reported(mcp_with_execute):
    mcp, sessions, _tracker, _cdp_path, _cache = mcp_with_execute
    sessions.set_active("s1")
    payload = await _call_raw(
        mcp,
        "execute",
        {"command": ["fake_cdp", "--sleep", "5"], "timeout_seconds": 0.5},
    )
    assert payload["status"] == "failed"
    assert payload["exit_code"] is None
    types = {e["type"] for e in payload["errors"]}
    assert "timeout" in types


# ---------------------------------------------------------------------------
# Context block details
# ---------------------------------------------------------------------------


async def test_context_block_lists_input_files_and_latest(mcp_with_execute):
    mcp, sessions, tracker, _cdp_path, _cache = mcp_with_execute
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "a.wav").write_bytes(b"x")
    (session.inputs_dir / "b.wav").write_bytes(b"x")
    tracker.update("graph_abc", "n1")

    payload = await _call_raw(
        mcp,
        "execute",
        {"command": ["fake_cdp", "--stdout", "hi", "--exit", "0"]},
    )
    assert payload["status"] == "ok"
    ctx = payload["context"]
    assert ctx["available_sources"] == ["a.wav", "b.wav"]
    assert ctx["active_graph"] is None
    assert ctx["latest"] == "graph_abc:n1"
    assert ctx["recent_graphs"] == []
