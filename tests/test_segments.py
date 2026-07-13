"""Tests for segments() and analyze(verbose=True) — Phase 2 observation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP
from PIL import Image as PILImage

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import analyze as analyze_module
from cdp_mcp.tools import segments as segments_module


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


async def test_segments_missing_target(harness):
    mcp, sessions, _ = harness
    sessions.set_active("s1")
    result = await _call(mcp, "segments", {"target": "ghost.wav"})
    assert result[0]["status"] == "failed"
    assert any(
        e["type"] == "reference_resolution" for e in result[0]["errors"]
    )


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
