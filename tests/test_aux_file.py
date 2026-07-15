"""Phase 3: aux_file parameter type + no_value switch semantics.

Three concern areas, per the tranche 3 findings record that motivated the
engine change (docs/curation/tranche3_timedomain_findings.json, dropped[0]):

1. ``validate_params`` — ``aux_file`` params accept a str path with any
   extension except ``.brk``; bools are accepted only for ``no_value``
   switch params.
2. ``build_cdp_argv`` — a ``no_value`` switch with a falsy value
   (False / 0 / None-after-default) must NOT emit the flag; truthy emits
   the bare flag. Regression: ``strange glis``'s ``default: false`` ``-i``
   previously emitted unconditionally.
3. End-to-end via ``process_impl`` — aux files resolve against the
   session's ``data/`` directory, render cwd-relative in the argv,
   missing files fail with ``param_aux_file_missing``, and an
   outside-session aux path is rejected by the security gate.

Plus a real-CDP-gated re-verification of ``texture simple`` mode 5 (the
re-curated entry that consumes aux_file).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import CDPConfig, detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.processing import build_cdp_argv, validate_params
from cdp_mcp.schema import KnowledgeEntry, ParameterSpec
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.node_validation import validate_node
from cdp_mcp.tools.process import process_impl

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()

_OTHER_CWD = Path("/elsewhere")


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


def _entry_with(
    parameters: dict[str, ParameterSpec],
    *,
    program: str = "p",
    mode: str = "m",
    submode: int | None = None,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        program=program,
        mode=mode,
        submode=submode,
        category="x",
        domain="time",
        input_arity=1,
        channel_constraint="any",
        input_format=".wav",
        output_format=".wav",
        duration_model={"kind": "static"},  # type: ignore[arg-type]
        description="x",
        musical_use="x",
        parameters=parameters,
    )


# ---------------------------------------------------------------------------
# validate_params: aux_file typing
# ---------------------------------------------------------------------------


def test_aux_file_accepts_txt_path_string():
    entry = _entry_with({"notedata": ParameterSpec(type="aux_file")})
    errors, warnings = validate_params(entry, {"notedata": "nd.txt"})
    assert errors == []
    assert warnings == []


@pytest.mark.parametrize("value", ["notes.dat", "data/notes.csv", "no_extension"])
def test_aux_file_accepts_any_non_brk_extension(value):
    entry = _entry_with({"notedata": ParameterSpec(type="aux_file")})
    errors, _ = validate_params(entry, {"notedata": value})
    assert errors == []


def test_aux_file_rejects_brk_path():
    """.brk is the breakpoint compiler's routing extension — an aux file
    named .brk would be validated as time/value pairs, which it is not."""
    entry = _entry_with({"notedata": ParameterSpec(type="aux_file")})
    errors, _ = validate_params(entry, {"notedata": "nd.brk"})
    assert any(e.type == "param_type" and ".brk" in e.message for e in errors)


@pytest.mark.parametrize("value", [5, 1.5, [[0.0, 60.0]], True, None])
def test_aux_file_rejects_non_string_values(value):
    entry = _entry_with({"notedata": ParameterSpec(type="aux_file")})
    errors, _ = validate_params(entry, {"notedata": value})
    assert any(e.type == "param_type" for e in errors)


def test_aux_file_positional_without_default_is_required():
    entry = _entry_with({"notedata": ParameterSpec(type="aux_file")})
    errors, _ = validate_params(entry, {})
    assert any(e.type == "missing_parameter" for e in errors)


# ---------------------------------------------------------------------------
# validate_params: bool acceptance for no_value switches
# ---------------------------------------------------------------------------


def test_bool_accepted_for_no_value_switch():
    entry = _entry_with({
        "quick": ParameterSpec(type="bool", flag="-i", flag_kind="no_value"),
    })
    for v in (True, False):
        errors, _ = validate_params(entry, {"quick": v})
        assert errors == [], f"bool {v} should be accepted for a no_value switch"


def test_bool_still_rejected_for_numeric_params():
    entry = _entry_with({"x": ParameterSpec(type="float")})
    errors, _ = validate_params(entry, {"x": True})
    assert any(e.type == "param_type" and "bool" in e.message for e in errors)


def test_bool_rejected_for_attached_value_flag():
    entry = _entry_with({
        "gain": ParameterSpec(type="float", flag="-g", flag_kind="attached_value"),
    })
    errors, _ = validate_params(entry, {"gain": True})
    assert any(e.type == "param_type" for e in errors)


# ---------------------------------------------------------------------------
# build_cdp_argv: no_value falsy/truthy semantics (the strange_glis bug)
# ---------------------------------------------------------------------------


def _switch_entry(**spec_kwargs) -> KnowledgeEntry:
    return _entry_with({
        "cnt": ParameterSpec(type="int"),
        "switch": ParameterSpec(
            type="bool", flag="-b", flag_kind="no_value", **spec_kwargs
        ),
    })


def test_no_value_flag_default_false_omitted():
    """Regression: a curated ``default: false`` switch must NOT emit the
    flag when the user doesn't ask for it (previously emitted always)."""
    entry = _switch_entry(default=False)
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"), {"cnt": 4}, cwd=_OTHER_CWD
    )
    assert "-b" not in argv


@pytest.mark.parametrize("falsy", [False, 0])
def test_no_value_flag_explicit_falsy_omitted(falsy):
    entry = _switch_entry(default=False)
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"),
        {"cnt": 4, "switch": falsy}, cwd=_OTHER_CWD,
    )
    assert "-b" not in argv


@pytest.mark.parametrize("truthy", [True, 1])
def test_no_value_flag_truthy_emits_bare_flag(truthy):
    entry = _switch_entry(default=False)
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"),
        {"cnt": 4, "switch": truthy}, cwd=_OTHER_CWD,
    )
    assert "-b" in argv
    assert not any(a.startswith("-b") and len(a) > 2 for a in argv)


def test_no_value_flag_default_true_emits_without_user_value():
    entry = _switch_entry(default=True)
    argv = build_cdp_argv(
        entry, [Path("in.wav")], Path("out.wav"), {"cnt": 4}, cwd=_OTHER_CWD
    )
    assert "-b" in argv


# ---------------------------------------------------------------------------
# build_cdp_argv: aux_file Path rendering
# ---------------------------------------------------------------------------


def test_aux_file_path_value_rendered_cwd_relative():
    """After node_validation resolves an aux_file param to a Path inside
    the session, build_cdp_argv renders it cwd-relative like any path."""
    entry = _entry_with({
        "notedata": ParameterSpec(type="aux_file"),
        "outdur": ParameterSpec(type="float"),
    })
    cwd = Path("/sessions/s1")
    argv = build_cdp_argv(
        entry,
        [cwd / "inputs" / "in.wav"],
        cwd / "graphs" / "g1" / "out.wav",
        {"notedata": cwd / "data" / "nd.txt", "outdur": 5.0},
        cwd=cwd,
    )
    assert "data/nd.txt" in argv
    i_nd = argv.index("data/nd.txt")
    i_od = argv.index("5")
    assert i_nd < i_od  # declaration order: notedata before outdur


# ---------------------------------------------------------------------------
# strange_glis: the curated entry that motivated the falsy fix
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def knowledge_index() -> KnowledgeIndex:
    return KnowledgeIndex.load()


def test_strange_glis_argv_excludes_i_by_default(knowledge_index):
    """quicksearch has default false — the -i switch must not appear
    unless asked for (it previously emitted on every run)."""
    entry = knowledge_index.get("strange", "glis")
    assert entry is not None
    argv = build_cdp_argv(
        entry, [Path("/tmp/in.ana")], Path("/tmp/out.ana"),
        {"pbands": 8, "glisrate": 2.0}, cwd=_OTHER_CWD,
    )
    assert "-i" not in argv


def test_strange_glis_quicksearch_true_emits_i(knowledge_index):
    entry = knowledge_index.get("strange", "glis")
    errors, _ = validate_params(
        entry, {"pbands": 8, "glisrate": 2.0, "quicksearch": True}
    )
    assert errors == []
    argv = build_cdp_argv(
        entry, [Path("/tmp/in.ana")], Path("/tmp/out.ana"),
        {"pbands": 8, "glisrate": 2.0, "quicksearch": True}, cwd=_OTHER_CWD,
    )
    assert "-i" in argv


# ---------------------------------------------------------------------------
# End-to-end via process_impl (fake CDP): texture simple's aux notedata
# ---------------------------------------------------------------------------


def _write_wrapper(path: Path) -> None:
    """Fake 'texture' binary: writes a non-silent wav at the last
    .wav-looking argv element (the output slot)."""
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
def texture_env(tmp_path):
    """Session + fake CDP install with a 'texture' wrapper binary."""
    cdp_dir = (tmp_path / "cdp").resolve()
    cdp_dir.mkdir()
    _write_wrapper(cdp_dir / "texture")
    cdp_cfg = CDPConfig(
        cdp_path=cdp_dir, version="fake", detected_binaries=["texture"]
    )
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    session, _ = sessions.set_active("aux_v1")
    samples = np.zeros(44100 * 2, dtype=np.float32)
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


_TEXTURE_PARAMS: dict[str, Any] = {
    "outdur": 5.0, "packing": 0.25, "mindur": 0.2, "maxdur": 0.5,
}


async def _run_texture(env, params: dict[str, Any]) -> dict:
    return await process_impl(
        _FakeCtx(),
        program="texture",
        mode="simple",
        input="in.wav",
        params=params,
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )


async def test_aux_file_resolves_from_data_dir_end_to_end(texture_env):
    env = texture_env
    session = env["session"]
    data_dir = session.root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "nd.txt").write_text("60\n")

    r = await _run_texture(env, {"notedata": "nd.txt", **_TEXTURE_PARAMS})
    assert r["status"] == "ok", r["errors"]

    # The lineage argv carries the cwd-relative resolved aux path, and the
    # params snapshot records the resolved absolute location.
    graph_id = r["context"]["active_graph"]
    lineage = json.loads(
        (session.graphs_dir / graph_id / "lineage.json").read_text()
    )
    (node,) = lineage["nodes"].values()
    assert "data/nd.txt" in node["argv"]
    assert node["params"]["notedata"] == str((data_dir / "nd.txt").resolve())
    # no_value regression in the real flow: 'whole' defaults false — no -w.
    assert "-w" not in node["argv"]


async def test_aux_file_missing_is_structured_error(texture_env):
    env = texture_env
    r = await _run_texture(env, {"notedata": "nope.txt", **_TEXTURE_PARAMS})
    assert r["status"] == "failed"
    assert any(e["type"] == "param_aux_file_missing" for e in r["errors"])


async def test_aux_file_outside_session_rejected_by_security_gate(
    texture_env, tmp_path
):
    """An aux path that exists but lives outside the session tree must be
    refused end-to-end — the security gate's path-scope check owns the
    boundary."""
    env = texture_env
    outside = (tmp_path / "outside.txt").resolve()
    outside.write_text("60\n")
    assert outside.is_file()
    r = await _run_texture(
        env, {"notedata": str(outside), **_TEXTURE_PARAMS}
    )
    assert r["status"] == "failed"
    assert any(e["type"] == "path_outside_session" for e in r["errors"])


async def test_aux_file_brk_value_rejected_end_to_end(texture_env):
    env = texture_env
    r = await _run_texture(env, {"notedata": "nd.brk", **_TEXTURE_PARAMS})
    assert r["status"] == "failed"
    assert any(e["type"] == "param_type" for e in r["errors"])


async def test_aux_file_dry_run_resolves_and_checks_existence(texture_env):
    """graph(dry_run=True) shares the aux resolution step: planned argv
    carries the resolved cwd-relative path; a missing file errors."""
    env = texture_env
    session = env["session"]
    data_dir = session.root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "nd.txt").write_text("60\n")
    entry = env["knowledge"].get("texture", "simple")

    ok = await validate_node(
        ctx=None,
        entry=entry,
        inputs=["in.wav"],
        params={"notedata": "nd.txt", **_TEXTURE_PARAMS},
        output_name=None,
        timeout_seconds=30.0,
        session=session,
        cdp=env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
        dry_run=True,
    )
    assert ok.errors == []
    assert ok.planned_argv is not None
    assert "data/nd.txt" in ok.planned_argv

    missing = await validate_node(
        ctx=None,
        entry=entry,
        inputs=["in.wav"],
        params={"notedata": "absent.txt", **_TEXTURE_PARAMS},
        output_name=None,
        timeout_seconds=30.0,
        session=session,
        cdp=env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
        dry_run=True,
    )
    assert any(e.type == "param_aux_file_missing" for e in missing.errors)


# ---------------------------------------------------------------------------
# Real CDP: texture simple mode 5 re-verification (gated)
# ---------------------------------------------------------------------------


@pytest.fixture
def real_texture_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    if not (real_cdp_path / "texture").is_file():
        pytest.skip("texture binary not present in CDP_PATH.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    session, _ = sessions.set_active("texture_recuration_v1")
    rng = np.random.default_rng(0)
    sig = (rng.standard_normal(44100 * 2) * 0.2).astype(np.float32)
    sf.write(str(session.inputs_dir / "in.wav"), sig, 44100, subtype="FLOAT")
    data_dir = session.root / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "nd60.txt").write_text("60\n")
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_config,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


@pytest.mark.timeout(60)
async def test_texture_simple_real_cdp_seeded_run(real_texture_env):
    """The re-curated entry against the real binary: aux notedata resolves,
    output is stereo, duration lands inside the honest set_by bounds, and
    the -r seed reproduces the output exactly (fixed-seed determinism)."""
    env = real_texture_env
    params = {
        "notedata": "nd60.txt", "outdur": 5.0, "packing": 0.25,
        "scatter": 0.3, "mindur": 0.2, "maxdur": 0.5, "seed": 5,
    }

    async def run(name: str) -> dict:
        # params is mutated by the engine (aux path resolution) — pass a
        # fresh copy per call like a real MCP client would.
        return await process_impl(
            _FakeCtx(),
            program="texture",
            mode="simple",
            input="in.wav",
            params=dict(params),
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
    assert info.channels == 2  # mono in -> stereo out, every run
    # Honest set_by bounds with maxdur 0.5: observed -1.3%..+1.2% across
    # both curation rounds; assert the generous documented envelope.
    assert 5.0 * 0.95 <= info.duration <= 5.0 + 0.5

    r2 = await run("take2")
    assert r2["status"] == "ok", r2["errors"]
    d1, _ = sf.read(r1["output"])
    d2, _ = sf.read(r2["output"])
    assert d1.shape == d2.shape
    assert np.array_equal(d1, d2), "same seed must reproduce output exactly"


@pytest.mark.timeout(60)
async def test_texture_simple_real_cdp_breakpoint_packing(real_texture_env):
    """packing is breakpoint_capable: a compiled envelope runs clean."""
    env = real_texture_env
    r = await process_impl(
        _FakeCtx(),
        program="texture",
        mode="simple",
        input="in.wav",
        params={
            "notedata": "nd60.txt", "outdur": 5.0,
            "packing": [[0.0, 0.1], [1.0, 0.5]],
            "scatter": 0.3, "mindur": 0.2, "maxdur": 0.5, "seed": 5,
        },
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )
    assert r["status"] == "ok", r["errors"]
    assert sf.info(r["output"]).channels == 2


@pytest.mark.timeout(60)
async def test_texture_simple_real_cdp_outdur_brk_refused(real_texture_env):
    """outdur is curated breakpoint_capable=false — a list value must be
    refused by the engine before CDP ever runs."""
    env = real_texture_env
    r = await process_impl(
        _FakeCtx(),
        program="texture",
        mode="simple",
        input="in.wav",
        params={
            "notedata": "nd60.txt", "outdur": [[0.0, 3.0], [1.0, 8.0]],
            "packing": 0.25, "mindur": 0.2, "maxdur": 0.5,
        },
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )
    assert r["status"] == "failed"
    # The duration pre-flight (step 6.5, set_by outdur can't evaluate a
    # list) or the breakpoint gate (step 8.5, capable=false) fires first
    # depending on ordering — either way the run never reaches CDP.
    types = {e["type"] for e in r["errors"]}
    assert types & {
        "param_breakpoint_not_capable",
        "predicted_duration_evaluation_failed",
    }
