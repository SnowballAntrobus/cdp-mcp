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
_EXPECTED_BREAKPOINT_CAPABLE: dict[tuple[str, str], dict[str, bool]] = {
    # --- Phase 5 tranches 5-6 (sandbox-CDP probed; see docs/curation/) ---
    ("submix", "interleave"): {
        # no numeric parameters
    },
    ("envel", "impose"): {
        "wsize": False,
    },
    ("envel", "replace"): {
        "wsize": False,
    },
    ("formants", "vocode"): {
        "fbands": False,
        "lof": False,
        "hif": False,
        "gain": False,
    },
    ("spec", "grab"): {
        "time": False,
    },
    ("modify", "loudness"): {
        "gain": True,
    },
    ("filter", "bank"): {
        "q": True,
        "gain": False,
        "lof": False,
        "hif": False,
        "tail": False,
        "scat": False,
        "double": False,
    },
    ("grain", "reverse"): {
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "duplicate"): {
        "repeats": True,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "timewarp"): {
        "ratio": True,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "rerhythm"): {
        "multfile": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "reposition"): {
        "timefile": False,
        "offset": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("pitch", "tune"): {
        "frequency": False,
        "focus": True,
        "clarity": True,
        "trace": True,
        "bcut": True,
    },
    ("combine", "interleave"): {
        "leafsize": False,
    },
    ("combine", "max"): {
        # no numeric parameters
    },
    ("strange", "shift"): {
        "frqshift": True,
        "frqlo": True,
        "frqhi": True,
        "log_interp": False,
    },
    ("distort", "interact"): {
        # no numeric parameters
    },
    ("clip", "clip"): {
        "fraction": False,
    },
    # --- Phase 3 tranche 3 (sandbox-CDP probed; see docs/curation/) ---
    ("texture", "simple"): {
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
    ("modify", "stack"): {
        "transpos": False,
        "count": False,
        "lean": False,
        "atk_offset": False,
        "gain": False,
        "dur": False,
        "normalise": False,
    },
    ("distort", "divide"): {
        "divider": True,
        "interpolate": False,
    },
    ("distort", "omit"): {
        "omit": True,
        "group": False,
    },
    ("extend", "doublets"): {
        "segdur": True,
        "repets": False,
        "sync": False,
    },
    ("bounce", "bounce"): {
        "count": False,
        "startgap": False,
        "shorten": False,
        "endlevel": False,
        "ewarp": False,
        "shrink": False,
        "cut_overlap": False,
        "trim_start": False,
    },
    ("specfnu", "specfnu"): {
        "narrow": True,
        "gain": False,
    },
    ("stretch", "spectrum"): {
        "frq_divide": False,
        "maxstretch": False,
        "exponent": False,
        "depth": True,
    },
    ("focus", "fold"): {
        "lofrq": True,
        "hifrq": True,
    },
    ("focus", "step"): {
        "timestep": False,
    },
    ("blur", "spread"): {
        "fchans": False,
        "pbands": False,
        "spread": True,
    },
    ("blur", "suppress"): {
        "n": True,
    },
    # --- Phase 3 tranche 2 (sandbox-CDP probed; see docs/curation/) ---
    ("modify", "revecho"): {
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
    ("distort", "average"): {
        "cyclecnt": True,
        "maxwavelen": False,
        "skipcycles": False,
    },
    ("distort", "fractal"): {
        "scaling": True,
        "loudness": True,
        "pre_attenuation": False,
    },
    ("distort", "interpolate"): {
        "multiplier": True,
        "skipcycles": False,
    },
    ("envel", "dovetail"): {
        "infadedur": False,
        "outfadedur": False,
        "intype": False,
        "outtype": False,
        "times": False,
    },
    ("sfedit", "cut"): {
        "start": False,
        "end": False,
        "splice": False,
    },
    ("stretch", "time"): {
        "timestretch": True,
    },
    ("strange", "glis"): {
        "fchans": False,
        "pbands": False,
        "glisrate": True,
        "topfrq": False,
    },
    ("strange", "invert"): {
        # no numeric parameters
    },
    ("hilite", "trace"): {
        "n": True,
    },
    ("spec", "magnify"): {
        "time": False,
        "dur": False,
    },
    ("focus", "accu"): {
        "decay": True,
        "glis": True,
    },
    # --- Phase 3 tranche 1 (sandbox-CDP probed; see docs/curation/) ---
    ("modify", "radical"): {
        # no numeric parameters
    },
    ("modify", "speed"): {
        "semitones": True,
    },
    ("distort", "multiply"): {
        "multiplier": True,
    },
    ("distort", "repeat"): {
        "multiplier": True,
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("extend", "zigzag"): {
        "start": False,
        "end": False,
        "dur": False,
        "minzig": False,
        "splicelen": False,
        "maxzig": False,
        "seed": False,
    },
    ("extend", "scramble"): {
        "minseglen": False,
        "maxseglen": False,
        "outdur": False,
        "splen": False,
        "seed": False,
    },
    ("filter", "lohi"): {
        "attenuation": False,
        "passband": False,
        "stopband": False,
        "tail": False,
        "prescale": False,
    },
    ("blur", "avrg"): {
        "n": True,
    },
    ("blur", "scatter"): {
        "keep": True,
        "blocksize": True,
    },
    ("blur", "drunk"): {
        "range": False,
        "starttime": False,
        "duration": False,
    },
    ("focus", "exag"): {
        "exaggeration": True,
    },
    ("combine", "diff"): {
        "crossover": True,
        "subzero": False,
    },
    ("morph", "glide"): {
        "duration": False,
    },
    ("blur", "blur"): {
        "blurring": True,
    },
    ("extend", "loop"): {
        "cnt": False, "start": False, "len": False,
        "step": False, "splen": False, "scat": False,
    },
    ("filter", "sweeping"): {
        "acuity": True, "gain": False,
        "lofrq": True, "hifrq": True, "sweepfrq": True,
        "tail": False, "phase": False,
    },
    ("modify", "brassage"): {
        "velocity": True,
    },
    ("morph", "morph"): {
        "as": False, "ae": False, "fs": False, "fe": False,
        "expa": False, "expf": False, "stagger": False,
    },
}


def _matrix_cases() -> list[tuple[str, str, str, bool]]:
    """Flatten the expectation table to one (program, mode, param, expected)
    case per row for pytest's parametrize."""
    return [
        (program, mode, param, expected)
        for (program, mode), params in _EXPECTED_BREAKPOINT_CAPABLE.items()
        for param, expected in params.items()
    ]


@pytest.fixture(scope="module")
def knowledge_index() -> KnowledgeIndex:
    return KnowledgeIndex.load()


@pytest.mark.parametrize(
    ("program", "mode", "param", "expected"), _matrix_cases(),
    ids=[
        f"{p}_{m}_{param}_{expected}"
        for (p, m, param, expected) in _matrix_cases()
    ],
)
def test_breakpoint_capable_matches_empirical(
    knowledge_index: KnowledgeIndex,
    program: str,
    mode: str,
    param: str,
    expected: bool,
) -> None:
    """Each curated parameter's ``breakpoint_capable`` matches the Task 5
    empirical probe outcome. The probe ran scalar + envelope invocations
    against real CDP r8; ``brkpnt_files not permitted`` → False, exit-0
    with output produced → True. See docs/phase-2-breakpoint-review.md."""
    entry = knowledge_index.get(program, mode)
    assert entry is not None, f"No curated entry for {program} {mode}"
    spec = entry.parameters[param]
    assert spec.breakpoint_capable is expected, (
        f"{program} {mode}.{param}: knowledge JSON says "
        f"breakpoint_capable={spec.breakpoint_capable}, empirical Task 5 "
        f"probe says {expected}. Either CDP r8's behavior changed (re-run "
        f"the probe in docs/phase-2-breakpoint-review.md §methodology) "
        f"or the JSON was edited without updating the empirical record."
    )


def _flipped_to_true() -> list[tuple[str, str, str]]:
    return [
        (p, m, param)
        for (p, m), params in _EXPECTED_BREAKPOINT_CAPABLE.items()
        for param, expected in params.items()
        if expected
    ]


@pytest.mark.parametrize(
    ("program", "mode", "param"), _flipped_to_true(),
    ids=[f"{p}_{m}_{param}" for (p, m, param) in _flipped_to_true()],
)
def test_newly_capable_param_compiles_an_envelope(
    knowledge_index: KnowledgeIndex,
    program: str,
    mode: str,
    param: str,
    tmp_path,
) -> None:
    """For each parameter Task 5 flipped to True, a 2-point relative-time
    envelope compiles cleanly. Source-duration / source-kind aren't
    behaviorally relevant at this layer — the compiler just needs a
    breakpoint-capable spec, a non-empty value, and writeable envelope
    storage."""
    entry = knowledge_index.get(program, mode)
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
        f"{program} {mode}.{param}: compile_breakpoint_value returned "
        f"errors despite breakpoint_capable=True: {result.errors}"
    )
    assert result.record is not None
    assert result.compiled_path is not None and result.compiled_path.exists()
