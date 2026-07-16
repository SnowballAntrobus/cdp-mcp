"""Phase 2 Task 6.6 — curation-formula regression guards.

Behavioral pins so the quantitative claims in the curated knowledge JSONs
can't silently drift from what CDP actually does. Prompted by the
`filter sweeping` sweepfrq bug (the curated entry copied CDP's own wrong
banner formula `infiledur/2`; the correct value for a single sweep is
`1/(2*infiledur)`).

Two guards, both gated on real CDP via the `real_cdp_path` fixture:

1. Duration-model consistency — for entries whose `duration_model` is a
   computable expression, the curated model (run through the real
   preflight evaluator) must match CDP's actual output duration.
2. `filter sweeping` sweep semantics — the corrected sweepfrq formula
   plus the (verified) phase direction: phase 0 sweeps up, phase 0.5
   sweeps down.
"""

from __future__ import annotations

from types import SimpleNamespace

import librosa
import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import detect_cdp
from cdp_mcp.duration_preflight import _evaluate_duration_model
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.process import process_impl

_SR = 44100


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


@pytest.fixture
def cdp_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    latest_tracker = LatestTracker()
    knowledge = KnowledgeIndex.load()
    session, _ = sessions.set_active("curation_formulas_v1.0")
    return SimpleNamespace(
        sessions=sessions, session=session, latest_tracker=latest_tracker,
        knowledge=knowledge, cdp_config=cdp_config, cache_root=cache_root,
    )


def _write_noise(path, dur_s, seed=0):
    n = int(_SR * dur_s)
    sig = np.random.default_rng(seed).standard_normal(n).astype(np.float32) * 0.2
    sf.write(path, sig, _SR, subtype="FLOAT")


async def _measured_duration(env, output_path_str: str) -> float:
    """Duration of a process output, whatever its domain.

    Time-domain outputs are read directly. Spectral outputs are CDP
    .ana files libsndfile cannot open (the 2026-07-14 macOS QA run
    failed 16 spectral rows exactly here) — synth them to a temp wav
    via the engine's own audition path first. pvoc synth is
    duration-faithful modulo frame padding (phase-1b handoff §5.5;
    re-verified in every tranche transcript), well inside the rows'
    rel_tol.
    """
    from pathlib import Path

    from cdp_mcp.pvoc import synth_for_audition

    out = Path(output_path_str)
    if out.suffix.lower() not in (".ana", ".pvx"):
        return sf.info(str(out)).duration
    wav, _sub = await synth_for_audition(
        out,
        session=env.session,
        cdp_path=env.cdp_config.cdp_path,
        cache_root=env.cache_root,
        cdp_version=env.cdp_config.version,
    )
    return sf.info(str(wav)).duration


async def _run(env, *, program, mode, input_name, params, submode=None):
    ctx = _FakeCtx()
    return await process_impl(
        ctx, program=program, mode=mode, input=input_name, params=params,
        submode=submode,
        sessions=env.sessions, knowledge_index=env.knowledge,
        cdp_config_provider=lambda: env.cdp_config,
        latest_tracker=env.latest_tracker, cache_root=env.cache_root,
    )


# ---------------------------------------------------------------------------
# 1. Duration-model consistency: curated model vs actual CDP output.
# ---------------------------------------------------------------------------


# Aux data files referenced by tranche-11 duration rows, written into the
# session's data/ dir before the row runs (the engine resolves aux_file
# params there — write_data_file's target). Contents from the tranche-11a
# transcript probes: td0.txt is a zero-transposition line held across the
# 6 s outduration (initial time must be 0, times must advance, values
# paired — the verbatim tdata rules); ndec1.txt is the agent's actual
# one-note decorated notedata (line 1 = notional midi pitches, '#1' =
# instrument block, then time/dur/pitch/velocity/param rows).
_AUX_FILES = {
    "td0.txt": "0 0\n6 0\n",
    "ndec1.txt": "60\n#1\n0 1 60 64 0.2\n",
}


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("program", "mode", "submode", "indur", "params", "rel_tol"),
    # Since the (program, mode, submode) re-keying (commit 728b986) every
    # row carries its entry's declared submode — None for submode-less
    # entries, the JSON's value otherwise — so lookups stay exact-triple
    # even on pairs curated in several submodes.
    [
        # extend loop: duration_model "cnt * len / 1000" (len in ms).
        ("extend", "loop", 3, 3.0, {"cnt": 3, "start": 0.0, "len": 500.0}, 0.05),
        ("extend", "loop", 3, 3.0, {"cnt": 5, "start": 0.0, "len": 200.0}, 0.05),
        # modify brassage: duration_model "indur / velocity" (granular splice
        # overhead → a few % slack).
        ("modify", "brassage", 2, 2.0, {"velocity": 0.5}, 0.05),
        ("modify", "brassage", 2, 2.0, {"velocity": 2.0}, 0.05),
        # filter sweeping: duration_model "indur + tail". The -t tail
        # exists only in the binary's banner (not the HTML manual) and
        # omitting it appends a default tail anyway (observed +1.00 s,
        # manual QA 2026-07-14) — so the engine always emits -t
        # explicitly and the model adds it. Default (1.0) and explicit
        # cases both pinned.
        ("filter", "sweeping", 2, 3.0,
         {"acuity": 0.1, "gain": 0.5, "lofrq": 200.0, "hifrq": 4000.0,
          "sweepfrq": 1.0}, 0.05),
        ("filter", "sweeping", 2, 3.0,
         {"acuity": 0.1, "gain": 0.5, "lofrq": 200.0, "hifrq": 4000.0,
          "sweepfrq": 1.0, "tail": 0.5}, 0.05),
        # --- Phase 3 tranche 1 (single-input entries; multi-input rows
        # excluded — this fixture writes one in.wav) ---
        ("scramble", "scramble", 10, 2.0,
         {"seed": 5},
         0.05),
        ("envspeak", "envspeak", 1, 2.0,
         {"wsize": 50.0, "splice": 15.0, "offset": 0, "repet": 2, "rand": 0.0},
         0.05),
        ("distort", "reform", 6, 2.0,
         {},
         0.05),
        ("newdelay", "newdelay", None, 2.0,
         {"midipitch": 60.0, "mix": 1.0, "feedback": 0.7},
         0.05),
        ("quirk", "quirk", 1, 2.0,
         {"powfac": 0.7},
         0.05),
        ("silend", "silend", 1, 2.0,
         {"sildur": 1.0},
         0.05),
        # (grain reverse/rerhythm/reposition + spec grab also excluded:
        # grain ops refuse the fixture's flat noise ('No grains found') and
        # rerhythm/reposition need aux timefiles the shared fixture cannot
        # supply — duration rules pinned in docs/curation/tranche6 transcript.)
        ("modify", "loudness", 1, 2.0,
         {"gain": 0.5},
         0.05),
        ("filter", "bank", 1, 2.0,
         {"q": 50.0, "gain": 1.0, "lof": 220.0, "hif": 4400.0, "tail": 1.0},
         0.05),
        ("grain", "duplicate", None, 2.0,
         {"repeats": 2},
         0.05),
        ("grain", "timewarp", None, 2.0,
         {"ratio": 1.0},
         0.05),
        ("pitch", "tune", 1, 2.0,
         {"frequency": 440.0},
         0.05),
        ("strange", "shift", 4, 2.0,
         {"frqshift": 200.0, "frqlo": 100.0, "frqhi": 8000.0},
         0.05),
        ("clip", "clip", 2, 2.0,
         {"fraction": 0.7},
         0.05),
        ("modify", "stack", None, 2.0,
         {"transpos": -12.0, "count": 3, "lean": 1.0, "atk_offset": 0.0, "gain": 1.0, "dur": 1.0},
         0.05),
        ("distort", "divide", None, 2.0,
         {"divider": 2},
         0.05),
        ("distort", "omit", None, 2.0,
         {"omit": 2, "group": 5},
         0.05),
        ("extend", "doublets", None, 2.0,
         {"segdur": 0.25, "repets": 3},
         0.05),
        ("bounce", "bounce", None, 2.0,
         {"count": 3, "startgap": 0.5, "shorten": 0.8, "endlevel": 0.5, "ewarp": 1.0},
         0.05),
        ("specfnu", "specfnu", 1, 2.0,
         {"narrow": 4.0},
         0.05),
        ("stretch", "spectrum", 1, 2.0,
         {"frq_divide": 1000.0, "maxstretch": 2.0, "exponent": 1.0},
         0.05),
        ("focus", "fold", None, 2.0,
         {"lofrq": 500.0, "hifrq": 1000.0},
         0.05),
        ("focus", "step", None, 2.0,
         {"timestep": 0.25},
         0.05),
        ("blur", "spread", None, 2.0,
         {"pbands": 8, "spread": 1.0},
         0.05),
        ("blur", "suppress", None, 2.0,
         {"n": 10},
         0.05),
        ("modify", "revecho", 2, 2.0,
         {"delay": 250.0, "mix": 0.5, "feedback": 0.5, "lfomod": 0.3,
          "lfofreq": 1.0, "lfophase": 0.0, "lfodelay": 0.0, "tail": 1.0},
         0.05),
        ("distort", "average", None, 2.0,
         {"cyclecnt": 5}, 0.05),
        ("distort", "fractal", None, 2.0,
         {"scaling": 4, "loudness": 1.0}, 0.05),
        ("distort", "interpolate", None, 2.0,
         {"multiplier": 3}, 0.05),
        ("envel", "dovetail", 1, 2.0,
         {"infadedur": 0.3, "outfadedur": 0.5, "intype": 1, "outtype": 1}, 0.05),
        ("sfedit", "cut", 1, 2.0,
         {"start": 0.5, "end": 1.5}, 0.05),
        ("stretch", "time", 1, 2.0,
         {"timestretch": 2.0}, 0.05),
        ("strange", "glis", 1, 2.0,
         {"pbands": 8, "glisrate": 2.0}, 0.05),
        ("strange", "invert", 1, 2.0,
         {}, 0.05),
        ("hilite", "trace", 1, 2.0,
         {"n": 10}, 0.05),
        ("spec", "magnify", None, 2.0,
         {"time": 0.5, "dur": 2.0}, 0.05),
        ("focus", "accu", None, 2.0,
         {"decay": 0.5, "glis": 0.5}, 0.05),
        ("modify", "radical", 1, 2.0, {}, 0.05),
        ("modify", "speed", 2, 2.0, {"semitones": -12.0}, 0.05),
        ("distort", "multiply", None, 2.0, {"multiplier": 2}, 0.05),
        ("distort", "repeat", None, 2.0, {"multiplier": 3}, 0.05),
        ("extend", "scramble", 1, 2.0,
         {"minseglen": 0.1, "maxseglen": 0.2, "outdur": 5.0}, 0.05),
        ("filter", "lohi", 1, 2.0,
         {"attenuation": -60.0, "passband": 1000.0, "stopband": 4000.0}, 0.05),
        ("blur", "avrg", None, 2.0, {"n": 9}, 0.05),
        ("blur", "scatter", None, 2.0, {"keep": 8}, 0.05),
        ("blur", "drunk", None, 2.0, {"range": 5, "starttime": 0.5, "duration": 1.5}, 0.05),
        ("focus", "exag", None, 2.0, {"exaggeration": 2.0}, 0.05),
        # --- Phase 5 wave 3 (tranche 9: sibling submodes of already-curated
        # pairs; rows from docs/curation/tranche9_submodes_findings.json) ---
        ("scramble", "scramble", 9, 2.0,
         {"seed": 5},
         0.05),
        ("filter", "bank", 5, 2.0,
         {"q": 50.0, "gain": 5.0, "lof": 200.0, "hif": 4000.0,
          "filtcnt": 8, "tail": 1.0},
         0.05),
        ("filter", "bank", 6, 2.0,
         {"q": 50.0, "gain": 5.0, "lof": 200.0, "hif": 4000.0,
          "interval": 3.0, "tail": 1.0},
         0.05),
        # (morph bridge 2/3 also excluded: 2-input entries, incompatible
        # with the single-input duration fixture — same as sibling sm1;
        # duration rules min(indur1 - offset, indur2) / min(indur1, indur2)
        # verified via pvoc synth round-trips in the tranche9 findings.)
        ("modify", "radical", 2, 2.0,
         {"repeats": 3, "chunklen": 0.1},
         0.05),
        ("modify", "radical", 5, 2.0,
         {"modfrq": 440.0},
         0.05),
        ("modify", "speed", 5, 2.0,
         {"accel": 2.0, "goaltime": 1.0},
         0.05),
        ("envspeak", "envspeak", 2, 2.0,
         {"wsize": 50.0, "splice": 15.0, "offset": 0},
         0.05),
        # synth wave 2/4: arity-0 generators — indur None means no input
        # fixture is written and the model evaluates with no indurs
        # (set_by dur).
        ("synth", "wave", 2, None,
         {"dur": 2.0, "frq": 440.0, "amp": 0.5},
         0.05),
        ("synth", "wave", 4, None,
         {"dur": 2.0, "frq": 440.0, "amp": 0.5},
         0.05),
        ("specfnu", "specfnu", 2, 2.0,
         {"squeeze": 4.0, "centre": 1},
         0.05),
        # --- Phase 5 wave 4 (tranche 10: ST-covered singles; rows from
        # docs/curation/tranche10{a,b}_st_singles_findings.json) ---
        ("blur", "chorus", 5, 2.0,
         {"aspread": 30.0, "fspread": 2.0},
         0.05),
        ("blur", "noise", None, 2.0,
         {"noise": 0.5},
         0.05),
        ("focus", "focus", None, 2.0,
         {"pbands": 7, "pk": 16, "bw": 0.3},
         0.05),
        ("spec", "cut", None, 2.0,
         {"starttime": 0.5, "endtime": 1.5},
         0.05),
        ("spec", "gain", None, 2.0,
         {"gain": 2.0},
         0.05),
        ("spectstr", "stretch", None, 2.0,
         {"timestretch": 2.0, "dratio": 0.0, "dirand": 0.0},
         0.05),
        ("strange", "waver", 1, 2.0,
         {"vibfrq": 4.0, "stretch": 2.0, "botfrq": 100.0},
         0.05),
        ("extend", "baktobak", None, 2.0,
         {"join_time": 1.0, "splice": 15.0},
         0.05),
        ("housekeep", "extract", 4, 2.0,
         {"shift": -0.02},
         0.05),
        # multiosc 3 / synspline: arity-0 generators (indur None, set_by
        # dur) — synspline pinned at seed 5 (seed 0 is the clock path).
        ("multiosc", "multiosc", 3, None,
         {"dur": 2.0, "frq1": 440.0, "frq2": 100.0, "amp2": 0.2,
          "frq3": 200.0, "amp3": 0.0, "frq4": 300.0, "amp4": 0.0,
          "srate": 44100, "dovesplice": 15.0},
         0.05),
        ("synspline", "synspline", None, None,
         {"srate": 44100, "dur": 2.0, "frq": 220.0, "splinecnt": 4,
          "interpval": 24.0, "seed": 5},
         0.05),
        ("phase", "phase", 1, 2.0,
         {},
         0.05),
        ("repitch", "transpose", 3, 2.0,
         {"transpos": 12.0},
         0.05),
        ("sfedit", "excise", 1, 2.0,
         {"start": 0.5, "end": 1.0},
         0.05),
        # (modify sausage + sfedit join excluded: 2-input entries,
        # incompatible with the single-input fixture — min(indurs)/velocity
        # and indur1 + indur2 - splice/1000 pinned in the tranche10b
        # transcript. phase phase 2 excluded: stereo-only, the shared
        # fixture writes mono; static duration verified in the transcript.)
        # --- Phase 6 tranche 11 (iteration/sequence + event-timing; rows
        # from docs/curation/tranche11{a,b}_*_findings.json). Rows whose
        # params reference _AUX_FILES get that data file written into the
        # session's data/ dir (contents from the 11a transcript probes) —
        # extending the fixture beats excluding the rows (testing-
        # principles §10). Excluded with reasons, pinned in transcripts:
        # extend sequence2 + iterlinef (multi-input / 25-input), stutter +
        # retime 1/6/7/9 (aux datafiles with data-dependent durations —
        # duration_model expressions engage the aux-param preflight skip),
        # retime 3/8/10 (flat noise refused: 'NO SILENCE-GAPS FOUND IN
        # FILE.'), retime 12 + peakfind (data outputs, no audio duration),
        # clicknew (arity-0, duration driven by the clicktimes datafile),
        # housekeep chans 4 (stereo-only). ---
        ("extend", "iterate", 1, 2.0,
         {"outduration": 6.0, "seed": 1},
         0.05),
        ("extend", "iterate", 2, 2.0,
         {"repetitions": 2, "delay": 1.0, "seed": 1},
         0.05),
        ("iterline", "iterline", 1, 2.0,
         {"tdata": "td0.txt", "outduration": 6.0, "delay": 2.0, "seed": 1},
         0.05),
        ("iterline", "iterline", 2, 2.0,
         {"tdata": "td0.txt", "outduration": 6.0, "delay": 2.0, "seed": 1},
         0.05),
        ("shrink", "shrink", 1, 2.0,
         {"shrinkage": 0.7, "gap": 2.0, "contract": 1.0, "dur": 6.0,
          "spl": 10.0},
         0.05),
        ("shrink", "shrink", 4, 2.0,
         {"time": 0.5, "shrinkage": 0.7, "gap": 2.0, "contract": 1.0,
          "dur": 6.0, "spl": 10.0},
         0.05),
        # texture decorated is stochastic (grouped precedent): tol 0.2.
        ("texture", "decorated", 5, 2.0,
         {"notedata": "ndec1.txt", "outdur": 5.0, "skiptime": 0.5,
          "mindur": 0.1, "maxdur": 0.15, "gpsizlo": 2, "gpsizhi": 4,
          "gppaklo": 20.0, "gppakhi": 60.0, "gpranglo": 3.0,
          "gpranghi": 8.0, "seed": 5},
         0.2),
        ("retime", "retime", 4, 2.0,
         {"tempo": 120.0, "minsil": 50.0, "pregain": 1.0},
         0.05),
        ("retime", "retime", 5, 2.0,
         {"factor": 2.0, "minsil": 50.0},
         0.05),
        ("sorter", "sorter", 1, 2.0,
         {"esiz": 0.1},
         0.05),
        ("sorter", "sorter", 5, 2.0,
         {"esiz": 0.1, "seed": 5},
         0.05),
        ("housekeep", "chans", 3, 2.0,
         {"channo": 1},
         0.05),
        ("housekeep", "chans", 5, 2.0,
         {},
         0.05),
    ],
)
async def test_duration_model_matches_cdp(
    cdp_env, program, mode, submode, indur, params, rel_tol
):
    """The curated duration_model, run through the real preflight
    evaluator, must predict CDP's actual output duration. Cross-checks
    the structured curated field against the binary — a wrong formula
    fails here rather than silently mispredicting at process() time."""
    env = cdp_env
    if indur is not None:
        _write_noise(env.session.inputs_dir / "in.wav", indur)
    referenced = [
        v for v in params.values()
        if isinstance(v, str) and v in _AUX_FILES
    ]
    if referenced:
        data_dir = env.session.root / "data"
        data_dir.mkdir(exist_ok=True)
        for name in referenced:
            (data_dir / name).write_text(_AUX_FILES[name])

    entry = env.knowledge.get(program, mode, submode)
    indurs = [indur] if indur is not None else []
    predicted = _evaluate_duration_model(entry, params, indurs)
    assert predicted is not None

    r = await _run(
        env, program=program, mode=mode, submode=submode,
        input_name="in.wav" if indur is not None else None, params=params,
    )
    assert r["status"] == "ok", r["errors"]
    actual = await _measured_duration(env, r["output"])

    assert actual == pytest.approx(predicted, rel=rel_tol), (
        f"{program} {mode} sm{submode} {params}: "
        f"duration_model predicted {predicted:.3f}s "
        f"but CDP produced {actual:.3f}s (rel_tol={rel_tol}). The curated "
        f"duration_model may have drifted from CDP behavior."
    )


# ---------------------------------------------------------------------------
# 2. filter sweeping: corrected sweepfrq + phase direction.
# ---------------------------------------------------------------------------


def _centroid_rises(wav_path) -> bool:
    """True if the spectral centroid's late third sits above its early
    third — a single rising sweep. Edge frames trimmed to avoid the
    filter ring-out / startup transient skewing the medians."""
    y, _ = librosa.load(str(wav_path), sr=_SR)
    cen = librosa.feature.spectral_centroid(y=y, sr=_SR, hop_length=4096)[0]
    cen = cen[5:-5]
    third = len(cen) // 3
    early = float(np.median(cen[:third]))
    late = float(np.median(cen[-third:]))
    return late > early


@pytest.mark.timeout(60)
@pytest.mark.parametrize("phase, expect_rising", [(0.0, True), (0.5, False)])
async def test_filter_sweep_direction(cdp_env, phase, expect_rising):
    """sweepfrq = 1/(2*dur) gives a single pass; phase 0 sweeps the focus
    up (200→4000), phase 0.5 sweeps it down. Pins the corrected sweepfrq
    formula and the verified phase semantics against CDP."""
    env = cdp_env
    dur = 6.0
    _write_noise(env.session.inputs_dir / "in.wav", dur, seed=1)
    sweepfrq = 1.0 / (2.0 * dur)

    r = await _run(
        env, program="filter", mode="sweeping", input_name="in.wav",
        params={
            "acuity": 0.05, "gain": 0.44, "lofrq": 200.0, "hifrq": 4000.0,
            "sweepfrq": sweepfrq, "phase": phase,
        },
    )
    assert r["status"] == "ok", r["errors"]
    rising = _centroid_rises(r["output"])
    assert rising is expect_rising, (
        f"phase={phase}: expected {'rising' if expect_rising else 'falling'} "
        f"sweep but spectral centroid {'rose' if rising else 'fell'}. "
        f"sweepfrq={sweepfrq:.4f} should produce a single "
        f"{'up' if expect_rising else 'down'}-sweep."
    )
