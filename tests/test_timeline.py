"""Tests for timeline() — deterministic multi-source event placement.

Hermetic coverage (fake submix binary): event-spec validation (bad
refs, negative at, empty events, unknown keys, bad level/pan), pan on a
stereo source, mixed sample rates, exact mixfile content pinning for a
3-event case, the duration pre-flight (rule max(at+dur) − min(at) and
the cap), and the three headroom modes against a fake getlevel report
(auto applies the factor as -g, clean mixes apply nothing, fail returns
the structured error carrying the factor, off skips the stage and
warns).

Real-CDP-gated coverage (fixture pattern from test_pre_output_aux):
3-event render duration within tolerance, headroom auto on a
deliberately hot mix (clean render — matches the ideal scaled sum, no
wrap), headroom off on the same mix WRAPS (negative-going samples where
the ideal sum is in the wrap band), pan renders stereo, and
graph/lineage well-formedness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig, detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import timeline as timeline_module
from cdp_mcp.tools.timeline import timeline_impl

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


# ---------------------------------------------------------------------------
# Hermetic harness
# ---------------------------------------------------------------------------


def _write_submix_wrapper(
    path: Path,
    factor: str = "0.336683",
    peak: str = "2.970153",
    getlevel_exit: int = 0,
) -> None:
    """Fake submix: 'getlevel' writes a pinned report shaped like the
    tranche-12 empirics to the LAST .txt argv element (the output — the
    mixfile precedes it); 'mix' writes a non-silent wav at the last
    .wav argv element."""
    path.write_text(
        f"""#!/bin/sh
MODE="$1"
if [ "$MODE" = "getlevel" ]; then
    if [ {getlevel_exit} -ne 0 ]; then exit {getlevel_exit}; fi
    OUT=""
    for arg in "$@"; do
        case "$arg" in *.txt) OUT="$arg" ;; esac
    done
    printf 'Clip at time 0.000000 secs : sample 0 : For 100 samples\\n\\n' > "$OUT"
    printf 'MAX SAMPLE ENCOUNTERED : {peak} at 0.004104 secs\\n' >> "$OUT"
    printf 'NORMALISATION REQUIRED : {factor}   OR  -9.4556dB\\n' >> "$OUT"
    exit 0
fi
OUT=""
for arg in "$@"; do
    case "$arg" in *.wav) OUT="$arg" ;; esac
done
exec "{_FAKE_SUBPROCESS}" --write-wav "$OUT"
"""
    )
    path.chmod(0o755)


@pytest.fixture
def harness(tmp_path):
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    _write_submix_wrapper(cdp / "submix")

    mcp = FastMCP("test-cdp-timeline")
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(
        cdp_path=cdp, version="fake", detected_binaries=["submix"],
    )
    sessions = SessionManager(
        (tmp_path / "sessions").resolve(), lambda: cdp_cfg
    )
    tracker = LatestTracker()
    knowledge = KnowledgeIndex.load()
    timeline_module.register(
        mcp,
        sessions=sessions,
        knowledge_index=knowledge,
        cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker,
        cache_root=cache_root,
    )
    return {
        "mcp": mcp,
        "sessions": sessions,
        "tracker": tracker,
        "cdp_dir": cdp,
        "cdp_cfg": cdp_cfg,
        "knowledge": knowledge,
        "cache_root": cache_root,
    }


async def _call(env: dict, args: dict[str, Any]) -> Any:
    """Through the registered MCP tool (schema-typed arguments)."""
    return await env["mcp"]._tool_manager.call_tool(
        "timeline", args, context=None, convert_result=False
    )


async def _impl(env: dict, events: Any, **kwargs) -> dict:
    """Directly against timeline_impl (for arguments the MCP schema
    layer would reject before the tool's own validation could run)."""
    return await timeline_impl(
        _FakeCtx(),
        events,
        kwargs.pop("headroom", "auto"),
        kwargs.pop("output_name", None),
        kwargs.pop("timeout_seconds", 120.0),
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )


def _session_with_inputs(env):
    """Session with mono 1 s / 2 s wavs, a stereo wav, and a 22.05 kHz
    mono wav (for the SR-compat refusal)."""
    session, _ = env["sessions"].set_active("tl1")
    sr = 44100
    rng = np.random.default_rng(0)
    one = (rng.standard_normal(sr) * 0.2).astype(np.float32)
    two = (rng.standard_normal(sr * 2) * 0.2).astype(np.float32)
    st = (rng.standard_normal((sr, 2)) * 0.2).astype(np.float32)
    low = (rng.standard_normal(22050) * 0.2).astype(np.float32)
    sf.write(str(session.inputs_dir / "one.wav"), one, sr, subtype="PCM_16")
    sf.write(str(session.inputs_dir / "two.wav"), two, sr, subtype="PCM_16")
    sf.write(str(session.inputs_dir / "st.wav"), st, sr, subtype="PCM_16")
    sf.write(
        str(session.inputs_dir / "low.wav"), low, 22050, subtype="PCM_16"
    )
    return session


# ---------------------------------------------------------------------------
# Validation failures (nothing executes, nothing on disk)
# ---------------------------------------------------------------------------


async def test_timeline_empty_or_malformed_events(harness):
    session = _session_with_inputs(harness)
    for bad in ([], "nope", [{"source": "one.wav", "at": 0.0}, 7]):
        payload = await _impl(harness, bad)
        assert payload["status"] == "failed"
        assert any(
            e["type"] == "timeline_spec_error" for e in payload["errors"]
        ), payload["errors"]
    assert list(session.graphs_dir.iterdir()) == []


async def test_timeline_bad_reference(harness):
    session = _session_with_inputs(harness)
    payload = await _call(
        harness, {"events": [{"source": "absent.wav", "at": 0.0}]}
    )
    assert payload["status"] == "failed"
    (err,) = payload["errors"]
    assert err["type"] == "reference_resolution"
    assert "events[0]" in err["message"]
    assert list(session.graphs_dir.iterdir()) == []


async def test_timeline_event_shape_errors_collected(harness):
    """Negative at, unknown key, bad level, bad pan — ALL reported in
    one round trip, index-prefixed."""
    _session_with_inputs(harness)
    payload = await _impl(harness, [
        {"source": "one.wav", "at": -0.5},
        {"source": "one.wav", "at": 0.0, "time": 1.0},
        {"source": "one.wav", "at": 0.0, "level": -1.0},
        {"source": "one.wav", "at": 0.0, "pan": "L"},
    ])
    assert payload["status"] == "failed"
    assert all(e["type"] == "invalid_event" for e in payload["errors"])
    messages = " | ".join(e["message"] for e in payload["errors"])
    for idx in range(4):
        assert f"events[{idx}]" in messages
    assert "at must be" in messages
    assert "unknown key" in messages
    assert "level must be" in messages
    assert "pan must be" in messages


async def test_timeline_bad_headroom_value(harness):
    _session_with_inputs(harness)
    payload = await _call(
        harness,
        {"events": [{"source": "one.wav", "at": 0.0}], "headroom": "loud"},
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "timeline_spec_error" for e in payload["errors"]
    )


async def test_timeline_pan_on_stereo_source_refused(harness):
    _session_with_inputs(harness)
    payload = await _call(
        harness, {"events": [{"source": "st.wav", "at": 0.0, "pan": 0.5}]}
    )
    assert payload["status"] == "failed"
    (err,) = payload["errors"]
    assert err["type"] == "pan_requires_mono"
    assert "events[0]" in err["message"]


async def test_timeline_mixed_sample_rates_refused(harness):
    _session_with_inputs(harness)
    payload = await _call(harness, {"events": [
        {"source": "one.wav", "at": 0.0},
        {"source": "low.wav", "at": 1.0},
    ]})
    assert payload["status"] == "failed"
    (err,) = payload["errors"]
    assert err["type"] == "incompatible_sample_rates"
    assert "22050" in err["message"] and "44100" in err["message"]


async def test_timeline_duration_cap(harness):
    """at 299.5 + a 1 s source predicts 300.5 s > the 300 s cap —
    refused before the mixfile is written or anything runs."""
    session = _session_with_inputs(harness)
    payload = await _call(
        harness, {"events": [
            {"source": "one.wav", "at": 0.0},
            {"source": "one.wav", "at": 299.5},
        ]}
    )
    assert payload["status"] == "failed"
    (err,) = payload["errors"]
    assert err["type"] == "predicted_duration_exceeds_cap"
    assert payload["predicted_duration_s"] == pytest.approx(300.5)
    assert payload["mixfile"] is None
    assert list(session.graphs_dir.iterdir()) == []
    assert list((session.root / "data").glob("timeline_*")) == []


# ---------------------------------------------------------------------------
# Mixfile content + duration rule (hermetic happy path, headroom off)
# ---------------------------------------------------------------------------


async def test_timeline_mixfile_content_pinned(harness):
    """Exact mixfile lines for a 3-event case: cwd-relative paths, chans
    column matching the real channel count, level defaulting, pan only
    on the event that carries one."""
    session = _session_with_inputs(harness)
    payload = await _call(harness, {
        "events": [
            {"source": "one.wav", "at": 0.0},
            {"source": "two.wav", "at": 0.5, "level": 0.5},
            {"source": "one.wav", "at": 2.0, "level": 1.0, "pan": -0.25},
        ],
        "headroom": "off",
    })
    assert payload["status"] == "ok", payload["errors"]

    mixfile = Path(payload["mixfile"])
    assert mixfile.parent == session.root / "data"
    assert mixfile.name.startswith("timeline_")
    assert mixfile.suffix == ".txt"
    assert mixfile.read_text() == (
        "inputs/one.wav 0 1 1\n"
        "inputs/two.wav 0.5 1 0.5\n"
        "inputs/one.wav 2 1 1 -0.25\n"
    )

    # Duration rule max(at+dur) − min(at): max(1.0, 2.5, 3.0) − 0.0.
    assert payload["predicted_duration_s"] == pytest.approx(3.0)

    # headroom='off': no getlevel node, warning says it may wrap.
    assert payload["headroom"] == {
        "mode": "off", "factor": None, "peak": None,
        "applied": False, "report": None,
    }
    assert any("WRAP" in w for w in payload["warnings"])

    # One graph dir, one node (n1_mix), latest updated to it.
    (graph_root,) = list(session.graphs_dir.iterdir())
    assert graph_root.name == payload["graph_id"]
    index = json.loads((graph_root / "node_index.json").read_text())
    assert set(index) == {"n1_mix"}
    assert harness["tracker"].latest == f"{payload['graph_id']}:n1_mix"
    assert Path(payload["output"]).exists()

    # Lineage: mixfile renders BEFORE the output slot; arity-0 (no
    # audio inputs); params snapshot carries the resolved mixfile path.
    lineage = json.loads((graph_root / "lineage.json").read_text())
    node = lineage["nodes"]["n1_mix"]
    argv = node["argv"]
    i_mix = argv.index(f"data/{mixfile.name}")
    (i_out,) = [
        i for i, a in enumerate(argv)
        if a.endswith(".wav") and "graphs/" in a
    ]
    assert i_mix < i_out
    assert node["inputs"] == []
    assert node["params"]["mixfile"].endswith(mixfile.name)

    # Per-event compact report.
    assert [e["path"] for e in payload["events"]] == [
        "inputs/one.wav", "inputs/two.wav", "inputs/one.wav",
    ]
    assert [e["at"] for e in payload["events"]] == [0.0, 0.5, 2.0]
    assert [e["level"] for e in payload["events"]] == [1.0, 0.5, 1.0]
    assert [e["pan"] for e in payload["events"]] == [None, None, -0.25]
    assert [e["end_s"] for e in payload["events"]] == [1.0, 2.5, 3.0]
    assert all(e["samplerate"] == 44100 for e in payload["events"])
    assert all(e["channels"] == 1 for e in payload["events"])


async def test_timeline_leading_silence_stripped_in_prediction(harness):
    """Events at 5.0/5.5 predict 2.5 s (max(at+dur) − min(at)), not
    7.5 — the leading-silence-stripped half of the duration rule."""
    _session_with_inputs(harness)
    payload = await _call(harness, {
        "events": [
            {"source": "one.wav", "at": 5.0},
            {"source": "two.wav", "at": 5.5},
        ],
        "headroom": "off",
    })
    assert payload["status"] == "ok", payload["errors"]
    assert payload["predicted_duration_s"] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Headroom staging (hermetic, fake getlevel reports)
# ---------------------------------------------------------------------------


async def test_timeline_headroom_auto_applies_factor(harness):
    """Default headroom: getlevel's factor < 1 lands as -g on the mix
    argv; both nodes share the graph dir; latest points at the mix."""
    session = _session_with_inputs(harness)
    payload = await _call(harness, {"events": [
        {"source": "one.wav", "at": 0.0},
        {"source": "one.wav", "at": 0.0},
        {"source": "one.wav", "at": 0.0},
    ]})
    assert payload["status"] == "ok", payload["errors"]
    assert payload["headroom"]["mode"] == "auto"
    assert payload["headroom"]["factor"] == pytest.approx(0.336683)
    assert payload["headroom"]["peak"] == pytest.approx(2.970153)
    assert payload["headroom"]["applied"] is True
    report = Path(payload["headroom"]["report"])
    assert report.exists()
    assert "NORMALISATION REQUIRED" in report.read_text()

    (graph_root,) = list(session.graphs_dir.iterdir())
    index = json.loads((graph_root / "node_index.json").read_text())
    assert set(index) == {"n1_headroom", "n2_mix"}
    assert harness["tracker"].latest == f"{payload['graph_id']}:n2_mix"

    lineage = json.loads((graph_root / "lineage.json").read_text())
    assert "-g0.336683" in lineage["nodes"]["n2_mix"]["argv"]


async def test_timeline_headroom_auto_clean_mix_applies_nothing(harness):
    """Factor > 1 (clean mix — available amplification, not a warning):
    no -g on the argv, applied stays false."""
    session = _session_with_inputs(harness)
    _write_submix_wrapper(
        harness["cdp_dir"] / "submix", factor="2.499924", peak="0.400012"
    )
    payload = await _call(
        harness, {"events": [{"source": "one.wav", "at": 0.0}]}
    )
    assert payload["status"] == "ok", payload["errors"]
    assert payload["headroom"]["factor"] == pytest.approx(2.499924)
    assert payload["headroom"]["applied"] is False
    (graph_root,) = list(session.graphs_dir.iterdir())
    lineage = json.loads((graph_root / "lineage.json").read_text())
    argv = lineage["nodes"]["n2_mix"]["argv"]
    assert not any(a.startswith("-g") for a in argv)


async def test_timeline_headroom_fail_structured_error(harness):
    """headroom='fail' + factor < 1 → headroom_required carrying the
    factor; the mix does NOT render; the getlevel node stays for
    inspection."""
    session = _session_with_inputs(harness)
    payload = await _call(harness, {
        "events": [
            {"source": "one.wav", "at": 0.0},
            {"source": "one.wav", "at": 0.0},
        ],
        "headroom": "fail",
    })
    assert payload["status"] == "failed"
    (err,) = payload["errors"]
    assert err["type"] == "headroom_required"
    assert "0.336683" in err["message"]
    assert "WRAP" in err["message"]
    assert payload["headroom"]["factor"] == pytest.approx(0.336683)
    assert payload["headroom"]["applied"] is False
    assert payload["output"] is None

    (graph_root,) = list(session.graphs_dir.iterdir())
    index = json.loads((graph_root / "node_index.json").read_text())
    assert set(index) == {"n1_headroom"}
    assert harness["tracker"].latest is None  # no mix → latest untouched


async def test_timeline_headroom_stage_failure_is_structured(harness):
    """A getlevel subprocess failure surfaces as
    headroom_preflight_failed plus the underlying stage errors."""
    _session_with_inputs(harness)
    _write_submix_wrapper(harness["cdp_dir"] / "submix", getlevel_exit=255)
    payload = await _call(
        harness, {"events": [{"source": "one.wav", "at": 0.0}]}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "headroom_preflight_failed"
    assert len(payload["errors"]) > 1  # per-stage errors follow
    assert payload["output"] is None


# ---------------------------------------------------------------------------
# Real CDP (gated): duration rule, headroom auto vs off (wrap), lineage
# ---------------------------------------------------------------------------


@pytest.fixture
def real_timeline_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    if not (real_cdp_path / "submix").is_file():
        pytest.skip("submix binary not present in CDP_PATH.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    session, _ = sessions.set_active("timeline_v1")
    sr = 44100
    rng = np.random.default_rng(7)
    one = (rng.standard_normal(sr) * 0.2).astype(np.float32)
    two = (rng.standard_normal(sr * 2) * 0.2).astype(np.float32)
    t = np.arange(sr) / sr
    loud = (0.9 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    sf.write(str(session.inputs_dir / "one.wav"), one, sr, subtype="PCM_16")
    sf.write(str(session.inputs_dir / "two.wav"), two, sr, subtype="PCM_16")
    sf.write(str(session.inputs_dir / "loud.wav"), loud, sr, subtype="PCM_16")
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_config,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


async def _run_timeline(env, events, **kwargs) -> dict:
    return await timeline_impl(
        _FakeCtx(),
        events,
        kwargs.pop("headroom", "auto"),
        kwargs.pop("output_name", None),
        kwargs.pop("timeout_seconds", 120.0),
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )


@pytest.mark.timeout(60)
async def test_timeline_real_three_event_duration(real_timeline_env):
    """A 3-event mix renders with duration max(at+dur) − min(at); all
    mono, no pans → mono output."""
    env = real_timeline_env
    r = await _run_timeline(env, [
        {"source": "one.wav", "at": 0.0},
        {"source": "two.wav", "at": 0.5, "level": 0.5},
        {"source": "one.wav", "at": 2.6},
    ])
    assert r["status"] == "ok", r["errors"]
    info = sf.info(r["output"])
    assert info.duration == pytest.approx(3.6, abs=1e-3)
    assert info.channels == 1
    assert r["predicted_duration_s"] == pytest.approx(3.6)


@pytest.mark.timeout(60)
async def test_timeline_real_headroom_auto_no_wrap(real_timeline_env):
    """Three full-level copies of a hot sine: getlevel's factor < 1 is
    applied as atten and the render matches the ideal scaled float sum
    — no wraparound (peak <= 1.0, and no wrap-band artifacts)."""
    env = real_timeline_env
    events = [
        {"source": "loud.wav", "at": 0.0},
        {"source": "loud.wav", "at": 0.0},
        {"source": "loud.wav", "at": 0.0},
    ]
    r = await _run_timeline(env, events)
    assert r["status"] == "ok", r["errors"]
    factor = r["headroom"]["factor"]
    assert r["headroom"]["applied"] is True
    assert factor is not None and factor < 1.0

    out, _ = sf.read(r["output"])
    src, _ = sf.read(str(env["session"].inputs_dir / "loud.wav"))
    ideal = 3.0 * src * factor
    n = min(len(out), len(ideal))
    assert float(np.max(np.abs(out))) <= 1.0
    assert float(np.max(np.abs(out[:n] - ideal[:n]))) < 1e-3

    # Lineage well-formed: getlevel + mix share the graph dir; latest
    # points at the rendered mix; the report parses.
    graph_root = env["session"].graphs_dir / r["graph_id"]
    index = json.loads((graph_root / "node_index.json").read_text())
    assert set(index) == {"n1_headroom", "n2_mix"}
    lineage = json.loads((graph_root / "lineage.json").read_text())
    assert set(lineage["nodes"]) == {"n1_headroom", "n2_mix"}
    assert any(
        a.startswith("-g") for a in lineage["nodes"]["n2_mix"]["argv"]
    )
    assert lineage["nodes"]["n2_mix"]["inputs"] == []
    assert env["tracker"].latest == f"{r['graph_id']}:n2_mix"
    assert "NORMALISATION REQUIRED" in Path(
        r["headroom"]["report"]
    ).read_text()


@pytest.mark.timeout(60)
async def test_timeline_real_headroom_off_wraps(real_timeline_env):
    """The same hot mix with headroom='off' WRAPS: where the ideal
    float sum sits in (1.1, 1.9), wrapped int16 output is negative
    (ideal − 2), the P5-3 pathology."""
    env = real_timeline_env
    events = [
        {"source": "loud.wav", "at": 0.0},
        {"source": "loud.wav", "at": 0.0},
        {"source": "loud.wav", "at": 0.0},
    ]
    r = await _run_timeline(env, events, headroom="off")
    assert r["status"] == "ok", r["errors"]
    assert r["headroom"]["applied"] is False
    assert any("WRAP" in w for w in r["warnings"])

    out, _ = sf.read(r["output"])
    src, _ = sf.read(str(env["session"].inputs_dir / "loud.wav"))
    ideal = 3.0 * src
    n = min(len(out), len(ideal))
    band = (ideal[:n] > 1.1) & (ideal[:n] < 1.9)
    assert band.sum() > 1000  # the hot sine spends real time in the band
    assert float(np.mean(out[:n][band] < 0)) > 0.9  # wrapped negative


@pytest.mark.timeout(60)
async def test_timeline_real_pan_renders_stereo(real_timeline_env):
    """A mono event with a (non-hard) pan produces a stereo render —
    the pinned channel rule and the 5-column mono pan line syntax."""
    env = real_timeline_env
    r = await _run_timeline(
        env,
        [{"source": "one.wav", "at": 0.0, "pan": 0.5}],
        headroom="off",
        output_name="panned",
    )
    assert r["status"] == "ok", r["errors"]
    info = sf.info(r["output"])
    assert info.channels == 2
    assert info.duration == pytest.approx(1.0, abs=1e-3)
