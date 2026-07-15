"""Integration tests for cleanup() and cleanup_cache().

Graph directories are hand-built on disk (node_index.json + lineage.json
mimicking GraphDir's exact layout, lineage input records shaped like
schema.InputRecord) so selection, dependency protection, and deletion
are exercised without running CDP.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import cleanup as cleanup_module

_ISO = "2026-07-13T00:00:00+00:00"

# ---------------------------------------------------------------------------
# Fixtures + hand-built graph helpers
# ---------------------------------------------------------------------------


def _fake_cdp() -> CDPConfig:
    return CDPConfig(
        cdp_path=Path("/tmp/fake"),
        version="8.0.1-fake",
        detected_binaries=["blur"],
    )


@pytest.fixture
def env(tmp_path):
    mcp = FastMCP("test-cdp-cleanup")
    sessions = SessionManager(tmp_path / "sessions", lambda: _fake_cdp())
    tracker = LatestTracker()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cleanup_module.register(
        mcp, sessions=sessions, latest_tracker=tracker, cache_root=cache_root
    )
    session, _ = sessions.set_active("cleanup_test")
    return mcp, sessions, session, tracker, cache_root


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


def _lineage_node(inputs: list[dict], output_path: Path) -> dict:
    """Minimal NodeLineage-shaped dict — only the fields cleanup reads
    (inputs[].path) need to be real; the rest mirror schema.NodeLineage
    field names so the fixture stays a faithful on-disk replica."""
    return {
        "argv": ["/fake/cdp/blur", "blur", "in", str(output_path), "10"],
        "inputs": inputs,
        "output_path": str(output_path),
        "output_sha256": "c" * 64,
        "params": {},
        "cdp_version": "8.0.1-fake",
        "started_at": _ISO,
        "finished_at": _ISO,
        "duration_ms": 42,
        "exit_code": 0,
    }


def _make_graph(
    session,
    graph_id: str,
    *,
    input_paths: list[Path] | None = None,
    payload_bytes: int = 256,
) -> Path:
    """Build graphs/<graph_id>/ with GraphDir's file layout: one output
    node ``n1`` whose lineage inputs reference ``input_paths``."""
    root = session.graphs_dir / graph_id
    root.mkdir(parents=True)
    out_name = "n1_blur-blur.wav"
    (root / out_name).write_bytes(b"\x00" * payload_bytes)
    (root / "node_index.json").write_text(
        json.dumps({"n1": out_name}, indent=2) + "\n"
    )
    records = [
        {"path": str(p), "sha256": "a" * 64, "source_node": None}
        for p in (input_paths or [])
    ]
    (root / "lineage.json").write_text(
        json.dumps(
            {"nodes": {"n1": _lineage_node(records, root / out_name)}},
            indent=2,
        )
        + "\n"
    )
    return root


def _graph_output(session, graph_id: str) -> Path:
    return session.graphs_dir / graph_id / "n1_blur-blur.wav"


def _set_age_days(path: Path, days: float) -> None:
    ts = time.time() - days * 86400
    os.utime(path, (ts, ts))


def _write_tags(session, mapping: dict) -> None:
    session.tags_path.write_text(json.dumps(mapping, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Registration + preconditions
# ---------------------------------------------------------------------------


async def test_tools_registered(env):
    mcp, *_ = env
    tools = {t.name for t in await mcp.list_tools()}
    assert {"cleanup", "cleanup_cache"} <= tools


async def test_no_active_session_is_structured_error(tmp_path):
    mcp = FastMCP("test-cdp-cleanup-nosession")
    sessions = SessionManager(tmp_path, lambda: _fake_cdp())
    cleanup_module.register(
        mcp,
        sessions=sessions,
        latest_tracker=LatestTracker(),
        cache_root=tmp_path / "cache",
    )
    payload = await _call_raw(mcp, "cleanup", {"predicate": {"glob": "*"}})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "no_active_session"


@pytest.mark.parametrize(
    "bad_predicate",
    [
        {},  # no key
        {"glob": "*", "tag": "x"},  # two keys
        {"nope": "*"},  # unknown key
        {"glob": ""},  # empty string
        {"age_days": -1},  # negative
        {"age_days": True},  # bool is not a number here
        {"and": []},  # empty composition
        {"and": [{"glob": "*"}, {"bogus": 1}]},  # nested unknown key
        {"not": "x"},  # non-dict operand
        {"tier": "pvoc"},  # cache-only key on the graph domain
    ],
)
async def test_invalid_predicates_are_structured_errors(env, bad_predicate):
    mcp, _, session, *_ = env
    _make_graph(session, "gA")
    payload = await _call_raw(mcp, "cleanup", {"predicate": bad_predicate})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "invalid_predicate"
    assert (session.graphs_dir / "gA").exists()


# ---------------------------------------------------------------------------
# Dry-run default + selection grammar
# ---------------------------------------------------------------------------


async def test_dry_run_is_the_default_and_touches_nothing(env):
    mcp, _, session, *_ = env
    _make_graph(session, "gA-batch")
    payload = await _call_raw(mcp, "cleanup", {"predicate": {"glob": "*batch*"}})
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["deleted"] == ["gA-batch"]
    assert payload["freed_bytes"] > 0
    assert (session.graphs_dir / "gA-batch").exists()  # nothing deleted


async def test_glob_selects_by_directory_name(env):
    mcp, _, session, *_ = env
    _make_graph(session, "2026-07-01T00-00-00-000-batch-blur")
    _make_graph(session, "2026-07-02T00-00-00-000-graph")
    payload = await _call_raw(mcp, "cleanup", {"predicate": {"glob": "*batch*"}})
    assert payload["deleted"] == ["2026-07-01T00-00-00-000-batch-blur"]


async def test_graph_id_selects_exactly_one(env):
    mcp, _, session, *_ = env
    _make_graph(session, "gA")
    _make_graph(session, "gAA")
    payload = await _call_raw(mcp, "cleanup", {"predicate": {"graph_id": "gA"}})
    assert payload["deleted"] == ["gA"]


async def test_age_days_selects_older_dirs_only(env):
    mcp, _, session, *_ = env
    old = _make_graph(session, "gOld")
    _make_graph(session, "gNew")
    _set_age_days(old, days=10)
    payload = await _call_raw(mcp, "cleanup", {"predicate": {"age_days": 5}})
    assert payload["deleted"] == ["gOld"]


async def test_and_or_not_composition(env):
    mcp, _, session, *_ = env
    old_batch = _make_graph(session, "gOld-batch")
    old_graph = _make_graph(session, "gOld-graph")
    _make_graph(session, "gNew-batch")
    _set_age_days(old_batch, days=10)
    _set_age_days(old_graph, days=10)

    payload = await _call_raw(mcp, "cleanup", {"predicate": {
        "and": [{"age_days": 5}, {"not": {"glob": "*graph*"}}],
    }})
    assert payload["deleted"] == ["gOld-batch"]

    payload = await _call_raw(mcp, "cleanup", {"predicate": {
        "or": [{"graph_id": "gNew-batch"}, {"glob": "*graph*"}],
    }})
    assert sorted(payload["deleted"]) == ["gNew-batch", "gOld-graph"]


# ---------------------------------------------------------------------------
# Dependency protection
# ---------------------------------------------------------------------------


async def test_survivor_reference_protects_candidate(env):
    """B's lineage inputs reference A's output; deleting A alone is
    refused, with B listed as the dependent."""
    mcp, _, session, *_ = env
    _make_graph(session, "gA")
    _make_graph(session, "gB", input_paths=[_graph_output(session, "gA")])

    payload = await _call_raw(
        mcp, "cleanup", {"predicate": {"graph_id": "gA"}, "dry_run": False}
    )
    assert payload["status"] == "ok"
    assert payload["deleted"] == []
    assert payload["protected"] == [
        {"id": "gA", "reason": "referenced_by_survivor", "dependents": ["gB"]}
    ]
    assert (session.graphs_dir / "gA").exists()


async def test_protection_cascades_to_fixpoint(env):
    """Select A and B where C (survivor) depends on B and B depends on A:
    protecting B makes it a survivor, which must then protect A too."""
    mcp, _, session, *_ = env
    _make_graph(session, "gA")
    _make_graph(session, "gB", input_paths=[_graph_output(session, "gA")])
    _make_graph(session, "gC", input_paths=[_graph_output(session, "gB")])

    payload = await _call_raw(mcp, "cleanup", {"predicate": {
        "or": [{"graph_id": "gA"}, {"graph_id": "gB"}],
    }, "dry_run": False})
    assert payload["deleted"] == []
    reasons = {p["id"]: p for p in payload["protected"]}
    assert reasons["gB"]["dependents"] == ["gC"]
    assert reasons["gA"]["dependents"] == ["gB"]


async def test_dependent_and_dependency_delete_together(env):
    """When the predicate selects the whole A<-B chain and nothing else
    references it, both delete — candidates aren't survivors."""
    mcp, _, session, *_ = env
    _make_graph(session, "gA")
    _make_graph(session, "gB", input_paths=[_graph_output(session, "gA")])

    payload = await _call_raw(
        mcp, "cleanup", {"predicate": {"glob": "g*"}, "dry_run": False}
    )
    assert sorted(payload["deleted"]) == ["gA", "gB"]
    assert payload["protected"] == []
    assert not (session.graphs_dir / "gA").exists()
    assert not (session.graphs_dir / "gB").exists()


async def test_self_reference_does_not_protect(env):
    """A graph whose lineage references its own files (the auto-PVOC
    pattern) must not pin itself."""
    mcp, _, session, *_ = env
    root = _make_graph(session, "gSelf")
    # Point the lineage input at the graph's own output file.
    (root / "lineage.json").write_text(json.dumps({"nodes": {"n1": _lineage_node(
        [{"path": str(root / "n1_blur-blur.wav"), "sha256": "a" * 64,
          "source_node": None}],
        root / "n1_blur-blur.wav",
    )}}) + "\n")
    payload = await _call_raw(
        mcp, "cleanup", {"predicate": {"graph_id": "gSelf"}, "dry_run": False}
    )
    assert payload["deleted"] == ["gSelf"]
    assert not root.exists()


# ---------------------------------------------------------------------------
# Tag protection + explicit-tag override
# ---------------------------------------------------------------------------


async def test_tagged_graph_is_protected(env):
    mcp, _, session, *_ = env
    _make_graph(session, "gKeep")
    _write_tags(session, {"graphs/gKeep/n1_blur-blur.wav": ["keeper"]})

    payload = await _call_raw(
        mcp, "cleanup", {"predicate": {"glob": "g*"}, "dry_run": False}
    )
    assert payload["deleted"] == []
    assert payload["protected"] == [
        {"id": "gKeep", "reason": "tagged", "tags": ["keeper"]}
    ]
    assert (session.graphs_dir / "gKeep").exists()


async def test_explicit_tag_selection_overrides_protection(env):
    mcp, _, session, *_ = env
    _make_graph(session, "gReject")
    _make_graph(session, "gOther")
    _write_tags(session, {"graphs/gReject/n1_blur-blur.wav": ["reject"]})

    payload = await _call_raw(
        mcp, "cleanup", {"predicate": {"tag": "reject"}, "dry_run": False}
    )
    assert payload["deleted"] == ["gReject"]
    assert payload["protected"] == []
    assert not (session.graphs_dir / "gReject").exists()
    assert (session.graphs_dir / "gOther").exists()
    # The tag entry pointing into the deleted dir is scrubbed.
    assert json.loads(session.tags_path.read_text()) == {}


async def test_tag_protection_holds_against_other_predicates(env):
    """A graph tagged 'keeper' selected via glob stays protected even
    when the predicate names a DIFFERENT tag."""
    mcp, _, session, *_ = env
    _make_graph(session, "gKeep")
    _write_tags(session, {"graphs/gKeep/n1_blur-blur.wav": ["keeper"]})
    payload = await _call_raw(mcp, "cleanup", {"predicate": {
        "or": [{"glob": "gKeep"}, {"tag": "reject"}],
    }, "dry_run": False})
    assert payload["deleted"] == []
    assert payload["protected"][0]["reason"] == "tagged"


# ---------------------------------------------------------------------------
# Real-run side effects: tracker pruning, tags scrub, freed bytes
# ---------------------------------------------------------------------------


async def test_real_delete_prunes_tracker_and_frees_bytes(env):
    mcp, _, session, tracker, _ = env
    _make_graph(session, "gA", payload_bytes=4096)
    _make_graph(session, "gB")
    tracker.update("gA", "n1")
    tracker.update("gB", "n1")  # latest -> gB, prev_1 -> gA
    _write_tags(session, {
        "graphs/gA/n1_blur-blur.wav": ["scratch"],
        "inputs/frog.wav": ["source"],
    })

    payload = await _call_raw(mcp, "cleanup", {
        "predicate": {"tag": "scratch"}, "dry_run": False,
    })
    assert payload["status"] == "ok"
    assert payload["dry_run"] is False
    assert payload["deleted"] == ["gA"]
    assert payload["freed_bytes"] >= 4096
    assert not (session.graphs_dir / "gA").exists()
    # Tracker: gA's slot is a hole (no renumbering); gB survives as latest.
    assert tracker.latest == "gB:n1"
    assert tracker.get_slot(1) is None
    # tags.json: only the deleted graph's entry is scrubbed.
    assert json.loads(session.tags_path.read_text()) == {
        "inputs/frog.wav": ["source"],
    }


async def test_deleting_latest_leaves_hole_not_successor(env):
    mcp, _, session, tracker, _ = env
    _make_graph(session, "gOld")
    _make_graph(session, "gNewest")
    tracker.update("gOld", "n1")
    tracker.update("gNewest", "n1")
    await _call_raw(mcp, "cleanup", {
        "predicate": {"graph_id": "gNewest"}, "dry_run": False,
    })
    # Rule 3: a pruned latest is gone, not silently replaced by older.
    assert tracker.latest is None


# ---------------------------------------------------------------------------
# cleanup_cache
# ---------------------------------------------------------------------------


def _seed_cache(cache_root: Path) -> None:
    (cache_root / "pvoc").mkdir(parents=True, exist_ok=True)
    (cache_root / "analysis").mkdir(parents=True, exist_ok=True)
    (cache_root / "pvoc" / ("a" * 64 + ".ana")).write_bytes(b"\x00" * 2048)
    (cache_root / "pvoc" / ("b" * 64 + ".ana")).write_bytes(b"\x00" * 1024)
    (cache_root / "analysis" / ("c" * 64 + ".json")).write_bytes(b"{}")


async def test_cache_report_with_no_predicate(env):
    mcp, _, _, _, cache_root = env
    _seed_cache(cache_root)
    payload = await _call_raw(mcp, "cleanup_cache", {})
    assert payload["status"] == "ok"
    assert payload["dry_run"] is True
    assert payload["deleted_count"] == 0
    assert payload["freed_bytes"] == 0
    assert payload["per_tier"]["pvoc"] == {
        "files": 2, "bytes": 3072, "matched_files": 0, "matched_bytes": 0,
    }
    assert payload["per_tier"]["analysis"]["files"] == 1
    assert payload["per_tier"]["visualizations"]["files"] == 0
    assert payload["per_tier"]["audition"]["files"] == 0


async def test_cache_tier_dry_run_then_delete(env):
    mcp, _, _, _, cache_root = env
    _seed_cache(cache_root)

    dry = await _call_raw(mcp, "cleanup_cache", {"predicate": {"tier": "pvoc"}})
    assert dry["dry_run"] is True
    assert dry["deleted_count"] == 2
    assert dry["freed_bytes"] == 3072
    assert len(list((cache_root / "pvoc").iterdir())) == 2  # untouched

    real = await _call_raw(mcp, "cleanup_cache", {
        "predicate": {"tier": "pvoc"}, "dry_run": False,
    })
    assert real["deleted_count"] == 2
    assert real["freed_bytes"] == 3072
    assert list((cache_root / "pvoc").iterdir()) == []
    # Other tiers untouched.
    assert len(list((cache_root / "analysis").iterdir())) == 1


async def test_cache_age_days_predicate(env):
    mcp, _, _, _, cache_root = env
    _seed_cache(cache_root)
    old = cache_root / "pvoc" / ("a" * 64 + ".ana")
    _set_age_days(old, days=100)
    payload = await _call_raw(mcp, "cleanup_cache", {
        "predicate": {"age_days": 30}, "dry_run": False,
    })
    assert payload["deleted_count"] == 1
    assert not old.exists()
    assert (cache_root / "pvoc" / ("b" * 64 + ".ana")).exists()


async def test_cache_size_gt_mb_predicate(env):
    mcp, _, _, _, cache_root = env
    _seed_cache(cache_root)
    big = cache_root / "pvoc" / ("d" * 64 + ".ana")
    big.write_bytes(b"\x00" * (1024 * 1024 + 1))
    payload = await _call_raw(mcp, "cleanup_cache", {
        "predicate": {"size_gt_mb": 1}, "dry_run": False,
    })
    assert payload["deleted_count"] == 1
    assert payload["freed_bytes"] == 1024 * 1024 + 1
    assert not big.exists()


async def test_cache_boolean_composition(env):
    mcp, _, _, _, cache_root = env
    _seed_cache(cache_root)
    payload = await _call_raw(mcp, "cleanup_cache", {"predicate": {
        "and": [{"tier": "pvoc"}, {"not": {"size_gt_mb": 0.0015}}],
    }, "dry_run": False})
    # Only the 1024-byte pvoc file is <= ~1573 bytes.
    assert payload["deleted_count"] == 1
    assert (cache_root / "pvoc" / ("a" * 64 + ".ana")).exists()
    assert not (cache_root / "pvoc" / ("b" * 64 + ".ana")).exists()


async def test_cache_real_run_requires_predicate(env):
    mcp, _, _, _, cache_root = env
    _seed_cache(cache_root)
    payload = await _call_raw(mcp, "cleanup_cache", {"dry_run": False})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "predicate_required"
    assert len(list((cache_root / "pvoc").iterdir())) == 2


@pytest.mark.parametrize(
    "bad_predicate",
    [
        {"tier": "bogus"},
        {"glob": "*"},  # graph-only key on the cache domain
        {"size_gt_mb": "10"},
    ],
)
async def test_cache_invalid_predicates(env, bad_predicate):
    mcp, *_ = env
    payload = await _call_raw(mcp, "cleanup_cache", {"predicate": bad_predicate})
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "invalid_predicate"
