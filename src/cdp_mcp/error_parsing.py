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

    if _CHANNEL_MISMATCH_RE.search(combined):
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

    return out
