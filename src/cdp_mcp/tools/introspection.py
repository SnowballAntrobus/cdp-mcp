"""Introspection tools: let the LLM ask what CDP can do.

These three tools are backed by the curated :class:`KnowledgeIndex` rather
than CDP itself — they describe what cdp-mcp knows, not what the binaries
on disk are. (Querying the binaries directly is Task 4's responsibility.)

Every tool is ``async def`` with ``ctx: Context`` as its first parameter,
matching the convention established in Task 1.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from ..knowledge.loader import KnowledgeIndex, SubmodeAmbiguousError


def _first_sentence(text: str) -> str:
    """First sentence of a description — a compact chooser summary."""
    idx = text.find(". ")
    return text[: idx + 1] if idx != -1 else text


def register(mcp: FastMCP, index: KnowledgeIndex) -> None:
    """Register the three introspection tools against ``mcp``.

    The ``index`` is captured by closure so each tool can query it without
    a module-level singleton — keeps the tools easy to test in isolation.
    """

    @mcp.tool()
    async def list_categories(ctx: Context) -> list[str]:
        """List the SoundShaper menu-group categories present in the knowledge index.

        Use this as a starting point to discover what kinds of CDP processes
        are curated. Pair with ``list_programs(category=...)`` to drill in.
        """
        return index.categories()

    @mcp.tool()
    async def list_programs(
        ctx: Context,
        category: str | None = None,
        domain: Literal["time", "spectral"] | None = None,
        curated_only: bool = True,
    ) -> list[dict]:
        """List programs (and their modes) matching the optional filters.

        Returns one short summary dict per entry — ``program``, ``mode``,
        ``submode``, ``category``, ``domain``, ``curated``,
        ``description`` — suitable for at-a-glance scanning. A pair
        curated in multiple submodes lists once per submode. Use
        :func:`get_program_info` for the full entry with parameter
        schemas and examples.

        ``category`` and ``domain`` compose with AND semantics. Pass neither
        to list everything.
        """
        entries = index.list_entries(
            category=category, domain=domain, curated_only=curated_only
        )
        return [
            {
                "program": e.program,
                "mode": e.mode,
                "submode": e.submode,
                "category": e.category,
                "domain": e.domain,
                "curated": e.curated,
                "description": e.description,
            }
            for e in entries
        ]

    @mcp.tool()
    async def get_program_info(
        ctx: Context,
        program: str,
        mode: str,
        submode: int | None = None,
    ) -> dict:
        """Return the full curated knowledge entry for ``(program, mode)``.

        Raises a tool error if no such entry exists. Use :func:`list_programs`
        to see what's available.

        Some pairs are curated in several submodes (distinct CDP
        behaviors with distinct parameters). Pass ``submode`` to fetch a
        specific one. Without ``submode``, an ambiguous pair returns a
        chooser payload instead of an error: ``{"status": "ok",
        "program", "mode", "submodes": [{"submode", "summary",
        "musical_use"}, ...]}`` — pick one and call again with
        ``submode=<n>``. Unambiguous pairs return the full entry as
        before.
        """
        if submode is not None:
            entry = index.get(program, mode, submode)
            if entry is None:
                known = [e.submode for e in index.get_pair(program, mode)]
                extra = (
                    f" Known submodes for this pair: {known}." if known else ""
                )
                raise ToolError(
                    f"No knowledge entry for {program} {mode} submode "
                    f"{submode}.{extra} "
                    "Call list_programs() to see what's available."
                )
            return entry.model_dump(mode="json")
        try:
            entry = index.get(program, mode)
        except SubmodeAmbiguousError:
            # Multiple submodes and no pick — return a chooser rather
            # than erroring, so the LLM can decide from the summaries.
            return {
                "status": "ok",
                "program": program,
                "mode": mode,
                "submodes": [
                    {
                        "submode": e.submode,
                        "summary": _first_sentence(e.description),
                        "musical_use": e.musical_use,
                    }
                    for e in index.get_pair(program, mode)
                ],
            }
        if entry is None:
            raise ToolError(
                f"No knowledge entry for {program} {mode}. "
                "Call list_programs() to see what's available."
            )
        return entry.model_dump(mode="json")
