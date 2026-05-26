"""Unit tests for pre-flight duration prediction.

Covers the four DurationModel kinds (static, set_by, linear, expression)
and the three failure modes (evaluation_failed, negative, exceeds_cap).
Integration via process() lives in test_process.py.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.duration_preflight import (
    DurationModelError,
    _evaluate_duration_model,
    _read_duration_seconds,
    check_duration_preflight,
)
from cdp_mcp.schema import (
    DurationModelExpression,
    DurationModelLinear,
    DurationModelSetBy,
    DurationModelStatic,
    KnowledgeEntry,
    ParameterSpec,
)


def _make_entry(
    *,
    duration_model,
    parameters: dict[str, ParameterSpec] | None = None,
    program: str = "fake",
    mode: str = "fake",
    arity: int = 1,
) -> KnowledgeEntry:
    """Build a minimal KnowledgeEntry with the given duration_model."""
    return KnowledgeEntry(
        program=program, mode=mode, submode=None,
        category="test", domain="time",
        input_arity=arity, channel_constraint="any",
        input_format=".wav", output_format=".wav",
        stability="stable", phase_sensitive=False,
        stereo_link_default=None,
        duration_model=duration_model,
        curated=True, version_sensitive=False,
        description="test", musical_use="test",
        parameters=parameters or {},
        examples=[], known_issues=[], references=[],
    )


def _make_wav(path: Path, duration_s: float, sr: int = 44100) -> None:
    """Write a silent wav of the given duration. Header is enough; tests
    of pre-flight need sf.info to read a duration but don't care about
    content."""
    samples = np.zeros(int(duration_s * sr), dtype=np.float32)
    sf.write(str(path), samples, sr)


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------


def test_static_single_input_returns_indur():
    entry = _make_entry(duration_model=DurationModelStatic(kind="static"))
    assert _evaluate_duration_model(entry, {}, [30.0]) == 30.0


def test_static_multi_input_returns_max():
    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"), arity=2,
    )
    assert _evaluate_duration_model(entry, {}, [12.0, 30.0]) == 30.0


def test_static_all_none_returns_none():
    """Chain invariant — skip pre-flight."""
    entry = _make_entry(duration_model=DurationModelStatic(kind="static"))
    assert _evaluate_duration_model(entry, {}, [None]) is None


def test_static_mixed_none_uses_known_max():
    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"), arity=2,
    )
    assert _evaluate_duration_model(entry, {}, [None, 42.0]) == 42.0


# ---------------------------------------------------------------------------
# set_by
# ---------------------------------------------------------------------------


def test_set_by_returns_param_value_as_float():
    entry = _make_entry(
        duration_model=DurationModelSetBy(kind="set_by", param="dur"),
    )
    assert _evaluate_duration_model(entry, {"dur": 42.5}, [10.0]) == 42.5


def test_set_by_missing_param_raises():
    entry = _make_entry(
        duration_model=DurationModelSetBy(kind="set_by", param="dur"),
    )
    with pytest.raises(DurationModelError, match="dur"):
        _evaluate_duration_model(entry, {}, [10.0])


def test_set_by_non_numeric_param_raises():
    entry = _make_entry(
        duration_model=DurationModelSetBy(kind="set_by", param="dur"),
    )
    with pytest.raises(DurationModelError, match="not numeric"):
        _evaluate_duration_model(entry, {"dur": "abc"}, [10.0])


# ---------------------------------------------------------------------------
# linear (currently identical to set_by in Phase 1b)
# ---------------------------------------------------------------------------


def test_linear_returns_param_value():
    """Phase 1b: linear evaluates as outdur = float(params[param]).
    Same as set_by until the schema gains a multiplier field."""
    entry = _make_entry(
        duration_model=DurationModelLinear(kind="linear", param="cnt"),
    )
    assert _evaluate_duration_model(entry, {"cnt": 8}, [10.0]) == 8.0


# ---------------------------------------------------------------------------
# expression
# ---------------------------------------------------------------------------


def test_expression_arithmetic_with_params():
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="cnt * len / 1000",
        ),
    )
    result = _evaluate_duration_model(
        entry, {"cnt": 8, "len": 200.0}, [10.0],
    )
    assert result == pytest.approx(1.6)


def test_expression_uses_indur():
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
    )
    result = _evaluate_duration_model(
        entry, {"velocity": 0.5}, [10.0],
    )
    assert result == pytest.approx(20.0)


def test_expression_multi_indur():
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur1 + indur2",
        ),
        arity=2,
    )
    result = _evaluate_duration_model(entry, {}, [3.0, 4.5])
    assert result == pytest.approx(7.5)


def test_expression_division_by_zero_raises():
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
    )
    with pytest.raises(DurationModelError, match="ZeroDivisionError"):
        _evaluate_duration_model(entry, {"velocity": 0}, [10.0])


def test_expression_unknown_identifier_raises():
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur * mystery_var",
        ),
    )
    with pytest.raises(DurationModelError, match="NameNotDefined"):
        _evaluate_duration_model(entry, {}, [10.0])


def test_expression_function_calls_forbidden():
    """simpleeval is configured with functions={} — int(), max(),
    math.sqrt(), etc. all raise."""
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="int(indur * 2)",
        ),
    )
    with pytest.raises(DurationModelError):
        _evaluate_duration_model(entry, {}, [10.0])


def test_expression_attribute_access_forbidden():
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur.__class__",
        ),
    )
    with pytest.raises(DurationModelError):
        _evaluate_duration_model(entry, {}, [10.0])


def test_expression_indur_none_skips_when_referenced():
    """Chain invariant: when indur is None (e.g., a .ana input) AND
    the expression references indur, return None (skip pre-flight).
    The Task 7 watchdog is the reactive guardrail. Task 8's lineage
    will close this gap by recording source_wav_duration_s for
    chained .ana inputs."""
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
    )
    result = _evaluate_duration_model(entry, {"velocity": 0.5}, [None])
    assert result is None


def test_expression_no_indur_reference_works_even_when_indur_unknown():
    """Expr that doesn't reference indur evaluates fine even with None
    inputs."""
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="2 * x + 1",
        ),
    )
    result = _evaluate_duration_model(entry, {"x": 5}, [None])
    assert result == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# check_duration_preflight — top-level integration
# ---------------------------------------------------------------------------


def test_preflight_passes_when_predicted_under_cap(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
        parameters={"velocity": ParameterSpec(type="float")},
    )
    errors = check_duration_preflight(
        entry=entry, params={"velocity": 0.5},
        resolved_inputs=[input_wav],
    )
    assert errors == []


def test_preflight_rejects_when_exceeds_cap(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
        parameters={"velocity": ParameterSpec(type="float")},
    )
    # 2.0 / 0.001 = 2000s, way over the 300s cap.
    errors = check_duration_preflight(
        entry=entry, params={"velocity": 0.001},
        resolved_inputs=[input_wav],
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_exceeds_cap"
    assert "2000" in errors[0].message
    assert "300" in errors[0].message


def test_preflight_rejects_when_negative(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur - long_offset",
        ),
        parameters={"long_offset": ParameterSpec(type="float")},
    )
    errors = check_duration_preflight(
        entry=entry, params={"long_offset": 5.0},
        resolved_inputs=[input_wav],
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_negative"


def test_preflight_rejects_on_evaluation_failure(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
        parameters={"velocity": ParameterSpec(type="float")},
    )
    errors = check_duration_preflight(
        entry=entry, params={"velocity": 0},
        resolved_inputs=[input_wav],
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_evaluation_failed"


def test_preflight_skips_when_static_indur_unknown(tmp_path):
    """`.ana` input → soundfile.info() fails → indur is None → static
    falls back to skip (chain invariant)."""
    ana_input = tmp_path / "in.ana"
    ana_input.write_bytes(b"fake ana data")  # not a real .ana, sf.info fails
    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"),
    )
    errors = check_duration_preflight(
        entry=entry, params={}, resolved_inputs=[ana_input],
    )
    assert errors == []


def test_preflight_can_override_cap(tmp_path):
    """The cap is a kwarg for testability; tests can tighten it."""
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"),
    )
    errors = check_duration_preflight(
        entry=entry, params={}, resolved_inputs=[input_wav],
        duration_cap_s=1.0,  # tighter than the 2-second input
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_exceeds_cap"


# ---------------------------------------------------------------------------
# _read_duration_seconds — header-only read
# ---------------------------------------------------------------------------


def test_read_duration_seconds_wav(tmp_path):
    p = tmp_path / "in.wav"
    _make_wav(p, duration_s=3.5)
    assert _read_duration_seconds(p) == pytest.approx(3.5, abs=0.01)


def test_read_duration_seconds_unreadable_returns_none(tmp_path):
    p = tmp_path / "fake.ana"
    p.write_bytes(b"not a real audio file")
    assert _read_duration_seconds(p) is None


def test_read_duration_seconds_nonexistent_returns_none(tmp_path):
    assert _read_duration_seconds(tmp_path / "missing.wav") is None
