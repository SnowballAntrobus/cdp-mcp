"""Integration tests for the visualize() MCP tool."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP, Image

# Import visualization first to pin matplotlib's Agg backend.
from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import visualize as visualize_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()
_SR = 22050


def _write_sine(path: Path, seconds: float = 1.0) -> None:
    t = np.arange(int(_SR * seconds)) / _SR
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), _SR)


@pytest.fixture
def fake_cdp_path(tmp_path, monkeypatch):
    """Tmp CDP_PATH with a pvoc wrapper that writes a real wav."""
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    shutil.copy2(_FAKE_SUBPROCESS, cdp / "pvoc")
    (cdp / "pvoc").chmod(0o755)
    # Make pvoc a wrapper that emits a valid wav for synth, otherwise no-op.
    wrapper = cdp / "pvoc"
    wrapper.unlink()
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
def mcp_with_visualize(fake_cdp_path, tmp_path):
    mcp = FastMCP("test-cdp-visualize")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(cdp_path=fake_cdp_path, version="fake", detected_binaries=["pvoc"])
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    tracker = LatestTracker()
    visualize_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions, tracker


@pytest.fixture
def mcp_without_cdp(tmp_path):
    """visualize() with CDP unconfigured — to exercise the spectral error path."""
    mcp = FastMCP("test-cdp-visualize-nocdp")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: None)
    tracker = LatestTracker()
    visualize_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: None,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions


async def _call(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "visualize", args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Pre-flight failure paths
# ---------------------------------------------------------------------------


async def test_no_active_session(mcp_with_visualize):
    mcp, _sessions, _tracker = mcp_with_visualize
    result = await _call(mcp, {"target": "x.wav"})
    assert isinstance(result, list) and len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in envelope["errors"])


async def test_reference_resolution_failure(mcp_with_visualize):
    mcp, sessions, _tracker = mcp_with_visualize
    sessions.set_active("s1")
    result = await _call(mcp, {"target": "ghost.wav"})
    assert len(result) == 1
    envelope = result[0]
    assert any(e["type"] == "reference_resolution" for e in envelope["errors"])


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_wav_input_happy_path(mcp_with_visualize):
    mcp, sessions, _tracker = mcp_with_visualize
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav")
    result = await _call(mcp, {"target": "frog.wav"})
    assert isinstance(result, list) and len(result) == 2
    assert isinstance(result[0], Image)
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["output"] is not None
    assert envelope["output"].endswith(".png")
    assert envelope["auto_synthed"] is False
    assert envelope["n_channels"] == 1
    assert Path(envelope["output"]).exists()


async def test_ana_input_auto_synths(mcp_with_visualize):
    mcp, sessions, _tracker = mcp_with_visualize
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)
    result = await _call(mcp, {"target": "frog.ana"})
    assert len(result) == 2
    assert isinstance(result[0], Image)
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["auto_synthed"] is True
    # Auto-synthed wav lives in session.tmp_dir.
    assert (session.tmp_dir / "frog.wav").exists()


async def test_ana_input_cdp_not_configured(mcp_without_cdp):
    mcp, sessions = mcp_without_cdp
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)
    result = await _call(mcp, {"target": "frog.ana"})
    assert len(result) == 1
    envelope = result[0]
    assert any(e["type"] == "cdp_not_configured" for e in envelope["errors"])


async def test_invalid_window_t_end_before_t_start(mcp_with_visualize):
    mcp, sessions, _tracker = mcp_with_visualize
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav", seconds=2.0)
    result = await _call(mcp, {"target": "frog.wav", "t_start": 1.0, "t_end": 0.5})
    assert len(result) == 1
    envelope = result[0]
    assert any(e["type"] == "invalid_window" for e in envelope["errors"])


async def test_window_past_end_returns_invalid_window(mcp_with_visualize):
    mcp, sessions, _tracker = mcp_with_visualize
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav", seconds=1.0)
    result = await _call(mcp, {"target": "frog.wav", "t_start": 5.0})
    assert len(result) == 1
    envelope = result[0]
    assert any(e["type"] == "invalid_window" for e in envelope["errors"])


# ---------------------------------------------------------------------------
# Task 10 — Visualization cache: miss populates, hit skips render
# ---------------------------------------------------------------------------


async def test_visualize_cache_miss_then_hit(mcp_with_visualize, tmp_path):
    """First call renders + populates the cache; second call materializes
    the cached PNG without calling ``render_spectrogram``."""
    mcp, sessions, _tracker = mcp_with_visualize
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav", seconds=1.0)

    result_1 = await _call(mcp, {"target": "frog.wav"})
    envelope_1 = result_1[1]
    assert envelope_1["status"] == "ok"
    assert envelope_1["cached"] is False
    # Cache populated.
    cache_files = list((tmp_path / "cache" / "visualizations").glob("*.png"))
    assert len(cache_files) == 1

    # Second call: monkey-patch render_spectrogram to raise; cache hit
    # must short-circuit before reaching it.
    import cdp_mcp.tools.visualize as visualize_module_path

    def explode(*_a, **_kw):
        raise AssertionError("render_spectrogram must not run on cache hit")

    original = visualize_module_path.render_spectrogram
    visualize_module_path.render_spectrogram = explode
    try:
        result_2 = await _call(mcp, {"target": "frog.wav"})
    finally:
        visualize_module_path.render_spectrogram = original

    envelope_2 = result_2[1]
    assert envelope_2["status"] == "ok"
    assert envelope_2["cached"] is True
    # Metadata fields are populated on the cache-hit path too.
    assert envelope_2["width_px"] > 0
    assert envelope_2["height_px"] > 0
    assert envelope_2["sample_rate"] == _SR
    assert envelope_2["n_channels"] == 1


async def test_visualize_cache_invalidates_on_matplotlib_version_change(
    mcp_with_visualize, monkeypatch, tmp_path
):
    """Matplotlib upgrade → visualization cache invalidates."""
    from cdp_mcp import cache as cache_mod

    mcp, sessions, _tracker = mcp_with_visualize
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav", seconds=1.0)

    monkeypatch.setitem(cache_mod._LIB_VERSIONS, "matplotlib", "test-v1")
    result_1 = await _call(mcp, {"target": "frog.wav"})
    assert result_1[1]["cached"] is False

    monkeypatch.setitem(cache_mod._LIB_VERSIONS, "matplotlib", "test-v2")
    result_2 = await _call(mcp, {"target": "frog.wav"})
    assert result_2[1]["cached"] is False


# ---------------------------------------------------------------------------
# Task 11 — Audition cache user-facing payoff: parameter variation hits cache
# ---------------------------------------------------------------------------


async def test_visualize_param_variation_hits_audition_cache(
    mcp_with_visualize, tmp_path, monkeypatch
):
    """Two visualize() calls on the same .ana target with different
    t_start values. First call: viz miss + audition miss → pvoc synth
    runs. Second call: viz miss (different window) + audition hit →
    pvoc synth MUST NOT run.

    This is the headline payoff of Task 11 — varying parameters on a
    spectral target gets cheap after the first call.
    """
    mcp, sessions, _tracker = mcp_with_visualize
    session, _ = sessions.set_active("s1")

    # The fake_subprocess --write-wav stub emits 200 samples at 44.1kHz
    # (~4.5ms), so t_start values must stay well under that. Both calls
    # produce different windows → different viz cache keys → both viz
    # cache miss; identical .ana bytes → audition cache hits on call 2.
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)

    # First call: cold, pvoc synth runs (no t_start).
    result_1 = await _call(mcp, {"target": "frog.ana"})
    assert result_1[1]["status"] == "ok", result_1[0] if result_1[0].get("errors") else result_1
    assert result_1[1]["auto_synthed"] is True

    # Second call: different window (viz cache miss), but the .ana
    # bytes are identical → audition cache hit. Patch run_cdp_command
    # to fail loudly if invoked.
    from unittest.mock import AsyncMock
    boom = AsyncMock(side_effect=AssertionError(
        "pvoc synth must not run on audition cache hit"
    ))
    monkeypatch.setattr("cdp_mcp.pvoc.run_cdp_command", boom)

    result_2 = await _call(
        mcp, {"target": "frog.ana", "t_start": 0.001, "t_end": 0.004}
    )
    boom.assert_not_called()
    assert isinstance(result_2, list) and len(result_2) == 2, result_2
    envelope_2 = result_2[1]
    assert envelope_2["status"] == "ok", envelope_2
    assert envelope_2["auto_synthed"] is True
    # Viz cache itself missed (different window).
    assert envelope_2["cached"] is False
