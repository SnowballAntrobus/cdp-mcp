"""Tests for sweep() — one source, many param variants, one graph
directory, atomic context event, validation short-circuit,
partial_success, param_sets bounds."""

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
from cdp_mcp.tools import sweep as sweep_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()

# Param value the fake blur wrapper fails on (exit 1, no output). Lets
# the partial_success contract be tested with a single program: every
# sweep variant runs the same binary, so the failure has to be keyed on
# a param value reaching the argv rather than on a distinct wrapper.
_MAGIC_FAIL_BLURRING = 666


def _write_wrapper(path: Path, write_flag: str) -> None:
    path.write_text(
        f"""#!/bin/sh
OUTPUT=""
for arg in "$@"; do
    case "$arg" in
        666|666.0) exit 1 ;;
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
    _write_wrapper(cdp / "blur", "--write-ana")
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

    mcp = FastMCP("test-cdp-sweep")
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(
        cdp_path=cdp, version="fake",
        detected_binaries=["blur", "pvoc"],
    )
    sessions = SessionManager((tmp_path / "sessions").resolve(), lambda: cdp_cfg)
    tracker = LatestTracker()
    sweep_module.register(
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
        "sweep", args, context=None, convert_result=False
    )


def _session_with_input(sessions, name="s.wav", duration_s=2.0):
    session, _ = sessions.set_active("sw1")
    sf.write(
        str(session.inputs_dir / name),
        np.zeros(int(duration_s * 44100), dtype=np.float32),
        44100,
    )
    return session


async def test_sweep_happy_path_single_graph_dir(harness):
    mcp, sessions, tracker = harness
    session = _session_with_input(sessions)
    # Seed a prior single-output action: sweep must NOT displace latest.
    tracker.update("g0", "n1")

    param_sets = [{"blurring": 5}, {"blurring": 20}, {"blurring": 50}]
    payload = await _call(
        mcp,
        {
            "program": "blur", "mode": "blur",
            "input": "s.wav",
            "param_sets": param_sets,
        },
    )
    assert payload["status"] == "ok"
    assert payload["sweep_size"] == 3
    assert [v["status"] for v in payload["variants"]] == ["ok"] * 3
    assert [v["params"] for v in payload["variants"]] == param_sets

    # ONE graph directory; three main nodes + three auto-PVOC nodes.
    graph_dirs = list(session.graphs_dir.iterdir())
    assert len(graph_dirs) == 1
    assert "sweep-blur-blur" in graph_dirs[0].name
    index = json.loads((graph_dirs[0] / "node_index.json").read_text())
    assert set(index) == {
        "n1_sweep_0", "n1_sweep_0_pvoc1",
        "n1_sweep_1", "n1_sweep_1_pvoc1",
        "n1_sweep_2", "n1_sweep_2_pvoc1",
    }
    for v in payload["variants"]:
        assert Path(v["output"]).exists()

    # graph.json records the whole sweep definition.
    definition = json.loads((graph_dirs[0] / "graph.json").read_text())
    assert definition["program"] == "blur"
    assert definition["mode"] == "blur"
    assert definition["input"] == "s.wav"
    assert definition["param_sets"] == param_sets

    # Atomic context event: latest untouched; ONE recent_graphs entry
    # with output_node null + batch_size 3.
    assert tracker.latest == "g0:n1"
    recent = payload["context"]["recent_graphs"]
    assert recent[0]["output_node"] is None
    assert recent[0]["batch_size"] == 3
    assert recent[0]["id"] == payload["graph_id"]
    assert recent[1]["id"] == "g0"

    # latest_batch[i] resolves to the variant's real output.
    resolved = resolve_target("latest_batch[1]", session, tracker)
    assert resolved.exists()
    assert resolved.name == "n1_sweep_1_blur-blur.ana"
    with pytest.raises(ReferenceResolutionError, match="valid indices"):
        resolve_target("latest_batch[3]", session, tracker)


async def test_sweep_validation_short_circuit(harness):
    """One bad variant (param below min) → whole sweep refused, nothing
    on disk, per-variant reports say which variant and why."""
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "program": "blur", "mode": "blur",
            "input": "s.wav",
            "param_sets": [{"blurring": 10}, {"blurring": 0.5}],
        },
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "sweep_validation_failed" for e in payload["errors"]
    )
    by_index = {v["index"]: v for v in payload["variants"]}
    assert by_index[0]["status"] == "ok"
    assert by_index[1]["status"] == "failed"
    assert by_index[1]["errors"]  # per-variant reasons are reported
    assert list(session.graphs_dir.iterdir()) == []  # nothing executed


async def test_sweep_partial_success_runtime_failure_does_not_cascade(harness):
    """A mid-sweep runtime failure (magic param value makes the fake
    blur exit 1) yields partial_success with the survivors on disk."""
    mcp, sessions, tracker = harness
    session = _session_with_input(sessions)
    payload = await _call(
        mcp,
        {
            "program": "blur", "mode": "blur",
            "input": "s.wav",
            "param_sets": [
                {"blurring": 5},
                {"blurring": _MAGIC_FAIL_BLURRING},
                {"blurring": 50},
            ],
        },
    )
    assert payload["status"] == "partial_success"
    by_index = {v["index"]: v for v in payload["variants"]}
    assert by_index[0]["status"] == "ok"
    assert by_index[1]["status"] == "failed"
    assert by_index[2]["status"] == "ok"
    assert by_index[1]["output"] is None
    assert by_index[1]["exit_code"] != 0
    for i in (0, 2):
        assert Path(by_index[i]["output"]).exists()

    # The whole sweep is still ONE context event; survivors resolve,
    # the failed variant's indexed file doesn't exist.
    assert resolve_target("latest_batch[0]", session, tracker).exists()
    assert resolve_target("latest_batch[2]", session, tracker).exists()
    with pytest.raises(ReferenceResolutionError, match="does not exist"):
        resolve_target("latest_batch[1]", session, tracker)


async def test_sweep_param_sets_bounds(harness):
    """Fewer than 2 or more than 32 variants → sweep_spec_error before
    anything runs."""
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)

    for bad_sets in (
        [],
        [{"blurring": 10}],
        [{"blurring": 10}] * 33,
    ):
        payload = await _call(
            mcp,
            {
                "program": "blur", "mode": "blur",
                "input": "s.wav",
                "param_sets": bad_sets,
            },
        )
        assert payload["status"] == "failed"
        assert any(
            e["type"] == "sweep_spec_error" for e in payload["errors"]
        ), f"expected sweep_spec_error for {len(bad_sets)} variants"
    assert list(session.graphs_dir.iterdir()) == []  # nothing executed
