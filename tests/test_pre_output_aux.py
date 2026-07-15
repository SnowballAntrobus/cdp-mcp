"""Phase 5 wave 2a: ``position: "pre_output"`` aux-parameter placement.

The engine gap that dropped ``submix mix`` and ``formants put`` in
tranche 5 (docs/curation/tranche5_mix_env_findings.json, dropped[0] and
dropped[3]): those programs want their data file BETWEEN the inputs and
the output path (``submix mix mixfile outfile``), while ``build_cdp_argv``
rendered every parameter after the output.

Coverage:

1. ``ParameterSpec`` validator — ``position`` is only legal on
   positional ``aux_file`` params.
2. ``build_cdp_argv`` — pre_output params render before the output slot,
   in entry declaration order; everything else stays after it.
3. End-to-end via ``process_impl`` with a fake binary — the curated
   ``submix mix`` entry (arity 0 + pre_output mixfile) produces an argv
   with the mixfile ahead of the output, records it in lineage, and
   passes verification.
4. Security — an existing outside-session pre_output path is rejected by
   the path-scope gate (``path_outside_session``), same boundary as
   ordinary aux files.

Plus real-CDP-gated re-verification of the tranche-5 empirics the
``submix mix`` entry ships: the duration rule (max(at+dur) − min(at),
leading silence stripped) and linear overlap summation.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from pydantic import ValidationError

from cdp_mcp.config import CDPConfig, detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.processing import build_cdp_argv
from cdp_mcp.schema import KnowledgeEntry, ParameterSpec
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.process import process_impl

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()

_OTHER_CWD = Path("/elsewhere")


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


# ---------------------------------------------------------------------------
# ParameterSpec validator: position requires a positional aux_file
# ---------------------------------------------------------------------------


def test_position_valid_on_positional_aux_file():
    spec = ParameterSpec(type="aux_file", position="pre_output")
    assert spec.position == "pre_output"


def test_position_rejected_on_non_aux_type():
    with pytest.raises(ValidationError, match="aux_file"):
        ParameterSpec(type="float", position="pre_output")


def test_position_rejected_on_flagged_aux_file():
    with pytest.raises(ValidationError, match="positional"):
        ParameterSpec(
            type="aux_file",
            position="pre_output",
            flag="-x",
            flag_kind="attached_value",
        )


def test_position_none_unconstrained():
    # position=None imposes nothing — the Phase 3 aux_file shape parses
    # exactly as before.
    spec = ParameterSpec(type="aux_file")
    assert spec.position is None


# ---------------------------------------------------------------------------
# build_cdp_argv ordering
# ---------------------------------------------------------------------------


def _entry(parameters: dict[str, ParameterSpec], **overrides) -> KnowledgeEntry:
    base: dict = dict(
        program="p",
        mode="m",
        submode=None,
        category="x",
        domain="time",
        input_arity=1,
        channel_constraint="any",
        input_format=".wav",
        output_format=".wav",
        duration_model={"kind": "static"},
        description="x",
        musical_use="x",
        parameters=parameters,
    )
    base.update(overrides)
    return KnowledgeEntry(**base)


def test_pre_output_param_renders_before_output_slot():
    entry = _entry({
        "datafile": ParameterSpec(type="aux_file", position="pre_output"),
        "gain": ParameterSpec(
            type="float", flag="-g", flag_kind="attached_value"
        ),
    })
    argv = build_cdp_argv(
        entry,
        [Path("in.wav")],
        Path("out.wav"),
        {"datafile": Path("data/events.mix"), "gain": 0.5},
        cwd=_OTHER_CWD,
    )
    assert argv == [
        "p", "m", "in.wav", "data/events.mix", "out.wav", "-g0.5",
    ]


def test_pre_output_with_arity_zero_layout():
    """submix mix's exact shape: [program, mode, mixfile, output, flags]."""
    entry = _entry(
        {
            "mixfile": ParameterSpec(type="aux_file", position="pre_output"),
            "atten": ParameterSpec(
                type="float", flag="-g", flag_kind="attached_value"
            ),
        },
        input_arity=0,
    )
    argv = build_cdp_argv(
        entry, [], Path("out.wav"),
        {"mixfile": Path("data/ev.mix"), "atten": 0.3},
        cwd=_OTHER_CWD,
    )
    assert argv == ["p", "m", "data/ev.mix", "out.wav", "-g0.3"]


def test_pre_output_declaration_order_preserved():
    entry = _entry({
        "first": ParameterSpec(type="aux_file", position="pre_output"),
        "second": ParameterSpec(type="aux_file", position="pre_output"),
    })
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"),
        {"first": Path("a.dat"), "second": Path("b.dat")},
        cwd=_OTHER_CWD,
    )
    assert argv.index("a.dat") < argv.index("b.dat") < argv.index("out.wav")


def test_ordinary_params_unaffected_by_pre_output_split():
    """No pre_output params → byte-for-byte the Phase 3 layout."""
    entry = _entry({
        "cnt": ParameterSpec(type="int"),
        "gain": ParameterSpec(
            type="float", flag="-g", flag_kind="attached_value"
        ),
    })
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"),
        {"cnt": 3, "gain": 0.5}, cwd=_OTHER_CWD,
    )
    assert argv == ["p", "m", "in.wav", "out.wav", "3", "-g0.5"]


# ---------------------------------------------------------------------------
# End-to-end via process_impl (fake CDP): the curated submix mix entry
# ---------------------------------------------------------------------------


def _write_wav_wrapper(path: Path) -> None:
    """Fake binary: writes a non-silent wav at the last .wav argv element
    (the output slot — the mixfile precedes it, so 'last' is the output)."""
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
def submix_env(tmp_path):
    cdp_dir = (tmp_path / "cdp").resolve()
    cdp_dir.mkdir()
    _write_wav_wrapper(cdp_dir / "submix")
    cdp_cfg = CDPConfig(
        cdp_path=cdp_dir, version="fake", detected_binaries=["submix"]
    )
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    session, _ = sessions.set_active("preout_v1")
    data_dir = session.root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "ev.mix").write_text(
        "inputs/a.wav 0.0 1 1.0\ninputs/b.wav 0.5 1 0.5\n"
    )
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_cfg,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


async def _run_submix(env, params) -> dict:
    return await process_impl(
        _FakeCtx(),
        program="submix",
        mode="mix",
        input=None,  # arity-0 entry: no audio input
        params=params,
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )


async def test_submix_mix_argv_places_mixfile_before_output(submix_env):
    env = submix_env
    r = await _run_submix(env, {"mixfile": "ev.mix"})
    assert r["status"] == "ok", r["errors"]

    graph_id = r["context"]["active_graph"]
    lineage = json.loads(
        (env["session"].graphs_dir / graph_id / "lineage.json").read_text()
    )
    (node,) = lineage["nodes"].values()
    argv = node["argv"]
    assert argv[1] == "mix"
    i_mix = argv.index("data/ev.mix")
    (i_out,) = [
        i for i, a in enumerate(argv)
        if a.endswith(".wav") and "graphs/" in a
    ]
    assert i_mix < i_out, f"mixfile must precede the output slot: {argv}"
    # Arity-0: lineage records no audio inputs; the mixfile path in the
    # params snapshot is the provenance trail.
    assert node["inputs"] == []
    assert node["params"]["mixfile"].endswith("ev.mix")


async def test_submix_mix_atten_flag_renders_after_output(submix_env):
    env = submix_env
    r = await _run_submix(env, {"mixfile": "ev.mix", "atten": 0.34})
    assert r["status"] == "ok", r["errors"]
    graph_id = r["context"]["active_graph"]
    lineage = json.loads(
        (env["session"].graphs_dir / graph_id / "lineage.json").read_text()
    )
    (node,) = lineage["nodes"].values()
    argv = node["argv"]
    (i_out,) = [
        i for i, a in enumerate(argv)
        if a.endswith(".wav") and "graphs/" in a
    ]
    assert "-g0.34" in argv and argv.index("-g0.34") > i_out


async def test_submix_mix_missing_mixfile_is_structured_error(submix_env):
    r = await _run_submix(submix_env, {"mixfile": "absent.mix"})
    assert r["status"] == "failed"
    assert any(e["type"] == "param_aux_file_missing" for e in r["errors"])


async def test_pre_output_outside_session_rejected_by_security_gate(
    submix_env, tmp_path
):
    """The pre_output slot goes through the same path-scope boundary as
    every argv element: an existing file outside the session refuses."""
    outside = (tmp_path / "outside.mix").resolve()
    outside.write_text("inputs/a.wav 0.0 1 1.0\n")
    assert outside.is_file()
    r = await _run_submix(submix_env, {"mixfile": str(outside)})
    assert r["status"] == "failed"
    assert any(e["type"] == "path_outside_session" for e in r["errors"])


async def test_submix_mix_duration_preflight_skips(submix_env):
    """duration_model expr 'mixfile' references a non-scalar param —
    pre-flight must skip (no prediction), never error."""
    from cdp_mcp.duration_preflight import check_duration_preflight

    entry = submix_env["knowledge"].get("submix", "mix")
    errors, predicted = await check_duration_preflight(
        entry=entry,
        params={"mixfile": "ev.mix"},
        resolved_inputs=[],
    )
    assert errors == []
    assert predicted is None


# ---------------------------------------------------------------------------
# Real CDP (gated): the tranche-5 submix mix empirics the entry ships
# ---------------------------------------------------------------------------


@pytest.fixture
def real_submix_env(tmp_path, real_cdp_path):
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
    session, _ = sessions.set_active("submix_mix_v1")
    sr = 44100
    rng = np.random.default_rng(0)
    one = (rng.standard_normal(sr) * 0.2).astype(np.float32)
    two = (rng.standard_normal(sr * 2) * 0.2).astype(np.float32)
    sf.write(str(session.inputs_dir / "one.wav"), one, sr, subtype="PCM_16")
    sf.write(str(session.inputs_dir / "two.wav"), two, sr, subtype="PCM_16")
    data_dir = session.root / "data"
    data_dir.mkdir(exist_ok=True)
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_config,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


@pytest.mark.timeout(60)
async def test_submix_mix_real_cdp_duration_rule(real_submix_env):
    """outdur = max(at+dur) − min(at): overlap config lands sample-exact,
    and leading silence before the first event is stripped."""
    env = real_submix_env
    session = env["session"]

    async def run(mixname: str, content: str, out: str) -> dict:
        (session.root / "data" / mixname).write_text(content)
        return await process_impl(
            _FakeCtx(),
            program="submix", mode="mix",
            params={"mixfile": mixname},
            output_name=out,
            sessions=env["sessions"],
            knowledge_index=env["knowledge"],
            cdp_config_provider=lambda: env["cdp_cfg"],
            latest_tracker=env["tracker"],
            cache_root=env["cache_root"],
        )

    # Overlap: 1 s file at 0.0 + 2 s file at 0.5 → 2.5 s exactly.
    r = await run(
        "overlap.mix",
        "inputs/one.wav 0.0 1 1.0\ninputs/two.wav 0.5 1 0.5\n",
        "overlap_take",
    )
    assert r["status"] == "ok", r["errors"]
    assert sf.info(r["output"]).duration == pytest.approx(2.5, abs=1e-4)

    # Leading silence stripped: a lone event at 1.0 s → 1.0 s output.
    r = await run(
        "late.mix", "inputs/one.wav 1.0 1 1.0\n", "late_take"
    )
    assert r["status"] == "ok", r["errors"]
    assert sf.info(r["output"]).duration == pytest.approx(1.0, abs=1e-4)


@pytest.mark.timeout(60)
async def test_submix_mix_real_cdp_linear_overlap_sum(real_submix_env):
    """Two 0.5-level copies of one file sum bit-identically to the
    original — the linearity half of the overload-WRAPS finding."""
    env = real_submix_env
    session = env["session"]
    (session.root / "data" / "sum.mix").write_text(
        "inputs/two.wav 0.0 1 0.5\ninputs/two.wav 0.0 1 0.5\n"
    )
    r = await process_impl(
        _FakeCtx(),
        program="submix", mode="mix",
        params={"mixfile": "sum.mix"},
        output_name="summed",
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )
    assert r["status"] == "ok", r["errors"]
    out, _ = sf.read(r["output"])
    src, _ = sf.read(str(session.inputs_dir / "two.wav"))
    assert np.array_equal(out, src)
