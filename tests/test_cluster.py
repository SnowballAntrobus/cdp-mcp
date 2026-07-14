"""Integration tests for the cluster() MCP tool.

Three clearly-different groups of tiny synthetic files (low sines,
white noise, click trains) exercise the full pipeline: auto-k via
silhouette scan, medoid membership, determinism under a fixed seed,
'latest_batch' expansion against a hand-built tracker + fake graph
dir, and the structured pre-flight failures.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import cluster as cluster_module

_SR = 22050


def _sine(freq: float, seconds: float = 0.5, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(_SR * seconds)) / _SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _noise(seconds: float = 0.5, amp: float = 0.3, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(int(_SR * seconds))).astype(np.float32)


def _clicks(period_s: float, seconds: float = 0.5, amp: float = 0.9) -> np.ndarray:
    y = np.zeros(int(_SR * seconds), dtype=np.float32)
    y[:: int(_SR * period_s)] = amp
    return y


def _write_three_groups(session) -> dict[str, list[str]]:
    """Nine 0.5 s files in session inputs: 3 low sines, 3 noises, 3 click
    trains. Returns {group: [filenames]}."""
    material = {
        "sine": [_sine(108.0), _sine(110.0), _sine(112.0)],
        "noise": [_noise(seed=i) for i in range(3)],
        "click": [_clicks(p) for p in (0.04, 0.05, 0.06)],
    }
    names: dict[str, list[str]] = {}
    for group, signals in material.items():
        names[group] = []
        for i, y in enumerate(signals):
            filename = f"{group}_{i}.wav"
            sf.write(str(session.inputs_dir / filename), y, _SR)
            names[group].append(filename)
    return names


@pytest.fixture
def harness(tmp_path):
    mcp = FastMCP("test-cdp-cluster")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: None)
    tracker = LatestTracker()
    cluster_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: None,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions, tracker


async def _call(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "cluster", args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Pre-flight failure paths
# ---------------------------------------------------------------------------


async def test_no_active_session(harness):
    mcp, _sessions, _tracker = harness
    payload = await _call(mcp, {"targets": ["a.wav", "b.wav", "c.wav"]})
    assert payload["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in payload["errors"])


async def test_too_few_targets(harness):
    mcp, sessions, _tracker = harness
    session, _ = sessions.set_active("s1")
    sf.write(str(session.inputs_dir / "a.wav"), _sine(110.0), _SR)
    sf.write(str(session.inputs_dir / "b.wav"), _sine(440.0), _SR)
    payload = await _call(mcp, {"targets": ["a.wav", "b.wav"]})
    assert payload["status"] == "failed"
    assert any(e["type"] == "cluster_too_few" for e in payload["errors"])
    assert payload["n_targets"] == 2
    assert payload["k"] is None


async def test_unresolvable_ref_error_names_the_ref(harness):
    mcp, sessions, _tracker = harness
    session, _ = sessions.set_active("s1")
    sf.write(str(session.inputs_dir / "a.wav"), _sine(110.0), _SR)
    sf.write(str(session.inputs_dir / "b.wav"), _sine(440.0), _SR)
    payload = await _call(mcp, {"targets": ["a.wav", "b.wav", "ghost.wav"]})
    assert payload["status"] == "failed"
    err = next(e for e in payload["errors"] if e["type"] == "reference_resolution")
    assert "ghost.wav" in err["message"]


async def test_latest_batch_without_any_batch(harness):
    mcp, sessions, _tracker = harness
    sessions.set_active("s1")
    payload = await _call(mcp, {"targets": "latest_batch"})
    assert payload["status"] == "failed"
    assert any(e["type"] == "batch_not_available" for e in payload["errors"])


async def test_k_of_one_rejected(harness):
    mcp, sessions, _tracker = harness
    session, _ = sessions.set_active("s1")
    names = _write_three_groups(session)
    refs = [n for group in names.values() for n in group]
    payload = await _call(mcp, {"targets": refs, "k": 1})
    assert payload["status"] == "failed"
    assert any(e["type"] == "invalid_k" for e in payload["errors"])


async def test_ana_target_without_cdp(harness):
    mcp, sessions, _tracker = harness
    session, _ = sessions.set_active("s1")
    sf.write(str(session.inputs_dir / "a.wav"), _sine(110.0), _SR)
    sf.write(str(session.inputs_dir / "b.wav"), _sine(440.0), _SR)
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)
    payload = await _call(mcp, {"targets": ["a.wav", "b.wav", "frog.ana"]})
    assert payload["status"] == "failed"
    assert any(e["type"] == "cdp_not_configured" for e in payload["errors"])


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_three_groups_auto_k_and_separation(harness):
    """Auto-k lands near 3 for three clearly-different timbral groups;
    the sines stay together and never share a cluster with noise."""
    mcp, sessions, _tracker = harness
    session, _ = sessions.set_active("s1")
    names = _write_three_groups(session)
    refs = [n for group in names.values() for n in group]

    payload = await _call(mcp, {"targets": refs})
    assert payload["status"] == "ok"
    assert payload["n_targets"] == 9
    assert payload["seed"] == 42
    assert payload["k"] in {2, 3, 4}
    assert len(payload["clusters"]) == payload["k"]

    label_of = {
        m: c["label"] for c in payload["clusters"] for m in c["members"]
    }
    sine_labels = {label_of[r] for r in names["sine"]}
    noise_labels = {label_of[r] for r in names["noise"]}
    assert len(sine_labels) == 1  # all three sines share one cluster
    assert sine_labels.isdisjoint(noise_labels)  # no sine sits with noise

    # Every medoid is a member of its own cluster; sizes are honest.
    for c in payload["clusters"]:
        assert c["medoid"] in c["members"]
        assert c["size"] == len(c["members"])
    assert sum(c["size"] for c in payload["clusters"]) == 9

    # 2-D PCA coordinate per target, rounded to 4 decimal places.
    assert set(payload["pca_coords"]) == set(refs)
    for xy in payload["pca_coords"].values():
        assert len(xy) == 2
        assert all(v == round(v, 4) for v in xy)


async def test_deterministic_under_fixed_seed(harness):
    mcp, sessions, _tracker = harness
    session, _ = sessions.set_active("s1")
    names = _write_three_groups(session)
    refs = [n for group in names.values() for n in group]

    payload_1 = await _call(mcp, {"targets": refs, "seed": 42})
    payload_2 = await _call(mcp, {"targets": refs, "seed": 42})
    assert payload_1["status"] == payload_2["status"] == "ok"
    assert payload_1["k"] == payload_2["k"]
    assert payload_1["clusters"] == payload_2["clusters"]
    assert payload_1["pca_coords"] == payload_2["pca_coords"]


async def test_explicit_k(harness):
    mcp, sessions, _tracker = harness
    session, _ = sessions.set_active("s1")
    names = _write_three_groups(session)
    refs = [n for group in names.values() for n in group]

    payload = await _call(mcp, {"targets": refs, "k": 3})
    assert payload["status"] == "ok"
    assert payload["k"] == 3
    assert len(payload["clusters"]) == 3
    assert sum(c["size"] for c in payload["clusters"]) == 9


async def test_latest_batch_mode(harness):
    """'latest_batch' expands via the tracker's (graph_id, node_ids)
    state against a hand-built graph dir with a real node_index.json."""
    mcp, sessions, tracker = harness
    session, _ = sessions.set_active("s1")

    graph_root = session.graphs_dir / "g0"
    graph_root.mkdir(parents=True)
    material = [_sine(110.0), _noise(seed=1), _clicks(0.05)]
    node_ids: list[str] = []
    index: dict[str, str] = {}
    for i, y in enumerate(material):
        node_id = f"n1_batch_{i}"
        filename = f"{node_id}_out.wav"
        sf.write(str(graph_root / filename), y, _SR)
        index[node_id] = filename
        node_ids.append(node_id)
    (graph_root / "node_index.json").write_text(json.dumps(index))
    tracker.record_batch("g0", node_ids)

    payload = await _call(mcp, {"targets": "latest_batch"})
    assert payload["status"] == "ok"
    assert payload["n_targets"] == 3
    assert payload["k"] == 2  # N=3 → silhouette scan covers only k=2
    all_members = sorted(m for c in payload["clusters"] for m in c["members"])
    assert all_members == [f"g0:{nid}" for nid in node_ids]
    for c in payload["clusters"]:
        assert c["medoid"] in c["members"]
