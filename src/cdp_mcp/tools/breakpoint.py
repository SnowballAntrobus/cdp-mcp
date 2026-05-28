"""The ``breakpoint()`` MCP tool — named-shape breakpoint envelope constructor.

Phase 2 Task 6. A pure constructor: it generates relative-time tuple lists
in named shapes (``linear``, ``exponential``, ``sigmoid``, ``pulse_train``,
``step``, ``random``) that the LLM then passes as a parameter value to
``process()``. The existing Phase 1b breakpoint compiler consumes the
output unchanged — ``breakpoint()`` adds no new compiler path.

Why a separate tool rather than inline ``process()`` syntax: construction-
time validation. ``breakpoint()`` rejects "this parameter isn't
breakpoint-capable" *when the envelope is built*, with an isolated, early
error — rather than burying it inside a later ``process()`` call mixed with
everything else process validates.

Output is always relative-time: times in ``[0.0, duration_relative]``,
values in the parameter's units. The compiler resolves relative→absolute
against the source duration at ``process()`` time, exactly as it does for
hand-written relative tuples. ``breakpoint()`` never needs the source
duration.
"""

from __future__ import annotations

import math

import numpy as np
from mcp.server.fastmcp import FastMCP

from ..knowledge.loader import KnowledgeIndex
from ..schema import ErrorEntry, ParameterSpec

# Sharp transitions (step / pulse_train edges) need two points straddling
# the transition time. The gap must exceed the compiler's 1e-6 dedup
# threshold or the points collapse and the step softens into a ramp. 1e-3
# in relative-time units is sharp enough audibly while staying well clear
# of dedup.
_EDGE_EPS = 1e-3

_VALID_SHAPES = frozenset(
    {"linear", "exponential", "sigmoid", "pulse_train", "step", "random", "custom"}
)


class _ShapeArgsError(Exception):
    """Raised by a shape generator when required kwargs are missing or
    invalid. Caught in :func:`breakpoint_impl` and converted to a
    structured ``breakpoint_shape_args`` error."""


class _CustomPointError(Exception):
    """Raised by :func:`_shape_custom` when an agent-supplied point is
    structurally invalid. Carries the compiler's error ``type`` so the
    early validation surfaces the *same* error the compiler would raise
    at ``process()`` time — identical feedback whether validated early
    or hit cold."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


# ---------------------------------------------------------------------------
# Pure shape generators — the unit-test targets. Each returns a list of
# ``[time, value]`` pairs with the first time at 0.0 and the last at
# ``duration_relative``.
# ---------------------------------------------------------------------------


def _round(v: float) -> float:
    """Round computed values for readable transcription. Deterministic, so
    reproducibility (``random`` seed) is preserved. Clean anchor values
    (e.g. 200.0) are unaffected."""
    return round(float(v), 6)


def _segments_to_breakpoints(
    segments: list[tuple[float, float]], duration_relative: float
) -> list[list[float]]:
    """Convert piecewise-constant ``(start_time, value)`` segments into
    linear-interp breakpoints with sharp edges.

    Each segment boundary gets a straddle pair: ``(t - eps, prev_value)``
    then ``(t, value)``, so CDP's linear interpolation renders a near-
    vertical step rather than a ramp. The final value is held to
    ``duration_relative``.
    """
    pts: list[list[float]] = []
    for i, (t, v) in enumerate(segments):
        if i == 0:
            pts.append([0.0, _round(v)])
        else:
            prev_v = segments[i - 1][1]
            pts.append([_round(t - _EDGE_EPS), _round(prev_v)])
            pts.append([_round(t), _round(v)])
    pts.append([_round(duration_relative), _round(segments[-1][1])])
    return pts


def _shape_linear(
    *, start: float | None, end: float | None, duration_relative: float
) -> list[list[float]]:
    if start is None or end is None:
        raise _ShapeArgsError("shape 'linear' requires 'start' and 'end'.")
    return [[0.0, _round(start)], [_round(duration_relative), _round(end)]]


def _shape_exponential(
    *,
    start: float | None,
    end: float | None,
    duration_relative: float,
    curve: float | None,
    points: int | None,
) -> list[list[float]]:
    if start is None or end is None:
        raise _ShapeArgsError("shape 'exponential' requires 'start' and 'end'.")
    c = 2.0 if curve is None else curve
    n = 12 if points is None else points
    if n < 2:
        raise _ShapeArgsError("shape 'exponential' requires points >= 2.")
    if c <= 0:
        raise _ShapeArgsError("shape 'exponential' requires curve > 0.")
    pts: list[list[float]] = []
    for i in range(n):
        u = i / (n - 1)
        t = u * duration_relative
        v = start + (end - start) * (u ** c)
        pts.append([_round(t), _round(v)])
    return pts


def _shape_sigmoid(
    *,
    start: float | None,
    end: float | None,
    duration_relative: float,
    steepness: float | None,
    points: int | None,
) -> list[list[float]]:
    if start is None or end is None:
        raise _ShapeArgsError("shape 'sigmoid' requires 'start' and 'end'.")
    k = 6.0 if steepness is None else steepness
    n = 12 if points is None else points
    if n < 2:
        raise _ShapeArgsError("shape 'sigmoid' requires points >= 2.")
    if k <= 0:
        raise _ShapeArgsError("shape 'sigmoid' requires steepness > 0.")

    def logistic(u: float) -> float:
        return 1.0 / (1.0 + math.exp(-k * (u - 0.5)))

    s0 = logistic(0.0)
    s1 = logistic(1.0)
    pts: list[list[float]] = []
    for i in range(n):
        u = i / (n - 1)
        s_norm = (logistic(u) - s0) / (s1 - s0)
        t = u * duration_relative
        v = start + (end - start) * s_norm
        pts.append([_round(t), _round(v)])
    return pts


def _shape_pulse_train(
    *,
    low: float | None,
    high: float | None,
    duration_relative: float,
    count: int | None,
    duty: float | None,
) -> list[list[float]]:
    if low is None or high is None:
        raise _ShapeArgsError("shape 'pulse_train' requires 'low' and 'high'.")
    c = 4 if count is None else count
    d = 0.5 if duty is None else duty
    if c < 1:
        raise _ShapeArgsError("shape 'pulse_train' requires count >= 1.")
    if not 0.0 < d < 1.0:
        raise _ShapeArgsError("shape 'pulse_train' requires 0 < duty < 1.")
    period = duration_relative / c
    segments: list[tuple[float, float]] = []
    for k in range(c):
        period_start = k * period
        fall_t = period_start + d * period
        segments.append((period_start, high))  # rising edge → high
        segments.append((fall_t, low))         # falling edge → low
    return _segments_to_breakpoints(segments, duration_relative)


def _shape_step(
    *,
    start: float | None,
    end: float | None,
    steps: int | None,
    values: list[float] | None,
    duration_relative: float,
) -> list[list[float]]:
    if values is not None:
        if len(values) < 1:
            raise _ShapeArgsError("shape 'step' with 'values' needs a non-empty list.")
        n = len(values)
        segments = [
            ((i / n) * duration_relative, float(values[i])) for i in range(n)
        ]
        return _segments_to_breakpoints(segments, duration_relative)
    # Generated form.
    if start is None or end is None:
        raise _ShapeArgsError(
            "shape 'step' requires either 'values' or ('start' and 'end')."
        )
    s = 4 if steps is None else steps
    if s < 1:
        raise _ShapeArgsError("shape 'step' requires steps >= 1.")
    segments = []
    for i in range(s):
        level = start if s == 1 else start + (end - start) * (i / (s - 1))
        segments.append(((i / s) * duration_relative, level))
    return _segments_to_breakpoints(segments, duration_relative)


def _shape_random(
    *,
    low: float | None,
    high: float | None,
    duration_relative: float,
    points: int | None,
    seed: int | None,
) -> list[list[float]]:
    if low is None or high is None:
        raise _ShapeArgsError("shape 'random' requires 'low' and 'high'.")
    n = 8 if points is None else points
    if n < 1:
        raise _ShapeArgsError("shape 'random' requires points >= 1.")
    # Instance-scoped RNG — never touches global numpy RNG state (Task 2.5
    # found global RNG mutation is a test-contamination vector). Same seed →
    # identical output across calls and sessions.
    rng = np.random.default_rng(seed)
    draws = rng.uniform(low, high, size=n)
    pts: list[list[float]] = []
    for i in range(n):
        u = 0.0 if n == 1 else i / (n - 1)
        pts.append([_round(u * duration_relative), _round(draws[i])])
    return pts


def _shape_custom(*, pairs: list[list[float]] | None) -> list[list[float]]:
    """Passthrough for agent-authored points — the 'verbal description →
    arbitrary envelope' path, with the same early validation the named
    shapes get.

    Structural checks mirror the compiler (``breakpoint_compiler.py``)
    so the agent sees identical feedback whether validating here or at
    ``process()`` time. Relative-time only (times in [0, 1]); the
    ``"abs:"`` escape hatch stays raw-tuples-only. Values are preserved
    exactly (not rounded — they're the agent's authored numbers). Points
    are returned sorted by time; near-duplicate dedup is left to the
    compiler.
    """
    if not pairs:
        raise _ShapeArgsError(
            "shape 'custom' requires 'pairs' — a list of [time, value] points."
        )
    if len(pairs) < 2:
        raise _ShapeArgsError(
            "shape 'custom' requires at least 2 points; a single point is a "
            "constant — pass a scalar parameter value instead."
        )
    validated: list[list[float]] = []
    for i, pair in enumerate(pairs):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise _CustomPointError(
                "param_breakpoint_value_type",
                f"custom point at index {i} is not a [time, value] pair: {pair!r}.",
            )
        t_raw, v_raw = pair[0], pair[1]
        if not isinstance(v_raw, (int, float)) or isinstance(v_raw, bool):
            raise _CustomPointError(
                "param_breakpoint_value_type",
                f"custom point at index {i} has non-numeric value {v_raw!r}.",
            )
        if not isinstance(t_raw, (int, float)) or isinstance(t_raw, bool):
            raise _CustomPointError(
                "param_breakpoint_value_type",
                f"custom point at index {i} has non-numeric time {t_raw!r}.",
            )
        if not 0.0 <= float(t_raw) <= 1.0:
            raise _CustomPointError(
                "param_breakpoint_time_out_of_range",
                f"custom point at index {i} has relative time {t_raw} "
                f"outside [0, 1]. (Absolute times need the raw-tuple "
                f"'abs:' escape hatch passed directly to process().)",
            )
        validated.append([float(t_raw), float(v_raw)])
    validated.sort(key=lambda p: p[0])
    return validated


def _generate(
    shape: str,
    *,
    start: float | None,
    end: float | None,
    low: float | None,
    high: float | None,
    duration_relative: float,
    points: int | None,
    count: int | None,
    steps: int | None,
    values: list[float] | None,
    pairs: list[list[float]] | None,
    curve: float | None,
    steepness: float | None,
    duty: float | None,
    seed: int | None,
) -> list[list[float]]:
    """Dispatch to the right shape generator. Raises :class:`_ShapeArgsError`
    for unknown shapes or missing/invalid kwargs, or :class:`_CustomPointError`
    for structurally bad custom points."""
    if shape not in _VALID_SHAPES:
        raise _ShapeArgsError(
            f"unknown shape {shape!r}; valid shapes: {sorted(_VALID_SHAPES)}."
        )
    # duration_relative scales generated-shape times into [0, duration_relative];
    # the compiler validates relative times in [0, 1], so values > 1 would be
    # rejected later. Guard early. (custom ignores duration_relative — it
    # supplies its own times — but the default 1.0 passes the guard.)
    if not 0.0 < duration_relative <= 1.0:
        raise _ShapeArgsError("duration_relative must be in (0, 1].")
    if shape == "custom":
        return _shape_custom(pairs=pairs)
    if shape == "linear":
        return _shape_linear(start=start, end=end, duration_relative=duration_relative)
    if shape == "exponential":
        return _shape_exponential(
            start=start, end=end, duration_relative=duration_relative,
            curve=curve, points=points,
        )
    if shape == "sigmoid":
        return _shape_sigmoid(
            start=start, end=end, duration_relative=duration_relative,
            steepness=steepness, points=points,
        )
    if shape == "pulse_train":
        return _shape_pulse_train(
            low=low, high=high, duration_relative=duration_relative,
            count=count, duty=duty,
        )
    if shape == "step":
        return _shape_step(
            start=start, end=end, steps=steps, values=values,
            duration_relative=duration_relative,
        )
    # shape == "random"
    return _shape_random(
        low=low, high=high, duration_relative=duration_relative,
        points=points, seed=seed,
    )


# ---------------------------------------------------------------------------
# Range helpers (min/max may be None → that bound is unconstrained)
# ---------------------------------------------------------------------------


def _below_min(v: float, spec: ParameterSpec) -> bool:
    return spec.min is not None and v < spec.min


def _above_max(v: float, spec: ParameterSpec) -> bool:
    return spec.max is not None and v > spec.max


def _clamp(v: float, spec: ParameterSpec) -> float:
    if spec.min is not None and v < spec.min:
        return spec.min
    if spec.max is not None and v > spec.max:
        return spec.max
    return v


# ---------------------------------------------------------------------------
# Implementation entry point
# ---------------------------------------------------------------------------


async def breakpoint_impl(
    shape: str,
    program: str,
    mode: str,
    param: str,
    *,
    start: float | None = None,
    end: float | None = None,
    low: float | None = None,
    high: float | None = None,
    duration_relative: float = 1.0,
    points: int | None = None,
    count: int | None = None,
    steps: int | None = None,
    values: list[float] | None = None,
    pairs: list[list[float]] | None = None,
    curve: float | None = None,
    steepness: float | None = None,
    duty: float | None = None,
    seed: int | None = None,
    knowledge_index: KnowledgeIndex,
) -> dict:
    """Build a relative-time breakpoint envelope of the named ``shape`` for
    ``(program, mode).param``, validated against the curated knowledge entry.

    ``shape="custom"`` takes the agent's own ``pairs=[[time, value], ...]``
    (relative times in [0, 1]) — the freeform path for shapes no named
    generator covers — and runs them through the same validation.

    Returns a light dict (no subprocess, no session state):
    ``{status, breakpoints, shape, target, point_count, errors, warnings}``.
    On success the LLM passes ``breakpoints`` straight to
    ``process(params={param: <breakpoints>})``.
    """
    target = f"{program} {mode}.{param}"
    warnings: list[str] = []

    def _fail(error: ErrorEntry) -> dict:
        return {
            "status": "failed",
            "breakpoints": None,
            "shape": shape,
            "target": target,
            "point_count": 0,
            "errors": [error.model_dump()],
            "warnings": warnings,
        }

    # 1. Entry lookup.
    entry = knowledge_index.get(program, mode)
    if entry is None or not entry.curated:
        return _fail(ErrorEntry(
            type="not_curated",
            message=f"No curated knowledge entry for {program!r} {mode!r}.",
            fix=(
                "Use list_programs() to see curated entries. breakpoint() "
                "only targets curated parameters."
            ),
        ))

    # 2. Param exists.
    if param not in entry.parameters:
        return _fail(ErrorEntry(
            type="unknown_parameter",
            message=(
                f"{program} {mode} has no parameter {param!r}. "
                f"Parameters: {sorted(entry.parameters)}."
            ),
            fix="Pass one of the listed parameter names.",
        ))
    spec = entry.parameters[param]

    # 3. Breakpoint-capable. Same error type process() raises — consistent
    # signal, surfaced early (the reason this is a separate tool).
    if not spec.breakpoint_capable:
        return _fail(ErrorEntry(
            type="param_breakpoint_not_capable",
            message=(
                f"Parameter {param!r} of {program} {mode} is not "
                f"breakpoint-capable; CDP rejects envelope files here."
            ),
            fix=(
                "Pass a constant scalar value for this parameter instead. "
                "Breakpoint-capable parameters for this entry: "
                f"{sorted(n for n, s in entry.parameters.items() if s.breakpoint_capable)}."
            ),
        ))

    # 4 + 5. Validate shape kwargs and generate.
    try:
        pts = _generate(
            shape,
            start=start, end=end, low=low, high=high,
            duration_relative=duration_relative,
            points=points, count=count, steps=steps, values=values,
            pairs=pairs, curve=curve, steepness=steepness, duty=duty, seed=seed,
        )
    except _ShapeArgsError as e:
        return _fail(ErrorEntry(
            type="breakpoint_shape_args",
            message=str(e),
            fix="Supply the kwargs the shape requires; see the tool docstring.",
        ))
    except _CustomPointError as e:
        # Structural problem in agent-supplied custom points; surface the
        # same error type the compiler would raise at process() time.
        return _fail(ErrorEntry(
            type=e.error_type,
            message=str(e),
            fix="Each custom point must be [relative_time (0-1), value].",
        ))

    # 6a. Explicit user-supplied values out of [min,max] → fail. These are
    # deliberate intent; failing is clearer than silently reshaping it.
    # For custom, every point is hand-authored, so all points are checked;
    # for named shapes, the anchors (start/end/low/high) are.
    if shape == "custom":
        for i, p in enumerate(pts):
            if _below_min(p[1], spec) or _above_max(p[1], spec):
                return _fail(ErrorEntry(
                    type="param_out_of_range",
                    message=(
                        f"custom point at index {i} value {p[1]} is outside "
                        f"the valid range for {param!r} (min={spec.min}, "
                        f"max={spec.max})."
                    ),
                    fix=f"Keep every point's value within [{spec.min}, {spec.max}].",
                ))
    else:
        for name, val in (("start", start), ("end", end), ("low", low), ("high", high)):
            if val is None:
                continue
            if _below_min(val, spec) or _above_max(val, spec):
                return _fail(ErrorEntry(
                    type="param_out_of_range",
                    message=(
                        f"{name}={val} is outside the valid range for {param!r} "
                        f"(min={spec.min}, max={spec.max})."
                    ),
                    fix=f"Choose {name} within [{spec.min}, {spec.max}].",
                ))

    # 6b. Generated values out of range → clamp + warn (defensive; the
    # current shapes don't overshoot in-range anchors, but a future shape
    # might).
    clamped = 0
    for p in pts:
        cv = _clamp(p[1], spec)
        if cv != p[1]:
            p[1] = _round(cv)
            clamped += 1
    if clamped:
        warnings.append(
            f"{clamped} generated value(s) were outside "
            f"[{spec.min}, {spec.max}] and were clamped to the bound."
        )

    # 7. Musical-range advisory (warning only, never an error).
    if spec.musical_range is not None:
        lo, hi = spec.musical_range
        outside = sum(1 for p in pts if not (lo <= p[1] <= hi))
        if outside:
            warnings.append(
                f"{outside} value(s) fall outside the musical range "
                f"[{lo}, {hi}] (advisory only)."
            )

    return {
        "status": "ok",
        "breakpoints": pts,
        "shape": shape,
        "target": target,
        "point_count": len(pts),
        "errors": [],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP, knowledge_index: KnowledgeIndex) -> None:
    """Register the ``breakpoint`` tool against ``mcp``.

    Thin wrapper around :func:`breakpoint_impl` — the implementation lives
    at module scope so in-process callers (tests, scripts) can invoke it
    without the MCP layer. The only dependency is the knowledge index
    (for construction-time validation); ``breakpoint()`` is a pure
    constructor — no sessions, no CDP, no cache.
    """

    @mcp.tool()
    async def breakpoint(  # noqa: A001 — intentional MCP tool name (shadows builtin locally only)
        shape: str,
        program: str,
        mode: str,
        param: str,
        start: float | None = None,
        end: float | None = None,
        low: float | None = None,
        high: float | None = None,
        duration_relative: float = 1.0,
        points: int | None = None,
        count: int | None = None,
        steps: int | None = None,
        values: list[float] | None = None,
        pairs: list[list[float]] | None = None,
        curve: float | None = None,
        steepness: float | None = None,
        duty: float | None = None,
        seed: int | None = None,
    ) -> dict:
        """Construct a breakpoint envelope for a curated parameter.

        Use this when the user describes a parameter that should *vary over
        time* (a rising filter sweep, an S-curve crossfade, random jitter)
        rather than hold a constant value. It returns a list of
        ``[time, value]`` points; pass that list straight back as the
        parameter's value in a following ``process()`` call.

        ``shape`` is one of:

        - ``linear`` — straight ramp. Needs ``start``, ``end``.
        - ``exponential`` — curved ramp. Needs ``start``, ``end``; optional
          ``curve`` (default 2.0; >1 slow-start, <1 fast-start), ``points``
          (default 12).
        - ``sigmoid`` — S-curve (slow, fast through the middle, slow). Needs
          ``start``, ``end``; optional ``steepness`` (default 6.0),
          ``points`` (default 12).
        - ``pulse_train`` — square on/off wave. Needs ``low``, ``high``;
          optional ``count`` (pulses, default 4), ``duty`` (high fraction,
          default 0.5).
        - ``step`` — held levels with jumps. Either ``values=[...]`` for
          explicit levels, or ``start``/``end``/``steps`` (default 4) for
          evenly-spaced levels.
        - ``random`` — random values. Needs ``low``, ``high``; optional
          ``points`` (default 8), ``seed`` (pass a seed for reproducible
          output — same seed always yields the same envelope).
        - ``custom`` — your own arbitrary shape when no named curve fits
          (e.g. "swell, hold, then cut"). Supply ``pairs=[[time, value],
          ...]`` with relative times in [0, 1] (at least 2 points). Gets
          the same capability/range validation as the named shapes — so
          a freeform envelope for a non-capable parameter, or with an
          out-of-range value, is caught here, not inside ``process()``.

        ``program``/``mode``/``param`` name the target. The tool validates
        that the parameter is breakpoint-capable and rejects with a clear
        error if not — so you learn here, not inside a later ``process()``
        call, whether an envelope is allowed.

        Times are relative: 0.0 is the start of the output, 1.0 (the default
        ``duration_relative``) is the end. The actual seconds are resolved
        at ``process()`` time against the source audio's duration.
        """
        return await breakpoint_impl(
            shape, program, mode, param,
            start=start, end=end, low=low, high=high,
            duration_relative=duration_relative,
            points=points, count=count, steps=steps, values=values,
            pairs=pairs, curve=curve, steepness=steepness, duty=duty, seed=seed,
            knowledge_index=knowledge_index,
        )
