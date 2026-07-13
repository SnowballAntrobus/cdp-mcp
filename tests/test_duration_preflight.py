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
    """linear evaluates as outdur = float(params[param]) — currently
    identical to set_by until the schema gains a multiplier field."""
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


async def test_preflight_passes_when_predicted_under_cap(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
        parameters={"velocity": ParameterSpec(type="float")},
    )
    errors = await check_duration_preflight(
        entry=entry, params={"velocity": 0.5},
        resolved_inputs=[input_wav],
    )
    assert errors == []


async def test_preflight_rejects_when_exceeds_cap(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
        parameters={"velocity": ParameterSpec(type="float")},
    )
    # 2.0 / 0.001 = 2000s, way over the 300s cap.
    errors = await check_duration_preflight(
        entry=entry, params={"velocity": 0.001},
        resolved_inputs=[input_wav],
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_exceeds_cap"
    assert "2000" in errors[0].message
    assert "300" in errors[0].message


async def test_preflight_rejects_when_negative(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur - long_offset",
        ),
        parameters={"long_offset": ParameterSpec(type="float")},
    )
    errors = await check_duration_preflight(
        entry=entry, params={"long_offset": 5.0},
        resolved_inputs=[input_wav],
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_negative"


async def test_preflight_rejects_on_evaluation_failure(tmp_path):
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur / velocity",
        ),
        parameters={"velocity": ParameterSpec(type="float")},
    )
    errors = await check_duration_preflight(
        entry=entry, params={"velocity": 0},
        resolved_inputs=[input_wav],
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_evaluation_failed"


async def test_preflight_skips_when_static_indur_unknown(tmp_path):
    """`.ana` input + no CDP context → indur is None → static falls
    back to skip (chain invariant). Without the CDP-context kwargs,
    the .ana fallback path stays disabled and behavior matches Phase 1b.
    """
    ana_input = tmp_path / "in.ana"
    ana_input.write_bytes(b"fake ana data")  # not a real .ana, sf.info fails
    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"),
    )
    errors = await check_duration_preflight(
        entry=entry, params={}, resolved_inputs=[ana_input],
    )
    assert errors == []


async def test_preflight_can_override_cap(tmp_path):
    """The cap is a kwarg for testability; tests can tighten it."""
    input_wav = tmp_path / "in.wav"
    _make_wav(input_wav, duration_s=2.0)
    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"),
    )
    errors = await check_duration_preflight(
        entry=entry, params={}, resolved_inputs=[input_wav],
        duration_cap_s=1.0,  # tighter than the 2-second input
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_exceeds_cap"


# ---------------------------------------------------------------------------
# _read_duration_seconds — header-only read
# ---------------------------------------------------------------------------


async def test_read_duration_seconds_wav(tmp_path):
    p = tmp_path / "in.wav"
    _make_wav(p, duration_s=3.5)
    assert await _read_duration_seconds(p) == pytest.approx(3.5, abs=0.01)


async def test_read_duration_seconds_unreadable_returns_none(tmp_path):
    p = tmp_path / "fake.ana"
    p.write_bytes(b"not a real audio file")
    assert await _read_duration_seconds(p) is None


async def test_read_duration_seconds_nonexistent_returns_none(tmp_path):
    assert await _read_duration_seconds(tmp_path / "missing.wav") is None


# ---------------------------------------------------------------------------
# Phase 2 Task 2 — .ana duration fallback via sfprops
# ---------------------------------------------------------------------------


_FAKE_SUBPROCESS_FOR_PREFLIGHT = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


def _install_fake_sfprops(cdp_path: Path, duration: str) -> None:
    """Drop a fake ``sfprops`` into ``cdp_path`` that prints ``duration``."""
    wrapper = cdp_path / "sfprops"
    wrapper.write_text(
        f"""#!/usr/bin/env bash
exec "{_FAKE_SUBPROCESS_FOR_PREFLIGHT}" --print-ana-duration "{duration}"
"""
    )
    wrapper.chmod(0o755)


async def test_preflight_uses_ana_fallback_when_cdp_context_provided(
    tmp_path,
):
    """`.ana` input + fake ``sfprops`` + CDP-context kwargs → fallback
    runs, the duration is realized, and the static model exercises it.

    Where ``test_preflight_skips_when_static_indur_unknown`` passes by
    skipping (chain invariant), this test passes by *computing* — the
    .ana indur becomes a real value the duration_model can evaluate.
    """
    cdp_path = (tmp_path / "cdp").resolve()
    cdp_path.mkdir()
    _install_fake_sfprops(cdp_path, duration="42.0")

    session_root = (tmp_path / "session").resolve()
    session_root.mkdir()
    inputs_dir = session_root / "inputs"
    inputs_dir.mkdir()
    ana_input = inputs_dir / "in.ana"
    ana_input.write_bytes(b"\xff\x00" * 1024)
    cache_dir = session_root / "tmp" / "ana_durations"

    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"),
    )
    # Static + a single 42-second .ana indur > 300s cap should reject.
    errors = await check_duration_preflight(
        entry=entry,
        params={},
        resolved_inputs=[ana_input],
        duration_cap_s=10.0,  # tighten so 42s breaches
        session_root=session_root,
        cdp_path=cdp_path,
        cdp_version="r8-fake",
        ana_duration_cache_dir=cache_dir,
    )
    assert len(errors) == 1
    assert errors[0].type == "predicted_duration_exceeds_cap"
    assert "42" in errors[0].message


async def test_preflight_ana_fallback_disabled_without_full_cdp_context(
    tmp_path,
):
    """Omitting any of the four CDP-context kwargs reduces to Phase 1b:
    the .ana branch returns None and the static model skips the check.
    This is the load-bearing backward-compat guarantee."""
    cdp_path = (tmp_path / "cdp").resolve()
    cdp_path.mkdir()
    _install_fake_sfprops(cdp_path, duration="42.0")

    session_root = (tmp_path / "session").resolve()
    session_root.mkdir()
    inputs_dir = session_root / "inputs"
    inputs_dir.mkdir()
    ana_input = inputs_dir / "in.ana"
    ana_input.write_bytes(b"\xff\x00" * 1024)

    entry = _make_entry(
        duration_model=DurationModelStatic(kind="static"),
    )
    # Provide three of the four kwargs (omit ana_duration_cache_dir);
    # the fallback must stay off, so duration is None → skip.
    errors = await check_duration_preflight(
        entry=entry,
        params={},
        resolved_inputs=[ana_input],
        duration_cap_s=10.0,
        session_root=session_root,
        cdp_path=cdp_path,
        cdp_version="r8-fake",
    )
    assert errors == []


def test_expression_type_error_becomes_structured(  # Phase 2 hardening, M11
):
    """A curated expr whose operator application raises TypeError (e.g.
    a string literal leaking into arithmetic) must surface as
    DurationModelError — the structured
    predicted_duration_evaluation_failed path — not a raw TypeError."""
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur * 'x'",
        ),
    )
    with pytest.raises(DurationModelError, match="TypeError"):
        _evaluate_duration_model(entry, {}, [10.0])


def test_expression_indur_min_multi_input():
    """combine cross's model: CDP emits the shorter input's duration.
    min/max aren't callable (functions={}), so the evaluator injects
    pre-computed indur_min/indur_max names."""
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur_min",
        ),
        arity=2,
    )
    result = _evaluate_duration_model(entry, {}, [3.0, 4.5])
    assert result == pytest.approx(3.0)


def test_expression_indur_max_multi_input():
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur_max",
        ),
        arity=2,
    )
    result = _evaluate_duration_model(entry, {}, [3.0, 4.5])
    assert result == pytest.approx(4.5)


def test_expression_indur_min_skips_when_any_duration_unknown():
    """The 'indur' substring skip guard covers indur_min: with any input
    duration unknown, preflight skips (watchdog covers reactively)
    rather than predicting from partial information."""
    entry = _make_entry(
        duration_model=DurationModelExpression(
            kind="expression", expr="indur_min",
        ),
        arity=2,
    )
    assert _evaluate_duration_model(entry, {}, [3.0, None]) is None
