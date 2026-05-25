"""Unit tests for cdp_mcp.analysis.extract_scorecard."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

# Same import-order rule as test_visualization: import the analysis (which
# imports visualization) first to pin matplotlib's backend.
from cdp_mcp.analysis import ScorecardResult, extract_scorecard

_SR = 22050


def _write_sine(path: Path, freq: float, seconds: float, channels: int = 1) -> None:
    n = int(_SR * seconds)
    t = np.arange(n) / _SR
    mono = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    if channels == 1:
        sf.write(str(path), mono, _SR)
    else:
        stereo = np.stack([mono] * channels, axis=1)
        sf.write(str(path), stereo, _SR)


def _write_click_train(path: Path, click_times_s: list[float], total_s: float) -> None:
    """Sparse impulse train — short bursts at the requested times."""
    n = int(_SR * total_s)
    y = np.zeros(n, dtype=np.float32)
    for t in click_times_s:
        i = int(t * _SR)
        # Tiny envelope (8 samples) around each impulse — easier for librosa
        # onset detection to pick up than a single nonzero sample.
        for k in range(8):
            if i + k < n:
                y[i + k] = 0.8 * (1.0 - k / 8)  # array is float32; scalar coerces
    sf.write(str(path), y, _SR)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_mono_440_full_scorecard(tmp_path):
    audio = tmp_path / "sine.wav"
    _write_sine(audio, 440.0, 2.0)
    s = extract_scorecard(audio)
    assert isinstance(s, ScorecardResult)
    assert abs(s.duration_s - 2.0) < 0.01
    assert s.n_channels == 1
    assert s.sample_rate == _SR
    # 0.5 amplitude sine → peak -6 dBFS (20*log10(0.5)); RMS -9 dBFS.
    assert s.peak_dbfs is not None and abs(s.peak_dbfs - (-6.02)) < 0.5
    assert s.rms_db is not None and abs(s.rms_db - (-9.03)) < 0.5
    # Spectral centroid for a pure 440 Hz sine is around 440 Hz (±100 Hz
    # tolerance for mel-binning fuzz).
    assert 340 <= s.spectral_centroid_hz <= 540
    # No transients in a pure sine → onset_count should be small.
    assert s.onset_count <= 5
    assert s.warnings == []


def test_stereo_scorecard(tmp_path):
    audio = tmp_path / "stereo.wav"
    _write_sine(audio, 440.0, 1.0, channels=2)
    s = extract_scorecard(audio)
    assert s.n_channels == 2
    # LUFS should compute on stereo (audio is 1s, well above the 0.4s gate).
    assert s.lufs_i is not None


def test_time_window_reflected(tmp_path):
    audio = tmp_path / "sine.wav"
    _write_sine(audio, 440.0, 2.0)
    s = extract_scorecard(audio, t_start=0.5, t_duration=1.0)
    assert abs(s.duration_s - 1.0) < 0.01


def test_silent_audio_handled(tmp_path):
    """Digital silence → peak/RMS are None; LUFS may be None or -inf-equivalent."""
    audio = tmp_path / "silent.wav"
    sf.write(str(audio), np.zeros(int(_SR * 1.0), dtype=np.float32), _SR)
    s = extract_scorecard(audio)
    assert s.peak_dbfs is None
    assert s.rms_db is None
    # lufs_i: pyloudnorm tends to return -inf which we normalize to None.
    # The point: no crash, no non-finite floats in the output.
    assert s.lufs_i is None or np.isfinite(s.lufs_i)


def test_too_short_for_lufs(tmp_path):
    audio = tmp_path / "tiny.wav"
    _write_sine(audio, 440.0, 0.2)  # 200ms — below pyloudnorm's gate
    s = extract_scorecard(audio)
    assert s.lufs_i is None
    assert any("too short" in w.lower() for w in s.warnings)
    # Other fields still populated normally.
    assert s.peak_dbfs is not None
    assert s.duration_s > 0


def test_click_train_detected(tmp_path):
    """A handful of impulses should produce onset detections in the right ballpark."""
    audio = tmp_path / "clicks.wav"
    _write_click_train(audio, click_times_s=[0.2, 0.5, 0.9, 1.3, 1.7], total_s=2.0)
    s = extract_scorecard(audio)
    # librosa onset detection isn't exact; assert a range that comfortably
    # brackets 5 clicks.
    assert 2 <= s.onset_count <= 8


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_window_past_end_raises(tmp_path):
    audio = tmp_path / "sine.wav"
    _write_sine(audio, 440.0, 1.0)
    with pytest.raises(ValueError):
        extract_scorecard(audio, t_start=10.0)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_scorecard(tmp_path / "ghost.wav")
