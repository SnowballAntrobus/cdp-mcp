"""Tests for the knowledge-backed introspection tools.

We exercise the tools via the registered FastMCP instance rather than calling
the inner functions directly — that catches registration bugs and tool-schema
mismatches at the same time. We reach into ``_tool_manager`` to get the raw
Python payload (``convert_result=False``); the public ``FastMCP.call_tool``
returns a sequence of ``ContentBlock`` objects which are less convenient to
assert against in unit tests.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.tools import introspection

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_with_tools():
    mcp = FastMCP("test-cdp")
    index = KnowledgeIndex.load()
    introspection.register(mcp, index)
    return mcp


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    """Invoke a registered tool and return the raw Python payload."""
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_all_three_tools_registered(mcp_with_tools):
    tools = await mcp_with_tools.list_tools()
    names = {t.name for t in tools}
    assert {"list_categories", "list_programs", "get_program_info"} <= names


# ---------------------------------------------------------------------------
# list_categories
# ---------------------------------------------------------------------------


async def test_list_categories_returns_sorted_unique(mcp_with_tools):
    payload = await _call_raw(mcp_with_tools, "list_categories", {})
    assert payload == ["extend", "filter", "granular", "morph", "spectral-time"]


# ---------------------------------------------------------------------------
# list_programs
# ---------------------------------------------------------------------------


async def test_list_programs_no_filter_returns_all_five(mcp_with_tools):
    payload = await _call_raw(mcp_with_tools, "list_programs", {})
    assert len(payload) == 5
    keys = {(e["program"], e["mode"]) for e in payload}
    assert keys == {
        ("blur", "blur"),
        ("modify", "brassage"),
        ("morph", "morph"),
        ("extend", "loop"),
        ("filter", "sweeping"),
    }


async def test_list_programs_category_filter(mcp_with_tools):
    payload = await _call_raw(mcp_with_tools, "list_programs", {"category": "filter"})
    assert [(e["program"], e["mode"]) for e in payload] == [("filter", "sweeping")]


async def test_list_programs_domain_filter(mcp_with_tools):
    payload = await _call_raw(mcp_with_tools, "list_programs", {"domain": "spectral"})
    keys = {(e["program"], e["mode"]) for e in payload}
    assert keys == {("blur", "blur"), ("morph", "morph")}


async def test_list_programs_combined_filters_compose_and(mcp_with_tools):
    payload = await _call_raw(
        mcp_with_tools, "list_programs", {"category": "filter", "domain": "spectral"}
    )
    assert payload == []


async def test_list_programs_summary_dicts_have_expected_keys(mcp_with_tools):
    payload = await _call_raw(mcp_with_tools, "list_programs", {})
    expected_keys = {"program", "mode", "category", "domain", "curated", "description"}
    for entry in payload:
        assert expected_keys <= set(entry.keys())


# ---------------------------------------------------------------------------
# get_program_info
# ---------------------------------------------------------------------------


async def test_get_program_info_blur_blur_full_entry(mcp_with_tools):
    payload = await _call_raw(
        mcp_with_tools, "get_program_info", {"program": "blur", "mode": "blur"}
    )
    assert payload["program"] == "blur"
    assert payload["mode"] == "blur"
    assert payload["submode"] is None
    assert payload["domain"] == "spectral"
    assert payload["category"] == "spectral-time"
    assert payload["duration_model"] == {"kind": "static"}
    assert "blurring" in payload["parameters"]


async def test_get_program_info_modify_brassage_carries_submode(mcp_with_tools):
    payload = await _call_raw(
        mcp_with_tools,
        "get_program_info",
        {"program": "modify", "mode": "brassage"},
    )
    assert payload["submode"] == 2
    assert payload["duration_model"]["kind"] == "expression"
    assert payload["duration_model"]["expr"] == "indur / velocity"


async def test_get_program_info_missing_raises_tool_error(mcp_with_tools):
    """FastMCP propagates raised ``ToolError`` instances out of ``call_tool``
    (wrapped in another ``ToolError`` with an "Error executing tool ..."
    prefix). The wire-level effect is ``isError=true`` on the JSON-RPC
    response — verified end-to-end in the manual smoke test, not here.
    """
    with pytest.raises(ToolError, match="No knowledge entry"):
        await _call_raw(
            mcp_with_tools,
            "get_program_info",
            {"program": "nonexistent", "mode": "mode"},
        )
