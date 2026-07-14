"""Unit tests for cdp_mcp.visualization.render_spectrogram."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

# Importing visualization FIRST locks matplotlib's Agg backend before any
# transitive librosa.display import grabs a different one.
from cdp_mcp.visualization import SpectrogramResult, render_spectrogram

_SR = 22050  # half CD rate — fast tests, still well above frog content


def _write_sine(path: Path, freq: float, seconds: float, channels: int = 1) -> None:
    n = int(_SR * seconds)
    t = np.arange(n) / _SR
    mono = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    if channels == 1:
        sf.write(str(path), mono, _SR)
    else:
        stereo = np.stack([mono] * channels, axis=1)  # samples-first for soundfile
        sf.write(str(path), stereo, _SR)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_mono_440hz_renders(tmp_path):
    audio = tmp_path / "in.wav"
    png = tmp_path / "out.png"
    _write_sine(audio, 440.0, 2.0)
    result = render_spectrogram(audio, png)
    assert isinstance(result, SpectrogramResult)
    assert png.exists()
    assert png.stat().st_size > 10_000  # PNGs of a real spectrogram are well over 10 KB
    # Dimensions in the rough ballpark of 1024×768. The plan's ±10% target
    # was directional — bbox_inches="tight" trims by ~15-20% in practice,
    # and the exact amount varies by matplotlib version. We assert a wider
    # window that still confirms "approximately the intended size, not a
    # thumbnail and not a 4K poster."
    assert 700 <= result.width_px <= 1200
    assert 500 <= result.height_px <= 900
    assert result.sample_rate == _SR
    assert result.n_channels == 1
    assert abs(result.duration_s - 2.0) < 0.01


def test_stereo_renders_with_downmix(tmp_path):
    audio = tmp_path / "stereo.wav"
    png = tmp_path / "stereo.png"
    _write_sine(audio, 440.0, 1.0, channels=2)
    result = render_spectrogram(audio, png)
    assert png.exists()
    assert result.n_channels == 2  # original channel count reported


def test_time_window_renders(tmp_path):
    audio = tmp_path / "in.wav"
    png = tmp_path / "windowed.png"
    _write_sine(audio, 440.0, 2.0)
    result = render_spectrogram(audio, png, t_start=0.5, t_duration=0.5)
    assert png.exists()
    assert abs(result.duration_s - 0.5) < 0.01


def test_silent_audio_does_not_crash(tmp_path):
    audio = tmp_path / "silent.wav"
    png = tmp_path / "silent.png"
    sf.write(str(audio), np.zeros(int(_SR * 2.0), dtype=np.float32), _SR)
    # render shouldn't crash; spectrogram just sits at the dB floor.
    render_spectrogram(audio, png)
    assert png.exists()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_window_past_end_raises(tmp_path):
    audio = tmp_path / "in.wav"
    png = tmp_path / "out.png"
    _write_sine(audio, 440.0, 2.0)
    with pytest.raises(ValueError, match="past file duration|extends past"):
        render_spectrogram(audio, png, t_start=10.0)


def test_negative_start_raises(tmp_path):
    audio = tmp_path / "in.wav"
    png = tmp_path / "out.png"
    _write_sine(audio, 440.0, 2.0)
    with pytest.raises(ValueError, match=">= 0"):
        render_spectrogram(audio, png, t_start=-1.0)


def test_zero_duration_raises(tmp_path):
    audio = tmp_path / "in.wav"
    png = tmp_path / "out.png"
    _write_sine(audio, 440.0, 2.0)
    with pytest.raises(ValueError, match=">"):
        render_spectrogram(audio, png, t_start=0.0, t_duration=0.0)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_spectrogram(tmp_path / "ghost.wav", tmp_path / "out.png")


# ---------------------------------------------------------------------------
# Figure-state hygiene (matplotlib leak guard)
# ---------------------------------------------------------------------------


def test_no_figure_leak_across_calls(tmp_path):
    import matplotlib._pylab_helpers as helpers

    audio = tmp_path / "in.wav"
    _write_sine(audio, 440.0, 0.5)
    before = len(helpers.Gcf.figs)
    for i in range(5):
        render_spectrogram(audio, tmp_path / f"render_{i}.png")
    after = len(helpers.Gcf.figs)
    assert after == before, (
        f"matplotlib leaked {after - before} figure(s); plt.close() not "
        "called somewhere"
    )


# ---------------------------------------------------------------------------
# shrink_png_under_cap (2026-07-14 QA: 1 MB tool-result cap)
# ---------------------------------------------------------------------------


def test_shrink_png_under_cap_reduces_oversized_png(tmp_path):
    """A PNG over the cap is downscaled in place until it fits, keeping
    aspect ratio; an already-small PNG is untouched."""
    import numpy as np
    from PIL import Image as PILImage

    from cdp_mcp.visualization import shrink_png_under_cap

    # Random noise compresses terribly — a 2000×1500 RGB noise PNG is
    # several MB, a reliable over-cap fixture.
    rng = np.random.default_rng(42)
    big = tmp_path / "big.png"
    PILImage.fromarray(
        rng.integers(0, 255, (1500, 2000, 3), dtype=np.uint8)
    ).save(big)
    assert big.stat().st_size > 700_000

    size, shrunk = shrink_png_under_cap(big)
    assert shrunk is True
    assert size <= 700_000
    assert big.stat().st_size == size
    with PILImage.open(big) as im:
        # Aspect preserved (2000:1500 = 4:3) within rounding.
        assert abs(im.width / im.height - 4 / 3) < 0.02
        assert im.width >= 256 and im.height >= 256

    # Small file: untouched.
    small = tmp_path / "small.png"
    PILImage.new("RGB", (100, 80), "white").save(small)
    before = small.stat().st_size
    size, shrunk = shrink_png_under_cap(small)
    assert shrunk is False
    assert size == before
