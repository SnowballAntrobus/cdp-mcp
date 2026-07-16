"""Phase 2 Task 5 — `breakpoint_capable` curation review tests.

Locks in the empirical verdict from the Task 5 probe pass: which curated
parameters CDP r8 actually accepts breakpoint envelopes for, and which
reject them with ``brkpnt_files not permitted``.

Two tiers of coverage:

1. **Knowledge-index integrity.** The expectation table below mirrors the
   forensic findings in ``docs/phase-2-breakpoint-review.md``. Any drift
   between the JSON and the empirical record trips a test failure here.
   This makes accidental flips visible to the test suite long before they
   reach a real-CDP session.

2. **Compiler behavior** for each newly-flipped parameter — a 2-point
   envelope compiles successfully (positive case). Stay-False parameters
   are not asserted at the unit-compiler level (the
   ``param_breakpoint_not_capable`` rejection is enforced one layer up in
   ``validate_node``; covering all 16 negatives at the JSON-integrity
   level keeps the matrix tight without duplicating compiler tests).
"""

from __future__ import annotations

import pytest

from cdp_mcp.breakpoint_compiler import compile_breakpoint_value
from cdp_mcp.knowledge.loader import KnowledgeIndex

# Empirical findings from the Task 5 probe pass (run against CDP r8 in
# cdpr8/_cdp/_cdprogs). Updating any cell in this table is a curation
# decision and must pair with an entry in docs/phase-2-breakpoint-review.md.
_EXPECTED_BREAKPOINT_CAPABLE: dict[tuple[str, str, int | None], dict[str, bool]] = {
    # --- Phase 5 wave 3 (tranche 9: sibling submodes of already-curated
    # pairs; see docs/curation/tranche9_submodes_findings.json) ---
    ("scramble", "scramble", 9): {
        "seed": False,
        "cnt": False,
        "trns": True,
        "atten": True,
    },
    ("filter", "bank", 5): {
        "q": True, "gain": False, "lof": False, "hif": False,
        "filtcnt": False, "tail": False, "scat": False, "double": False,
    },
    ("filter", "bank", 6): {
        "q": True, "gain": False, "lof": False, "hif": False,
        "interval": False, "tail": False, "scat": False, "double": False,
    },
    ("morph", "bridge", 2): {
        "offset": False, "sf2": False, "sa2": False,
        "ef2": False, "ea2": False, "start": False, "end": False,
    },
    ("morph", "bridge", 3): {
        "offset": False, "sf2": False, "sa2": False,
        "ef2": False, "ea2": False, "start": False, "end": False,
    },
    ("modify", "radical", 2): {
        "repeats": False, "chunklen": False,
        "scatter": False, "smooth": False,
    },
    ("modify", "radical", 5): {
        "modfrq": True,
    },
    ("modify", "speed", 5): {
        "accel": False, "goaltime": False, "starttime": False,
    },
    ("envspeak", "envspeak", 2): {
        "wsize": False, "splice": False, "offset": False,
    },
    ("synth", "wave", 2): {
        "srate": False, "chans": False, "dur": False,
        "frq": True, "amp": True, "tabsize": False,
    },
    ("synth", "wave", 4): {
        "srate": False, "chans": False, "dur": False,
        "frq": True, "amp": True, "tabsize": False,
    },
    ("specfnu", "specfnu", 2): {
        "squeeze": True, "centre": False, "gain": False,
        "at_trough": False, "force_fundamental": False,
        "short_window": False, "exclude_nonharmonic": False,
        "kill_harmonic": False, "silence_unpitched": False,
    },
    # --- Phase 5 wave 2b (tranche 8; see docs/curation/) ---
    ("scramble", "scramble", 10): {
        "seed": False,
        "cnt": False,
        "trns": True,
        "atten": True,
    },
    ("texture", "grouped", 5): {
        "notedata": False,
        "outdur": False,
        "packing": True,
        "scatter": True,
        "tgrid": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "minpich": True,
        "maxpich": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "gpsizelo": True,
        "gpsizehi": True,
        "gppaklo": True,
        "gppakhi": True,
        "gpranglo": True,
        "gpranghi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "fixstep": False,
    },
    ("envspeak", "envspeak", 1): {
        "wsize": False,
        "splice": False,
        "offset": False,
        "repet": True,
        "rand": True,
    },
    ("morph", "bridge", 1): {
        "offset": False,
        "sf2": False,
        "sa2": False,
        "ef2": False,
        "ea2": False,
        "start": False,
        "end": False,
    },
    ("distort", "reform", 6): {
        # no numeric parameters
    },
    ("distort", "delete", 2): {
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("distort", "replace", None): {
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("analjoin", "join", None): {
        # no numeric parameters
    },
    ("newdelay", "newdelay", None): {
        "midipitch": True,
        "mix": False,
        "feedback": False,
    },
    ("quirk", "quirk", 1): {
        "powfac": False,
    },
    ("silend", "silend", 1): {
        "sildur": False,
    },
    # --- Phase 5 wave 2a (tranche 7: unblocked entries; see docs/curation/) ---
    ("submix", "mix", None): {
        "atten": False,
    },
    ("envel", "extract", 1): {
        "wsize": False,
    },
    ("formants", "get", None): {
        "fbands": False,
    },
    ("formants", "put", 1): {
        "quicksearch": False, "lof": False, "hif": False, "gain": False,
    },
    ("synth", "noise", None): {
        "srate": False, "chans": False, "dur": False, "amp": True,
    },
    ("synth", "wave", 1): {
        "srate": False, "chans": False, "dur": False,
        "frq": True, "amp": True, "tabsize": False,
    },
    # --- Phase 5 tranches 5-6 (sandbox-CDP probed; see docs/curation/) ---
    ("submix", "interleave", None): {
        # no numeric parameters
    },
    ("envel", "impose", 1): {
        "wsize": False,
    },
    ("envel", "replace", 1): {
        "wsize": False,
    },
    ("formants", "vocode", None): {
        "fbands": False,
        "lof": False,
        "hif": False,
        "gain": False,
    },
    ("spec", "grab", None): {
        "time": False,
    },
    ("modify", "loudness", 1): {
        "gain": True,
    },
    ("filter", "bank", 1): {
        "q": True,
        "gain": False,
        "lof": False,
        "hif": False,
        "tail": False,
        "scat": False,
        "double": False,
    },
    ("grain", "reverse", None): {
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "duplicate", None): {
        "repeats": True,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "timewarp", None): {
        "ratio": True,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "rerhythm", 1): {
        "multfile": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "reposition", None): {
        "timefile": False,
        "offset": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("pitch", "tune", 1): {
        "frequency": False,
        "focus": True,
        "clarity": True,
        "trace": True,
        "bcut": True,
    },
    ("combine", "interleave", None): {
        "leafsize": False,
    },
    ("combine", "max", None): {
        # no numeric parameters
    },
    ("strange", "shift", 4): {
        "frqshift": True,
        "frqlo": True,
        "frqhi": True,
        "log_interp": False,
    },
    ("distort", "interact", 2): {
        # no numeric parameters
    },
    ("clip", "clip", 2): {
        "fraction": False,
    },
    # --- Phase 3 tranche 3 (sandbox-CDP probed; see docs/curation/) ---
    ("texture", "simple", 5): {
        "notedata": False,
        "outdur": False,
        "packing": True,
        "scatter": True,
        "tgrid": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "minpich": True,
        "maxpich": True,
        "omit": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
    },
    ("modify", "stack", None): {
        "transpos": False,
        "count": False,
        "lean": False,
        "atk_offset": False,
        "gain": False,
        "dur": False,
        "normalise": False,
    },
    ("distort", "divide", None): {
        "divider": True,
        "interpolate": False,
    },
    ("distort", "omit", None): {
        "omit": True,
        "group": False,
    },
    ("extend", "doublets", None): {
        "segdur": True,
        "repets": False,
        "sync": False,
    },
    ("bounce", "bounce", None): {
        "count": False,
        "startgap": False,
        "shorten": False,
        "endlevel": False,
        "ewarp": False,
        "shrink": False,
        "cut_overlap": False,
        "trim_start": False,
    },
    ("specfnu", "specfnu", 1): {
        "narrow": True,
        "gain": False,
    },
    ("stretch", "spectrum", 1): {
        "frq_divide": False,
        "maxstretch": False,
        "exponent": False,
        "depth": True,
    },
    ("focus", "fold", None): {
        "lofrq": True,
        "hifrq": True,
    },
    ("focus", "step", None): {
        "timestep": False,
    },
    ("blur", "spread", None): {
        "fchans": False,
        "pbands": False,
        "spread": True,
    },
    ("blur", "suppress", None): {
        "n": True,
    },
    # --- Phase 3 tranche 2 (sandbox-CDP probed; see docs/curation/) ---
    ("modify", "revecho", 2): {
        "delay": False,
        "mix": False,
        "feedback": False,
        "lfomod": False,
        "lfofreq": False,
        "lfophase": False,
        "lfodelay": False,
        "tail": False,
        "prescale": False,
        "seed": False,
    },
    ("distort", "average", None): {
        "cyclecnt": True,
        "maxwavelen": False,
        "skipcycles": False,
    },
    ("distort", "fractal", None): {
        "scaling": True,
        "loudness": True,
        "pre_attenuation": False,
    },
    ("distort", "interpolate", None): {
        "multiplier": True,
        "skipcycles": False,
    },
    ("envel", "dovetail", 1): {
        "infadedur": False,
        "outfadedur": False,
        "intype": False,
        "outtype": False,
        "times": False,
    },
    ("sfedit", "cut", 1): {
        "start": False,
        "end": False,
        "splice": False,
    },
    ("stretch", "time", 1): {
        "timestretch": True,
    },
    ("strange", "glis", 1): {
        "fchans": False,
        "pbands": False,
        "glisrate": True,
        "topfrq": False,
    },
    ("strange", "invert", 1): {
        # no numeric parameters
    },
    ("hilite", "trace", 1): {
        "n": True,
    },
    ("spec", "magnify", None): {
        "time": False,
        "dur": False,
    },
    ("focus", "accu", None): {
        "decay": True,
        "glis": True,
    },
    # --- Phase 3 tranche 1 (sandbox-CDP probed; see docs/curation/) ---
    ("modify", "radical", 1): {
        # no numeric parameters
    },
    ("modify", "speed", 2): {
        "semitones": True,
    },
    ("distort", "multiply", None): {
        "multiplier": True,
    },
    ("distort", "repeat", None): {
        "multiplier": True,
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("extend", "zigzag", 1): {
        "start": False,
        "end": False,
        "dur": False,
        "minzig": False,
        "splicelen": False,
        "maxzig": False,
        "seed": False,
    },
    ("extend", "scramble", 1): {
        "minseglen": False,
        "maxseglen": False,
        "outdur": False,
        "splen": False,
        "seed": False,
    },
    ("filter", "lohi", 1): {
        "attenuation": False,
        "passband": False,
        "stopband": False,
        "tail": False,
        "prescale": False,
    },
    ("blur", "avrg", None): {
        "n": True,
    },
    ("blur", "scatter", None): {
        "keep": True,
        "blocksize": True,
    },
    ("blur", "drunk", None): {
        "range": False,
        "starttime": False,
        "duration": False,
    },
    ("focus", "exag", None): {
        "exaggeration": True,
    },
    ("combine", "diff", None): {
        "crossover": True,
        "subzero": False,
    },
    ("morph", "glide", None): {
        "duration": False,
    },
    ("blur", "blur", None): {
        "blurring": True,
    },
    ("extend", "loop", 3): {
        "cnt": False, "start": False, "len": False,
        "step": False, "splen": False, "scat": False,
    },
    ("filter", "sweeping", 2): {
        "acuity": True, "gain": False,
        "lofrq": True, "hifrq": True, "sweepfrq": True,
        "tail": False, "phase": False,
    },
    ("modify", "brassage", 2): {
        "velocity": True,
    },
    ("morph", "morph", 1): {
        "as": False, "ae": False, "fs": False, "fe": False,
        "expa": False, "expf": False, "stagger": False,
    },
}


def _matrix_cases() -> list[tuple[str, str, int | None, str, bool]]:
    """Flatten the expectation table to one (program, mode, submode, param,
    expected) case per row for pytest's parametrize. Since the
    (program, mode, submode) re-keying (commit 728b986) each key carries
    its entry's declared submode — None for submode-less entries — so
    lookups stay exact-triple even on pairs curated in several submodes."""
    return [
        (program, mode, submode, param, expected)
        for (program, mode, submode), params in _EXPECTED_BREAKPOINT_CAPABLE.items()
        for param, expected in params.items()
    ]


@pytest.fixture(scope="module")
def knowledge_index() -> KnowledgeIndex:
    return KnowledgeIndex.load()


@pytest.mark.parametrize(
    ("program", "mode", "submode", "param", "expected"), _matrix_cases(),
    ids=[
        f"{p}_{m}_sm{s}_{param}_{expected}"
        for (p, m, s, param, expected) in _matrix_cases()
    ],
)
def test_breakpoint_capable_matches_empirical(
    knowledge_index: KnowledgeIndex,
    program: str,
    mode: str,
    submode: int | None,
    param: str,
    expected: bool,
) -> None:
    """Each curated parameter's ``breakpoint_capable`` matches the Task 5
    empirical probe outcome. The probe ran scalar + envelope invocations
    against real CDP r8; ``brkpnt_files not permitted`` → False, exit-0
    with output produced → True. See docs/phase-2-breakpoint-review.md."""
    entry = knowledge_index.get(program, mode, submode)
    assert entry is not None, (
        f"No curated entry for {program} {mode} sm{submode}"
    )
    spec = entry.parameters[param]
    assert spec.breakpoint_capable is expected, (
        f"{program} {mode} sm{submode}.{param}: knowledge JSON says "
        f"breakpoint_capable={spec.breakpoint_capable}, empirical Task 5 "
        f"probe says {expected}. Either CDP r8's behavior changed (re-run "
        f"the probe in docs/phase-2-breakpoint-review.md §methodology) "
        f"or the JSON was edited without updating the empirical record."
    )


def _flipped_to_true() -> list[tuple[str, str, int | None, str]]:
    return [
        (p, m, s, param)
        for (p, m, s), params in _EXPECTED_BREAKPOINT_CAPABLE.items()
        for param, expected in params.items()
        if expected
    ]


@pytest.mark.parametrize(
    ("program", "mode", "submode", "param"), _flipped_to_true(),
    ids=[f"{p}_{m}_sm{s}_{param}" for (p, m, s, param) in _flipped_to_true()],
)
def test_newly_capable_param_compiles_an_envelope(
    knowledge_index: KnowledgeIndex,
    program: str,
    mode: str,
    submode: int | None,
    param: str,
    tmp_path,
) -> None:
    """For each parameter Task 5 flipped to True, a 2-point relative-time
    envelope compiles cleanly. Source-duration / source-kind aren't
    behaviorally relevant at this layer — the compiler just needs a
    breakpoint-capable spec, a non-empty value, and writeable envelope
    storage."""
    entry = knowledge_index.get(program, mode, submode)
    assert entry is not None
    spec = entry.parameters[param]

    # Choose two values inside the param's declared range.
    lo = spec.min if spec.min is not None else 0.0
    hi = spec.max if spec.max is not None else (lo + 1.0)
    # Make sure hi > lo for the breakpoint to be a real ramp.
    if hi <= lo:
        hi = lo + 1.0

    result = compile_breakpoint_value(
        param_name=param,
        param_spec=spec,
        value=[[0.0, lo], [1.0, hi]],
        source_duration_s=2.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert result.errors == [], (
        f"{program} {mode} sm{submode}.{param}: compile_breakpoint_value "
        f"returned errors despite breakpoint_capable=True: {result.errors}"
    )
    assert result.record is not None
    assert result.compiled_path is not None and result.compiled_path.exists()
