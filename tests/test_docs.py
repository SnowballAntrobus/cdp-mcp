"""Tests for the CDP-docs FTS5 index and the search_docs/read_doc tools.

Hermetic: a tiny fake docs tree (including one latin-1 page) is built in
``tmp_path`` for everything except the final integration test, which
indexes the real ``cdpr8/docs`` corpus and skips when it isn't present.
Tool-level tests go through the registered FastMCP instance via
``_tool_manager`` with ``convert_result=False``, matching
``tests/test_introspection.py``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from cdp_mcp import docs_index
from cdp_mcp.tools import docs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BLUR_HTML = """<html><head><title>CDP BLUR Functions</title></head>
<body><!-- a comment the index must not see -->
<h1>Blur</h1>
<p>Time-average the spectral data; blurring softens attacks.</p>
<script>var indexPoison = "sweeping";</script>
</body></html>"""

_FILTER_HTML = """<html><head><title>CDP FILTER Functions</title></head>
<body><p>A sweeping filter moves its centre frequency along a breakpoint
envelope; use q to set the bandwidth of the sweeping band.</p></body></html>"""

# No <title> — title must come from the heading. Contains a latin-1 char.
_GUIDE_HTML = """<html><body><h2>Getting Started</h2>
<p>Composers caf\xe9 chat: granulate a sound, then stretch it.</p></body></html>"""

# No <title>, no heading — title must fall back to the filename stem.
_DEMO_HTML = "<html><body><p>Demo patchwork: dovetail two zigzag takes.</p></body></html>"


@pytest.fixture
def fake_docs_root(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    (root / "html").mkdir(parents=True)
    (root / "guide").mkdir()
    (root / "demo").mkdir()
    (root / "html" / "cblur.htm").write_text(_BLUR_HTML, encoding="latin-1")
    (root / "html" / "cfilter.htm").write_text(_FILTER_HTML, encoding="latin-1")
    (root / "guide" / "intro.html").write_text(_GUIDE_HTML, encoding="latin-1")
    (root / "demo" / "patchwork.htm").write_text(_DEMO_HTML, encoding="latin-1")
    return root


@pytest.fixture
def index_path(tmp_path: Path) -> Path:
    # Deliberately in a not-yet-existing subdirectory: build_index must
    # create parents itself.
    return tmp_path / "index" / "docs.sqlite3"


@pytest.fixture
def built_index(fake_docs_root: Path, index_path: Path) -> Path:
    docs_index.build_index(fake_docs_root, index_path, "r8")
    return index_path


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


def test_build_index_records_meta(built_index, fake_docs_root):
    meta = _meta(built_index)
    assert meta["cdp_version"] == "r8"
    assert meta["doc_count"] == "4"
    assert meta["built_at"]
    assert len(meta["corpus_fingerprint"]) == 64
    assert not built_index.with_name(built_index.name + ".tmp").exists()


def test_titles_from_title_tag_heading_and_filename(built_index):
    by_uri = {
        uri: docs_index.read(built_index, uri)["title"]
        for uri in (
            "cdp://docs/html/cfilter",
            "cdp://docs/guide/intro",
            "cdp://docs/demo/patchwork",
        )
    }
    assert by_uri["cdp://docs/html/cfilter"] == "CDP FILTER Functions"
    assert by_uri["cdp://docs/guide/intro"] == "Getting Started"
    assert by_uri["cdp://docs/demo/patchwork"] == "patchwork"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_finds_page_by_keyword_with_snippet(built_index):
    results = docs_index.search(built_index, "sweeping")
    assert results, "expected at least one hit for 'sweeping'"
    top = results[0]
    assert top["uri"] == "cdp://docs/html/cfilter"
    assert top["title"] == "CDP FILTER Functions"
    assert "[sweeping]" in top["snippet"]
    assert isinstance(top["rank"], float)


def test_search_ignores_script_content_and_comments(built_index):
    # "sweeping" appears in cblur.htm only inside a <script> block, and
    # the comment text must not be indexed either.
    uris = {r["uri"] for r in docs_index.search(built_index, "sweeping")}
    assert "cdp://docs/html/cblur" not in uris
    assert docs_index.search(built_index, "indexPoison") == []
    assert docs_index.search(built_index, "comment the index") == []


def test_search_unknown_word_returns_empty(built_index):
    assert docs_index.search(built_index, "xylophonic") == []


def test_search_respects_limit(built_index):
    # "the" appears in several pages; limit must cap the result count.
    assert len(docs_index.search(built_index, "the", limit=1)) == 1


def test_search_sanitizes_fts5_operators(built_index):
    # Raw user text full of FTS5 syntax must not raise OperationalError.
    hits = docs_index.search(built_index, 'sweeping" AND (filter')
    assert any(r["uri"] == "cdp://docs/html/cfilter" for r in hits)
    assert docs_index.search(built_index, '" AND ( OR NOT * NEAR/2 )') == []
    assert docs_index.search(built_index, "") == []


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_returns_full_body_with_latin1_text(built_index):
    doc = docs_index.read(built_index, "cdp://docs/guide/intro")
    assert doc is not None
    assert "caf\xe9" in doc["body"]
    assert doc["truncated"] is False
    assert doc["total_chars"] == len(doc["body"])


def test_read_truncates_at_max_chars(built_index):
    doc = docs_index.read(built_index, "cdp://docs/html/cfilter", max_chars=10)
    assert len(doc["body"]) == 10
    assert doc["truncated"] is True
    assert doc["total_chars"] > 10


def test_read_unknown_uri_returns_none(built_index):
    assert docs_index.read(built_index, "cdp://docs/html/nope") is None


# ---------------------------------------------------------------------------
# ensure_index rebuild triggers
# ---------------------------------------------------------------------------


def test_ensure_index_builds_when_missing(fake_docs_root, index_path):
    assert docs_index.ensure_index(fake_docs_root, index_path, "r8") is True
    assert index_path.exists()


def test_ensure_index_noop_when_fresh(fake_docs_root, index_path):
    docs_index.ensure_index(fake_docs_root, index_path, "r8")
    built_at = _meta(index_path)["built_at"]
    assert docs_index.ensure_index(fake_docs_root, index_path, "r8") is False
    assert _meta(index_path)["built_at"] == built_at


def test_ensure_index_rebuilds_on_version_change(fake_docs_root, index_path):
    docs_index.ensure_index(fake_docs_root, index_path, "r8")
    assert docs_index.ensure_index(fake_docs_root, index_path, "r9") is True
    assert _meta(index_path)["cdp_version"] == "r9"


def test_ensure_index_rebuilds_on_corpus_change(fake_docs_root, index_path):
    docs_index.ensure_index(fake_docs_root, index_path, "r8")
    new_page = fake_docs_root / "html" / "cnew.htm"
    new_page.write_text(
        "<html><title>New</title><body>freshly minted page</body></html>",
        encoding="latin-1",
    )
    assert docs_index.ensure_index(fake_docs_root, index_path, "r8") is True
    assert _meta(index_path)["doc_count"] == "5"
    assert docs_index.search(index_path, "freshly minted")


# ---------------------------------------------------------------------------
# derive_docs_root
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_install(tmp_path: Path) -> Path:
    """Stock CDP layout: <root>/cdpr8/_cdp/_cdprogs + <root>/cdpr8/docs."""
    cdprogs = tmp_path / "cdpr8" / "_cdp" / "_cdprogs"
    cdprogs.mkdir(parents=True)
    docs_dir = tmp_path / "cdpr8" / "docs" / "html"
    docs_dir.mkdir(parents=True)
    (docs_dir / "cblur.htm").write_text(_BLUR_HTML, encoding="latin-1")
    return cdprogs


def test_derive_docs_root_walks_up_two_levels(fake_install, monkeypatch):
    monkeypatch.delenv("CDP_MCP_DOCS_ROOT", raising=False)
    assert docs.derive_docs_root(fake_install) == fake_install.parents[1] / "docs"


def test_derive_docs_root_env_override_wins(fake_install, tmp_path, monkeypatch):
    override = tmp_path / "elsewhere"
    override.mkdir()
    monkeypatch.setenv("CDP_MCP_DOCS_ROOT", str(override))
    assert docs.derive_docs_root(fake_install) == override


def test_derive_docs_root_nothing_found(tmp_path, monkeypatch):
    monkeypatch.delenv("CDP_MCP_DOCS_ROOT", raising=False)
    bare = tmp_path / "no_docs" / "_cdp" / "_cdprogs"
    bare.mkdir(parents=True)
    assert docs.derive_docs_root(bare) is None
    assert docs.derive_docs_root(None) is None


def test_derive_docs_root_ignores_docs_dir_without_html(tmp_path, monkeypatch):
    monkeypatch.delenv("CDP_MCP_DOCS_ROOT", raising=False)
    cdprogs = tmp_path / "cdpr8" / "_cdp" / "_cdprogs"
    cdprogs.mkdir(parents=True)
    (tmp_path / "cdpr8" / "docs").mkdir()  # empty: no .htm files
    assert docs.derive_docs_root(cdprogs) is None


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_with_docs(fake_docs_root, index_path):
    mcp = FastMCP("test-cdp-docs")
    docs.register(
        mcp,
        docs_root_provider=lambda: fake_docs_root,
        index_path=index_path,
        cdp_config_provider=lambda: None,
    )
    return mcp


@pytest.fixture
def mcp_without_docs(index_path):
    mcp = FastMCP("test-cdp-nodocs")
    docs.register(
        mcp,
        docs_root_provider=lambda: None,
        index_path=index_path,
        cdp_config_provider=lambda: None,
    )
    return mcp


async def test_both_tools_registered(mcp_with_docs):
    names = {t.name for t in await mcp_with_docs.list_tools()}
    assert {"search_docs", "read_doc"} <= names


async def test_search_docs_tool_happy_path(mcp_with_docs):
    payload = await _call_raw(mcp_with_docs, "search_docs", {"query": "sweeping"})
    assert payload["status"] == "ok"
    assert payload["result_count"] >= 1
    assert payload["results"][0]["uri"] == "cdp://docs/html/cfilter"


async def test_read_doc_tool_returns_body(mcp_with_docs):
    payload = await _call_raw(
        mcp_with_docs, "read_doc", {"uri": "cdp://docs/guide/intro"}
    )
    assert payload["status"] == "ok"
    assert "caf\xe9" in payload["body"]
    assert payload["truncated"] is False


async def test_read_doc_unknown_uri_structured_error(mcp_with_docs):
    payload = await _call_raw(
        mcp_with_docs, "read_doc", {"uri": "cdp://docs/html/nope"}
    )
    assert payload["status"] == "failed"
    assert payload["errors"][0]["type"] == "doc_not_found"
    assert payload["errors"][0]["fix"]


async def test_docs_root_none_returns_docs_not_available(mcp_without_docs):
    for name, args in (
        ("search_docs", {"query": "sweeping"}),
        ("read_doc", {"uri": "cdp://docs/html/cfilter"}),
    ):
        payload = await _call_raw(mcp_without_docs, name, args)
        assert payload["status"] == "failed"
        assert payload["errors"][0]["type"] == "docs_not_available"
        assert payload["errors"][0]["fix"]


async def test_search_docs_tool_survives_fts5_operators(mcp_with_docs):
    payload = await _call_raw(
        mcp_with_docs, "search_docs", {"query": '" AND ('}
    )
    assert payload["status"] == "ok"
    assert payload["results"] == []


# ---------------------------------------------------------------------------
# Integration: real corpus
# ---------------------------------------------------------------------------

_REAL_DOCS = Path(__file__).resolve().parents[1] / "cdpr8" / "docs"


@pytest.mark.skipif(
    not _REAL_DOCS.exists(), reason="real CDP docs (cdpr8/docs) not present"
)
@pytest.mark.timeout(120)
def test_real_docs_index_and_search(tmp_path):
    index_path = tmp_path / "real_docs.sqlite3"
    docs_index.build_index(_REAL_DOCS, index_path, "r8")
    meta = _meta(index_path)
    assert int(meta["doc_count"]) > 100
    results = docs_index.search(index_path, "sweeping filter", limit=10)
    assert results, "expected hits for 'sweeping filter' in the real manual"
    assert any(
        "filt" in r["uri"] for r in results
    ), f"no filter-related uri in {[r['uri'] for r in results]}"
