"""MIR feature scorecard for the ``analyze()`` MCP tool.

Pure-function extraction — no MCP types, no tool registration. The MCP tool
layer (:mod:`cdp_mcp.tools.analyze`) wraps :func:`extract_scorecard` with
target resolution, PVOC auto-synth, and envelope construction.

The scorecard's 10 fields are exactly what the Phase 1a design doc
specifies — no more, no less. Verbose mode (full feature matrices, MFCCs,
chroma, tonnetz) lands in Phase 1b.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln

# Importing visualization here is fine and intentional: it locks
# ``matplotlib.use("Agg")`` in even when analyze() is the first observation
# tool invoked. The transitive librosa.display import won't pin a different
# backend afterwards.
from .visualization import _apply_window


@dataclass
class ScorecardResult:
    """Concise Phase 1a scorecard.

    ``peak_dbfs`` and ``rms_db`` are ``None`` when the signal is digital
    silence (JSON forbids ``-inf``; the convention matches
    :class:`~cdp_mcp.schema.OutputVerification.rms_dbfs`).
    ``lufs_i`` is ``None`` when audio is too short for pyloudnorm's gating
    block (~400 ms); a corresponding warning is recorded.
    """

    duration_s: float
    peak_dbfs: float | None
    rms_db: float | None
    lufs_i: float | None
    spectral_centroid_hz: float
    spectral_flux: float
    zero_crossing_rate: float
    onset_count: int
    n_channels: int
    sample_rate: int
    warnings: list[str] = field(default_factory=list)


def extract_scorecard(
    audio_path: Path,
    t_start: float | None = None,
    t_duration: float | None = None,
) -> ScorecardResult:
    """Compute the 10-field MIR scorecard for ``audio_path``.

    Raises:
        FileNotFoundError: if ``audio_path`` doesn't exist.
        ValueError: if the requested time window is invalid.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    y, sr = librosa.load(str(audio_path), sr=None, mono=False)
    n_channels = 1 if y.ndim == 1 else y.shape[0]
    full_duration_s = float(y.shape[-1] / sr)
    y = _apply_window(y, sr, full_duration_s, t_start, t_duration)
    effective_duration_s = float(y.shape[-1] / sr)

    warnings: list[str] = []

    # Peak / RMS on the original (post-window, multi-channel) signal.
    peak_linear = float(np.max(np.abs(y))) if y.size > 0 else 0.0
    peak_dbfs = 20.0 * np.log10(peak_linear) if peak_linear > 0.0 else None

    rms_linear = float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) if y.size > 0 else 0.0
    rms_db = 20.0 * np.log10(rms_linear) if rms_linear > 0.0 else None

    # LUFS on the original channel layout. pyloudnorm wants samples-first;
    # librosa returns channels-first when multi-channel — transpose.
    lufs_i: float | None
    try:
        meter = pyln.Meter(sr)
        pyln_input = y.T if y.ndim > 1 else y
        lufs_i = float(meter.integrated_loudness(pyln_input))
        # pyloudnorm returns -inf for digital silence; same JSON gotcha.
        if not np.isfinite(lufs_i):
            lufs_i = None
    except ValueError:
        lufs_i = None
        warnings.append("audio too short for LUFS measurement (< 400ms)")

    # Spectral features on a mono downmix. librosa.to_mono expects
    # channels-first input, matching librosa.load's output shape.
    y_mono = librosa.to_mono(y) if y.ndim > 1 else y

    spectral_centroid_hz = float(
        np.mean(librosa.feature.spectral_centroid(y=y_mono, sr=sr))
    )
    # librosa.onset.onset_strength is the spectral-flux-based novelty
    # function — what the design doc means by "spectral_flux".
    spectral_flux = float(
        np.mean(librosa.onset.onset_strength(y=y_mono, sr=sr))
    )
    zero_crossing_rate = float(
        np.mean(librosa.feature.zero_crossing_rate(y_mono))
    )
    onset_count = int(len(librosa.onset.onset_detect(y=y_mono, sr=sr)))

    return ScorecardResult(
        duration_s=effective_duration_s,
        peak_dbfs=peak_dbfs,
        rms_db=rms_db,
        lufs_i=lufs_i,
        spectral_centroid_hz=spectral_centroid_hz,
        spectral_flux=spectral_flux,
        zero_crossing_rate=zero_crossing_rate,
        onset_count=onset_count,
        n_channels=n_channels,
        sample_rate=sr,
        warnings=warnings,
    )
