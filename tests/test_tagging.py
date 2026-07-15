"""Tests for tag() and journal() — durable session memory (tags.json,
journal.md): add/remove/dedupe/query/validation for tags, append/read/
caps for the journal."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import journal as journal_module
from cdp_mcp.tools import tagging as tagging_module


@pytest.fixture
def harness(tmp_path):
    mcp = FastMCP("test-cdp-tagging")
    sessions = SessionManager((tmp_path / "sessions").resolve(), lambda: None)
    tracker = LatestTracker()
    tagging_module.register(mcp, sessions=sessions, latest_tracker=tracker)
    journal_module.register(mcp, sessions=sessions)
    return mcp, sessions, tracker


async def _call(mcp: FastMCP, tool: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        tool, args, context=None, convert_result=False
    )


def _session_with_input(sessions, name="a.wav"):
    session, _ = sessions.set_active("t1")
    (session.inputs_dir / name).write_bytes(b"\x00" * 64)
    return session


# ---------------------------------------------------------------------------
# tag()
# ---------------------------------------------------------------------------


async def test_tag_add_and_on_disk_shape(harness):
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)
    payload = await _call(
        mcp, "tag", {"target": "a.wav", "tags": ["warm", "drone"]}
    )
    assert payload["status"] == "ok"
    assert payload["path"] == "inputs/a.wav"
    assert payload["tags"] == ["drone", "warm"]  # deduped, sorted
    assert payload["all_tags"] == {"drone": 1, "warm": 1}

    on_disk = json.loads(session.tags_path.read_text())
    assert on_disk == {"inputs/a.wav": ["drone", "warm"]}


async def test_tag_dedupe_on_repeat_add(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    await _call(mcp, "tag", {"target": "a.wav", "tags": ["drone", "warm"]})
    payload = await _call(
        mcp, "tag", {"target": "a.wav", "tags": ["drone", "bright"]}
    )
    assert payload["tags"] == ["bright", "drone", "warm"]
    assert payload["all_tags"]["drone"] == 1  # not double-counted


async def test_tag_remove_drops_empty_key(harness):
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)
    await _call(mcp, "tag", {"target": "a.wav", "tags": ["drone", "warm"]})

    payload = await _call(
        mcp, "tag", {"target": "a.wav", "tags": ["warm"], "remove": True}
    )
    assert payload["status"] == "ok"
    assert payload["tags"] == ["drone"]

    payload = await _call(
        mcp, "tag", {"target": "a.wav", "tags": ["drone"], "remove": True}
    )
    assert payload["tags"] == []
    # File with no tags left drops out of tags.json entirely.
    assert json.loads(session.tags_path.read_text()) == {}


async def test_tag_empty_tags_queries_without_writing(harness):
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)
    (session.inputs_dir / "b.wav").write_bytes(b"\x00" * 64)
    await _call(mcp, "tag", {"target": "a.wav", "tags": ["drone"]})
    await _call(mcp, "tag", {"target": "b.wav", "tags": ["drone", "grain"]})
    before = session.tags_path.read_text()

    payload = await _call(mcp, "tag", {"target": "a.wav", "tags": []})
    assert payload["status"] == "ok"
    assert payload["tags"] == ["drone"]
    assert payload["all_tags"] == {"drone": 2, "grain": 1}
    assert payload["tag_map"] == {
        "inputs/a.wav": ["drone"],
        "inputs/b.wav": ["drone", "grain"],
    }
    assert session.tags_path.read_text() == before  # nothing written


async def test_tag_invalid_tags_rejected(harness):
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)
    for bad in (["Drone"], ["bad tag"], ["x" * 33], [""], ["ok", "no/pe"]):
        payload = await _call(mcp, "tag", {"target": "a.wav", "tags": bad})
        assert payload["status"] == "failed"
        assert any(e["type"] == "tag_invalid" for e in payload["errors"])
    assert json.loads(session.tags_path.read_text()) == {}  # untouched


async def test_tag_alias_target_resolves(harness):
    """Aliases go through the shared reference grammar: `latest`
    resolves to the graph node's output and is stored by its
    session-relative path."""
    mcp, sessions, tracker = harness
    session = _session_with_input(sessions)
    graph_root = session.graphs_dir / "g1"
    graph_root.mkdir(parents=True)
    (graph_root / "node_index.json").write_text(
        json.dumps({"n1": "n1_out.wav"})
    )
    (graph_root / "n1_out.wav").write_bytes(b"\x00" * 64)
    tracker.update("g1", "n1")

    payload = await _call(mcp, "tag", {"target": "latest", "tags": ["keeper"]})
    assert payload["status"] == "ok"
    assert payload["path"] == "graphs/g1/n1_out.wav"
    assert json.loads(session.tags_path.read_text()) == {
        "graphs/g1/n1_out.wav": ["keeper"],
    }


async def test_tag_unresolvable_target_and_no_session(harness):
    mcp, sessions, _ = harness
    payload = await _call(mcp, "tag", {"target": "a.wav", "tags": ["drone"]})
    assert payload["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in payload["errors"])

    _session_with_input(sessions)
    payload = await _call(
        mcp, "tag", {"target": "missing.wav", "tags": ["drone"]}
    )
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "reference_resolution" for e in payload["errors"]
    )


# ---------------------------------------------------------------------------
# journal()
# ---------------------------------------------------------------------------

_ENTRY_RE = re.compile(
    r"^- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] tried blur 40$",
    re.MULTILINE,
)


async def test_journal_append_and_read(harness):
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)

    payload = await _call(mcp, "journal", {"note": "tried blur 40"})
    assert payload["status"] == "ok"
    assert payload["entry_count"] == 1
    assert payload["path"] == str(session.journal_path)
    assert _ENTRY_RE.search(session.journal_path.read_text())

    payload = await _call(mcp, "journal", {"note": "variant 2 too harsh"})
    assert payload["entry_count"] == 2

    # No note (and empty string) → read path, no write.
    for read_args in ({}, {"note": ""}):
        payload = await _call(mcp, "journal", read_args)
        assert payload["status"] == "ok"
        assert payload["truncated"] is False
        assert "tried blur 40" in payload["content"]
        assert "variant 2 too harsh" in payload["content"]
        assert payload["entry_count"] == 2


async def test_journal_multiline_note_collapses_to_one_entry(harness):
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)
    payload = await _call(
        mcp, "journal", {"note": "line one\nline two\r\nline three"}
    )
    assert payload["entry_count"] == 1
    text = session.journal_path.read_text()
    assert "line one line two line three" in text


async def test_journal_note_cap(harness):
    mcp, sessions, _ = harness
    session = _session_with_input(sessions)
    before = session.journal_path.read_text()
    payload = await _call(mcp, "journal", {"note": "x" * 5000})
    assert payload["status"] == "failed"
    assert any(
        e["type"] == "journal_note_too_large" for e in payload["errors"]
    )
    assert session.journal_path.read_text() == before  # nothing appended


async def test_journal_read_cap_truncates(harness):
    mcp, sessions, _ = harness
    _session_with_input(sessions)
    for i in range(9):  # 9 × ~4 KB ≈ 36 KB > the 32 KiB read cap
        await _call(mcp, "journal", {"note": f"{i} " + "x" * 4000})
    payload = await _call(mcp, "journal", {})
    assert payload["status"] == "ok"
    assert payload["truncated"] is True
    assert len(payload["content"].encode("utf-8")) <= 32 * 1024
    assert payload["entry_count"] == 9  # counted from the full file
