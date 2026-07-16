"""Phase 6 tranche 24: the ``free_string`` parameter type.

The schema gap that dropped ``blur shuffle`` at its tranche-10a
spot-check and ``distort shuffle`` in tranche 16: both take a REQUIRED
positional domain-image map (``"ab-abab"``) parsed straight from argv
(``cdp2k/tklib3.c:646 read_shuffle_data`` — no file fallback), and
``validate_params._check_type`` accepted strings only for ``.brk``
paths and ``aux_file`` params.

Coverage:

1. ``ParameterSpec`` — the ``pattern`` field is free_string-only and
   must compile (load-time curator errors).
2. ``validate_params`` — free_string accepts plain strings, gates them
   through ``pattern`` (``re.fullmatch``), refuses ``.brk`` names (the
   breakpoint compiler's string routing must never see one), refuses
   non-strings, and the missing-required fix says "string" not
   "numeric".
3. ``build_cdp_argv`` — the value renders verbatim as a positional in
   declaration order; curated defaults on sibling positionals render.
4. End-to-end via ``process_impl`` with a fake binary.
5. Real-CDP-gated: blur shuffle (duration rule ~imgcnt/dmncnt) and
   distort shuffle through the engine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from pydantic import ValidationError

from cdp_mcp.config import CDPConfig, detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.processing import build_cdp_argv, validate_params
from cdp_mcp.schema import KnowledgeEntry, ParameterSpec
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.process import process_impl

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


def _entry(parameters: dict[str, ParameterSpec]) -> KnowledgeEntry:
    return KnowledgeEntry(
        program="blur",
        mode="shuffle",
        category="spectral-time",
        domain="spectral",
        input_arity=1,
        channel_constraint="mono",
        input_format=".ana",
        output_format=".ana",
        duration_model={"kind": "expression", "expr": "domain_image"},
        description="x",
        musical_use="x",
        parameters=parameters,
    )


_MAP_SPEC = ParameterSpec(type="free_string", pattern="^[a-zA-Z]+-[a-zA-Z]+$")


# ---------------------------------------------------------------------------
# 1. Schema: pattern is free_string-only and must compile
# ---------------------------------------------------------------------------


def test_pattern_on_non_free_string_rejected():
    with pytest.raises(ValidationError, match="requires type 'free_string'"):
        ParameterSpec(type="float", pattern="^[a-z]+$")


def test_pattern_must_compile():
    with pytest.raises(ValidationError, match="not a valid regex"):
        ParameterSpec(type="free_string", pattern="([unclosed")


def test_free_string_without_pattern_valid():
    spec = ParameterSpec(type="free_string")
    assert spec.pattern is None


# ---------------------------------------------------------------------------
# 2. validate_params
# ---------------------------------------------------------------------------


def test_free_string_accepts_matching_value():
    entry = _entry({"domain_image": _MAP_SPEC})
    errors, warnings = validate_params(entry, {"domain_image": "ab-abab"})
    assert errors == []
    assert warnings == []


def test_free_string_pattern_mismatch_structured():
    entry = _entry({"domain_image": _MAP_SPEC})
    errors, _ = validate_params(entry, {"domain_image": "abab"})
    assert [e.type for e in errors] == ["param_pattern_mismatch"]
    assert "abab" in errors[0].message
    assert "^[a-zA-Z]+-[a-zA-Z]+$" in errors[0].message


def test_free_string_without_pattern_accepts_any_string():
    entry = _entry({"code": ParameterSpec(type="free_string")})
    errors, _ = validate_params(entry, {"code": "whatever-goes 123"})
    assert errors == []


def test_free_string_rejects_brk_suffix():
    """A .brk-named value would be intercepted by the breakpoint
    compiler's string routing in validate_node step 8.5 — refuse at
    type-check time instead."""
    entry = _entry({"code": ParameterSpec(type="free_string")})
    errors, _ = validate_params(entry, {"code": "map.brk"})
    assert [e.type for e in errors] == ["param_type"]
    assert ".brk" in errors[0].message


def test_free_string_rejects_non_string():
    entry = _entry({"domain_image": _MAP_SPEC})
    for bad in (3, 2.5, True, [["ab", 1]], None):
        errors, _ = validate_params(entry, {"domain_image": bad})
        assert errors, f"value {bad!r} should be rejected"
        assert errors[0].type == "param_type"


def test_missing_required_free_string_hint_says_string():
    entry = _entry({"domain_image": _MAP_SPEC})
    errors, _ = validate_params(entry, {})
    assert [e.type for e in errors] == ["missing_parameter"]
    assert "string" in errors[0].fix
    assert "numeric" not in errors[0].fix
    assert "^[a-zA-Z]+-[a-zA-Z]+$" in errors[0].fix


# ---------------------------------------------------------------------------
# 3. build_cdp_argv
# ---------------------------------------------------------------------------


def test_free_string_renders_verbatim_positional(tmp_path):
    entry = _entry({
        "domain_image": _MAP_SPEC,
        "grpsize": ParameterSpec(type="int", min=1, max=32767, default=1),
    })
    argv = build_cdp_argv(
        entry,
        [tmp_path / "in.ana"],
        tmp_path / "out.ana",
        {"domain_image": "abc-cba"},
        cwd=tmp_path,
    )
    # blur shuffle in.ana out.ana abc-cba 1 — map verbatim, default
    # grpsize rendered, declaration order after the output slot.
    assert argv == ["blur", "shuffle", "in.ana", "out.ana", "abc-cba", "1"]


def test_free_string_never_numeric_reformatted(tmp_path):
    """A numeric-looking map must not round-trip through float
    formatting (declared_type routing in _format_value)."""
    entry = _entry({"code": ParameterSpec(type="free_string")})
    argv = build_cdp_argv(
        entry, [tmp_path / "in.ana"], tmp_path / "out.ana",
        {"code": "0001"}, cwd=tmp_path,
    )
    assert argv[-1] == "0001"


# ---------------------------------------------------------------------------
# 4. Curated entries load with the new type
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_index():
    return KnowledgeIndex.load()


@pytest.mark.parametrize("program", ["blur", "distort"])
def test_shuffle_entries_curated(real_index, program):
    entry = real_index.get(program, "shuffle")
    assert entry is not None
    spec = entry.parameters["domain_image"]
    assert spec.type == "free_string"
    assert spec.pattern is not None
    assert spec.flag is None  # positional
    assert spec.default is None  # required


# ---------------------------------------------------------------------------
# 5. End-to-end via process_impl (fake CDP)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_env(tmp_path):
    cdp_dir = (tmp_path / "cdp").resolve()
    cdp_dir.mkdir()
    # Fake blur: writes ~2 KB at the SECOND .ana argv slot (the output;
    # argv is `blur shuffle in.ana out.ana <map> <grpsize>`).
    (cdp_dir / "blur").write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in
        *.ana) OUTPUT="$arg" ;;
    esac
done
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
    )
    (cdp_dir / "blur").chmod(0o755)
    cdp_cfg = CDPConfig(
        cdp_path=cdp_dir, version="fake", detected_binaries=["blur"],
    )
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    session, _ = sessions.set_active("freestr_v1")
    # Pre-converted .ana input: domain matches (no auto-PVOC needed) and
    # the skip-sentinel duration model means no duration probe either.
    (session.inputs_dir / "in.ana").write_bytes(b"\x00" * 4096)
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_cfg,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


async def _run(env, params) -> dict:
    return await process_impl(
        _FakeCtx(),
        program="blur",
        mode="shuffle",
        input="in.ana",
        params=params,
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )


async def test_blur_shuffle_end_to_end_fake_cdp(fake_env):
    r = await _run(fake_env, {"domain_image": "ab-abab", "grpsize": 2})
    assert r["status"] == "ok", r["errors"]
    argv = None
    lineage = Path(r["output"]).parent / "lineage.json"
    import json
    nodes = json.loads(lineage.read_text())["nodes"]
    argv = nodes[max(nodes)]["argv"]
    assert argv[-2:] == ["ab-abab", "2"]


async def test_blur_shuffle_pattern_gate_fake_cdp(fake_env):
    r = await _run(fake_env, {"domain_image": "abab"})
    assert r["status"] == "failed"
    assert any(e["type"] == "param_pattern_mismatch" for e in r["errors"])


async def test_blur_shuffle_missing_map_fake_cdp(fake_env):
    r = await _run(fake_env, {})
    assert r["status"] == "failed"
    assert any(e["type"] == "missing_parameter" for e in r["errors"])


# ---------------------------------------------------------------------------
# 6. Real CDP (gated)
# ---------------------------------------------------------------------------


@pytest.fixture
def real_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    for binary in ("blur", "distort", "pvoc"):
        if not (real_cdp_path / binary).is_file():
            pytest.skip(f"{binary} binary not present in CDP_PATH.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    session, _ = sessions.set_active("freestr_real_v1")
    sr = 44100
    t = np.arange(sr * 2, dtype=np.float64) / sr
    sig = np.zeros_like(t)
    for h in range(1, 9):
        sig += (1.0 / h ** 1.2) * np.sin(2 * np.pi * 220.0 * h * t)
    sig *= 0.3
    ramp = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.03)
    sf.write(
        str(session.inputs_dir / "tone.wav"),
        (sig * ramp).astype(np.float32), sr,
    )
    return {
        "sessions": sessions,
        "session": session,
        "cdp_cfg": cdp_config,
        "cache_root": cache_root,
        "tracker": LatestTracker(),
        "knowledge": KnowledgeIndex.load(),
    }


async def _run_real(env, program, mode, input, params) -> dict:
    return await process_impl(
        _FakeCtx(),
        program=program,
        mode=mode,
        input=input,
        params=params,
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )


@pytest.mark.timeout(120)
async def test_blur_shuffle_real_cdp(real_env):
    """'ab-abab' echoes each window pair: output windows ~2x input
    (exact rule: 1 + floor((n-1)/2)*4). Verified by resynthesizing and
    comparing durations."""
    env = real_env
    r = await _run_real(
        env, "blur", "shuffle", "tone.wav",
        {"domain_image": "ab-abab", "grpsize": 1},
    )
    assert r["status"] == "ok", r["errors"]
    out = Path(r["output"])
    assert out.suffix == ".ana"
    wav = out.parent / "resynth_check.wav"
    p = subprocess.run(
        [str(env["cdp_cfg"].cdp_path / "pvoc"), "synth", str(out), str(wav)],
        capture_output=True, cwd=env["session"].root, timeout=60,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    ratio = sf.info(str(wav)).duration / 2.0
    assert 1.9 < ratio < 2.1, f"expected ~2x duration, got {ratio:.3f}x"


@pytest.mark.timeout(60)
async def test_blur_shuffle_bad_map_real_cdp(real_env):
    """A pattern-legal but CDP-invalid map ('ab-abc': image symbol not
    in domain) passes the engine gate and fails at CDP with exit 255 —
    the verbatim refusal surfaces in the envelope."""
    env = real_env
    r = await _run_real(
        env, "blur", "shuffle", "tone.wav",
        {"domain_image": "ab-abc", "grpsize": 1},
    )
    assert r["status"] == "failed"
    assert r["exit_code"] not in (0, None)


@pytest.mark.timeout(60)
async def test_distort_shuffle_real_cdp(real_env):
    """Time-domain twin: 2.0 s 'ab-abab' → ~2x minus the trailing
    incomplete wavecycle block (3.9909 on the tranche-16 tone probe)."""
    env = real_env
    r = await _run_real(
        env, "distort", "shuffle", "tone.wav", {"domain_image": "ab-abab"},
    )
    assert r["status"] == "ok", r["errors"]
    out = Path(r["output"])
    assert out.suffix == ".wav"
    dur = sf.info(str(out)).duration
    assert 3.8 < dur < 4.05, f"expected ~3.99 s, got {dur:.4f}"
