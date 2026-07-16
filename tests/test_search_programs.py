"""Tests for the curated-knowledge FTS5 index and the search_programs tool.

Hermetic: the corpus is the REAL packaged knowledge
(``KnowledgeIndex.load()`` reads package data — no CDP install, no
session, no network), indexed into a tmp sqlite file. Tool-level tests
go through the registered FastMCP instance via ``_tool_manager`` with
``convert_result=False``, matching ``tests/test_docs.py``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp.knowledge import search_index
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.tools import search_programs as sp_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def knowledge() -> KnowledgeIndex:
    return KnowledgeIndex.load()


@pytest.fixture(scope="module")
def built_index(knowledge: KnowledgeIndex, tmp_path_factory) -> Path:
    # Deliberately in a not-yet-existing subdirectory: build_index must
    # create parents itself (mirrors the docs_index contract).
    path = tmp_path_factory.mktemp("kidx") / "index" / "programs.sqlite3"
    search_index.build_index(knowledge, path)
    return path


def _meta(index_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(index_path)
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()


async def _call_raw(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    """Invoke a registered tool and return the raw Python payload."""
    return await mcp._tool_manager.call_tool(
        name, args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# build_index / metadata
# ---------------------------------------------------------------------------


def test_build_index_records_meta(built_index, knowledge):
    meta = _meta(built_index)
    curated = knowledge.list_entries(curated_only=True)
    assert int(meta["entry_count"]) == len(curated)
    assert int(meta["entry_count"]) > 300  # the Phase 6 curated corpus
    assert meta["built_at"]
    assert len(meta["knowledge_fingerprint"]) == 64
    assert not built_index.with_name(built_index.name + ".tmp").exists()


def test_uncurated_entries_are_excluded(built_index, knowledge):
    # data_uncurated/ stubs widen list_programs(curated_only=False) but
    # must never surface from the musical-intent search.
    all_entries = knowledge.list_entries(curated_only=False)
    curated = knowledge.list_entries(curated_only=True)
    assert len(all_entries) > len(curated), "fixture assumption: stubs exist"
    conn = sqlite3.connect(built_index)
    try:
        (count,) = conn.execute("SELECT count(*) FROM entries").fetchone()
    finally:
        conn.close()
    assert count == len(curated)


# ---------------------------------------------------------------------------
# search: musical-intent queries against the real corpus
# ---------------------------------------------------------------------------


def test_granular_finds_grain_brassage_family(built_index):
    results = search_index.search(built_index, "granular", limit=8)
    assert results, "expected hits for 'granular'"
    families = {(r["program"], r["mode"]) for r in results}
    assert any(
        prog == "grain" or mode == "brassage" or prog == "grainex"
        for prog, mode in families
    ) or any(r["category"] == "granular" for r in results), (
        f"no grain/brassage-family hit in {sorted(families)}"
    )


def test_stutter_finds_stutter_envspeak_family(built_index):
    results = search_index.search(built_index, "stutter", limit=8)
    assert results, "expected hits for 'stutter'"
    programs = {r["program"] for r in results}
    assert programs & {"stutter", "envspeak"}, (
        f"no stutter/envspeak-family hit in {sorted(programs)}"
    )


def test_name_tokens_rank_the_named_entry_first(built_index):
    results = search_index.search(built_index, "blur chorus", limit=3)
    assert results
    assert (results[0]["program"], results[0]["mode"]) == ("blur", "chorus")


def test_result_shape_and_musical_use_truncation(built_index):
    results = search_index.search(built_index, "granular", limit=8)
    for r in results:
        assert set(r) == {
            "program",
            "mode",
            "submode",
            "category",
            "domain",
            "score",
            "snippet",
            "musical_use",
        }
        assert r["submode"] is None or isinstance(r["submode"], int)
        assert r["domain"] in ("time", "spectral")
        assert isinstance(r["score"], float)
        # ~200 chars plus a little slack for the word-boundary ellipsis.
        assert len(r["musical_use"]) <= 210


def test_natural_language_phrase_ranks_informative_terms(built_index):
    # Stopwords ("make", "it", "and") are dropped; what ranks the hits
    # must be the informative terms, visible as snippet match markers.
    results = search_index.search(built_index, "make it shimmer and sustain")
    assert results, "natural-language query returned nothing"
    top_snippets = " ".join(r["snippet"].lower() for r in results[:3])
    assert "[shimmer" in top_snippets or "[sustain" in top_snippets


def test_all_stopword_query_still_searches(built_index):
    # The stopword filter must not turn "make it" into an empty query —
    # the guard falls back to the original tokens.
    assert isinstance(search_index.search(built_index, "make it"), list)


# ---------------------------------------------------------------------------
# search: filters
# ---------------------------------------------------------------------------


def test_category_filter_narrows_results(built_index):
    unfiltered = search_index.search(built_index, "grain", limit=20)
    filtered = search_index.search(
        built_index, "grain", limit=20, category="granular"
    )
    assert filtered, "expected granular-category hits for 'grain'"
    assert all(r["category"] == "granular" for r in filtered)
    assert {r["category"] for r in unfiltered} != {"granular"} or len(
        unfiltered
    ) >= len(filtered)


def test_domain_filter_narrows_results(built_index):
    filtered = search_index.search(
        built_index, "stretch", limit=20, domain="spectral"
    )
    assert filtered, "expected spectral-domain hits for 'stretch'"
    assert all(r["domain"] == "spectral" for r in filtered)


def test_filters_compose_with_and_semantics(built_index):
    results = search_index.search(
        built_index, "average smear", limit=20,
        category="spectral-time", domain="spectral",
    )
    for r in results:
        assert r["category"] == "spectral-time"
        assert r["domain"] == "spectral"


# ---------------------------------------------------------------------------
# search: degenerate queries
# ---------------------------------------------------------------------------


def test_unknown_word_returns_empty_list(built_index):
    assert search_index.search(built_index, "xylotelepathic") == []


def test_fts5_operator_soup_is_sanitized(built_index):
    # Raw FTS5 syntax must never raise OperationalError. Pure operator
    # soup leaves no tokens and returns []; syntax mixed with real words
    # still matches on those words ("NEAR/2" legitimately leaves "2",
    # which may match real entry text — so no zero-match assertion).
    assert search_index.search(built_index, '" AND ( OR NOT * )') == []
    assert isinstance(
        search_index.search(built_index, '" AND ( OR NOT * NEAR/2 )'), list
    )
    hits = search_index.search(built_index, 'granular" AND (stutter')
    assert hits, "quoted-operator query should still match its real tokens"


def test_empty_query_returns_empty_list(built_index):
    assert search_index.search(built_index, "") == []
    assert search_index.search(built_index, "   ") == []


def test_limit_is_respected(built_index):
    assert len(search_index.search(built_index, "sound", limit=3)) <= 3


# ---------------------------------------------------------------------------
# ensure_index: fingerprint stability and rebuild triggers
# ---------------------------------------------------------------------------


def test_ensure_index_builds_when_missing(knowledge, tmp_path):
    path = tmp_path / "programs.sqlite3"
    assert search_index.ensure_index(knowledge, path) is True
    assert path.exists()


def test_ensure_index_noop_when_fresh(knowledge, tmp_path):
    path = tmp_path / "programs.sqlite3"
    search_index.ensure_index(knowledge, path)
    built_at = _meta(path)["built_at"]
    # Second call: same knowledge, same fingerprint — no rebuild.
    assert search_index.ensure_index(knowledge, path) is False
    assert _meta(path)["built_at"] == built_at


def test_ensure_index_rebuilds_when_knowledge_changes(knowledge, tmp_path):
    path = tmp_path / "programs.sqlite3"
    search_index.ensure_index(knowledge, path)
    # A different corpus (subset of entries) means a different fingerprint.
    subset = KnowledgeIndex(knowledge.list_entries(curated_only=True)[:10])
    assert search_index.ensure_index(subset, path) is True
    assert int(_meta(path)["entry_count"]) == 10


def test_ensure_index_rebuilds_on_corrupt_file(knowledge, tmp_path):
    path = tmp_path / "programs.sqlite3"
    path.write_bytes(b"this is not a sqlite database")
    assert search_index.ensure_index(knowledge, path) is True
    assert search_index.search(path, "granular")


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


@pytest.fixture()
def mcp_with_search(knowledge, tmp_path):
    mcp = FastMCP("test-cdp-search-programs")
    sp_module.register(
        mcp,
        knowledge_index=knowledge,
        index_path=tmp_path / "programs.sqlite3",
    )
    return mcp


async def test_tool_registered(mcp_with_search):
    names = {t.name for t in await mcp_with_search.list_tools()}
    assert "search_programs" in names


async def test_tool_happy_path(mcp_with_search):
    payload = await _call_raw(
        mcp_with_search, "search_programs", {"query": "granular stutter"}
    )
    assert payload["status"] == "ok"
    assert payload["query"] == "granular stutter"
    assert payload["result_count"] == len(payload["results"]) > 0
    top = payload["results"][0]
    assert {"program", "mode", "submode", "category", "domain"} <= set(top)


async def test_tool_empty_result_shape(mcp_with_search):
    payload = await _call_raw(
        mcp_with_search, "search_programs", {"query": "xylotelepathic"}
    )
    assert payload == {
        "status": "ok",
        "query": "xylotelepathic",
        "result_count": 0,
        "results": [],
    }


async def test_tool_filters_pass_through(mcp_with_search):
    payload = await _call_raw(
        mcp_with_search,
        "search_programs",
        {"query": "grain", "category": "granular", "domain": "time"},
    )
    assert payload["status"] == "ok"
    assert payload["results"]
    assert all(r["category"] == "granular" for r in payload["results"])
    assert all(r["domain"] == "time" for r in payload["results"])


async def test_tool_unknown_category_warns(mcp_with_search):
    payload = await _call_raw(
        mcp_with_search,
        "search_programs",
        {"query": "grain", "category": "no-such-category"},
    )
    assert payload["status"] == "ok"
    assert payload["results"] == []
    assert any("no-such-category" in w for w in payload["warnings"])
    assert any("granular" in w for w in payload["warnings"])  # lists valid


# ---------------------------------------------------------------------------
# recommend_transforms prompt
# ---------------------------------------------------------------------------


def test_prompt_function_mentions_the_workflow_tools():
    text = sp_module.recommend_transforms_prompt()
    for needle in (
        "analyze",
        "search_programs",
        "get_program_info",
        "sweep",
        "compare",
        "tag",
        "list_examples",
    ):
        assert needle in text, f"prompt text is missing {needle!r}"
    # The material-class vocabulary from docs/generalization-matrix.md.
    for klass in ("PITCHED SUSTAIN", "ARTICULATED", "BROADBAND BED", "ONE-SHOT"):
        assert klass in text


def test_prompt_function_interpolates_arguments():
    text = sp_module.recommend_transforms_prompt("bell.wav", "metallic shimmer")
    assert "bell.wav" in text
    assert "metallic shimmer" in text


async def test_register_prompt_exposes_recommend_transforms():
    mcp = FastMCP("test-cdp-search-prompt")
    sp_module.register_prompt(mcp)
    prompts = {p.name for p in await mcp.list_prompts()}
    assert "recommend_transforms" in prompts
    rendered = await mcp.get_prompt(
        "recommend_transforms", {"input_file": "bell.wav"}
    )
    joined = " ".join(str(m.content) for m in rendered.messages)
    assert "bell.wav" in joined
    assert "search_programs" in joined
