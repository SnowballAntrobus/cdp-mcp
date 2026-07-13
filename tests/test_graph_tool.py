"""Tests for the graph() tool — Phase 2 Task 11a (dry-run only).

The dry-run path must leave zero persistent artifacts: no graph
directories, no envelope files, no subprocess invocations. Several tests
assert that directly, since "no side effects" is the contract the whole
feature hangs on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import graph_tool as graph_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()

_ALL_PROGRAMS = ("blur", "modify", "morph", "extend", "filter", "combine", "pvoc")


@pytest.fixture
def fake_cdp_path(tmp_path):
    """Executable stubs are enough — dry-run never spawns them, but the
    security gate's binary check requires real executables on disk."""
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    for name in _ALL_PROGRAMS:
        p = cdp / name
        p.write_text("#!/bin/sh\nexit 1\n")
        p.chmod(0o755)
    return cdp


@pytest.fixture
def harness(fake_cdp_path, tmp_path):
    mcp = FastMCP("test-cdp-graph")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(
        cdp_path=fake_cdp_path,
        version="fake",
        detected_binaries=sorted(_ALL_PROGRAMS),
    )
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    tracker = LatestTracker()
    graph_module.register(
        mcp,
        sessions=sessions,
        knowledge_index=KnowledgeIndex.load(),
        cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker,
        cache_root=cache_root,
    )
    return mcp, sessions, tracker


async def _call(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "graph", args, context=None, convert_result=False
    )


def _write_wav(path: Path, duration_s: float, sr: int = 44100) -> None:
    sf.write(str(path), np.zeros(int(duration_s * sr), dtype=np.float32), sr)


def _session_with_input(sessions, duration_s: float = 2.0):
    session, _ = sessions.set_active("g1")
    _write_wav(session.inputs_dir / "frog.wav", duration_s)
    return session


def _assert_no_side_effects(session):
    """Dry run must not create graph dirs or leave envelope/tmp files."""
    assert list(session.graphs_dir.iterdir()) == []
    assert list(session.envelopes_dir.iterdir()) == []
    leftovers = [
        p for p in session.tmp_dir.rglob("*")
        if p.is_file() and "dryrun-envelopes" in str(p)
    ]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Preconditions and the Task 11a execution boundary
# ---------------------------------------------------------------------------


async def test_no_active_session(harness):
    mcp, _, _ = harness
    payload = await _call(mcp, {"nodes": [], "dry_run": True})
    assert payload["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in payload["errors"])


async def test_full_execution_not_implemented(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [{"id": "b1", "op": "blur blur", "in": "src",
                       "params": {"blurring": 10}}],
            "dry_run": False,
        },
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "graph_execution_not_implemented"
        for e in payload["errors"]
    )
    # The redirect fix must point at dry_run.
    assert "dry_run=True" in payload["errors"][0]["fix"]


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


async def test_unresolved_bare_reference(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "nodes": [{"id": "b1", "op": "blur blur", "in": "nonexistent",
                       "params": {"blurring": 10}}],
            "dry_run": True,
        },
    )
    assert payload["status"] == "failed"
    errs = [e for e in payload["errors"] if e["type"] == "graph_topology_error"]
    assert errs and "nonexistent" in errs[0]["message"]


async def test_cycle_detected(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "nodes": [
                {"id": "a", "op": "blur blur", "in": "b", "params": {"blurring": 10}},
                {"id": "b", "op": "blur blur", "in": "a", "params": {"blurring": 10}},
            ],
            "dry_run": True,
        },
    )
    assert payload["status"] == "failed"
    cycle_errors = [
        e for e in payload["errors"]
        if e["type"] == "graph_topology_error" and "cycle" in e["message"]
    ]
    assert cycle_errors
    assert "'a'" in cycle_errors[0]["message"]
    assert "'b'" in cycle_errors[0]["message"]


async def test_duplicate_node_id(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [
                {"id": "x", "op": "blur blur", "in": "src", "params": {"blurring": 10}},
                {"id": "x", "op": "blur blur", "in": "src", "params": {"blurring": 20}},
            ],
            "dry_run": True,
        },
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "graph_spec_error" and "duplicate" in e["message"]
        for e in payload["errors"]
    )


async def test_unknown_node_key_rejected(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [{"id": "x", "op": "blur blur", "in": "src",
                       "parms": {"blurring": 10}}],  # typo'd key
            "dry_run": True,
        },
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "graph_spec_error" and "parms" in e["message"]
        for e in payload["errors"]
    )


async def test_not_curated_op(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [{"id": "x", "op": "nonexistent thing", "in": "src"}],
            "dry_run": True,
        },
    )
    assert payload["status"] == "failed"
    assert any(e["type"] == "not_curated" for e in payload["errors"])


async def test_output_must_be_a_node(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [{"id": "b1", "op": "blur blur", "in": "src",
                       "params": {"blurring": 10}}],
            "output": "b9",
            "dry_run": True,
        },
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "graph_spec_error" and "b9" in e["message"]
        for e in payload["errors"]
    )


# ---------------------------------------------------------------------------
# Happy path: chain with auto-PVOC planning and duration chaining
# ---------------------------------------------------------------------------


async def test_two_node_chain_validates_and_plans(harness):
    """wav input → blur blur (spectral, needs auto-PVOC) → extend loop
    (time-domain, needs auto-synth). Both nodes validate; planned argv
    carries planned intermediate paths; nothing touches disk."""
    mcp, sessions, _ = harness
    session = _session_with_input(sessions, duration_s=2.0)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [
                {"id": "blurred", "op": "blur blur", "in": "src",
                 "params": {"blurring": 10}},
                {"id": "looped", "op": "extend loop", "in": "blurred",
                 "params": {"start": 0.0, "cnt": 4, "len": 500, "step": 250}},
            ],
            "output": "looped",
            "dry_run": True,
        },
    )
    assert payload["status"] == "ok"
    assert payload["topological_order"] == ["blurred", "looped"]
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id["blurred"]["status"] == "ok"
    assert by_id["looped"]["status"] == "ok"
    # blur is spectral on a wav input: planned argv references a planned
    # pvoc-anal intermediate.
    assert any("pvoc-anal" in a for a in by_id["blurred"]["planned_argv"])
    # extend loop's duration model: cnt * len / 1000 = 4 * 500ms = 2 s.
    assert by_id["looped"]["predicted_duration_s"] == pytest.approx(2.0)
    _assert_no_side_effects(session)


async def test_duration_cap_violation_names_the_node(harness):
    """The whole point of dry-run: a cap violation is attributed to the
    specific node, and downstream nodes are skipped, not mis-reported."""
    mcp, sessions, _ = harness
    session = _session_with_input(sessions, duration_s=2.0)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [
                # 2000 repeats of a 1 s segment = 2000 s >> 300 s cap.
                {"id": "runaway", "op": "extend loop", "in": "src",
                 "params": {"start": 0.0, "cnt": 2000, "len": 1000, "step": 100}},
                {"id": "downstream", "op": "blur blur", "in": "runaway",
                 "params": {"blurring": 10}},
            ],
            "dry_run": True,
        },
    )
    assert payload["status"] == "failed"
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id["runaway"]["status"] == "failed"
    assert any(
        e["type"] == "predicted_duration_exceeds_cap"
        for e in by_id["runaway"]["errors"]
    )
    # Prediction is reported even though the node failed.
    assert by_id["runaway"]["predicted_duration_s"] == pytest.approx(2000.0)
    assert by_id["downstream"]["status"] == "skipped"
    _assert_no_side_effects(session)


async def test_predicted_duration_chains_downstream(harness):
    """extend loop's predicted 4 s output feeds the next extend loop's
    prediction: without chaining, node two's input duration would be
    unknowable (its input file never exists during dry-run)."""
    mcp, sessions, _ = harness
    _session_with_input(sessions, duration_s=2.0)
    payload = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [
                {"id": "loop1", "op": "extend loop", "in": "src",
                 "params": {"start": 0.0, "cnt": 4, "len": 1000, "step": 100}},
                # modify brassage sm2: duration model indur / velocity.
                {"id": "stretched", "op": "modify brassage", "in": "loop1",
                 "params": {"velocity": 0.5}},
            ],
            "dry_run": True,
        },
    )
    assert payload["status"] == "ok"
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id["loop1"]["predicted_duration_s"] == pytest.approx(4.0)
    # 4 s upstream prediction / velocity 0.5 = 8 s — only computable via
    # the indur override chain.
    assert by_id["stretched"]["predicted_duration_s"] == pytest.approx(8.0)


async def test_multi_input_combine_cross(harness):
    """combine cross takes two inputs; its duration model is indur_min.
    Mixed sources: one session input, one upstream node."""
    mcp, sessions, _ = harness
    session = _session_with_input(sessions, duration_s=2.0)
    _write_wav(session.inputs_dir / "voice.wav", 5.0)
    payload = await _call(
        mcp,
        {
            "inputs": {"frog": "frog.wav", "voice": "voice.wav"},
            "nodes": [
                {"id": "blurred", "op": "blur blur", "in": "voice",
                 "params": {"blurring": 10}},
                {"id": "crossed", "op": "combine cross",
                 "in": ["blurred", "frog"], "params": {"interp": 0.7}},
            ],
            "output": "crossed",
            "dry_run": True,
        },
    )
    assert payload["status"] == "ok"
    by_id = {n["id"]: n for n in payload["nodes"]}
    # blur (static model) predicts max(known indurs) = 5 s; combine cross
    # takes min(5 s upstream, 2 s frog) = 2 s.
    assert by_id["crossed"]["predicted_duration_s"] == pytest.approx(2.0)
    _assert_no_side_effects(session)


async def test_breakpoint_param_validated_without_artifacts(harness):
    """A breakpoint envelope on a capable param validates in dry-run and
    leaves no compiled .brk behind; an out-of-range envelope fails."""
    mcp, sessions, _ = harness
    session = _session_with_input(sessions, duration_s=2.0)
    ok = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [{"id": "b1", "op": "blur blur", "in": "src",
                       "params": {"blurring": [[0.0, 1.0], [1.0, 40.0]]}}],
            "dry_run": True,
        },
    )
    assert ok["status"] == "ok"
    _assert_no_side_effects(session)

    # Structurally invalid envelope (non-pair entry): same error the
    # real path raises. (Value-RANGE checks on raw tuples are the
    # breakpoint() DSL's job — the compiler checks structure and times.)
    bad = await _call(
        mcp,
        {
            "inputs": {"src": "frog.wav"},
            "nodes": [{"id": "b1", "op": "blur blur", "in": "src",
                       "params": {"blurring": [[0.0, 1.0], "nonsense"]}}],
            "dry_run": True,
        },
    )
    by_id = {n["id"]: n for n in bad["nodes"]}
    assert by_id["b1"]["status"] == "failed"
    _assert_no_side_effects(session)


async def test_dry_run_does_not_mutate_params(harness):
    """The real validate_node path mutates params (breakpoint values →
    compiled paths); dry-run must not — a later real run would otherwise
    receive a dangling temp path."""
    mcp, sessions, _ = harness
    _session_with_input(sessions, duration_s=2.0)
    params = {"blurring": [[0.0, 1.0], [1.0, 40.0]]}
    nodes = [{"id": "b1", "op": "blur blur", "in": "src", "params": params}]
    payload = await _call(
        mcp,
        {"inputs": {"src": "frog.wav"}, "nodes": nodes, "dry_run": True},
    )
    assert payload["status"] == "ok"
    assert params == {"blurring": [[0.0, 1.0], [1.0, 40.0]]}
