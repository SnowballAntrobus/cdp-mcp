"""Tests for batch() — one graph directory, atomic context event,
latest_batch[i] addressing, validation short-circuit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import (
    LatestTracker,
    ReferenceResolutionError,
    resolve_target,
)
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import batch as batch_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


def _write_wrapper(path: Path, write_flag: str) -> None:
    path.write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in
        *.wav|*.ana|*.pvx) OUTPUT="$arg" ;;
    esac
done
exec "{_FAKE_SUBPROCESS}" {write_flag} "$OUTPUT"
"""
    )
    path.chmod(0o755)


@pytest.fixture
def harness(tmp_path):
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    for name in ("modify", "extend", "filter"):
        _write_wrapper(cdp / name, "--write-wav")
    for name in ("blur", "morph", "combine"):
        _write_wrapper(cdp / name, "--write-ana")
    (cdp / "pvoc").write_text(
        f"""#!/bin/sh
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

    mcp = FastMCP("test-cdp-batch")
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(
        cdp_path=cdp, version="fake",
        detected_binaries=["blur", "extend", "modify", "pvoc"],
    )
    sessions = SessionManager((tmp_path / "sessions").resolve(), lambda: cdp_cfg)
    tracker = LatestTracker()
    batch_module.register(
        mcp,
        sessions=sessions,
        knowledge_index=KnowledgeIndex.load(),
        cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker,
        cache_root=cache_root,
    )
    return mcp, sessions, tracker


async def _call(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "batch", args, context=None, convert_result=False
    )


def _session_with_inputs(sessions, names, duration_s=2.0):
    session, _ = sessions.set_active("b1")
    for name in names:
        sf.write(
            str(session.inputs_dir / name),
            np.zeros(int(duration_s * 44100), dtype=np.float32),
            44100,
        )
    return session


async def test_batch_happy_path_single_graph_dir(harness):
    mcp, sessions, tracker = harness
    session = _session_with_inputs(sessions, ["a.wav", "b.wav", "c.wav"])
    # Seed a prior single-output action: batch must NOT displace latest.
    tracker.update("g0", "n1")

    payload = await _call(
        mcp,
        {
            "program": "blur", "mode": "blur",
            "inputs": ["a.wav", "b.wav", "c.wav"],
            "params": {"blurring": 10},
        },
    )
    assert payload["status"] == "ok"
    assert payload["batch_size"] == 3
    assert [e["status"] for e in payload["elements"]] == ["ok"] * 3

    # ONE graph directory; three main nodes + three auto-PVOC nodes.
    graph_dirs = list(session.graphs_dir.iterdir())
    assert len(graph_dirs) == 1
    assert "batch-blur-blur" in graph_dirs[0].name
    index = json.loads((graph_dirs[0] / "node_index.json").read_text())
    assert set(index) == {
        "n1_batch_0", "n1_batch_0_pvoc1",
        "n1_batch_1", "n1_batch_1_pvoc1",
        "n1_batch_2", "n1_batch_2_pvoc1",
    }
    for e in payload["elements"]:
        assert Path(e["output"]).exists()

    # Atomic context event: latest untouched; ONE recent_graphs entry
    # with output_node null + batch_size 3.
    assert tracker.latest == "g0:n1"
    recent = payload["context"]["recent_graphs"]
    assert recent[0]["output_node"] is None
    assert recent[0]["batch_size"] == 3
    assert recent[0]["id"] == payload["graph_id"]
    assert recent[1]["id"] == "g0"

    # latest_batch[i] resolves to the element's real output.
    resolved = resolve_target("latest_batch[1]", session, tracker)
    assert resolved.exists()
    assert resolved.name == "n1_batch_1_blur-blur.ana"
    with pytest.raises(ReferenceResolutionError, match="valid indices"):
        resolve_target("latest_batch[3]", session, tracker)


async def test_batch_validation_short_circuit(harness):
    """One bad element (param below min) → whole batch refused, nothing
    on disk, per-element reports say which element and why."""
    mcp, sessions, _ = harness
    session = _session_with_inputs(sessions, ["a.wav", "b.wav"])
    payload = await _call(
        mcp,
        {
            "program": "blur", "mode": "blur",
            "inputs": ["a.wav", "missing.wav"],
            "params": {"blurring": 10},
        },
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "batch_validation_failed" for e in payload["errors"]
    )
    by_index = {e["index"]: e for e in payload["elements"]}
    assert by_index[0]["status"] == "ok"
    assert by_index[1]["status"] == "failed"
    assert list(session.graphs_dir.iterdir()) == []  # nothing executed


async def test_batch_only_session_latest_aliases_redirect(harness):
    """With ONLY a batch in the deque: `latest` has no single-output
    action to name, and both alias paths point the user at
    latest_batch[i] instead of resolving to something bogus."""
    mcp, sessions, tracker = harness
    session = _session_with_inputs(sessions, ["a.wav"])
    payload = await _call(
        mcp,
        {
            "program": "blur", "mode": "blur",
            "inputs": ["a.wav"],
            "params": {"blurring": 10},
        },
    )
    assert payload["status"] == "ok"
    assert tracker.latest is None  # batch entries are not single outputs
    with pytest.raises(ReferenceResolutionError, match="latest_batch"):
        resolve_target("latest", session, tracker)
    # A hypothetical prev_N landing on the batch slot also redirects.
    tracker.update("g9", "n1")  # push a single on top; batch is now prev_1
    with pytest.raises(ReferenceResolutionError, match="latest_batch"):
        resolve_target("prev_1", session, tracker)
