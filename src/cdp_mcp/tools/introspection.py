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

from ..knowledge.loader import KnowledgeIndex


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
        ``category``, ``domain``, ``curated``, ``description`` — suitable
        for at-a-glance scanning. Use :func:`get_program_info` for the full
        entry with parameter schemas and examples.

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
                "category": e.category,
                "domain": e.domain,
                "curated": e.curated,
                "description": e.description,
            }
            for e in entries
        ]

    @mcp.tool()
    async def get_program_info(ctx: Context, program: str, mode: str) -> dict:
        """Return the full curated knowledge entry for ``(program, mode)``.

        Raises a tool error if no such entry exists. Use :func:`list_programs`
        to see what's available. In Phase 1a every curated program has exactly
        one curated mode, so the call requires both arguments explicitly.
        """
        entry = index.get(program, mode)
        if entry is None:
            raise ToolError(
                f"No knowledge entry for {program} {mode}. "
                "Call list_programs() to see what's available."
            )
        return entry.model_dump(mode="json")
