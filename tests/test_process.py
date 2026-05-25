"""Integration tests for the process() tool with PVOC auto-insertion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
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
    (cdp / "pvoc").write_text(
        f"""#!/bin/sh
# argv[1] is "anal" or "synth"; argv[-1] is the output path.
OUTPUT=""
for arg in "$@"; do OUTPUT="$arg"; done
case "$1" in
    anal) exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT" ;;
    synth) exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT" ;;
    *) exit 1 ;;
esac
"""
    )
    (cdp / "pvoc").chmod(0o755)
    monkeypatch.setenv("CDP_MCP_DISABLE_ARCH_X86_64", "1")
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)

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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)

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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)

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


async def test_output_name_honored(mcp_with_process):
    mcp, sessions, tracker, _cdp = mcp_with_process
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
    (session.inputs_dir / "frog.wav").write_bytes(b"\x00" * 2000)
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
