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
    spec = ParameterSpec(type="float", flag="-l")
    assert spec.flag == "-l"


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
