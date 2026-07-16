"""Tests for (program, mode, submode) knowledge-index keying.

The loader keys entries by the full triple so one (program, mode) pair
can carry multiple curated submodes. Covered here: exact-submode
selection, backward-compat ``get()`` on single-entry pairs, the
``submode_required`` structured error from process / batch / sweep and a
graph() node, the explicit-but-wrong-submode ``not_curated`` message,
the loader's duplicate-triple skip, and ``get_program_info``'s chooser
payload for ambiguous pairs.

Synthetic entries are constructed via the ``KnowledgeIndex`` class
directly — no files are written into the package, so the pinned counts
in test_knowledge_loader.py / test_introspection.py are untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex, SubmodeAmbiguousError
from cdp_mcp.schema import KnowledgeEntry
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import batch as batch_module
from cdp_mcp.tools import breakpoint as breakpoint_module
from cdp_mcp.tools import graph_tool as graph_module
from cdp_mcp.tools import introspection
from cdp_mcp.tools import process as process_module
from cdp_mcp.tools import sweep as sweep_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


# ---------------------------------------------------------------------------
# Synthetic entries
# ---------------------------------------------------------------------------


def _entry(submode: int | None, **overrides: Any) -> KnowledgeEntry:
    base: dict[str, Any] = {
        "program": "fakeprog",
        "mode": "fakemode",
        "submode": submode,
        "category": "filter",
        "domain": "time",
        "input_arity": 1,
        "channel_constraint": "any",
        "input_format": ".wav",
        "output_format": ".wav",
        "duration_model": {"kind": "static"},
        "description": (
            f"Submode {submode} does the fake thing. Longer detail follows "
            "in a second sentence."
        ),
        "musical_use": f"Musical use for submode {submode}.",
        "parameters": {},
    }
    base.update(overrides)
    return KnowledgeEntry.model_validate(base)


def _multi_submode_index() -> KnowledgeIndex:
    """Two curated submodes of (fakeprog, fakemode) with DISTINCT params
    (so exact selection is observable), plus a single-entry pair."""
    return KnowledgeIndex([
        _entry(1, parameters={
            "alpha": {
                "type": "float", "min": 0.0, "max": 10.0,
                "breakpoint_capable": True,
            },
        }),
        _entry(2, parameters={
            "beta": {
                "type": "float", "min": 0.0, "max": 10.0,
                "breakpoint_capable": True,
            },
        }),
        _entry(None, program="solo", mode="only"),
    ])


# ---------------------------------------------------------------------------
# KnowledgeIndex — triple keying
# ---------------------------------------------------------------------------


def test_exact_submode_selection():
    index = _multi_submode_index()
    assert index.get("fakeprog", "fakemode", 1).submode == 1
    assert index.get("fakeprog", "fakemode", 2).submode == 2
    assert index.get("fakeprog", "fakemode", 3) is None


def test_ambiguous_pair_raises_with_sorted_curated_submodes():
    index = _multi_submode_index()
    with pytest.raises(SubmodeAmbiguousError) as exc:
        index.get("fakeprog", "fakemode")
    assert exc.value.submodes == [1, 2]
    assert exc.value.program == "fakeprog"
    assert exc.value.mode == "fakemode"


def test_backward_compat_get_single_entry_pair_synthetic():
    index = _multi_submode_index()
    # Exactly one entry for the pair → returned without a submode arg.
    entry = index.get("solo", "only")
    assert entry is not None and entry.submode is None
    # Unknown pair → None, not an exception.
    assert index.get("nope", "nothing") is None


def test_backward_compat_get_single_entry_pair_real_index():
    real = KnowledgeIndex.load()
    # Submode-less curated entry: unchanged call shape.
    blur = real.get("blur", "blur")
    assert blur is not None and blur.submode is None
    # Curated entry that carries a submode but is its pair's only entry:
    # still resolvable without passing submode.
    bank = real.get("filter", "bank")
    assert bank is not None and bank.submode == 1


def test_get_pair_sorted_none_first():
    index = KnowledgeIndex([
        _entry(2), _entry(None), _entry(1),
    ])
    assert [
        e.submode for e in index.get_pair("fakeprog", "fakemode")
    ] == [None, 1, 2]
    assert index.get_pair("nope", "nothing") == []


def test_list_entries_deterministic_submode_order():
    index = KnowledgeIndex([_entry(2), _entry(1)])
    assert [
        (e.program, e.mode, e.submode) for e in index.list_entries()
    ] == [("fakeprog", "fakemode", 1), ("fakeprog", "fakemode", 2)]


def test_loader_duplicate_triple_warns_and_skips(capsys):
    first = _entry(1, description="First wins. Kept entry.")
    later = _entry(1, description="Later loses. Skipped entry.")
    index = KnowledgeIndex([first, later])
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "duplicate" in err
    pair = index.get_pair("fakeprog", "fakemode")
    assert len(pair) == 1
    assert pair[0].description.startswith("First wins")
    # The skipped entry must not leak through the category path either.
    assert len(index.list_entries(curated_only=False)) == 1


# ---------------------------------------------------------------------------
# Tool-surface harness (FastMCP fixture pattern, as in test_batch.py)
# ---------------------------------------------------------------------------


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
    _write_wrapper(cdp / "fakeprog", "--write-wav")

    mcp = FastMCP("test-cdp-submode")
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(
        cdp_path=cdp, version="fake", detected_binaries=["fakeprog"],
    )
    sessions = SessionManager(
        (tmp_path / "sessions").resolve(), lambda: cdp_cfg
    )
    tracker = LatestTracker()
    index = _multi_submode_index()
    deps = dict(
        sessions=sessions,
        knowledge_index=index,
        cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker,
        cache_root=cache_root,
    )
    process_module.register(mcp, **deps)
    batch_module.register(mcp, **deps)
    sweep_module.register(mcp, **deps)
    graph_module.register(mcp, **deps)
    breakpoint_module.register(mcp, index)
    introspection.register(mcp, index)
    return mcp, sessions


async def _call(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


def _session_with_input(sessions, name="x.wav", duration_s=2.0):
    session, _ = sessions.set_active("submode1")
    sf.write(
        str(session.inputs_dir / name),
        np.zeros(int(duration_s * 44100), dtype=np.float32),
        44100,
    )
    return session


def _assert_submode_required(err: dict) -> None:
    assert err["type"] == "submode_required"
    # Message lists the curated submodes; fix says how to choose and
    # where to read about each.
    assert "1, 2" in err["message"]
    assert "submode=<n>" in err["fix"]
    assert "get_program_info" in err["fix"]


# ---------------------------------------------------------------------------
# submode_required from each tool surface
# ---------------------------------------------------------------------------


async def test_process_submode_required(harness):
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "process", {
        "program": "fakeprog", "mode": "fakemode", "input": "x.wav",
    })
    assert payload["status"] == "failed"
    _assert_submode_required(payload["errors"][0])


async def test_batch_submode_required(harness):
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "batch", {
        "program": "fakeprog", "mode": "fakemode", "inputs": ["x.wav"],
    })
    assert payload["status"] == "failed"
    _assert_submode_required(payload["errors"][0])


async def test_sweep_submode_required(harness):
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "sweep", {
        "program": "fakeprog", "mode": "fakemode", "input": "x.wav",
        "param_sets": [{}, {}],
    })
    assert payload["status"] == "failed"
    _assert_submode_required(payload["errors"][0])


async def test_graph_node_submode_required(harness):
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "graph", {
        "inputs": {"src": "x.wav"},
        "nodes": [{"id": "a", "op": "fakeprog fakemode", "in": "src"}],
        "dry_run": True,
    })
    assert payload["status"] == "failed"
    matching = [
        e for e in payload["errors"] if e["type"] == "submode_required"
    ]
    assert matching, payload["errors"]
    _assert_submode_required(matching[0])
    assert "node 'a'" in matching[0]["message"]


async def test_graph_node_explicit_submode_validates(harness):
    """A node spec's 'submode' key threads through to entry selection —
    submode 1's parameter set (alpha) validates clean in the dry run."""
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "graph", {
        "inputs": {"src": "x.wav"},
        "nodes": [{
            "id": "a", "op": "fakeprog fakemode", "in": "src",
            "submode": 1, "params": {"alpha": 3.0},
        }],
        "dry_run": True,
    })
    assert payload["status"] == "ok", payload
    assert payload["nodes"][0]["status"] == "ok"


async def test_graph_node_submode_bad_type_is_spec_error(harness):
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "graph", {
        "inputs": {"src": "x.wav"},
        "nodes": [{
            "id": "a", "op": "fakeprog fakemode", "in": "src",
            "submode": "one",
        }],
        "dry_run": True,
    })
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "graph_spec_error" and "submode" in e["message"]
        for e in payload["errors"]
    )


# ---------------------------------------------------------------------------
# Exact selection + explicit-but-wrong submode
# ---------------------------------------------------------------------------


async def test_process_exact_submode_selects_and_executes(harness):
    """submode=2 must select the entry whose params include 'beta' —
    the run validates and executes end-to-end against the fake binary."""
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "process", {
        "program": "fakeprog", "mode": "fakemode", "input": "x.wav",
        "params": {"beta": 5.0}, "submode": 2,
    })
    assert payload["status"] == "ok", payload["errors"]
    assert Path(payload["output"]).exists()


async def test_process_explicit_wrong_submode_mentions_curated(harness):
    mcp, sessions = harness
    _session_with_input(sessions)
    payload = await _call(mcp, "process", {
        "program": "fakeprog", "mode": "fakemode", "input": "x.wav",
        "submode": 7,
    })
    assert payload["status"] == "failed"
    err = payload["errors"][0]
    assert err["type"] == "not_curated"
    assert "7" in err["message"]
    assert "1, 2" in err["message"]  # names the submodes that ARE curated


async def test_breakpoint_submode_threading(harness):
    mcp, _sessions = harness
    base = {
        "shape": "linear", "program": "fakeprog", "mode": "fakemode",
        "param": "beta", "start": 1.0, "end": 2.0,
    }
    # Ambiguous pair without submode → submode_required.
    r = await _call(mcp, "breakpoint", dict(base))
    assert r["status"] == "failed"
    _assert_submode_required(r["errors"][0])
    # submode=2 selects the entry that HAS 'beta'.
    r = await _call(mcp, "breakpoint", dict(base, submode=2))
    assert r["status"] == "ok"
    assert r["breakpoints"] == [[0.0, 1.0], [1.0, 2.0]]
    # submode=1 selects the sibling entry, which doesn't have 'beta'.
    r = await _call(mcp, "breakpoint", dict(base, submode=1))
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "unknown_parameter"


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


async def test_get_program_info_chooser_payload(harness):
    mcp, _sessions = harness
    payload = await _call(mcp, "get_program_info", {
        "program": "fakeprog", "mode": "fakemode",
    })
    assert payload["status"] == "ok"
    assert payload["program"] == "fakeprog"
    assert payload["mode"] == "fakemode"
    assert [s["submode"] for s in payload["submodes"]] == [1, 2]
    for item in payload["submodes"]:
        n = item["submode"]
        assert item["summary"] == f"Submode {n} does the fake thing."
        assert item["musical_use"] == f"Musical use for submode {n}."
    # The chooser payload deliberately omits the full entry body.
    assert "parameters" not in payload


async def test_get_program_info_explicit_submode_full_entry(harness):
    mcp, _sessions = harness
    payload = await _call(mcp, "get_program_info", {
        "program": "fakeprog", "mode": "fakemode", "submode": 2,
    })
    assert payload["submode"] == 2
    assert "beta" in payload["parameters"]


async def test_get_program_info_unambiguous_pair_shape_unchanged(harness):
    mcp, _sessions = harness
    payload = await _call(mcp, "get_program_info", {
        "program": "solo", "mode": "only",
    })
    assert payload["program"] == "solo"
    assert payload["submode"] is None
    assert "parameters" in payload
    assert "submodes" not in payload  # no chooser fields on the entry dump


async def test_get_program_info_missing_submode_lists_known(harness):
    mcp, _sessions = harness
    with pytest.raises(ToolError, match=r"Known submodes.*\[1, 2\]"):
        await _call(mcp, "get_program_info", {
            "program": "fakeprog", "mode": "fakemode", "submode": 9,
        })


async def test_list_programs_items_include_submode(harness):
    mcp, _sessions = harness
    payload = await _call(mcp, "list_programs", {})
    assert all("submode" in item for item in payload)
    fake = [
        item["submode"] for item in payload
        if (item["program"], item["mode"]) == ("fakeprog", "fakemode")
    ]
    assert fake == [1, 2]
