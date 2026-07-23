"""The ``analyze()`` MCP tool — concise MIR scorecard.

Returns a single envelope dict with a 13-field `analysis` block. Same
target grammar and auto-synth behavior as :func:`visualize`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from ..analysis import extract_scorecard, extract_verbose
from ..cache import analysis_cache_key, cache_lookup, cache_populate_json
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
from ..utils import sha256_file

_SPECTRAL_SUFFIXES = frozenset({".ana", ".pvx"})


async def analyze_impl(
    ctx: Context,
    target: str,
    t_start: float | None = None,
    t_duration: float | None = None,
    timeout_seconds: float = 60.0,
    verbose: bool = False,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> dict:
    """Implementation of ``analyze()``.

    Exposed at module scope so callers can invoke without going through
    the MCP protocol layer. The ``@mcp.tool()`` wrapper inside
    :func:`register` is a thin closure that rebinds the deps from
    server-startup state and delegates here.

    Extracts a concise MIR feature scorecard from the target audio.

    ``target`` accepts a session input filename, a ``<graph_id>:nN``
    reference, or the ``"latest"`` alias. ``.ana`` / ``.pvx`` targets
    are auto-synthesized to a temporary ``.wav`` first.

    Returns an envelope whose ``analysis`` field carries the 13-field
    scorecard: ``duration_s``, ``peak_dbfs``, ``rms_db``, ``lufs_i``,
    ``crest_db``, ``spectral_centroid_hz``, ``spectral_flatness_db``,
    ``spectral_rolloff85_hz``, ``spectral_flux``,
    ``zero_crossing_rate``, ``onset_count``, ``n_channels``,
    ``sample_rate``. Any warnings (e.g. "audio too short for LUFS")
    surface in ``warnings``.
    """
    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _failed_envelope_no_session(latest_tracker, str(e))

    # 2. Resolve target.
    try:
        audio_path = resolve_target(target, session, latest_tracker)
    except ReferenceResolutionError as e:
        return _failed_envelope(
            session,
            latest_tracker,
            [
                ErrorEntry(
                    type="reference_resolution",
                    message=str(e),
                    fix=(
                        "Check the reference: 'latest', "
                        "'<graph_id>:<node_id>', an absolute path, or "
                        "a filename inside the session's inputs/ "
                        "directory."
                    ),
                )
            ],
        )

    # 3. Auto-synth if spectral.
    auto_synthed = False
    if audio_path.suffix.lower() in _SPECTRAL_SUFFIXES:
        cdp = cdp_config_provider()
        if cdp is None:
            return _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="cdp_not_configured",
                        message=(
                            "Cannot auto-synth spectral input — CDP is "
                            "not configured on this server."
                        ),
                        fix=(
                            "Set CDP_PATH and restart the server, or "
                            "pass a .wav target."
                        ),
                    )
                ],
            )
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
            return _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="pvoc_failed",
                        message=str(e),
                        fix=(
                            "Check the input .ana file; if pvoc synth "
                            "fails on a known-good spectral file, this "
                            "is a CDP-side issue, not the tool."
                        ),
                    )
                ],
            )
        auto_synthed = True

    # 4. Validate window (analyze takes t_duration directly).
    if t_start is not None and t_start < 0:
        return _failed_envelope(
            session,
            latest_tracker,
            [
                ErrorEntry(
                    type="invalid_window",
                    message=f"t_start ({t_start}) must be >= 0.",
                    fix="Pass t_start in seconds, non-negative.",
                )
            ],
        )
    if t_duration is not None and t_duration <= 0:
        return _failed_envelope(
            session,
            latest_tracker,
            [
                ErrorEntry(
                    type="invalid_window",
                    message=f"t_duration ({t_duration}) must be > 0.",
                    fix="Pass t_duration in seconds, positive.",
                )
            ],
        )

    # 5. Cache lookup (Task 10). The scorecard JSON is a pure function of
    # (audio bytes, feature_set, window, librosa-stack versions). On hit,
    # we skip the librosa extraction entirely.
    # Hash off the event loop — sha256 of a long wav is exactly the
    # sync CPU work the async commitment says must not starve MCP
    # heartbeats. (Phase 2 hardening, M2.)
    # feature_set "concise_v3" since the sub-register fix scaled the
    # centroid STFT window with sample rate (n_fft 4096 at 96 kHz) —
    # high-rate scorecards change. Old concise_v1/v2 entries orphan
    # harmlessly (never matched, swept by ordinary cache cleanup).
    audio_sha = await asyncio.to_thread(sha256_file, audio_path)
    cache_key = analysis_cache_key(audio_sha, "concise_v3", t_start, t_duration)
    cache = cache_lookup(cache_root, "analysis", cache_key, ".json")

    scorecard_dict: dict | None = None
    warnings: list[str] = []
    cached = False
    if cache.hit:
        try:
            payload = json.loads(cache.path.read_text())
            scorecard_dict = payload["scorecard"]
            warnings = payload.get("warnings", [])
            cached = True
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            # Treat a corrupt or stale-shape cache entry (including a
            # non-dict JSON root — TypeError at the subscript) as a miss.
            cached = False

    # 6. Extract scorecard — off the event loop via asyncio.to_thread,
    # with periodic MCP progress heartbeat so longer files don't trip
    # Claude Desktop's per-tool-call timeout.
    if not cached:
        try:
            scorecard = await run_with_progress(
                ctx,
                "extracting scorecard",
                extract_scorecard,
                audio_path,
                t_start,
                t_duration,
            )
        except FileNotFoundError as e:
            return _failed_envelope(
                session,
                latest_tracker,
                [ErrorEntry(type="audio_not_found", message=str(e), fix=None)],
            )
        except ValueError as e:
            return _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="invalid_window",
                        message=str(e),
                        fix=(
                            "Pass a t_start/t_duration window inside the "
                            "file's duration."
                        ),
                    )
                ],
            )
        except Exception as e:  # noqa: BLE001 — soundfile/librosa raise a zoo
            # sf.LibsndfileError is a RuntimeError subclass; audioread and
            # librosa raise their own types; corrupt/truncated audio must
            # surface as a structured envelope, not a raw protocol error.
            # (Phase 2 hardening, M3.)
            return _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="analysis_failed",
                        message=(
                            f"feature extraction failed on "
                            f"{audio_path.name}: {type(e).__name__}: {e}"
                        ),
                        fix=(
                            "The audio file may be corrupt, truncated, or "
                            "in an unsupported encoding. Re-generate it or "
                            "check it with visualize()/a wav tool."
                        ),
                    )
                ],
            )
        scorecard_dict = asdict(scorecard)
        warnings = scorecard_dict.pop("warnings")
        # Best-effort cache populate. Failure logs a warning and returns
        # False; we still return the freshly computed scorecard.
        cache_populate_json(
            cache.path,
            {"scorecard": scorecard_dict, "warnings": warnings},
        )

    # 6.5. Verbose block (Phase 2, opt-in). Cached separately in the
    # analysis tier — verbose extraction (MFCC/chroma/beat tracking) is
    # several times the cost of the scorecard, and most calls don't
    # want it.
    verbose_block: dict | None = None
    if verbose:
        # feature_set "verbose_v3" since the sub-register fix: the
        # payload gained the sub block + f0_pinned_at_floor, and the
        # trajectory STFT window now scales with sample rate.
        verbose_cache = cache_lookup(
            cache_root, "analysis",
            analysis_cache_key(audio_sha, "verbose_v3", t_start, t_duration),
            ".json",
        )
        if verbose_cache.hit:
            try:
                verbose_block = json.loads(verbose_cache.path.read_text())
            except (OSError, json.JSONDecodeError, TypeError):
                verbose_block = None
        if verbose_block is None:
            try:
                verbose_block = await run_with_progress(
                    ctx, "extracting verbose features", extract_verbose,
                    audio_path, t_start, t_duration,
                )
            except Exception as e:  # noqa: BLE001 — librosa zoo (M3)
                return _failed_envelope(session, latest_tracker, [ErrorEntry(
                    type="analysis_failed",
                    message=(
                        f"verbose feature extraction failed on "
                        f"{audio_path.name}: {type(e).__name__}: {e}"
                    ),
                    fix=(
                        "The concise scorecard may still work — retry "
                        "with verbose=False, or re-generate the audio."
                    ),
                )])
            cache_populate_json(verbose_cache.path, verbose_block)

    # 7. Build envelope. Promote scorecard.warnings to envelope.warnings;
    # the analysis dict carries the 13 numeric fields.
    envelope = ResultEnvelope(
        status="ok",
        output=None,
        stdout="",
        stderr="",
        exit_code=None,
        errors=[],
        warnings=warnings,
        cached=cached,
        duration_ms=None,
        context=build_context_block(session, latest_tracker, active_graph=None),
    )
    envelope_dict = envelope.model_dump(mode="json")
    envelope_dict["analysis"] = scorecard_dict
    if verbose_block is not None:
        envelope_dict["analysis_verbose"] = verbose_block
    envelope_dict["auto_synthed"] = auto_synthed
    return envelope_dict


def register(
    mcp: FastMCP,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``analyze`` tool against ``mcp``.

    Thin wrapper around :func:`analyze_impl`.
    """

    @mcp.tool()
    async def analyze(
        ctx: Context,
        target: str,
        t_start: float | None = None,
        t_duration: float | None = None,
        timeout_seconds: float = 60.0,
        verbose: bool = False,
    ) -> dict:
        """Extract a concise MIR feature scorecard from the target audio.

        ``target`` accepts a session input filename, a ``<graph_id>:nN``
        reference, or the ``"latest"`` alias. ``.ana`` / ``.pvx`` targets
        are auto-synthesized to a temporary ``.wav`` first.

        Returns an envelope whose ``analysis`` field carries the 13-field
        scorecard: ``duration_s``, ``peak_dbfs``, ``rms_db``, ``lufs_i``,
        ``crest_db``, ``spectral_centroid_hz``, ``spectral_flatness_db``,
        ``spectral_rolloff85_hz``, ``spectral_flux``,
        ``zero_crossing_rate``, ``onset_count``, ``n_channels``,
        ``sample_rate``. Any warnings (e.g. "audio too short for LUFS")
        surface in ``warnings``.

        How to read the v2 fields: ``spectral_flatness_db`` near 0 dB
        means noise-like; very negative (below roughly -40 dB) means
        pitched/tonal — it distinguishes "went noisy" from "went
        bright", which centroid/zcr alone cannot. Read it jointly with
        rolloff/centroid: lowpassed noise also scores low.
        ``spectral_rolloff85_hz`` is the spectral edge — 85% of energy
        sits below it — directly actionable when choosing filter bands
        (e.g. where to place a lowpass or a band split). ``crest_db``
        (peak minus RMS) is transient-ness: ~35 dB for a click train,
        ~4-6 dB for a sustained tone; blurring or compression pulls it
        down. Caveat: ``onset_count`` is unreliable on sustained
        material (28 spurious onsets measured on a 3 s steady tone) —
        trust it on percussive material, cross-check crest_db/flux
        elsewhere.

        ``verbose=True`` adds an ``analysis_verbose`` block: MFCC
        means/stds (13 coefficients — timbre), chroma means (12 pitch
        classes — harmonic color), a tempo estimate, per-channel
        peak/RMS, plus the v2 additions — ``trajectory`` (16 points of
        rms_db/centroid_hz/flatness_db across the file: the numeric
        view of temporal evolution — dissolves, glissandi, scrambling
        — that whole-file means cannot see), ``inharmonicity``
        (harmonic-grid deviation: ~0.002 harmonic, ~0.014 bell-like),
        ``roughness`` (20-150 Hz envelope-modulation fraction —
        grain/throb), ``attack_sharpness`` (1.0 = click, ~0.1 = pad),
        ``stereo_width`` (1-|corr(L,R)|: 0 = dual-mono, ~0.4 =
        spatialised; null for mono), and ``f0`` (pyin median_hz /
        range_hz / voiced_fraction). The f0 block is the one expensive
        feature (~2 s of compute per 3 s of audio) and tracks
        *periodicity*, not perceived spectral pitch — waveset-multiplied
        audio keeps its f0 while the perceived pitch rises — so read it
        alongside zcr/centroid, never instead of them.

        Sub-register material (below ~80 Hz): the verbose block adds
        ``sub`` — ``sub_f0_hz`` from a zero-padded rFFT peak-pick
        (~0.05 Hz resolution; trustworthy where pyin octave-folds and
        centroid misreads), plus ``sub_h2_db``/``sub_h3_db``, the
        2nd/3rd-harmonic levels in dB relative to the fundamental
        (even-harmonic material reads h2 > h3; odd-harmonic the
        reverse). ``sub`` is null when less than 5% of spectral energy
        sits in 20-80 Hz. pyin cannot report below 65.4 Hz: when its
        median pins at that floor the f0 block sets
        ``f0_pinned_at_floor: true`` with a note — read
        ``sub.sub_f0_hz`` as the fundamental instead, and
        ``inharmonicity`` is reported null (its 60-450 Hz harmonic
        grid cannot represent a sub fundamental).
        """
        return await analyze_impl(
            ctx,
            target,
            t_start,
            t_duration,
            timeout_seconds,
            verbose,
            sessions=sessions,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )


# ---------------------------------------------------------------------------
# Helpers
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
