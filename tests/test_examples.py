"""Tests for the packaged examples library (``cdp://examples/*``).

Three tiers, per testing-principles §10 ("integration code extending a
pinned table must EXECUTE the table"):

1. Loader/summary integrity — the packaged JSONs load, carry the
   required fields, and ``list_examples`` summarizes them.
2. The ``read_doc`` namespace dispatch — ``cdp://examples/...`` uris
   resolve through the docs tool WITHOUT a CDP manual installed, and
   unknown names return a structured ``example_not_found``.
3. Every shipped definition DRY-RUNS CLEAN through the real ``graph()``
   validation path against a synthesized session input — params
   validate against the curated entries, references resolve, and every
   node gets a duration prediction. A drifted example (renamed param,
   stale op, broken chain arithmetic) fails here, not in a user session.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import docs as docs_module
from cdp_mcp.tools import examples as examples_module
from cdp_mcp.tools import graph_tool as graph_module

_EXPECTED_EXAMPLES = frozenset(
    {
        "spectral_smear_granular",
        "pitched_vibrato_warp",
        "texture_sweep_scramble",
        "oneshot_bounce_stretch",
        "syllabic_grain_stutter",
        "palindrome_chorus",
    }
)


# ---------------------------------------------------------------------------
# 1. Loader + list_examples
# ---------------------------------------------------------------------------


def test_load_examples_ships_the_expected_set():
    examples = examples_module.load_examples()
    assert set(examples) == _EXPECTED_EXAMPLES
    for name, ex in examples.items():
        assert ex["name"] == name
        definition = ex["definition"]
        assert set(definition) == {"inputs", "nodes", "output"}
        assert definition["nodes"], f"{name}: empty node list"
        node_ids = [n["id"] for n in definition["nodes"]]
        assert definition["output"] in node_ids, (
            f"{name}: output {definition['output']!r} is not a node id"
        )
        assert ex["notes"], f"{name}: examples must carry usage notes"
        assert "verified" in ex["source"].lower(), (
            f"{name}: source field must state verification provenance"
        )


async def test_list_examples_summaries():
    mcp = FastMCP("test-examples")
    examples_module.register(mcp)
    payload = await mcp._tool_manager.call_tool(
        "list_examples", {}, context=None, convert_result=False
    )
    assert payload["status"] == "ok"
    assert payload["example_count"] == len(_EXPECTED_EXAMPLES)
    for summary in payload["examples"]:
        assert summary["uri"] == f"cdp://examples/{summary['name']}"
        assert summary["node_count"] == len(summary["ops"]) > 0
        assert summary["title"] and summary["material"]


# ---------------------------------------------------------------------------
# 2. read_doc dispatch (no CDP manual required)
# ---------------------------------------------------------------------------


@pytest.fixture
def docs_mcp(tmp_path):
    """Docs tools registered with NO manual installed — the examples
    namespace must be served anyway."""
    mcp = FastMCP("test-docs-dispatch")
    docs_module.register(
        mcp,
        docs_root_provider=lambda: None,
        index_path=tmp_path / "docs_index.sqlite",
        cdp_config_provider=lambda: None,
    )
    return mcp


async def _read_doc(mcp: FastMCP, uri: str) -> Any:
    return await mcp._tool_manager.call_tool(
        "read_doc", {"uri": uri}, context=None, convert_result=False
    )


async def test_read_doc_serves_examples_without_manual(docs_mcp):
    payload = await _read_doc(docs_mcp, "cdp://examples/palindrome_chorus")
    assert payload["status"] == "ok"
    assert payload["uri"] == "cdp://examples/palindrome_chorus"
    assert payload["definition"]["output"] == "out"
    assert "graph()" in payload["hint"]
    # Sanity: the docs namespace still reports docs_not_available.
    docs_payload = await _read_doc(docs_mcp, "cdp://docs/html/blur")
    assert docs_payload["status"] == "failed"
    assert docs_payload["errors"][0]["type"] == "docs_not_available"


async def test_read_doc_unknown_example_is_structured(docs_mcp):
    payload = await _read_doc(docs_mcp, "cdp://examples/no_such_example")
    assert payload["status"] == "failed"
    (err,) = payload["errors"]
    assert err["type"] == "example_not_found"
    assert "list_examples" in err["fix"]


# ---------------------------------------------------------------------------
# 3. Every shipped definition dry-runs clean through graph()
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_harness(tmp_path):
    """graph() wired like server startup, fake CDP path, one 3 s mono
    input in the active session. Dry-run spawns nothing, so the fake
    binaries are stub files."""
    cdp_dir = (tmp_path / "cdp").resolve()
    cdp_dir.mkdir()
    programs = sorted(
        {
            ex["definition"]["nodes"][i]["op"].split()[0]
            for ex in examples_module.load_examples().values()
            for i in range(len(ex["definition"]["nodes"]))
        }
        | {"pvoc"}
    )
    for name in programs:
        stub = cdp_dir / name
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)
    cdp_cfg = CDPConfig(
        cdp_path=cdp_dir, version="fake", detected_binaries=programs
    )
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    session, _ = sessions.set_active("examples_dryrun_v1")
    sr = 44100
    rng = np.random.default_rng(seed=7)
    audio = (rng.standard_normal(3 * sr) * 0.2).astype(np.float32)
    sf.write(session.inputs_dir / "in.wav", audio, sr, subtype="FLOAT")

    mcp = FastMCP("test-examples-graph")
    graph_module.register(
        mcp,
        sessions=sessions,
        knowledge_index=KnowledgeIndex.load(),
        cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=LatestTracker(),
        cache_root=cache_root,
    )
    return mcp


@pytest.mark.parametrize("name", sorted(_EXPECTED_EXAMPLES))
async def test_example_dry_runs_clean(graph_harness, name):
    example = examples_module.load_examples()[name]
    definition = example["definition"]
    inputs = {key: "in.wav" for key in definition["inputs"]}
    payload = await graph_harness._tool_manager.call_tool(
        "graph",
        {
            "inputs": inputs,
            "nodes": definition["nodes"],
            "output": definition["output"],
            "dry_run": True,
        },
        context=None,
        convert_result=False,
    )
    assert payload["status"] == "ok", (
        f"example {name!r} failed dry-run validation: "
        f"{payload.get('errors')} / "
        f"{[n.get('errors') for n in payload.get('nodes', [])]}"
    )
    for node in payload["nodes"]:
        assert node["status"] == "ok", f"{name}:{node.get('id')}: {node}"
        assert node.get("predicted_duration_s") is not None, (
            f"{name}:{node.get('id')} has no duration prediction — "
            f"chained pre-flight is part of the example contract"
        )
