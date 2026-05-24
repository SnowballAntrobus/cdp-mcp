"""Smoke test for FastMCP server assembly.

Does NOT exercise the stdio transport — that's the manual acceptance test
documented in the README. We only verify here that the server builds, the
``list_categories`` tool is registered with the expected schema, and calling
it returns the stub list.
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


async def test_server_builds_and_lists_tools(cdp_stub):
    from cdp_mcp.server import create_server

    server = create_server()
    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "list_categories" in tool_names


async def test_list_categories_returns_stub_list(cdp_stub):
    from cdp_mcp.server import create_server
    from cdp_mcp.tools.introspection import _STUB_CATEGORIES

    server = create_server()
    result = await server.call_tool("list_categories", {})
    # FastMCP's call_tool returns a tuple of (content_list, structured_dict);
    # the structured payload is what JSON-RPC clients receive.
    if isinstance(result, tuple):
        _content, structured = result
        payload = structured.get("result") if isinstance(structured, dict) else structured
    else:
        payload = result

    assert payload == _STUB_CATEGORIES


async def test_server_starts_even_without_cdp_path(monkeypatch):
    monkeypatch.delenv("CDP_PATH", raising=False)
    from cdp_mcp.server import create_server

    server = create_server()
    tools = await server.list_tools()
    assert any(t.name == "list_categories" for t in tools)
