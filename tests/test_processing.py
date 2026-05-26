"""Unit tests for cdp_mcp.processing."""

from __future__ import annotations

from pathlib import Path

from cdp_mcp.processing import build_cdp_argv, validate_params
from cdp_mcp.schema import KnowledgeEntry, ParameterSpec

# ---------------------------------------------------------------------------
# Fixture entries (built in-test to stay independent of curated-data drift)
# ---------------------------------------------------------------------------


def _entry_with(
    parameters: dict[str, ParameterSpec],
    *,
    program: str = "p",
    mode: str = "m",
    submode: int | None = None,
    domain: str = "time",
    input_arity: int = 1,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        program=program,
        mode=mode,
        submode=submode,
        category="x",
        domain=domain,  # type: ignore[arg-type]
        input_arity=input_arity,
        channel_constraint="any",
        input_format=".wav" if domain == "time" else ".ana",
        output_format=".wav" if domain == "time" else ".ana",
        duration_model={"kind": "static"},  # type: ignore[arg-type]
        description="x",
        musical_use="x",
        parameters=parameters,
    )


# ---------------------------------------------------------------------------
# validate_params
# ---------------------------------------------------------------------------


def test_all_required_empty_params_reports_each_missing():
    entry = _entry_with({
        "a": ParameterSpec(type="float"),
        "b": ParameterSpec(type="float"),
    })
    errors, warnings = validate_params(entry, {})
    types = [e.type for e in errors]
    assert types.count("missing_parameter") == 2
    names = " ".join(e.message for e in errors)
    assert "'a'" in names
    assert "'b'" in names
    assert warnings == []


def test_unknown_param_reported():
    entry = _entry_with({"velocity": ParameterSpec(type="float")})
    errors, _ = validate_params(entry, {"velocity": 0.5, "bogus": 1.0})
    assert any(e.type == "unknown_parameter" and "bogus" in e.message for e in errors)


def test_out_of_range_low_and_high():
    entry = _entry_with({
        "x": ParameterSpec(type="float", min=0.0, max=10.0),
    })
    low, _ = validate_params(entry, {"x": -1.0})
    high, _ = validate_params(entry, {"x": 11.0})
    assert any(e.type == "param_out_of_range" and "minimum" in e.message for e in low)
    assert any(e.type == "param_out_of_range" and "maximum" in e.message for e in high)


def test_type_error_on_string():
    entry = _entry_with({"x": ParameterSpec(type="float")})
    errors, _ = validate_params(entry, {"x": "not a number"})
    assert any(e.type == "param_type" for e in errors)


def test_type_error_on_list_mentions_phase_1b():
    entry = _entry_with({"x": ParameterSpec(type="float")})
    errors, _ = validate_params(entry, {"x": [0.0, 0.5, 1.0]})
    matching = [e for e in errors if e.type == "param_type"]
    assert matching
    assert any("Phase 1b" in (e.fix or "") for e in matching)


def test_bool_value_rejected_in_phase_1a():
    entry = _entry_with({"x": ParameterSpec(type="float")})
    errors, _ = validate_params(entry, {"x": True})
    assert any(e.type == "param_type" and "bool" in e.message for e in errors)


def test_musical_range_warning_does_not_block():
    entry = _entry_with({
        "gain": ParameterSpec(
            type="float", min=0.0, max=10.0, musical_range=(0.5, 4.0)
        ),
    })
    errors, warnings = validate_params(entry, {"gain": 8.0})
    assert errors == []
    assert len(warnings) == 1
    assert "musical_range" in warnings[0]


def test_valid_params_no_errors_no_warnings():
    entry = _entry_with({"x": ParameterSpec(type="float", min=0.0, max=1.0)})
    errors, warnings = validate_params(entry, {"x": 0.5})
    assert errors == []
    assert warnings == []


def test_all_checks_run_to_completion():
    """Unknown + missing + out-of-range in one call → all three reported."""
    entry = _entry_with({
        "a": ParameterSpec(type="float", min=0.0, max=1.0),
        "b": ParameterSpec(type="float"),
    })
    errors, _ = validate_params(entry, {"a": 5.0, "bogus": 1.0})
    types = {e.type for e in errors}
    assert "unknown_parameter" in types
    assert "missing_parameter" in types
    assert "param_out_of_range" in types


# ---------------------------------------------------------------------------
# build_cdp_argv
# ---------------------------------------------------------------------------


# Most argv tests use a cwd that doesn't share a prefix with the test input
# paths, so paths stay absolute (or unchanged) in the argv. Dedicated tests
# below cover the cwd-relative conversion.
_OTHER_CWD = Path("/elsewhere")


def test_argv_no_submode_all_positional():
    entry = _entry_with({"blurring": ParameterSpec(type="float", min=1.0)})
    argv = build_cdp_argv(
        entry, [Path("/tmp/in.ana")], Path("/tmp/out.ana"), {"blurring": 10},
        cwd=_OTHER_CWD,
    )
    assert argv == ["p", "m", "/tmp/in.ana", "/tmp/out.ana", "10"]


def test_argv_with_submode():
    entry = _entry_with(
        {"velocity": ParameterSpec(type="float", min=0.0)},
        submode=2,
    )
    argv = build_cdp_argv(
        entry, [Path("/tmp/in.wav")], Path("/tmp/out.wav"), {"velocity": 1.5},
        cwd=_OTHER_CWD,
    )
    assert argv == ["p", "m", "2", "/tmp/in.wav", "/tmp/out.wav", "1.5"]


def test_argv_multi_input_morph_morph_shape():
    entry = _entry_with(
        {
            "as": ParameterSpec(type="float"),
            "ae": ParameterSpec(type="float"),
            "fs": ParameterSpec(type="float"),
            "fe": ParameterSpec(type="float"),
            "expa": ParameterSpec(type="float"),
            "expf": ParameterSpec(type="float"),
            "stagger": ParameterSpec(
                type="float", default=0.0, flag="-s", flag_kind="attached_value",
            ),
        },
        program="morph",
        mode="morph",
        submode=1,
        domain="spectral",
        input_arity=2,
    )
    argv = build_cdp_argv(
        entry,
        [Path("/tmp/a.ana"), Path("/tmp/b.ana")],
        Path("/tmp/out.ana"),
        {"as": 0.0, "ae": 3.0, "fs": 1.0, "fe": 4.0, "expa": 1.0, "expf": 1.0},
        cwd=_OTHER_CWD,
    )
    assert argv == [
        "morph", "morph", "1",
        "/tmp/a.ana", "/tmp/b.ana", "/tmp/out.ana",
        "0", "3", "1", "4", "1", "1",  # positional floats trimmed by .10g
        "-s0",  # stagger default 0.0 → flag-attached
    ]


def test_argv_flag_attached_no_space():
    entry = _entry_with({
        "phase": ParameterSpec(type="float", flag="-p", flag_kind="attached_value"),
    })
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"), {"phase": 0.25},
        cwd=_OTHER_CWD,
    )
    assert "-p0.25" in argv
    assert "-p 0.25" not in argv  # No space between flag and value


def test_argv_uses_default_when_param_omitted():
    entry = _entry_with({
        "x": ParameterSpec(type="float"),  # required
        "splen": ParameterSpec(
            type="float", default=25.0, flag="-w", flag_kind="attached_value",
        ),
    })
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"), {"x": 1.0}, cwd=_OTHER_CWD
    )
    assert "-w25" in argv


def test_argv_float_formatting_0_1_plus_0_2():
    """The classic floating-point trap: 0.1 + 0.2 == 0.30000000000000004."""
    entry = _entry_with({"x": ParameterSpec(type="float")})
    argv = build_cdp_argv(
        entry, [Path("in")], Path("out"), {"x": 0.1 + 0.2}, cwd=_OTHER_CWD
    )
    assert "0.3" in argv  # not "0.30000000000000004"


def test_argv_float_preserves_precision():
    entry = _entry_with({"x": ParameterSpec(type="float")})
    argv = build_cdp_argv(
        entry, [Path("in")], Path("out"), {"x": 1.234567}, cwd=_OTHER_CWD
    )
    assert "1.234567" in argv


def test_argv_int_no_decimal_point():
    entry = _entry_with({"cnt": ParameterSpec(type="int")})
    argv = build_cdp_argv(
        entry, [Path("in")], Path("out"), {"cnt": 5}, cwd=_OTHER_CWD
    )
    assert "5" in argv
    assert "5.0" not in argv


# ---------------------------------------------------------------------------
# cwd-relative path conversion (Task 6.1 fix)
# ---------------------------------------------------------------------------


def test_argv_paths_relative_to_cwd_when_inside_cwd():
    """Paths under cwd get rendered as cwd-relative — workaround for CDP
    programs (notably modify brassage) that crash on absolute paths whose
    ancestry contains a '.' (e.g. session dirs like 'frog_v0.1').
    """
    entry = _entry_with({"velocity": ParameterSpec(type="float")}, submode=2)
    cwd = Path("/Users/dgm/cdp_sessions/frog_v0.1")
    argv = build_cdp_argv(
        entry,
        [cwd / "inputs" / "frog.wav"],
        cwd / "graphs" / "g1" / "out.wav",
        {"velocity": 0.5},
        cwd=cwd,
    )
    # The relative forms appear, the absolute prefix does not.
    assert "inputs/frog.wav" in argv
    assert "graphs/g1/out.wav" in argv
    assert all(not a.startswith(str(cwd)) for a in argv[1:])


def test_argv_paths_outside_cwd_stay_absolute():
    """Files that legitimately live outside cwd (e.g. the CDP cache) keep
    their absolute form rather than getting a '..'-traversal relative path.
    """
    entry = _entry_with({"x": ParameterSpec(type="float")})
    cwd = Path("/Users/dgm/cdp_sessions/frog_v0.1")
    cache_file = Path("/Users/dgm/.cdp_mcp/cache/pvoc/abc.ana")
    argv = build_cdp_argv(
        entry, [cache_file], cwd / "out.ana", {"x": 1.0}, cwd=cwd,
    )
    # Cache path keeps its absolute form.
    assert str(cache_file) in argv
    # Output (inside cwd) becomes relative.
    assert "out.ana" in argv


def test_optional_flag_with_no_value_omitted_from_argv():
    """Flag params are CDP-optional by definition. With no user value and no
    default, the flag should not appear in argv at all — emitting it bare
    would be invalid CDP syntax.
    """
    entry = _entry_with({
        "cnt": ParameterSpec(type="int"),  # required positional
        "step": ParameterSpec(
            type="float", flag="-l", flag_kind="attached_value",
        ),  # optional, no default
    })
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"), {"cnt": 4}, cwd=_OTHER_CWD
    )
    assert "-l" not in " ".join(argv)
    assert not any(a.startswith("-l") for a in argv)


def test_argv_no_value_flag_emits_bare_switch_when_supplied():
    """Value-less switch flags emit `-b` alone, not `-bTrue` or `-b1`.

    This test exercises the no_value branch via a synthetic fixture. No
    Phase 1a curated entry declares a no_value flag yet (the -b switch on
    extend loop remains unexposed pending bool-param support); the test
    documents the codegen contract for when one does.
    """
    entry = _entry_with({
        "cnt": ParameterSpec(type="int"),
        "play_from_start": ParameterSpec(
            type="bool", flag="-b", flag_kind="no_value", default=False,
        ),
    })
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"),
        {"cnt": 4, "play_from_start": True},
        cwd=_OTHER_CWD,
    )
    assert "-b" in argv
    # Crucially: no "-bTrue" or "-b1" or any -b<suffix> in argv.
    assert not any(a.startswith("-b") and len(a) > 2 for a in argv)


def test_argv_no_value_flag_omitted_when_not_supplied():
    """Switch flag with no user value and no default → omit entirely.

    Same skip-when-no-value semantics as attached_value flags; only the
    emission form differs when the flag IS present.
    """
    entry = _entry_with({
        "cnt": ParameterSpec(type="int"),
        "play_from_start": ParameterSpec(
            type="bool", flag="-b", flag_kind="no_value",
        ),
    })
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"), {"cnt": 4},
        cwd=_OTHER_CWD,
    )
    assert "-b" not in argv


def test_optional_flag_not_required_by_validate_params():
    """validate_params must not flag an optional flag param as missing."""
    entry = _entry_with({
        "cnt": ParameterSpec(type="int"),
        "step": ParameterSpec(type="float", flag="-l", flag_kind="attached_value"),
        "scat": ParameterSpec(type="float", flag="-s", flag_kind="attached_value"),
    })
    errors, _ = validate_params(entry, {"cnt": 4})
    types = [e.type for e in errors]
    # Only `cnt` is required; missing it should be the only complaint.
    # Since cnt IS supplied here, errors should be empty.
    assert errors == [], f"unexpected errors: {types}"


def test_argv_insertion_order_respected():
    """Params should emit in declaration order, not alphabetical."""
    entry = _entry_with({
        "z_first": ParameterSpec(type="float"),
        "a_second": ParameterSpec(type="float"),
    })
    argv = build_cdp_argv(
        entry, [Path("in")], Path("out"), {"z_first": 1.0, "a_second": 2.0},
        cwd=_OTHER_CWD,
    )
    # The two values should appear in the order z_first then a_second.
    i1 = argv.index("1")
    i2 = argv.index("2")
    assert i1 < i2
