"""Workspace tools: create/switch sessions, describe the current state.

Two tools live here in Phase 1a:

- ``set_session(name)`` — activate (or create) the named session on disk.
- ``describe_workspace()`` — return situational awareness for the active
  session, including a count of input files and known sibling sessions.

Both follow Task 1's convention: ``async def`` with ``ctx: Context`` first.
Both are backed by a :class:`~cdp_mcp.session.SessionManager` captured by
closure in :func:`register`, mirroring the knowledge-index pattern from
Task 2's :mod:`cdp_mcp.tools.introspection`.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from ..session import (
    Session,
    SessionInitError,
    SessionManager,
    SessionNameError,
)


def register(mcp: FastMCP, sessions: SessionManager) -> None:
    """Register the workspace tools against ``mcp``."""

    @mcp.tool()
    async def set_session(ctx: Context, name: str) -> dict:
        """Activate (or create) a named session.

        Sessions are directories under the sessions root that hold a piece of
        work's inputs, graphs, and metadata. First call with a fresh name
        creates the directory layout; subsequent calls with the same name
        just switch active state in memory.

        Returns a small dict describing the activated session. Raises a
        tool error on invalid names or filesystem failures.
        """
        try:
            session, created = sessions.set_active(name)
        except SessionNameError as e:
            raise ToolError(str(e)) from e
        except SessionInitError as e:
            raise ToolError(str(e)) from e
        return _set_session_response(session, created=created)

    @mcp.tool()
    async def describe_workspace(ctx: Context) -> dict:
        """Return situational awareness for the active session.

        With no session active, returns a small dict listing any sessions
        already on disk plus a hint to call :func:`set_session`. With a
        session active, returns the session's path, creation timestamp, CDP
        version captured at creation, a flat listing of input filenames,
        and a recursive disk-usage estimate.

        Designed to grow: later tasks will add recent_graphs detail
        (Task 4) and available_sources (Task 6) here.
        """
        active = sessions.active
        available = sessions.list_sessions()
        if active is None:
            return {
                "active_session": None,
                "available_sessions": available,
                "hint": "Call set_session(name) to activate or create one.",
            }
        return _describe_active(active, available)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _set_session_response(session: Session, *, created: bool) -> dict:
    return {
        "name": session.name,
        "path": str(session.root),
        "created": created,
        "cdp_version": session.config.cdp_version,
        "inputs_dir": str(session.inputs_dir),
        "graphs_count": _count_dirs(session.graphs_dir),
    }


def _describe_active(session: Session, available_sessions: list[str]) -> dict:
    input_files = _list_input_files(session)
    return {
        "active_session": session.name,
        "session_path": str(session.root),
        "session_created_at": session.config.created_at.isoformat(),
        "cdp_version_at_creation": session.config.cdp_version,
        "input_files": input_files,
        "input_count": len(input_files),
        "graph_count": _count_dirs(session.graphs_dir),
        "disk_usage_bytes": _disk_usage(session.root),
        "available_sessions": available_sessions,
    }


def _list_input_files(session: Session) -> list[str]:
    if not session.inputs_dir.exists():
        return []
    return sorted(
        p.name for p in session.inputs_dir.iterdir() if p.is_file()
    )


def _count_dirs(path) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.iterdir() if p.is_dir())


def _disk_usage(root) -> int:
    """Recursive sum of file sizes under ``root``.

    Phase 1a uses a naive ``rglob`` — fine for sessions with a handful of
    inputs and a few graphs. Revisit if it becomes slow in practice.
    """
    if not root.exists():
        return 0
    total = 0
    for f in root.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                # File could have disappeared mid-walk; skip silently.
                continue
    return total
