"""Phase 3: uncurated long-tail loading.

``scripts/generate_uncurated_entries.py`` writes minimal ``curated: false``
stubs into ``src/cdp_mcp/knowledge/data_uncurated/``; the loader picks them
up alongside the curated ``data/`` entries. These tests pin the contract:

- both directories load into one index;
- ``curated_only`` filtering separates the populations correctly;
- ``process()`` still hard-rejects uncurated entries by name.

No exact counts are pinned here — those live in the dedicated pinned-count
test files.
"""

from __future__ import annotations

import json
from importlib.resources import as_file, files

import pytest

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.process import process_impl


@pytest.fixture(scope="module")
def index() -> KnowledgeIndex:
    return KnowledgeIndex.load()


def _uncurated_stub_entries() -> list[dict]:
    """Read the generated stubs straight from the packaged directory."""
    root = files("cdp_mcp.knowledge").joinpath("data_uncurated")
    with as_file(root) as d:
        assert d.is_dir(), (
            "data_uncurated/ missing — run "
            "scripts/generate_uncurated_entries.py"
        )
        return [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(d.glob("*.json"))
        ]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_loader_loads_both_directories(index):
    # A curated entry from data/ ...
    curated = index.get("blur", "blur")
    assert curated is not None
    assert curated.curated is True
    # ... and every generated stub from data_uncurated/ is retrievable.
    stubs = _uncurated_stub_entries()
    assert stubs, "generator produced no stubs"
    for stub in stubs:
        loaded = index.get(stub["program"], stub["mode"])
        assert loaded is not None, f"stub {stub['program']} not loaded"
        assert loaded.curated is False
        assert loaded.category == "uncurated"
        assert loaded.stability == "unstable"


def test_uncurated_stubs_never_collide_with_curated_programs(index):
    """The generator only emits programs with no curated entry, so no
    (program, mode) key in the index can be both."""
    curated_programs = {
        e.program for e in index.list_entries(curated_only=True)
    }
    for stub in _uncurated_stub_entries():
        assert stub["program"] not in curated_programs


# ---------------------------------------------------------------------------
# curated_only filtering
# ---------------------------------------------------------------------------


def test_curated_only_true_excludes_stubs(index):
    entries = index.list_entries(curated_only=True)
    assert entries, "no curated entries loaded"
    assert all(e.curated for e in entries)
    assert all(e.category != "uncurated" for e in entries)


def test_curated_only_false_surfaces_the_long_tail(index):
    all_entries = index.list_entries(curated_only=False)
    curated = index.list_entries(curated_only=True)
    uncurated = [e for e in all_entries if not e.curated]
    assert len(all_entries) == len(curated) + len(uncurated)
    assert len(uncurated) == len(_uncurated_stub_entries())
    # Filters still compose: category narrows within the long tail.
    tail = index.list_entries(category="uncurated", curated_only=False)
    assert tail == sorted(uncurated, key=lambda e: (e.program, e.mode))
    # And curated_only=True composes with the uncurated category to zero.
    assert index.list_entries(category="uncurated", curated_only=True) == []


def test_uncurated_category_visible_in_categories(index):
    assert "uncurated" in index.categories()


# ---------------------------------------------------------------------------
# process() hard gate
# ---------------------------------------------------------------------------


async def test_process_hard_rejects_generated_uncurated_entry(index, tmp_path):
    """An entry that loads with curated=false must still be refused by
    process() — loading widens discovery, not execution."""
    stub = _uncurated_stub_entries()[0]
    # Sanity: the entry IS in the index...
    assert index.get(stub["program"], stub["mode"]) is not None

    cdp_cfg = CDPConfig(
        cdp_path=tmp_path, version="fake", detected_binaries=[]
    )
    sessions = SessionManager(
        (tmp_path / "sessions").resolve(), lambda: cdp_cfg
    )
    sessions.set_active("uncurated_gate_v1")
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()

    r = await process_impl(
        None,
        program=stub["program"],
        mode=stub["mode"],
        input="x.wav",
        params={},
        sessions=sessions,
        knowledge_index=index,
        cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=LatestTracker(),
        cache_root=cache_root,
    )
    assert r["status"] == "failed"
    assert any(e["type"] == "not_curated" for e in r["errors"])
