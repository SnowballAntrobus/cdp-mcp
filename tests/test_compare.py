"""Integration tests for the compare() MCP tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import compare as compare_module
from cdp_mcp.visualization import render_spectrogram

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()
_SR = 22050

_SCORECARD_FIELDS = {
    "duration_s",
    "peak_dbfs",
    "rms_db",
    "lufs_i",
    "spectral_centroid_hz",
    "spectral_flux",
    "zero_crossing_rate",
    "onset_count",
    "n_channels",
    "sample_rate",
}


def _write_sine(
    path: Path, seconds: float = 1.0, amp: float = 0.5, freq: float = 440.0
) -> None:
    t = np.arange(int(_SR * seconds)) / _SR
    sf.write(str(path), (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32), _SR)


def _write_clicks(path: Path, seconds: float = 1.2) -> None:
    """Transient click train — very high crest factor (~23 dB)."""
    n = int(_SR * seconds)
    y = np.zeros(n, dtype=np.float32)
    for start in range(0, n, int(0.1 * _SR)):
        y[start : start + 10] = 0.9
    sf.write(str(path), y, _SR)


def _write_noise(path: Path, seconds: float = 1.2, amp: float = 0.5) -> None:
    """Uniform-noise wash — low crest factor (~4.8 dB)."""
    rng = np.random.default_rng(42)
    y = (amp * rng.uniform(-1.0, 1.0, int(_SR * seconds))).astype(np.float32)
    sf.write(str(path), y, _SR)


@pytest.fixture
def fake_cdp_path(tmp_path):
    """Tmp CDP_PATH with a pvoc wrapper that writes a real wav."""
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    wrapper = cdp / "pvoc"
    wrapper.write_text(
        f"""#!/usr/bin/env bash
case "$1" in
    synth)
        OUTPUT="${{@: -1}}"
        exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT"
        ;;
    *)
        exit 1
        ;;
esac
"""
    )
    wrapper.chmod(0o755)
    return cdp


@pytest.fixture
def mcp_with_compare(fake_cdp_path, tmp_path):
    mcp = FastMCP("test-cdp-compare")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(cdp_path=fake_cdp_path, version="fake", detected_binaries=["pvoc"])
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    tracker = LatestTracker()
    compare_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions, tracker


async def _call(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "compare", args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Pre-flight failure paths
# ---------------------------------------------------------------------------


async def test_no_active_session(mcp_with_compare):
    mcp, _sessions, _tracker = mcp_with_compare
    result = await _call(mcp, {"target_a": "x.wav", "target_b": "y.wav"})
    assert isinstance(result, list) and len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in envelope["errors"])


async def test_invalid_loudness_method(mcp_with_compare):
    mcp, sessions, _tracker = mcp_with_compare
    sessions.set_active("s1")
    result = await _call(
        mcp,
        {"target_a": "a.wav", "target_b": "b.wav", "loudness_method": "rms"},
    )
    assert isinstance(result, list) and len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert any(
        e["type"] == "invalid_loudness_method" for e in envelope["errors"]
    )


async def test_missing_target_reference_resolution(mcp_with_compare):
    mcp, sessions, _tracker = mcp_with_compare
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "real.wav")
    result = await _call(mcp, {"target_a": "real.wav", "target_b": "ghost.wav"})
    assert isinstance(result, list) and len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert any(
        e["type"] == "reference_resolution" and "target_b" in e["message"]
        for e in envelope["errors"]
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_two_wav_inputs_happy_path(mcp_with_compare):
    mcp, sessions, _tracker = mcp_with_compare
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "low.wav", freq=440.0)
    _write_sine(session.inputs_dir / "high.wav", freq=880.0)
    result = await _call(mcp, {"target_a": "low.wav", "target_b": "high.wav"})
    assert isinstance(result, list) and len(result) == 2
    assert isinstance(result[0], Image)
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["loudness_method"] == "lufs_i"
    assert envelope["cached"] is False
    assert envelope["auto_synthed_a"] is False
    assert envelope["auto_synthed_b"] is False
    assert envelope["output"].endswith(".png")
    png_path = Path(envelope["output"])
    assert png_path.exists()

    # Scorecards + delta carry the full field set.
    assert set(envelope["analysis_a"].keys()) == _SCORECARD_FIELDS
    assert set(envelope["analysis_b"].keys()) == _SCORECARD_FIELDS
    assert set(envelope["delta"].keys()) == _SCORECARD_FIELDS

    # Delta arithmetic: b minus a for numeric fields.
    expected = (
        envelope["analysis_b"]["spectral_centroid_hz"]
        - envelope["analysis_a"]["spectral_centroid_hz"]
    )
    assert envelope["delta"]["spectral_centroid_hz"] == pytest.approx(expected)
    assert envelope["delta"]["spectral_centroid_hz"] > 0  # 880 Hz vs 440 Hz
    assert envelope["delta"]["sample_rate"] == 0
    assert envelope["delta"]["n_channels"] == 0

    # Composite is a valid image whose size matches the envelope.
    with PILImage.open(png_path) as im:
        assert im.size == (envelope["width_px"], envelope["height_px"])

    # Both panels present: composite is taller than a single panel render.
    single_png = session.tmp_dir / "single_reference.png"
    render_spectrogram(session.inputs_dir / "low.wav", single_png)
    with PILImage.open(single_png) as single, PILImage.open(png_path) as comp:
        assert comp.height > single.height


async def test_lufs_i_matching_attenuates_louder_file_only(mcp_with_compare):
    mcp, sessions, _tracker = mcp_with_compare
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "quiet.wav", amp=0.1)
    _write_sine(session.inputs_dir / "loud.wav", amp=0.8)
    result = await _call(mcp, {"target_a": "quiet.wav", "target_b": "loud.wav"})
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["loudness_method"] == "lufs_i"
    # Both matched to the QUIETER file's LUFS-I: the quiet side keeps
    # its gain, the loud side is attenuated.
    assert envelope["gain_applied_db_a"] == pytest.approx(0.0, abs=1e-6)
    assert envelope["gain_applied_db_b"] < -6.0
    # Post-match levels agree (same-shape signals).
    assert envelope["delta"]["rms_db"] == pytest.approx(0.0, abs=1.0)


async def test_crest_factor_warning_transient_vs_wash(mcp_with_compare):
    mcp, sessions, _tracker = mcp_with_compare
    session, _ = sessions.set_active("s1")
    _write_clicks(session.inputs_dir / "clicks.wav")
    _write_noise(session.inputs_dir / "wash.wav")
    result = await _call(mcp, {"target_a": "clicks.wav", "target_b": "wash.wav"})
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["loudness_method"] == "lufs_i"
    assert any("loudness_method='peak'" in w for w in envelope["warnings"])


async def test_peak_method_normalizes_both_to_minus_1_dbfs(mcp_with_compare):
    mcp, sessions, _tracker = mcp_with_compare
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "a.wav", amp=0.25)
    _write_sine(session.inputs_dir / "b.wav", amp=0.7, freq=660.0)
    result = await _call(
        mcp,
        {"target_a": "a.wav", "target_b": "b.wav", "loudness_method": "peak"},
    )
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["loudness_method"] == "peak"
    assert envelope["analysis_a"]["peak_dbfs"] == pytest.approx(-1.0, abs=0.1)
    assert envelope["analysis_b"]["peak_dbfs"] == pytest.approx(-1.0, abs=0.1)
    assert Path(envelope["output"]).exists()


async def test_lufs_m_method_matches_to_quieter_momentary(mcp_with_compare):
    mcp, sessions, _tracker = mcp_with_compare
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "quiet.wav", amp=0.1)
    _write_sine(session.inputs_dir / "loud.wav", amp=0.8)
    result = await _call(
        mcp,
        {
            "target_a": "quiet.wav",
            "target_b": "loud.wav",
            "loudness_method": "lufs_m",
        },
    )
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["loudness_method"] == "lufs_m"
    assert envelope["gain_applied_db_a"] == pytest.approx(0.0, abs=1e-6)
    assert envelope["gain_applied_db_b"] < -6.0


async def test_ana_target_auto_synths_and_short_audio_falls_back_to_peak(
    mcp_with_compare,
):
    mcp, sessions, _tracker = mcp_with_compare
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)
    _write_sine(session.inputs_dir / "ref.wav")
    result = await _call(mcp, {"target_a": "frog.ana", "target_b": "ref.wav"})
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["auto_synthed_a"] is True
    assert envelope["auto_synthed_b"] is False
    # Auto-synthed wav lives in session.tmp_dir.
    assert (session.tmp_dir / "frog.wav").exists()
    # The synth stub emits ~4.5 ms of audio — too short for LUFS-I, so
    # matching falls back to peak with a warning.
    assert envelope["loudness_method"] == "peak"
    assert any("falling back" in w for w in envelope["warnings"])
