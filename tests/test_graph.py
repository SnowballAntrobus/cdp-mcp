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
    build_context_block,
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
# LatestTracker — deque + prev_N
# ---------------------------------------------------------------------------


def test_latest_tracker_starts_empty():
    t = LatestTracker()
    assert t.latest is None
    assert t.get_slot(0) is None
    assert t.recent_entries() == []


def test_latest_tracker_single_update():
    t = LatestTracker()
    t.update("g1", "n1")
    assert t.latest == "g1:n1"
    assert t.get_slot(0).graph_id == "g1"
    assert t.get_slot(0).node_id == "n1"
    assert t.get_slot(1) is None


def test_latest_tracker_push_shifts_older_to_prev_n():
    t = LatestTracker()
    t.update("g1", "n1")
    t.update("g2", "n1")
    t.update("g3", "n1")
    assert t.latest == "g3:n1"
    assert t.get_slot(0).graph_id == "g3"
    assert t.get_slot(1).graph_id == "g2"
    assert t.get_slot(2).graph_id == "g1"
    assert t.get_slot(3) is None


def test_latest_tracker_capacity_drops_oldest():
    t = LatestTracker()
    for i in range(1, 7):  # 6 pushes against a 5-slot deque
        t.update(f"g{i}", "n1")
    assert t.latest == "g6:n1"
    # Slots 0..4 hold g6..g2; g1 has aged off.
    expected = ["g6", "g5", "g4", "g3", "g2"]
    for pos, gid in enumerate(expected):
        assert t.get_slot(pos).graph_id == gid
    # No slot holds g1.
    for pos in range(5):
        assert t.get_slot(pos).graph_id != "g1"


def test_latest_tracker_recent_entries_assigns_positional_aliases():
    t = LatestTracker()
    t.update("g1", "n1")
    t.update("g2", "n1")
    t.update("g3", "n1")
    entries = t.recent_entries()
    aliases = [e.alias for e in entries]
    assert aliases == ["latest", "prev_1", "prev_2"]
    assert entries[0].id == "g3"
    assert entries[1].id == "g2"
    assert entries[2].id == "g1"


def test_latest_tracker_remove_creates_hole_without_shifting():
    t = LatestTracker()
    for i in range(1, 4):
        t.update(f"g{i}", "n1")
    # Deque now: [g3, g2, g1]; latest=g3, prev_1=g2, prev_2=g1.
    t.remove("g2")
    # The g2 slot is now a hole; g1 and g3 keep their positions.
    assert t.get_slot(0).graph_id == "g3"
    assert t.get_slot(1) is None
    assert t.get_slot(2).graph_id == "g1"
    # latest still points at g3.
    assert t.latest == "g3:n1"


def test_latest_tracker_recent_entries_skips_holes_keeps_aliases():
    t = LatestTracker()
    for i in range(1, 4):
        t.update(f"g{i}", "n1")
    t.remove("g2")
    entries = t.recent_entries()
    aliases = [e.alias for e in entries]
    ids = [e.id for e in entries]
    # prev_1 is the hole; latest (g3) and prev_2 (g1) survive with their
    # original positional aliases — NOT renumbered.
    assert aliases == ["latest", "prev_2"]
    assert ids == ["g3", "g1"]


def test_latest_tracker_remove_when_graph_id_absent_is_noop():
    t = LatestTracker()
    t.update("g1", "n1")
    t.remove("does-not-exist")
    assert t.get_slot(0).graph_id == "g1"


def test_latest_tracker_clear_empties_deque():
    t = LatestTracker()
    t.update("g1", "n1")
    t.update("g2", "n1")
    t.clear()
    assert t.latest is None
    assert t.recent_entries() == []
    assert t.get_slot(0) is None


def test_latest_tracker_push_after_hole_does_not_fill_hole():
    """New pushes shift everything left and drop from the right end. A
    hole left by remove() doesn't get 'filled' by the next push — it
    just shifts toward older positions like any other slot."""
    t = LatestTracker()
    for i in range(1, 4):
        t.update(f"g{i}", "n1")   # [g3, g2, g1]
    t.remove("g2")                # [g3, None, g1]
    t.update("g4", "n1")          # [g4, g3, None, g1]
    assert t.get_slot(0).graph_id == "g4"
    assert t.get_slot(1).graph_id == "g3"
    assert t.get_slot(2) is None
    assert t.get_slot(3).graph_id == "g1"


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
    # Phase 2 M5 containment: absolute refs resolve only INSIDE the
    # session tree (previously any existing absolute path was accepted;
    # see TestResolveTargetContainment for the rejection cases).
    target = session.root / "tmp" / "somewhere_else.wav"
    target.write_bytes(b"hi")
    assert resolve_target(str(target), session, LatestTracker()) == target.resolve()


def test_resolve_target_absolute_path_missing(session):
    with pytest.raises(ReferenceResolutionError, match="does not exist"):
        resolve_target("/nonexistent/absolute/path.wav", session, LatestTracker())


def test_resolve_target_empty_string(session):
    with pytest.raises(ReferenceResolutionError, match="Empty"):
        resolve_target("", session, LatestTracker())


def test_resolve_target_prev_1_raises_when_unset(session):
    with pytest.raises(ReferenceResolutionError, match="prev_1"):
        resolve_target("prev_1", session, LatestTracker())


def test_resolve_target_prev_1_resolves_after_one_prior_action(session):
    # Two graphs: g_a (oldest), g_b (newest). prev_1 should point at g_a.
    g_a = GraphDir(session, "ga")
    out_a = g_a.root / "n1.wav"
    out_a.write_bytes(b"hi")
    g_a.add_node("n1", "n1.wav", _fake_lineage())

    g_b = GraphDir(session, "gb")
    out_b = g_b.root / "n1.wav"
    out_b.write_bytes(b"hi")
    g_b.add_node("n1", "n1.wav", _fake_lineage())

    t = LatestTracker()
    t.update(g_a.id, "n1")
    t.update(g_b.id, "n1")
    assert resolve_target("prev_1", session, t) == out_a
    assert resolve_target("latest", session, t) == out_b


def test_resolve_target_prev_n_out_of_range_raises(session):
    t = LatestTracker()
    t.update("g1", "n1")
    with pytest.raises(ReferenceResolutionError, match="N must be 1..4"):
        resolve_target("prev_5", session, t)
    with pytest.raises(ReferenceResolutionError, match="N must be 1..4"):
        resolve_target("prev_0", session, t)


def test_resolve_target_prev_n_malformed_raises(session):
    t = LatestTracker()
    with pytest.raises(ReferenceResolutionError, match="Malformed prev reference"):
        resolve_target("prev_abc", session, t)


def test_resolve_target_prev_n_on_hole_raises(session):
    """A slot emptied by remove() does not silently roll forward to the
    next graph — prev_N for that slot raises a clear error."""
    g_a = GraphDir(session, "ga")
    (g_a.root / "n1.wav").write_bytes(b"hi")
    g_a.add_node("n1", "n1.wav", _fake_lineage())
    g_b = GraphDir(session, "gb")
    (g_b.root / "n1.wav").write_bytes(b"hi")
    g_b.add_node("n1", "n1.wav", _fake_lineage())

    t = LatestTracker()
    t.update(g_a.id, "n1")
    t.update(g_b.id, "n1")
    # Deque: [g_b, g_a]. Now remove g_a — prev_1 becomes a hole.
    t.remove(g_a.id)
    with pytest.raises(ReferenceResolutionError, match="prev_1"):
        resolve_target("prev_1", session, t)


# ---------------------------------------------------------------------------
# build_context_block — recent_graphs + available_sources
# ---------------------------------------------------------------------------


def test_build_context_empty_session_no_actions(session):
    ctx = build_context_block(session, LatestTracker(), active_graph=None)
    assert ctx.latest is None
    assert ctx.recent_graphs == []
    assert ctx.available_sources == []  # empty inputs_dir


def test_build_context_populates_recent_graphs(session):
    t = LatestTracker()
    t.update("g1", "n1")
    t.update("g2", "n2")
    ctx = build_context_block(session, t, active_graph="g2")
    assert ctx.active_graph == "g2"
    assert ctx.latest == "g2:n2"
    aliases = [e.alias for e in ctx.recent_graphs]
    assert aliases == ["latest", "prev_1"]


def test_build_context_available_sources_includes_recent_refs(session):
    # Put an input file in the session.
    (session.inputs_dir / "frog.wav").write_bytes(b"x")
    t = LatestTracker()
    t.update("g1", "n1")
    ctx = build_context_block(session, t, active_graph="g1")
    # Inputs come first, then graph refs.
    assert ctx.available_sources == ["frog.wav", "g1:n1"]


def test_build_context_available_sources_deduplicates(session):
    """If an input filename happens to match the string form of a graph
    ref (it never should in practice, but defensively), no duplicates."""
    (session.inputs_dir / "g1:n1").write_bytes(b"x")  # contrived
    t = LatestTracker()
    t.update("g1", "n1")
    ctx = build_context_block(session, t, active_graph="g1")
    assert ctx.available_sources.count("g1:n1") == 1


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


# ---------------------------------------------------------------------------
# resolve_target containment (Phase 2 hardening, M5)
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker() -> LatestTracker:
    return LatestTracker()


class TestResolveTargetContainment:
    def test_absolute_path_outside_session_rejected(self, session, tracker, tmp_path):
        outside = tmp_path.parent / "outside.wav"
        outside.write_bytes(b"x")
        with pytest.raises(ReferenceResolutionError, match="outside the session tree"):
            resolve_target(str(outside), session, tracker)

    def test_relative_traversal_outside_session_rejected(
        self, session, tracker, tmp_path
    ):
        outside = tmp_path.parent / "escape.wav"
        outside.write_bytes(b"x")
        depth = len(session.inputs_dir.parts)
        ref = ("../" * depth) + str(outside).lstrip("/")
        with pytest.raises(ReferenceResolutionError):
            resolve_target(ref, session, tracker)

    def test_graph_id_traversal_rejected(self, session, tracker):
        with pytest.raises(ReferenceResolutionError, match="separators or traversal"):
            resolve_target("../../../etc:n1", session, tracker)

    def test_node_index_filename_escape_rejected(self, session, tracker):
        graph_root = session.graphs_dir / "20260101T000000-evil"
        graph_root.mkdir(parents=True)
        (graph_root / "node_index.json").write_text(
            '{"n1": "../../../../etc/passwd"}'
        )
        with pytest.raises(ReferenceResolutionError, match="escapes the graph"):
            resolve_target("20260101T000000-evil:n1", session, tracker)

    def test_inputs_path_still_resolves(self, session, tracker):
        target = session.inputs_dir / "ok.wav"
        target.write_bytes(b"x")
        assert resolve_target("ok.wav", session, tracker) == target.resolve()
