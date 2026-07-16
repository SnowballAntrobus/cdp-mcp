"""Phase 5 wave 2a: arity-0 (generator) entries.

``input_arity: 0`` marks entries with no audio inputs — ``synth noise``
/ ``synth wave`` (pure generators) and ``submix mix`` (sources live in
its mixfile). Coverage:

1. ``process_impl`` runs a generator with the input argument omitted
   (or ``[]``); lineage records an empty inputs list.
2. Passing an input to a generator is a structured ``arity_mismatch``
   with a generator-aware fix.
3. Duration pre-flight with no indurs: ``set_by`` evaluates from the
   dur param; an ``indur``-referencing expression skips cleanly.
4. Breakpoint envelopes on generators compile against the OUTPUT
   duration (``set_by_param`` axis) — synth wave's frq/amp are
   breakpoint-capable with no input audio to borrow an axis from.
5. graph()/batch()/sweep() exclude arity-0 with the structured
   ``arity_zero_unsupported`` error (documented choice: their spec
   shapes are input-wiring by construction).

Plus real-CDP-gated runs: synth noise's deterministic no-seed rendering
(same params → byte-identical) and synth wave's sample-exact set_by dur.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import CDPConfig, detect_cdp
from cdp_mcp.duration_preflight import check_duration_preflight
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.batch import batch_impl
from cdp_mcp.tools.graph_tool import graph_impl
from cdp_mcp.tools.node_validation import validate_node
from cdp_mcp.tools.process import process_impl
from cdp_mcp.tools.sweep import sweep_impl

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


def _write_wav_wrapper(path: Path) -> None:
    path.write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in
        *.wav) OUTPUT="$arg" ;;
    esac
done
exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT"
"""
    )
    path.chmod(0o755)


@pytest.fixture
def synth_env(tmp_path):
    cdp_dir = (tmp_path / "cdp").resolve()
    cdp_dir.mkdir()
    _write_wav_wrapper(cdp_dir / "synth")
    cdp_cfg = CDPConfig(
        cdp_path=cdp_dir, version="fake", detected_binaries=["synth"]
    )
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    session, _ = sessions.set_active("arity0_v1")
    # One ordinary input so the sweep/batch negative tests have a
    # plausible reference to offer.
    samples = np.zeros(44100, dtype=np.float32)
    samples[::2] = 0.2
    sf.write(str(session.inputs_dir / "in.wav"), samples, 44100)
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_cfg,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


async def _run_process(
    env, program, mode, input=None, params=None, submode=None
) -> dict:
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


# ---------------------------------------------------------------------------
# process(): generators run with no input
# ---------------------------------------------------------------------------


async def test_generator_runs_with_input_omitted(synth_env):
    env = synth_env
    r = await _run_process(env, "synth", "noise", params={"dur": 2.0})
    assert r["status"] == "ok", r["errors"]
    assert Path(r["output"]).suffix == ".wav"

    # Lineage: empty inputs list, argv has no input slot before the output.
    graph_id = r["context"]["active_graph"]
    lineage = json.loads(
        (env["session"].graphs_dir / graph_id / "lineage.json").read_text()
    )
    (node,) = lineage["nodes"].values()
    assert node["inputs"] == []
    # [synth, noise, <output>, srate, chans, dur] — output directly after mode.
    assert node["argv"][2].endswith(".wav")
    assert node["argv"][3:6] == ["44100", "1", "2"]


async def test_generator_runs_with_empty_list_input(synth_env):
    r = await _run_process(synth_env, "synth", "noise", input=[], params={"dur": 1.0})
    assert r["status"] == "ok", r["errors"]


async def test_generator_with_input_is_structured_arity_mismatch(synth_env):
    r = await _run_process(
        synth_env, "synth", "noise", input="in.wav", params={"dur": 1.0}
    )
    assert r["status"] == "failed"
    (err,) = [e for e in r["errors"] if e["type"] == "arity_mismatch"]
    assert "generator" in err["fix"]


async def test_synth_wave_submode_and_frq_positional_order(synth_env):
    """synth wave's argv shape: [synth, wave, 1, out, sr, chans, dur, frq]
    — submode before the output, positionals in banner order after it."""
    env = synth_env
    r = await _run_process(
        env, "synth", "wave", submode=1, params={"dur": 2.0, "frq": 220.0}
    )
    assert r["status"] == "ok", r["errors"]
    graph_id = r["context"]["active_graph"]
    lineage = json.loads(
        (env["session"].graphs_dir / graph_id / "lineage.json").read_text()
    )
    (node,) = lineage["nodes"].values()
    argv = node["argv"]
    assert argv[1:3] == ["wave", "1"]
    assert argv[3].endswith(".wav")
    assert argv[4:8] == ["44100", "1", "2", "220"]


# ---------------------------------------------------------------------------
# Duration pre-flight with no indurs
# ---------------------------------------------------------------------------


async def test_preflight_set_by_dur_with_no_inputs(synth_env):
    entry = synth_env["knowledge"].get("synth", "noise")
    errors, predicted = await check_duration_preflight(
        entry=entry, params={"dur": 2.0}, resolved_inputs=[],
    )
    assert errors == []
    assert predicted == pytest.approx(2.0)


async def test_preflight_set_by_dur_still_caps(synth_env):
    entry = synth_env["knowledge"].get("synth", "noise")
    errors, predicted = await check_duration_preflight(
        entry=entry, params={"dur": 7000.0}, resolved_inputs=[],
    )
    assert any(
        e.type == "predicted_duration_exceeds_cap" for e in errors
    )
    assert predicted == pytest.approx(7000.0)


async def test_preflight_indur_expression_skips_with_no_inputs():
    """An indur-referencing expression with an empty indurs list must
    skip (chain-invariant style), not KeyError into a structured
    evaluation failure."""
    from cdp_mcp.schema import KnowledgeEntry

    entry = KnowledgeEntry(
        program="p", mode="m", category="x", domain="time",
        input_arity=0, channel_constraint="any",
        input_format="none", output_format=".wav",
        duration_model={"kind": "expression", "expr": "indur * 2"},
        description="x", musical_use="x", parameters={},
    )
    errors, predicted = await check_duration_preflight(
        entry=entry, params={}, resolved_inputs=[],
    )
    assert errors == []
    assert predicted is None


# ---------------------------------------------------------------------------
# Breakpoints on generators: set_by_param axis
# ---------------------------------------------------------------------------


async def test_generator_breakpoint_axis_is_output_duration(synth_env):
    """synth wave frq envelope: with no input audio, relative times must
    compile against the dur param (set_by_param), producing a .brk whose
    final timestamp is the output duration."""
    env = synth_env
    vr = await validate_node(
        ctx=None,
        entry=env["knowledge"].get("synth", "wave", 1),
        inputs=[],
        params={"dur": 4.0, "frq": [[0.0, 220.0], [1.0, 880.0]]},
        output_name=None,
        timeout_seconds=30.0,
        session=env["session"],
        cdp=env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
        dry_run=True,
    )
    assert vr.errors == []
    record = vr.compiled_breakpoints["frq"]
    assert record.source_kind == "set_by_param"
    assert record.source_duration_s == pytest.approx(4.0)


async def test_generator_breakpoint_end_to_end(synth_env):
    env = synth_env
    r = await _run_process(
        env, "synth", "wave", submode=1,
        params={"dur": 2.0, "frq": [[0.0, 220.0], [1.0, 880.0]]},
    )
    assert r["status"] == "ok", r["errors"]
    graph_id = r["context"]["active_graph"]
    lineage = json.loads(
        (env["session"].graphs_dir / graph_id / "lineage.json").read_text()
    )
    (node,) = lineage["nodes"].values()
    assert node["compiled_breakpoints"]["frq"]["source_kind"] == "set_by_param"
    # The frq positional slot carries the compiled .brk path.
    assert any(a.endswith(".brk") for a in node["argv"])


# ---------------------------------------------------------------------------
# graph()/batch()/sweep(): structured exclusion
# ---------------------------------------------------------------------------


async def test_batch_refuses_arity_zero(synth_env):
    env = synth_env
    r = await batch_impl(
        _FakeCtx(),
        program="synth",
        mode="noise",
        inputs=["in.wav"],
        params={"dur": 1.0},
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )
    assert r["status"] == "failed"
    assert any(
        e["type"] == "arity_zero_unsupported" for e in r["errors"]
    )


async def test_sweep_refuses_arity_zero(synth_env):
    env = synth_env
    r = await sweep_impl(
        _FakeCtx(),
        program="synth",
        mode="noise",
        input="in.wav",
        param_sets=[{"dur": 1.0}, {"dur": 2.0}],
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )
    assert r["status"] == "failed"
    assert any(
        e["type"] == "arity_zero_unsupported" for e in r["errors"]
    )


async def test_graph_refuses_arity_zero_node(synth_env):
    env = synth_env
    r = await graph_impl(
        _FakeCtx(),
        inputs={"src": "in.wav"},
        nodes=[
            {"id": "gen", "op": "synth noise", "in": "src",
             "params": {"dur": 1.0}},
        ],
        dry_run=True,
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )
    assert r["status"] == "failed"
    assert any(
        e["type"] == "arity_zero_unsupported" for e in r["errors"]
    )


# ---------------------------------------------------------------------------
# Real CDP (gated): synth generators against the binaries
# ---------------------------------------------------------------------------


@pytest.fixture
def real_synth_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    if not (real_cdp_path / "synth").is_file():
        pytest.skip("synth binary not present in CDP_PATH.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    session, _ = sessions.set_active("synth_real_v1")
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_config,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


@pytest.mark.timeout(60)
async def test_synth_noise_real_cdp_deterministic_and_exact(real_synth_env):
    """set_by dur is sample-exact, and the no-seed determinism the entry
    documents holds: identical params render byte-identically."""
    env = real_synth_env

    async def run(name: str) -> dict:
        return await process_impl(
            _FakeCtx(),
            program="synth", mode="noise",
            params={"dur": 2.0, "amp": 0.5},
            output_name=name,
            sessions=env["sessions"],
            knowledge_index=env["knowledge"],
            cdp_config_provider=lambda: env["cdp_cfg"],
            latest_tracker=env["tracker"],
            cache_root=env["cache_root"],
        )

    r1 = await run("take1")
    assert r1["status"] == "ok", r1["errors"]
    info = sf.info(r1["output"])
    assert info.frames == 88200  # sample-exact set_by dur
    assert info.channels == 1

    r2 = await run("take2")
    assert r2["status"] == "ok", r2["errors"]
    a, _ = sf.read(r1["output"])
    b, _ = sf.read(r2["output"])
    assert np.array_equal(a, b), "synth noise must be deterministic (no seed)"


@pytest.mark.timeout(60)
async def test_synth_wave_real_cdp_frq_breakpoint(real_synth_env):
    """A frq envelope through the engine's set_by_param axis renders and
    differs from the constant-frq render."""
    env = real_synth_env

    async def run(params, name):
        return await process_impl(
            _FakeCtx(),
            program="synth", mode="wave", submode=1,
            params=params,
            output_name=name,
            sessions=env["sessions"],
            knowledge_index=env["knowledge"],
            cdp_config_provider=lambda: env["cdp_cfg"],
            latest_tracker=env["tracker"],
            cache_root=env["cache_root"],
        )

    r_const = await run({"dur": 2.0, "frq": 440.0, "amp": 0.5}, "const")
    assert r_const["status"] == "ok", r_const["errors"]
    assert sf.info(r_const["output"]).frames == 88200

    r_brk = await run(
        {"dur": 2.0, "frq": [[0.0, 220.0], [1.0, 880.0]], "amp": 0.5},
        "gliss",
    )
    assert r_brk["status"] == "ok", r_brk["errors"]
    a, _ = sf.read(r_const["output"])
    b, _ = sf.read(r_brk["output"])
    assert not np.array_equal(a, b)
