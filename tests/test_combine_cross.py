"""Tests for the ``combine cross`` curated entry (Phase 2 Task 9).

The point of this entry is to prove a *second* multi-input spectral op ships
usefully through the **existing** node-validation path — each input
independently auto-PVOC'd, no length-alignment step — relying on CDP's native
length handling (output = shorter input, confirmed order-independent by the
Task 9 probe). The differing-length test asserts exactly that: success plus the
absence of any alignment artifact in the graph.

Real-CDP tests gate on ``real_cdp_path`` AND a local ``combine`` presence check
(``combine`` is not in conftest's shared required-binaries list).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.breakpoint import breakpoint_impl
from cdp_mcp.tools.process import process_impl

# ---------------------------------------------------------------------------
# Unit: curation loads + validates
# ---------------------------------------------------------------------------


def test_combine_cross_entry_loads_and_validates():
    idx = KnowledgeIndex.load()
    entry = idx.get("combine", "cross")
    assert entry is not None, "combine cross entry missing from the index"
    assert entry.input_arity == 2
    assert entry.domain == "spectral"
    # The whole proof: this entry needs no alignment, so it declares no strategy.
    assert entry.default_length_strategy is None
    assert entry.submode is None
    interp = entry.parameters["interp"]
    assert interp.flag == "-i" and interp.flag_kind == "attached_value"
    assert interp.breakpoint_capable is True
    assert interp.breakpoint_duration_source == "input1"
    assert (interp.min, interp.max, interp.default) == (0.0, 1.0, 0.5)


# ---------------------------------------------------------------------------
# Real-CDP end-to-end
# ---------------------------------------------------------------------------


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


def _make_wav(path: Path, dur_s: float, seed: int) -> None:
    sr = 44100
    n = int(sr * dur_s)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n).astype(np.float32) * 0.3
    env = np.exp(-3.0 * np.linspace(0.0, 1.0, n)).astype(np.float32)
    sf.write(path, noise * env, sr, subtype="FLOAT")


@pytest.fixture
def cross_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    if not (real_cdp_path / "combine").is_file():
        pytest.skip("combine binary not present in $CDP_PATH.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    latest_tracker = LatestTracker()
    knowledge = KnowledgeIndex.load()
    session, _ = sessions.set_active("combine_cross_v1.0")
    return SimpleNamespace(
        sessions=sessions,
        session=session,
        latest_tracker=latest_tracker,
        knowledge=knowledge,
        cdp_config=cdp_config,
        cache_root=cache_root,
    )


def _deps(env):
    return dict(
        sessions=env.sessions,
        knowledge_index=env.knowledge,
        cdp_config_provider=lambda: env.cdp_config,
        latest_tracker=env.latest_tracker,
        cache_root=env.cache_root,
    )


@pytest.mark.timeout(60)
async def test_combine_cross_constant_interp(cross_env):
    """Two wavs → auto-PVOC each → combine cross runs → .ana output."""
    env = cross_env
    _make_wav(env.session.inputs_dir / "a.wav", 2.0, seed=42)
    _make_wav(env.session.inputs_dir / "b.wav", 2.0, seed=43)

    r = await process_impl(
        _FakeCtx(), program="combine", mode="cross",
        input=["a.wav", "b.wav"], params={"interp": 0.5}, **_deps(env),
    )
    assert r["status"] == "ok", r
    assert r["output"].endswith(".ana")

    graph_dir = env.session.graphs_dir / r["context"]["active_graph"]
    node_index = json.loads((graph_dir / "node_index.json").read_text())
    # n1 = pvoc(a), n2 = pvoc(b), n3 = combine cross. Two PVOC nodes + main.
    assert set(node_index.keys()) == {"n1", "n2", "n3"}
    assert "pvoc" in node_index["n1"] and "pvoc" in node_index["n2"]
    assert "combine" in node_index["n3"]


@pytest.mark.timeout(60)
@pytest.mark.parametrize("order", [("a.wav", "b.wav"), ("b.wav", "a.wav")])
async def test_combine_cross_differing_lengths_no_alignment(cross_env, order):
    """Differing-length inputs (2s, 3s) succeed with NO alignment step —
    the proof that the multi-input path needs no Task 8 alignment layer."""
    env = cross_env
    _make_wav(env.session.inputs_dir / "a.wav", 2.0, seed=42)  # shorter
    _make_wav(env.session.inputs_dir / "b.wav", 3.0, seed=43)  # longer

    r = await process_impl(
        _FakeCtx(), program="combine", mode="cross",
        input=list(order), params={"interp": 0.5}, **_deps(env),
    )
    assert r["status"] == "ok", r

    graph_dir = env.session.graphs_dir / r["context"]["active_graph"]
    node_index = json.loads((graph_dir / "node_index.json").read_text())
    # Exactly the existing path: two PVOC nodes + main. No alignment nodes.
    assert set(node_index.keys()) == {"n1", "n2", "n3"}
    # No aligned-input artifact written anywhere in the graph dir.
    assert not list(graph_dir.rglob("*aligned*")), (
        "found an alignment artifact — the existing path should run unmodified"
    )


@pytest.mark.timeout(60)
async def test_combine_cross_breakpoint_on_interp(cross_env):
    """interp as a linear 0→1 breakpoint compiles against input1's duration
    via the existing resolver and runs — Task 6 DSL on a multi-input entry."""
    env = cross_env
    _make_wav(env.session.inputs_dir / "a.wav", 2.0, seed=42)
    _make_wav(env.session.inputs_dir / "b.wav", 3.0, seed=43)

    bp = await breakpoint_impl(
        "linear", "combine", "cross", "interp",
        start=0.0, end=1.0, knowledge_index=env.knowledge,
    )
    assert bp["status"] == "ok", bp

    r = await process_impl(
        _FakeCtx(), program="combine", mode="cross",
        input=["a.wav", "b.wav"], params={"interp": bp["breakpoints"]},
        **_deps(env),
    )
    assert r["status"] == "ok", r

    graph_dir = env.session.graphs_dir / r["context"]["active_graph"]
    lineage = json.loads((graph_dir / "lineage.json").read_text())
    main = lineage["nodes"]["n3"]
    cb = main["compiled_breakpoints"]["interp"]
    assert cb["sha256"] != ""
    # Source duration resolves to input1 (~2.0s), via the auto-PVOC node.
    assert cb["source_duration_s"] == pytest.approx(2.0, abs=0.1)
