"""``list_session_files()``: glob over the session tree (excluding
``tmp/``) with relative paths and sizes, so the LLM can answer "what's on
disk?" without walking ``describe_workspace``'s coarser summary.

Failures follow the house structured-error convention:
``{"status": "failed", "errors": [ErrorEntry...]}``.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import Context, FastMCP

from ..schema import ErrorEntry
from ..session import Session, SessionManager, SessionNotActiveError

# list_session_files response cap. Sessions with more matching files get
# the first 500 (sorted) plus truncated=true.
_MAX_LISTING_ENTRIES = 500


def register(mcp: FastMCP, *, sessions: SessionManager) -> None:
    """Register ``list_session_files`` against ``mcp``."""

    @mcp.tool()
    async def list_session_files(ctx: Context, pattern: str = "*") -> dict:
        """List files in the active session tree, with sizes.

        ``pattern`` is a glob: a bare pattern like ``*.wav`` matches at
        every depth (both ``*.wav`` and ``**/*.wav``); a pattern with a
        ``/`` (e.g. ``inputs/*.wav`` or ``graphs/**/*.ana``) is used
        as-is relative to the session root. ``tmp/`` is always
        excluded — its contents are disposable rendering aids.

        Returns ``{status, pattern, files: [{path, size_bytes}, ...],
        count, truncated}`` with session-relative paths, sorted, capped
        at 500 entries (``truncated: true`` beyond that).
        """
        try:
            session = sessions.require_active()
        except SessionNotActiveError as e:
            return _failed([ErrorEntry(
                type="no_active_session",
                message=str(e),
                fix="Call set_session('<name>') first.",
            )])
        if (
            not isinstance(pattern, str)
            or not pattern
            or pattern.startswith(("/", "\\"))
            or ".." in pattern.split("/")
        ):
            return _failed([ErrorEntry(
                type="pattern_invalid",
                message=(
                    f"Invalid pattern {pattern!r}: must be a non-empty "
                    "session-relative glob (no leading '/', no '..')."
                ),
                fix="Use a glob like '*.wav' or 'graphs/**/*.ana'.",
            )])
        # The glob walk is disk work — off the event loop.
        return await asyncio.to_thread(_list_files, session, pattern)


# ---------------------------------------------------------------------------
# Implementation (sync — runs inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _list_files(session: Session, pattern: str) -> dict:
    root = session.root
    # A bare pattern matches at every depth; a pattern that already
    # carries a '/' addresses a specific subtree and is used verbatim.
    patterns = [pattern] if "/" in pattern else [pattern, f"**/{pattern}"]
    entries: dict[str, int] = {}
    for pat in patterns:
        for p in root.glob(pat):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if rel.parts and rel.parts[0] == "tmp":
                continue  # tmp/ is disposable rendering scratch
            try:
                entries[rel.as_posix()] = p.stat().st_size
            except OSError:
                continue  # disappeared mid-walk; skip silently
    ordered = sorted(entries.items())
    truncated = len(ordered) > _MAX_LISTING_ENTRIES
    files = [
        {"path": path, "size_bytes": size}
        for path, size in ordered[:_MAX_LISTING_ENTRIES]
    ]
    return {
        "status": "ok",
        "pattern": pattern,
        "files": files,
        "count": len(files),
        "truncated": truncated,
    }


def _failed(errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "errors": [e.model_dump(mode="json") for e in errors],
    }
