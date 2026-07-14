"""SQLite FTS5 full-text index over CDP's HTML manual.

The corpus is every ``*.htm`` / ``*.html`` file under a docs root (the real
one is ``<install>/cdpr8/docs`` with ``html/``, ``guide/``, and ``demo/``
subdirectories — a few hundred latin-1-encoded files). Each page is reduced
to plain text with stdlib ``re`` + ``html.unescape`` (no bs4 dependency)
and stored in one FTS5 row: a stable ``cdp://docs/<relpath>`` uri, a title
(from ``<title>``, else the first heading, else the filename), and the
body text.

A ``meta`` key/value table records the CDP version the index was built
from, the document count, a build timestamp, and a corpus fingerprint
(sha256 over sorted ``relpath:size`` pairs). :func:`ensure_index` rebuilds
whenever the index is missing, the recorded CDP version differs from the
current one, or the fingerprint no longer matches the files on disk.

Design-doc deviation, documented here on purpose: the design commits that
"the index records the CDP version it was built from; mismatch triggers
rebuild". That check happens *lazily* — :func:`ensure_index` runs at
tool-call time (``search_docs`` / ``read_doc`` in
:mod:`cdp_mcp.tools.docs`), not at ``set_session()``. Sessions that never
touch the docs tools never pay the index-build cost, and the staleness
check still runs before every query that could observe stale data.

Builds are atomic: the database is written to ``<index_path>.tmp`` and
moved into place with ``os.replace``, so readers never see a half-built
index.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

# Extensions that make up the manual corpus. Everything else under the
# docs root (PDFs, images, CSS) is ignored.
_HTML_SUFFIXES = (".htm", ".html")

# Number of tokens FTS5's snippet() returns around the best match.
_SNIPPET_TOKENS = 12

# CDP's HTML manual predates UTF-8 discipline; latin-1 decodes every byte
# sequence, so no page can fail to load.
_DOCS_ENCODING = "latin-1"

_URI_PREFIX = "cdp://docs/"

# ---------------------------------------------------------------------------
# HTML -> plain text (stdlib only)
# ---------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]*>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_HEADING_RE = re.compile(
    r"<h[1-6][^>]*>(.*?)</h[1-6]\s*>", re.IGNORECASE | re.DOTALL
)
_WS_RE = re.compile(r"\s+")


def _html_to_text(markup: str) -> str:
    """Strip tags/comments/scripts and collapse whitespace to one line."""
    markup = _COMMENT_RE.sub(" ", markup)
    markup = _SCRIPT_STYLE_RE.sub(" ", markup)
    markup = _TAG_RE.sub(" ", markup)
    return _WS_RE.sub(" ", unescape(markup)).strip()


def _extract_title(markup: str, fallback: str) -> str:
    """Page title: ``<title>``, else the first heading, else ``fallback``."""
    for pattern in (_TITLE_RE, _HEADING_RE):
        m = pattern.search(markup)
        if m is None:
            continue
        title = _html_to_text(m.group(1))
        if title:
            return title
    return fallback


# ---------------------------------------------------------------------------
# Corpus enumeration and fingerprinting
# ---------------------------------------------------------------------------


def _corpus_files(docs_root: Path) -> list[Path]:
    """Every HTML page under ``docs_root``, sorted for determinism."""
    return sorted(
        p
        for p in docs_root.rglob("*")
        if p.is_file() and p.suffix.lower() in _HTML_SUFFIXES
    )


def _corpus_fingerprint(files: list[Path], docs_root: Path) -> str:
    """sha256 over sorted ``relpath:size`` pairs.

    Cheap (stat only, no content reads) yet catches the realistic drift
    cases: files added, removed, renamed, or edited to a different size.
    """
    h = hashlib.sha256()
    for path in files:
        rel = path.relative_to(docs_root).as_posix()
        h.update(f"{rel}:{path.stat().st_size}\n".encode())
    return h.hexdigest()


def _doc_uri(relpath: Path) -> str:
    """Stable uri for one page: ``cdp://docs/<relpath-without-suffix>``."""
    return _URI_PREFIX + relpath.with_suffix("").as_posix()


# ---------------------------------------------------------------------------
# Build / freshness
# ---------------------------------------------------------------------------


def build_index(docs_root: Path, index_path: Path, cdp_version: str) -> None:
    """(Re)build the FTS5 index at ``index_path`` from ``docs_root``.

    Writes to a ``.tmp`` sibling and ``os.replace``s it into place so a
    crash mid-build never leaves a truncated database behind. Raises
    ``OSError`` / ``sqlite3.Error`` on filesystem or database failures;
    callers (the docs tools) translate those into structured errors.
    """
    files = _corpus_files(docs_root)
    fingerprint = _corpus_fingerprint(files, docs_root)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = index_path.with_name(index_path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE docs USING fts5(uri UNINDEXED, title, body)"
            )
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for path in files:
                markup = path.read_text(encoding=_DOCS_ENCODING)
                rel = path.relative_to(docs_root)
                conn.execute(
                    "INSERT INTO docs (uri, title, body) VALUES (?, ?, ?)",
                    (
                        _doc_uri(rel),
                        _extract_title(markup, rel.stem),
                        _html_to_text(markup),
                    ),
                )
            meta = {
                "cdp_version": cdp_version,
                "doc_count": str(len(files)),
                "built_at": datetime.now(timezone.utc).isoformat(),
                "corpus_fingerprint": fingerprint,
            }
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)", meta.items()
            )
            conn.commit()
        finally:
            conn.close()
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, index_path)


def ensure_index(docs_root: Path, index_path: Path, cdp_version: str) -> bool:
    """Build the index if missing or stale. Returns whether a build ran.

    Stale means: the recorded CDP version differs from ``cdp_version``,
    the corpus fingerprint no longer matches the files on disk, or the
    database is unreadable/corrupt. Fresh indexes are left untouched so
    repeated tool calls stay cheap (one stat pass over the corpus).
    """
    if not index_path.exists():
        build_index(docs_root, index_path, cdp_version)
        return True
    meta = _read_meta(index_path)
    if (
        meta is None
        or meta.get("cdp_version") != cdp_version
        or meta.get("corpus_fingerprint")
        != _corpus_fingerprint(_corpus_files(docs_root), docs_root)
    ):
        build_index(docs_root, index_path, cdp_version)
        return True
    return False


def _read_meta(index_path: Path) -> dict[str, str] | None:
    """The meta table as a dict, or ``None`` when the file isn't a
    healthy index (missing table, corrupt database, ...)."""
    try:
        conn = _connect_readonly(index_path)
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return dict(rows)


def _connect_readonly(index_path: Path) -> sqlite3.Connection:
    """Read-only connection — queries can never mutate a shared index."""
    return sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

_QUERY_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# FTS5 treats these as operators only when fully uppercase; a user who
# typed one almost certainly meant the operator, so requiring it as a
# literal term would only hurt recall. Lowercase "and"/"or" pass through
# as ordinary (quoted) terms.
_FTS5_OPERATOR_TOKENS = frozenset({"AND", "OR", "NOT", "NEAR"})


def _sanitize_query(query: str) -> str:
    """Reduce raw user text to a syntax-error-proof FTS5 MATCH expression.

    Word characters are extracted, bare uppercase operator words are
    stripped, and each surviving token is double-quoted — which
    neutralises the remaining FTS5 syntax (``(``, ``)``, ``*``, ``"``,
    ``-``, column filters). Tokens compose with FTS5's implicit AND.
    Returns ``""`` when nothing survives.
    """
    tokens = [
        t for t in _QUERY_TOKEN_RE.findall(query) if t not in _FTS5_OPERATOR_TOKENS
    ]
    return " ".join(f'"{token}"' for token in tokens)


def search(index_path: Path, query: str, limit: int = 8) -> list[dict]:
    """Rank pages against ``query`` with bm25; best matches first.

    Returns up to ``limit`` dicts of ``uri``, ``title``, ``snippet``
    (body excerpt with matches wrapped in ``[`` ``]``), and ``rank``
    (bm25 score — more negative is better). An operator-free empty
    query returns ``[]`` rather than erroring.
    """
    match = _sanitize_query(query)
    if not match:
        return []
    conn = _connect_readonly(index_path)
    try:
        rows = conn.execute(
            "SELECT uri, title, snippet(docs, 2, '[', ']', ' … ', ?), bm25(docs) "
            "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
            (_SNIPPET_TOKENS, match, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"uri": uri, "title": title, "snippet": snippet, "rank": rank}
        for uri, title, snippet, rank in rows
    ]


def read(index_path: Path, uri: str, max_chars: int = 20000) -> dict | None:
    """Full body text for one ``cdp://docs/...`` uri, or ``None`` if absent.

    Returns ``uri``, ``title``, ``body`` (capped at ``max_chars``),
    ``truncated`` (bool), and ``total_chars`` so callers can tell how
    much was cut.
    """
    conn = _connect_readonly(index_path)
    try:
        row = conn.execute(
            "SELECT title, body FROM docs WHERE uri = ?", (uri,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    title, body = row
    return {
        "uri": uri,
        "title": title,
        "body": body[:max_chars],
        "truncated": len(body) > max_chars,
        "total_chars": len(body),
    }
