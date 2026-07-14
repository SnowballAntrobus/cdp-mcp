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


async def _run(env, *, program, mode, input_name, params):
    ctx = _FakeCtx()
    return await process_impl(
        ctx, program=program, mode=mode, input=input_name, params=params,
        sessions=env.sessions, knowledge_index=env.knowledge,
        cdp_config_provider=lambda: env.cdp_config,
        latest_tracker=env.latest_tracker, cache_root=env.cache_root,
    )


# ---------------------------------------------------------------------------
# 1. Duration-model consistency: curated model vs actual CDP output.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("program", "mode", "indur", "params", "rel_tol"),
    [
        # extend loop: duration_model "cnt * len / 1000" (len in ms).
        ("extend", "loop", 3.0, {"cnt": 3, "start": 0.0, "len": 500.0}, 0.05),
        ("extend", "loop", 3.0, {"cnt": 5, "start": 0.0, "len": 200.0}, 0.05),
        # modify brassage: duration_model "indur / velocity" (granular splice
        # overhead → a few % slack).
        ("modify", "brassage", 2.0, {"velocity": 0.5}, 0.05),
        ("modify", "brassage", 2.0, {"velocity": 2.0}, 0.05),
        # filter sweeping: duration_model "indur + tail". The -t tail
        # exists only in the binary's banner (not the HTML manual) and
        # omitting it appends a default tail anyway (observed +1.00 s,
        # manual QA 2026-07-14) — so the engine always emits -t
        # explicitly and the model adds it. Default (1.0) and explicit
        # cases both pinned.
        ("filter", "sweeping", 3.0,
         {"acuity": 0.1, "gain": 0.5, "lofrq": 200.0, "hifrq": 4000.0,
          "sweepfrq": 1.0}, 0.05),
        ("filter", "sweeping", 3.0,
         {"acuity": 0.1, "gain": 0.5, "lofrq": 200.0, "hifrq": 4000.0,
          "sweepfrq": 1.0, "tail": 0.5}, 0.05),
        # --- Phase 3 tranche 1 (single-input entries; multi-input rows
        # excluded — this fixture writes one in.wav) ---
        ("modify", "stack", 2.0,
         {"transpos": -12.0, "count": 3, "lean": 1.0, "atk_offset": 0.0, "gain": 1.0, "dur": 1.0},
         0.05),
        ("distort", "divide", 2.0,
         {"divider": 2},
         0.05),
        ("distort", "omit", 2.0,
         {"omit": 2, "group": 5},
         0.05),
        ("extend", "doublets", 2.0,
         {"segdur": 0.25, "repets": 3},
         0.05),
        ("bounce", "bounce", 2.0,
         {"count": 3, "startgap": 0.5, "shorten": 0.8, "endlevel": 0.5, "ewarp": 1.0},
         0.05),
        ("specfnu", "specfnu", 2.0,
         {"narrow": 4.0},
         0.05),
        ("stretch", "spectrum", 2.0,
         {"frq_divide": 1000.0, "maxstretch": 2.0, "exponent": 1.0},
         0.05),
        ("focus", "fold", 2.0,
         {"lofrq": 500.0, "hifrq": 1000.0},
         0.05),
        ("focus", "step", 2.0,
         {"timestep": 0.25},
         0.05),
        ("blur", "spread", 2.0,
         {"pbands": 8, "spread": 1.0},
         0.05),
        ("blur", "suppress", 2.0,
         {"n": 10},
         0.05),
        ("modify", "revecho", 2.0,
         {"delay": 250.0, "mix": 0.5, "feedback": 0.5, "lfomod": 0.3,
          "lfofreq": 1.0, "lfophase": 0.0, "lfodelay": 0.0, "tail": 1.0},
         0.05),
        ("distort", "average", 2.0,
         {"cyclecnt": 5}, 0.05),
        ("distort", "fractal", 2.0,
         {"scaling": 4, "loudness": 1.0}, 0.05),
        ("distort", "interpolate", 2.0,
         {"multiplier": 3}, 0.05),
        ("envel", "dovetail", 2.0,
         {"infadedur": 0.3, "outfadedur": 0.5, "intype": 1, "outtype": 1}, 0.05),
        ("sfedit", "cut", 2.0,
         {"start": 0.5, "end": 1.5}, 0.05),
        ("stretch", "time", 2.0,
         {"timestretch": 2.0}, 0.05),
        ("strange", "glis", 2.0,
         {"pbands": 8, "glisrate": 2.0}, 0.05),
        ("strange", "invert", 2.0,
         {}, 0.05),
        ("hilite", "trace", 2.0,
         {"n": 10}, 0.05),
        ("spec", "magnify", 2.0,
         {"time": 0.5, "dur": 2.0}, 0.05),
        ("focus", "accu", 2.0,
         {"decay": 0.5, "glis": 0.5}, 0.05),
        ("modify", "radical", 2.0, {}, 0.05),
        ("modify", "speed", 2.0, {"semitones": -12.0}, 0.05),
        ("distort", "multiply", 2.0, {"multiplier": 2}, 0.05),
        ("distort", "repeat", 2.0, {"multiplier": 3}, 0.05),
        ("extend", "scramble", 2.0,
         {"minseglen": 0.1, "maxseglen": 0.2, "outdur": 5.0}, 0.05),
        ("filter", "lohi", 2.0,
         {"attenuation": -60.0, "passband": 1000.0, "stopband": 4000.0}, 0.05),
        ("blur", "avrg", 2.0, {"n": 9}, 0.05),
        ("blur", "scatter", 2.0, {"keep": 8}, 0.05),
        ("blur", "drunk", 2.0, {"range": 5, "starttime": 0.5, "duration": 1.5}, 0.05),
        ("focus", "exag", 2.0, {"exaggeration": 2.0}, 0.05),
    ],
)
async def test_duration_model_matches_cdp(
    cdp_env, program, mode, indur, params, rel_tol
):
    """The curated duration_model, run through the real preflight
    evaluator, must predict CDP's actual output duration. Cross-checks
    the structured curated field against the binary — a wrong formula
    fails here rather than silently mispredicting at process() time."""
    env = cdp_env
    _write_noise(env.session.inputs_dir / "in.wav", indur)

    entry = env.knowledge.get(program, mode)
    predicted = _evaluate_duration_model(entry, params, [indur])
    assert predicted is not None

    r = await _run(env, program=program, mode=mode, input_name="in.wav", params=params)
    assert r["status"] == "ok", r["errors"]
    actual = await _measured_duration(env, r["output"])

    assert actual == pytest.approx(predicted, rel=rel_tol), (
        f"{program} {mode} {params}: duration_model predicted {predicted:.3f}s "
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
