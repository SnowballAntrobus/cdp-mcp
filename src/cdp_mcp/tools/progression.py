"""The ``progression()`` MCP tool — stacked spectrograms of a processing chain.

Returns a two-content-block response: a vertical composite PNG (one
spectrogram panel per target, top to bottom, in the order given) plus a
JSON envelope with metadata. On failure: a single envelope, no image.

The composite is assembled with PIL, **not** a matplotlib grid —
``bbox_inches="tight"`` trims each axes unpredictably, which garbles
grid alignment when tiling. Each panel is a colormapped mel matrix
rendered at a fixed horizontal scale (``_PX_PER_S`` pixels per second,
capped at ``_PANEL_MAX_W``), so a 1 s croak and a 30 s blur read at
their true relative lengths instead of being squished into equal boxes.

``targets`` is either a list of target refs (same grammar as
``visualize()``: filenames, ``<graph_id>:nN``, ``"latest"`` and friends,
with ``.ana`` / ``.pvx`` auto-synth) or a single string naming a graph
id, in which case every completed node in that graph is rendered in
node-id order.

**No caching for the composite** — this first pass ships uncached. A
composite cache key would have to hash every target plus the layout
params, and the per-panel mel render is cheap next to CDP processing;
deferred until usage data justifies it. (``.ana`` auto-synth still hits
the audition cache inside :func:`~cdp_mcp.pvoc.synth_for_audition`.)
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import librosa
import numpy as np
from matplotlib import colormaps
from mcp.server.fastmcp import Context, FastMCP, Image
from PIL import Image as PILImage
from PIL import ImageDraw

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
from ..session import Session, SessionManager, SessionNotActiveError

# Importing visualization locks in matplotlib's Agg backend before
# anything in the import graph pulls in pyplot, and keeps the mel render
# parameters identical to visualize()'s.
from ..visualization import _CMAP, _DB_VMAX, _DB_VMIN, _HOP_LENGTH, _N_FFT, _WINDOW

_SPECTRAL_SUFFIXES = frozenset({".ana", ".pvx"})

# Layout. All panels share one horizontal scale (_PX_PER_S) so relative
# durations stay legible; the composite canvas is _PANEL_MAX_W wide with
# panels left-aligned on it. Tests compute expected composite dimensions
# from these constants — change them together.
_PANEL_MAX_W = 1024  # composite width; spectrogram strips never exceed it
_PX_PER_S = 100  # horizontal scale — pixels per second of audio
_SPEC_H = 192  # spectrogram strip height per panel
_LABEL_H = 24  # label strip above each spectrogram
_GUTTER_PX = 20  # vertical gap between panels
_PANEL_CAP = 8  # max spectrogram panels per composite
_OMITTED_PANEL_H = 48  # height of the text-only "N more nodes omitted" panel


async def progression_impl(
    ctx: Context,
    targets: list[str] | str,
    timeout_seconds: float = 60.0,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> list:
    """Implementation of ``progression()``.

    Exposed at module scope so callers can invoke without going through
    the MCP protocol layer. The ``@mcp.tool()`` wrapper inside
    :func:`register` is a thin closure that rebinds the deps from
    server-startup state and delegates here.

    Renders stacked spectrograms of the targets into one composite PNG.

    ``targets`` is either a list of target refs (each accepting the same
    grammar as ``visualize()``) or a single string naming a graph id —
    that graph's completed nodes render in node-id order (``n1``,
    ``n2``, … ``n9``, ``n10``; label ids sort lexicographically after).

    At most ``_PANEL_CAP`` panels render; longer lists truncate to the
    first ``_PANEL_CAP`` plus a text-only summary panel, with the
    truncation recorded in the envelope's ``warnings``.

    Returns a two-element list on success: the composite PNG (inline
    image) plus a metadata envelope dict carrying ``panel_count``,
    ``truncated``, and ``targets_rendered``. On failure: a
    single-element list with just the envelope.
    """
    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return [_failed_envelope_no_session(latest_tracker, str(e))]

    # 2. Expand the graph-id form into per-node refs; a list passes
    # through unchanged.
    if isinstance(targets, str):
        try:
            refs = _expand_graph_targets(targets, session)
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
                                "Pass an existing graph id, or a list of "
                                "target refs: 'latest', "
                                "'<graph_id>:<node_id>', or filenames "
                                "inside the session's inputs/ directory."
                            ),
                        )
                    ],
                )
            ]
        empty_message = f"Graph {targets!r} has no completed nodes to render."
    else:
        refs = list(targets)
        empty_message = "progression() got an empty targets list."

    if not refs:
        return [
            _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="progression_empty",
                        message=empty_message,
                        fix=(
                            "Pass at least one target ref, or a graph id "
                            "whose nodes have completed."
                        ),
                    )
                ],
            )
        ]

    # 3. Truncate to the panel cap; record the cut in warnings.
    truncated = len(refs) > _PANEL_CAP
    omitted = len(refs) - _PANEL_CAP if truncated else 0
    render_refs = refs[:_PANEL_CAP]
    warnings: list[str] = []
    if truncated:
        warnings.append(
            f"progression truncated at {_PANEL_CAP} panels: "
            f"{omitted} more nodes omitted. Use a subset."
        )

    # 4. Resolve every rendered target up front — one unresolvable ref
    # fails the whole call, naming the offender.
    panel_specs: list[tuple[str, Path]] = []
    for ref in render_refs:
        try:
            audio_path = resolve_target(ref, session, latest_tracker)
        except ReferenceResolutionError as e:
            return [
                _failed_envelope(
                    session,
                    latest_tracker,
                    [
                        ErrorEntry(
                            type="reference_resolution",
                            message=f"progression target {ref!r}: {e}",
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

        # 5. Auto-synth spectral targets.
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
                                    f"Cannot auto-synth spectral target "
                                    f"{ref!r} — CDP is not configured on "
                                    "this server."
                                ),
                                fix=(
                                    "Set CDP_PATH and restart the server, "
                                    "or pass .wav targets."
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
                                message=f"progression target {ref!r}: {e}",
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
        panel_specs.append((ref, audio_path))

    # 6. Composite path — timestamped, like visualize().
    vis_dir = session.root / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-") + (
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}"
    )
    png_path = vis_dir / f"progression_{timestamp}.png"

    # 7. Render — off the event loop via run_with_progress, with
    # periodic MCP progress heartbeat so multi-panel renders don't trip
    # Claude Desktop's per-tool-call timeout. No composite cache (see
    # module docstring).
    try:
        width_px, height_px = await run_with_progress(
            ctx,
            "rendering progression composite",
            _render_progression,
            panel_specs,
            png_path,
            omitted,
        )
    except Exception as e:  # noqa: BLE001 — soundfile/librosa/PIL raise a zoo
        # Corrupt/truncated/unsupported audio must surface as a
        # structured envelope, not a raw protocol error. (Phase 2
        # hardening, M3.)
        return [
            _failed_envelope(
                session,
                latest_tracker,
                [
                    ErrorEntry(
                        type="render_failed",
                        message=f"progression render failed: {e}",
                        fix=(
                            "One of the target audio files may be corrupt, "
                            "truncated, or in an unsupported encoding. "
                            "Re-generate it or check it with analyze()."
                        ),
                    )
                ],
            )
        ]

    # 8. Build envelope. progression-specific metadata rides as sibling
    # keys next to the standard envelope fields, like visualize().
    envelope = ResultEnvelope(
        status="ok",
        output=str(png_path),
        stdout="",
        stderr="",
        exit_code=None,
        errors=[],
        warnings=warnings,
        cached=False,
        duration_ms=None,
        context=build_context_block(session, latest_tracker, active_graph=None),
    )
    envelope_dict = envelope.model_dump(mode="json")
    envelope_dict["panel_count"] = len(panel_specs)
    envelope_dict["truncated"] = truncated
    envelope_dict["targets_rendered"] = [ref for ref, _path in panel_specs]
    envelope_dict["width_px"] = width_px
    envelope_dict["height_px"] = height_px

    # 9. Two content blocks: image + JSON envelope.
    return [Image(path=str(png_path)), envelope_dict]


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``progression`` tool against ``mcp``.

    Thin wrapper around :func:`progression_impl`.
    """

    @mcp.tool()
    async def progression(
        ctx: Context,
        targets: list[str] | str,
        timeout_seconds: float = 60.0,
    ) -> list:
        """Render stacked spectrograms of multiple targets in one PNG.

        ``targets`` is either a list of target refs (each accepting the
        same grammar as visualize(): session input filenames,
        '<graph_id>:nN' references, the 'latest' alias; .ana/.pvx
        targets are auto-synthesized) or a single string naming a graph
        id — in that case every completed node in the graph renders in
        node-id order (n1, n2, ... n9, n10). To render one file, pass a
        one-element list.

        Panels stack top to bottom in target order and share one
        horizontal scale (100 px per second, capped at 1024 px wide),
        so relative durations are visible at a glance. At most 8 panels
        render; longer lists truncate to the first 8 plus a summary
        panel, with the truncation recorded in ``warnings``.

        Returns a two-element list on success: the composite PNG
        (inline image) plus a metadata envelope dict with
        ``panel_count``, ``truncated``, and ``targets_rendered``. On
        failure: a single-element list with just the envelope.
        """
        return await progression_impl(
            ctx,
            targets,
            timeout_seconds,
            sessions=sessions,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )


# ---------------------------------------------------------------------------
# Graph-id expansion
# ---------------------------------------------------------------------------

_NODE_ID_NUM_RE = re.compile(r"n(\d+)")


def _node_sort_key(node_id: str) -> tuple[int, int, str]:
    """Numeric-aware node-id ordering: n2 < n9 < n10.

    Label ids (``graph()`` definitions allow non-``nN`` names) sort
    lexicographically, after the ``nN`` family.
    """
    m = _NODE_ID_NUM_RE.match(node_id)
    if m:
        return (0, int(m.group(1)), node_id)
    return (1, 0, node_id)


def _expand_graph_targets(graph_id: str, session: Session) -> list[str]:
    """Turn a bare graph id into ``"<graph_id>:<node_id>"`` refs.

    Node ids come from the graph's ``node_index.json``, ordered by
    :func:`_node_sort_key`. An existing graph with no nodes returns
    ``[]`` (the caller maps that to ``progression_empty``).

    Raises:
        ReferenceResolutionError: when the graph is missing, its id is
            malformed, or its index is unreadable.
    """
    # Graph IDs are bare directory names minted by _make_graph_id;
    # anything with separators or dot-traversal is not a graph ID
    # (same containment rule as resolve_target).
    if (
        "/" in graph_id
        or "\\" in graph_id
        or graph_id in ("", ".", "..")
        or graph_id.startswith("..")
    ):
        raise ReferenceResolutionError(
            f"Reference {graph_id!r}: graph ids are bare directory names "
            "under graphs/ — no separators or traversal."
        )
    node_index_path = session.graphs_dir / graph_id / "node_index.json"
    if not node_index_path.exists():
        raise ReferenceResolutionError(
            f"Reference {graph_id!r}: no such graph "
            f"(missing {node_index_path}). To render specific files "
            "instead, pass a list of target refs."
        )
    try:
        index = json.loads(node_index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ReferenceResolutionError(
            f"Reference {graph_id!r}: could not read node_index.json: {e}"
        ) from e
    node_ids = sorted(index.keys(), key=_node_sort_key)
    return [f"{graph_id}:{node_id}" for node_id in node_ids]


# ---------------------------------------------------------------------------
# Panel rendering (sync — runs in a worker thread via run_with_progress)
# ---------------------------------------------------------------------------


def _render_progression(
    panel_specs: list[tuple[str, Path]],
    output_path: Path,
    omitted_count: int,
) -> tuple[int, int]:
    """Render every panel and composite them onto one white canvas.

    Blocking CPU work (librosa + PIL) — callers must run this off the
    event loop. Returns ``(width_px, height_px)`` of the saved PNG.
    """
    panels: list[PILImage.Image] = []
    for ref, audio_path in panel_specs:
        try:
            panels.append(_render_panel(ref, audio_path))
        except Exception as e:  # noqa: BLE001 — name the failing panel
            raise RuntimeError(
                f"panel {ref!r} ({audio_path.name}): {type(e).__name__}: {e}"
            ) from e
    if omitted_count:
        panels.append(_render_omitted_panel(omitted_count))

    height = sum(p.height for p in panels) + _GUTTER_PX * (len(panels) - 1)
    canvas = PILImage.new("RGB", (_PANEL_MAX_W, height), "white")
    y = 0
    for panel in panels:
        canvas.paste(panel, (0, y))
        y += panel.height + _GUTTER_PX
    canvas.save(output_path)
    return canvas.width, canvas.height


def _render_panel(ref: str, audio_path: Path) -> PILImage.Image:
    """One labeled spectrogram panel: a text strip over a mel strip.

    The mel matrix is colormapped directly and PIL-resized to
    ``duration * _PX_PER_S`` pixels wide, capped at ``_PANEL_MAX_W``
    (files longer than the cap get compressed beyond it) — panel widths
    encode relative duration exactly, with no matplotlib axes to trim.
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    duration_s = float(y.shape[-1] / sr)
    mel = librosa.feature.melspectrogram(
        y=y, sr=sr, n_fft=_N_FFT, hop_length=_HOP_LENGTH, window=_WINDOW
    )
    mel_db = librosa.power_to_db(mel, ref=np.max)
    norm = np.clip((mel_db - _DB_VMIN) / (_DB_VMAX - _DB_VMIN), 0.0, 1.0)
    # Row 0 of the mel matrix is the lowest band; flip so low frequencies
    # end up at the bottom. Copy makes the strides positive for PIL.
    rgb = (colormaps[_CMAP](norm)[..., :3] * 255.0).astype(np.uint8)
    strip = PILImage.fromarray(np.ascontiguousarray(rgb[::-1]))
    spec_w = max(1, min(_PANEL_MAX_W, round(duration_s * _PX_PER_S)))
    strip = strip.resize((spec_w, _SPEC_H), PILImage.Resampling.LANCZOS)

    panel = PILImage.new("RGB", (_PANEL_MAX_W, _LABEL_H + _SPEC_H), "white")
    draw = ImageDraw.Draw(panel)
    # Default PIL bitmap font — ASCII-only label text on purpose.
    draw.text((4, 5), f"{ref}  ({duration_s:.2f}s)", fill="black")
    panel.paste(strip, (0, _LABEL_H))
    return panel


def _render_omitted_panel(omitted_count: int) -> PILImage.Image:
    """Text-only summary panel appended when the target list truncates."""
    panel = PILImage.new("RGB", (_PANEL_MAX_W, _OMITTED_PANEL_H), "white")
    draw = ImageDraw.Draw(panel)
    draw.text(
        (4, _OMITTED_PANEL_H // 2 - 5),
        f"{omitted_count} more nodes omitted. Use a subset.",
        fill="black",
    )
    return panel


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
