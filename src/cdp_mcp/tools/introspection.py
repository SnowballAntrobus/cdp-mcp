"""Introspection tools: let the LLM ask what CDP can do.

Every tool in this project is ``async def`` and takes ``ctx: Context`` as its
first parameter, even trivial stubs. The pattern is mandatory because later
tasks (subprocess execution, progress reporting) rely on it.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

# Phase 1a stub — Task 2 will replace this with the knowledge-layer-backed
# implementation. Keep the list small and unsurprising; it's only here so we
# can verify the MCP wiring end-to-end.
_STUB_CATEGORIES = [
    "spectral",
    "time-domain",
    "synthesis",
    "envelope",
    "filter",
    "pitch",
    "texture",
    "housekeep",
]


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_categories(ctx: Context) -> list[str]:
        """List top-level CDP program categories.

        Phase 1a: returns a static stub list. Task 2 will replace this with the
        curated knowledge-layer index.
        """
        return _STUB_CATEGORIES
