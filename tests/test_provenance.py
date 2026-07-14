"""Integration tests for the why() provenance tool.

Graph directories are hand-built on disk (node_index.json + lineage.json
JSONs mimicking the exact shape GraphDir.add_node writes — field names
copied from schema.NodeLineage / schema.InputRecord, datetimes as
isoformat strings) so the walk logic is exercised without running CDP.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import provenance

# ---------------------------------------------------------------------------
# Fixtures + hand-built lineage helpers
# ---------------------------------------------------------------------------

_ISO = "2026-07-13T00:00:00+00:00"
_FROG_BYTES = b"RIFF-frog-stub"


def _fake_cdp() -> CDPConfig:
    return CDPConfig(
        cdp_path=Path("/tmp/fake"),
        version="8.0.1-fake",
        detected_binaries=["blur"],
    )


@pytest.fixture
def mcp_with_why(tmp_path):
    mcp = FastMCP("test-cdp-provenance")
    sessions = SessionManager(tmp_path, lambda: _fake_cdp())
    tracker = LatestTracker()
    provenance.register(mcp, sessions=sessions, latest_tracker=tracker)
    return mcp, sessions, tracker


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


def _input_record(path, sha256: str, source_node: str | None = None) -> dict:
    """Field names mirror schema.InputRecord exactly."""
    return {"path": str(path), "sha256": sha256, "source_node": source_node}


def _lineage_node(
    argv: list,
    inputs: list[dict],
    output_path,
    output_sha256: str,
    params: dict,
    *,
    cache_hit: bool = False,
) -> dict:
    """Field names mirror schema.NodeLineage exactly; datetimes as
    isoformat strings, matching what model_dump(mode="json") writes."""
    return {
        "argv": [str(a) for a in argv],
        "inputs": inputs,
        "output_path": str(output_path),
        "output_sha256": output_sha256,
        "params": params,
        "cdp_version": "8.0.1-fake",
        "started_at": _ISO,
        "finished_at": _ISO,
        "duration_ms": 42,
        "exit_code": 0,
        "source_wav_duration_s": None,
        "compiled_breakpoints": {},
        "cache_hit": cache_hit,
    }


def _write_graph(
    graphs_root: Path,
    graph_id: str,
    node_index: dict,
    lineage_nodes: dict | None = None,
) -> Path:
    """Mimic GraphDir's on-disk layout: node_index.json is a flat
    node_id -> filename map; lineage.json is {"nodes": {...}}."""
    root = graphs_root / graph_id
    root.mkdir(parents=True)
    (root / "node_index.json").write_text(
        json.dumps(node_index, indent=2, sort_keys=True)
    )
    if lineage_nodes is not None:
        (root / "lineage.json").write_text(
            json.dumps({"nodes": lineage_nodes}, indent=2, sort_keys=True)
        )
    return root


def _build_two_node_session(sessions: SessionManager):
    """inputs/frog.wav -> gA:n1 (auto-pvoc) -> gA:n2 (blur, main op)."""
    session, _ = sessions.set_active("prov")
    frog = session.inputs_dir / "frog.wav"
    frog.write_bytes(_FROG_BYTES)
    frog_sha = hashlib.sha256(_FROG_BYTES).hexdigest()

    graphs = session.graphs_dir
    g = graphs / "gA"
    n1_out = "n1_pvoc-anal.ana"
    n2_out = "n2_blur-blur.ana"
    _write_graph(
        graphs,
        "gA",
        {"n1": n1_out, "n2": n2_out},
        {
            "n1": _lineage_node(
                argv=["/fake/cdp/pvoc", "anal", "1", frog, g / n1_out],
                inputs=[_input_record(frog, frog_sha)],
                output_path=g / n1_out,
                output_sha256="a" * 64,
                params={},
            ),
            "n2": _lineage_node(
                argv=["/fake/cdp/blur", "blur", g / n1_out, g / n2_out, "10"],
                inputs=[_input_record(g / n1_out, "b" * 64, source_node="n1")],
                output_path=g / n2_out,
                output_sha256="c" * 64,
                params={"blurring": 10},
            ),
        },
    )
    (g / n1_out).write_bytes(b"ana-stub-1")
    (g / n2_out).write_bytes(b"ana-stub-2")
    return session, frog_sha


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


async def test_why_registered(mcp_with_why):
    mcp, _, _ = mcp_with_why
    tools = await mcp.list_tools()
    assert "why" in {t.name for t in tools}


# ---------------------------------------------------------------------------
# Failure envelopes
# ---------------------------------------------------------------------------


async def test_no_active_session_is_structured_error(mcp_with_why):
    mcp, _, _ = mcp_with_why
    payload = await _call_raw(mcp, "why", {"target": "latest"})
    assert payload["status"] == "failed"
    assert payload["chain"] == []
    assert payload["errors"][0]["type"] == "no_active_session"


async def test_unresolvable_reference_is_structured_error(mcp_with_why):
    mcp, sessions, _ = mcp_with_why
    sessions.set_active("prov")
    payload = await _call_raw(mcp, "why", {"target": "nope.wav"})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "reference_resolution"
    assert "nope.wav" in payload["errors"][0]["message"]


async def test_missing_lineage_json_is_structured_error(mcp_with_why):
    """A graph dir with node_index.json but no lineage.json (hand-built,
    or a crash before GraphDir init finished) fails cleanly."""
    mcp, sessions, _ = mcp_with_why
    session, _ = sessions.set_active("prov")
    root = _write_graph(session.graphs_dir, "gX", {"n1": "n1_out.wav"})
    (root / "n1_out.wav").write_bytes(b"stub")
    payload = await _call_raw(mcp, "why", {"target": "gX:n1"})
    assert payload["status"] == "failed"
    assert payload["chain"] == []
    assert payload["errors"][0]["type"] == "lineage_missing"
    assert "gX" in payload["errors"][0]["message"]


# ---------------------------------------------------------------------------
# Chain walks
# ---------------------------------------------------------------------------


async def test_two_node_chain_walks_to_source(mcp_with_why):
    """auto-pvoc n1 -> main op n2 within one graph: why(gA:n2) walks
    n2 -> n1 -> the session input, leaf-last."""
    mcp, sessions, _ = mcp_with_why
    session, frog_sha = _build_two_node_session(sessions)

    payload = await _call_raw(mcp, "why", {"target": "gA:n2"})
    assert payload["status"] == "ok"
    assert payload["target"] == "gA:n2"
    expected_path = (session.graphs_dir / "gA" / "n2_blur-blur.ana").resolve()
    assert payload["resolved_path"] == str(expected_path)

    assert [e["kind"] for e in payload["chain"]] == ["node", "node", "source"]
    main, pvoc, source = payload["chain"]

    assert main["graph_id"] == "gA"
    assert main["node_id"] == "n2"
    assert main["program"] == "blur blur"
    assert main["argv"][0] == "/fake/cdp/blur"
    assert main["params"] == {"blurring": 10}
    assert main["output_sha256"] == "c" * 12
    assert main["cache_hit"] is False
    assert main["started_at"] == _ISO
    assert main["duration_ms"] == 42

    assert pvoc["graph_id"] == "gA"
    assert pvoc["node_id"] == "n1"
    assert pvoc["program"] == "pvoc anal"
    assert pvoc["output_sha256"] == "a" * 12

    assert source["path"] == str(session.inputs_dir / "frog.wav")
    assert source["sha256"] == frog_sha[:12]

    assert payload["warnings"] == []
    assert payload["errors"] == []


async def test_cross_graph_reference_walks_across(mcp_with_why):
    """gB:n1's input points at gA's n2 output (source_node null) — the
    walk locates the node in the other graph and keeps going."""
    mcp, sessions, _ = mcp_with_why
    session, frog_sha = _build_two_node_session(sessions)
    graphs = session.graphs_dir
    upstream_out = graphs / "gA" / "n2_blur-blur.ana"

    g_b = graphs / "gB"
    out = "n1_stretch.wav"
    _write_graph(
        graphs,
        "gB",
        {"n1": out},
        {
            "n1": _lineage_node(
                argv=["/fake/cdp/stretch", "time", "1", upstream_out, g_b / out, "2"],
                inputs=[_input_record(upstream_out, "d" * 64)],
                output_path=g_b / out,
                output_sha256="e" * 64,
                params={"multiplier": 2},
            ),
        },
    )
    (g_b / out).write_bytes(b"wav-stub")

    payload = await _call_raw(mcp, "why", {"target": "gB:n1"})
    assert payload["status"] == "ok"
    hops = [
        (e["kind"], e.get("graph_id"), e.get("node_id")) for e in payload["chain"]
    ]
    assert hops == [
        ("node", "gB", "n1"),
        ("node", "gA", "n2"),
        ("node", "gA", "n1"),
        ("source", None, None),
    ]
    assert payload["chain"][0]["program"] == "stretch time"
    assert payload["chain"][-1]["sha256"] == frog_sha[:12]
    assert payload["warnings"] == []


async def test_latest_alias_resolves(mcp_with_why):
    mcp, sessions, tracker = mcp_with_why
    _build_two_node_session(sessions)
    tracker.update("gA", "n2")
    payload = await _call_raw(mcp, "why", {"target": "latest"})
    assert payload["status"] == "ok"
    assert payload["chain"][0]["graph_id"] == "gA"
    assert payload["chain"][0]["node_id"] == "n2"
    assert len(payload["chain"]) == 3


async def test_session_input_target_is_terminal_source(mcp_with_why):
    """why(<input filename>) — the resolved file isn't in any graph dir,
    so the chain is a single source entry hashed from disk."""
    mcp, sessions, _ = mcp_with_why
    session, _ = sessions.set_active("prov")
    data = b"RIFF-direct"
    (session.inputs_dir / "direct.wav").write_bytes(data)
    payload = await _call_raw(mcp, "why", {"target": "direct.wav"})
    assert payload["status"] == "ok"
    assert payload["chain"] == [
        {
            "kind": "source",
            "path": str((session.inputs_dir / "direct.wav").resolve()),
            "sha256": hashlib.sha256(data).hexdigest()[:12],
        }
    ]


# ---------------------------------------------------------------------------
# Guards: cycles + depth cap
# ---------------------------------------------------------------------------


async def test_cycle_guard_terminates_with_warning(mcp_with_why):
    """Two lineage entries pointing at each other must terminate with a
    warning, not hang (the 30 s suite timeout is the backstop)."""
    mcp, sessions, _ = mcp_with_why
    session, _ = sessions.set_active("prov")
    graphs = session.graphs_dir
    g_c = graphs / "gC"
    _write_graph(
        graphs,
        "gC",
        {"n1": "n1.wav", "n2": "n2.wav"},
        {
            "n1": _lineage_node(
                argv=["/fake/cdp/opA", "modeA", g_c / "n2.wav", g_c / "n1.wav"],
                inputs=[_input_record(g_c / "n2.wav", "f" * 64, source_node="n2")],
                output_path=g_c / "n1.wav",
                output_sha256="1" * 64,
                params={},
            ),
            "n2": _lineage_node(
                argv=["/fake/cdp/opB", "modeB", g_c / "n1.wav", g_c / "n2.wav"],
                inputs=[_input_record(g_c / "n1.wav", "e" * 64, source_node="n1")],
                output_path=g_c / "n2.wav",
                output_sha256="2" * 64,
                params={},
            ),
        },
    )
    (g_c / "n2.wav").write_bytes(b"stub")

    payload = await _call_raw(mcp, "why", {"target": "gC:n2"})
    assert payload["status"] == "ok"
    node_ids = [e["node_id"] for e in payload["chain"] if e["kind"] == "node"]
    assert node_ids == ["n2", "n1"]
    assert any("cycle" in w for w in payload["warnings"])


async def test_depth_cap_truncates_with_warning(mcp_with_why):
    """A 30-node chain stops at 25 node entries plus a truncation warning."""
    mcp, sessions, _ = mcp_with_why
    session, _ = sessions.set_active("prov")
    graphs = session.graphs_dir
    g_d = graphs / "gD"

    index = {"n1": "n1.wav"}
    nodes = {
        "n1": _lineage_node(
            argv=["/fake/cdp/op", "mode", session.inputs_dir / "seed.wav", g_d / "n1.wav"],
            inputs=[_input_record(session.inputs_dir / "seed.wav", "0" * 64)],
            output_path=g_d / "n1.wav",
            output_sha256="9" * 64,
            params={},
        )
    }
    for i in range(2, 31):
        index[f"n{i}"] = f"n{i}.wav"
        nodes[f"n{i}"] = _lineage_node(
            argv=["/fake/cdp/op", "mode", g_d / f"n{i - 1}.wav", g_d / f"n{i}.wav"],
            inputs=[
                _input_record(g_d / f"n{i - 1}.wav", "9" * 64, source_node=f"n{i - 1}")
            ],
            output_path=g_d / f"n{i}.wav",
            output_sha256="9" * 64,
            params={},
        )
    _write_graph(graphs, "gD", index, nodes)
    (g_d / "n30.wav").write_bytes(b"stub")

    payload = await _call_raw(mcp, "why", {"target": "gD:n30"})
    assert payload["status"] == "ok"
    node_entries = [e for e in payload["chain"] if e["kind"] == "node"]
    assert len(node_entries) == 25
    assert node_entries[0]["node_id"] == "n30"
    assert node_entries[-1]["node_id"] == "n6"
    assert any("truncated" in w for w in payload["warnings"])
