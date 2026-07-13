"""MIR feature scorecard for the ``analyze()`` MCP tool.

Pure-function extraction — no MCP types, no tool registration. The MCP tool
layer (:mod:`cdp_mcp.tools.analyze`) wraps :func:`extract_scorecard` with
target resolution, PVOC auto-synth, and envelope construction.

The scorecard surfaces a curated 10-field summary of the audio: the
basic level/dynamics metrics (duration, peak, RMS, LUFS), three
spectral descriptors (centroid, flux, zero-crossing rate), onset
count, channel count, and sample rate. Verbose feature matrices
(MFCCs, chroma, tonnetz, full STFT) aren't currently exposed — a
future expansion could add them as an opt-in mode.
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
    # function — the librosa-side analogue of "spectral_flux" in the
    # scorecard.
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


# ---------------------------------------------------------------------------
# Segmentation (Phase 2 — segments() tool)
# ---------------------------------------------------------------------------

# Boundaries closer than this are collapsed (mirrors the breakpoint
# compiler's dedup instinct; sub-millisecond segments are render noise).
_SEGMENT_DEDUP_S = 1e-3


def extract_segments(
    audio_path: Path,
    method: str,
) -> tuple[list[dict], list[float], list[str]]:
    """Segment the audio by ``method``; pure function, no caching.

    Returns ``(segments, markers, warnings)``:

    - ``segments`` — ``[{"start": s, "end": e, "label": "<method>_<i>"},
      …]`` covering the full duration for onset/novelty; only the
      non-silent stretches for silence.
    - ``markers`` — the interior boundary times, for the spectrogram
      overlay.
    - ``warnings`` — non-fatal notes (e.g. "no onsets detected").

    Methods:

    - ``"onset"`` — spectral-flux onset events
      (``librosa.onset.onset_detect``): boundaries at attack transients.
    - ``"novelty"`` — peaks in the onset-strength envelope via
      ``librosa.util.peak_pick`` with a coarser window than onset
      detection: fewer, structurally-salient boundaries.
    - ``"silence"`` — non-silent intervals (``librosa.effects.split``,
      top_db=40): each interval is one segment; gaps are silence.

    Raises whatever librosa/soundfile raise on unreadable audio — the
    tool layer converts to structured envelopes.
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    duration_s = float(len(y) / sr)
    warnings: list[str] = []

    if method == "silence":
        intervals = librosa.effects.split(y, top_db=40)
        segments = [
            {
                "start": round(float(s / sr), 6),
                "end": round(float(e / sr), 6),
                "label": f"silence_{i}",
            }
            for i, (s, e) in enumerate(intervals)
        ]
        if not segments:
            warnings.append("entire file is below the -40 dB silence floor.")
        markers = sorted({p for seg in segments for p in (seg["start"], seg["end"])})
        markers = [m for m in markers if 0.0 < m < duration_s]
        return segments, markers, warnings

    if method == "onset":
        times = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    elif method == "novelty":
        env = librosa.onset.onset_strength(y=y, sr=sr)
        # Coarser peak-picking than onset_detect: ~0.3 s context windows
        # so only structurally salient flux peaks survive.
        frames = librosa.util.peak_pick(
            env,
            pre_max=int(0.15 * sr / 512) or 1,
            post_max=int(0.15 * sr / 512) or 1,
            pre_avg=int(0.3 * sr / 512) or 1,
            post_avg=int(0.3 * sr / 512) or 1,
            delta=float(np.median(env) if env.size else 0.0),
            wait=int(0.3 * sr / 512) or 1,
        )
        times = librosa.frames_to_time(frames, sr=sr, hop_length=512)
    else:  # pragma: no cover — the tool layer validates method first
        raise ValueError(f"unknown segmentation method {method!r}")

    boundaries: list[float] = [0.0]
    for t in sorted(float(t) for t in times):
        if t - boundaries[-1] >= _SEGMENT_DEDUP_S and t < duration_s:
            boundaries.append(t)
    if duration_s - boundaries[-1] >= _SEGMENT_DEDUP_S:
        boundaries.append(duration_s)
    else:
        boundaries[-1] = duration_s

    if len(boundaries) < 2:
        warnings.append(f"no {method} boundaries detected; one segment spans the file.")
        boundaries = [0.0, duration_s]
    segments = [
        {
            "start": round(boundaries[i], 6),
            "end": round(boundaries[i + 1], 6),
            "label": f"{method}_{i}",
        }
        for i in range(len(boundaries) - 1)
    ]
    markers = [round(b, 6) for b in boundaries[1:-1]]
    return segments, markers, warnings


# ---------------------------------------------------------------------------
# Verbose feature block (Phase 2 — analyze(verbose=True))
# ---------------------------------------------------------------------------


def extract_verbose(
    audio_path: Path,
    t_start: float | None = None,
    t_duration: float | None = None,
) -> dict:
    """Opt-in verbose feature block for ``analyze(verbose=True)``.

    Design doc v9 sketched "per-frame matrices"; what ships is summary
    statistics over those matrices — MFCC means/stds (13 coefficients),
    chroma means (12 pitch classes), a tempo estimate, and per-channel
    level metrics. Raw per-frame matrices are thousands of floats that
    would flood an LLM context window for no interpretive gain; the
    stats carry the same timbral/harmonic signal at ~40 numbers. (If a
    future consumer needs the matrices, add a file-output mode rather
    than inlining them.)
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=False)
    n_channels = 1 if y.ndim == 1 else y.shape[0]
    duration_s = float(y.shape[-1] / sr)
    y = _apply_window(y, sr, duration_s, t_start, t_duration)
    y_mono = librosa.to_mono(y) if y.ndim > 1 else y

    mfcc = librosa.feature.mfcc(y=y_mono, sr=sr, n_mfcc=13)
    chroma = librosa.feature.chroma_stft(y=y_mono, sr=sr)
    tempo_bpm: float | None
    try:
        tempo, _ = librosa.beat.beat_track(y=y_mono, sr=sr)
        tempo_bpm = round(float(np.atleast_1d(tempo)[0]), 2) or None
    except Exception:  # noqa: BLE001 — beat tracking fails on odd material
        tempo_bpm = None

    def _channel_levels(ch: np.ndarray) -> dict:
        peak = float(np.max(np.abs(ch))) if ch.size else 0.0
        rms = float(np.sqrt(np.mean(ch**2))) if ch.size else 0.0
        return {
            "peak_dbfs": round(20 * np.log10(peak), 2) if peak > 0 else None,
            "rms_db": round(20 * np.log10(rms), 2) if rms > 0 else None,
        }

    channels = (
        [_channel_levels(y)] if y.ndim == 1
        else [_channel_levels(y[c]) for c in range(y.shape[0])]
    )
    return {
        "mfcc_mean": [round(float(v), 4) for v in mfcc.mean(axis=1)],
        "mfcc_std": [round(float(v), 4) for v in mfcc.std(axis=1)],
        "chroma_mean": [round(float(v), 4) for v in chroma.mean(axis=1)],
        "tempo_bpm": tempo_bpm,
        "n_channels": n_channels,
        "per_channel": channels,
    }
