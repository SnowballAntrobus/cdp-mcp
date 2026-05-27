"""Pre-flight duration prediction for ``process()``.

Evaluates a curated entry's ``duration_model`` against the supplied
parameters and input durations, and returns structured ``ErrorEntry``
items when the predicted output duration violates the cap or doesn't
compute cleanly. Complements the reactive disk watchdog (Task 7) —
pre-flight catches cleanly-curated mis-parameterizations cheaply
(before CDP spawns); the watchdog catches everything pre-flight can't
predict.

Expressions are evaluated via ``simpleeval`` (single-file, zero-deps,
no function calls allowed). The threat surface is curated JSON entries,
not user input, so the safety story is defense in depth rather than
first-line protection.

A note on .ana inputs: ``soundfile.info()`` doesn't read CDP's .ana
format, so input durations for .ana files are ``None`` in Phase 1b.
The evaluator handles ``None`` per-kind. Task 8's lineage
``source_wav_duration_s`` field will fill in the chained case; pre-
converted .ana files in ``inputs/`` remain a gap with no current
solution. The watchdog (Task 7) covers either way.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import soundfile as sf
from simpleeval import InvalidExpression, SimpleEval

from .limits import OUTPUT_DURATION_CAP_S
from .schema import (
    DurationModelExpression,
    DurationModelLinear,
    DurationModelSetBy,
    DurationModelStatic,
    ErrorEntry,
    KnowledgeEntry,
)


class DurationModelError(Exception):
    """Raised inside ``_evaluate_duration_model`` for any computational
    failure. Caught at the top level and converted to a structured
    ``predicted_duration_evaluation_failed`` ``ErrorEntry``."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_duration_seconds(path: Path) -> float | None:
    """Header-only audio duration via ``soundfile.info()``.

    Returns ``None`` for any read failure — including ``.ana`` files,
    which soundfile doesn't support. Never raises; ``None`` is the
    sentinel for "duration unknown, fall back to chain invariant or
    skip."
    """
    try:
        info = sf.info(str(path))
        return float(info.duration)
    except Exception:  # noqa: BLE001 — soundfile raises a variety
        return None


def _evaluate_duration_model(
    entry: KnowledgeEntry,
    params: dict[str, Any],
    indurs: list[float | None],
) -> float | None:
    """Compute predicted output duration in seconds.

    Returns ``None`` when the model can't be evaluated and skipping is
    the right call (chain invariant — upstream already respected the
    cap). Raises ``DurationModelError`` for genuine evaluation
    failures.
    """
    model = entry.duration_model

    if isinstance(model, DurationModelStatic):
        known = [d for d in indurs if d is not None]
        if not known:
            return None  # chain invariant — skip pre-flight
        return max(known)

    if isinstance(model, (DurationModelSetBy, DurationModelLinear)):
        # Phase 1b: `linear` is currently identical to `set_by`. The
        # schema's `linear` kind doesn't encode a multiplier field, so
        # we evaluate as `outdur = float(params[param])`. The kind tag
        # is preserved for future schema refinement.
        param_name = model.param
        if param_name not in params:
            raise DurationModelError(
                f"duration_model references parameter "
                f"{param_name!r}, which is not in the supplied params "
                f"dict (validate_params should have caught this; "
                f"likely a curation defect)."
            )
        try:
            return float(params[param_name])
        except (TypeError, ValueError) as e:
            raise DurationModelError(
                f"duration_model parameter {param_name!r} = "
                f"{params[param_name]!r} is not numeric: {e}"
            ) from e

    if isinstance(model, DurationModelExpression):
        # Chain invariant: if any input duration is None (e.g. a .ana
        # file, which soundfile.info doesn't read) AND the expression
        # references indur, skip pre-flight. The Task 7 watchdog
        # catches runaways post-spawn. Task 8's lineage will close
        # this gap by recording source_wav_duration_s for chained
        # .ana inputs. The "indur" substring check is conservative
        # — it also matches names like "indur1", "indur2" — but that
        # IS the intent: any missing input duration that the expression
        # might reference means we can't predict.
        if any(d is None for d in indurs) and "indur" in model.expr:
            return None

        # Task 8: if any param is a breakpoint value (list or .brk path),
        # pre-flight can't predict — the parameter varies over time.
        # Skip; the Task 7 watchdog catches runaway output, and the
        # breakpoint compiler (step 8.5 in process.py) runs structured
        # validation independently.
        for name, value in params.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                if name in model.expr:
                    return None

        names: dict[str, Any] = dict(params)
        # Single-input convenience: indur is the lone input duration.
        if len(indurs) == 1 and indurs[0] is not None:
            names["indur"] = indurs[0]
        # Multi-input: indur1, indur2, ... for each known duration.
        for i, d in enumerate(indurs):
            if d is not None:
                names[f"indur{i + 1}"] = d

        evaluator = SimpleEval(names=names, functions={})
        try:
            result = evaluator.eval(model.expr)
        except (InvalidExpression, ZeroDivisionError, OverflowError) as e:
            raise DurationModelError(
                f"failed to evaluate expression {model.expr!r}: "
                f"{type(e).__name__}: {e}"
            ) from e

        try:
            value = float(result)
        except (TypeError, ValueError) as e:
            raise DurationModelError(
                f"expression {model.expr!r} did not produce a numeric "
                f"value (got {result!r} of type "
                f"{type(result).__name__})"
            ) from e

        if not math.isfinite(value):
            raise DurationModelError(
                f"expression {model.expr!r} produced a non-finite "
                f"result ({value!r}) — likely division by zero or "
                f"overflow."
            )
        return value

    # Unreachable: the discriminated union covers all cases.
    raise DurationModelError(f"unknown duration_model kind: {model!r}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_duration_preflight(
    *,
    entry: KnowledgeEntry,
    params: dict[str, Any],
    resolved_inputs: list[Path],
    duration_cap_s: float = OUTPUT_DURATION_CAP_S,
) -> list[ErrorEntry]:
    """Pre-flight duration prediction.

    Returns structured errors on rejection, empty list on pass (or
    skip — when the chain invariant lets us defer to the watchdog).

    Three failure modes:
    - ``predicted_duration_evaluation_failed`` — model couldn't be
      computed (bad expression, missing param, division by zero,
      unknown identifier).
    - ``predicted_duration_negative`` — evaluated to ≤ 0.
    - ``predicted_duration_exceeds_cap`` — predicted > duration_cap_s.
    """
    indurs = [_read_duration_seconds(p) for p in resolved_inputs]

    try:
        predicted = _evaluate_duration_model(entry, params, indurs)
    except DurationModelError as e:
        return [ErrorEntry(
            type="predicted_duration_evaluation_failed",
            message=str(e),
            fix=(
                "The duration_model for this entry couldn't be computed "
                "against your parameters. This is likely a curation "
                "defect. Either correct the parameters and retry, or "
                "call this via execute() to bypass pre-flight — the "
                "disk watchdog still protects against runaway output."
            ),
        )]

    if predicted is None:
        return []  # chain invariant — skip pre-flight

    if predicted <= 0:
        return [ErrorEntry(
            type="predicted_duration_negative",
            message=f"predicted output duration {predicted:.3f}s is <= 0",
            fix=(
                "Review your parameters — one or more values are "
                "producing a non-positive duration (for example, "
                "subtracting an offset larger than the input)."
            ),
        )]

    if predicted > duration_cap_s:
        return [ErrorEntry(
            type="predicted_duration_exceeds_cap",
            message=(
                f"predicted output duration {predicted:.1f}s exceeds "
                f"the {duration_cap_s:.0f}s cap"
            ),
            fix=(
                "Reduce the parameter values that drive duration "
                "(counts, multipliers, time spans), or split the "
                "operation into multiple shorter calls."
            ),
        )]

    return []
