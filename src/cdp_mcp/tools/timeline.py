"""The ``timeline()`` MCP tool — deterministic multi-source event placement.

Phase 6 core build. ``timeline()`` renders an explicit event list
``[{source, at, level?, pan?}]`` into one soundfile through CDP's
``submix mix`` engine: the tool validates every reference (full grammar,
including ``latest_batch[i]``), pins SR/channel compatibility against
the submix-mix empirics (tranche 5/7/12), writes the mixfile into the
session's ``data/`` directory, and executes through ``validate_node`` /
``execute_validated_node`` so security, the watchdog, and lineage are
inherited unchanged.

Two facts drive the design (forensics P5-3):

- ``submix mix`` output duration is ``max(at + dur) − min(at)`` and the
  engine's pre-flight deliberately can't compute it (the durations live
  inside the mixfile) — so THIS tool computes the prediction and
  enforces the duration cap before anything runs.
- Overload WRAPS (integer wraparound, not clipping). Headroom is staged
  BEFORE the mix via the curated ``submix getlevel 3`` data entry, run
  through the same engine path; its ``NORMALISATION REQUIRED`` factor
  feeds ``submix mix``'s ``atten`` (``-g``), which attenuates the float
  sum pre-quantisation.

Routing decision (phase-6 design, post-run recheck): v1 is SUBMIX-ONLY.
Pitch-bearing event lists are ``extend sequence2``'s job — the docstring
says so; there is no auto-routing (the two engines' wrap and duration
semantics differ enough that silent routing would surprise).
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import soundfile as sf
from mcp.server.fastmcp import Context, FastMCP

from ..config import CDPConfig
from ..graph import (
    GraphDir,
    LatestTracker,
    ReferenceResolutionError,
    build_context_block,
    resolve_target,
)
from ..knowledge.loader import KnowledgeIndex
from ..limits import OUTPUT_DURATION_CAP_S
from ..schema import ContextBlock, ErrorEntry, ResultEnvelope
from ..session import Session, SessionManager, SessionNotActiveError
from .data_files import _write_data_file
from .entry_lookup import resolve_entry
from .node_execution import execute_validated_node
from .node_validation import validate_node

_HEADROOM_MODES = ("auto", "off", "fail")
_EVENT_KEYS = frozenset({"source", "at", "level", "pan"})

# Curated ``atten`` minimum (submix_mix.json): CDP accepts -g0 but that
# renders digital silence, so the entry keeps the valve reachable-but-
# nonzero. A getlevel factor below this is clamped (with a warning).
_ATTEN_MIN = 1e-6

# getlevel 3 report grammar (tranche 12 §7, verbatim format): zero or
# more clip lines, a blank line, then MAX SAMPLE + NORMALISATION
# REQUIRED. The factor is 1/peak UNCONDITIONALLY — > 1 means available
# headroom, only < 1 means the render would wrap.
_FACTOR_RE = re.compile(r"NORMALISATION REQUIRED\s*:\s*([-+0-9.eE]+)")
_PEAK_RE = re.compile(r"MAX SAMPLE ENCOUNTERED\s*:\s*([-+0-9.eE]+)")


@dataclass
class _Event:
    """One validated, resolved timeline event."""

    index: int
    source: str
    at: float
    level: float
    pan: float | None
    resolved: Path | None = None
    rel: str | None = None  # session-root-relative path for the mixfile line
    duration_s: float | None = None
    samplerate: int | None = None
    channels: int | None = None

    def report(self) -> dict:
        """Compact per-event record for the result payload."""
        return {
            "index": self.index,
            "source": self.source,
            "path": self.rel,
            "at": self.at,
            "level": self.level,
            "pan": self.pan,
            "duration_s": self.duration_s,
            "end_s": (
                round(self.at + self.duration_s, 6)
                if self.duration_s is not None else None
            ),
            "samplerate": self.samplerate,
            "channels": self.channels,
        }


def _fmt(value: float) -> str:
    """Mixfile-friendly number: fixed 6 dp (sub-sample at 44.1 kHz),
    trailing zeros trimmed. ``0.0 → '0'``, ``0.5 → '0.5'``."""
    s = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


async def timeline_impl(
    ctx: Context,
    events: list[dict[str, Any]],
    headroom: str = "auto",
    output_name: str | None = None,
    timeout_seconds: float = 120.0,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> dict:
    """Implementation of ``timeline()``."""
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _no_session_failure(latest_tracker, str(e))
    cdp = cdp_config_provider()
    if cdp is None:
        return _failure(session, latest_tracker, [ErrorEntry(
            type="cdp_not_configured",
            message="CDP is not configured on this server.",
            fix=(
                "Set the CDP_PATH environment variable to the directory "
                "containing CDP binaries and restart the server."
            ),
        )])

    mix_entry, mix_error = resolve_entry(knowledge_index, "submix", "mix")
    if mix_error is not None:
        return _failure(session, latest_tracker, [mix_error])
    assert mix_entry is not None  # resolve_entry contract
    getlevel_entry, getlevel_error = resolve_entry(
        knowledge_index, "submix", "getlevel", 3
    )
    if getlevel_error is not None:
        return _failure(session, latest_tracker, [getlevel_error])
    assert getlevel_entry is not None

    if headroom not in _HEADROOM_MODES:
        return _failure(session, latest_tracker, [ErrorEntry(
            type="timeline_spec_error",
            message=(
                f"headroom must be one of {list(_HEADROOM_MODES)}; got "
                f"{headroom!r}."
            ),
            fix=(
                "'auto' (default) applies getlevel's factor when < 1, "
                "'off' renders raw (overs WRAP), 'fail' refuses when the "
                "factor is < 1."
            ),
        )])

    # ---- Event validation (shape, then resolution/probes) -----------------
    if (
        not isinstance(events, list)
        or not events
        or not all(isinstance(e, dict) for e in events)
    ):
        return _failure(session, latest_tracker, [ErrorEntry(
            type="timeline_spec_error",
            message=(
                "events must be a non-empty list of event dicts "
                "{source, at, level?, pan?}."
            ),
            fix=(
                "Pass at least one event: e.g. "
                "[{'source': 'latest', 'at': 0.0}]."
            ),
        )])

    validated, shape_errors = _validate_event_shapes(events)
    if shape_errors:
        return _failure(session, latest_tracker, shape_errors)

    warnings: list[str] = []
    resolve_errors = _resolve_and_probe_events(
        validated, session, latest_tracker, warnings
    )
    if resolve_errors:
        return _failure(session, latest_tracker, resolve_errors)

    # SR compatibility: mixfile sources must all share ONE sample rate
    # (mixed rates refuse with 'Incompatible sample-rate in file ...').
    rates = {ev.samplerate for ev in validated}
    if len(rates) > 1:
        listing = "; ".join(
            f"events[{ev.index}] {ev.rel} @ {ev.samplerate} Hz"
            for ev in validated
        )
        return _failure(session, latest_tracker, [ErrorEntry(
            type="incompatible_sample_rates",
            message=(
                "submix mix requires all sources to share one sample "
                f"rate; got {sorted(rates)}. {listing}."
            ),
            fix=(
                "Resample the odd files out (or regenerate them at the "
                "common rate) before placing them on the timeline."
            ),
        )])

    # ---- Duration pre-flight (the rule the engine can't compute) ----------
    # Output duration = max(at + dur) − min(at): leading silence before
    # the FIRST event is stripped; interior gaps are preserved.
    predicted = round(
        max(ev.at + (ev.duration_s or 0.0) for ev in validated)
        - min(ev.at for ev in validated),
        6,
    )
    if predicted > OUTPUT_DURATION_CAP_S:
        return _failure(
            session, latest_tracker,
            [ErrorEntry(
                type="predicted_duration_exceeds_cap",
                message=(
                    f"predicted output duration {predicted:.1f}s exceeds "
                    f"the {OUTPUT_DURATION_CAP_S:.0f}s cap (rule: "
                    "max(at + source_duration) - min(at))."
                ),
                fix=(
                    "Move events earlier / use shorter sources, or split "
                    "the gesture into multiple timeline() calls."
                ),
            )],
            predicted=predicted,
            events_report=[ev.report() for ev in validated],
        )

    # ---- Write the mixfile (write_data_file conventions, fresh name) ------
    mix_lines = []
    for ev in validated:
        line = f"{ev.rel} {_fmt(ev.at)} {ev.channels} {_fmt(ev.level)}"
        if ev.pan is not None:
            line += f" {_fmt(ev.pan)}"
        mix_lines.append(line)
    mixfile_name = f"timeline_{uuid.uuid4().hex[:10]}.txt"
    write_result = _write_data_file(
        session, mixfile_name, "\n".join(mix_lines) + "\n"
    )
    if write_result["status"] != "ok":
        return _failure(
            session, latest_tracker,
            [ErrorEntry(**e) for e in write_result["errors"]],
            events_report=[ev.report() for ev in validated],
            predicted=predicted,
        )
    mixfile_path = write_result["path"]
    events_report = [ev.report() for ev in validated]

    # ---- One graph directory for the whole timeline call ------------------
    graph_dir = GraphDir(session, "timeline")
    graph_dir.set_graph_definition({
        "tool": "timeline",
        "events": events,
        "headroom": headroom,
        "output_name": output_name,
        "mixfile": mixfile_path,
        "predicted_duration_s": predicted,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    })

    # ---- Headroom staging (P5-3): curated getlevel 3 via the engine -------
    headroom_report: dict[str, Any] = {
        "mode": headroom, "factor": None, "peak": None,
        "applied": False, "report": None,
    }
    mix_params: dict[str, Any] = {"mixfile": mixfile_name}
    mix_node_id = "n1_mix"
    if headroom == "off":
        warnings.append(
            "headroom staging skipped (headroom='off'): overlapping "
            "events sum linearly and overs WRAP (integer wraparound, "
            "not clipping) — the render may be garbage if the sum "
            "exceeds full scale."
        )
    else:
        stage = await _run_headroom_stage(
            ctx=ctx,
            entry=getlevel_entry,
            mixfile_name=mixfile_name,
            timeout_seconds=timeout_seconds,
            session=session,
            cdp=cdp,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
            graph_dir=graph_dir,
        )
        if stage.errors:
            return _failure(
                session, latest_tracker, stage.errors,
                active_graph=graph_dir.id,
                warnings=warnings,
                events_report=events_report,
                mixfile=mixfile_path,
                headroom_report=headroom_report,
                predicted=predicted,
                stdout=stage.stdout, stderr=stage.stderr,
                exit_code=stage.exit_code,
            )
        headroom_report["factor"] = stage.factor
        headroom_report["peak"] = stage.peak
        headroom_report["report"] = stage.report_path
        mix_node_id = "n2_mix"
        assert stage.factor is not None  # error-free stage contract
        if stage.factor < 1.0:
            if headroom == "fail":
                return _failure(
                    session, latest_tracker,
                    [ErrorEntry(
                        type="headroom_required",
                        message=(
                            f"mix would exceed full scale (peak "
                            f"{stage.peak}); submix getlevel 3 reports "
                            f"NORMALISATION REQUIRED : {stage.factor} "
                            "(< 1). Rendering would WRAP (integer "
                            "wraparound, not clipping)."
                        ),
                        fix=(
                            "Re-run with headroom='auto' to apply the "
                            "factor as submix mix's atten, lower or move "
                            "the colliding events (the getlevel report's "
                            "clip lines say where), or headroom='off' to "
                            "render raw anyway."
                        ),
                    )],
                    active_graph=graph_dir.id,
                    warnings=warnings,
                    events_report=events_report,
                    mixfile=mixfile_path,
                    headroom_report=headroom_report,
                    predicted=predicted,
                )
            # headroom == "auto"
            atten = stage.factor
            if atten < _ATTEN_MIN:
                atten = _ATTEN_MIN
                warnings.append(
                    f"getlevel factor {stage.factor} is below the atten "
                    f"minimum {_ATTEN_MIN}; clamped."
                )
            mix_params["atten"] = atten
            headroom_report["applied"] = True

    # ---- The mix render itself, through the normal engine path ------------
    validation = await validate_node(
        ctx=ctx,
        entry=mix_entry,
        inputs=[],
        params=mix_params,
        output_name=output_name,
        timeout_seconds=timeout_seconds,
        session=session,
        cdp=cdp,
        latest_tracker=latest_tracker,
        cache_root=cache_root,
        graph_dir=graph_dir,
        node_id_base=mix_node_id,
    )
    if validation.errors:
        return _failure(
            session, latest_tracker, validation.errors,
            active_graph=graph_dir.id,
            warnings=warnings + validation.warnings,
            events_report=events_report,
            mixfile=mixfile_path,
            headroom_report=headroom_report,
            predicted=predicted,
        )
    outcome = await execute_validated_node(
        ctx=ctx,
        validation=validation,
        program="submix",
        mode="mix",
        params=mix_params,
        timeout_seconds=timeout_seconds,
        session=session,
        cdp=cdp,
    )
    if outcome.bookkeeping_error is not None:
        return _failure(
            session, latest_tracker, [outcome.bookkeeping_error],
            active_graph=graph_dir.id,
            warnings=warnings + validation.warnings,
            events_report=events_report,
            mixfile=mixfile_path,
            headroom_report=headroom_report,
            predicted=predicted,
        )

    sub = outcome.subprocess_result
    if outcome.success:
        latest_tracker.update(graph_dir.id, mix_node_id)

    envelope = ResultEnvelope(
        status="ok" if outcome.success else "failed",
        output=str(validation.output_path) if outcome.success else None,
        stdout=sub.stdout,
        stderr=sub.stderr,
        exit_code=sub.exit_code,
        errors=outcome.errors,
        warnings=warnings + validation.warnings,
        cached=False,
        duration_ms=sub.duration_ms,
        context=build_context_block(
            session, latest_tracker, active_graph=graph_dir.id
        ),
    )
    result = envelope.model_dump(mode="json")
    result.update({
        "graph_id": graph_dir.id,
        "mixfile": mixfile_path,
        "predicted_duration_s": predicted,
        "headroom": headroom_report,
        "events": events_report,
    })
    return result


# ---------------------------------------------------------------------------
# Event validation helpers
# ---------------------------------------------------------------------------


def _validate_event_shapes(
    events: list[dict[str, Any]],
) -> tuple[list[_Event], list[ErrorEntry]]:
    """Structural validation of the raw event dicts. Collects EVERY
    error (per-event, index-prefixed) rather than stopping at the first,
    so one round trip fixes the whole list."""
    validated: list[_Event] = []
    errors: list[ErrorEntry] = []
    for i, raw in enumerate(events):
        unknown = set(raw) - _EVENT_KEYS
        if unknown:
            errors.append(_event_error(
                i,
                f"unknown key(s) {sorted(unknown)}",
                "Each event is {source, at, level?, pan?}.",
            ))
            continue
        source = raw.get("source")
        if not isinstance(source, str) or not source:
            errors.append(_event_error(
                i, f"source must be a non-empty string; got {source!r}",
                "Pass a reference: a session input filename, 'latest', "
                "'prev_N', 'latest_batch[i]', or '<graph_id>:<node_id>'.",
            ))
            continue
        at = raw.get("at")
        if not _is_number(at) or not math.isfinite(at) or at < 0:
            errors.append(_event_error(
                i, f"at must be a finite number >= 0 seconds; got {at!r}",
                "Event start times are absolute seconds from timeline "
                "zero (negative start times are refused by CDP).",
            ))
            continue
        level = raw.get("level", 1.0)
        if not _is_number(level) or not math.isfinite(level) or level <= 0:
            errors.append(_event_error(
                i,
                f"level must be a finite number > 0; got {level!r}",
                "level is a linear multiplier (1.0 = unity). CDP refuses "
                "plain negative levels; for attenuation use values in "
                "(0, 1).",
            ))
            continue
        pan = raw.get("pan")
        if pan is not None and (not _is_number(pan) or not math.isfinite(pan)):
            errors.append(_event_error(
                i, f"pan must be a finite number when given; got {pan!r}",
                "pan: -1 hard left, 0 centre, +1 hard right; beyond ±1 "
                "keeps the hard side and attenuates by 1/|pan|.",
            ))
            continue
        validated.append(_Event(
            index=i,
            source=source,
            at=float(at),
            level=float(level),
            pan=float(pan) if pan is not None else None,
        ))
    return validated, errors


def _resolve_and_probe_events(
    validated: list[_Event],
    session: Session,
    latest_tracker: LatestTracker,
    warnings: list[str],
) -> list[ErrorEntry]:
    """Resolve each event's reference and probe SR/channels/duration.

    Mutates the events in place; returns the collected errors. Pinned
    rules (submix mix empirics, tranches 5/7/12): sources are .wav; the
    chans column must equal the file's real channel count (probed here,
    emitted by us); pan lines are mono-only in the verified line syntax
    ('sndname start 1 level pan' — the stereo panned form takes four
    level/pan columns and is out of v1 scope); mixfile paths resolve
    against the session root and cannot contain whitespace.
    """
    errors: list[ErrorEntry] = []
    for ev in validated:
        try:
            ev.resolved = resolve_target(ev.source, session, latest_tracker)
        except ReferenceResolutionError as e:
            errors.append(ErrorEntry(
                type="reference_resolution",
                message=f"events[{ev.index}]: {e}",
                fix=(
                    "Check the reference: 'latest', 'prev_N', "
                    "'latest_batch[i]', '<graph_id>:<node_id>', or a "
                    "filename inside the session's inputs/ directory."
                ),
            ))
            continue
        if ev.resolved.suffix.lower() != ".wav":
            errors.append(_event_error(
                ev.index,
                f"source resolves to {ev.resolved.name!r}; submix mix "
                "sources must be .wav soundfiles",
                "Resynthesize spectral outputs first (they auto-convert "
                "in process(), but a mixfile names raw soundfiles), or "
                "pick a .wav-producing node.",
            ))
            continue
        try:
            info = sf.info(str(ev.resolved))
        except Exception as e:  # noqa: BLE001 — soundfile raises a variety
            errors.append(_event_error(
                ev.index,
                f"could not read {ev.resolved.name!r}: {e}",
                "The source must be a readable .wav soundfile.",
            ))
            continue
        ev.duration_s = float(info.duration)
        ev.samplerate = int(info.samplerate)
        ev.channels = int(info.channels)
        if ev.channels not in (1, 2):
            errors.append(_event_error(
                ev.index,
                f"{ev.resolved.name!r} has {ev.channels} channels; the "
                "verified mixfile line syntax covers mono and stereo "
                "sources only",
                "Split multichannel material down to mono/stereo before "
                "placing it on the timeline.",
            ))
            continue
        if ev.pan is not None and ev.channels != 1:
            errors.append(ErrorEntry(
                type="pan_requires_mono",
                message=(
                    f"events[{ev.index}]: pan given but "
                    f"{ev.resolved.name!r} is stereo — pan lines are "
                    "mono-only in submix mix's verified syntax."
                ),
                fix=(
                    "Give the event a mono source, or pre-position the "
                    "stereo file (it renders where it stands) and omit "
                    "pan."
                ),
            ))
            continue
        rel = ev.resolved.relative_to(session.root.resolve()).as_posix()
        if any(ch.isspace() for ch in rel):
            errors.append(_event_error(
                ev.index,
                f"path {rel!r} contains whitespace; mixfile columns are "
                "whitespace-split, so such paths cannot be referenced",
                "Rename the file (no spaces) and try again.",
            ))
            continue
        ev.rel = rel
        if ev.pan is not None and abs(ev.pan) > 1.0:
            warnings.append(
                f"events[{ev.index}]: pan {ev.pan} is beyond ±1 — CDP "
                "keeps the hard side and attenuates the level by "
                "1/|pan|."
            )
    return errors


def _event_error(index: int, message: str, fix: str) -> ErrorEntry:
    return ErrorEntry(
        type="invalid_event",
        message=f"events[{index}]: {message}.",
        fix=fix,
    )


# ---------------------------------------------------------------------------
# Headroom staging
# ---------------------------------------------------------------------------


@dataclass
class _HeadroomStage:
    """Outcome of the getlevel-3 pre-flight node."""

    errors: list[ErrorEntry]
    factor: float | None = None
    peak: float | None = None
    report_path: str | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


async def _run_headroom_stage(
    *,
    ctx: Context,
    entry,
    mixfile_name: str,
    timeout_seconds: float,
    session: Session,
    cdp: CDPConfig,
    latest_tracker: LatestTracker,
    cache_root: Path,
    graph_dir: GraphDir,
) -> _HeadroomStage:
    """Run the curated ``submix getlevel 3`` entry on the mixfile through
    the normal engine path (node ``n1_headroom`` in the shared graph
    dir) and parse the NORMALISATION REQUIRED factor from its report."""
    validation = await validate_node(
        ctx=ctx,
        entry=entry,
        inputs=[],
        params={"mixfile": mixfile_name},
        output_name=None,
        timeout_seconds=timeout_seconds,
        session=session,
        cdp=cdp,
        latest_tracker=latest_tracker,
        cache_root=cache_root,
        graph_dir=graph_dir,
        node_id_base="n1_headroom",
    )
    if validation.errors:
        return _HeadroomStage(errors=_staged(validation.errors))
    outcome = await execute_validated_node(
        ctx=ctx,
        validation=validation,
        program="submix",
        mode="getlevel",
        params={"mixfile": mixfile_name},
        timeout_seconds=timeout_seconds,
        session=session,
        cdp=cdp,
    )
    errors = list(outcome.errors)
    if outcome.bookkeeping_error is not None:
        errors.append(outcome.bookkeeping_error)
    sub = outcome.subprocess_result
    if not outcome.success:
        return _HeadroomStage(
            errors=_staged(errors),
            stdout=sub.stdout, stderr=sub.stderr, exit_code=sub.exit_code,
        )
    assert validation.output_path is not None
    try:
        report_text = validation.output_path.read_text(encoding="utf-8")
    except OSError as e:
        return _HeadroomStage(errors=[ErrorEntry(
            type="headroom_preflight_failed",
            message=f"could not read the getlevel report: {e}",
            fix="Inspect the graph directory on disk for clues.",
        )])
    factor_m = _FACTOR_RE.findall(report_text)
    peak_m = _PEAK_RE.findall(report_text)
    if not factor_m:
        return _HeadroomStage(errors=[ErrorEntry(
            type="headroom_preflight_failed",
            message=(
                "getlevel report has no 'NORMALISATION REQUIRED' line "
                f"({validation.output_path})."
            ),
            fix=(
                "Inspect the report file; if the format changed, this "
                "is a curation/engine defect."
            ),
        )])
    return _HeadroomStage(
        errors=[],
        factor=float(factor_m[-1]),
        peak=float(peak_m[-1]) if peak_m else None,
        report_path=str(validation.output_path),
        stdout=sub.stdout, stderr=sub.stderr, exit_code=sub.exit_code,
    )


def _staged(errors: list[ErrorEntry]) -> list[ErrorEntry]:
    """Prefix stage errors with a headroom_preflight_failed marker so
    the caller can tell WHICH node failed without parsing messages."""
    return [ErrorEntry(
        type="headroom_preflight_failed",
        message=(
            "the submix getlevel 3 headroom pre-flight failed before "
            "the mix could render; per-stage errors follow."
        ),
        fix=(
            "Fix the underlying error (below), or pass headroom='off' "
            "to skip staging (overs WRAP)."
        ),
    ), *errors]


# ---------------------------------------------------------------------------
# Failure envelopes
# ---------------------------------------------------------------------------


def _failure(
    session,
    latest_tracker: LatestTracker,
    errors: list[ErrorEntry],
    *,
    active_graph: str | None = None,
    warnings: list[str] | None = None,
    events_report: list[dict] | None = None,
    mixfile: str | None = None,
    headroom_report: dict | None = None,
    predicted: float | None = None,
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
) -> dict:
    envelope = ResultEnvelope(
        status="failed",
        output=None,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        errors=errors,
        warnings=warnings or [],
        cached=False,
        duration_ms=None,
        context=build_context_block(
            session, latest_tracker, active_graph=active_graph
        ),
    )
    result = envelope.model_dump(mode="json")
    result.update({
        "graph_id": active_graph,
        "mixfile": mixfile,
        "predicted_duration_s": predicted,
        "headroom": headroom_report,
        "events": events_report or [],
    })
    return result


def _no_session_failure(latest_tracker: LatestTracker, message: str) -> dict:
    envelope = ResultEnvelope(
        status="failed",
        output=None,
        stdout="",
        stderr="",
        exit_code=None,
        errors=[ErrorEntry(
            type="no_active_session",
            message=message,
            fix="Call set_session('<name>') first.",
        )],
        warnings=[],
        cached=False,
        duration_ms=None,
        context=ContextBlock(
            active_graph=None,
            latest=latest_tracker.latest,
            recent_graphs=[],
            available_sources=[],
        ),
    )
    result = envelope.model_dump(mode="json")
    result.update({
        "graph_id": None,
        "mixfile": None,
        "predicted_duration_s": None,
        "headroom": None,
        "events": [],
    })
    return result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``timeline`` tool against ``mcp``."""

    @mcp.tool()
    async def timeline(
        ctx: Context,
        events: list[dict[str, Any]],
        headroom: str = "auto",
        output_name: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict:
        """Place multiple sources at explicit times — one composed gesture.

        Deterministic multi-source event placement (CDP ``submix mix``):
        each event is ``{source, at, level?, pan?}`` — ``source`` accepts
        the full reference grammar (a session input filename, ``latest``,
        ``prev_N``, ``latest_batch[i]``, ``<graph_id>:<node_id>``); ``at``
        is the start time in seconds (>= 0, need not be sorted); ``level``
        is a linear multiplier (default 1.0, must be > 0); ``pan`` is
        optional and MONO SOURCES ONLY (-1 hard left, 0 centre, +1 hard
        right; beyond ±1 keeps the hard side and attenuates by 1/|pan|).
        All sources must be .wav files sharing one sample rate. Output
        channels: all-mono with no pans → mono; any pan or any stereo
        source → stereo. Output duration = ``max(at + source_duration) −
        min(at)`` — leading silence before the first event is stripped,
        interior gaps are preserved. Idiomatic use: ``sweep()`` makes N
        variants → ``timeline()`` places them (e.g. a bounce accelerando
        is a geometric ``at`` series) → ``segments()``/``analyze()``
        verify the result.

        PITCH ROUTING: timeline() is pitch-agnostic by design. If your
        event list carries per-event pitch (a melodic/harmonic score:
        midi pitches, transpositions), use ``process("extend",
        "sequence2", ...)`` instead — the curated multi-source score
        renderer (its sequence file rows are ``sound-number time pitch
        loudness dur``). The two engines' wrap and duration semantics
        differ, so timeline() does NOT auto-route.

        HEADROOM: overlapping events sum linearly, and when the sum
        exceeds full scale CDP's output WRAPS (integer wraparound —
        harsh garbage, not gentle clipping). timeline() therefore stages
        headroom before rendering: it runs the curated ``submix getlevel
        3`` pre-flight on the mixfile and reads its NORMALISATION
        REQUIRED factor (1/peak, reported unconditionally — only < 1
        means action). ``headroom="auto"`` (default) applies a factor
        < 1 as the mix's ``atten`` (applied to the float sum BEFORE
        quantisation — clean render at peak ~1.0) and reports
        ``headroom.applied: true``; ``"fail"`` refuses with a structured
        ``headroom_required`` error carrying the factor; ``"off"`` skips
        the stage and renders raw (the result may wrap — the report
        warns). The getlevel report (kept in the graph directory) lists
        WHERE clipping would occur, so you can lower or move the
        colliding events instead of attenuating the whole mix.

        The generated mixfile lands in the session's ``data/`` directory
        (fresh name per call, path echoed as ``mixfile``); the getlevel
        node (``n1_headroom``) and the mix node (``n2_mix``; ``n1_mix``
        when headroom='off') share one graph directory with full
        lineage. On success ``latest`` points at the rendered mix. The
        result carries a compact per-event report ({index, source, path,
        at, level, pan, duration_s, end_s, samplerate, channels}),
        ``predicted_duration_s``, and the ``headroom`` report
        ({mode, factor, peak, applied, report}).
        """
        return await timeline_impl(
            ctx,
            events,
            headroom,
            output_name,
            timeout_seconds,
            sessions=sessions,
            knowledge_index=knowledge_index,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )
