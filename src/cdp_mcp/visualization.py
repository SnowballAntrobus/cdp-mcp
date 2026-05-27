"""Mel-spectrogram rendering for the ``visualize()`` MCP tool.

Pure-function rendering — no MCP types, no tool registration, just numpy /
librosa / matplotlib in and a PNG out. The MCP tool layer (:mod:`cdp_mcp.tools.visualize`)
wraps :func:`render_spectrogram` with target resolution, PVOC auto-synth,
and envelope construction.

**Order-sensitive import**: ``matplotlib.use("Agg")`` must be called before
any ``matplotlib.pyplot`` import anywhere in the import graph. To make that
robust this module sets the backend at the very top and is the only place
in the project that imports pyplot. Any other module that needs charts
should import this one (or a helper from it).
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — must precede pyplot import

from dataclasses import dataclass
from pathlib import Path

import librosa
import librosa.display
import matplotlib.pyplot as plt  # noqa: E402 — backend already locked above
import numpy as np
import soundfile as sf
from PIL import Image as PILImage

_FIG_W_INCHES = 10.24
_FIG_H_INCHES = 7.68
_FIG_DPI = 100  # 1024×768 before bbox_inches="tight" trim
_N_FFT = 2048
_HOP_LENGTH = 512
_WINDOW = "hann"
_CMAP = "magma"
_DB_VMIN = -90.0
_DB_VMAX = 0.0


@dataclass
class SpectrogramResult:
    """What :func:`render_spectrogram` returns alongside the on-disk PNG."""

    output_path: Path
    width_px: int
    height_px: int
    duration_s: float
    sample_rate: int
    n_channels: int


def render_spectrogram(
    audio_path: Path,
    output_path: Path,
    t_start: float | None = None,
    t_duration: float | None = None,
) -> SpectrogramResult:
    """Render a mel spectrogram PNG to ``output_path``.

    Phase 1a defaults are locked: mel scale, magma colormap, 1024×768
    (±10% after ``bbox_inches="tight"`` trim), dB range [-90, 0], 2048 FFT,
    512 hop, Hann window. No user overrides.

    Args:
        audio_path: Input wav (or anything libsndfile can read).
        output_path: PNG destination. Parent directory must exist.
        t_start: Optional time-window start in seconds.
        t_duration: Optional time-window duration in seconds.

    Raises:
        FileNotFoundError: if ``audio_path`` doesn't exist.
        ValueError: if the requested window is invalid or outside file
            duration.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # librosa.load returns channels-first for multi-channel: (n_channels, n_samples).
    # Mono returns 1D: (n_samples,). sr=None preserves the file's native rate.
    y, sr = librosa.load(str(audio_path), sr=None, mono=False)
    n_channels = 1 if y.ndim == 1 else y.shape[0]
    duration_s = float(y.shape[-1] / sr)

    y = _apply_window(y, sr, duration_s, t_start, t_duration)

    # Downmix for the spectrogram itself. librosa.to_mono expects channels-first.
    y_mono = librosa.to_mono(y) if y.ndim > 1 else y

    mel = librosa.feature.melspectrogram(
        y=y_mono, sr=sr, n_fft=_N_FFT, hop_length=_HOP_LENGTH, window=_WINDOW
    )
    mel_db = librosa.power_to_db(mel, ref=np.max)

    fig, ax = plt.subplots(figsize=(_FIG_W_INCHES, _FIG_H_INCHES), dpi=_FIG_DPI)
    try:
        img = librosa.display.specshow(
            mel_db,
            sr=sr,
            hop_length=_HOP_LENGTH,
            x_axis="time",
            y_axis="mel",
            cmap=_CMAP,
            vmin=_DB_VMIN,
            vmax=_DB_VMAX,
            ax=ax,
        )
        fig.colorbar(img, ax=ax, format="%+2.0f dB")
        ax.set_title(f"{audio_path.name} — mel spectrogram")
        fig.savefig(output_path, dpi=_FIG_DPI, bbox_inches="tight")
    finally:
        # MANDATORY: matplotlib retains figure references in module-global
        # state until close(). Without this the server leaks figures across
        # repeated visualize() calls and eventually exhausts memory.
        plt.close(fig)

    with PILImage.open(output_path) as im:
        width_px, height_px = im.size

    # Effective duration is the post-window length.
    effective_duration = float(y.shape[-1] / sr) if y.ndim > 0 else duration_s

    return SpectrogramResult(
        output_path=output_path,
        width_px=width_px,
        height_px=height_px,
        duration_s=effective_duration,
        sample_rate=sr,
        n_channels=n_channels,
    )


# ---------------------------------------------------------------------------
# Cache-hit metadata helper
# ---------------------------------------------------------------------------


def audio_metadata_for_cached_png(
    audio_path: Path,
    png_path: Path,
    t_start: float | None,
    t_duration: float | None,
) -> SpectrogramResult:
    """Build a :class:`SpectrogramResult` for a PNG served from cache.

    The PNG already exists on disk; we just need to populate the
    envelope's audio + image metadata fields the same way the live
    render path does. Image dimensions are read from the PNG itself
    (cheap PIL call); audio metadata comes from ``soundfile.info`` to
    avoid loading the whole audio array.

    Used by :mod:`cdp_mcp.tools.visualize` on a visualization cache
    hit. ``audio_path`` is the post-auto-synth audio file (always a
    .wav by the time we get here).
    """
    info = sf.info(str(audio_path))
    full_duration = float(info.duration)
    if t_start is None and t_duration is None:
        effective_duration = full_duration
    else:
        start = 0.0 if t_start is None else float(t_start)
        if t_duration is None:
            effective_duration = max(0.0, full_duration - start)
        else:
            effective_duration = float(t_duration)
    with PILImage.open(png_path) as im:
        width_px, height_px = im.size
    return SpectrogramResult(
        output_path=png_path,
        width_px=width_px,
        height_px=height_px,
        duration_s=effective_duration,
        sample_rate=int(info.samplerate),
        n_channels=int(info.channels),
    )


# ---------------------------------------------------------------------------
# Shared windowing helper (consumed by visualization + analysis)
# ---------------------------------------------------------------------------


def _apply_window(
    y: np.ndarray,
    sr: int,
    duration_s: float,
    t_start: float | None,
    t_duration: float | None,
) -> np.ndarray:
    """Validate and slice a time window in sample space.

    Used by both :func:`render_spectrogram` and
    :func:`cdp_mcp.analysis.extract_scorecard`. Keeping this here (and
    re-exported by analysis.py) avoids a second module just for windowing.
    """
    if t_start is None and t_duration is None:
        return y
    start = 0.0 if t_start is None else float(t_start)
    if start < 0:
        raise ValueError(f"t_start={start} must be >= 0")
    if start > duration_s:
        raise ValueError(
            f"t_start={start} is past file duration {duration_s:.3f}s"
        )
    if t_duration is None:
        end_sample = y.shape[-1]
    else:
        duration = float(t_duration)
        if duration <= 0:
            raise ValueError(f"t_duration={duration} must be > 0")
        if start + duration > duration_s:
            raise ValueError(
                f"window [{start}, {start + duration}] extends past file "
                f"duration {duration_s:.3f}s"
            )
        end_sample = int(round((start + duration) * sr))
    start_sample = int(round(start * sr))
    # Channels-first or mono — slice the last axis either way.
    return y[..., start_sample:end_sample]
