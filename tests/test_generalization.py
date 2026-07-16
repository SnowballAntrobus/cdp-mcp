"""Phase 5 generalization matrix — four material classes through curated chains.

The 107-entry curated knowledge base was probed almost entirely on synthetic
noise/tone fixtures. This module verifies the acceptance machinery (process
chaining, auto-PVOC boundary insertion, duration models, lineage) generalizes
to four musically distinct material classes, each represented by a
deterministic (seeded) numpy-synthesized proxy — no wav fixtures live in the
repo; all audio is generated in-fixture. Real recorded material + listening
is the human half of Phase 5; this is the machine half.

The four proxies and why they're built the way they are:

1. **clarinet-ish** (``_synth_clarinet``): sustained D4 (147 Hz) with an
   odd-harmonic-dominant spectrum (clarinet's closed-pipe signature), ~5 Hz
   vibrato, soft 150 ms attack, 2.5 s. Stresses spectral *pitch* ops —
   repitch/waver need a coherent harmonic spectrum to act on, which flat
   noise never gave them.
2. **field-recording proxy** (``_synth_field``): broadband one-pole-filtered
   noise bed with a slow (0.23 Hz) amplitude drift, three sparse decaying
   sine-burst transients, and a faint 50 Hz hum, 3 s. Stresses filters and
   spectral blur on non-stationary broadband material — and turns out to be
   the interesting edge case for amplitude-gated grain detection (see
   ``test_material_sensitivity``).
3. **synth one-shot** (``_synth_oneshot``): percussive hit — noise-burst
   attack, exponentially decaying body whose pitch sweeps 900→70 Hz, 0.7 s.
   Stresses extend/edit ops built for short gestures (bounce, loop) and
   spectral timestretch at the short-duration end where analysis-window
   padding is proportionally largest.
4. **vocal-phrase proxy** (``_synth_vocal``): glottal-ish pulse train with a
   falling 150→115 Hz pitch contour, run through three fixed formant
   resonators (650/1100/2500 Hz two-pole sections), shaped by a 4-syllable
   amplitude envelope with real inter-syllable silence. Stresses
   onset/syllable-sensitive ops (grain reverse, envspeak) that refuse
   unarticulated material outright.

Each chain runs 3–5 curated ops spanning spectral + time-domain + an
extend/edit family, chained via ``input="latest"``, with at least one
.wav → spectral crossing (auto-PVOC anal) and one .ana → time-domain
crossing (auto-PVOC synth) per chain. Per step: status ok, and measured
output duration vs the curated ``duration_model`` run through the real
preflight evaluator (the ``test_curation_formulas.py`` approach). Structural
lineage checks (node_index / lineage.json well-formedness) at least once per
chain. Byte-determinism is deliberately NOT asserted — brassage and scramble
place grains stochastically (scramble is pinned by its seed param, brassage
has none).

``test_material_sensitivity`` pins the negative half of the matrix — which
curated claims did NOT generalize (grain gating on drifting beds, the
"steady tones are refused" envspeak claim). Findings are written up in
``docs/generalization-matrix.md``.

Gated on real CDP via the ``real_cdp_path`` fixture: hermetic runs (no
``$CDP_PATH``) skip cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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


# ---------------------------------------------------------------------------
# Proxy synthesis. All deterministic (fixed seeds), mono, 44.1 kHz, float32.
# ---------------------------------------------------------------------------


def _synth_clarinet(dur: float = 2.5, f0: float = 147.0, seed: int = 101) -> np.ndarray:
    """Sustained pitched tone, odd-harmonic-dominant, soft attack, 5 Hz vibrato."""
    t = np.arange(int(_SR * dur)) / _SR
    vib = 1.0 + 0.004 * np.sin(2 * np.pi * 5.0 * t)
    phase = 2 * np.pi * f0 * np.cumsum(vib) / _SR
    sig = np.zeros_like(t)
    # Odd harmonics dominate (closed-pipe); trace even content for realism.
    for k, amp in ((1, 1.0), (3, 0.75), (5, 0.5), (7, 0.3), (9, 0.18), (2, 0.06), (4, 0.04)):
        sig += amp / k * np.sin(k * phase)
    env = np.minimum(1.0, t / 0.15) * np.minimum(1.0, (dur - t) / 0.3)
    breath = np.random.default_rng(seed).standard_normal(len(t)) * 0.004
    out = (sig / np.max(np.abs(sig)) * 0.5 + breath) * env
    return out.astype(np.float32)


def _synth_field(dur: float = 3.0, seed: int = 202) -> np.ndarray:
    """Broadband textured bed + slow amplitude drift + sparse transients + 50 Hz hum."""
    rng = np.random.default_rng(seed)
    n = int(_SR * dur)
    t = np.arange(n) / _SR
    noise = rng.standard_normal(n)
    # Gentle one-pole lowpass — "distant traffic" coloration.
    bed = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc += 0.15 * (noise[i] - acc)
        bed[i] = acc
    bed /= np.max(np.abs(bed))
    drift = 0.55 + 0.35 * np.sin(2 * np.pi * 0.23 * t + 1.0)
    sig = bed * drift * 0.25
    for t0, f, amp in ((0.7, 1800.0, 0.5), (1.6, 900.0, 0.45), (2.35, 2600.0, 0.4)):
        i0 = int(t0 * _SR)
        m = int(0.06 * _SR)
        tt = np.arange(m) / _SR
        sig[i0 : i0 + m] += np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.012) * amp
    out = sig + 0.02 * np.sin(2 * np.pi * 50.0 * t)
    return (out / np.max(np.abs(out)) * 0.6).astype(np.float32)


def _synth_oneshot(dur: float = 0.7, seed: int = 303) -> np.ndarray:
    """Percussive hit: bright noise attack, exponential decay, 900→70 Hz sweep."""
    rng = np.random.default_rng(seed)
    n = int(_SR * dur)
    t = np.arange(n) / _SR
    f_inst = 70.0 + (900.0 - 70.0) * np.exp(-t / 0.06)
    body = np.sin(2 * np.pi * np.cumsum(f_inst) / _SR) * np.exp(-t / 0.12)
    click = rng.standard_normal(n) * np.exp(-t / 0.008) * 0.7
    out = body + click
    return (out / np.max(np.abs(out)) * 0.8).astype(np.float32)


def _synth_vocal(dur: float = 2.5) -> np.ndarray:
    """Pulse train with falling pitch contour through 3 formant resonators,
    shaped into 4 'syllables' with genuine inter-syllable silence (the
    below-gate holes grain/envspeak detection needs)."""
    n = int(_SR * dur)
    t = np.arange(n) / _SR
    f0 = 150.0 - 35.0 * (t / dur) + 4.0 * np.sin(2 * np.pi * 4.5 * t)
    phase = np.cumsum(f0) / _SR
    pulses = ((phase % 1.0) < (f0 / _SR) * 4).astype(np.float64)

    def resonate(x: np.ndarray, freq: float, bw: float) -> np.ndarray:
        r = np.exp(-np.pi * bw / _SR)
        th = 2 * np.pi * freq / _SR
        b1, b2 = 2 * r * np.cos(th), -r * r
        y = np.empty_like(x)
        y1 = y2 = 0.0
        for i in range(len(x)):
            y0 = x[i] + b1 * y1 + b2 * y2
            y[i] = y0
            y2, y1 = y1, y0
        return y

    voiced = (
        resonate(pulses, 650.0, 80.0)
        + resonate(pulses, 1100.0, 90.0) * 0.7
        + resonate(pulses, 2500.0, 120.0) * 0.35
    )
    voiced /= np.max(np.abs(voiced))
    env = np.zeros(n)
    for start, length in ((0.05, 0.50), (0.70, 0.45), (1.30, 0.55), (2.00, 0.42)):
        i0, i1 = int(start * _SR), int((start + length) * _SR)
        env[i0:i1] = np.sin(np.pi * np.linspace(0, 1, i1 - i0)) ** 0.6
    return (voiced * env * 0.8).astype(np.float32)


_PROXIES = {
    "clarinet.wav": _synth_clarinet,
    "field.wav": _synth_field,
    "oneshot.wav": _synth_oneshot,
    "vocal.wav": _synth_vocal,
}


# ---------------------------------------------------------------------------
# Environment + chain runner.
# ---------------------------------------------------------------------------


@pytest.fixture
def gen_env(tmp_path, real_cdp_path):
    """Real-CDP session with all four proxies written to inputs/."""
    if real_cdp_path is None:
        pytest.skip(
            "Real CDP not configured. Set $CDP_PATH to a directory "
            "containing blur, pvoc, modify, and extend binaries."
        )
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    knowledge = KnowledgeIndex.load()
    session, _ = sessions.set_active("generalization_v1.0")
    for name, synth in _PROXIES.items():
        sf.write(session.inputs_dir / name, synth(), _SR, subtype="FLOAT")
    return SimpleNamespace(
        sessions=sessions,
        session=session,
        latest_tracker=LatestTracker(),
        knowledge=knowledge,
        cdp_config=cdp_config,
        cache_root=cache_root,
    )


async def _measured_duration(env, output_path_str: str) -> float:
    """Duration of a process output whatever its domain — .ana measured via
    the engine's own audition synth (libsndfile cannot open .ana; see
    test_curation_formulas._measured_duration and testing-principles §10)."""
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


class _Chain:
    """Runs curated steps chained via input='latest', checking the curated
    duration_model against the measured output at every step."""

    def __init__(self, env, input_filename: str):
        self.env = env
        self.input = input_filename
        self.dur = sf.info(str(env.session.inputs_dir / input_filename)).duration
        self.last_result = None

    async def step(
        self,
        program: str,
        mode: str,
        submode,
        params: dict,
        *,
        rel: float = 0.05,
        duration_range: tuple[float, float] | None = None,
    ):
        r = await process_impl(
            _FakeCtx(),
            program=program,
            mode=mode,
            submode=submode,
            input=self.input,
            params=params,
            sessions=self.env.sessions,
            knowledge_index=self.env.knowledge,
            cdp_config_provider=lambda: self.env.cdp_config,
            latest_tracker=self.env.latest_tracker,
            cache_root=self.env.cache_root,
        )
        assert r["status"] == "ok", (
            f"{program} {mode} sm{submode} on {self.input!r} failed: "
            f"{r.get('errors')} / stdout tail: {str(r.get('stdout'))[-300:]}"
        )
        measured = await _measured_duration(self.env, r["output"])
        if duration_range is not None:
            lo, hi = duration_range
            assert lo <= measured <= hi, (
                f"{program} {mode} sm{submode}: measured {measured:.3f}s "
                f"outside documented range [{lo:.3f}, {hi:.3f}]"
            )
        else:
            entry = self.env.knowledge.get(program, mode, submode)
            predicted = _evaluate_duration_model(entry, params, [self.dur])
            assert predicted is not None
            assert measured == pytest.approx(predicted, rel=rel), (
                f"{program} {mode} sm{submode} {params}: duration_model "
                f"predicted {predicted:.3f}s, CDP produced {measured:.3f}s "
                f"(rel_tol={rel}) — the model may not generalize to this "
                f"material class."
            )
        self.dur = measured
        self.input = "latest"
        self.last_result = r
        return r

    def assert_final_nonsilent(self, peak_floor: float = 0.01) -> None:
        """Probe hygiene: exit 0 isn't enough — the chain must end audible."""
        audio, _sr = sf.read(self.last_result["output"])
        assert float(np.max(np.abs(audio))) > peak_floor, (
            f"Final chain output is silent (peak <= {peak_floor})."
        )


def _assert_autopvoc_graph(env, result, expected_op_fragment: str) -> None:
    """Structural lineage check on an auto-PVOC boundary graph: n1 is the
    inserted pvoc node, n2 the curated op sourcing n1, and the graph trio
    (graph.json / node_index.json / lineage.json) is well-formed."""
    graph_dir = env.session.graphs_dir / result["context"]["active_graph"]
    for required in ("graph.json", "node_index.json", "lineage.json"):
        assert (graph_dir / required).is_file(), f"missing {required} in {graph_dir}"
    node_index = json.loads((graph_dir / "node_index.json").read_text())
    assert set(node_index.keys()) == {"n1", "n2"}, node_index
    assert "pvoc" in node_index["n1"]
    assert expected_op_fragment in node_index["n2"]
    lineage = json.loads((graph_dir / "lineage.json").read_text())
    op_inputs = lineage["nodes"]["n2"]["inputs"]
    assert any(inp.get("source_node") == "n1" for inp in op_inputs), op_inputs


# ---------------------------------------------------------------------------
# The four chains.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
async def test_clarinet_chain(gen_env):
    """Pitched sustained material through spectral-pitch ops.

    repitch transpose 3 (+12 st, wav→.ana auto-PVOC) → strange waver
    (harmonicity vibrato, .ana→.ana) → modify speed 2 (-12 st varispeed,
    .ana→time crossing, doubles duration) → envel dovetail (edit family).
    Chosen because these ops act on a coherent harmonic spectrum — the
    curation-era noise fixtures never gave the pitch ops real pitch.
    """
    chain = _Chain(gen_env, "clarinet.wav")

    r1 = await chain.step("repitch", "transpose", 3, {"transpos": 12.0})
    assert r1["output"].endswith(".ana")
    _assert_autopvoc_graph(gen_env, r1, "transpose")

    await chain.step("strange", "waver", 1, {"vibfrq": 4.0, "stretch": 2.0, "botfrq": 100.0})

    r3 = await chain.step("modify", "speed", 2, {"semitones": -12.0})
    assert r3["output"].endswith(".wav")

    await chain.step(
        "envel",
        "dovetail",
        1,
        {"infadedur": 0.1, "outfadedur": 0.5, "intype": 1, "outtype": 1},
    )
    chain.assert_final_nonsilent()


@pytest.mark.timeout(120)
async def test_field_chain(gen_env):
    """Broadband non-stationary bed through filter + spectral-blur ops.

    filter sweeping (one full up-down sweep across the bed) → blur blur
    (wav→.ana auto-PVOC; time-averaging suits stationary-ish texture) →
    modify brassage velocity 0.5 (.ana→time crossing, granular half-speed)
    → extend scramble (edit family, seeded — the -s param pins the
    otherwise clock-seeded chunk sequence).
    """
    chain = _Chain(gen_env, "field.wav")

    await chain.step(
        "filter",
        "sweeping",
        2,
        {
            "acuity": 0.1,
            "gain": 0.5,
            "lofrq": 150.0,
            "hifrq": 5000.0,
            "sweepfrq": 1.0 / 6.0,  # one full cycle over the 3 s input
            "tail": 0.5,
        },
    )

    r2 = await chain.step("blur", "blur", None, {"blurring": 10})
    _assert_autopvoc_graph(gen_env, r2, "blur")

    # Brassage grain placement is unseeded-stochastic: duration is stable
    # (±0.1% observed run-to-run) but bytes are not — no determinism assert.
    await chain.step("modify", "brassage", 2, {"velocity": 0.5})

    # set_by outdur, but the documented overrun is "up to about one chunk":
    # assert the documented range rather than a symmetric rel_tol.
    outdur, maxseglen = 4.0, 0.3
    await chain.step(
        "extend",
        "scramble",
        1,
        {"minseglen": 0.1, "maxseglen": maxseglen, "outdur": outdur, "seed": 7},
        duration_range=(outdur - 0.01, outdur + maxseglen + 0.05),
    )
    chain.assert_final_nonsilent()


@pytest.mark.timeout(120)
async def test_oneshot_chain(gen_env):
    """Short percussive gesture through extend/edit + spectral-time ops.

    bounce (accelerating repeats — built for exactly this material) →
    stretch time 2.5x (wav→.ana auto-PVOC; short input = worst-case
    analysis padding, observed +2%) → extend loop (.ana→time crossing) →
    sfedit cut (edit family, exact duration).
    """
    chain = _Chain(gen_env, "oneshot.wav")

    await chain.step(
        "bounce",
        "bounce",
        None,
        {"count": 5, "startgap": 0.35, "shorten": 0.75, "endlevel": 0.15, "ewarp": 1.0},
    )

    r2 = await chain.step("stretch", "time", 1, {"timestretch": 2.5})
    _assert_autopvoc_graph(gen_env, r2, "time")

    r3 = await chain.step("extend", "loop", 3, {"cnt": 4, "start": 0.0, "len": 400.0})
    # .ana → time-domain crossing: auto-inserted pvoc synth precedes loop.
    node_index = json.loads(
        (
            gen_env.session.graphs_dir
            / r3["context"]["active_graph"]
            / "node_index.json"
        ).read_text()
    )
    assert "pvoc" in node_index["n1"] and "loop" in node_index["n2"], node_index

    await chain.step("sfedit", "cut", 1, {"start": 0.2, "end": 1.2})
    chain.assert_final_nonsilent()


@pytest.mark.timeout(120)
async def test_vocal_chain(gen_env):
    """Syllabic articulated material through onset/formant-sensitive ops.

    grain reverse (amplitude-gated syllable reversal — refuses anything
    unarticulated, so this proxy is its real test) → specfnu narrow
    (formant-aware spectral op, wav→.ana auto-PVOC — designed for vocal
    material) → modify loudness (.ana→time crossing) → envspeak repeat
    (syllable stutter, duration exactly indur * repet at rand=0).
    """
    chain = _Chain(gen_env, "vocal.wav")

    # Static duration model, but grain gating discards below-gate material:
    # observed -3.4% on this 4-syllable proxy (entry documents -1.3% on
    # sparse trains). rel widened to 0.08 to pin "runs and stays close",
    # not the exact splice arithmetic.
    await chain.step("grain", "reverse", None, {}, rel=0.08)

    r2 = await chain.step("specfnu", "specfnu", 1, {"narrow": 4.0})
    _assert_autopvoc_graph(gen_env, r2, "specfnu")

    await chain.step("modify", "loudness", 1, {"gain": 0.8})

    await chain.step(
        "envspeak",
        "envspeak",
        1,
        {"wsize": 50.0, "splice": 15.0, "offset": 0, "repet": 2, "rand": 0.0},
    )
    chain.assert_final_nonsilent()


# ---------------------------------------------------------------------------
# The negative half of the matrix: what did NOT generalize.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
async def test_material_sensitivity(gen_env):
    """Pins the material-class boundaries discovered while building the matrix.

    1. grain reverse refuses the sustained clarinet AND the single-grain
       one-shot ('No grains found', exit 255) — the curated refusal claim
       generalizes from noise/tones to real instrument-like sustains.
    2. grain reverse does NOT refuse the field bed: the slow amplitude
       drift dips below the 0.3 gate, so the continuous bed is segmented
       into pseudo-grains and the below-gate material is silently
       DISCARDED — output ~23% shorter than the static duration model
       predicts. The model does not generalize to weakly-articulated beds.
    3. envspeak does NOT refuse the clarinet despite the curated 'steady
       tones are refused' claim: the swell envelope counts as one
       'syllable', giving whole-file repetition at exactly indur * repet.
    """
    env = gen_env
    deps = {
        "sessions": env.sessions,
        "knowledge_index": env.knowledge,
        "cdp_config_provider": lambda: env.cdp_config,
        "latest_tracker": env.latest_tracker,
        "cache_root": env.cache_root,
    }

    # 1. Refusals on unarticulated / single-event material.
    for infile in ("clarinet.wav", "oneshot.wav"):
        r = await process_impl(
            _FakeCtx(), program="grain", mode="reverse", submode=None,
            input=infile, params={}, **deps,
        )
        assert r["status"] != "ok", f"grain reverse unexpectedly accepted {infile}"
        assert "No grains found" in str(r.get("stdout", "")), (
            f"expected CDP's 'No grains found' refusal on {infile}; "
            f"stdout: {str(r.get('stdout'))[-200:]}"
        )

    # 2. Acceptance-with-truncation on the drifting bed.
    r = await process_impl(
        _FakeCtx(), program="grain", mode="reverse", submode=None,
        input="field.wav", params={}, **deps,
    )
    assert r["status"] == "ok", f"grain reverse refused the field bed: {r.get('errors')}"
    indur = sf.info(str(env.session.inputs_dir / "field.wav")).duration
    measured = await _measured_duration(env, r["output"])
    assert measured < 0.85 * indur, (
        f"Expected grain reverse to discard below-gate bed material "
        f"(observed ~{0.77:.2f}x indur when pinned); got {measured:.3f}s "
        f"from {indur:.3f}s — the truncation finding may no longer hold."
    )

    # 3. envspeak accepts the swelled sustain (one 'syllable' = whole file).
    r = await process_impl(
        _FakeCtx(), program="envspeak", mode="envspeak", submode=1,
        input="clarinet.wav",
        params={"wsize": 50.0, "splice": 15.0, "offset": 0, "repet": 2, "rand": 0.0},
        **deps,
    )
    assert r["status"] == "ok", f"envspeak refused the clarinet swell: {r.get('errors')}"
    clarinet_dur = sf.info(str(env.session.inputs_dir / "clarinet.wav")).duration
    measured = await _measured_duration(env, r["output"])
    assert measured == pytest.approx(clarinet_dur * 2, rel=0.05), (
        f"envspeak on the swell should double the file (one syllable x2); "
        f"got {measured:.3f}s from {clarinet_dur:.3f}s"
    )
