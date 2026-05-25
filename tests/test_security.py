"""Unit tests for cdp_mcp.security.validate_command."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from cdp_mcp.security import SecurityError, validate_command

# ---------------------------------------------------------------------------
# Fixture: roots + a dummy executable named "blur"
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def roots(tmp_path):
    """Resolved cdp_path / session_root / cache_root with `blur` in cdp_path.

    All three roots are .resolve()-d to match what server.py does — this
    keeps the macOS /tmp -> /private/tmp symlink from creating
    is_relative_to false-positives.
    """
    cdp = (tmp_path / "cdp").resolve()
    session = (tmp_path / "session").resolve()
    cache = (tmp_path / "cache").resolve()
    for p in (cdp, session, cache, session / "inputs", cache / "pvoc"):
        p.mkdir(parents=True, exist_ok=True)
    _make_executable(cdp / "blur")
    return cdp, session, cache


# ---------------------------------------------------------------------------
# Empty command
# ---------------------------------------------------------------------------


def test_empty_command_raises(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command([], cdp, session, cache)
    assert exc.value.errors[0].type == "empty_command"


# ---------------------------------------------------------------------------
# Binary check
# ---------------------------------------------------------------------------


def test_bare_name_resolves(roots):
    cdp, session, cache = roots
    validated = validate_command(["blur", "input.wav", "output.wav", "10"], cdp, session, cache)
    assert validated[0] == str(cdp / "blur")
    # Rest of argv is unchanged.
    assert validated[1:] == ["input.wav", "output.wav", "10"]


def test_bare_name_missing(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["nonexistent"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "binary_not_in_cdp_path" in types


def test_absolute_path_inside_cdp_path(roots):
    cdp, session, cache = roots
    validated = validate_command([str(cdp / "blur"), "10"], cdp, session, cache)
    assert validated[0] == str(cdp / "blur")


def test_absolute_path_outside_cdp_path(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["/bin/echo", "hi"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "binary_not_in_cdp_path" in types


def test_relative_with_dir_component_rejected(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["../bin/foo"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "binary_not_in_cdp_path" in types


def test_dot_slash_argv0_rejected(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["./blur"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "binary_not_in_cdp_path" in types


def test_bare_name_present_but_not_executable(tmp_path):
    cdp = (tmp_path / "cdp").resolve()
    session = (tmp_path / "session").resolve()
    cache = (tmp_path / "cache").resolve()
    for p in (cdp, session, cache):
        p.mkdir(parents=True, exist_ok=True)
    not_exec = cdp / "tool"
    not_exec.write_text("hello")  # no chmod +x
    with pytest.raises(SecurityError) as exc:
        validate_command(["tool"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "binary_not_in_cdp_path" in types


# ---------------------------------------------------------------------------
# Metacharacter check
# ---------------------------------------------------------------------------


def test_clean_args_no_metacharacter_errors(roots):
    cdp, session, cache = roots
    validate_command(["blur", "input.wav", "output.wav", "10", "-g1.5"], cdp, session, cache)
    # No raise == success.


@pytest.mark.parametrize(
    "bad_arg,offending",
    [
        ("input.wav; rm -rf /", ";"),
        ("input.wav | tee /tmp/x", "|"),
        ("input.wav & whoami", "&"),
        ("input.wav$HOME", "$"),
        ("input.wav`whoami`", "`"),
        ("a>b", ">"),
        ("a<b", "<"),
        ("input(.wav", "("),
        ("input).wav", ")"),
        ("input.wav\nrm /etc/passwd", "\n"),
        ("input.wav\rcarriage", "\r"),
        ("input.wav\0null", "\0"),
    ],
)
def test_each_metacharacter_flagged(roots, bad_arg, offending):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["blur", bad_arg], cdp, session, cache)
    meta_errors = [e for e in exc.value.errors if e.type == "metacharacter_rejected"]
    assert len(meta_errors) == 1
    assert repr(offending) in meta_errors[0].message


def test_multiple_chars_in_one_arg_collapsed_to_one_error(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["blur", "a;b|c"], cdp, session, cache)
    meta_errors = [e for e in exc.value.errors if e.type == "metacharacter_rejected"]
    assert len(meta_errors) == 1
    assert "';'" in meta_errors[0].message
    assert "'|'" in meta_errors[0].message


# ---------------------------------------------------------------------------
# Path scope check
# ---------------------------------------------------------------------------


def test_relative_path_inside_session_inputs(roots):
    cdp, session, cache = roots
    (session / "inputs" / "frog.wav").write_bytes(b"x")
    validate_command(["blur", "inputs/frog.wav"], cdp, session, cache)  # no raise


def test_absolute_path_inside_session(roots):
    cdp, session, cache = roots
    (session / "inputs" / "frog.wav").write_bytes(b"x")
    validate_command(["blur", str(session / "inputs" / "frog.wav")], cdp, session, cache)


def test_path_outside_session(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["blur", "/etc/passwd"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "path_outside_session" in types


def test_path_inside_cache(roots):
    cdp, session, cache = roots
    target = cache / "pvoc" / "x.ana"
    target.write_bytes(b"x")
    validate_command(["blur", str(target)], cdp, session, cache)  # no raise


def test_nonexistent_output_in_session(roots):
    cdp, session, cache = roots
    # Output file doesn't exist yet — resolve() still normalizes it.
    validate_command(["blur", "inputs/in.wav", "output.wav"], cdp, session, cache)


def test_path_traversal_normalized_and_rejected(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["blur", "../../etc/passwd"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "path_outside_session" in types


def test_tilde_expansion_outside_session(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["blur", "~/foo.wav"], cdp, session, cache)
    # ~/foo.wav expands to user's home which is almost certainly not under
    # our test tmp_path.
    types = {e.type for e in exc.value.errors}
    assert "path_outside_session" in types


def test_non_path_like_args_skip_scope_check(roots):
    cdp, session, cache = roots
    # No file extensions, no slashes — these are numeric / flag values.
    validate_command(["blur", "10", "1.5", "-g"], cdp, session, cache)


@pytest.mark.parametrize("ext", [".pvx", ".for", ".brk", ".mix", ".mmx", ".amb"])
def test_extension_triggers_heuristic(roots, ext):
    cdp, session, cache = roots
    # A bare filename with a known CDP extension but nowhere to be found
    # should still trigger the path-scope heuristic and be checked against
    # session_root + cache_root. With no slash, it resolves to session_root /
    # <name>, which is INSIDE — so the file would pass scope.
    # We pick `/etc/foo<ext>` to confirm the heuristic also runs for
    # absolute-looking external paths.
    with pytest.raises(SecurityError) as exc:
        validate_command(["blur", f"/etc/foo{ext}"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "path_outside_session" in types


# ---------------------------------------------------------------------------
# Combined / aggregation: all three checks run, all violations reported
# ---------------------------------------------------------------------------


def test_triple_violation_all_three_types_reported(roots):
    cdp, session, cache = roots
    with pytest.raises(SecurityError) as exc:
        validate_command(["/bin/rm", "out.wav; rm /tmp", "/etc/passwd"], cdp, session, cache)
    types = {e.type for e in exc.value.errors}
    assert "binary_not_in_cdp_path" in types
    assert "metacharacter_rejected" in types
    assert "path_outside_session" in types
