"""Pattern recognition for known CDP failure modes.

Maps subprocess stdout/stderr (and optionally an expected output path and
verification result) into structured :class:`ErrorEntry` items. Appended
to the existing generic errors (``timeout``, ``subprocess_error``,
``output_verification_failed``) by ``process()`` and ``execute()``.

Patterns ship as conservative first approximations — regex tuning is
refined opportunistically as real CDP outputs are observed. False
positives are worse than false negatives here: a misleading ``fix`` hint
sends the LLM down the wrong path, while a missed match falls back to
the generic ``subprocess_error`` (still actionable, just not specific).

The Phase 6 extension maps the refusal corpus accumulated during
curation (verbatim quotes in ``docs/curation/tranche*.md``) to
structured entries with fix hints grounded in the curated knowledge —
see the "Phase 6 refusal corpus" section below. Fix hints that name a
concrete upstream repair (``gate gate 1``, explicit ``-e`` on submix)
cite the tranche where that repair was verified against real CDP.

**A note on streams.** Real CDP emits many "error"-class messages to
*stdout* rather than stderr (verified empirically with ``pvoc synth``
refuse-to-clobber and ``sndinfo chandiff`` channel-mismatch). The
``output_exists`` and ``channel_mismatch`` patterns therefore search
both streams. ``usage_banner_returned`` already did. ``silent_output``
is verification-based and stream-agnostic.

The function is pure over its inputs; never raises.
"""

from __future__ import annotations

import re
from pathlib import Path

from .schema import ErrorEntry, OutputVerification

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Refuse-to-clobber / output-path-unusable. Real CDP r8 emits
# "Cannot open output file ..." (verified empirically with pvoc synth);
# the fake_subprocess fixture emits "cannot create output file ..." for
# --cdp-refuse-clobber. Both phrasings accepted, in either stream.
_OUTPUT_EXISTS_RE = re.compile(r"cannot\s+(create|open)\s+output", re.IGNORECASE)

# Channel-constraint errors. Real CDP r8 emits
# "Process only works with STEREO files." (verified empirically with
# sndinfo chandiff on a mono input). Other phrasings remain speculative
# — leaving them in covers cases I haven't empirically observed yet.
_CHANNEL_MISMATCH_RE = re.compile(
    r"("
    r"channel.*mismatch"
    r"|must\s+be\s+mono"
    r"|must\s+be\s+stereo"
    r"|input.*not\s+mono"
    r"|requires?\s+mono"
    r"|requires?\s+stereo"
    r"|only\s+works\s+with\s+(mono|stereo)"   # real CDP r8 phrasing
    r")",
    re.IGNORECASE,
)

# "Usage:" banner — every CDP binary prints one when invoked with no /
# wrong arguments. ``\b`` prevents matching "Usual" / "Usages" etc.
_USAGE_BANNER_RE = re.compile(r"\busage:", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Phase 6 refusal corpus (docs/curation/tranche*.md, verbatim quotes)
# ---------------------------------------------------------------------------
# Every pattern below is grounded in verbatim refusal text recorded during
# curation; each comment cites the tranche(s) where the quote appears.
# Per forensics 5.1.3, over-generic phrasings ("Application doesn't work
# with this type of infile", bare "out of range" with no bounds) are
# deliberately NOT matched — a misleading fix is worse than none.

# "ERROR: INVALID DATA / ERROR: No grains found." — grain family
# articulation constraint (tranches 6, 19; grain_reverse entry).
_NO_GRAINS_RE = re.compile(r"no\s+grains\s+found", re.IGNORECASE)

# "ERROR: NO SILENCE-GAPS FOUND IN FILE." — retime event-timing family
# (tranche 11b); events are bounded by EXACT digital zeros, no threshold.
_NO_SILENCE_GAPS_RE = re.compile(r"no\s+silence[\s-]*gaps\s+found", re.IGNORECASE)

# "ERROR: CANNOT ACHIEVE TASK: / ERROR: NO CHANGE to original sound file."
# — identity-transform refusal, e.g. shift 0 on the DC-offset program
# (tranche 10b: SoundThread defaults that param to 0; CDP refuses it).
_NO_CHANGE_RE = re.compile(r"no\s+change\s+to\s+original\s+sound\s*file", re.IGNORECASE)

# "Insufficient parameters on command line." / "... on cmdline." — both
# forms verbatim across tranches 5, 7, 8, 9, 10a, 11a, 19, 22.
_INSUFFICIENT_PARAMS_RE = re.compile(
    r"insufficient\s+parameters\s+on\s+c(?:ommand\s*line|mdline)", re.IGNORECASE,
)

# "Cannot read parameter N [...]: brkpnt_files not permitted." — breakpoint
# file passed for a scalar-only parameter (tranches 1, 2, 6, 14, 16, 21...).
_BRKPNT_NOT_PERMITTED_RE = re.compile(r"brkpnt_files\s+not\s+permitted", re.IGNORECASE)

# Range refusals with extractable bounds. Corpus forms (all verbatim):
#   "Parameter[1] Value (17.000000) out of range (2.000000 to 16.000000)"
#   "Ratio (50.000000) out of range (-48.000000 - 48.000000)"   (dash form)
#   "Value (0.4) out of range (...) in brkpntfile b_len.brk."
#   "Program mode value [5] is out of range [1 - 4]."
#   "harmonic number [1030] out of range 2 - 1024"               (unbracketed)
# Bounds are REQUIRED by the regex: bare "out of range" with no numbers
# (e.g. "Start of fade time : out of range.") stays generic per 5.1.3.
_OUT_OF_RANGE_RE = re.compile(
    r"out\s+of\s+range\s*[\(\[]?\s*(-?\d+(?:\.\d+)?)\s*(?:to\s|-)\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# "ERROR: <name> is not a valid CDP file" — extension-driven data-file
# typing (tranche 13: renamed .evl→.dat refused; source scans for
# plain-text chars only).
_INVALID_CDP_FILE_RE = re.compile(r"is\s+not\s+a\s+valid\s+CDP\s+file", re.IGNORECASE)

# "Formant flag missing on cmdline." — argv-order landmine (tranche 22:
# '-p8 <brk>' exits 0 where '<brk> -p8' exits 255).
_FORMANT_FLAG_MISSING_RE = re.compile(r"formant\s+flag\s+missing", re.IGNORECASE)

# "ERROR: This program is currently malfunctioning." — unconditional
# kill-switch compiled into the binary (tranche 23: hfperm delperm,
# dead by design since June 2004, dev/hfperm/hfperm.c:1865).
_KILL_SWITCH_RE = re.compile(r"program\s+is\s+currently\s+malfunctioning", re.IGNORECASE)

# "ERROR: Mix cuts off before 2nd file enters" — submix LP64 bug
# (tranche 12: default end time overflows a 32-bit iparam on stereo
# paths; explicit -e unblocks).
_MIX_CUTS_OFF_RE = re.compile(r"mix\s+cuts\s+off\s+before", re.IGNORECASE)

# "File <name> is not of correct type" — wrong input file type (wav where
# .ana expected or vice versa, text in an audio slot, or a mode-specific
# channel restriction). When the "(must be mono/stereo)" suffix is present
# the channel_mismatch pattern already explains it more precisely, so this
# entry is suppressed in that case (see parse_cdp_errors).
_WRONG_TYPE_RE = re.compile(r"is\s+not\s+of\s+correct\s+type", re.IGNORECASE)


# Simple stream-matched patterns: (regex, type, message, fix). Matched
# against the combined stderr+stdout view (forensics 5.1.2: CDP emits
# error-class messages to stdout). Special-cased patterns (range
# extraction, wrong-type suppression) live in parse_cdp_errors directly.
_SIMPLE_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        _NO_GRAINS_RE,
        "no_grains_found",
        (
            "CDP found no grains in the input — the grain family needs at "
            "least two amplitude-separable grains and refuses continuous "
            "material (pure tones, flat noise, pads)."
        ),
        (
            "Grain detection is amplitude-gating: use material with real "
            "attacks and dips between events (percussive, speech, iterative "
            "sources); create silences upstream with 'gate gate 1 <in> <out> "
            "<dB>' (ABSOLUTE dBFS threshold, e.g. -40; mode 1 preserves "
            "duration); or lower this program's gate level so quieter "
            "troughs count as holes between grains."
        ),
    ),
    (
        _NO_SILENCE_GAPS_RE,
        "no_silence_gaps",
        (
            "CDP found no silence gaps in the input — this program "
            "segments events at runs of EXACT digital zeros, so any noise "
            "floor makes the whole file one event."
        ),
        (
            "There is no detection threshold; gate the input first: "
            "'gate gate 1 <in> <out> <dB>' zeroes everything below an "
            "ABSOLUTE dBFS threshold (e.g. -40) while preserving duration, "
            "creating the digital-zero gaps this program needs. Verified "
            "chain: gate gate 1, then this program finds its events."
        ),
    ),
    (
        _NO_CHANGE_RE,
        "no_change_refused",
        (
            "CDP refused an identity transform — the parameter values "
            "would leave the sound unchanged (e.g. a shift/offset of 0)."
        ),
        (
            "Use a parameter value that actually alters the sound, or skip "
            "this step. Some downstream toolkits default such parameters "
            "to 0; the CDP binary refuses that default outright."
        ),
    ),
    (
        _INSUFFICIENT_PARAMS_RE,
        "insufficient_parameters",
        "CDP refused: a required parameter is missing from the command line.",
        (
            "Supply every required positional. Two curation-verified traps: "
            "some usage banners omit required positionals entirely, and "
            "some programs take banner-documented 'flags' as required "
            "positionals instead. Check the parameter list (and required "
            "markers) in get_program_info."
        ),
    ),
    (
        _BRKPNT_NOT_PERMITTED_RE,
        "breakpoint_not_permitted",
        (
            "CDP rejected a breakpoint file for a parameter that only "
            "accepts a scalar value."
        ),
        (
            "Pass a plain number for this parameter — it is not "
            "time-varying-capable. get_program_info marks which parameters "
            "accept breakpoint files. Note: the parameter number CDP quotes "
            "is internal, stage-dependent numbering and may not match the "
            "usage banner's ordering."
        ),
    ),
    (
        _INVALID_CDP_FILE_RE,
        "invalid_cdp_file",
        "CDP rejected a file as 'not a valid CDP file'.",
        (
            "CDP types many data files by EXTENSION and rejects non-plain-"
            "text content: a correctly formatted file with the wrong "
            "extension is refused on the extension alone (e.g. envelope "
            "data must be .evl, not .dat). Ensure the file has exactly the "
            "extension the program expects and contains only plain ASCII "
            "text; write_data_file with the expected extension is the "
            "reliable path."
        ),
    ),
    (
        _FORMANT_FLAG_MISSING_RE,
        "formant_flag_missing",
        "CDP refused: the formant-resolution flag (-f/-p) is missing or misplaced.",
        (
            "This program requires -f<N> or -p<N>, and the flag must come "
            "BEFORE the later positionals in argv: '-p8 <datafile>' "
            "succeeds where '<datafile> -p8' is refused with this exact "
            "message. Add the flag (typically -p8) ahead of the remaining "
            "arguments; via process() the curated entry's declaration "
            "order handles the placement."
        ),
    ),
    (
        _KILL_SWITCH_RE,
        "program_dead_by_design",
        (
            "This CDP program is dead by design: the 'currently "
            "malfunctioning' message is an unconditional kill-switch "
            "compiled into the binary."
        ),
        (
            "No parameter change will make this program run — the error "
            "fires on every invocation (verified for hfperm delperm/"
            "delperm2, disabled in source since June 2004). Use a sibling "
            "program or a different mode; see list_programs / "
            "get_program_info for alternatives."
        ),
    ),
    (
        _MIX_CUTS_OFF_RE,
        "mix_end_overflow",
        (
            "The mix ended before a later-entering file's start time "
            "('Mix cuts off before 2nd file enters')."
        ),
        (
            "Known CDP LP64 bug: the default mix end time overflows a "
            "32-bit parameter on any stereo path, truncating the mix. Pass "
            "an explicit end time covering the full mix duration (the -e "
            "flag, e.g. -e2.0) to unblock."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_cdp_errors(
    *,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    expected_output: Path | None = None,
    verification: OutputVerification | None = None,
) -> list[ErrorEntry]:
    """Pattern-match CDP output streams into structured ``ErrorEntry`` items.

    Args:
        stdout: Captured subprocess stdout.
        stderr: Captured subprocess stderr.
        exit_code: Subprocess exit code. ``None`` means the caller killed
            it via timeout — the caller should not invoke this function
            in that case, since stderr is partial output.
        expected_output: Path the run was supposed to produce, or ``None``
            for ``execute()`` calls where the LLM specifies the command
            directly and there is no engine-known output. Required for
            ``usage_banner_returned``.
        verification: Result of ``verify_output()`` on the expected
            output, or ``None`` for ``execute()`` (which doesn't run
            verification). Required for ``silent_output``.

    Returns:
        List of structured ``ErrorEntry`` items, additive to whatever the
        caller has already collected. Empty if nothing matched.
    """
    out: list[ErrorEntry] = []

    # Real CDP often emits error-class messages to stdout rather than
    # stderr (verified empirically). Search the combined view for the
    # two patterns that benefit.
    combined = stderr + "\n" + stdout

    if _OUTPUT_EXISTS_RE.search(combined):
        out.append(ErrorEntry(
            type="output_exists",
            message="CDP refused to overwrite an existing output file.",
            fix=(
                "Delete the target output path before retry, or use a "
                "different output_name. process() pre-deletes its outputs "
                "automatically — this typically means execute() bypassed "
                "that contract or the path collided with an external file."
            ),
        ))

    channel_mismatched = _CHANNEL_MISMATCH_RE.search(combined) is not None
    if channel_mismatched:
        out.append(ErrorEntry(
            type="channel_mismatch",
            message=(
                "CDP rejected the input file because of a channel-count "
                "constraint (mono vs stereo)."
            ),
            fix=(
                "Run housekeep stereo or housekeep mono upstream to "
                "convert the input to the channel count this program "
                "expects. Check channel_constraint in get_program_info "
                "for the requirement."
            ),
        ))

    if (
        expected_output is not None
        and not expected_output.exists()
        and (_USAGE_BANNER_RE.search(stderr) or _USAGE_BANNER_RE.search(stdout))
    ):
        out.append(ErrorEntry(
            type="usage_banner_returned",
            message=(
                "CDP printed its usage banner instead of running. The "
                "argv shape was probably wrong."
            ),
            fix=(
                "Most common cause: the knowledge entry's submode is "
                "unset or wrong for the intended CDP submode. Also check "
                "parameter ordering and types against get_program_info. "
                "The raw usage banner appears in stderr/stdout above."
            ),
        ))

    if (
        verification is not None
        and verification.exists
        and not verification.ok
        and exit_code == 0
    ):
        rms_related = any(
            "silent" in e.lower() or "below silence threshold" in e.lower()
            for e in verification.errors
        )
        if rms_related:
            out.append(ErrorEntry(
                type="silent_output",
                message=(
                    "CDP exited 0 but the output file is digitally silent "
                    "or near-silent."
                ),
                fix=(
                    "Common causes: envelope-gating amplitude to zero, "
                    "parameter combinations that produce no signal, or "
                    "the input being silent itself. Inspect the input "
                    "and parameters via analyze() or visualize(). If "
                    "silence is intentional, call execute() directly to "
                    "bypass verification."
                ),
            ))

    # Phase 6 corpus patterns: simple stream matches first ...
    for pattern, err_type, message, fix in _SIMPLE_PATTERNS:
        if pattern.search(combined):
            out.append(ErrorEntry(type=err_type, message=message, fix=fix))

    # ... then the two special cases.

    # parameter_out_of_range: only fires when bounds are extractable —
    # the range goes into the message so the retry can be exact.
    range_match = _OUT_OF_RANGE_RE.search(combined)
    if range_match:
        lo, hi = range_match.group(1), range_match.group(2)
        line = next(
            (
                ln.strip() for ln in combined.splitlines()
                if _OUT_OF_RANGE_RE.search(ln)
            ),
            "",
        )
        quoted = f' Raw refusal: "{line[:200]}"' if line else ""
        out.append(ErrorEntry(
            type="parameter_out_of_range",
            message=(
                f"CDP rejected a value as out of range "
                f"({lo} to {hi}).{quoted}"
            ),
            fix=(
                f"Supply a value within {lo} to {hi}. CDP-enforced bounds "
                "are often runtime-dependent (tied to input duration, "
                "window count, or sample rate) and can differ from banner "
                "or manual claims — treat the range in this message as "
                "authoritative for this input. get_program_info shows the "
                "curated ranges."
            ),
        ))

    # input_wrong_type: suppressed when the channel_mismatch pattern also
    # matched — "File x.wav is not of correct type (must be mono)" is a
    # channel constraint, already explained more precisely above.
    if _WRONG_TYPE_RE.search(combined) and not channel_mismatched:
        out.append(ErrorEntry(
            type="input_wrong_type",
            message=(
                "CDP rejected an input file as not of the correct type "
                "for this program or mode."
            ),
            fix=(
                "Check input_format in get_program_info: spectral "
                "programs need .ana analysis files (make one with pvoc "
                "anal), time-domain programs need .wav (resynthesize with "
                "pvoc synth), and some slots expect text data files. "
                "Mode-specific channel restrictions can also surface this "
                "way when no '(must be mono/stereo)' suffix is printed."
            ),
        ))

    return out
