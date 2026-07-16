"""Documentation tools: search and read CDP's official HTML manual.

Two tools live here:

- ``search_docs(query, limit)`` — full-text search (SQLite FTS5, bm25)
  over the manual pages shipped with the CDP install.
- ``read_doc(uri)`` — fetch the plain-text body of one page by the
  ``cdp://docs/...`` uri that ``search_docs`` returned. It also serves
  the rest of the ``cdp://`` namespace: ``cdp://examples/...`` uris
  (from ``list_examples``) dispatch to
  :func:`cdp_mcp.tools.examples.read_example_uri` — those are package
  data and never require a CDP manual install.

Both are backed by :mod:`cdp_mcp.docs_index`, with the docs root and the
index location captured by closure in :func:`register`, mirroring the
knowledge-index pattern from :mod:`cdp_mcp.tools.introspection`. These
are introspection-style tools: results are plain dicts, no
ResultEnvelope/context block.

Unlike the introspection tools these don't raise ``ToolError`` for the
"docs aren't installed" case — a missing manual is an environment state
the LLM should route around, not a malformed call — so both tools return
a structured ``{status: "failed", errors: [...]}`` dict with a
``docs_not_available`` entry instead.

The index freshness check (CDP version + corpus fingerprint) runs lazily
on every tool call via :func:`cdp_mcp.docs_index.ensure_index`; see that
module's docstring for why it's not hooked into ``set_session()``.
Building is synchronous CPU/disk work, so it runs through
``asyncio.to_thread`` to keep MCP heartbeats alive.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from .. import docs_index
from ..config import CDPConfig
from . import examples as examples_module

# Environment override for the docs root; wins over any derivation.
_DOCS_ROOT_ENV = "CDP_MCP_DOCS_ROOT"

# How many ancestors of cdp_path derive_docs_root inspects (inclusive of
# cdp_path itself). The real layout needs two hops (_cdprogs -> _cdp ->
# cdpr8/docs); the cap keeps us from wandering up to / and adopting some
# unrelated "docs" directory.
_MAX_WALK_UP = 4

# Defensive cap on search_docs' limit argument — the manual has a few
# hundred pages; nobody needs more than this per query.
_MAX_SEARCH_LIMIT = 50


def derive_docs_root(cdp_path: Path | None) -> Path | None:
    """Locate the CDP HTML manual relative to the CDP binaries directory.

    ``$CDP_MCP_DOCS_ROOT`` wins when set (and points at a directory).
    Otherwise walk up from ``cdp_path`` (the ``_cdprogs`` dir) looking
    for an ancestor that contains a ``docs`` directory holding ``.htm``
    / ``.html`` files — the stock layout is ``<root>/cdpr8/_cdp/_cdprogs``
    with the manual at ``<root>/cdpr8/docs``, two levels up. Returns
    ``None`` when nothing plausible is found.
    """
    override = os.environ.get(_DOCS_ROOT_ENV)
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_dir() else None
    if cdp_path is None:
        return None
    for ancestor in [cdp_path, *cdp_path.parents][: _MAX_WALK_UP + 1]:
        candidate = ancestor / "docs"
        if candidate.is_dir() and _contains_html(candidate):
            return candidate
    return None


def _contains_html(directory: Path) -> bool:
    """True when at least one .htm/.html file lives under ``directory``."""
    try:
        for pattern in ("*.htm", "*.html"):
            if next(directory.rglob(pattern), None) is not None:
                return True
    except OSError:
        return False
    return False


def register(
    mcp: FastMCP,
    *,
    docs_root_provider: Callable[[], Path | None],
    index_path: Path,
    cdp_config_provider: Callable[[], CDPConfig | None],
) -> None:
    """Register the documentation tools against ``mcp``.

    ``docs_root_provider`` returns the manual's root directory (or
    ``None`` when no docs are installed); ``index_path`` is where the
    FTS5 database lives; ``cdp_config_provider`` supplies the CDP
    version stamped into the index for staleness detection.
    """

    async def _ready_index() -> dict | None:
        """Bring the index up to date; a structured error dict on failure."""
        docs_root = docs_root_provider()
        if docs_root is None:
            return _docs_not_available(
                "CDP documentation was not found on this machine."
            )
        config = cdp_config_provider()
        cdp_version = config.version if config is not None else "unknown"
        try:
            await asyncio.to_thread(
                docs_index.ensure_index, docs_root, index_path, cdp_version
            )
        except (OSError, sqlite3.Error) as e:
            return _docs_not_available(
                f"Building the documentation index failed: {e}"
            )
        return None

    @mcp.tool()
    async def search_docs(ctx: Context, query: str, limit: int = 8) -> dict:
        """Full-text search over CDP's official HTML manual.

        This searches the reference documentation shipped with the CDP
        install — program pages, parameter explanations, tutorials, and
        guides — and is the place to look things up that the curated
        knowledge index (``list_programs`` / ``get_program_info``)
        doesn't cover. Plain keywords work best; operators are treated
        as literal words.

        Returns ``status`` plus a ``results`` list of ``uri``, ``title``,
        ``snippet`` (matches wrapped in ``[`` ``]``), and ``rank`` (lower
        is better), best matches first. Pass a returned ``uri`` to
        :func:`read_doc` to read the full page. Returns a
        ``docs_not_available`` error dict when no CDP documentation is
        installed.
        """
        error = await _ready_index()
        if error is not None:
            return error
        limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        results = await asyncio.to_thread(
            docs_index.search, index_path, query, limit
        )
        return {
            "status": "ok",
            "query": query,
            "result_count": len(results),
            "results": results,
        }

    @mcp.tool()
    async def read_doc(ctx: Context, uri: str) -> dict:
        """Read one ``cdp://`` resource as plain text.

        ``cdp://docs/...`` uris (from :func:`search_docs`) return one
        page of CDP's official manual: ``status``, ``uri``, ``title``,
        ``body`` (truncated at 20,000 characters), ``truncated``, and
        ``total_chars``. ``cdp://examples/...`` uris (from
        ``list_examples``) return a verified chain example: metadata
        plus a ready-to-run ``definition`` for ``graph()``. Unknown
        uris and missing documentation come back as structured error
        dicts rather than exceptions.
        """
        if uri.startswith("cdp://examples/"):
            # Package data — served even when no CDP manual is installed.
            return examples_module.read_example_uri(uri)
        error = await _ready_index()
        if error is not None:
            return error
        doc = await asyncio.to_thread(docs_index.read, index_path, uri)
        if doc is None:
            return {
                "status": "failed",
                "errors": [
                    {
                        "type": "doc_not_found",
                        "message": f"No manual page with uri {uri!r}.",
                        "fix": (
                            "Call search_docs(query) and pass one of the "
                            "returned uris verbatim."
                        ),
                    }
                ],
            }
        return {"status": "ok", **doc}


def _docs_not_available(message: str) -> dict:
    """The shared failure shape for 'no manual to search'."""
    return {
        "status": "failed",
        "errors": [
            {
                "type": "docs_not_available",
                "message": message,
                "fix": (
                    "Install the CDP documentation alongside the binaries "
                    "(a docs/ directory near CDP_PATH) or point the "
                    "CDP_MCP_DOCS_ROOT environment variable at the folder "
                    "containing the HTML manual."
                ),
            }
        ],
    }
