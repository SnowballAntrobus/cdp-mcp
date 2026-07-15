"""Phase 5 wave 2a: data (non-audio) output support.

The schema gap that dropped ``envel extract`` and ``formants get`` in
tranche 5 (docs/curation/tranche5_mix_env_findings.json, dropped[1] and
dropped[2]): both emit RIFF-container DATA files that CDP writes
verbatim under any name. The old engine named every output ``.wav`` /
``.ana`` and ran audio verification on it — an envel extract output is a
sample-rate-57 pseudo-wav that PASSES an RMS check, and a formants get
output named .ana misreports 107.85 s via sfprops. Poison, not failure.

Coverage:

1. ``verify_output`` — a valid data file passes on exists + non-empty
   alone, is NEVER fed to the wav RMS/silence decoder, and an empty
   data file fails.
2. Output naming — data-output entries derive the extension from
   ``output_format`` (.evl/.for), extensionless output_names get it
   appended, and a mismatched audio extension refuses.
3. Duration pre-flight — skipped entirely for data-output entries.
4. End-to-end via ``process_impl`` with a fake binary.

Plus real-CDP-gated runs: envel extract emits a healthy .evl, and the
formants get → formants put chain (the reason get/put ship together)
runs through the engine end to end.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp import graph as graph_module
from cdp_mcp.config import CDPConfig, detect_cdp
from cdp_mcp.duration_preflight import check_duration_preflight
from cdp_mcp.graph import LatestTracker, verify_output
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.node_validation import validate_node
from cdp_mcp.tools.process import process_impl

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


# ---------------------------------------------------------------------------
# verify_output: data files are size-checked, never RMS-checked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", [".for", ".evl", ".txt"])
def test_verify_output_accepts_valid_data_file(tmp_path, suffix):
    p = tmp_path / f"out{suffix}"
    p.write_bytes(b"\x01\x02" * 1024)
    v = verify_output(p)
    assert v.ok, v.errors
    assert v.rms_dbfs is None
    assert v.size_bytes == 2048


def test_verify_output_accepts_tiny_data_file(tmp_path):
    """A one-window envelope can be a handful of bytes — 'non-empty' is
    the whole size contract for data outputs (audio keeps its 100-byte
    header floor)."""
    p = tmp_path / "tiny.evl"
    p.write_bytes(b"\x00\x00\x80\x3f")  # one float32
    v = verify_output(p)
    assert v.ok, v.errors


def test_verify_output_rejects_empty_data_file(tmp_path):
    p = tmp_path / "empty.for"
    p.write_bytes(b"")
    v = verify_output(p)
    assert not v.ok
    assert v.exists


def test_verify_output_never_rms_checks_data_files(tmp_path, monkeypatch):
    """The poison case: envel extract's .evl is a RIFF/WAVE container
    soundfile would happily decode as sr-57 audio. The verifier must not
    even attempt it — trip a mine if the RMS path is entered."""
    def _boom(*a, **kw):
        raise AssertionError("data output reached the wav RMS decoder")

    monkeypatch.setattr(graph_module, "_compute_wav_rms_dbfs", _boom)
    # A real-shaped pseudo-wav payload, named as data: write actual RIFF
    # bytes so this test fails loudly if a future change routes data
    # files by content sniffing instead of extension.
    p = tmp_path / "env.evl"
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(57)
        w.writeframes(b"\x00\x01" * 115)
    p.write_bytes(buf.getvalue())
    v = verify_output(p)
    assert v.ok, v.errors
    assert v.rms_dbfs is None
    # .wav still goes through the decoder (mine still armed).
    wav = tmp_path / "x.wav"
    wav.write_bytes(buf.getvalue())
    with pytest.raises(AssertionError, match="RMS decoder"):
        verify_output(wav)


# ---------------------------------------------------------------------------
# Output naming + pre-flight skip (dry-run validate_node, no subprocess)
# ---------------------------------------------------------------------------


@pytest.fixture
def data_env(tmp_path):
    cdp_dir = (tmp_path / "cdp").resolve()
    cdp_dir.mkdir()
    for name, ext in (("envel", ".evl"), ("formants", ".for")):
        # Fake binary writes ~2 KB of bytes at the data-output argv slot.
        (cdp_dir / name).write_text(
            f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in
        *{ext}) OUTPUT="$arg" ;;
    esac
done
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
        )
        (cdp_dir / name).chmod(0o755)
    cdp_cfg = CDPConfig(
        cdp_path=cdp_dir, version="fake",
        detected_binaries=["envel", "formants"],
    )
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    session, _ = sessions.set_active("dataout_v1")
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


async def _dry_run(env, program, mode, params, output_name=None):
    return await validate_node(
        ctx=None,
        entry=env["knowledge"].get(program, mode),
        inputs=["in.wav"],
        params=params,
        output_name=output_name,
        timeout_seconds=30.0,
        session=env["session"],
        cdp=env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
        dry_run=True,
    )


async def test_data_output_named_with_declared_extension(data_env):
    vr = await _dry_run(data_env, "envel", "extract", {"wsize": 20.0})
    assert vr.errors == []
    assert vr.output_path is not None
    assert vr.output_path.suffix == ".evl"


async def test_data_output_extensionless_name_gets_extension(data_env):
    vr = await _dry_run(
        data_env, "envel", "extract", {"wsize": 20.0}, output_name="shape"
    )
    assert vr.errors == []
    assert vr.out_filename == "shape.evl"


async def test_data_output_wav_name_refused(data_env):
    """A .wav-named envel extract output is exactly the tranche-5 poison
    — the namer must refuse, not silently rewrite."""
    vr = await _dry_run(
        data_env, "envel", "extract", {"wsize": 20.0}, output_name="x.wav"
    )
    assert any(e.type == "invalid_output_name" for e in vr.errors)


async def test_data_output_preflight_skips(data_env):
    entry = data_env["knowledge"].get("formants", "get")
    errors, predicted = await check_duration_preflight(
        entry=entry,
        params={"fbands": 8.0},
        resolved_inputs=[Path("whatever.ana")],
    )
    assert errors == []
    assert predicted is None


# ---------------------------------------------------------------------------
# End-to-end via process_impl (fake CDP)
# ---------------------------------------------------------------------------


async def test_envel_extract_end_to_end_fake_cdp(data_env):
    env = data_env
    r = await process_impl(
        _FakeCtx(),
        program="envel",
        mode="extract",
        input="in.wav",
        params={"wsize": 20.0},
        sessions=env["sessions"],
        knowledge_index=env["knowledge"],
        cdp_config_provider=lambda: env["cdp_cfg"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
    )
    assert r["status"] == "ok", r["errors"]
    out = Path(r["output"])
    assert out.suffix == ".evl"
    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# Real CDP (gated): envel extract .evl + the formants get → put chain
# ---------------------------------------------------------------------------


@pytest.fixture
def real_data_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    for binary in ("envel", "formants", "pvoc"):
        if not (real_cdp_path / binary).is_file():
            pytest.skip(f"{binary} binary not present in CDP_PATH.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    session, _ = sessions.set_active("dataout_real_v1")
    sr = 44100
    rng = np.random.default_rng(0)
    sig = (rng.standard_normal(sr * 2) * 0.2).astype(np.float32)
    t = np.linspace(0, 2 * np.pi, len(sig), dtype=np.float32)
    sig *= 0.6 + 0.4 * np.sin(1.5 * t)  # give the envelope something to track
    sf.write(str(session.inputs_dir / "in.wav"), sig, sr, subtype="PCM_16")
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


@pytest.mark.timeout(60)
async def test_envel_extract_real_cdp(real_data_env):
    """The curated entry against the real binary: output is a non-empty
    .evl whose payload is a plausible per-window envelope (values in
    [0, 1], more than a handful of windows for 2 s at wsize 20)."""
    env = real_data_env
    r = await _run_real(env, "envel", "extract", "in.wav", {"wsize": 20.0})
    assert r["status"] == "ok", r["errors"]
    out = Path(r["output"])
    assert out.suffix == ".evl"
    assert out.stat().st_size > 0
    # The .evl is a RIFF container; read its data chunk floats directly.
    import struct
    b = out.read_bytes()
    i = 12
    data = None
    while i < len(b):
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"data":
            data = b[i + 8:i + 8 + sz]
            break
        i += 8 + sz + (sz & 1)
    assert data is not None
    env_vals = np.frombuffer(data, dtype="<f4")
    assert len(env_vals) > 50  # ~115 windows for 2 s at wsize 20
    assert float(env_vals.min()) >= 0.0
    assert float(env_vals.max()) <= 1.0


@pytest.mark.timeout(120)
async def test_formants_get_put_chain_real_cdp(real_data_env):
    """Extract a .for with formants get, then impose it with formants put
    (pre_output aux slot) — the two-entry workflow that motivated both
    engine gaps, end to end through process()."""
    env = real_data_env
    session = env["session"]

    r_get = await _run_real(env, "formants", "get", "in.wav", {"fbands": 8.0})
    assert r_get["status"] == "ok", r_get["errors"]
    for_path = Path(r_get["output"])
    assert for_path.suffix == ".for"
    assert for_path.stat().st_size > 0

    for_rel = str(for_path.relative_to(session.root))
    r_put = await _run_real(
        env, "formants", "put", "in.wav",
        {"fmntfile": for_rel, "gain": 0.5},
    )
    assert r_put["status"] == "ok", r_put["errors"]
    out = Path(r_put["output"])
    assert out.suffix == ".ana"
    assert out.stat().st_size > 1000
