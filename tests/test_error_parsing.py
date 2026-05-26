"""Unit tests for the CDP stderr pattern parser.

The parser is exercised end-to-end via process() and execute() in
test_process.py / test_execute.py; this file pins down the matching
logic directly so regex changes are caught at the unit level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cdp_mcp.error_parsing import parse_cdp_errors
from cdp_mcp.schema import OutputVerification

# ---------------------------------------------------------------------------
# output_exists
# ---------------------------------------------------------------------------


def test_output_exists_detects_canonical_phrasing():
    errors = parse_cdp_errors(
        stdout="",
        stderr="ERROR: cannot create output file /foo/bar.ana\n",
        exit_code=255,
    )
    assert len(errors) == 1
    assert errors[0].type == "output_exists"
    assert "delete" in errors[0].fix.lower()


def test_output_exists_case_insensitive():
    errors = parse_cdp_errors(
        stdout="",
        stderr="Cannot Create Output of some kind",
        exit_code=255,
    )
    assert any(e.type == "output_exists" for e in errors)


def test_output_exists_tolerates_extra_whitespace():
    errors = parse_cdp_errors(
        stdout="",
        stderr="cannot   create\toutput",
        exit_code=255,
    )
    assert any(e.type == "output_exists" for e in errors)


def test_output_exists_detects_cannot_open_real_cdp_phrasing():
    """Real CDP r8 emits 'Cannot open output file ...' (uses 'open' not
    'create'). Verified empirically against pvoc synth into an existing
    output path."""
    errors = parse_cdp_errors(
        stdout="",
        stderr="ERROR: Cannot open output file /tmp/foo.wav\n",
        exit_code=255,
    )
    assert any(e.type == "output_exists" for e in errors)


def test_output_exists_detects_from_stdout():
    """Real CDP emits this class of error to stdout, not stderr.
    Verified empirically with pvoc synth."""
    errors = parse_cdp_errors(
        stdout="ERROR: INVALID DATA\nERROR: Cannot open output file /tmp/foo.wav\n",
        stderr="",
        exit_code=255,
    )
    assert any(e.type == "output_exists" for e in errors)


# ---------------------------------------------------------------------------
# channel_mismatch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stderr",
    [
        "channel mismatch in input file",
        "input must be mono",
        "this program requires stereo input",
        "input is not mono — convert first",
        "MUST BE STEREO",
    ],
)
def test_channel_mismatch_detects_common_phrasings(stderr):
    errors = parse_cdp_errors(
        stdout="", stderr=stderr, exit_code=1,
    )
    assert any(e.type == "channel_mismatch" for e in errors), (
        f"expected channel_mismatch in errors for stderr={stderr!r}"
    )
    msg = next(e for e in errors if e.type == "channel_mismatch")
    assert "housekeep" in msg.fix.lower()


def test_channel_mismatch_detects_only_works_with_phrasing():
    """Real CDP r8 emits 'Process only works with STEREO files.' for
    channel-constraint failures. Verified empirically against sndinfo
    chandiff on a mono file."""
    errors = parse_cdp_errors(
        stdout="",
        stderr="ERROR: INVALID DATA\nERROR: Process only works with STEREO files.\n",
        exit_code=255,
    )
    assert any(e.type == "channel_mismatch" for e in errors)


def test_channel_mismatch_detects_from_stdout():
    """Real CDP emits channel-mismatch errors to stdout, not stderr."""
    errors = parse_cdp_errors(
        stdout="ERROR: Process only works with MONO files.\n",
        stderr="",
        exit_code=255,
    )
    assert any(e.type == "channel_mismatch" for e in errors)


# ---------------------------------------------------------------------------
# usage_banner_returned
# ---------------------------------------------------------------------------


def test_usage_banner_returned_requires_missing_output(tmp_path):
    out = tmp_path / "missing.wav"
    errors = parse_cdp_errors(
        stdout="",
        stderr="Usage: blur blur infile outfile blurring\n",
        exit_code=1,
        expected_output=out,
    )
    assert any(e.type == "usage_banner_returned" for e in errors)


def test_usage_banner_returned_skipped_when_output_exists(tmp_path):
    """If the expected output is present, the 'Usage:' string is treated
    as incidental (some CDP programs print usage as part of normal
    completion banners). Don't fire the pattern."""
    out = tmp_path / "exists.wav"
    out.write_bytes(b"some content")
    errors = parse_cdp_errors(
        stdout="",
        stderr="Usage: blur blur infile outfile blurring\n",
        exit_code=0,
        expected_output=out,
    )
    assert not any(e.type == "usage_banner_returned" for e in errors)


def test_usage_banner_returned_skipped_when_no_expected_output():
    """execute() never passes expected_output → pattern can't fire."""
    errors = parse_cdp_errors(
        stdout="",
        stderr="Usage: blur blur infile outfile blurring",
        exit_code=1,
        expected_output=None,
    )
    assert not any(e.type == "usage_banner_returned" for e in errors)


@pytest.mark.parametrize("exit_code", [0, 1, 2, 255])
def test_usage_banner_returned_exit_code_agnostic(tmp_path, exit_code):
    """Design-doc Rule (v7 correction): trigger is behavioral (missing
    output + Usage: present), NOT exit-code dependent. CDP binaries are
    inconsistent about exit codes when printing usage."""
    out = tmp_path / "missing.wav"
    errors = parse_cdp_errors(
        stdout="",
        stderr="Usage: blur blur infile outfile blurring",
        exit_code=exit_code,
        expected_output=out,
    )
    assert any(e.type == "usage_banner_returned" for e in errors), (
        f"failed at exit_code={exit_code}"
    )


def test_usage_banner_returned_matches_stdout_too(tmp_path):
    """Some CDP binaries print usage to stdout rather than stderr.
    Either stream triggers the pattern."""
    out = tmp_path / "missing.wav"
    errors = parse_cdp_errors(
        stdout="Usage: blur blur infile outfile blurring",
        stderr="",
        exit_code=1,
        expected_output=out,
    )
    assert any(e.type == "usage_banner_returned" for e in errors)


def test_usage_banner_returned_word_boundary():
    """Words like 'Usual' or 'Usages' don't trigger the pattern.
    \\b in the regex prevents the false positive."""
    out = Path("/nonexistent/foo.wav")
    errors = parse_cdp_errors(
        stdout="Usually we do X",
        stderr="Usages are diverse",
        exit_code=1,
        expected_output=out,
    )
    assert not any(e.type == "usage_banner_returned" for e in errors)


# ---------------------------------------------------------------------------
# silent_output
# ---------------------------------------------------------------------------


def test_silent_output_detects_zero_rms(tmp_path):
    v = OutputVerification(
        ok=False, exists=True, size_bytes=1000, rms_dbfs=None,
        errors=["silent (rms = 0)"],
    )
    errors = parse_cdp_errors(
        stdout="", stderr="", exit_code=0,
        expected_output=tmp_path / "x.wav",
        verification=v,
    )
    assert any(e.type == "silent_output" for e in errors)


def test_silent_output_detects_below_threshold():
    v = OutputVerification(
        ok=False, exists=True, size_bytes=1000, rms_dbfs=-72.0,
        errors=["below silence threshold -60.0 dBFS (rms = -72.00 dBFS)"],
    )
    errors = parse_cdp_errors(
        stdout="", stderr="", exit_code=0,
        verification=v,
    )
    assert any(e.type == "silent_output" for e in errors)


def test_silent_output_skipped_on_nonzero_exit():
    """When CDP also exits nonzero, the subprocess_error already explains
    the situation — silent output is incidental."""
    v = OutputVerification(
        ok=False, exists=True, size_bytes=1000, rms_dbfs=None,
        errors=["silent (rms = 0)"],
    )
    errors = parse_cdp_errors(
        stdout="", stderr="", exit_code=1,
        verification=v,
    )
    assert not any(e.type == "silent_output" for e in errors)


def test_silent_output_skipped_when_verification_is_none():
    """execute() passes None — pattern can't fire."""
    errors = parse_cdp_errors(
        stdout="", stderr="", exit_code=0,
        verification=None,
    )
    assert not any(e.type == "silent_output" for e in errors)


def test_silent_output_skipped_when_file_missing():
    """A missing file is a different failure (likely usage_banner_returned
    or subprocess_error). Don't conflate."""
    v = OutputVerification(
        ok=False, exists=False, size_bytes=0, rms_dbfs=None,
        errors=["file does not exist: /foo/bar.wav"],
    )
    errors = parse_cdp_errors(
        stdout="", stderr="", exit_code=0,
        verification=v,
    )
    assert not any(e.type == "silent_output" for e in errors)


def test_silent_output_skipped_on_unrelated_verification_failure():
    """Size-below-threshold or unreadable-wav don't trigger silent_output.
    Those are different anti-patterns covered by the generic
    output_verification_failed."""
    v = OutputVerification(
        ok=False, exists=True, size_bytes=50, rms_dbfs=None,
        errors=["file size 50 bytes is below minimum 100"],
    )
    errors = parse_cdp_errors(
        stdout="", stderr="", exit_code=0,
        verification=v,
    )
    assert not any(e.type == "silent_output" for e in errors)


# ---------------------------------------------------------------------------
# Multi-pattern + clean-input cases
# ---------------------------------------------------------------------------


def test_no_patterns_on_clean_stderr():
    errors = parse_cdp_errors(
        stdout="processing complete\n",
        stderr="",
        exit_code=0,
    )
    assert errors == []


def test_multiple_patterns_all_appended():
    """If multiple patterns match (rare in real life but possible
    artificially), each gets its own entry — additive, not overriding."""
    errors = parse_cdp_errors(
        stdout="",
        stderr="cannot create output AND input must be mono",
        exit_code=255,
    )
    types = {e.type for e in errors}
    assert "output_exists" in types
    assert "channel_mismatch" in types
