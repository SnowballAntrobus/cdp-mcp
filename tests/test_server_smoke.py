"""Smoke test for FastMCP server assembly.

Does NOT exercise the stdio transport — that's the manual acceptance test
documented in the README. We only verify here that the server builds and
the three introspection tools are registered. Deep behavior tests live in
``test_introspection.py``.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def cdp_stub(tmp_path, monkeypatch):
    for name in ("housekeep", "blur", "modify", "pvoc"):
        _make_executable(tmp_path / name)
    monkeypatch.setenv("CDP_PATH", str(tmp_path))
    return tmp_path


async def test_server_builds_and_registers_introspection_tools(cdp_stub):
    from cdp_mcp.server import create_server

    server = create_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    assert {"list_categories", "list_programs", "get_program_info"} <= tool_names


async def test_server_starts_even_without_cdp_path(monkeypatch):
    monkeypatch.delenv("CDP_PATH", raising=False)
    from cdp_mcp.server import create_server

    server = create_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    # Introspection tools work even without CDP — they only need the
    # knowledge index, which is built from packaged JSON.
    assert "list_categories" in tool_names
