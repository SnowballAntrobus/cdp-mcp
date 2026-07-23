"""MIR feature scorecard for the ``analyze()`` MCP tool.

Pure-function extraction — no MCP types, no tool registration. The MCP tool
layer (:mod:`cdp_mcp.tools.analyze`) wraps :func:`extract_scorecard` with
target resolution, PVOC auto-synth, and envelope construction.

The scorecard surfaces a curated 13-field summary of the audio: the
level/dynamics metrics (duration, peak, RMS, LUFS, crest factor),
five spectral descriptors (centroid, flatness in dB, rolloff-85,
flux, zero-crossing rate), onset count, channel count, and sample
rate. :func:`extract_verbose` adds the opt-in block (MFCC/chroma
stats, tempo, per-channel levels, and the MIR v2 additions: a
16-point trajectory, inharmonicity, roughness, attack sharpness,
stereo width, a pyin f0 block, and a sub-register ``sub`` block —
the <80 Hz fundamental + harmonic-dialect fix). Field choices are
empirical — see ``docs/mir-gap-analysis.md`` for the measured
discrimination tests behind each addition.
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
    """Concise scorecard (Phase 1a core + MIR v2 additions).

    ``peak_dbfs`` and ``rms_db`` are ``None`` when the signal is digital
    silence (JSON forbids ``-inf``; the convention matches
    :class:`~cdp_mcp.schema.OutputVerification.rms_dbfs`).
    ``lufs_i`` is ``None`` when audio is too short for pyloudnorm's gating
    block (~400 ms); a corresponding warning is recorded.
    ``crest_db`` (peak minus RMS — transient-ness) is ``None`` whenever
    either operand is. ``spectral_flatness_db`` is the mean flatness in
    dB (``10*log10``), floored at -120 dB so pure tones and silence stay
    JSON-finite: near 0 dB reads noise-like, very negative reads
    pitched/tonal. ``spectral_rolloff85_hz`` is the frequency below
    which 85% of spectral energy sits — the actionable spectral edge.
    """

    duration_s: float
    peak_dbfs: float | None
    rms_db: float | None
    lufs_i: float | None
    crest_db: float | None
    spectral_centroid_hz: float
    spectral_flatness_db: float
    spectral_rolloff85_hz: float
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
    """Compute the 13-field MIR scorecard for ``audio_path``.

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

    # n_fft scaled with sr (sub-register fix): librosa's default 2048
    # holds a ~46 ms window only at 44.1 kHz; at 96 kHz it is 46.9
    # Hz/bin — too coarse below ~47 Hz. See _n_fft_for_sr.
    spectral_centroid_hz = float(
        np.mean(
            librosa.feature.spectral_centroid(y=y_mono, sr=sr, n_fft=_n_fft_for_sr(sr))
        )
    )
    # Mean flatness in dB (MIR v2): raw flatness spans 1e-9 (pure tone)
    # to ~0.9 (white noise) — dB reads better and avoids "0.0" rounding.
    # Floored at -120 dB (gap analysis §4.1).
    spectral_flatness_db = _power_db(
        float(np.mean(librosa.feature.spectral_flatness(y=y_mono)))
    )
    spectral_rolloff85_hz = float(
        np.mean(librosa.feature.spectral_rolloff(y=y_mono, sr=sr, roll_percent=0.85))
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

    # Crest factor is free — both operands are already computed. Same
    # derivation compare() has always used privately (_crest_db).
    crest_db = (
        peak_dbfs - rms_db
        if peak_dbfs is not None and rms_db is not None
        else None
    )

    return ScorecardResult(
        duration_s=effective_duration_s,
        peak_dbfs=peak_dbfs,
        rms_db=rms_db,
        lufs_i=lufs_i,
        crest_db=crest_db,
        spectral_centroid_hz=spectral_centroid_hz,
        spectral_flatness_db=spectral_flatness_db,
        spectral_rolloff85_hz=spectral_rolloff85_hz,
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

# Grid-free rhythm analysis (Phase 6): event-density trajectory bins the
# detected events into 16 equal-width windows — the same 16-point
# compromise as _TRAJECTORY_POINTS, but binning *events* rather than
# STFT frames, so it never degrades to fewer points.
_DENSITY_POINTS = 16

# IOI trend threshold: |least-squares slope| relative to the mean IOI.
# The slope's units are seconds per event index; dividing by the mean
# IOI reads as "fractional IOI change per event". Onset-frame
# quantization jitter (hop 512 ≈ 23 ms at 22.05 kHz) averages out in the
# fit to well under 1% per event on a steady train, while a
# bouncing-ball geometric shrink of ratio r changes the IOI by
# |r − 1| ≈ 10-25% per event — 5% splits the two with a wide margin.
_IOI_TREND_THRESHOLD = 0.05


def extract_rhythm(
    event_times: list[float] | np.ndarray,
    duration_s: float,
) -> dict:
    """Grid-free rhythm block from detected event times; pure numpy.

    NO grid detection — no beat tracking, no meter induction, no tempo
    curve (the Phase 6 detection-vs-construction ruling). Two views of
    the raw event timing:

    - ``ioi`` — inter-onset-interval statistics: ``count`` (number of
      intervals, ``onset_count − 1`` floored at 0), ``mean_s`` /
      ``std_s`` (population) / ``min_s`` / ``max_s``, ``slope`` (the
      least-squares slope of IOI vs event index, in seconds per event —
      the accelerando detector), and ``trend``: ``"accelerando"`` when
      ``slope < −0.05 × mean_s``, ``"ritardando"`` when
      ``slope > +0.05 × mean_s``, ``"steady"`` within that band (see
      ``_IOI_TREND_THRESHOLD``).
    - ``density`` — event counts in ``_DENSITY_POINTS`` equal-width
      windows spanning ``[0, duration_s]``; ``window_s`` reports the
      normalized window length ``duration_s / points``.

    Degenerate cases are explicit, never a crash: with 0 or 1 events
    every ``ioi`` statistic is ``None`` (``count`` 0); with exactly 2
    events (one interval) ``mean_s``/``min_s``/``max_s`` equal that
    interval and ``std_s`` is 0.0, but ``slope``/``trend`` stay ``None``
    (a line through one point is indeterminate). A non-positive
    ``duration_s`` yields an empty density block (``points`` 0,
    ``window_s`` ``None``).
    """
    events = np.sort(np.asarray(event_times, dtype=np.float64).ravel())
    n = int(events.size)

    ioi: dict = {
        "count": max(n - 1, 0),
        "mean_s": None,
        "std_s": None,
        "min_s": None,
        "max_s": None,
        "slope": None,
        "trend": None,
    }
    if n >= 2:
        iois = np.diff(events)
        mean = float(iois.mean())
        ioi["mean_s"] = round(mean, 6)
        ioi["std_s"] = round(float(iois.std()), 6)
        ioi["min_s"] = round(float(iois.min()), 6)
        ioi["max_s"] = round(float(iois.max()), 6)
        if iois.size >= 2:
            slope = float(
                np.polyfit(np.arange(iois.size, dtype=np.float64), iois, 1)[0]
            )
            ioi["slope"] = round(slope, 6)
            if abs(slope) <= _IOI_TREND_THRESHOLD * mean:
                ioi["trend"] = "steady"
            elif slope < 0.0:
                ioi["trend"] = "accelerando"
            else:
                ioi["trend"] = "ritardando"

    if duration_s > 0.0:
        counts, _edges = np.histogram(
            events, bins=_DENSITY_POINTS, range=(0.0, duration_s)
        )
        density = {
            "points": _DENSITY_POINTS,
            "window_s": round(duration_s / _DENSITY_POINTS, 6),
            "counts": [int(c) for c in counts],
        }
    else:
        density = {"points": 0, "window_s": None, "counts": []}

    return {"onset_count": n, "ioi": ioi, "density": density}


def extract_segments(
    audio_path: Path,
    method: str,
) -> tuple[list[dict], list[float], dict, list[str]]:
    """Segment the audio by ``method``; pure function, no caching.

    Returns ``(segments, markers, rhythm, warnings)``:

    - ``segments`` — ``[{"start": s, "end": e, "label": "<method>_<i>"},
      …]`` covering the full duration for onset/novelty; only the
      non-silent stretches for silence.
    - ``markers`` — the interior boundary times, for the spectrogram
      overlay.
    - ``rhythm`` — the grid-free rhythm block
      (:func:`extract_rhythm`) computed from the method's raw event
      times: the detected onset/novelty times, or the non-silent
      interval starts for silence.
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
        # Each non-silent island's start is one event.
        rhythm = extract_rhythm([seg["start"] for seg in segments], duration_s)
        return segments, markers, rhythm, warnings

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

    # Rhythm works on the RAW detected event times — before the boundary
    # dedup below, which exists only to keep the segment tiling sane.
    event_times = sorted(float(t) for t in times)
    rhythm = extract_rhythm(event_times, duration_s)

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
    return segments, markers, rhythm, warnings


# ---------------------------------------------------------------------------
# MIR v2 feature math (2026-07 gap analysis — docs/mir-gap-analysis.md)
# ---------------------------------------------------------------------------

# dB floor for flatness / trajectory RMS: keeps pure tones (flatness
# ~1e-9) and digital silence JSON-finite instead of -inf.
_DB_FLOOR = -120.0

# Trajectory: 16 equal-width points normally; short files degrade to
# fewer, but never below 4 while at least 4 STFT frames exist.
_TRAJECTORY_POINTS = 16
_TRAJECTORY_MIN_POINTS = 4

# Inharmonicity: top-12 spectral peaks vs a harmonic grid whose f0 is
# grid-searched over 60-450 Hz (gap analysis §3.0/§3.b).
_INHARM_PEAKS = 12
_INHARM_F0_MIN_HZ = 60.0
_INHARM_F0_MAX_HZ = 450.0
_INHARM_F0_STEP_HZ = 0.25

# Roughness proxy: RMS envelope at a fixed 689 Hz frame rate — the gap
# analysis's "hop 64" is that rate's 44.1 kHz realization (frame_length
# 4×hop = 256 there). Holding the RATE constant (not the hop) keeps the
# proxy sample-rate-invariant: the short-window RMS ripple of a pitched
# signal aliases against the frame rate, and at 689 Hz a 220 Hz tone's
# 440 Hz ripple lands at 249 Hz — outside the band — at any input sr.
_ENV_MOD_FRAME_RATE_HZ = 689.0
_ENV_MOD_BAND_HZ = (20.0, 150.0)

# pyin search range: C2..C7 — librosa's canonical bounds, wide enough
# for every CDP register claim in the curated corpus.
_PYIN_FMIN_HZ = 65.4
_PYIN_FMAX_HZ = 2093.0

# Pinned-floor detector (sub-register fix, 2026-07): pyin cannot report
# below fmin, so on sub material it pins its median AT the floor rather
# than failing loudly — measured voiced_fraction 1.0, median exactly
# 65.4 on a 36.7 Hz (D1) sine at 96 kHz. A voiced median within 2% of
# the floor is that failure mode, not a real C2. Deliberately a
# detector, NOT a lower fmin: lowering fmin would silently change every
# existing f0 result across the corpus.
_PYIN_PIN_REL_TOL = 0.02

# Rate-invariant STFT window (sub-register fix, 2026-07): librosa's
# default n_fft=2048 holds a ~46 ms window only at 44.1 kHz; at 96 kHz
# the same 2048 samples span 21 ms → 46.9 Hz/bin, which cannot resolve
# anything below ~47 Hz — HIGHER sample rates get WORSE low-frequency
# resolution. Hold the window DURATION constant instead (the same
# rate-invariance philosophy as _ENV_MOD_FRAME_RATE_HZ above), rounded
# to the nearest power of two and never below the 44.1 kHz default:
# 2048 at 22.05/44.1/48 kHz, 4096 at 88.2/96 kHz, 8192 at 192 kHz.
_STFT_WINDOW_S = 2048.0 / 44100.0  # ≈ 46.4 ms


def _n_fft_for_sr(sr: int) -> int:
    """Power-of-two ``n_fft`` holding a ~46 ms analysis window at any sr."""
    return max(2048, int(2 ** round(np.log2(_STFT_WINDOW_S * float(sr)))))


# Sub-register block (sub-register fix, 2026-07): reported when at
# least 5% (_SUB_MIN_ENERGY_FRACTION — the documented relative
# threshold) of the analysis window's non-DC spectral energy sits in
# the 20-80 Hz band. The fundamental comes from a zero-padded rFFT
# peak-pick (pad to ≤0.05 Hz bin spacing — the resolution the 96 kHz
# field container validated against D1/F1/A1 sub renders) refined by
# parabolic interpolation; h2/h3 are read at 2×/3× the found
# fundamental (±2% search window) in dB relative to the fundamental's
# magnitude — the even-vs-odd harmonic-dialect axis. The FFT stays
# bounded on long files: at most _SUB_WINDOW_MAX_S seconds around the
# RMS-envelope energy peak are analyzed.
_SUB_BAND_MIN_HZ = 20.0
_SUB_BAND_MAX_HZ = 80.0
_SUB_MIN_ENERGY_FRACTION = 0.05
_SUB_RESOLUTION_HZ = 0.05
_SUB_WINDOW_MAX_S = 4.0
_SUB_HARMONIC_TOL_REL = 0.02


def _power_db(value: float, floor: float = _DB_FLOOR) -> float:
    """``10*log10(value)`` floored — for power-like quantities (flatness)."""
    if value <= 0.0:
        return floor
    return max(10.0 * float(np.log10(value)), floor)


def _amp_db(value: float, floor: float = _DB_FLOOR) -> float:
    """``20*log10(value)`` floored — for amplitude-like quantities (RMS)."""
    if value <= 0.0:
        return floor
    return max(20.0 * float(np.log10(value)), floor)


def trajectory_frames(
    y_mono: np.ndarray,
    sr: int,
    points: int = _TRAJECTORY_POINTS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Equal-width trajectory: ``(rms_db, centroid_hz, flatness_db)`` arrays.

    One shared STFT; the per-frame RMS / centroid / flatness series are
    split into ``points`` near-equal-width bins (``np.array_split``) and
    averaged per bin (linear mean, then dB where applicable, floored at
    -120 dB). Short files degrade gracefully: fewer than ``points``
    frames yields one point per frame, never fewer than
    ``_TRAJECTORY_MIN_POINTS`` when that many frames exist. Empty input
    yields three empty arrays.

    This is the D7 (temporal evolution) fix from the gap analysis §3.f:
    whole-file means are permutation-invariant, so ordered and scrambled
    material are indistinguishable without the time axis. Shared by
    :func:`extract_verbose` (the ``trajectory`` block) and ``cluster()``
    (centroid total variation, RMS range) — one frame math, two
    consumers.
    """
    if y_mono.size == 0:
        empty = np.array([], dtype=np.float64)
        return empty.copy(), empty.copy(), empty.copy()

    # n_fft scaled with sr (sub-register fix): hold the ~46 ms window
    # so low-frequency resolution is rate-invariant — see _n_fft_for_sr.
    n_fft = _n_fft_for_sr(sr)
    S = np.abs(librosa.stft(y_mono, n_fft=n_fft))
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    flatness = librosa.feature.spectral_flatness(S=S)[0]
    rms = librosa.feature.rms(S=S, frame_length=n_fft)[0]

    n_frames = int(centroid.shape[0])
    if n_frames >= _TRAJECTORY_MIN_POINTS:
        n_points = min(points, n_frames)
    else:
        n_points = n_frames

    rms_db = np.array(
        [_amp_db(float(chunk.mean())) for chunk in np.array_split(rms, n_points)]
    )
    centroid_hz = np.array(
        [float(chunk.mean()) for chunk in np.array_split(centroid, n_points)]
    )
    flatness_db = np.array(
        [_power_db(float(chunk.mean())) for chunk in np.array_split(flatness, n_points)]
    )
    return rms_db, centroid_hz, flatness_db


def _inharmonicity(y_mono: np.ndarray, sr: int) -> float | None:
    """Harmonic-grid deviation — the D6 axis (gap analysis §3.b).

    Mean relative deviation of the top-12 peaks of the mean magnitude
    spectrum from a best-fit harmonic grid, with the grid's f0 searched
    over 60-450 Hz. Peak frequencies are refined by parabolic
    interpolation on the log-magnitude spectrum (bin quantization alone
    would swamp the measure). ~0.002 for harmonic material; ×7.2 on
    ``stretch spectrum`` output where partials leave the harmonic
    series. ``None`` when fewer than 2 usable peaks exist (silence,
    near-DC-only content).
    """
    if y_mono.size == 0:
        return None
    spec = np.abs(librosa.stft(y_mono)).mean(axis=1)
    if spec.size < 3 or not np.any(spec > 0.0):
        return None
    hz_per_bin = sr / (2.0 * (spec.size - 1))

    interior = spec[1:-1]
    is_peak = (interior > spec[:-2]) & (interior >= spec[2:])
    peak_bins = np.nonzero(is_peak)[0] + 1
    # Drop peaks below the f0 search floor — the grid cannot explain
    # them and real material there is usually DC leakage / rumble.
    peak_bins = peak_bins[peak_bins * hz_per_bin >= _INHARM_F0_MIN_HZ]
    if peak_bins.size < 2:
        return None
    strongest = peak_bins[np.argsort(spec[peak_bins])[::-1][:_INHARM_PEAKS]]

    # Parabolic (quadratic) interpolation around each peak bin.
    log_spec = np.log(spec + 1e-12)
    alpha = log_spec[strongest - 1]
    beta = log_spec[strongest]
    gamma = log_spec[strongest + 1]
    denom = alpha - 2.0 * beta + gamma
    offset = np.where(np.abs(denom) > 1e-12, 0.5 * (alpha - gamma) / denom, 0.0)
    peak_hz = (strongest + offset) * hz_per_bin

    f0_grid = np.arange(_INHARM_F0_MIN_HZ, _INHARM_F0_MAX_HZ + 1e-9, _INHARM_F0_STEP_HZ)
    harmonic_n = np.clip(np.round(peak_hz[None, :] / f0_grid[:, None]), 1.0, None)
    deviation = np.abs(peak_hz[None, :] - harmonic_n * f0_grid[:, None]) / peak_hz[None, :]
    return float(deviation.mean(axis=1).min())


def _roughness(y_mono: np.ndarray, sr: int) -> float | None:
    """Envelope-modulation proxy — the D3/D10 axis (gap analysis §3.c).

    Fraction of the RMS-envelope AC-spectrum energy that falls in the
    20-150 Hz roughness/grain band; envelope at a fixed 689 Hz frame
    rate (hop 64 / frame 256 at 44.1 kHz — see the constant note).
    ÷141 when ``blur blur`` dissolves a click train; ×61 when ``focus
    exag`` roughens a tone. ``None`` when the signal is too short to
    frame; 0.0 for a static (or silent) envelope.
    """
    hop = max(1, round(sr / _ENV_MOD_FRAME_RATE_HZ))
    frame = 4 * hop
    if y_mono.size < frame:
        return None
    env = librosa.feature.rms(y=y_mono, frame_length=frame, hop_length=hop)[0]
    env = env - env.mean()
    power = np.abs(np.fft.rfft(env)) ** 2
    total = float(power[1:].sum())  # AC only — skip the DC bin
    if total <= 0.0:
        return 0.0
    freqs = np.fft.rfftfreq(env.size, d=hop / sr)
    lo, hi = _ENV_MOD_BAND_HZ
    band = float(power[(freqs >= lo) & (freqs <= hi)].sum())
    return band / total


def _attack_sharpness(y_mono: np.ndarray) -> float | None:
    """Peak positive first-difference of the RMS envelope, normalised.

    Normalised by the envelope maximum: 1.0 means silence-to-peak
    within one hop (a click train); ~0.1 means gradual swells. The D4
    axis where centroid/zcr actively mislead (gap analysis §3.c:
    1.00 → 0.087 across ``blur blur 50``). ``None`` for silent or
    sub-two-frame signals.
    """
    if y_mono.size == 0:
        return None
    env = librosa.feature.rms(y=y_mono)[0]
    peak = float(env.max()) if env.size else 0.0
    if env.size < 2 or peak <= 0.0:
        return None
    return max(0.0, float(np.max(np.diff(env)) / peak))


def _stereo_width(y: np.ndarray) -> float | None:
    """``1 - |corr(L, R)|`` — the D9 axis (gap analysis §3.g).

    0.0 for a dual-mono bounce, 0.40 measured on ``texture simple``'s
    spatialised cloud. ``None`` for anything but 2-channel input, and
    for degenerate channels (silence — correlation undefined).
    """
    if y.ndim != 2 or y.shape[0] != 2 or y.shape[1] < 2:
        return None
    left = y[0].astype(np.float64)
    right = y[1].astype(np.float64)
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return None
    corr = float(np.corrcoef(left, right)[0, 1])
    return 1.0 - abs(corr)


def _sub_block(y_mono: np.ndarray, sr: int) -> dict | None:
    """Sub-register fundamental block — the <80 Hz fix (2026-07).

    Zero-padded rFFT peak-pick over the 20-80 Hz band, the measurement
    that read 14 field renders of D1/F1/A1 (36.7/43.7/55.0 Hz)
    correctly where pyin octave-folded and centroid misread. Returns
    ``{"sub_f0_hz", "sub_h2_db", "sub_h3_db"}`` — the harmonic levels
    (dB re: the fundamental's magnitude) carry the musical even-vs-odd
    dialect distinction: even-harmonic synths read ``sub_h2_db >
    sub_h3_db``, odd-harmonic synths the reverse.

    ``None`` when less than 5% of the (Hann-windowed, non-DC) spectral
    energy sits in the band — mid/high-register material, silence,
    empty input. Constants and thresholds documented at
    ``_SUB_BAND_MIN_HZ`` above.
    """
    if y_mono.size == 0:
        return None
    # Bound the analysis window on long files so the zero-padded FFT
    # cost never scales with duration: take _SUB_WINDOW_MAX_S seconds
    # centered on the RMS-envelope energy peak.
    max_n = int(_SUB_WINDOW_MAX_S * sr)
    if y_mono.size > max_n:
        env = librosa.feature.rms(y=y_mono, frame_length=2048, hop_length=1024)[0]
        center = int(np.argmax(env)) * 1024
        start = min(max(center - max_n // 2, 0), y_mono.size - max_n)
        seg = y_mono[start : start + max_n]
    else:
        seg = y_mono
    seg = seg.astype(np.float64) * np.hanning(seg.size)
    # Pad to ≤_SUB_RESOLUTION_HZ bin spacing (0.05 Hz — ~2^21 at 96 kHz).
    n_pad = 1 << int(np.ceil(np.log2(max(sr / _SUB_RESOLUTION_HZ, float(seg.size)))))
    mag = np.abs(np.fft.rfft(seg, n=n_pad))
    freqs = np.fft.rfftfreq(n_pad, d=1.0 / sr)
    power = mag**2
    total = float(power[1:].sum())  # AC only — a DC offset is not music
    if total <= 0.0:
        return None
    in_band = (freqs >= _SUB_BAND_MIN_HZ) & (freqs < _SUB_BAND_MAX_HZ)
    if not np.any(in_band):
        return None
    if float(power[in_band].sum()) / total < _SUB_MIN_ENERGY_FRACTION:
        return None

    # Peak-pick in band; parabolic refinement on the log-magnitude
    # spectrum (same move as _inharmonicity). The band starts above bin
    # 0 and ends far below Nyquist, so k-1 / k+1 always exist.
    band_bins = np.nonzero(in_band)[0]
    k = int(band_bins[np.argmax(mag[band_bins])])
    log_mag = np.log(mag + 1e-12)
    alpha, beta, gamma = log_mag[k - 1], log_mag[k], log_mag[k + 1]
    denom = alpha - 2.0 * beta + gamma
    offset = 0.5 * (alpha - gamma) / denom if abs(denom) > 1e-12 else 0.0
    sub_f0_hz = (k + offset) * sr / n_pad
    fund_mag = float(mag[k])

    def _harmonic_db(mult: float) -> float:
        target = mult * sub_f0_hz
        if target >= sr / 2.0 or fund_mag <= 0.0:
            return _DB_FLOOR
        half = max(0.5, _SUB_HARMONIC_TOL_REL * target)
        window = (freqs >= target - half) & (freqs <= target + half)
        h_mag = float(mag[window].max()) if np.any(window) else 0.0
        return _amp_db(h_mag / fund_mag)

    return {
        "sub_f0_hz": round(float(sub_f0_hz), 2),
        "sub_h2_db": round(_harmonic_db(2.0), 2),
        "sub_h3_db": round(_harmonic_db(3.0), 2),
    }


def _f0_block(y_mono: np.ndarray, sr: int) -> dict:
    """pyin f0 block — THE expensive verbose feature (~2 s per 3 s file).

    Everything else in the verbose block is O(ms); pyin runs at roughly
    0.75× realtime, which is why f0 lives in verbose and not the
    always-on scorecard (gap analysis §4.2).

    Honest caveat (measured, §3.d): pyin tracks *periodicity*, NOT
    perceived spectral pitch. ``distort multiply`` N=2/4/8 leaves the
    waveform 220 Hz-periodic at every N — f0_median stays 220.1 Hz
    while the perceived pitch rises with N. Read f0 alongside
    zero_crossing_rate / centroid, never instead of them.

    ``range_hz`` is the robust p05-p95 spread of voiced frames. All
    three fields degrade to ``None`` / 0.0 when pyin finds nothing to
    track (noise, clicks, silence).

    ``f0_pinned_at_floor`` (sub-register fix, 2026-07): True when the
    voiced median lands within 2% of the 65.4 Hz search floor — pyin
    cannot report lower, so on sub material it pins there instead of
    failing (measured: median exactly 65.4 on a 36.7 Hz sine at
    96 kHz). When pinned, a plain-language ``note`` points at the
    ``sub`` block, which measures the true fundamental.
    """
    unvoiced = {
        "median_hz": None,
        "range_hz": None,
        "voiced_fraction": 0.0,
        "f0_pinned_at_floor": False,
    }
    if y_mono.size == 0:
        return unvoiced
    try:
        f0, voiced_flag, _voiced_prob = librosa.pyin(
            y_mono, fmin=_PYIN_FMIN_HZ, fmax=_PYIN_FMAX_HZ, sr=sr
        )
    except Exception:  # noqa: BLE001 — pyin fails on degenerate material
        return unvoiced
    if f0 is None or f0.size == 0:
        return unvoiced
    voiced = np.asarray(voiced_flag, dtype=bool) & np.isfinite(f0)
    voiced_fraction = float(np.mean(voiced))
    if not np.any(voiced):
        return unvoiced
    tracked = f0[voiced]
    p05, p95 = np.percentile(tracked, [5.0, 95.0])
    median_hz = float(np.median(tracked))
    pinned = median_hz <= _PYIN_FMIN_HZ * (1.0 + _PYIN_PIN_REL_TOL)
    block = {
        "median_hz": round(median_hz, 2),
        "range_hz": round(float(p95 - p05), 2),
        "voiced_fraction": round(voiced_fraction, 3),
        "f0_pinned_at_floor": pinned,
    }
    if pinned:
        block["note"] = (
            f"f0 median sits at pyin's {_PYIN_FMIN_HZ:g} Hz search floor — "
            "the material likely lies below it (pyin cannot report lower); "
            "consult the sub block for the true fundamental."
        )
    return block


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

    MIR v2 additions (all empirically motivated —
    ``docs/mir-gap-analysis.md``), additive to the v1 keys:

    - ``trajectory`` — ``{"points", "rms_db", "centroid_hz",
      "flatness_db"}``: 16 equal-width points across the (windowed)
      signal, 2 dp. The 48-number time axis that whole-file means
      cannot see (D7/D8: dissolves, glissandi, scrambling, decays).
      The deliberate compromise between static means and full frame
      matrices — same reasoning as above.
    - ``inharmonicity`` — harmonic-grid deviation (D6); ~0.002
      harmonic, ~0.014 bell-like stretched spectra.
    - ``roughness`` — 20-150 Hz envelope-modulation fraction (D3/D10
      grain/throb proxy).
    - ``attack_sharpness`` — normalised peak RMS-envelope rise (D4);
      1.0 = click, ~0.1 = pad.
    - ``stereo_width`` — ``1 - |corr(L, R)|`` (D9); ``None`` for mono.
    - ``f0`` — pyin ``median_hz`` / ``range_hz`` / ``voiced_fraction``
      / ``f0_pinned_at_floor``. The ONE expensive feature (~0.75×
      realtime — ~2 s of compute on a 3 s file; everything else here
      is O(ms)). pyin tracks periodicity, not perceived spectral pitch
      — see :func:`_f0_block` for the measured ``distort multiply``
      caveat and the pinned-floor detector.
    - ``sub`` — sub-register block (2026-07 fix): ``sub_f0_hz`` /
      ``sub_h2_db`` / ``sub_h3_db`` when ≥5% of spectral energy sits
      in 20-80 Hz; ``None`` otherwise. See :func:`_sub_block`.

    Inharmonicity guard (2026-07 fix): when the material's fundamental
    sits below the harmonic grid's 60 Hz search floor — the ``sub``
    block found one there, or pyin pinned at its own floor — the
    ``inharmonicity`` value is unreliable (the grid fits overtones of
    a fundamental it cannot represent) and is reported ``None``, the
    block's existing degenerate-case convention.
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

    # MIR v2 additions. Cheap block first (O(ms)), pyin last (~0.75×
    # realtime — the one expensive feature; see _f0_block).
    rms_traj, centroid_traj, flatness_traj = trajectory_frames(y_mono, sr)
    trajectory = {
        "points": int(rms_traj.size),
        "rms_db": [round(float(v), 2) for v in rms_traj],
        "centroid_hz": [round(float(v), 2) for v in centroid_traj],
        "flatness_db": [round(float(v), 2) for v in flatness_traj],
    }
    inharmonicity = _inharmonicity(y_mono, sr)
    roughness = _roughness(y_mono, sr)
    attack = _attack_sharpness(y_mono)
    width = _stereo_width(y)
    sub = _sub_block(y_mono, sr)
    f0_info = _f0_block(y_mono, sr)

    # Inharmonicity guard (sub-register fix): the grid's f0 search
    # starts at _INHARM_F0_MIN_HZ — when the actual fundamental sits
    # below it (sub block found one, or pyin pinned at its floor), the
    # grid is fitting overtones of a fundamental it cannot represent.
    # Same treatment as the block's other degenerate cases: None.
    if inharmonicity is not None and (
        (sub is not None and sub["sub_f0_hz"] < _INHARM_F0_MIN_HZ)
        or f0_info["f0_pinned_at_floor"]
    ):
        inharmonicity = None

    return {
        "mfcc_mean": [round(float(v), 4) for v in mfcc.mean(axis=1)],
        "mfcc_std": [round(float(v), 4) for v in mfcc.std(axis=1)],
        "chroma_mean": [round(float(v), 4) for v in chroma.mean(axis=1)],
        "tempo_bpm": tempo_bpm,
        "n_channels": n_channels,
        "per_channel": channels,
        "trajectory": trajectory,
        "inharmonicity": round(inharmonicity, 4) if inharmonicity is not None else None,
        "roughness": round(roughness, 4) if roughness is not None else None,
        "attack_sharpness": round(attack, 4) if attack is not None else None,
        "stereo_width": round(width, 4) if width is not None else None,
        "sub": sub,
        "f0": f0_info,
    }
