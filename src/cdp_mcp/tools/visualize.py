"""The ``visualize()`` MCP tool — mel-spectrogram of any target audio.

Returns a two-content-block response: the rendered PNG (inline image in
chat) plus a JSON envelope with metadata (path on disk, dimensions,
auto-synth flag, context block). On failure: a single envelope, no image.

Targets accepted: session input filenames, ``<graph_id>:nN`` references,
and the ``"latest"`` alias. ``.ana`` / ``.pvx`` targets get
auto-synthesized to a temp wav before rendering (see
:func:`~cdp_mcp.pvoc.synth_for_audition`).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP, Image

from ..cache import (
    cache_lookup,
    cache_populate,
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

# Importing visualization here also locks in matplotlib's Agg backend
# before any test or tool imports librosa.display (which transitively
# imports pyplot).
from ..progress import run_with_progress
from ..pvoc import PVOCFailedError, synth_for_audition
from ..schema import ContextBlock, ErrorEntry, ResultEnvelope
from ..security import SecurityError
from ..session import SessionManager, SessionNotActiveError
from ..utils import sha256_file
from ..visualization import (
    _FIG_DPI,
    _FIG_H_INCHES,
    _FIG_W_INCHES,
    _HOP_LENGTH,
    _N_FFT,
    audio_metadata_for_cached_png,
    render_spectrogram,
)

_SPECTRAL_SUFFIXES = frozenset({".ana", ".pvx"})


async def visualize_impl(
    ctx: Context,
    target: str,
    t_start: float | None = None,
    t_end: float | None = None,
    timeout_seconds: float = 60.0,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> list:
    """Implementation of ``visualize()``.

    Exposed at module scope so callers can invoke without going through
    the MCP protocol layer. The ``@mcp.tool()`` wrapper inside
    :func:`register` is a thin closure that rebinds the deps from
    server-startup state and delegates here.

    Renders a mel spectrogram of the target audio.

    ``target`` accepts a session input filename, a ``<graph_id>:nN``
    reference, or the ``"latest"`` alias. ``.ana`` / ``.pvx`` targets
    are auto-synthesized to a temporary ``.wav`` for rendering.

    ``t_start`` / ``t_end`` are an optional time window in seconds.
    Both ``None`` means full file.

    Returns a two-element list on success: the rendered PNG (inline
    image) plus a metadata envelope dict. On failure: a single-element
    list with just the envelope.
    """
    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return [_failed_envelope_no_session(latest_tracker, str(e))]

    # 2. Resolve target.
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
                        message=str(e),
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

    # 3. Auto-synth if spectral.
    auto_synthed = False
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
                                "Cannot auto-synth spectral input — CDP "
                                "is not configured on this server."
                            ),
                            fix=(
                                "Set CDP_PATH and restart the server, or "
                                "pass a .wav target."
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
                            message=str(e),
                            fix=(
                                "Check the input .ana file; if pvoc synth "
                                "fails on a known-good spectral file, "
                                "this is a CDP-side issue, not the tool."
                            ),
                        )
                    ],
                )
            ]
        auto_synthed = True

    # 4. Translate (t_start, t_end) → (t_start, t_duration).
    t_duration: float | None
    if t_end is None:
        t_duration = None
    else:
        t_start_effective = 0.0 if t_start is None else float(t_start)
        t_duration = float(t_end) - t_start_effective
        t_start = t_start_effective
        if t_duration <= 0:
            return [
                _failed_envelope(
                    session,
                    latest_tracker,
                    [
                        ErrorEntry(
                            type="invalid_window",
                            message=(
                                f"t_end ({t_end}) must be greater than "
                                f"t_start ({t_start})."
                            ),
                            fix="Pass t_end > t_start (both in seconds).",
                        )
                    ],
                )
            ]

    # 5. PNG path.
    vis_dir = session.root / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-") + (
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}"
    )
    png_path = vis_dir / f"{_normalize_target_id(target, audio_path)}_{timestamp}.png"

    # 6. Cache lookup (Task 10). The rendered PNG is a pure function of
    # (audio bytes, mode, window, render params, librosa+mpl versions).
    # On hit, materialize the cached PNG into the session's
    # visualizations/ dir (timestamped path the LLM expects) and
    # populate metadata from soundfile + PIL — no librosa load needed.
    audio_sha = sha256_file(audio_path)
    render_params = (
        f"nfft={_N_FFT},hop={_HOP_LENGTH},dpi={_FIG_DPI},"
        f"w={_FIG_W_INCHES},h={_FIG_H_INCHES}"
    )
    cache_key = visualization_cache_key(
        audio_sha, "mel", t_start, t_duration, render_params,
    )
    cache = cache_lookup(cache_root, "visualizations", cache_key, ".png")

    cached = False
    spec_result = None
    if cache.hit:
        try:
            materialize_cached_artifact(cache.path, png_path)
            spec_result = audio_metadata_for_cached_png(
                audio_path, png_path, t_start, t_duration,
            )
            cached = True
        except (OSError, ValueError):
            # Cache file unreadable or corrupt — treat as miss.
            cached = False

    # 7. Render — off the event loop via asyncio.to_thread, with
    # periodic MCP progress heartbeat so Claude Desktop doesn't time
    # out long renders.
    if not cached:
        try:
            spec_result = await run_with_progress(
                ctx,
                "rendering spectrogram",
                render_spectrogram,
                audio_path,
                png_path,
                t_start,
                t_duration,
            )
        except FileNotFoundError as e:
            return [
                _failed_envelope(
                    session,
                    latest_tracker,
                    [
                        ErrorEntry(
                            type="audio_not_found",
                            message=str(e),
                            fix=None,
                        )
                    ],
                )
            ]
        except ValueError as e:
            return [
                _failed_envelope(
                    session,
                    latest_tracker,
                    [
                        ErrorEntry(
                            type="invalid_window",
                            message=str(e),
                            fix=(
                                "Pass a t_start/t_end window inside the "
                                "file's duration."
                            ),
                        )
                    ],
                )
            ]
        # Best-effort cache populate. Failure logs a warning; the freshly
        # rendered PNG in vis_dir is still returned.
        cache_populate(cache.path, png_path)

    # 8. Build envelope. Extra rendering metadata goes into the warnings
    # field's adjacent location: we tuck it into a sibling key the LLM
    # can read.
    envelope = ResultEnvelope(
        status="ok",
        output=str(png_path),
        stdout="",
        stderr="",
        exit_code=None,
        errors=[],
        warnings=[],
        cached=cached,
        duration_ms=None,
        context=build_context_block(session, latest_tracker, active_graph=None),
    )
    envelope_dict = envelope.model_dump(mode="json")
    envelope_dict["width_px"] = spec_result.width_px
    envelope_dict["height_px"] = spec_result.height_px
    envelope_dict["audio_duration_s"] = spec_result.duration_s
    envelope_dict["sample_rate"] = spec_result.sample_rate
    envelope_dict["n_channels"] = spec_result.n_channels
    envelope_dict["auto_synthed"] = auto_synthed

    # 9. Two content blocks: image + JSON envelope.
    return [Image(path=str(png_path)), envelope_dict]


def register(
    mcp: FastMCP,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``visualize`` tool against ``mcp``.

    Thin wrapper around :func:`visualize_impl`.
    """

    @mcp.tool()
    async def visualize(
        ctx: Context,
        target: str,
        t_start: float | None = None,
        t_end: float | None = None,
        timeout_seconds: float = 60.0,
    ) -> list:
        """Render a mel spectrogram of the target audio.

        ``target`` accepts a session input filename, a ``<graph_id>:nN``
        reference, or the ``"latest"`` alias. ``.ana`` / ``.pvx`` targets
        are auto-synthesized to a temporary ``.wav`` for rendering.

        ``t_start`` / ``t_end`` are an optional time window in seconds.
        Both ``None`` means full file.

        Returns a two-element list on success: the rendered PNG (inline
        image) plus a metadata envelope dict. On failure: a single-element
        list with just the envelope.
        """
        return await visualize_impl(
            ctx,
            target,
            t_start,
            t_end,
            timeout_seconds,
            sessions=sessions,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_target_id(target: str, resolved_path: Path) -> str:
    """Turn a target ref into a filesystem-safe filename stem.

    - ``"<graph_id>:<node_id>"`` → ``"<graph_id>_<node_id>"``
    - ``"latest"`` → the resolved path's stem (gives stable names for
      repeated visualize(latest) calls)
    - otherwise → ``Path(target).stem`` (strips dirs + extension)
    """
    if ":" in target and not Path(target).is_absolute():
        graph_id, _, node_id = target.partition(":")
        return f"{graph_id}_{node_id}"
    if target == "latest":
        return resolved_path.stem
    return Path(target).stem


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
