"""Unit tests for cdp_mcp.graph."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.graph import (
    GraphDir,
    LatestTracker,
    ReferenceResolutionError,
    resolve_target,
    verify_output,
)
from cdp_mcp.schema import InputRecord, NodeLineage
from cdp_mcp.session import Session, SessionConfig

_GRAPH_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}-[A-Za-z0-9_.-]+$")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session(tmp_path) -> Session:
    """Build a Session against tmp_path with all subdirs present."""
    root = tmp_path / "session_root"
    for sub in ("inputs", "graphs", "templates", "envelopes", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    config = SessionConfig(
        session_name="test",
        created_at=datetime.now(timezone.utc),
        cdp_version="test",
        python_version="3.11.6",
        cdp_mcp_version="0.0.0",
    )
    return Session(name="test", root=root, config=config)


def _fake_lineage() -> NodeLineage:
    now = datetime.now(timezone.utc)
    return NodeLineage(
        argv=["/usr/bin/true"],
        inputs=[InputRecord(path="/tmp/in.wav", sha256="a" * 64)],
        output_path="/tmp/out.wav",
        output_sha256="b" * 64,
        params={"velocity": 0.5},
        cdp_version="test",
        started_at=now,
        finished_at=now,
        duration_ms=10,
        exit_code=0,
    )


# ---------------------------------------------------------------------------
# GraphDir
# ---------------------------------------------------------------------------


def test_graphdir_init_creates_directory_with_expected_name(session):
    g = GraphDir(session, "blur-blur")
    assert g.root.is_dir()
    assert _GRAPH_ID_RE.match(g.id), f"unexpected graph id: {g.id}"
    assert g.id.endswith("-blur-blur")


def test_graphdir_init_writes_empty_index_and_lineage(session):
    g = GraphDir(session, "x")
    assert json.loads(g.node_index_path.read_text(encoding="utf-8")) == {}
    assert json.loads(g.lineage_path.read_text(encoding="utf-8")) == {"nodes": {}}
    assert not g.graph_definition_path.exists()


def test_set_graph_definition_writes_atomically(session):
    g = GraphDir(session, "x")
    g.set_graph_definition({"nodes": [{"id": "n1"}], "edges": []})
    data = json.loads(g.graph_definition_path.read_text(encoding="utf-8"))
    assert data == {"nodes": [{"id": "n1"}], "edges": []}
    # No stray .tmp file.
    assert not g.graph_definition_path.with_suffix(".json.tmp").exists()


def test_add_node_updates_both_files(session):
    g = GraphDir(session, "x")
    lineage = _fake_lineage()
    g.add_node("n1", "n1_blur-blur.wav", lineage)

    index = json.loads(g.node_index_path.read_text(encoding="utf-8"))
    assert index == {"n1": "n1_blur-blur.wav"}

    lineage_data = json.loads(g.lineage_path.read_text(encoding="utf-8"))
    assert "n1" in lineage_data["nodes"]
    # Round-trip the lineage record back into the model.
    reloaded = NodeLineage.model_validate(lineage_data["nodes"]["n1"])
    assert reloaded.argv == lineage.argv
    assert reloaded.exit_code == 0


def test_add_node_two_sequential_calls(session):
    g = GraphDir(session, "x")
    g.add_node("n1", "n1.wav", _fake_lineage())
    g.add_node("n2", "n2.wav", _fake_lineage())
    index = json.loads(g.node_index_path.read_text(encoding="utf-8"))
    assert index == {"n1": "n1.wav", "n2": "n2.wav"}
    lineage_data = json.loads(g.lineage_path.read_text(encoding="utf-8"))
    assert set(lineage_data["nodes"].keys()) == {"n1", "n2"}


def test_get_node_output_path(session):
    g = GraphDir(session, "x")
    g.add_node("n1", "n1_out.wav", _fake_lineage())
    assert g.get_node_output_path("n1") == g.root / "n1_out.wav"
    assert g.get_node_output_path("missing") is None


def test_node_ids_returns_sorted(session):
    g = GraphDir(session, "x")
    g.add_node("n2", "n2.wav", _fake_lineage())
    g.add_node("n1", "n1.wav", _fake_lineage())
    g.add_node("n10", "n10.wav", _fake_lineage())
    # Lexicographic sort — n1, n10, n2 — that's fine for Phase 1a.
    assert g.node_ids() == ["n1", "n10", "n2"]


# ---------------------------------------------------------------------------
# LatestTracker
# ---------------------------------------------------------------------------


def test_latest_tracker_lifecycle():
    t = LatestTracker()
    assert t.latest is None
    t.update("g1", "n1")
    assert t.latest == "g1:n1"
    t.update("g2", "n5")
    assert t.latest == "g2:n5"
    t.clear()
    assert t.latest is None


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------


def test_resolve_target_latest_raises_when_unset(session):
    with pytest.raises(ReferenceResolutionError, match="latest"):
        resolve_target("latest", session, LatestTracker())


def test_resolve_target_latest_follows_pointer(session):
    g = GraphDir(session, "x")
    out = g.root / "n1.wav"
    out.write_bytes(b"hi")
    g.add_node("n1", "n1.wav", _fake_lineage())
    tracker = LatestTracker()
    tracker.update(g.id, "n1")
    assert resolve_target("latest", session, tracker) == out


def test_resolve_target_graph_ref_resolves(session):
    g = GraphDir(session, "x")
    out = g.root / "n1.wav"
    out.write_bytes(b"hi")
    g.add_node("n1", "n1.wav", _fake_lineage())
    assert resolve_target(f"{g.id}:n1", session, LatestTracker()) == out


def test_resolve_target_graph_ref_missing_graph(session):
    with pytest.raises(ReferenceResolutionError, match="no such graph"):
        resolve_target("not-a-graph:n1", session, LatestTracker())


def test_resolve_target_graph_ref_missing_node(session):
    g = GraphDir(session, "x")
    with pytest.raises(ReferenceResolutionError, match="no node"):
        resolve_target(f"{g.id}:does_not_exist", session, LatestTracker())


def test_resolve_target_graph_ref_malformed(session):
    with pytest.raises(ReferenceResolutionError, match="Malformed"):
        resolve_target("only-colon-no-node:", session, LatestTracker())


def test_resolve_target_relative_path_in_inputs(session):
    f = session.inputs_dir / "frog.wav"
    f.write_bytes(b"hi")
    assert resolve_target("frog.wav", session, LatestTracker()) == f


def test_resolve_target_relative_path_not_found(session):
    with pytest.raises(ReferenceResolutionError, match="not found in session inputs"):
        resolve_target("ghost.wav", session, LatestTracker())


def test_resolve_target_absolute_path_exists(session, tmp_path):
    target = tmp_path / "somewhere_else.wav"
    target.write_bytes(b"hi")
    assert resolve_target(str(target), session, LatestTracker()) == target


def test_resolve_target_absolute_path_missing(session):
    with pytest.raises(ReferenceResolutionError, match="does not exist"):
        resolve_target("/nonexistent/absolute/path.wav", session, LatestTracker())


def test_resolve_target_empty_string(session):
    with pytest.raises(ReferenceResolutionError, match="Empty"):
        resolve_target("", session, LatestTracker())


# ---------------------------------------------------------------------------
# verify_output
# ---------------------------------------------------------------------------


def _write_wav(path: Path, samples: np.ndarray, sr: int = 44100) -> None:
    sf.write(str(path), samples, sr)


def test_verify_output_missing_file(tmp_path):
    v = verify_output(tmp_path / "ghost.wav")
    assert v.ok is False
    assert v.exists is False
    assert v.size_bytes == 0
    assert v.rms_dbfs is None
    assert any("does not exist" in e for e in v.errors)


def test_verify_output_tiny_file(tmp_path):
    target = tmp_path / "tiny.wav"
    target.write_bytes(b"x" * 10)
    v = verify_output(target)
    assert v.ok is False
    assert v.exists is True
    assert v.size_bytes == 10
    assert any("below minimum" in e for e in v.errors)


def test_verify_output_silent_wav(tmp_path):
    target = tmp_path / "silent.wav"
    _write_wav(target, np.zeros(44100, dtype=np.float32))
    v = verify_output(target)
    assert v.ok is False
    assert v.exists is True
    assert v.rms_dbfs is None
    assert any("silent" in e for e in v.errors)


def test_verify_output_valid_wav(tmp_path):
    target = tmp_path / "sine.wav"
    sr = 44100
    t = np.arange(sr) / sr
    samples = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    _write_wav(target, samples, sr)
    v = verify_output(target)
    assert v.ok is True
    assert v.exists is True
    assert v.errors == []
    # Full-scale sine RMS is 1/sqrt(2) ≈ -3.01 dBFS.
    assert v.rms_dbfs is not None
    assert math.isclose(v.rms_dbfs, -3.01, abs_tol=0.5)


def test_verify_output_below_threshold_wav(tmp_path):
    # Wav at -80 dBFS (well below the default -60 threshold).
    target = tmp_path / "quiet.wav"
    sr = 44100
    t = np.arange(sr) / sr
    samples = (0.0001 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    _write_wav(target, samples, sr)
    v = verify_output(target)
    assert v.ok is False
    # rms_dbfs reported even though below threshold.
    assert v.rms_dbfs is not None
    assert v.rms_dbfs < -60
    assert any("below silence threshold" in e for e in v.errors)


def test_verify_output_stereo_wav_flattens(tmp_path):
    # Two channels, both full-scale sines but anti-correlated. A naive
    # channel-mean would cancel and report ~silent; flatten gives ~-3 dBFS.
    target = tmp_path / "anti.wav"
    sr = 44100
    t = np.arange(sr) / sr
    left = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    stereo = np.stack([left, -left], axis=1)
    _write_wav(target, stereo, sr)
    v = verify_output(target)
    assert v.ok is True
    assert v.rms_dbfs is not None
    assert math.isclose(v.rms_dbfs, -3.01, abs_tol=0.5)


def test_verify_output_ana_file_size_only(tmp_path):
    # .ana files are spectral, RMS isn't meaningful — size check only.
    target = tmp_path / "frame.ana"
    target.write_bytes(b"x" * 2048)
    v = verify_output(target)
    assert v.ok is True
    assert v.size_bytes == 2048
    assert v.rms_dbfs is None
    assert v.errors == []
