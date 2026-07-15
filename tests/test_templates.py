"""Integration tests for save_graph / load_graph / list_graphs, plus a
registration smoke test for the MCP prompt templates.

Graph directories are hand-built on disk with graph()-shaped and
process()-shaped graph.json files (field layout copied from
graph_tool._execute_pass and node_validation's set_graph_definition
call) so template extraction is exercised without running CDP.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp import prompts
from cdp_mcp.config import CDPConfig
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import templates as templates_module

# ---------------------------------------------------------------------------
# Fixtures + hand-built graph helpers
# ---------------------------------------------------------------------------

_GRAPH_NODES = [
    {"id": "b1", "op": "blur blur", "in": "src", "params": {"blurring": 40}},
    {"id": "s1", "op": "stretch time", "in": "b1",
     "params": {"timestretch": 2.0}},
]
_GRAPH_DEFINITION = {
    "inputs": {"src": "frog.wav"},
    "nodes": _GRAPH_NODES,
    "output": "s1",
    "issued_at": "2026-07-13T00:00:00+00:00",  # run-specific; not templated
}


def _fake_cdp() -> CDPConfig:
    return CDPConfig(
        cdp_path=Path("/tmp/fake"),
        version="8.0.1-fake",
        detected_binaries=["blur"],
    )


@pytest.fixture
def env(tmp_path):
    mcp = FastMCP("test-cdp-templates")
    sessions = SessionManager(tmp_path, lambda: _fake_cdp())
    templates_module.register(mcp, sessions=sessions)
    session, _ = sessions.set_active("templates_test")
    return mcp, sessions, session


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


def _make_graph_dir(
    session,
    graph_id: str,
    definition: dict | None,
    node_index: dict | None = None,
) -> Path:
    root = session.graphs_dir / graph_id
    root.mkdir(parents=True)
    if definition is not None:
        (root / "graph.json").write_text(
            json.dumps(definition, indent=2, sort_keys=True) + "\n"
        )
    (root / "node_index.json").write_text(
        json.dumps(node_index or {}, indent=2) + "\n"
    )
    (root / "lineage.json").write_text('{"nodes": {}}\n')
    return root


def _process_style_definition() -> dict:
    """graph.json as written by process() — no 'nodes' key."""
    return {
        "program": "blur",
        "mode": "blur",
        "input": "frog.wav",
        "params": {"blurring": 40},
        "output_name": None,
    }


# ---------------------------------------------------------------------------
# Registration + preconditions
# ---------------------------------------------------------------------------


async def test_tools_registered(env):
    mcp, *_ = env
    tools = {t.name for t in await mcp.list_tools()}
    assert {"save_graph", "load_graph", "list_graphs"} <= tools


@pytest.mark.parametrize(
    "tool, args",
    [
        ("save_graph", {"name": "t"}),
        ("load_graph", {"name": "t"}),
        ("list_graphs", {}),
    ],
)
async def test_no_active_session_is_structured_error(tmp_path, tool, args):
    mcp = FastMCP("test-cdp-templates-nosession")
    sessions = SessionManager(tmp_path, lambda: _fake_cdp())
    templates_module.register(mcp, sessions=sessions)
    payload = await _call_raw(mcp, tool, args)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "no_active_session"


# ---------------------------------------------------------------------------
# save_graph
# ---------------------------------------------------------------------------


async def test_save_graph_explicit_id_strips_run_specific_fields(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    payload = await _call_raw(
        mcp, "save_graph", {"name": "fog", "graph_id": "gA"}
    )
    assert payload["status"] == "ok"
    assert payload["name"] == "fog"
    assert payload["source_graph_id"] == "gA"
    assert payload["node_count"] == 2
    assert payload["overwritten"] is False
    saved = json.loads(
        (session.templates_dir / "fog.json").read_text(encoding="utf-8")
    )
    assert saved == {
        "inputs": {"src": "frog.wav"},
        "nodes": _GRAPH_NODES,
        "output": "s1",
    }


async def test_save_graph_default_picks_most_recent_graph_created(env):
    """The default source is the newest dir whose graph.json has a
    'nodes' list — a newer process()-style dir must be skipped, not
    trip the error."""
    mcp, _, session = env
    older = dict(_GRAPH_DEFINITION, output="b1")
    _make_graph_dir(session, "2026-07-01T00-00-00-000-graph", older)
    _make_graph_dir(session, "2026-07-02T00-00-00-000-graph", _GRAPH_DEFINITION)
    _make_graph_dir(
        session, "2026-07-03T00-00-00-000-blur-blur", _process_style_definition()
    )
    payload = await _call_raw(mcp, "save_graph", {"name": "latest_chain"})
    assert payload["status"] == "ok"
    assert payload["source_graph_id"] == "2026-07-02T00-00-00-000-graph"
    saved = json.loads(
        (session.templates_dir / "latest_chain.json").read_text(encoding="utf-8")
    )
    assert saved["output"] == "s1"


async def test_save_graph_refuses_process_style_source(env):
    mcp, _, session = env
    _make_graph_dir(session, "gProc", _process_style_definition())
    payload = await _call_raw(
        mcp, "save_graph", {"name": "t", "graph_id": "gProc"}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "template_source_missing"


async def test_save_graph_no_eligible_graphs(env):
    mcp, _, session = env
    _make_graph_dir(session, "gProc", _process_style_definition())
    _make_graph_dir(session, "gBare", None)  # no graph.json at all
    payload = await _call_raw(mcp, "save_graph", {"name": "t"})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "template_source_missing"


async def test_save_graph_unknown_graph_id(env):
    mcp, *_ = env
    payload = await _call_raw(
        mcp, "save_graph", {"name": "t", "graph_id": "nope"}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "graph_not_found"


@pytest.mark.parametrize(
    "bad_name",
    ["sub/x", "..\\x", "..", ".", "", ".hidden", ".json"],
)
async def test_save_graph_name_validation(env, bad_name):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    payload = await _call_raw(
        mcp, "save_graph", {"name": bad_name, "graph_id": "gA"}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "invalid_template_name"


async def test_save_graph_overwrite_flagged_and_json_suffix_normalized(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    first = await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    assert first["overwritten"] is False
    # "fog.json" names the SAME template, not fog.json.json.
    second = await _call_raw(
        mcp, "save_graph", {"name": "fog.json", "graph_id": "gA"}
    )
    assert second["status"] == "ok"
    assert second["name"] == "fog"
    assert second["overwritten"] is True
    assert sorted(p.name for p in session.templates_dir.iterdir()) == ["fog.json"]


# ---------------------------------------------------------------------------
# load_graph
# ---------------------------------------------------------------------------


async def test_load_graph_roundtrip_without_overrides(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    payload = await _call_raw(mcp, "load_graph", {"name": "fog"})
    assert payload["status"] == "ok"
    assert payload["definition"] == {
        "inputs": {"src": "frog.wav"},
        "nodes": _GRAPH_NODES,
        "output": "s1",
    }
    assert "graph()" in payload["hint"]


async def test_load_graph_overrides_deep_merge(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    payload = await _call_raw(mcp, "load_graph", {"name": "fog", "overrides": {
        "inputs": {"src": "whale.wav"},
        "nodes": {"b1": {"params": {"blurring": 80}}},
        "output": "b1",
    }})
    assert payload["status"] == "ok"
    d = payload["definition"]
    assert d["inputs"] == {"src": "whale.wav"}
    assert d["output"] == "b1"
    b1 = next(n for n in d["nodes"] if n["id"] == "b1")
    s1 = next(n for n in d["nodes"] if n["id"] == "s1")
    # b1's params key replaced; its other spec keys intact.
    assert b1["params"] == {"blurring": 80}
    assert b1["in"] == "src"
    assert b1["op"] == "blur blur"
    # Untouched node fully as saved.
    assert s1 == _GRAPH_NODES[1]
    # The template on disk is NOT mutated by an overridden load.
    saved = json.loads((session.templates_dir / "fog.json").read_text())
    assert saved["nodes"] == _GRAPH_NODES


async def test_load_graph_params_merge_is_per_key(env):
    """Overriding one params key keeps the node's other params."""
    mcp, _, session = env
    definition = dict(_GRAPH_DEFINITION)
    definition["nodes"] = [{
        "id": "m1", "op": "modify brassage", "in": "src",
        "params": {"velocity": 0.5, "density": 2.0},
    }]
    _make_graph_dir(session, "gA", definition)
    await _call_raw(mcp, "save_graph", {"name": "grain", "graph_id": "gA"})
    payload = await _call_raw(mcp, "load_graph", {"name": "grain", "overrides": {
        "nodes": {"m1": {"params": {"velocity": 2.0}}},
    }})
    assert payload["definition"]["nodes"][0]["params"] == {
        "velocity": 2.0, "density": 2.0,
    }


async def test_load_graph_unknown_node_override(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    payload = await _call_raw(mcp, "load_graph", {"name": "fog", "overrides": {
        "nodes": {"zz": {"params": {"blurring": 80}}},
    }})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "unknown_override_node"
    assert "b1" in payload["errors"][0]["message"]


async def test_load_graph_invalid_override_keys(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    payload = await _call_raw(mcp, "load_graph", {"name": "fog", "overrides": {
        "bogus": 1,
    }})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "invalid_overrides"


async def test_load_graph_missing_template_lists_available(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    payload = await _call_raw(mcp, "load_graph", {"name": "nope"})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "template_not_found"
    assert "fog" in payload["errors"][0]["fix"]


# ---------------------------------------------------------------------------
# list_graphs
# ---------------------------------------------------------------------------


async def test_list_graphs_templates_and_graphs(env):
    mcp, _, session = env
    _make_graph_dir(
        session, "gA", _GRAPH_DEFINITION,
        node_index={"n1": "n1_pvoc-anal.ana", "n2": "n2_blur-blur.ana"},
    )
    await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    session.tags_path.write_text(
        json.dumps({"graphs/gA/n2_blur-blur.ana": ["keeper"]})
    )

    payload = await _call_raw(mcp, "list_graphs", {})
    assert payload["status"] == "ok"
    assert payload["templates"] == [{
        "name": "fog",
        "node_count": 2,
        "ops": ["blur blur", "stretch time"],
    }]
    assert payload["graphs"] == [{
        "id": "gA",
        "primary_output": "n2_blur-blur.ana",  # highest-numbered node
        "tags": ["keeper"],
    }]


async def test_list_graphs_tag_filter(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", None, node_index={"n1": "a.wav"})
    _make_graph_dir(session, "gB", None, node_index={"n1": "b.wav"})
    session.tags_path.write_text(json.dumps({"graphs/gB/b.wav": ["keeper"]}))
    payload = await _call_raw(mcp, "list_graphs", {"tag": "keeper"})
    assert [g["id"] for g in payload["graphs"]] == ["gB"]


async def test_list_graphs_exclude_templates(env):
    mcp, _, session = env
    _make_graph_dir(session, "gA", _GRAPH_DEFINITION)
    await _call_raw(mcp, "save_graph", {"name": "fog", "graph_id": "gA"})
    payload = await _call_raw(mcp, "list_graphs", {"include_templates": False})
    assert payload["templates"] == []
    assert [g["id"] for g in payload["graphs"]] == ["gA"]


async def test_list_graphs_skips_unreadable_template_with_warning(env):
    mcp, _, session = env
    (session.templates_dir / "broken.json").write_text("{not json")
    payload = await _call_raw(mcp, "list_graphs", {})
    assert payload["templates"] == []
    assert any("broken" in w for w in payload["warnings"])


# ---------------------------------------------------------------------------
# MCP prompts smoke test
# ---------------------------------------------------------------------------


async def test_prompts_register_and_render():
    mcp = FastMCP("test-cdp-prompts")
    prompts.register(mcp)
    names = {p.name for p in await mcp.list_prompts()}
    assert {"explore_material", "build_texture", "review_provenance"} <= names

    result = await mcp.get_prompt(
        "explore_material", {"input_file": "frog.wav"}
    )
    text = result.messages[0].content.text
    # Workflow-shaped: references real tool names and the argument.
    for expected in ("set_session", "analyze", "batch", "cluster", "frog.wav"):
        assert expected in text

    result = await mcp.get_prompt("build_texture", {"source": "frog.wav"})
    text = result.messages[0].content.text
    for expected in ("graph(", "dry_run", "compare", "save_graph"):
        assert expected in text

    result = await mcp.get_prompt("review_provenance", {})
    text = result.messages[0].content.text
    for expected in ("why(", "progression", "latest"):
        assert expected in text
