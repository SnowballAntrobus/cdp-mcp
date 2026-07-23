"""Compile breakpoint parameter values into CDP-compatible `.brk` files.

A param value can be a relative-time tuple list (floats in [0, 1] ×
source duration), an absolute-time tuple list (strings prefixed with
``"abs:"``), or a path to a pre-existing `.brk` file. The compiler:

- Detects the form and validates consistency.
- Resolves source duration from input audio (or upstream lineage for
  chained .ana inputs).
- Sorts, dedups near-identical timestamps (1e-6 threshold), validates
  range, auto-appends a final point at end-of-file.
- Compiles to plain-text ``"TIME VALUE\\n"`` format (CDP-tolerant — see
  examples in cdpr8/docs/demo/sdbats/*.brk).
- Writes to ``session.envelopes_dir`` with a content-hashed filename so
  identical breakpoint content shares one file across calls.
- Returns a :class:`CompiledBreakpoint` record for the node's lineage
  and a Path that ``build_cdp_argv`` consumes.

Pure functions over inputs; no global state. Errors are returned as
:class:`ErrorEntry` items rather than raised — callers aggregate them
with other validation errors per the all-at-once reporting principle.

**Why the .brk content sha (not the original tuple list) feeds Task
12's cache key**: the same tuple ``[[0.0, 5], [1.0, 50]]`` produces
different .brk content for different source durations, which IS what
we want the cache to disambiguate. Hashing the tuple directly would
silently reuse cached output across input duration changes, producing
wrong results. This comment must survive any future "optimization"
that proposes to hash the tuple instead.

**JSON intake note**: MCP delivers tuple lists as lists-of-lists
(JSON has no tuples). Internals use index access (``pair[0]``,
``pair[1]``) rather than tuple-unpacking — accepts both shapes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .schema import CompiledBreakpoint, ErrorEntry, ParameterSpec

# Threshold for "near-identical" timestamps that we dedup with a
# warning. 1 microsecond is well below any musically meaningful
# breakpoint resolution.
_DEDUP_EPSILON_S = 1e-6


@dataclass
class BreakpointCompileResult:
    """Outcome of one ``compile_breakpoint_value`` call.

    ``record`` and ``compiled_path`` are ``None`` on failure (``errors``
    populated). On success both are set. Warnings are non-fatal and may
    accompany a successful result (e.g., near-identical-dedup notice).
    """

    record: CompiledBreakpoint | None = None
    compiled_path: Path | None = None
    errors: list[ErrorEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def is_breakpoint_value(value: Any) -> bool:
    """True if ``value`` looks like a breakpoint value (list of pairs,
    or a string ending in ``.brk``)."""
    if isinstance(value, list):
        return True
    if isinstance(value, str) and value.lower().endswith(".brk"):
        return True
    return False


def detect_breakpoint_mode(
    value: list,
) -> Literal["relative", "absolute", "mixed", "empty"]:
    """Inspect a list value to determine the time mode.

    ``"mixed"`` and ``"empty"`` are error signals — the caller surfaces
    structured errors. Otherwise the first element's first item decides:
    a string starting with ``"abs:"`` is absolute, anything else is
    relative.
    """
    if not value:
        return "empty"
    has_absolute = False
    has_relative = False
    for pair in value:
        # Tolerate non-list/tuple entries; the per-tuple validator will
        # report them as param_breakpoint_value_type. Treat them as
        # whichever mode we've already seen so we don't flap to mixed.
        if not isinstance(pair, (list, tuple)) or len(pair) < 1:
            continue
        first = pair[0]
        if isinstance(first, str) and first.startswith("abs:"):
            has_absolute = True
        else:
            has_relative = True
    if has_absolute and has_relative:
        return "mixed"
    if has_absolute:
        return "absolute"
    return "relative"


# ---------------------------------------------------------------------------
# Compilation entry point
# ---------------------------------------------------------------------------


def compile_breakpoint_value(
    *,
    param_name: str,
    param_spec: ParameterSpec,
    value: Any,
    source_duration_s: float | None,
    source_kind: Literal[
        "input_wav", "pvoc_lineage", "ana_sfprops", "set_by_param",
        "dry_run_override", "dry_run_dummy",
    ] | None,
    session_root: Path,
    envelopes_dir: Path,
) -> BreakpointCompileResult:
    """Compile a single breakpoint parameter value.

    The caller resolves ``source_duration_s`` before calling and passes
    it explicitly. Path-mode values don't need it; relative-time lists
    require it (else: ``param_breakpoint_no_source_duration``); absolute
    lists tolerate ``None`` (skip the auto-append step with a warning).

    Mutates nothing — caller is responsible for replacing
    ``params_dict[param_name]`` with the returned ``compiled_path``.
    """
    # Path mode — pre-existing .brk file.
    if isinstance(value, str) and value.lower().endswith(".brk"):
        return _handle_preexisting_path(
            param_name=param_name,
            value=value,
            session_root=session_root,
            envelopes_dir=envelopes_dir,
        )

    # List mode — relative or absolute tuple list.
    if not isinstance(value, list):
        # Caller should have screened via is_breakpoint_value; if we
        # got here with a non-list non-path value, that's a contract
        # violation upstream.
        return BreakpointCompileResult(errors=[ErrorEntry(
            type="param_breakpoint_value_type",
            message=(
                f"Parameter {param_name!r} got {type(value).__name__} "
                f"{value!r} — expected a list of (time, value) pairs "
                f"or a path to a .brk file."
            ),
            fix="Pass a numeric constant, a list of [time, value] pairs, or a .brk path.",
        )])

    mode = detect_breakpoint_mode(value)
    if mode == "empty":
        return BreakpointCompileResult(errors=[ErrorEntry(
            type="param_breakpoint_empty_list",
            message=f"Parameter {param_name!r} got an empty breakpoint list.",
            fix="Provide at least one [time, value] pair.",
        )])
    if mode == "mixed":
        return BreakpointCompileResult(errors=[ErrorEntry(
            type="param_breakpoint_mode_mixed",
            message=(
                f"Parameter {param_name!r}'s breakpoint list mixes "
                f"relative and absolute timestamps. Pick one — either "
                f"all floats in [0, 1] (relative) or all strings prefixed "
                f"with 'abs:' (absolute)."
            ),
            fix="Convert every tuple's first element to the same form.",
        )])

    return _compile_list_mode(
        param_name=param_name,
        param_spec=param_spec,
        tuples=value,
        mode=mode,
        source_duration_s=source_duration_s,
        source_kind=source_kind,
        envelopes_dir=envelopes_dir,
    )


# ---------------------------------------------------------------------------
# Path mode
# ---------------------------------------------------------------------------


def _handle_preexisting_path(
    *,
    param_name: str,
    value: str,
    session_root: Path,
    envelopes_dir: Path,
) -> BreakpointCompileResult:
    """Resolve and read a pre-existing .brk file referenced by path.

    Resolution order for relative paths:
    1. ``envelopes_dir / value`` — canonical location for .brk files.
       Bare basenames like ``"shift.brk"`` find files dropped into
       ``<session>/envelopes/`` on the first try.
    2. ``session_root / value`` — fallback for explicit paths like
       ``"envelopes/shift.brk"`` or ``"templates/foo/bar.brk"``.

    Absolute paths pass through unchanged. The path-scope security
    gate in ``build_cdp_argv`` rejects paths outside the session tree
    later if needed.
    """
    raw_path = Path(value)
    primary: Path | None = None
    fallback: Path | None = None
    if raw_path.is_absolute():
        resolved = raw_path
    else:
        primary = envelopes_dir / raw_path
        fallback = session_root / raw_path
        resolved = primary if primary.exists() else fallback
    try:
        resolved = resolved.resolve(strict=True)
    except (OSError, FileNotFoundError):
        if primary is not None and fallback is not None:
            message = (
                f"Parameter {param_name!r} references .brk file "
                f"{value!r} but it was not found. Searched: "
                f"{primary}, {fallback}."
            )
        else:
            message = (
                f"Parameter {param_name!r} references .brk file "
                f"{value!r} but it could not be resolved."
            )
        return BreakpointCompileResult(errors=[ErrorEntry(
            type="param_breakpoint_file_unreadable",
            message=message,
            fix=(
                "Place the .brk file in the session's envelopes/ "
                "directory (canonical location), or pass an explicit "
                "relative path from the session root (e.g. "
                "'templates/my.brk')."
            ),
        )])
    try:
        contents = resolved.read_bytes()
    except OSError as e:
        return BreakpointCompileResult(errors=[ErrorEntry(
            type="param_breakpoint_file_unreadable",
            message=(
                f"Parameter {param_name!r}: could not read .brk file "
                f"{resolved}: {e}."
            ),
            fix="Check file permissions.",
        )])
    sha = hashlib.sha256(contents).hexdigest()
    return BreakpointCompileResult(
        record=CompiledBreakpoint(
            path=str(resolved),
            sha256=sha,
            source_duration_s=None,
            source_kind="preexisting_brk",
        ),
        compiled_path=resolved,
    )


# ---------------------------------------------------------------------------
# List mode (relative + absolute)
# ---------------------------------------------------------------------------


def _compile_list_mode(
    *,
    param_name: str,
    param_spec: ParameterSpec,
    tuples: list,
    mode: Literal["relative", "absolute"],
    source_duration_s: float | None,
    source_kind: Literal[
        "input_wav", "pvoc_lineage", "ana_sfprops", "set_by_param",
        "dry_run_override", "dry_run_dummy",
    ] | None,
    envelopes_dir: Path,
) -> BreakpointCompileResult:
    errors: list[ErrorEntry] = []
    warnings: list[str] = []

    # Relative mode requires source_duration_s. Absolute mode can compile
    # without it (we just skip the auto-append step).
    if mode == "relative" and source_duration_s is None:
        return BreakpointCompileResult(errors=[ErrorEntry(
            type="param_breakpoint_no_source_duration",
            message=(
                f"Parameter {param_name!r}'s relative-time breakpoint "
                f"list can't be compiled — the input audio's duration "
                f"could not be resolved."
            ),
            fix=(
                "Use absolute timestamps (each first element prefixed "
                "with 'abs:'), or pre-convert the input via a prior "
                "process() call so its lineage records the source "
                "duration."
            ),
        )])

    # Validate + convert each tuple to absolute seconds.
    abs_points: list[tuple[float, float]] = []
    for i, pair in enumerate(tuples):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            errors.append(ErrorEntry(
                type="param_breakpoint_value_type",
                message=(
                    f"Parameter {param_name!r} breakpoint at index {i} "
                    f"is not a [time, value] pair: {pair!r}."
                ),
                fix="Each element must be a 2-item list [time, value].",
            ))
            continue
        t_raw, v_raw = pair[0], pair[1]
        if not isinstance(v_raw, (int, float)) or isinstance(v_raw, bool):
            errors.append(ErrorEntry(
                type="param_breakpoint_value_type",
                message=(
                    f"Parameter {param_name!r} breakpoint at index {i} "
                    f"has non-numeric value {v_raw!r}."
                ),
                fix="Each value must be an int or float.",
            ))
            continue
        if mode == "relative":
            if not isinstance(t_raw, (int, float)) or isinstance(t_raw, bool):
                errors.append(ErrorEntry(
                    type="param_breakpoint_value_type",
                    message=(
                        f"Parameter {param_name!r} breakpoint at index {i} "
                        f"has non-numeric relative time {t_raw!r}."
                    ),
                    fix="Relative-mode times must be numeric in [0, 1].",
                ))
                continue
            if not 0.0 <= float(t_raw) <= 1.0:
                errors.append(ErrorEntry(
                    type="param_breakpoint_time_out_of_range",
                    message=(
                        f"Parameter {param_name!r} breakpoint at index {i} "
                        f"has relative time {t_raw} outside [0, 1]."
                    ),
                    fix=(
                        "Relative times must be in [0, 1]. Use absolute "
                        "mode (prefix with 'abs:') if you need times "
                        "outside this range."
                    ),
                ))
                continue
            abs_t = float(t_raw) * source_duration_s
        else:  # absolute
            if not isinstance(t_raw, str) or not t_raw.startswith("abs:"):
                errors.append(ErrorEntry(
                    type="param_breakpoint_value_type",
                    message=(
                        f"Parameter {param_name!r} breakpoint at index {i} "
                        f"has invalid absolute-mode time {t_raw!r}."
                    ),
                    fix="Absolute-mode times must be strings like 'abs:1.5'.",
                ))
                continue
            try:
                abs_t = float(t_raw[len("abs:"):])
            except ValueError:
                errors.append(ErrorEntry(
                    type="param_breakpoint_value_type",
                    message=(
                        f"Parameter {param_name!r} breakpoint at index {i} "
                        f"has unparseable absolute time {t_raw!r}."
                    ),
                    fix="Use a numeric suffix like 'abs:1.5'.",
                ))
                continue
            if source_duration_s is not None and (
                abs_t < 0 or abs_t > source_duration_s + _DEDUP_EPSILON_S
            ):
                errors.append(ErrorEntry(
                    type="param_breakpoint_time_out_of_range",
                    message=(
                        f"Parameter {param_name!r} breakpoint at index {i} "
                        f"has absolute time {abs_t} outside "
                        f"[0, {source_duration_s}]."
                    ),
                    fix="Reduce the timestamp or use a longer input.",
                ))
                continue
        abs_points.append((abs_t, float(v_raw)))

    if errors:
        return BreakpointCompileResult(errors=errors, warnings=warnings)

    # Sort by time.
    abs_points.sort(key=lambda p: p[0])

    # Dedup near-identical timestamps.
    deduped: list[tuple[float, float]] = []
    for pt in abs_points:
        if deduped and (pt[0] - deduped[-1][0]) < _DEDUP_EPSILON_S:
            warnings.append(
                f"Parameter {param_name!r}: dropped near-identical "
                f"timestamp at {pt[0]:.6f}s (within "
                f"{_DEDUP_EPSILON_S}s of previous point)."
            )
            continue
        deduped.append(pt)

    # Auto-append final point if source_duration_s is known and the
    # last point is below it.
    if source_duration_s is not None:
        if deduped and deduped[-1][0] < source_duration_s - _DEDUP_EPSILON_S:
            deduped.append((source_duration_s, deduped[-1][1]))
    else:
        # Absolute mode without source_duration: skip auto-append; emit
        # advisory warning so users know.
        warnings.append(
            f"Parameter {param_name!r}: source_duration unknown — "
            f"auto-append of a final end-of-file point was skipped. CDP "
            f"will hold the last value past the final breakpoint."
        )

    # Compile + write.
    contents = _format_brk_contents(deduped)
    sha = hashlib.sha256(contents.encode("utf-8")).hexdigest()
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    out_path = envelopes_dir / f"{param_name}_{sha[:12]}.brk"
    if not out_path.exists():
        out_path.write_text(contents, encoding="utf-8")

    return BreakpointCompileResult(
        record=CompiledBreakpoint(
            path=str(out_path),
            sha256=sha,
            source_duration_s=source_duration_s,
            source_kind=source_kind or "input_wav",
        ),
        compiled_path=out_path,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _format_brk_contents(points: list[tuple[float, float]]) -> str:
    """Render ``points`` as a CDP-compatible .brk text block.

    One ``"<time> <value>\\n"`` line per point. Numbers are formatted as
    PLAIN DECIMALS, never scientific notation: the previous ``".10g"``
    convention rendered tiny values as e.g. ``1e-06``, which CDP's brk
    parser mis-tokenizes — the exponent shifts token alignment and the
    refusal surfaces as a misleading ``times not in increasing order``
    (field find, church-holiday session journal 2026-07-23; a synth wave
    amp envelope with a 1e-06 floor). ``".10f"`` with trailing-zero
    stripping keeps clean output (``0.5``, ``0.000001``) at the cost of
    flooring magnitudes below 5e-11 to ``0`` — far below anything CDP
    distinguishes. The argv scalar path (``processing._format_value``)
    deliberately keeps ``".10g"``: no CLI misparse has ever been
    evidenced, and repinning every argv test for an unevidenced risk
    would be guessing.
    """

    def _plain(x: float) -> str:
        s = f"{x:.10f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-") else "0"

    lines = [f"{_plain(t)} {_plain(v)}\n" for t, v in points]
    return "".join(lines)
