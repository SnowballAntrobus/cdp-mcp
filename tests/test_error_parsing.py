"""Unit tests for the CDP stderr pattern parser.

The parser is exercised end-to-end via process() and execute() in
test_process.py / test_execute.py; this file pins down the matching
logic directly so regex changes are caught at the unit level.

The Phase 6 refusal-corpus patterns are tested with VERBATIM refusal
strings quoted from the curation transcripts (docs/curation/tranche*.md)
— each test cites its tranche. Two end-to-end checks against real CDP
(gated on the ``real_cdp_path`` fixture) prove the structured entries
reach process() results for genuinely refusing binaries.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import detect_cdp
from cdp_mcp.error_parsing import parse_cdp_errors
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.schema import OutputVerification
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.process import process_impl

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


# ---------------------------------------------------------------------------
# Phase 6 refusal corpus — one case per pattern, verbatim strings from
# the curation transcripts (docs/curation/tranche*.md).
# ---------------------------------------------------------------------------


def _types(errors):
    return {e.type for e in errors}


def test_no_grains_found_verbatim():
    """tranche6/tranche19: grain family refuses continuous material.
    Live-verified stdout capture (note CDP's progress-junk prefix)."""
    errors = parse_cdp_errors(
        stdout=(
            "0 min  0.00 sec0 min  0.00 secERROR: INVALID DATA\n"
            "ERROR: No grains found.\n\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "no_grains_found" in _types(errors)
    e = next(e for e in errors if e.type == "no_grains_found")
    assert "gate gate 1" in e.fix


def test_no_silence_gaps_verbatim():
    """tranche11b: retime modes 3/6-10 refuse material without exact
    digital-zero gaps. Live-verified stdout capture."""
    errors = parse_cdp_errors(
        stdout=(
            "INFO: Counting silences between events.\n"
            "ERROR: INVALID DATA\n"
            "ERROR: NO SILENCE-GAPS FOUND IN FILE.\n\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "no_silence_gaps" in _types(errors)
    e = next(e for e in errors if e.type == "no_silence_gaps")
    assert "gate gate 1" in e.fix
    assert "dBFS" in e.fix


def test_no_change_refused_verbatim():
    """tranche10b: shift 0 refused — SoundThread defaults the param to 0,
    the CDP binary refuses the identity transform."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: CANNOT ACHIEVE TASK: \n"
            "ERROR: NO CHANGE to original sound file.\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "no_change_refused" in _types(errors)


@pytest.mark.parametrize(
    "stdout",
    [
        # tranches 5/7/8/9/10a/22 — long form.
        "ERROR: Insufficient parameters on command line.\n",
        # tranches 10a/11a/19 — short form.
        "ERROR: Insufficient parameters on cmdline.\n",
    ],
)
def test_insufficient_parameters_both_phrasings(stdout):
    errors = parse_cdp_errors(stdout=stdout, stderr="", exit_code=255)
    assert "insufficient_parameters" in _types(errors)
    e = next(e for e in errors if e.type == "insufficient_parameters")
    assert "positional" in e.fix.lower()


def test_breakpoint_not_permitted_verbatim():
    """tranche1 (and a dozen others): brk file passed for a scalar-only
    parameter."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: Cannot read parameter 1 [b_rng.brk]: "
            "brkpnt_files not permitted.\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "breakpoint_not_permitted" in _types(errors)
    e = next(e for e in errors if e.type == "breakpoint_not_permitted")
    assert "scalar" in e.fix.lower() or "plain number" in e.fix.lower()


def test_out_of_range_extracts_bounds_to_form():
    """tranche1_timedomain: 'Parameter[1] Value (17.000000) out of range
    (2.000000 to 16.000000)' — the bounds land in the message so the
    retry can be exact."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: Parameter[1] Value (17.000000) out of range "
            "(2.000000 to 16.000000)\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "parameter_out_of_range" in _types(errors)
    e = next(e for e in errors if e.type == "parameter_out_of_range")
    assert "2.000000" in e.message
    assert "16.000000" in e.message
    assert "2.000000" in e.fix


def test_out_of_range_extracts_bounds_dash_form_negative():
    """tranche19: datafile ratios use the DASH form with negative bounds
    — 'Ratio (50.000000) out of range (-48.000000 - 48.000000)'."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: INVALID DATA\n"
            "ERROR: Ratio (50.000000) out of range (-48.000000 - 48.000000)\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "parameter_out_of_range" in _types(errors)
    e = next(e for e in errors if e.type == "parameter_out_of_range")
    assert "-48.000000" in e.message
    assert "48.000000" in e.message


def test_out_of_range_mode_digit_bracket_form():
    """tranche7/18: 'Program mode value [5] is out of range [1 - 4].' —
    the message quotes the raw line, so the mode context is visible."""
    errors = parse_cdp_errors(
        stdout="ERROR: Program mode value [5] is out of range [1 - 4].\n",
        stderr="",
        exit_code=255,
    )
    assert "parameter_out_of_range" in _types(errors)
    e = next(e for e in errors if e.type == "parameter_out_of_range")
    assert "Program mode value" in e.message


def test_out_of_range_brkpntfile_form():
    """tranche21: in-brk values out of range — 'Value (0.000000) out of
    range (0.000010 to 0.900000) in brkpntfile b_fi.brk.'"""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: Value (0.000000) out of range "
            "(0.000010 to 0.900000) in brkpntfile b_fi.brk.\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "parameter_out_of_range" in _types(errors)


def test_out_of_range_without_bounds_stays_generic():
    """tranche13: 'Start of fade time : out of range.' carries no bounds
    — matching it would produce a rangeless entry, so per forensics
    5.1.3 it deliberately falls back to the generic subprocess_error."""
    errors = parse_cdp_errors(
        stdout="ERROR: Start of fade time : out of range.\n",
        stderr="",
        exit_code=255,
    )
    assert "parameter_out_of_range" not in _types(errors)


def test_invalid_cdp_file_verbatim():
    """tranche13: '.evl' data renamed to '.dat' refused on extension
    alone — 'ERROR: out1.dat is not a valid CDP file'."""
    errors = parse_cdp_errors(
        stdout="ERROR: out1.dat is not a valid CDP file\n",
        stderr="",
        exit_code=255,
    )
    assert "invalid_cdp_file" in _types(errors)
    e = next(e for e in errors if e.type == "invalid_cdp_file")
    assert "extension" in e.fix.lower()


def test_formant_flag_missing_verbatim():
    """tranche22: argv-order landmine — '-p8 <brk>' exits 0 where
    '<brk> -p8' exits 255 with this message."""
    errors = parse_cdp_errors(
        stdout="ERROR: Formant flag missing on cmdline.\n",
        stderr="",
        exit_code=255,
    )
    assert "formant_flag_missing" in _types(errors)
    e = next(e for e in errors if e.type == "formant_flag_missing")
    assert "before" in e.fix.lower()


def test_program_dead_by_design_verbatim():
    """tranche23: hfperm delperm's unconditional kill-switch (doubled
    'ERROR:' prefix is verbatim)."""
    errors = parse_cdp_errors(
        stdout="ERROR: ERROR: This program is currently malfunctioning.\n",
        stderr="",
        exit_code=255,
    )
    assert "program_dead_by_design" in _types(errors)
    e = next(e for e in errors if e.type == "program_dead_by_design")
    assert "no parameter" in e.fix.lower()


def test_mix_end_overflow_verbatim():
    """tranche12: submix LP64 bug — stereo paths need an explicit -e."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: INVALID DATA\n"
            "ERROR: Mix cuts off before 2nd file enters\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "mix_end_overflow" in _types(errors)
    e = next(e for e in errors if e.type == "mix_end_overflow")
    assert "-e" in e.fix


def test_input_wrong_type_bare_form():
    """tranche20: time-domain program given a .ana — 'File rich2.ana is
    not of correct type' with no channel suffix."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: INVALID DATA\n"
            "ERROR: File rich2.ana is not of correct type\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "input_wrong_type" in _types(errors)
    assert "channel_mismatch" not in _types(errors)


def test_input_wrong_type_mode_specific_form():
    """tranche16: 'File st2.wav is not of correct type for Mode 3'."""
    errors = parse_cdp_errors(
        stdout="ERROR: File st2.wav is not of correct type for Mode 3\n",
        stderr="",
        exit_code=255,
    )
    assert "input_wrong_type" in _types(errors)


def test_input_wrong_type_suppressed_by_channel_suffix():
    """tranche6/9/13/...: 'File st2.wav is not of correct type (must be
    mono)' is a CHANNEL constraint — channel_mismatch explains it more
    precisely, so input_wrong_type must not double-fire."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: INVALID DATA\n"
            "ERROR: File st2.wav is not of correct type (must be mono)\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "channel_mismatch" in _types(errors)
    assert "input_wrong_type" not in _types(errors)


def test_channel_mismatch_covers_must_be_stereo_suffix_form():
    """tranche10b verbatim: 'File ... is not of correct type (must be
    stereo)' — confirms the pre-existing channel regex covers the corpus
    suffix phrasing for stereo too."""
    errors = parse_cdp_errors(
        stdout=(
            "ERROR: File in.wav is not of correct type (must be stereo)\n"
        ),
        stderr="",
        exit_code=255,
    )
    assert "channel_mismatch" in _types(errors)
    assert "input_wrong_type" not in _types(errors)


# ---------------------------------------------------------------------------
# Real CDP (gated): refusals surface as structured errors via process()
# ---------------------------------------------------------------------------


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


@pytest.fixture
def refusal_env(tmp_path, real_cdp_path):
    """Real-CDP session with refusal-inducing inputs: a pure tone (no
    grain articulation) and flat noise (no digital-zero gaps)."""
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    for binary in ("grain", "retime"):
        if not (real_cdp_path / binary).is_file():
            pytest.skip(f"{binary} binary not present in CDP_PATH.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    session, _ = sessions.set_active("refusal_corpus_v1")
    sr = 44100
    t = np.arange(sr) / sr
    tone = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    sf.write(str(session.inputs_dir / "tone.wav"), tone, sr, subtype="PCM_16")
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(sr) * 0.2).astype(np.float32)
    sf.write(str(session.inputs_dir / "flatnoise.wav"), noise, sr, subtype="PCM_16")
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_config,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


async def _run_refusal(env, *, program, mode, submode, input, params):
    return await process_impl(
        _FakeCtx(),
        program=program,
        mode=mode,
        submode=submode,
        input=input,
        params=params,
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )


@pytest.mark.timeout(60)
async def test_grain_reverse_on_tone_real_cdp_structured_no_grains(refusal_env):
    """grain reverse on a pure tone refuses 'No grains found.' — the
    process() result must carry the structured entry with the gate-1
    upstream fix, not just the generic subprocess_error."""
    r = await _run_refusal(
        refusal_env,
        program="grain", mode="reverse", submode=None,
        input="tone.wav", params={},
    )
    assert r["status"] == "failed"
    types = {e["type"] for e in r["errors"]}
    assert "no_grains_found" in types, r["errors"]
    e = next(e for e in r["errors"] if e["type"] == "no_grains_found")
    assert "gate gate 1" in e["fix"]


@pytest.mark.timeout(60)
async def test_retime_3_on_flat_noise_real_cdp_structured_no_silence_gaps(refusal_env):
    """retime retime 3 on flat noise refuses 'NO SILENCE-GAPS FOUND IN
    FILE.' (events are bounded by EXACT zeros; a noise floor is one
    event) — the structured entry with the absolute-dBFS gate fix must
    reach the process() result."""
    r = await _run_refusal(
        refusal_env,
        program="retime", mode="retime", submode=3,
        input="flatnoise.wav",
        params={"minsil": 50, "inevwidth": 500, "outevwidth": 80, "splicelen": 5},
    )
    assert r["status"] == "failed"
    types = {e["type"] for e in r["errors"]}
    assert "no_silence_gaps" in types, r["errors"]
    e = next(e for e in r["errors"] if e["type"] == "no_silence_gaps")
    assert "gate gate 1" in e["fix"]
