"""The ``compare()`` MCP tool — paired spectrograms + feature deltas.

Loudness-matches two targets (so the comparison reads as spectral and
temporal difference, not level difference), renders each matched signal
as a mel spectrogram, stitches the two panels into one composite PNG,
and runs the analyze() scorecard on both matched signals plus a
b-minus-a ``delta`` block.

Panels are stitched with PIL rather than tiled in a single matplotlib
figure: ``bbox_inches="tight"`` garbles grid alignment when tiling axes,
so each panel renders to its own PNG and is stacked with a small gutter.

No caching layer for the composite — the first pass ships uncached (a
compare is two renders plus two scorecards; revisit if it shows up in
profiles).

Targets accepted: session input filenames, ``<graph_id>:nN`` references,
and the ``"latest"`` alias. ``.ana`` / ``.pvx`` targets get
auto-synthesized to a temp wav before comparison (see
:func:`~cdp_mcp.pvoc.synth_for_audition`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from mcp.server.fastmcp import Context, FastMCP, Image
from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

from ..analysis import extract_scorecard
from ..config import CDPConfig
from ..graph import (
    LatestTracker,
    ReferenceResolutionError,
    build_context_block,
    resolve_target,
)
from ..progress import run_with_progress
from ..pvoc import PVOCFailedError, synth_for_audition
from ..schema import ContextBlock, ErrorEntry, ResultEnvelope
from ..security import SecurityError
from ..session import SessionManager, SessionNotActiveError

# Importing visualization here also locks in matplotlib's Agg backend
# before any test or tool imports librosa.display (which transitively
# imports pyplot). visualization.py is the only module in the project
# allowed to import pyplot; this module only touches PIL.
from ..visualization import render_spectrogram
from .visualize import _normalize_target_id

_SPECTRAL_SUFFIXES = frozenset({".ana", ".pvx"})
_LOUDNESS_METHODS = ("lufs_i", "lufs_m", "peak")
_PEAK_TARGET_DBFS = -1.0
_MOMENTARY_WINDOW_S = 0.400
_MOMENTARY_HOP_S = 0.100
_CREST_DELTA_WARN_DB = 12.0
_LABEL_STRIP_PX = 28
_GUTTER_PX = 12


async def compare_impl(
    ctx: Context,
    target_a: str,
    target_b: str,
    loudness_method: str = "lufs_i",
    timeout_seconds: float = 60.0,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> list:
    """Implementation of ``compare()``.

    Exposed at module scope so callers can invoke without going through
    the MCP protocol layer. The ``@mcp.tool()`` wrapper inside
    :func:`register` is a thin closure that rebinds the deps from
    server-startup state and delegates here.

    Loudness-matches the two targets per ``loudness_method``, renders
    both matched signals as mel spectrograms stacked into one composite
    PNG (each panel labeled with its target ref), and runs the
    scorecard extractor on both matched signals.

    Returns a two-element list on success: the composite PNG (inline
    image) plus a metadata envelope dict carrying ``analysis_a``,
    ``analysis_b``, ``delta`` (b minus a), ``loudness_method`` (the
    method actually applied), and the per-target gains. On failure: a
    single-element list with just the envelope.
    """
    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return [_failed_envelope_no_session(latest_tracker, str(e))]

    # 2. Validate loudness_method before touching any audio.
    if loudness_method not in _LOUDNESS_METHODS:
        return [
            _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="invalid_loudness_method",
                        message=(
                            f"Unknown loudness_method {loudness_method!r}."
                        ),
                        fix="Pass one of: 'lufs_i', 'lufs_m', 'peak'.",
                    )
                ],
            )
        ]

    # 3. Resolve both targets; auto-synth spectral inputs.
    paths: dict[str, Path] = {}
    auto_synthed: dict[str, bool] = {}
    for label, target in (("a", target_a), ("b", target_b)):
        try:
            audio_path = resolve_target(target, session, latest_tracker)
        except ReferenceResolutionError as e:
            return [
                _failed_envelope(
                    session,
                    latest_tracker,
                    [
                        ErrorEntry(
                            type="reference_resolution",
                            message=f"target_{label}: {e}",
                            fix=(
                                "Check the reference: 'latest', "
                                "'<graph_id>:<node_id>', an absolute path, "
                                "or a filename inside the session's "
                                "inputs/ directory."
                            ),
                        )
                    ],
                )
            ]
        synthed = False
        if audio_path.suffix.lower() in _SPECTRAL_SUFFIXES:
            cdp = cdp_config_provider()
            if cdp is None:
                return [
                    _failed_envelope(
                        session,
                        latest_tracker,
                        [
                            ErrorEntry(
                                type="cdp_not_configured",
                                message=(
                                    f"Cannot auto-synth spectral target_"
                                    f"{label} — CDP is not configured on "
                                    f"this server."
                                ),
                                fix=(
                                    "Set CDP_PATH and restart the server, "
                                    "or pass a .wav target."
                                ),
                            )
                        ],
                    )
                ]
            try:
                audio_path, _sub = await synth_for_audition(
                    audio_path,
                    session=session,
                    cdp_path=cdp.cdp_path,
                    cache_root=cache_root,
                    cdp_version=cdp.version,
                    timeout_seconds=timeout_seconds,
                    ctx=ctx,
                )
            except (PVOCFailedError, SecurityError) as e:
                return [
                    _failed_envelope(
                        session,
                        latest_tracker,
                        [
                            ErrorEntry(
                                type="pvoc_failed",
                                message=f"target_{label}: {e}",
                                fix=(
                                    "Check the input .ana file; if pvoc "
                                    "synth fails on a known-good spectral "
                                    "file, this is a CDP-side issue, not "
                                    "the tool."
                                ),
                            )
                        ],
                    )
                ]
            synthed = True
        paths[label] = audio_path
        auto_synthed[label] = synthed

    # 4. Composite PNG path — timestamped, in the session's
    # visualizations/ dir, same convention as visualize().
    vis_dir = session.root / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-") + (
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}"
    )
    id_a = _normalize_target_id(target_a, paths["a"])
    id_b = _normalize_target_id(target_b, paths["b"])
    png_path = vis_dir / f"compare_{id_a}_vs_{id_b}_{timestamp}.png"

    # 5. Loudness-match, analyze, render, stitch — all sync CPU work
    # (librosa loads, pyloudnorm, matplotlib, PIL), pushed off the event
    # loop with an MCP progress heartbeat.
    try:
        outcome = await run_with_progress(
            ctx,
            "comparing targets",
            _compare_sync,
            paths["a"],
            paths["b"],
            target_a,
            target_b,
            loudness_method,
            session.tmp_dir,
            png_path,
        )
    except FileNotFoundError as e:
        return [
            _failed_envelope(
                session,
                latest_tracker,
                [ErrorEntry(type="audio_not_found", message=str(e), fix=None)],
            )
        ]
    except Exception as e:  # noqa: BLE001 — soundfile/librosa/pyloudnorm raise a zoo
        # Corrupt/truncated/unsupported audio must surface as a
        # structured envelope, not a raw protocol error. (Phase 2
        # hardening, M3.)
        return [
            _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="compare_failed",
                        message=(
                            f"compare failed on {paths['a'].name} vs "
                            f"{paths['b'].name}: {type(e).__name__}: {e}"
                        ),
                        fix=(
                            "One of the audio files may be corrupt, "
                            "truncated, or in an unsupported encoding. "
                            "Check each side with analyze() or "
                            "visualize()."
                        ),
                    )
                ],
            )
        ]

    # 6. Build envelope. Loudness/gain/scorecard metadata rides in
    # sibling keys the LLM can read alongside the standard envelope.
    envelope = ResultEnvelope(
        status="ok",
        output=str(png_path),
        stdout="",
        stderr="",
        exit_code=None,
        errors=[],
        warnings=outcome.warnings,
        cached=False,
        duration_ms=None,
        context=build_context_block(session, latest_tracker, active_graph=None),
    )
    envelope_dict = envelope.model_dump(mode="json")
    envelope_dict["loudness_method"] = outcome.loudness_method
    envelope_dict["gain_applied_db_a"] = outcome.gain_db_a
    envelope_dict["gain_applied_db_b"] = outcome.gain_db_b
    envelope_dict["analysis_a"] = outcome.analysis_a
    envelope_dict["analysis_b"] = outcome.analysis_b
    envelope_dict["delta"] = outcome.delta
    envelope_dict["width_px"] = outcome.width_px
    envelope_dict["height_px"] = outcome.height_px
    envelope_dict["auto_synthed_a"] = auto_synthed["a"]
    envelope_dict["auto_synthed_b"] = auto_synthed["b"]

    # 7. Two content blocks: image + JSON envelope.
    return [Image(path=str(png_path)), envelope_dict]


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``compare`` tool against ``mcp``.

    Thin wrapper around :func:`compare_impl`.
    """

    @mcp.tool()
    async def compare(
        ctx: Context,
        target_a: str,
        target_b: str,
        loudness_method: str = "lufs_i",
        timeout_seconds: float = 60.0,
    ) -> list:
        """Compare two audio targets: stacked mel spectrograms in one
        composite PNG plus per-target feature scorecards and a b-minus-a
        ``delta`` block.

        ``target_a`` / ``target_b`` accept a session input filename, a
        ``<graph_id>:nN`` reference, or the ``"latest"`` alias. ``.ana``
        / ``.pvx`` targets are auto-synthesized to a temporary ``.wav``
        first.

        Both files are loudness-matched before rendering and analysis so
        the comparison reads as spectral/temporal difference, not level
        difference. ``loudness_method`` picks how:

        - ``"lufs_i"`` (default) — both gain-matched to the *quieter*
          file's integrated LUFS. Preserves dynamic range and never
          amplifies noise; the best general-purpose choice for
          sustained material.
        - ``"lufs_m"`` — matched to the quieter file's maximum momentary
          loudness (400 ms windows). Use for short transients and
          percussive material, where integrated loudness misleads.
        - ``"peak"`` — both peak-normalized to -1 dBFS, ignoring LUFS.
          Use when the targets have very different crest factors (a
          transient train vs a sustained wash); a warning suggests this
          automatically when crest factors differ by more than 12 dB.

        Files too short for LUFS (< 400 ms) fall back to ``"peak"`` with
        a warning. The envelope reports the method actually applied plus
        the per-target gains (``gain_applied_db_a`` /
        ``gain_applied_db_b``).

        Returns a two-element list on success: the composite PNG (inline
        image) plus a metadata envelope dict. On failure: a
        single-element list with just the envelope.
        """
        return await compare_impl(
            ctx,
            target_a,
            target_b,
            loudness_method,
            timeout_seconds,
            sessions=sessions,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )


# ---------------------------------------------------------------------------
# Sync pipeline (runs in a thread via run_with_progress)
# ---------------------------------------------------------------------------


@dataclass
class _CompareOutcome:
    """Everything the envelope needs, computed off the event loop."""

    loudness_method: str  # the method actually applied (post-fallback)
    gain_db_a: float
    gain_db_b: float
    analysis_a: dict
    analysis_b: dict
    delta: dict
    width_px: int
    height_px: int
    warnings: list[str]


def _compare_sync(
    path_a: Path,
    path_b: Path,
    ref_a: str,
    ref_b: str,
    loudness_method: str,
    tmp_dir: Path,
    png_path: Path,
) -> _CompareOutcome:
    """Load → loudness-match → temp wavs → scorecards → panels → stitch.

    The gain-adjusted temp wavs (and per-panel PNGs) are left in the
    session's ``tmp/`` — transients are allowed there and the cleanup
    tool sweeps them.
    """
    for p in (path_a, path_b):
        if not p.exists():
            raise FileNotFoundError(f"Audio file not found: {p}")

    y_a, sr_a = librosa.load(str(path_a), sr=None, mono=False)
    y_b, sr_b = librosa.load(str(path_b), sr=None, mono=False)

    effective, gain_db_a, gain_db_b, warnings = _match_loudness(
        y_a, sr_a, y_b, sr_b, loudness_method
    )

    tmp_dir.mkdir(parents=True, exist_ok=True)
    token = png_path.stem
    matched_a = tmp_dir / f"{token}_a.wav"
    matched_b = tmp_dir / f"{token}_b.wav"
    _write_gain_adjusted(y_a, sr_a, gain_db_a, matched_a)
    _write_gain_adjusted(y_b, sr_b, gain_db_b, matched_b)

    # Scorecards on the gain-adjusted signals; per-side extractor
    # warnings get a target prefix and ride the envelope warnings.
    analysis_a = asdict(extract_scorecard(matched_a))
    analysis_b = asdict(extract_scorecard(matched_b))
    warnings += [f"target_a: {w}" for w in analysis_a.pop("warnings")]
    warnings += [f"target_b: {w}" for w in analysis_b.pop("warnings")]

    delta = {
        key: (
            None
            if analysis_a[key] is None or analysis_b[key] is None
            else analysis_b[key] - analysis_a[key]
        )
        for key in analysis_a
    }

    # Crest-factor sanity check: a transient train and a noise wash can
    # share LUFS-I yet feel wildly different in volume. Crest factor is
    # gain-invariant, so the post-match scorecards are a fine source.
    crest_a = _crest_db(analysis_a)
    crest_b = _crest_db(analysis_b)
    if (
        effective == "lufs_i"
        and crest_a is not None
        and crest_b is not None
        and abs(crest_a - crest_b) > _CREST_DELTA_WARN_DB
    ):
        warnings.append(
            f"crest factors differ by {abs(crest_a - crest_b):.1f} dB "
            f"(a={crest_a:.1f} dB, b={crest_b:.1f} dB); integrated LUFS "
            f"matching can be misleading across such different dynamics "
            f"— consider loudness_method='peak'."
        )

    panel_a = tmp_dir / f"{token}_a.png"
    panel_b = tmp_dir / f"{token}_b.png"
    render_spectrogram(matched_a, panel_a)
    render_spectrogram(matched_b, panel_b)
    label_a = f"A: {ref_a}   [{effective}, gain {gain_db_a:+.1f} dB]"
    label_b = f"B: {ref_b}   [{effective}, gain {gain_db_b:+.1f} dB]"
    width_px, height_px = _stitch_panels(
        panel_a, panel_b, label_a, label_b, png_path
    )

    return _CompareOutcome(
        loudness_method=effective,
        gain_db_a=gain_db_a,
        gain_db_b=gain_db_b,
        analysis_a=analysis_a,
        analysis_b=analysis_b,
        delta=delta,
        width_px=width_px,
        height_px=height_px,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Loudness matching
# ---------------------------------------------------------------------------


def _match_loudness(
    y_a: np.ndarray,
    sr_a: int,
    y_b: np.ndarray,
    sr_b: int,
    method: str,
) -> tuple[str, float, float, list[str]]:
    """Compute per-target gains for the requested matching method.

    Returns ``(effective_method, gain_db_a, gain_db_b, warnings)``.
    LUFS methods match both files to the *quieter* measurement (gains
    are always <= 0), preserving dynamic range and never amplifying
    noise. When LUFS is unmeasurable (audio shorter than the 400 ms
    gating block, or digital silence) the method falls back to
    ``"peak"`` with a warning.
    """
    warnings: list[str] = []
    if method in ("lufs_i", "lufs_m"):
        measure = _integrated_lufs if method == "lufs_i" else _max_momentary_lufs
        try:
            loud_a = measure(y_a, sr_a)
            loud_b = measure(y_b, sr_b)
        except ValueError as e:
            warnings.append(
                f"{method} matching unavailable ({e}); falling back to "
                f"loudness_method='peak'."
            )
        else:
            target = min(loud_a, loud_b)
            return method, target - loud_a, target - loud_b, warnings
    gain_a, warn_a = _peak_gain(y_a, "target_a")
    gain_b, warn_b = _peak_gain(y_b, "target_b")
    warnings += warn_a + warn_b
    return "peak", gain_a, gain_b, warnings


def _integrated_lufs(y: np.ndarray, sr: int) -> float:
    """Integrated LUFS via pyloudnorm.

    pyloudnorm wants samples-first; librosa returns channels-first when
    multi-channel — transpose.

    Raises:
        ValueError: if the audio is shorter than pyloudnorm's ~400 ms
            gating block (pyloudnorm's own error), or is digitally
            silent (-inf is not a usable matching target).
    """
    meter = pyln.Meter(sr)
    value = float(meter.integrated_loudness(y.T if y.ndim > 1 else y))
    if not np.isfinite(value):
        raise ValueError("integrated loudness undefined (digital silence)")
    return value


def _max_momentary_lufs(y: np.ndarray, sr: int) -> float:
    """Approximate maximum momentary loudness (LUFS-M).

    True momentary LUFS (BS.1770) is the ungated K-weighted mean square
    over a sliding 400 ms window. pyloudnorm doesn't expose that
    directly, so we approximate: slice the signal into 400 ms windows on
    a 100 ms hop and run pyloudnorm's ``integrated_loudness`` on each
    window — over a single gating block the measurement is effectively
    ungated, so the max over windows tracks max momentary closely.
    Documented approximation, honest about its provenance.

    Raises:
        ValueError: if the audio is shorter than 400 ms or every window
            measures -inf (digital silence).
    """
    window = int(round(_MOMENTARY_WINDOW_S * sr))
    hop = int(round(_MOMENTARY_HOP_S * sr))
    n_samples = y.shape[-1]
    if n_samples < window:
        raise ValueError("audio too short for momentary loudness (< 400ms)")
    meter = pyln.Meter(sr)
    best = -np.inf
    for start in range(0, n_samples - window + 1, hop):
        chunk = y[..., start : start + window]
        value = meter.integrated_loudness(chunk.T if chunk.ndim > 1 else chunk)
        if np.isfinite(value) and value > best:
            best = value
    if not np.isfinite(best):
        raise ValueError("momentary loudness undefined (digital silence)")
    return float(best)


def _peak_gain(y: np.ndarray, label: str) -> tuple[float, list[str]]:
    """Gain (dB) that normalizes ``y`` to the -1 dBFS peak target."""
    peak = float(np.max(np.abs(y))) if y.size > 0 else 0.0
    if peak <= 0.0:
        return 0.0, [f"{label} is digitally silent; no peak gain applied."]
    return _PEAK_TARGET_DBFS - 20.0 * float(np.log10(peak)), []


def _crest_db(scorecard: dict) -> float | None:
    """Crest factor (peak - RMS, dB) from a scorecard dict, or None."""
    peak, rms = scorecard["peak_dbfs"], scorecard["rms_db"]
    if peak is None or rms is None:
        return None
    return peak - rms


def _write_gain_adjusted(
    y: np.ndarray, sr: int, gain_db: float, out_path: Path
) -> None:
    """Write ``y`` scaled by ``gain_db`` as a float32 wav (lossless)."""
    scaled = (y * (10.0 ** (gain_db / 20.0))).astype(np.float32)
    data = scaled.T if scaled.ndim > 1 else scaled
    sf.write(str(out_path), data, sr, subtype="FLOAT")


# ---------------------------------------------------------------------------
# PIL composite
# ---------------------------------------------------------------------------


def _stitch_panels(
    panel_a: Path,
    panel_b: Path,
    label_a: str,
    label_b: str,
    out_path: Path,
) -> tuple[int, int]:
    """Stack two panel PNGs vertically with label strips and a gutter.

    Returns the composite ``(width_px, height_px)``.
    """
    with PILImage.open(panel_a) as im_a, PILImage.open(panel_b) as im_b:
        width = max(im_a.width, im_b.width)
        height = 2 * _LABEL_STRIP_PX + im_a.height + im_b.height + _GUTTER_PX
        canvas = PILImage.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        y = 0
        for im, label in ((im_a, label_a), (im_b, label_b)):
            draw.text((8, y + 8), label, fill="black", font=font)
            canvas.paste(im.convert("RGB"), (0, y + _LABEL_STRIP_PX))
            y += _LABEL_STRIP_PX + im.height + _GUTTER_PX
        canvas.save(out_path)
        return canvas.size


# ---------------------------------------------------------------------------
# Failure envelopes
# ---------------------------------------------------------------------------


def _failed_envelope_no_session(latest_tracker: LatestTracker, message: str) -> dict:
    return ResultEnvelope(
        status="failed",
        output=None,
        stdout="",
        stderr="",
        exit_code=None,
        errors=[
            ErrorEntry(
                type="no_active_session",
                message=message,
                fix="Call set_session('<name>') first.",
            )
        ],
        warnings=[],
        cached=False,
        duration_ms=None,
        context=ContextBlock(
            active_graph=None,
            latest=latest_tracker.latest,
            recent_graphs=[],
            available_sources=[],
        ),
    ).model_dump(mode="json")


def _failed_envelope(
    session,
    latest_tracker: LatestTracker,
    errors: list[ErrorEntry],
) -> dict:
    return ResultEnvelope(
        status="failed",
        output=None,
        stdout="",
        stderr="",
        exit_code=None,
        errors=errors,
        warnings=[],
        cached=False,
        duration_ms=None,
        context=build_context_block(session, latest_tracker, active_graph=None),
    ).model_dump(mode="json")
