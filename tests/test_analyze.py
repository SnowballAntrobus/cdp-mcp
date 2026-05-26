"""Integration tests for the analyze() MCP tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import analyze as analyze_module

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


def _write_sine(path: Path, seconds: float = 1.0) -> None:
    t = np.arange(int(_SR * seconds)) / _SR
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), _SR)


@pytest.fixture
def fake_cdp_path(tmp_path, monkeypatch):
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    wrapper = cdp / "pvoc"
    wrapper.write_text(
        f"""#!/bin/sh
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
def mcp_with_analyze(fake_cdp_path, tmp_path):
    mcp = FastMCP("test-cdp-analyze")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(cdp_path=fake_cdp_path, version="fake", detected_binaries=["pvoc"])
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    tracker = LatestTracker()
    analyze_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions, tracker


@pytest.fixture
def mcp_without_cdp(tmp_path):
    mcp = FastMCP("test-cdp-analyze-nocdp")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: None)
    tracker = LatestTracker()
    analyze_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: None,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions


async def _call(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "analyze", args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Pre-flight failure paths
# ---------------------------------------------------------------------------


async def test_no_active_session(mcp_with_analyze):
    mcp, _sessions, _tracker = mcp_with_analyze
    envelope = await _call(mcp, {"target": "x.wav"})
    assert envelope["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in envelope["errors"])


async def test_reference_resolution_failure(mcp_with_analyze):
    mcp, sessions, _tracker = mcp_with_analyze
    sessions.set_active("s1")
    envelope = await _call(mcp, {"target": "ghost.wav"})
    assert any(e["type"] == "reference_resolution" for e in envelope["errors"])


async def test_ana_input_cdp_not_configured(mcp_without_cdp):
    mcp, sessions = mcp_without_cdp
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)
    envelope = await _call(mcp, {"target": "frog.ana"})
    assert any(e["type"] == "cdp_not_configured" for e in envelope["errors"])


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_wav_input_returns_full_scorecard(mcp_with_analyze):
    mcp, sessions, _tracker = mcp_with_analyze
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav", seconds=1.0)
    envelope = await _call(mcp, {"target": "frog.wav"})
    assert envelope["status"] == "ok"
    assert envelope["output"] is None
    assert envelope["auto_synthed"] is False
    assert "analysis" in envelope
    assert set(envelope["analysis"].keys()) == _SCORECARD_FIELDS
    assert envelope["analysis"]["n_channels"] == 1
    assert envelope["analysis"]["sample_rate"] == _SR


async def test_ana_input_auto_synths(mcp_with_analyze):
    mcp, sessions, _tracker = mcp_with_analyze
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)
    envelope = await _call(mcp, {"target": "frog.ana"})
    assert envelope["status"] == "ok"
    assert envelope["auto_synthed"] is True
    assert (session.tmp_dir / "frog.wav").exists()
    assert set(envelope["analysis"].keys()) == _SCORECARD_FIELDS


async def test_too_short_audio_warning_surfaces(mcp_with_analyze):
    mcp, sessions, _tracker = mcp_with_analyze
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "tiny.wav", seconds=0.2)
    envelope = await _call(mcp, {"target": "tiny.wav"})
    assert envelope["status"] == "ok"
    assert envelope["analysis"]["lufs_i"] is None
    assert any("too short" in w.lower() for w in envelope["warnings"])


async def test_invalid_window_t_start_negative(mcp_with_analyze):
    mcp, sessions, _tracker = mcp_with_analyze
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav")
    envelope = await _call(mcp, {"target": "frog.wav", "t_start": -1.0})
    assert any(e["type"] == "invalid_window" for e in envelope["errors"])


async def test_invalid_window_t_duration_zero(mcp_with_analyze):
    mcp, sessions, _tracker = mcp_with_analyze
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav")
    envelope = await _call(mcp, {"target": "frog.wav", "t_duration": 0.0})
    assert any(e["type"] == "invalid_window" for e in envelope["errors"])
