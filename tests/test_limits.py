"""Unit tests for ``cdp_mcp.limits._resolve_positive_float``."""

from __future__ import annotations

import importlib

import pytest

from cdp_mcp import limits
from cdp_mcp.limits import _resolve_positive_float


def test_resolve_positive_float_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("CDP_MCP_TEST_VAR", raising=False)
    result = _resolve_positive_float("CDP_MCP_TEST_VAR", 7.5, "test label")
    assert result == 7.5


def test_resolve_positive_float_parses_valid_override(monkeypatch):
    monkeypatch.setenv("CDP_MCP_TEST_VAR", "42.5")
    result = _resolve_positive_float("CDP_MCP_TEST_VAR", 7.5, "test label")
    assert result == 42.5


def test_resolve_positive_float_non_numeric_falls_back_with_warning(
    monkeypatch, capsys,
):
    monkeypatch.setenv("CDP_MCP_TEST_VAR", "abc")
    result = _resolve_positive_float("CDP_MCP_TEST_VAR", 7.5, "test label")
    assert result == 7.5
    captured = capsys.readouterr()
    assert "CDP_MCP_TEST_VAR" in captured.err
    assert "not a number" in captured.err
    assert "test label" in captured.err


def test_resolve_positive_float_zero_falls_back_with_warning(
    monkeypatch, capsys,
):
    monkeypatch.setenv("CDP_MCP_TEST_VAR", "0")
    result = _resolve_positive_float("CDP_MCP_TEST_VAR", 7.5, "test label")
    assert result == 7.5
    captured = capsys.readouterr()
    assert "must be positive" in captured.err


def test_resolve_positive_float_negative_falls_back_with_warning(
    monkeypatch, capsys,
):
    monkeypatch.setenv("CDP_MCP_TEST_VAR", "-1")
    result = _resolve_positive_float("CDP_MCP_TEST_VAR", 7.5, "test label")
    assert result == 7.5
    captured = capsys.readouterr()
    assert "must be positive" in captured.err


def test_module_level_constants_present_with_defaults():
    """The module exports the two constants at import time. Defaults
    apply when no env var is set."""
    assert limits.OUTPUT_DURATION_CAP_S == pytest.approx(300.0)
    assert limits.OUTPUT_FILE_SIZE_CAP_BYTES == 1_073_741_824


def test_env_var_override_round_trip(monkeypatch):
    """End-to-end: setting CDP_MCP_DURATION_CAP_S then reimporting limits
    picks up the new value. Confirms the integration path that operators
    would actually use (set env, start server)."""
    monkeypatch.setenv("CDP_MCP_DURATION_CAP_S", "60")
    monkeypatch.setenv("CDP_MCP_OUTPUT_SIZE_CAP_BYTES", "1048576")
    reloaded = importlib.reload(limits)
    try:
        assert reloaded.OUTPUT_DURATION_CAP_S == 60.0
        assert reloaded.OUTPUT_FILE_SIZE_CAP_BYTES == 1_048_576
    finally:
        # Restore the module to its default state so other tests see
        # the defaults.
        monkeypatch.delenv("CDP_MCP_DURATION_CAP_S", raising=False)
        monkeypatch.delenv("CDP_MCP_OUTPUT_SIZE_CAP_BYTES", raising=False)
        importlib.reload(limits)
