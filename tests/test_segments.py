"""Tests for segments() and analyze(verbose=True) — Phase 2 observation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP
from PIL import Image as PILImage

from cdp_mcp.analysis import extract_rhythm
from cdp_mcp.cache import analysis_cache_key, cache_lookup, cache_populate_json
from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import analyze as analyze_module
from cdp_mcp.tools import segments as segments_module
from cdp_mcp.utils import sha256_file


@pytest.fixture
def harness(tmp_path):
    mcp = FastMCP("test-cdp-segments")
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(
        cdp_path=(tmp_path / "cdp").resolve(), version="fake",
        detected_binaries=["pvoc"],
    )
    (tmp_path / "cdp").mkdir()
    sessions = SessionManager((tmp_path / "sessions").resolve(), lambda: cdp_cfg)
    tracker = LatestTracker()
    for module in (segments_module, analyze_module):
        module.register(
            mcp,
            sessions=sessions,
            cdp_config_provider=lambda: cdp_cfg,
            latest_tracker=tracker,
            cache_root=cache_root,
        )
    return mcp, sessions, tracker


async def _call(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


def _write_click_train(path: Path, n_clicks: int = 4, sr: int = 22050) -> None:
    """1 s of silence-separated clicks — unambiguous onsets."""
    y = np.zeros(sr, dtype=np.float32)
    for i in range(n_clicks):
        pos = int((i + 0.5) * sr / n_clicks)
        y[pos:pos + 64] = 0.9
    sf.write(str(path), y, sr)


def _write_clicks_at(
    path: Path, times: list[float], total_s: float, sr: int = 22050
) -> None:
    """Clicks at explicit times — for known-IOI rhythm fixtures."""
    y = np.zeros(int(total_s * sr), dtype=np.float32)
    for t in times:
        pos = int(t * sr)
        y[pos:pos + 64] = 0.9
    sf.write(str(path), y, sr)


def _geometric_times(
    start: float, first_gap: float, ratio: float, n: int
) -> list[float]:
    """Bouncing-ball event times: gap shrinks geometrically per event."""
    times = [start]
    gap = first_gap
    for _ in range(n - 1):
        times.append(times[-1] + gap)
        gap *= ratio
    return times


def _session_with_clicks(sessions):
    session, _ = sessions.set_active("s1")
    _write_click_train(session.inputs_dir / "clicks.wav")
    return session


# ---------------------------------------------------------------------------
# segments()
# ---------------------------------------------------------------------------


async def test_segments_onset_happy_path(harness):
    mcp, sessions, _ = harness
    _session_with_clicks(sessions)
    result = await _call(mcp, "segments", {"target": "clicks.wav"})
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["method"] == "onset"
    segs = envelope["segments"]
    assert envelope["count"] == len(segs) >= 2  # 4 clicks → boundaries found
    # Segments tile the file: contiguous, ordered, full coverage.
    assert segs[0]["start"] == 0.0
    for a, b in zip(segs, segs[1:], strict=False):
        assert a["end"] == b["start"]
    assert segs[-1]["end"] == pytest.approx(1.0, abs=0.01)
    assert all(s["label"].startswith("onset_") for s in segs)
    # The marked-up PNG exists and is a real image.
    png = Path(envelope["visualization"])
    assert png.exists()
    with PILImage.open(png) as im:
        assert im.size[0] > 100


async def test_segments_silence_method(harness):
    mcp, sessions, _ = harness
    _session_with_clicks(sessions)
    result = await _call(
        mcp, "segments", {"target": "clicks.wav", "method": "silence"}
    )
    envelope = result[1]
    assert envelope["status"] == "ok"
    # Four clicks → four (or so) non-silent islands; definitely not one
    # segment spanning the file.
    assert envelope["count"] >= 2
    assert all(s["label"].startswith("silence_") for s in envelope["segments"])


async def test_segments_invalid_method(harness):
    mcp, sessions, _ = harness
    _session_with_clicks(sessions)
    result = await _call(
        mcp, "segments", {"target": "clicks.wav", "method": "vibes"}
    )
    assert result[0]["status"] == "failed"
    assert any(
        e["type"] == "invalid_segmentation_method"
        for e in result[0]["errors"]
    )


async def test_segments_cache_roundtrip(harness):
    """Second call on identical audio hits the analysis-tier cache."""
    mcp, sessions, _ = harness
    _session_with_clicks(sessions)
    first = await _call(mcp, "segments", {"target": "clicks.wav"})
    second = await _call(mcp, "segments", {"target": "clicks.wav"})
    assert first[1]["cached"] is False
    assert second[1]["cached"] is True
    assert second[1]["segments"] == first[1]["segments"]
    assert second[1]["rhythm"] == first[1]["rhythm"]


async def test_segments_missing_target(harness):
    mcp, sessions, _ = harness
    sessions.set_active("s1")
    result = await _call(mcp, "segments", {"target": "ghost.wav"})
    assert result[0]["status"] == "failed"
    assert any(
        e["type"] == "reference_resolution" for e in result[0]["errors"]
    )


# ---------------------------------------------------------------------------
# extract_rhythm() — pure-function pins (Phase 6 grid-free rhythm)
# ---------------------------------------------------------------------------


def test_rhythm_zero_events():
    """0 onsets: block present, count 0, all statistics null, no crash."""
    r = extract_rhythm([], 1.0)
    assert r["onset_count"] == 0
    assert r["ioi"] == {
        "count": 0, "mean_s": None, "std_s": None, "min_s": None,
        "max_s": None, "slope": None, "trend": None,
    }
    assert r["density"]["points"] == 16
    assert r["density"]["window_s"] == pytest.approx(1.0 / 16)
    assert r["density"]["counts"] == [0] * 16


def test_rhythm_single_event():
    """1 onset: zero intervals, null stats; density still counts it."""
    r = extract_rhythm([0.5], 1.0)
    assert r["onset_count"] == 1
    assert r["ioi"]["count"] == 0
    assert r["ioi"]["mean_s"] is None
    assert r["ioi"]["slope"] is None
    assert r["ioi"]["trend"] is None
    assert sum(r["density"]["counts"]) == 1
    assert r["density"]["counts"][8] == 1  # 0.5 s → window 8 of 16


def test_rhythm_two_events_one_interval():
    """2 onsets = 1 IOI: mean/min/max defined, std 0, slope/trend null
    (a line through one point is indeterminate — documented)."""
    r = extract_rhythm([0.1, 0.35], 1.0)
    assert r["ioi"]["count"] == 1
    assert r["ioi"]["mean_s"] == pytest.approx(0.25, abs=1e-6)
    assert r["ioi"]["min_s"] == r["ioi"]["max_s"] == r["ioi"]["mean_s"]
    assert r["ioi"]["std_s"] == pytest.approx(0.0, abs=1e-9)
    assert r["ioi"]["slope"] is None
    assert r["ioi"]["trend"] is None


def test_rhythm_steady_train():
    """Uniform IOIs: slope exactly 0, trend 'steady'."""
    events = [0.1 + 0.25 * k for k in range(8)]
    r = extract_rhythm(events, 2.1)
    assert r["onset_count"] == 8
    assert r["ioi"]["count"] == 7
    assert r["ioi"]["mean_s"] == pytest.approx(0.25, abs=1e-6)
    assert r["ioi"]["slope"] == pytest.approx(0.0, abs=1e-6)
    assert r["ioi"]["trend"] == "steady"


def test_rhythm_geometric_accelerando():
    """Bouncing-ball geometric IOI shrink → negative slope, 'accelerando'."""
    events = _geometric_times(0.1, 0.4, 0.8, 8)
    r = extract_rhythm(events, 2.5)
    assert r["ioi"]["count"] == 7
    assert r["ioi"]["slope"] < -0.01
    assert r["ioi"]["trend"] == "accelerando"
    # Geometric shrink: max is the first gap, min the last.
    assert r["ioi"]["max_s"] == pytest.approx(0.4, abs=1e-6)
    assert r["ioi"]["min_s"] == pytest.approx(0.4 * 0.8**6, abs=1e-6)


def test_rhythm_ritardando():
    """Growing IOIs → positive slope, 'ritardando'."""
    iois = [0.2, 0.24, 0.28, 0.32]
    events = [0.1]
    for g in iois:
        events.append(events[-1] + g)
    r = extract_rhythm(events, 1.5)
    # Linear IOI ramp: least-squares slope is exactly the increment.
    assert r["ioi"]["slope"] == pytest.approx(0.04, abs=1e-6)
    assert r["ioi"]["trend"] == "ritardando"


def test_rhythm_trend_threshold_boundary():
    """|slope| ≤ 5% of mean IOI per event reads 'steady' — the documented
    threshold. 0.01/0.215 ≈ 4.7% sits just inside."""
    iois = [0.2, 0.21, 0.22, 0.23]
    events = [0.1]
    for g in iois:
        events.append(events[-1] + g)
    r = extract_rhythm(events, 1.2)
    assert r["ioi"]["slope"] == pytest.approx(0.01, abs=1e-6)
    assert r["ioi"]["trend"] == "steady"


def test_rhythm_density_pins():
    """Known event times land in the exact 16 windows."""
    r = extract_rhythm([0.125, 0.375, 0.625, 0.875], 1.0)
    expected = [0] * 16
    for idx in (2, 6, 10, 14):
        expected[idx] = 1
    assert r["density"]["counts"] == expected
    assert r["density"]["points"] == 16
    assert r["density"]["window_s"] == pytest.approx(0.0625)


def test_rhythm_density_edge_event():
    """An event exactly at the file end lands in the last window."""
    r = extract_rhythm([0.0, 1.0], 1.0)
    assert r["density"]["counts"][0] == 1
    assert r["density"]["counts"][15] == 1


def test_rhythm_zero_duration():
    """Non-positive duration: empty density block, no crash."""
    r = extract_rhythm([], 0.0)
    assert r["density"] == {"points": 0, "window_s": None, "counts": []}


# ---------------------------------------------------------------------------
# segments() rhythm block — end-to-end through the tool
# ---------------------------------------------------------------------------


async def test_segments_rhythm_block_steady(harness):
    """Steady click train through the tool: block shape + 'steady' trend."""
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("s1")
    _write_clicks_at(
        session.inputs_dir / "steady.wav",
        [0.1 + 0.25 * k for k in range(8)],
        total_s=2.1,
    )
    result = await _call(mcp, "segments", {"target": "steady.wav"})
    envelope = result[1]
    assert envelope["status"] == "ok"
    rhythm = envelope["rhythm"]
    assert rhythm["onset_count"] >= 6  # librosa should find ~all 8
    assert rhythm["ioi"]["count"] == rhythm["onset_count"] - 1
    assert rhythm["ioi"]["mean_s"] == pytest.approx(0.25, abs=0.05)
    assert rhythm["ioi"]["trend"] == "steady"
    density = rhythm["density"]
    assert density["points"] == 16
    assert density["window_s"] == pytest.approx(2.1 / 16, abs=0.01)
    assert sum(density["counts"]) == rhythm["onset_count"]


async def test_segments_rhythm_accelerando(harness):
    """Bouncing-ball fixture through the tool: negative slope, trend
    'accelerando' — the Phase 6 reference use case."""
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("s1")
    times = _geometric_times(0.1, 0.35, 0.82, 10)
    _write_clicks_at(
        session.inputs_dir / "bounce.wav", times, total_s=times[-1] + 0.3
    )
    result = await _call(mcp, "segments", {"target": "bounce.wav"})
    envelope = result[1]
    assert envelope["status"] == "ok"
    rhythm = envelope["rhythm"]
    assert rhythm["onset_count"] >= 8
    assert rhythm["ioi"]["slope"] < -0.01
    assert rhythm["ioi"]["trend"] == "accelerando"


async def test_segments_rhythm_degenerate_silence(harness):
    """Digital silence: zero onsets → null IOI stats, zero density, ok."""
    mcp, sessions, _ = harness
    session, _ = sessions.set_active("s1")
    sf.write(
        str(session.inputs_dir / "hush.wav"),
        np.zeros(22050, dtype=np.float32), 22050,
    )
    result = await _call(mcp, "segments", {"target": "hush.wav"})
    envelope = result[1]
    assert envelope["status"] == "ok"
    rhythm = envelope["rhythm"]
    assert rhythm["onset_count"] == 0
    assert rhythm["ioi"]["count"] == 0
    assert rhythm["ioi"]["mean_s"] is None
    assert rhythm["ioi"]["trend"] is None
    assert sum(rhythm["density"]["counts"]) == 0


async def test_segments_rhythm_silence_method(harness):
    """method='silence' derives events from non-silent island starts."""
    mcp, sessions, _ = harness
    _session_with_clicks(sessions)
    result = await _call(
        mcp, "segments", {"target": "clicks.wav", "method": "silence"}
    )
    envelope = result[1]
    assert envelope["status"] == "ok"
    rhythm = envelope["rhythm"]
    assert rhythm["onset_count"] == envelope["count"]
    assert rhythm["ioi"]["count"] == max(rhythm["onset_count"] - 1, 0)


async def test_segments_cache_key_bump(harness, tmp_path):
    """The v1 → v2 feature-set bump: a stale v1 payload (no rhythm block)
    must NOT be read — keys don't collide, results regenerate."""
    mcp, sessions, _ = harness
    session = _session_with_clicks(sessions)
    cache_root = tmp_path / "cache"
    sha = sha256_file(session.inputs_dir / "clicks.wav")

    old_key = analysis_cache_key(sha, "segments_onset_v1", None, None)
    new_key = analysis_cache_key(sha, "segments_onset_v2", None, None)
    assert old_key != new_key

    # Poison the OLD key with a recognizable stale payload.
    stale = cache_lookup(cache_root, "analysis", old_key, ".json")
    assert not stale.hit
    cache_populate_json(stale.path, {
        "segments": [{"start": 0.0, "end": 9.9, "label": "stale_0"}],
        "markers": [],
        "warnings": [],
    })

    result = await _call(mcp, "segments", {"target": "clicks.wav"})
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["cached"] is False  # the stale v1 entry never hit
    assert all(s["label"] != "stale_0" for s in envelope["segments"])
    assert envelope["rhythm"]["onset_count"] >= 2


async def test_segments_v2_payload_without_rhythm_regenerates(harness, tmp_path):
    """Defense in depth: a v2-keyed payload missing 'rhythm' (corruption)
    is treated as a miss and recomputed, not served."""
    mcp, sessions, _ = harness
    session = _session_with_clicks(sessions)
    cache_root = tmp_path / "cache"
    sha = sha256_file(session.inputs_dir / "clicks.wav")
    key = analysis_cache_key(sha, "segments_onset_v2", None, None)
    entry = cache_lookup(cache_root, "analysis", key, ".json")
    cache_populate_json(entry.path, {
        "segments": [{"start": 0.0, "end": 1.0, "label": "norhythm_0"}],
        "markers": [],
        "warnings": [],
    })
    result = await _call(mcp, "segments", {"target": "clicks.wav"})
    envelope = result[1]
    assert envelope["cached"] is False
    assert envelope["rhythm"] is not None
    assert all(s["label"] != "norhythm_0" for s in envelope["segments"])


# ---------------------------------------------------------------------------
# analyze(verbose=True)
# ---------------------------------------------------------------------------


async def test_analyze_verbose_block(harness):
    mcp, sessions, _ = harness
    _session_with_clicks(sessions)
    payload = await _call(
        mcp, "analyze", {"target": "clicks.wav", "verbose": True}
    )
    assert payload["status"] == "ok"
    assert "analysis" in payload  # concise scorecard still present
    vb = payload["analysis_verbose"]
    assert len(vb["mfcc_mean"]) == 13
    assert len(vb["mfcc_std"]) == 13
    assert len(vb["chroma_mean"]) == 12
    assert vb["n_channels"] == 1
    assert vb["per_channel"][0]["peak_dbfs"] is not None


async def test_analyze_default_omits_verbose(harness):
    mcp, sessions, _ = harness
    _session_with_clicks(sessions)
    payload = await _call(mcp, "analyze", {"target": "clicks.wav"})
    assert payload["status"] == "ok"
    assert "analysis_verbose" not in payload
