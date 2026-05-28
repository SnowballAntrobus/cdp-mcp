"""Unit tests for cdp_mcp.schema."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError

from cdp_mcp.schema import (
    ContextBlock,
    DurationModelExpression,
    DurationModelLinear,
    DurationModelSetBy,
    DurationModelStatic,
    KnowledgeEntry,
    ParameterSpec,
    ResultEnvelope,
)

# ---------------------------------------------------------------------------
# Knowledge-entry round-trip
# ---------------------------------------------------------------------------


def _blur_blur_path() -> Path:
    return Path(str(files("cdp_mcp.knowledge").joinpath("data/blur_blur.json")))


def test_blur_blur_roundtrip_is_idempotent():
    """The on-disk JSON omits defaulted fields (e.g. ``musical_range``), so a
    strict dict-vs-dict equality with the original would fail. The meaningful
    invariant is that ``validate → dump → validate`` is idempotent: dumping
    once normalizes the form, and re-validating + re-dumping must match.
    """
    raw = _blur_blur_path().read_text(encoding="utf-8")
    entry = KnowledgeEntry.model_validate_json(raw)
    dumped = entry.model_dump(mode="json")
    reloaded = KnowledgeEntry.model_validate(dumped)
    assert reloaded.model_dump(mode="json") == dumped
    # Spot-check: the fields explicitly present on disk survive the round-trip
    # with their declared values.
    original = json.loads(raw)
    for key in ("program", "mode", "submode", "category", "domain", "duration_model"):
        assert dumped[key] == original[key]


def test_required_field_omission_raises():
    payload = {
        # missing program/mode/category/domain/etc.
        "description": "x",
    }
    with pytest.raises(ValidationError):
        KnowledgeEntry.model_validate(payload)


def test_invalid_domain_literal_raises():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["domain"] = "not-a-domain"
    with pytest.raises(ValidationError):
        KnowledgeEntry.model_validate(payload)


# ---------------------------------------------------------------------------
# DurationModel discriminated union
# ---------------------------------------------------------------------------


def test_duration_model_static_parses():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["duration_model"] = {"kind": "static"}
    entry = KnowledgeEntry.model_validate(payload)
    assert isinstance(entry.duration_model, DurationModelStatic)


def test_duration_model_set_by_parses():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["duration_model"] = {"kind": "set_by", "param": "dur"}
    entry = KnowledgeEntry.model_validate(payload)
    assert isinstance(entry.duration_model, DurationModelSetBy)
    assert entry.duration_model.param == "dur"


def test_duration_model_linear_parses():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["duration_model"] = {"kind": "linear", "param": "cnt"}
    entry = KnowledgeEntry.model_validate(payload)
    assert isinstance(entry.duration_model, DurationModelLinear)


def test_duration_model_expression_parses():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["duration_model"] = {"kind": "expression", "expr": "indur / velocity"}
    entry = KnowledgeEntry.model_validate(payload)
    assert isinstance(entry.duration_model, DurationModelExpression)
    assert entry.duration_model.expr == "indur / velocity"


def test_duration_model_missing_discriminator_raises():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["duration_model"] = {"param": "dur"}  # no kind
    with pytest.raises(ValidationError):
        KnowledgeEntry.model_validate(payload)


# ---------------------------------------------------------------------------
# input_arity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arity", [1, 2, "N", "variable"])
def test_input_arity_accepts_valid_values(arity):
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["input_arity"] = arity
    # Phase 2 Task 5: blur_blur's ``blurring`` is breakpoint_capable. When
    # we force arity > 1 just to exercise the input_arity Literal, the
    # KnowledgeEntry-level validator now requires a
    # ``breakpoint_duration_source`` to accompany it. Add one when we
    # cross into multi-input territory so this test stays focused on the
    # arity field rather than entangling with breakpoint validation.
    if arity == 2:
        payload["parameters"]["blurring"]["breakpoint_duration_source"] = "input1"
    entry = KnowledgeEntry.model_validate(payload)
    assert entry.input_arity == arity


def test_input_arity_rejects_bogus_string():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["input_arity"] = "abc"
    with pytest.raises(ValidationError):
        KnowledgeEntry.model_validate(payload)


# ---------------------------------------------------------------------------
# ParameterSpec.flag
# ---------------------------------------------------------------------------


def test_parameter_spec_flag_defaults_to_none():
    spec = ParameterSpec(type="float")
    assert spec.flag is None


def test_parameter_spec_flag_accepts_dash_string():
    spec = ParameterSpec(type="float", flag="-l", flag_kind="attached_value")
    assert spec.flag == "-l"


def test_parameter_spec_flag_kind_required_when_flag_present():
    with pytest.raises(ValidationError):
        ParameterSpec(type="float", flag="-l")


def test_parameter_spec_flag_kind_forbidden_when_flag_absent():
    with pytest.raises(ValidationError):
        ParameterSpec(type="float", flag_kind="attached_value")


def test_parameter_spec_attached_value_flag_round_trip():
    spec = ParameterSpec(type="float", flag="-l", flag_kind="attached_value")
    assert spec.flag_kind == "attached_value"


def test_parameter_spec_no_value_flag_round_trip():
    spec = ParameterSpec(type="bool", flag="-b", flag_kind="no_value")
    assert spec.flag_kind == "no_value"


def test_parameter_spec_positional_keeps_both_none():
    spec = ParameterSpec(type="float")
    assert spec.flag is None
    assert spec.flag_kind is None


# ---------------------------------------------------------------------------
# KnowledgeEntry.submode
# ---------------------------------------------------------------------------


def test_submode_defaults_to_none():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload.pop("submode", None)
    entry = KnowledgeEntry.model_validate(payload)
    assert entry.submode is None


def test_submode_accepts_int():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["submode"] = 2
    entry = KnowledgeEntry.model_validate(payload)
    assert entry.submode == 2


def test_submode_rejects_string():
    payload = json.loads(_blur_blur_path().read_text(encoding="utf-8"))
    payload["submode"] = "two"
    with pytest.raises(ValidationError):
        KnowledgeEntry.model_validate(payload)


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


def test_result_envelope_constructs_with_only_status():
    env = ResultEnvelope(status="ok")
    assert env.status == "ok"
    assert env.errors == []
    assert env.warnings == []
    assert isinstance(env.context, ContextBlock)
    assert env.context.recent_graphs == []


# TODO: ParameterSpec cross-field validation (min > max) is intentionally not
# enforced in Phase 1a. CDP itself would reject such a call; we can revisit
# in Phase 3 if the curated entries ever benefit from the extra guardrail.


# ---------------------------------------------------------------------------
# Phase 2 Task 5 — schema additions
# ---------------------------------------------------------------------------


def _minimal_entry_payload(**overrides) -> dict:
    base = {
        "program": "x", "mode": "x", "category": "test",
        "domain": "time", "input_arity": 1, "channel_constraint": "any",
        "input_format": ".wav", "output_format": ".wav",
        "duration_model": {"kind": "static"},
        "description": "t", "musical_use": "t",
        "parameters": {},
    }
    base.update(overrides)
    return base


def test_breakpoint_duration_source_rejected_when_arity_one():
    payload = _minimal_entry_payload(
        parameters={
            "v": {
                "type": "float",
                "breakpoint_capable": True,
                "breakpoint_duration_source": "input1",
            }
        },
    )
    with pytest.raises(ValidationError, match="breakpoint_duration_source"):
        KnowledgeEntry.model_validate(payload)


def test_breakpoint_duration_source_required_on_multi_input_capable():
    payload = _minimal_entry_payload(
        input_arity=2,
        parameters={
            "v": {
                "type": "float",
                "breakpoint_capable": True,
                # missing breakpoint_duration_source
            }
        },
    )
    with pytest.raises(ValidationError, match="breakpoint_duration_source"):
        KnowledgeEntry.model_validate(payload)


def test_breakpoint_duration_source_accepted_when_paired():
    payload = _minimal_entry_payload(
        input_arity=2,
        parameters={
            "v": {
                "type": "float",
                "breakpoint_capable": True,
                "breakpoint_duration_source": "max",
            }
        },
    )
    entry = KnowledgeEntry.model_validate(payload)
    assert entry.parameters["v"].breakpoint_duration_source == "max"


@pytest.mark.parametrize("value", [
    "pad_with_fade", "truncate_to_shortest", "fail",
    "stagger:0", "stagger:0.5", "stagger:-1.5", "stagger:3.14159",
    None,
])
def test_default_length_strategy_accepts_valid_values(value):
    payload = _minimal_entry_payload(default_length_strategy=value)
    entry = KnowledgeEntry.model_validate(payload)
    assert entry.default_length_strategy == value


@pytest.mark.parametrize("value", [
    "", "foo", "stagger:", "stagger:abc",
    "pad", "pad_with_fade ", "STAGGER:0", "stagger:0:5",
])
def test_default_length_strategy_rejects_invalid_values(value):
    payload = _minimal_entry_payload(default_length_strategy=value)
    with pytest.raises(ValidationError, match="default_length_strategy"):
        KnowledgeEntry.model_validate(payload)
