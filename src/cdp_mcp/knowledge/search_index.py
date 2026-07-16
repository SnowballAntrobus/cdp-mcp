"""SQLite FTS5 full-text index over the CURATED knowledge entries.

Where :mod:`cdp_mcp.docs_index` indexes CDP's HTML manual (reference
prose, covering curated and uncurated programs indiscriminately), this
module indexes what the curated knowledge itself says: each entry's
name tokens, category/domain, description, ``musical_use``, parameter
names + descriptions, ``known_issues``, and stability. It backs the
``search_programs`` tool — "which curated program is FOR this musical
idea" — and deliberately mirrors docs_index's architecture: a lazily
built sqlite file at a caller-supplied path, a ``meta`` key/value table
with a content fingerprint, atomic tmp+``os.replace`` builds, read-only
query connections, and bm25 ranking with snippet extraction.

One FTS5 row per curated entry (uncurated stubs are excluded — they
carry no musical knowledge to search). The ``(program, mode, submode)``
triple plus ``category``/``domain`` are stored UNINDEXED as payload and
filter columns; the searchable columns are bm25-weighted so name tokens
("blur chorus") beat taxonomy ("granular spectral"), which beats
``musical_use``, then ``description``, then parameter text and issues.

Freshness is keyed on a fingerprint of the loaded knowledge — entry
count plus a sha256 over every curated entry's canonical JSON — so
:func:`ensure_index` rebuilds when any entry is added, removed, or
edited, and otherwise costs one meta-table read. There is no CDP-version
component: the knowledge is package data, independent of the installed
binaries.

Query semantics: tokens are extracted and double-quoted exactly like
docs_index (immune to FTS5 syntax), with two curated-prose adaptations:
English stopwords are dropped ("make it shimmer and sustain" ranks on
shimmer/sustain, not on which entry says "it" most), and tokens are
prefix-matched (no stemming in unicode61; "chop"* also hits "chopped").
The tokens are tried first with FTS5's implicit AND for precision; when
that matches nothing they are retried OR-composed so bm25 can rank rows
by the informative terms. Callers just see one ranked result list.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..schema import KnowledgeEntry
from .loader import KnowledgeIndex

# Number of tokens FTS5's snippet() returns around the best match.
_SNIPPET_TOKENS = 12

# musical_use is returned with every hit; cap it so eight results stay a
# skim, not a wall. Full text is one get_program_info() away.
_MUSICAL_USE_CHARS = 200

# Bumped whenever the table layout / row-text builders change, forcing a
# rebuild of indexes built by older code (the knowledge fingerprint alone
# can't see code changes).
_INDEX_FORMAT = "1"

# Column layout of the ``entries`` FTS5 table, in declaration order. The
# first five are UNINDEXED payload/filter columns (the entry key and the
# category/domain filters); the rest are the searchable text.
_COLUMNS = (
    "program",
    "mode",
    "submode",
    "category",
    "domain",
    "name",
    "taxonomy",
    "description",
    "musical_use",
    "parameters",
    "issues",
)
_COLUMNS_SQL = (
    "program UNINDEXED, mode UNINDEXED, submode UNINDEXED, "
    "category UNINDEXED, domain UNINDEXED, "
    "name, taxonomy, description, musical_use, parameters, issues"
)

# bm25 weights, one per column in declaration order (SQLite requires the
# full set; UNINDEXED columns never match, so their weights are inert).
# name > taxonomy > musical_use > description > parameters > issues:
# an entry literally named what you typed should win, a category match
# ("granular") should beat an incidental prose mention, and the curated
# "what it's for" text outranks the mechanical description.
_BM25_WEIGHTS = "0, 0, 0, 0, 0, 6.0, 4.0, 2.0, 3.0, 1.0, 0.5"


# ---------------------------------------------------------------------------
# Row text
# ---------------------------------------------------------------------------


def _name_text(entry: KnowledgeEntry) -> str:
    """Name tokens, e.g. ``"blur chorus"``. FTS5's unicode61 tokenizer
    splits on ``_``/``-`` itself, so compound names need no massaging."""
    return f"{entry.program} {entry.mode}"


def _taxonomy_text(entry: KnowledgeEntry) -> str:
    """Category + domain as searchable tokens (``"granular time"``)."""
    return f"{entry.category} {entry.domain}"


def _parameters_text(entry: KnowledgeEntry) -> str:
    """Parameter names and their curated descriptions, concatenated."""
    parts: list[str] = []
    for pname, spec in entry.parameters.items():
        parts.append(pname)
        if spec.description:
            parts.append(spec.description)
    return " ".join(parts)


def _issues_text(entry: KnowledgeEntry) -> str:
    """Stability plus the known_issues strings — lets "buggy", "unstable",
    or an issue's own wording ("clicks", "mono only") match."""
    return " ".join([entry.stability, *entry.known_issues])


def _row(entry: KnowledgeEntry) -> tuple[str, ...]:
    """One FTS5 row for ``entry``, in ``_COLUMNS`` order. ``submode`` is
    stored as text (``""`` for ``None``) — FTS5 columns are text."""
    return (
        entry.program,
        entry.mode,
        "" if entry.submode is None else str(entry.submode),
        entry.category,
        entry.domain,
        _name_text(entry),
        _taxonomy_text(entry),
        entry.description,
        entry.musical_use,
        _parameters_text(entry),
        _issues_text(entry),
    )


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def _curated_entries(knowledge: KnowledgeIndex) -> list[KnowledgeEntry]:
    """The indexable corpus: curated entries only, in the loader's stable
    (program, mode, submode) order — determinism matters for the hash."""
    return knowledge.list_entries(curated_only=True)


def _fingerprint(entries: list[KnowledgeEntry]) -> str:
    """sha256 over the entry count plus every entry's canonical JSON.

    Unlike docs_index's stat-based corpus fingerprint there are no files
    to stat here — the knowledge is already in memory — so hashing full
    content is both exact and cheap (a few hundred small models).
    """
    h = hashlib.sha256()
    h.update(f"{len(entries)}\n".encode())
    for entry in entries:
        h.update(entry.model_dump_json().encode())
        h.update(b"\n")
    return h.hexdigest()


def knowledge_fingerprint(knowledge: KnowledgeIndex) -> str:
    """Fingerprint of ``knowledge``'s curated entries (see _fingerprint)."""
    return _fingerprint(_curated_entries(knowledge))


# ---------------------------------------------------------------------------
# Build / freshness
# ---------------------------------------------------------------------------


def build_index(knowledge: KnowledgeIndex, index_path: Path) -> None:
    """(Re)build the FTS5 index at ``index_path`` from ``knowledge``.

    Mirrors docs_index.build_index: writes to a ``.tmp`` sibling and
    ``os.replace``s it into place, so a crash mid-build never leaves a
    truncated database. Raises ``OSError`` / ``sqlite3.Error``; the
    tool layer translates those into structured errors.
    """
    entries = _curated_entries(knowledge)
    fingerprint = _fingerprint(entries)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = index_path.with_name(index_path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE entries USING fts5({_COLUMNS_SQL})"
            )
            conn.execute(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            placeholders = ", ".join("?" * len(_COLUMNS))
            conn.executemany(
                f"INSERT INTO entries ({', '.join(_COLUMNS)}) "
                f"VALUES ({placeholders})",
                (_row(e) for e in entries),
            )
            meta = {
                "index_format": _INDEX_FORMAT,
                "entry_count": str(len(entries)),
                "built_at": datetime.now(timezone.utc).isoformat(),
                "knowledge_fingerprint": fingerprint,
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


def ensure_index(knowledge: KnowledgeIndex, index_path: Path) -> bool:
    """Build the index if missing or stale. Returns whether a build ran.

    Stale means: the recorded index format differs from this code's, the
    knowledge fingerprint no longer matches the loaded entries, or the
    database is unreadable/corrupt. A fresh index is left untouched, so
    repeated tool calls cost one fingerprint pass over in-memory models.
    """
    if not index_path.exists():
        build_index(knowledge, index_path)
        return True
    meta = _read_meta(index_path)
    if (
        meta is None
        or meta.get("index_format") != _INDEX_FORMAT
        or meta.get("knowledge_fingerprint") != knowledge_fingerprint(knowledge)
    ):
        build_index(knowledge, index_path)
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

# Same rationale as docs_index: fully-uppercase operator words were almost
# certainly meant as operators, so requiring them as literal terms would
# only hurt recall. Lowercase "and"/"or" pass through as ordinary terms.
_FTS5_OPERATOR_TOKENS = frozenset({"AND", "OR", "NOT", "NEAR"})

# English function words (plus a couple of request fillers like "make")
# dropped from queries before matching. The entries are long curated
# prose, so nearly every row contains "it"/"and"/"into"; under the OR
# fallback those terms reward verbose entries over relevant ones — for
# "make it shimmer and sustain" the shimmer/sustain entries must win.
# Deliberately conservative: no musical vocabulary ("warm", "dark",
# "soft" stay), and if filtering would leave nothing, the original
# tokens are kept so an all-stopword query degrades instead of dying.
_QUERY_STOPWORDS = frozenset(
    """a an the and or but not it its this that these those there then than
    so as is are be was were being been do does did can could should would
    i you we me my your our their them they he she of in on at to for with
    into onto from by about over under out up down off want wants need
    needs make makes made give gives turn turns get gets like please something
    sound sounds""".split()
)


def _query_tokens(query: str) -> list[str]:
    """Word tokens from raw user text, minus bare FTS5 operator words
    and (when anything else survives) English stopwords."""
    tokens = [
        t for t in _QUERY_TOKEN_RE.findall(query) if t not in _FTS5_OPERATOR_TOKENS
    ]
    content = [t for t in tokens if t.lower() not in _QUERY_STOPWORDS]
    return content or tokens


def _truncate(text: str, limit: int = _MUSICAL_USE_CHARS) -> str:
    """Cap ``text`` at ~``limit`` chars, cutting at a word boundary."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + " …"


def search(
    index_path: Path,
    query: str,
    limit: int = 8,
    category: str | None = None,
    domain: str | None = None,
) -> list[dict]:
    """Rank curated entries against ``query`` with bm25; best first.

    ``category`` / ``domain`` narrow the result set with AND semantics
    (they filter, they don't rank). Tokens are first composed with
    FTS5's implicit AND; if nothing survives that (and the filters),
    the same tokens are retried OR-composed so descriptive phrases
    still rank by their informative words.

    Returns up to ``limit`` dicts of ``program``, ``mode``, ``submode``
    (the ``get_program_info`` key), ``category``, ``domain``, ``score``
    (bm25 — more negative is better), ``snippet`` (matched terms
    wrapped in ``[`` ``]``), and ``musical_use`` (truncated to ~200
    chars). An operator-free empty query returns ``[]``.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return []
    # Prefix-match tokens of >= 3 chars ("chop"* also hits "chopped",
    # "shimmer"* hits "shimmering") — unicode61 has no stemming, and the
    # curated prose freely inflects its musical vocabulary. Short tokens
    # stay exact so "2" doesn't swallow every number in the corpus.
    quoted = [f'"{t}"*' if len(t) >= 3 else f'"{t}"' for t in tokens]
    rows = _run_query(index_path, " ".join(quoted), limit, category, domain)
    if not rows and len(quoted) > 1:
        rows = _run_query(
            index_path, " OR ".join(quoted), limit, category, domain
        )
    return rows


def _run_query(
    index_path: Path,
    match: str,
    limit: int,
    category: str | None,
    domain: str | None,
) -> list[dict]:
    """Execute one MATCH expression with optional key-column filters."""
    where = ["entries MATCH ?"]
    args: list[object] = [match]
    if category is not None:
        where.append("category = ?")
        args.append(category)
    if domain is not None:
        where.append("domain = ?")
        args.append(domain)
    args.append(limit)
    sql = (
        "SELECT program, mode, submode, category, domain, "
        f"bm25(entries, {_BM25_WEIGHTS}) AS score, "
        # Column -1: snippet() picks the best-matching indexed column.
        f"snippet(entries, -1, '[', ']', ' … ', {_SNIPPET_TOKENS}), "
        "musical_use "
        f"FROM entries WHERE {' AND '.join(where)} "
        "ORDER BY score LIMIT ?"
    )
    conn = _connect_readonly(index_path)
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    return [
        {
            "program": program,
            "mode": mode,
            "submode": int(submode) if submode != "" else None,
            "category": cat,
            "domain": dom,
            "score": score,
            "snippet": snippet,
            "musical_use": _truncate(musical_use),
        }
        for program, mode, submode, cat, dom, score, snippet, musical_use in rows
    ]
