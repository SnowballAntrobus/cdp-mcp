"""Integration tests for the process() tool with PVOC auto-insertion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import process as process_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()

# Map (program, mode, domain) → output file extension. Drives the per-binary
# wrapper script the fixture writes into the fake CDP_PATH.
_PROGRAMS_TIME = {"modify", "extend", "filter"}
_PROGRAMS_SPECTRAL = {"blur", "morph"}


# ---------------------------------------------------------------------------
# Fixture: fake CDP_PATH with multiple binaries that always write output
# ---------------------------------------------------------------------------


def _write_real_wav(path: Path, duration_s: float, sr: int = 44100) -> None:
    """Write a silent wav of the given duration. Header is enough; tests
    of pre-flight need sf.info to read a duration but don't care about
    content."""
    samples = np.zeros(int(duration_s * sr), dtype=np.float32)
    sf.write(str(path), samples, sr)


def _write_wrapper(path: Path, write_flag: str) -> None:
    """Write a shell wrapper that delegates to fake_subprocess.py.

    The wrapper writes its output file via the given flag (`--write-wav`
    or `--write-ana`) at argv's last position — matching CDP's convention
    of "the last argv element is the output filename" for most curated
    programs.
    """
    path.write_text(
        f"""#!/bin/sh
# Find the last argv element that looks like an output path (not a flag).
# Simplest heuristic that matches all curated entries: walk argv until we
# find an arg ending in .wav, .ana, or .pvx — that's the output.
OUTPUT=""
for arg in "$@"; do
    case "$arg" in
        *.wav|*.ana|*.pvx) OUTPUT="$arg" ;;
    esac
done
if [ -z "$OUTPUT" ]; then
    # Fallback: assume last arg is the output.
    for arg in "$@"; do OUTPUT="$arg"; done
fi
exec "{_FAKE_SUBPROCESS}" {write_flag} "$OUTPUT"
"""
    )
    path.chmod(0o755)


@pytest.fixture
def fake_cdp_path(tmp_path, monkeypatch):
    """Tmp CDP_PATH with wrapper scripts for blur/modify/morph/extend/filter/pvoc.

    Each wrapper writes a non-silent output file at the position where CDP
    would. blur/morph produce .ana; modify/extend/filter produce .wav;
    pvoc auto-detects based on its second arg (anal → .ana, synth → .wav).
    """
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    # Time-domain programs write .wav outputs.
    for name in _PROGRAMS_TIME:
        _write_wrapper(cdp / name, "--write-wav")
    # Spectral programs write .ana outputs.
    for name in _PROGRAMS_SPECTRAL:
        _write_wrapper(cdp / name, "--write-ana")
    # pvoc is special — write whichever output extension matches.
    # Find the output path by extension; robust to `-c<N> -o<N>` flags
    # being appended after the positionals (Phase 2 Task 4).
    (cdp / "pvoc").write_text(
        f"""#!/bin/sh
OUTPUT=""
case "$1" in
    anal)
        for arg in "$@"; do case "$arg" in *.ana) OUTPUT="$arg" ;; esac; done
        exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT" ;;
    synth)
        for arg in "$@"; do case "$arg" in *.wav) OUTPUT="$arg" ;; esac; done
        exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT" ;;
    *) exit 1 ;;
esac
"""
    )
    (cdp / "pvoc").chmod(0o755)
    return cdp


@pytest.fixture
def mcp_with_process(fake_cdp_path, tmp_path):
    """FastMCP with process() registered against the fake CDP install."""
    mcp = FastMCP("test-cdp-process")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(
        cdp_path=fake_cdp_path,
        version="fake",
        detected_binaries=sorted(_PROGRAMS_TIME | _PROGRAMS_SPECTRAL | {"pvoc"}),
    )
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    tracker = LatestTracker()
    index = KnowledgeIndex.load()
    process_module.register(
        mcp,
        sessions=sessions,
        knowledge_index=index,
        cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker,
        cache_root=cache_root,
    )
    return mcp, sessions, tracker, fake_cdp_path


async def _call(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Validation failure paths (no subprocess, no graph)
# ---------------------------------------------------------------------------


async def test_not_curated(mcp_with_process):
    mcp, sessions, _tracker, _cdp = mcp_with_process
    sessions.set_active("s1")
    payload = await _call(
        mcp,
        "process",
        {"program": "nonexistent", "mode": "mode", "input": "x.wav"},
    )
    assert payload["status"] == "failed"
    assert any(e["type"] == "not_curated" for e in payload["errors"])


async def test_arity_mismatch(mcp_with_process):
    mcp, sessions, _tracker, _cdp = mcp_with_process
    sessions.set_active("s1")
    # blur expects 1 input but we pass 2.
    payload = await _call(
        mcp,
        "process",
        {"program": "blur", "mode": "blur", "input": ["a.wav", "b.wav"]},
    )
    assert payload["status"] == "failed"
    assert any(e["type"] == "arity_mismatch" for e in payload["errors"])


async def test_param_out_of_range(mcp_with_process):
    mcp, sessions, _tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "x.wav").write_bytes(b"\x00" * 2000)
    # blur.blurring has min=1.0; passing 0.0 should fail validation.
    payload = await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "x.wav", "params": {"blurring": 0.0},
        },
    )
    assert payload["status"] == "failed"
    assert any(e["type"] == "param_out_of_range" for e in payload["errors"])


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_time_op_wav_input_no_pvoc(mcp_with_process):
    """modify.brassage is a time op with .wav input — no PVOC needed."""
    mcp, sessions, tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    payload = await _call(
        mcp,
        "process",
        {
            "program": "modify", "mode": "brassage",
            "input": "frog.wav", "params": {"velocity": 0.5},
        },
    )
    assert payload["status"] == "ok", payload["errors"]
    assert payload["output"] is not None
    assert payload["output"].endswith(".wav")
    # Only one node — the main op (no PVOC inserted).
    assert tracker.latest is not None
    assert tracker.latest.endswith(":n1")


async def test_spectral_op_wav_input_inserts_pvoc(mcp_with_process):
    """blur.blur is a spectral op with .wav input → pvoc anal as n1, blur as n2."""
    mcp, sessions, tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    payload = await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "frog.wav", "params": {"blurring": 10},
        },
    )
    assert payload["status"] == "ok", payload["errors"]
    assert payload["output"].endswith(".ana")
    # tracker points at n2 (the main op).
    assert tracker.latest is not None
    assert tracker.latest.endswith(":n2")
    # Read the graph's node_index — should have n1 (pvoc-anal) and n2 (blur).
    graph_id = tracker.latest.split(":")[0]
    graph_root = session.graphs_dir / graph_id
    index = json.loads((graph_root / "node_index.json").read_text())
    assert set(index.keys()) == {"n1", "n2"}
    assert "pvoc-anal" in index["n1"]
    assert "blur-blur" in index["n2"]


async def test_lineage_main_op_source_node_points_at_pvoc(mcp_with_process):
    mcp, sessions, tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "frog.wav", "params": {"blurring": 10},
        },
    )
    graph_id = tracker.latest.split(":")[0]
    lineage = json.loads(
        (session.graphs_dir / graph_id / "lineage.json").read_text()
    )
    n2 = lineage["nodes"]["n2"]
    assert n2["inputs"][0]["source_node"] == "n1"


async def test_chain_via_latest_inserts_pvoc_synth(mcp_with_process):
    """process #1 produces .ana; process #2 of a time op uses input='latest'
    → engine auto-inserts pvoc synth."""
    mcp, sessions, tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Step 1: blur (spectral) — leaves an .ana behind in latest.
    p1 = await _call(
        mcp,
        "process",
        {"program": "blur", "mode": "blur",
         "input": "frog.wav", "params": {"blurring": 10}},
    )
    assert p1["status"] == "ok"
    latest_after_blur = tracker.latest

    # Step 2: modify.brassage (time domain) with input="latest".
    p2 = await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "latest", "params": {"velocity": 0.5}},
    )
    assert p2["status"] == "ok", p2["errors"]
    # New graph, latest changed.
    assert tracker.latest != latest_after_blur
    graph_id = tracker.latest.split(":")[0]
    index = json.loads(
        (session.graphs_dir / graph_id / "node_index.json").read_text()
    )
    # n1 should be pvoc-synth (converting .ana → .wav), n2 the brassage.
    assert "pvoc-synth" in index["n1"]
    assert "modify-brassage" in index["n2"]


async def test_main_op_failure_leaves_latest_unchanged(mcp_with_process):
    mcp, sessions, tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Pin latest to a known value first via a successful run.
    await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "frog.wav", "params": {"velocity": 0.5}},
    )
    pinned_latest = tracker.latest

    # Now sabotage the modify wrapper to exit 1.
    sabotaged = cdp_path / "modify"
    sabotaged.write_text(
        f"""#!/bin/sh
exec "{_FAKE_SUBPROCESS}" --exit 1
"""
    )
    sabotaged.chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "frog.wav", "params": {"velocity": 0.5}},
    )
    assert p["status"] == "failed"
    assert any(e["type"] == "subprocess_error" for e in p["errors"])
    # latest unchanged.
    assert tracker.latest == pinned_latest


async def test_output_verification_failure(mcp_with_process):
    """CDP exits 0 but writes a silent output → output_verification_failed."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Replace modify with a wrapper that writes a SILENT wav.
    (cdp_path / "modify").write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in *.wav|*.ana) OUTPUT="$arg" ;; esac
done
exec "{_FAKE_SUBPROCESS}" --write-wav-silent "$OUTPUT"
"""
    )
    (cdp_path / "modify").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "frog.wav", "params": {"velocity": 0.5}},
    )
    assert p["status"] == "failed"
    assert any(e["type"] == "output_verification_failed" for e in p["errors"])


# ---------------------------------------------------------------------------
# Stderr pattern parsing — process() surfaces structured ErrorEntry items
# alongside the generic timeout / subprocess_error / output_verification_failed.
# ---------------------------------------------------------------------------


async def test_process_output_exists_pattern(mcp_with_process):
    """Refuse-to-clobber stderr ('cannot create output') surfaces as a
    structured output_exists ErrorEntry alongside the generic
    subprocess_error (additive contract)."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Wrapper that emits the canonical stderr and exits 255 — mirrors
    # what CDP r8 pvoc synth does when its output already exists.
    (cdp_path / "modify").write_text(
        """#!/bin/sh
echo "ERROR: cannot create output file foo" >&2
exit 255
"""
    )
    (cdp_path / "modify").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "frog.wav", "params": {"velocity": 0.5}},
    )
    assert p["status"] == "failed"
    types = {e["type"] for e in p["errors"]}
    assert "output_exists" in types
    # Generic subprocess_error coexists (additive, no dedup in Phase 1b).
    assert "subprocess_error" in types


async def test_process_silent_output_pattern_via_silent_wav(mcp_with_process):
    """A wrapper that exits 0 and writes a silent wav surfaces both the
    structured silent_output AND the generic output_verification_failed
    (additive contract)."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    (cdp_path / "modify").write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in *.wav|*.ana) OUTPUT="$arg" ;; esac
done
exec "{_FAKE_SUBPROCESS}" --cdp-silent-output "$OUTPUT"
"""
    )
    (cdp_path / "modify").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "frog.wav", "params": {"velocity": 0.5}},
    )
    assert p["status"] == "failed"
    types = {e["type"] for e in p["errors"]}
    assert "silent_output" in types
    assert "output_verification_failed" in types


async def test_process_usage_banner_pattern(mcp_with_process):
    """A wrapper that prints 'Usage:' and exits without writing the
    output surfaces a structured usage_banner_returned ErrorEntry."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Wrapper prints usage and exits 1. Crucially: does NOT write the
    # output file, so usage_banner_returned's missing-output precondition
    # is satisfied.
    (cdp_path / "modify").write_text(
        """#!/bin/sh
echo "Usage: modify brassage mode infile outfile velocity" >&2
exit 1
"""
    )
    (cdp_path / "modify").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "frog.wav", "params": {"velocity": 0.5}},
    )
    assert p["status"] == "failed"
    types = {e["type"] for e in p["errors"]}
    assert "usage_banner_returned" in types


async def test_output_name_honored(mcp_with_process):
    mcp, sessions, tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    p = await _call(
        mcp,
        "process",
        {
            "program": "modify", "mode": "brassage",
            "input": "frog.wav", "params": {"velocity": 0.5},
            "output_name": "stretched.wav",
        },
    )
    assert p["status"] == "ok"
    assert p["output"].endswith("/stretched.wav")


async def test_output_name_extension_appended_when_missing(mcp_with_process):
    """Regression: extensionless output_name used to mismatch what CDP wrote.

    CDP appends .wav itself when the output argv lacks one (brassage at
    least), so the verifier opened the bare path and reported a phantom
    output_verification_failed even though CDP succeeded. Fix normalizes
    the name up-front so argv and verifier agree.
    """
    mcp, sessions, _tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    p = await _call(
        mcp,
        "process",
        {
            "program": "modify", "mode": "brassage",
            "input": "frog.wav", "params": {"velocity": 0.5},
            "output_name": "capm_brassage_v3",
        },
    )
    assert p["status"] == "ok"
    assert p["output"].endswith("/capm_brassage_v3.wav")


async def test_output_name_extension_preserved_no_double_append(mcp_with_process):
    """Explicit .wav stays single — no foo.wav.wav nonsense."""
    mcp, sessions, _tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    p = await _call(
        mcp,
        "process",
        {
            "program": "modify", "mode": "brassage",
            "input": "frog.wav", "params": {"velocity": 0.5},
            "output_name": "stretched.wav",
        },
    )
    assert p["status"] == "ok"
    assert p["output"].endswith("/stretched.wav")
    assert not p["output"].endswith(".wav.wav")


async def test_output_name_wrong_extension_rejected(mcp_with_process):
    """Mismatched audio extension → structured invalid_output_name error."""
    mcp, sessions, _tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    p = await _call(
        mcp,
        "process",
        {
            "program": "modify", "mode": "brassage",
            "input": "frog.wav", "params": {"velocity": 0.5},
            "output_name": "x.aiff",
        },
    )
    assert p["status"] == "failed"
    assert len(p["errors"]) == 1
    assert p["errors"][0]["type"] == "invalid_output_name"
    # Fix string should name the expected extension so the LLM can self-correct.
    assert ".wav" in p["errors"][0]["fix"]


async def test_output_name_spectral_appends_ana(mcp_with_process):
    """Spectral program → missing extension gets .ana, not .wav."""
    mcp, sessions, _tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    p = await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "frog.wav", "params": {"blurring": 10},
            "output_name": "myblur",
        },
    )
    assert p["status"] == "ok"
    assert p["output"].endswith("/myblur.ana")


async def test_graph_json_records_user_intent(mcp_with_process):
    mcp, sessions, tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)
    await _call(
        mcp,
        "process",
        {"program": "blur", "mode": "blur",
         "input": "frog.wav", "params": {"blurring": 10}},
    )
    graph_id = tracker.latest.split(":")[0]
    graph_json = json.loads(
        (session.graphs_dir / graph_id / "graph.json").read_text()
    )
    assert graph_json["program"] == "blur"
    assert graph_json["mode"] == "blur"
    # Original ref, not the resolved path.
    assert graph_json["input"] == "frog.wav"
    assert graph_json["params"] == {"blurring": 10}
    assert graph_json["output_name"] is None
    assert "issued_at" in graph_json


# ---------------------------------------------------------------------------
# Pre-flight duration prediction (Task 6) — process() rejects runaway
# durations BEFORE spawning CDP. Complements the reactive watchdog (Task 7).
# ---------------------------------------------------------------------------


async def test_process_preflight_rejects_runaway_duration(mcp_with_process):
    """A modify brassage call with extremely low velocity predicts a huge
    output (indur / velocity → thousands of seconds). Pre-flight catches
    this before CDP spawns — no graph dir created."""
    mcp, sessions, _tracker, _cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    # Real wav so sf.info reads a 2.0s duration.
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    p = await _call(
        mcp,
        "process",
        {
            "program": "modify", "mode": "brassage",
            "input": "frog.wav",
            "params": {"velocity": 0.001},  # 2 / 0.001 = 2000s > 300s
        },
    )
    assert p["status"] == "failed"
    types = {e["type"] for e in p["errors"]}
    assert "predicted_duration_exceeds_cap" in types
    # No graph dir created — failure happens before step 7.
    assert p["context"]["active_graph"] is None


# ---------------------------------------------------------------------------
# Disk watchdog (Task 7) — process() surfaces size_cap_exceeded in the
# envelope and precedence-orders it ahead of the generic subprocess_error.
# ---------------------------------------------------------------------------


async def test_process_envelope_on_watchdog_kill(mcp_with_process, monkeypatch):
    """A watchdog kill produces a size_cap_exceeded ErrorEntry in the
    envelope; the generic subprocess_error is NOT additionally surfaced
    (precedence rule).

    The wrapper writes a ~444-byte wav up-front then sleeps so the
    watchdog's 1-second poll has time to fire. Cap is 100 bytes."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Patch BOTH the source module and the importing module — process.py
    # captures the constant by name at import time, so patching only
    # the source doesn't update its bound copy.
    monkeypatch.setattr("cdp_mcp.limits.OUTPUT_FILE_SIZE_CAP_BYTES", 100)
    monkeypatch.setattr(
        "cdp_mcp.tools.process.OUTPUT_FILE_SIZE_CAP_BYTES", 100
    )

    # Wrapper: write the wav immediately (puts the file over the 100-byte
    # cap), then sleep so the watchdog (1s production poll) has time to
    # fire. Pre-flight for modify brassage with velocity=0.5 predicts 4s
    # — well under the duration cap; only the size cap should fire.
    (cdp_path / "modify").write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in *.wav|*.ana) OUTPUT="$arg" ;; esac
done
exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT" --sleep 3
"""
    )
    (cdp_path / "modify").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {"program": "modify", "mode": "brassage",
         "input": "frog.wav", "params": {"velocity": 0.5}},
    )
    assert p["status"] == "failed"
    types = {e["type"] for e in p["errors"]}
    assert "size_cap_exceeded" in types
    # Precedence rule: subprocess_error is NOT additionally surfaced.
    assert "subprocess_error" not in types


# ---------------------------------------------------------------------------
# Polymorphic parameters + breakpoint compilation (Task 8)
# ---------------------------------------------------------------------------


async def test_process_breakpoint_compilation_happy_path(mcp_with_process):
    """blur_blur with a breakpoint list on `blurring` compiles to a
    .brk file in envelopes/. The fake `blur` wrapper writes a .ana so
    process() can complete; we inspect the compiled file separately."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Wrapper: just write a fake .ana so verification + lineage succeed.
    (cdp_path / "blur").write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in *.ana) OUTPUT="$arg" ;; esac
done
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
    )
    (cdp_path / "blur").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "frog.wav",
            "params": {"blurring": [[0.0, 5], [1.0, 50]]},
        },
    )
    assert p["status"] == "ok", p["errors"]
    brk_files = list(session.envelopes_dir.glob("blurring_*.brk"))
    assert len(brk_files) == 1
    contents = brk_files[0].read_text()
    # Expect three points: (0, 5), (2, 50) from compiling [0.0, 5] and
    # [1.0, 50] against 2s duration. The (1.0, 50) at t=2.0 already
    # reaches source_duration so no auto-append is needed.
    lines = [line for line in contents.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0].split() == ["0", "5"]
    assert lines[1].split() == ["2", "50"]


async def test_process_breakpoint_not_capable_rejected(mcp_with_process):
    """modify brassage's velocity is not breakpoint_capable → list
    value rejected with a structured error before CDP spawns."""
    mcp, sessions, _tracker, _cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    p = await _call(
        mcp,
        "process",
        {
            "program": "modify", "mode": "brassage",
            "input": "frog.wav",
            "params": {"velocity": [[0.0, 0.5], [1.0, 2.0]]},
        },
    )
    assert p["status"] == "failed"
    types = {e["type"] for e in p["errors"]}
    assert "param_breakpoint_not_capable" in types


async def test_process_breakpoint_preexisting_brk_path(mcp_with_process):
    """User pre-writes a .brk file under envelopes/ and references it
    by relative path. Compiler hashes + records source_kind."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    # Pre-write the user's .brk.
    (session.envelopes_dir / "my_curve.brk").write_text("0 5\n1 25\n2 50\n")

    (cdp_path / "blur").write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in *.ana) OUTPUT="$arg" ;; esac
done
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
    )
    (cdp_path / "blur").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "frog.wav",
            "params": {"blurring": "envelopes/my_curve.brk"},
        },
    )
    assert p["status"] == "ok", p["errors"]
    # Inspect lineage for source_kind == "preexisting_brk".
    graph_id = p["context"]["active_graph"]
    doc = json.loads(
        (session.graphs_dir / graph_id / "lineage.json").read_text()
    )
    # Find the main op node by program name in argv[0] (resolved binary
    # path). Phase 2 Task 4 added `-c<N> -o<N>` flags to the PVOC anal
    # argv, which shifted argv[-3] from "1" to the .ana output path —
    # the substring `"blur" in argv[-3]` then started ambiguously
    # matching the auto-inserted PVOC node too (its output lives under
    # a "blur-blur" graph slug). argv[0]'s basename is the safest
    # discriminator.
    main_node = next(
        (n for n in doc["nodes"].values() if n["argv"][0].endswith("/blur")),
        None,
    )
    assert main_node is not None
    brk_record = main_node["compiled_breakpoints"]["blurring"]
    assert brk_record["source_kind"] == "preexisting_brk"
    assert brk_record["sha256"] != ""


async def test_process_breakpoint_compilation_records_sha_in_lineage(
    mcp_with_process,
):
    """Every compiled .brk records its content sha in
    NodeLineage.compiled_breakpoints — what Task 12's cache key will
    consume."""
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")
    _write_real_wav(session.inputs_dir / "frog.wav", duration_s=2.0)

    (cdp_path / "blur").write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in *.ana) OUTPUT="$arg" ;; esac
done
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
    )
    (cdp_path / "blur").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "frog.wav",
            "params": {"blurring": [[0.0, 5], [1.0, 50]]},
        },
    )
    assert p["status"] == "ok"
    graph_id = p["context"]["active_graph"]
    doc = json.loads(
        (session.graphs_dir / graph_id / "lineage.json").read_text()
    )
    # The main node (blur) should have compiled_breakpoints recorded.
    # Find the main op node by program name in argv[0] (resolved binary
    # path). Phase 2 Task 4 added `-c<N> -o<N>` flags to the PVOC anal
    # argv, which shifted argv[-3] from "1" to the .ana output path —
    # the substring `"blur" in argv[-3]` then started ambiguously
    # matching the auto-inserted PVOC node too (its output lives under
    # a "blur-blur" graph slug). argv[0]'s basename is the safest
    # discriminator.
    main_node = next(
        (n for n in doc["nodes"].values() if n["argv"][0].endswith("/blur")),
        None,
    )
    assert main_node is not None
    bp = main_node["compiled_breakpoints"]
    assert "blurring" in bp
    assert bp["blurring"]["sha256"] != ""
    # PVOC was auto-inserted (.wav → .ana for blur), so source_kind is
    # "pvoc_lineage" — the breakpoint compiler looked up the just-
    # inserted PVOC node's source_wav_duration_s.
    assert bp["blurring"]["source_kind"] == "pvoc_lineage"
    assert bp["blurring"]["source_duration_s"] == pytest.approx(2.0, abs=0.01)


async def test_process_breakpoint_source_kind_ana_sfprops_fallback(
    mcp_with_process,
):
    """Pre-converted .ana in inputs/ → no same-graph PVOC lineage →
    _resolve_source_duration falls back to sfprops via read_ana_duration.

    Asserts the lineage record carries source_kind="ana_sfprops" and
    the duration matches the fake sfprops output. Phase 2 Task 2.
    """
    mcp, sessions, _tracker, cdp_path = mcp_with_process
    session, _ = sessions.set_active("s1")

    # Stub .ana input — bytes don't matter, just that it has the .ana suffix
    # so PVOC anal isn't auto-inserted (blur is spectral, input is already
    # spectral, so the auto-insert is skipped and pvoc_source_nodes[0] is None).
    (session.inputs_dir / "frog.ana").write_bytes(b"\xff\x00" * 1024)

    # Install fake sfprops that reports a known duration. Generic test util,
    # not a CDP-quirk flag.
    (cdp_path / "sfprops").write_text(
        f"""#!/usr/bin/env bash
exec "{_FAKE_SUBPROCESS}" --print-ana-duration "7.5"
"""
    )
    (cdp_path / "sfprops").chmod(0o755)

    p = await _call(
        mcp,
        "process",
        {
            "program": "blur", "mode": "blur",
            "input": "frog.ana",
            # Relative-time breakpoints — require source_duration_s to compile.
            "params": {"blurring": [[0.0, 5], [1.0, 50]]},
        },
    )
    assert p["status"] == "ok", p["errors"]

    graph_id = p["context"]["active_graph"]
    doc = json.loads(
        (session.graphs_dir / graph_id / "lineage.json").read_text()
    )
    # Pre-converted .ana → no PVOC auto-insert → blur is the only node.
    assert list(doc["nodes"].keys()) == ["n1"]
    bp_record = doc["nodes"]["n1"]["compiled_breakpoints"]["blurring"]
    assert bp_record["source_kind"] == "ana_sfprops"
    assert bp_record["source_duration_s"] == pytest.approx(7.5, abs=0.001)

