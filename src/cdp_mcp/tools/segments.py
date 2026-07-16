"""The ``segments()`` MCP tool — temporal segmentation with a marked-up
spectrogram.

Phase 2 observation track. Three methods (onset / novelty / silence, see
:func:`cdp_mcp.analysis.extract_segments`) produce a segment list plus a
mel spectrogram overlaid with boundary markers. Both halves are cached
in the global derivative caches — the segment JSON in the ``analysis``
tier, the marked PNG in the ``visualizations`` tier — since each is a
pure function of (audio bytes, method, library versions).

Phase 6 adds the grid-free ``rhythm`` block
(:func:`cdp_mcp.analysis.extract_rhythm`) — IOI statistics with an
accelerando-detecting slope, plus a 16-point event-density trajectory —
computed from the same detected events and cached in the same payload
(cache key bumped ``v1`` → ``v2`` so stale segment-only entries
regenerate).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP, Image

from ..analysis import extract_segments
from ..cache import (
    analysis_cache_key,
    cache_lookup,
    cache_populate,
    cache_populate_json,
    materialize_cached_artifact,
    visualization_cache_key,
)
from ..config import CDPConfig
from ..graph import (
    LatestTracker,
    ReferenceResolutionError,
    build_context_block,
    resolve_target,
)
from ..progress import run_with_progress
from ..pvoc import PVOCFailedError, synth_for_audition
from ..schema import ErrorEntry, ResultEnvelope
from ..security import SecurityError
from ..session import SessionManager, SessionNotActiveError
from ..utils import sha256_file
from ..visualization import (
    _FIG_DPI,
    _FIG_H_INCHES,
    _FIG_W_INCHES,
    _HOP_LENGTH,
    _N_FFT,
    render_spectrogram,
)
from .visualize import (
    _failed_envelope,
    _failed_envelope_no_session,
    _normalize_target_id,
)

_SPECTRAL_SUFFIXES = frozenset({".ana", ".pvx"})
_VALID_METHODS = ("onset", "novelty", "silence")


async def segments_impl(
    ctx: Context,
    target: str,
    method: str = "onset",
    timeout_seconds: float = 60.0,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> list:
    """Implementation of ``segments()``. Returns ``[Image, envelope]``
    on success, ``[envelope]`` on failure — same contract as
    ``visualize()``."""
    if method not in _VALID_METHODS:
        # Validate before session/target work — cheapest error first.
        try:
            session = sessions.require_active()
        except SessionNotActiveError as e:
            return [_failed_envelope_no_session(latest_tracker, str(e))]
        return [_failed_envelope(session, latest_tracker, [ErrorEntry(
            type="invalid_segmentation_method",
            message=f"method {method!r} is not one of {_VALID_METHODS}.",
            fix="Pass method='onset', 'novelty', or 'silence'.",
        )])]

    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return [_failed_envelope_no_session(latest_tracker, str(e))]

    try:
        audio_path = resolve_target(target, session, latest_tracker)
    except ReferenceResolutionError as e:
        return [_failed_envelope(session, latest_tracker, [ErrorEntry(
            type="reference_resolution",
            message=str(e),
            fix=(
                "Check the reference: 'latest', '<graph_id>:<node_id>', "
                "an absolute path, or a filename inside the session's "
                "inputs/ directory."
            ),
        )])]

    auto_synthed = False
    if audio_path.suffix.lower() in _SPECTRAL_SUFFIXES:
        cdp = cdp_config_provider()
        if cdp is None:
            return [_failed_envelope(session, latest_tracker, [ErrorEntry(
                type="cdp_not_configured",
                message=(
                    "Cannot auto-synth spectral input — CDP is not "
                    "configured on this server."
                ),
                fix=(
                    "Set CDP_PATH and restart the server, or pass a .wav "
                    "target."
                ),
            )])]
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
            return [_failed_envelope(session, latest_tracker, [ErrorEntry(
                type="pvoc_failed",
                message=str(e),
                fix=(
                    "Check the input .ana file; if pvoc synth fails on a "
                    "known-good spectral file, this is a CDP-side issue."
                ),
            )])]
        auto_synthed = True

    # Cache keys — hash off the event loop (M2 discipline). Feature-set
    # v2: the payload gained the Phase 6 `rhythm` block; the bump makes
    # stale v1 (segments-only) entries miss and regenerate.
    audio_sha = await asyncio.to_thread(sha256_file, audio_path)
    seg_cache = cache_lookup(
        cache_root, "analysis",
        analysis_cache_key(audio_sha, f"segments_{method}_v2", None, None),
        ".json",
    )

    segments: list[dict] | None = None
    markers: list[float] = []
    rhythm: dict | None = None
    warnings: list[str] = []
    cached = False
    if seg_cache.hit:
        try:
            payload = json.loads(seg_cache.path.read_text())
            segments = payload["segments"]
            markers = payload["markers"]
            rhythm = payload["rhythm"]
            warnings = payload.get("warnings", [])
            cached = True
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            cached = False

    if not cached:
        try:
            segments, markers, rhythm, warnings = await run_with_progress(
                ctx, f"segmenting ({method})", extract_segments,
                audio_path, method,
            )
        except FileNotFoundError as e:
            return [_failed_envelope(session, latest_tracker, [ErrorEntry(
                type="audio_not_found", message=str(e), fix=None,
            )])]
        except Exception as e:  # noqa: BLE001 — librosa/soundfile zoo (M3)
            return [_failed_envelope(session, latest_tracker, [ErrorEntry(
                type="segmentation_failed",
                message=(
                    f"segmentation failed on {audio_path.name}: "
                    f"{type(e).__name__}: {e}"
                ),
                fix=(
                    "The audio file may be corrupt, truncated, or in an "
                    "unsupported encoding. Re-generate it or check it "
                    "with analyze()."
                ),
            )])]
        cache_populate_json(seg_cache.path, {
            "segments": segments, "markers": markers, "rhythm": rhythm,
            "warnings": warnings,
        })

    # Marked-up spectrogram — viz tier; markers are derived from
    # (audio, method), so the method in the mode string keys them.
    vis_dir = session.root / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]
    png_path = (
        vis_dir
        / f"{_normalize_target_id(target, audio_path)}_segments-{method}_{stamp}.png"
    )
    render_params = (
        f"nfft={_N_FFT},hop={_HOP_LENGTH},dpi={_FIG_DPI},"
        f"w={_FIG_W_INCHES},h={_FIG_H_INCHES},markers=v1"
    )
    png_cache = cache_lookup(
        cache_root, "visualizations",
        visualization_cache_key(
            audio_sha, f"segments_{method}", None, None, render_params,
        ),
        ".png",
    )
    if png_cache.hit:
        try:
            materialize_cached_artifact(png_cache.path, png_path)
        except Exception:  # noqa: BLE001 — cache is never load-bearing
            png_cache = None  # type: ignore[assignment]
    if png_cache is None or not png_cache.hit:
        try:
            await run_with_progress(
                ctx, "rendering marked spectrogram", render_spectrogram,
                audio_path, png_path, None, None, markers,
            )
        except Exception as e:  # noqa: BLE001 (M3)
            return [_failed_envelope(session, latest_tracker, [ErrorEntry(
                type="render_failed",
                message=(
                    f"spectrogram render failed on {audio_path.name}: "
                    f"{type(e).__name__}: {e}"
                ),
                fix="See analyze()/visualize() on this target for detail.",
            )])]
        if png_cache is not None:
            cache_populate(png_cache.path, png_path)

    envelope = ResultEnvelope(
        status="ok",
        output=str(png_path),
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
    envelope_dict["segments"] = segments
    envelope_dict["count"] = len(segments or [])
    envelope_dict["method"] = method
    envelope_dict["rhythm"] = rhythm
    envelope_dict["visualization"] = str(png_path)
    envelope_dict["auto_synthed"] = auto_synthed
    return [Image(path=str(png_path)), envelope_dict]


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``segments`` tool against ``mcp``."""

    @mcp.tool()
    async def segments(
        ctx: Context,
        target: str,
        method: str = "onset",
        timeout_seconds: float = 60.0,
    ) -> list:
        """Segment the target audio and see the boundaries on a spectrogram.

        Use this to understand a sound's temporal structure before
        cutting, looping, or arranging it: where the attacks are
        (``method="onset"``), where the structurally salient changes are
        (``method="novelty"`` — coarser than onset), or which stretches
        are actually sounding (``method="silence"`` — non-silent
        intervals above a -40 dB floor).

        ``target`` accepts a session input filename, a
        ``<graph_id>:<node_id>`` reference, or the ``"latest"`` /
        ``prev_N`` / ``latest_batch[i]`` aliases. ``.ana`` targets are
        auto-synthesized for analysis.

        Returns the marked-up spectrogram image plus an envelope whose
        ``segments`` field lists ``{start, end, label}`` in seconds —
        ready to feed into ``process()`` time parameters or breakpoint
        envelopes.

        The envelope also carries a grid-free ``rhythm`` block computed
        from the same detected events (no beat tracking or tempo
        inference): ``ioi`` holds inter-onset-interval statistics —
        ``count``, ``mean_s``, ``std_s``, ``min_s``, ``max_s``,
        ``slope`` (least-squares IOI change per event: negative =
        speeding up) and ``trend`` (``"accelerando"`` / ``"ritardando"``
        / ``"steady"``; steady means |slope| ≤ 5% of the mean IOI per
        event) — and ``density`` is a 16-point event-count trajectory
        across the file with its window length in ``window_s``. With
        fewer than 2 events the IOI stats are ``None``; ``slope`` and
        ``trend`` need at least 3.
        """
        return await segments_impl(
            ctx,
            target,
            method,
            timeout_seconds,
            sessions=sessions,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )
