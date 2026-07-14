"""Integration tests for the write_data_file tool."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.security import validate_command
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import data_files
from cdp_mcp.tools.data_files import _MAX_DATA_FILE_BYTES

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
def mcp_with_data_files(tmp_path):
    mcp = FastMCP("test-cdp-data-files")
    sessions = SessionManager(tmp_path, lambda: _fake_cdp())
    data_files.register(mcp, sessions=sessions)
    return mcp, sessions


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Registration + happy path
# ---------------------------------------------------------------------------


async def test_tool_registered(mcp_with_data_files):
    mcp, _ = mcp_with_data_files
    tools = await mcp.list_tools()
    assert "write_data_file" in {t.name for t in tools}


async def test_happy_path_writes_and_rereads(mcp_with_data_files):
    mcp, sessions = mcp_with_data_files
    session, _ = sessions.set_active("s1")
    content = "0.0 1.0\n0.5 2.0\n1.0 1.0\n"
    payload = await _call_raw(
        mcp, "write_data_file", {"name": "grid.brk", "content": content}
    )
    assert payload["status"] == "ok"
    assert payload["size_bytes"] == len(content.encode("utf-8"))
    assert payload["overwritten"] is False
    path = Path(payload["path"])
    assert path == session.root / "data" / "grid.brk"
    assert path.read_text(encoding="utf-8") == content


async def test_no_active_session_is_structured_error(mcp_with_data_files):
    mcp, _ = mcp_with_data_files
    payload = await _call_raw(
        mcp, "write_data_file", {"name": "grid.dat", "content": "1 2\n"}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "no_active_session"


# ---------------------------------------------------------------------------
# Validation rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "sub/x.txt",
        "../x.txt",
        "..\\x.txt",
        "..",
        ".",
        "",
        ".hidden.txt",
        "/etc/passwd.txt",
    ],
)
async def test_rejects_non_basenames(mcp_with_data_files, bad_name):
    mcp, sessions = mcp_with_data_files
    session, _ = sessions.set_active("s1")
    payload = await _call_raw(
        mcp, "write_data_file", {"name": bad_name, "content": "x"}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "invalid_data_file_name"
    assert not (session.root / "data").exists()


@pytest.mark.parametrize("bad_name", ["notes.md", "clip.wav", "run.py", "noext"])
async def test_rejects_disallowed_extensions(mcp_with_data_files, bad_name):
    mcp, sessions = mcp_with_data_files
    sessions.set_active("s1")
    payload = await _call_raw(
        mcp, "write_data_file", {"name": bad_name, "content": "x"}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "unsupported_data_file_extension"


async def test_rejects_oversized_content(mcp_with_data_files):
    mcp, sessions = mcp_with_data_files
    session, _ = sessions.set_active("s1")
    payload = await _call_raw(
        mcp,
        "write_data_file",
        {"name": "big.txt", "content": "x" * (_MAX_DATA_FILE_BYTES + 1)},
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "data_file_too_large"
    assert not (session.root / "data" / "big.txt").exists()

    # The cap is a UTF-8 *byte* length: multibyte chars trip it at half
    # the character count.
    payload = await _call_raw(
        mcp,
        "write_data_file",
        {"name": "wide.txt", "content": "é" * (_MAX_DATA_FILE_BYTES // 2 + 1)},
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "data_file_too_large"


async def test_content_at_cap_is_accepted(mcp_with_data_files):
    mcp, sessions = mcp_with_data_files
    sessions.set_active("s1")
    payload = await _call_raw(
        mcp,
        "write_data_file",
        {"name": "cap.txt", "content": "x" * _MAX_DATA_FILE_BYTES},
    )
    assert payload["status"] == "ok"
    assert payload["size_bytes"] == _MAX_DATA_FILE_BYTES


# ---------------------------------------------------------------------------
# Overwrite semantics
# ---------------------------------------------------------------------------


async def test_overwrite_allowed_and_flagged(mcp_with_data_files):
    mcp, sessions = mcp_with_data_files
    sessions.set_active("s1")
    first = await _call_raw(
        mcp, "write_data_file", {"name": "notes.txt", "content": "v1\n"}
    )
    assert first["status"] == "ok"
    assert first["overwritten"] is False

    second = await _call_raw(
        mcp, "write_data_file", {"name": "notes.txt", "content": "v2 longer\n"}
    )
    assert second["status"] == "ok"
    assert second["overwritten"] is True
    assert second["path"] == first["path"]
    assert second["size_bytes"] == len(b"v2 longer\n")
    assert Path(second["path"]).read_text(encoding="utf-8") == "v2 longer\n"


# ---------------------------------------------------------------------------
# Security-gate acceptance
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


async def test_written_file_passes_security_gate(
    mcp_with_data_files, tmp_path_factory
):
    """The path-scope check allows any path inside the session tree, so
    <session>/data/ files pass validate_command without changes."""
    mcp, sessions = mcp_with_data_files
    session, _ = sessions.set_active("s1")
    payload = await _call_raw(
        mcp, "write_data_file", {"name": "pattern.dat", "content": "1 2 3\n"}
    )
    assert payload["status"] == "ok"

    fake_cdp = tmp_path_factory.mktemp("gate_cdp").resolve()
    _make_executable(fake_cdp / "blur")
    cache_root = tmp_path_factory.mktemp("gate_cache").resolve()

    validated = validate_command(
        ["blur", payload["path"], "out.ana", "10"],
        fake_cdp,
        session.root.resolve(),
        cache_root,
    )
    assert validated[0] == str(fake_cdp / "blur")
    assert validated[1] == payload["path"]
