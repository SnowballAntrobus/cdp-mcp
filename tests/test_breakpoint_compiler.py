"""Unit tests for the breakpoint compiler.

Covers value-shape detection, mode determination, tuple list compilation
(sort, dedup, auto-append, range validation), pre-existing .brk path
mode, structured error production, and content-addressable determinism.
Integration via process() lives in test_process.py.
"""

from __future__ import annotations

import pytest

from cdp_mcp.breakpoint_compiler import (
    compile_breakpoint_value,
    detect_breakpoint_mode,
    is_breakpoint_value,
)
from cdp_mcp.schema import ParameterSpec

_BREAKPOINT_SPEC = ParameterSpec(type="float", breakpoint_capable=True)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_is_breakpoint_value_constant():
    assert is_breakpoint_value(0.5) is False
    assert is_breakpoint_value(5) is False


def test_is_breakpoint_value_list():
    assert is_breakpoint_value([[0.0, 5], [1.0, 50]]) is True


def test_is_breakpoint_value_brk_path():
    assert is_breakpoint_value("my.brk") is True
    assert is_breakpoint_value("MY.BRK") is True  # case-insensitive


def test_is_breakpoint_value_arbitrary_string():
    assert is_breakpoint_value("not_a_brk_path") is False


@pytest.mark.parametrize("mode_value,expected", [
    ([[0.0, 5], [1.0, 50]], "relative"),
    ([["abs:0.0", 5], ["abs:5.0", 50]], "absolute"),
    ([[0.0, 5], ["abs:5.0", 50]], "mixed"),
    ([], "empty"),
])
def test_detect_breakpoint_mode(mode_value, expected):
    assert detect_breakpoint_mode(mode_value) == expected


# ---------------------------------------------------------------------------
# Compilation — relative mode
# ---------------------------------------------------------------------------


def test_relative_two_point_ramp(tmp_path):
    """Two points spanning the full input duration → no auto-append."""
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], [1.0, 50]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert not result.errors
    assert result.compiled_path is not None
    assert result.compiled_path.exists()
    lines = [
        line for line in result.compiled_path.read_text().splitlines()
        if line.strip()
    ]
    # Two points expected; t=1.0 already reaches source_duration.
    assert len(lines) == 2
    assert lines[0].split()[0] == "0"
    assert lines[1].split()[0] == "10"


def test_relative_auto_appends_final_point(tmp_path):
    """Last point at t=0.5 → t=5.0s on a 10s file → auto-append (10.0, last)."""
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], [0.5, 25]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    lines = [
        line for line in result.compiled_path.read_text().splitlines()
        if line.strip()
    ]
    assert len(lines) == 3
    assert lines[-1].split() == ["10", "25"]


def test_relative_dedups_near_identical_with_warning(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], [0.5, 25], [0.50000001, 26], [1.0, 50]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    lines = [
        line for line in result.compiled_path.read_text().splitlines()
        if line.strip()
    ]
    # Three points expected (one near-dup dropped); warning emitted.
    assert len(lines) == 3
    assert any("near-identical" in w.lower() for w in result.warnings)


def test_relative_sorts_scrambled_input(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[1.0, 50], [0.0, 5], [0.5, 25]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    lines = result.compiled_path.read_text().splitlines()
    times = [float(line.split()[0]) for line in lines if line.strip()]
    assert times == sorted(times)


def test_relative_out_of_range_errors(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], [1.5, 50]],  # t=1.5 > 1.0
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert result.compiled_path is None
    assert any(
        e.type == "param_breakpoint_time_out_of_range"
        for e in result.errors
    )


def test_relative_requires_source_duration(tmp_path):
    """Relative mode needs source_duration — None → no_source_duration error."""
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], [1.0, 50]],
        source_duration_s=None,
        source_kind=None,
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert any(
        e.type == "param_breakpoint_no_source_duration"
        for e in result.errors
    )


# ---------------------------------------------------------------------------
# Compilation — absolute mode
# ---------------------------------------------------------------------------


def test_absolute_two_point(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[["abs:0.0", 5], ["abs:3.0", 50]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert not result.errors
    lines = [
        line for line in result.compiled_path.read_text().splitlines()
        if line.strip()
    ]
    # Three points: (0, 5), (3, 50), (10, 50) — auto-appended.
    assert len(lines) == 3


def test_absolute_no_source_duration_still_compiles_with_warning(tmp_path):
    """Absolute mode compiles without source_duration; skips auto-append
    and emits an advisory warning."""
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[["abs:0.0", 5], ["abs:3.0", 50]],
        source_duration_s=None,
        source_kind=None,
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert result.compiled_path is not None
    assert any(
        "source_duration" in w.lower() or "auto-append" in w.lower()
        for w in result.warnings
    )


def test_mixed_mode_rejected(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], ["abs:5.0", 50]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert any(
        e.type == "param_breakpoint_mode_mixed"
        for e in result.errors
    )


def test_empty_list_rejected(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert any(
        e.type == "param_breakpoint_empty_list"
        for e in result.errors
    )


# ---------------------------------------------------------------------------
# Pre-existing .brk path mode
# ---------------------------------------------------------------------------


def test_preexisting_brk_path_hashed_not_compiled(tmp_path):
    envelopes = tmp_path / "envelopes"
    envelopes.mkdir()
    user_brk = envelopes / "my_curve.brk"
    user_brk.write_text("0.0 5\n5.0 25\n10.0 50\n")
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value="envelopes/my_curve.brk",
        source_duration_s=None,  # not needed for path mode
        source_kind=None,
        session_root=tmp_path,
        envelopes_dir=envelopes,
    )
    assert not result.errors
    assert result.record.source_kind == "preexisting_brk"
    # Resolved path equals the user-supplied file (after .resolve()).
    assert result.compiled_path == user_brk.resolve()
    assert result.record.sha256 != ""


def test_preexisting_brk_missing_file_errors(tmp_path):
    envelopes = tmp_path / "envelopes"
    envelopes.mkdir()
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value="envelopes/does_not_exist.brk",
        source_duration_s=None,
        source_kind=None,
        session_root=tmp_path,
        envelopes_dir=envelopes,
    )
    assert any(
        e.type == "param_breakpoint_file_unreadable"
        for e in result.errors
    )


# ---------------------------------------------------------------------------
# Determinism / content addressing
# ---------------------------------------------------------------------------


def test_same_value_produces_same_file(tmp_path):
    """Two compilations with identical inputs produce the same sha and
    same filepath — content-addressable backbone for Task 12's cache."""
    kwargs = dict(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], [1.0, 50]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    r1 = compile_breakpoint_value(**kwargs)
    r2 = compile_breakpoint_value(**kwargs)
    assert r1.compiled_path == r2.compiled_path
    assert r1.record.sha256 == r2.record.sha256


def test_different_source_duration_produces_different_files(tmp_path):
    """Same tuple list at different source durations → different
    compiled content → different shas → different files. This is what
    lets Task 12's cache invalidate correctly across input duration
    changes."""
    base = dict(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5], [1.0, 50]],
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    r1 = compile_breakpoint_value(**base, source_duration_s=10.0)
    r2 = compile_breakpoint_value(**base, source_duration_s=20.0)
    assert r1.record.sha256 != r2.record.sha256


# ---------------------------------------------------------------------------
# Tuple-shape and value-type validation
# ---------------------------------------------------------------------------


def test_non_numeric_value_rejected(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, "five"], [1.0, 50]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert any(
        e.type == "param_breakpoint_value_type"
        for e in result.errors
    )


def test_wrong_tuple_length_rejected(tmp_path):
    result = compile_breakpoint_value(
        param_name="blurring",
        param_spec=_BREAKPOINT_SPEC,
        value=[[0.0, 5, 99], [1.0, 50]],
        source_duration_s=10.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert any(
        e.type == "param_breakpoint_value_type"
        for e in result.errors
    )
