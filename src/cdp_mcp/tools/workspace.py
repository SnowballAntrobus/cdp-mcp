"""Workspace tools: create/switch sessions, describe the current state.

Three tools live here:

- ``set_session(name)`` — activate (or create) the named session on disk.
- ``describe_workspace()`` — return situational awareness for the active
  session, including counts of input files and envelope files and known
  sibling sessions.
- ``read_envelope(name)`` — read a `.brk` / `.txt` artifact from the
  active session's ``envelopes/`` directory. Lets the LLM introspect
  user-supplied breakpoint files without copy-paste.

All follow Task 1's convention: ``async def`` with ``ctx: Context`` first.
All are backed by a :class:`~cdp_mcp.session.SessionManager` captured by
closure in :func:`register`, mirroring the knowledge-index pattern from
Task 2's :mod:`cdp_mcp.tools.introspection`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from ..config import CDPConfig
from ..graph import LatestTracker
from ..session import (
    Session,
    SessionInitError,
    SessionManager,
    SessionNameError,
    cdp_version_mismatch_warning,
)


def register(
    mcp: FastMCP,
    sessions: SessionManager,
    latest_tracker: LatestTracker,
    cdp_config_provider: Callable[[], CDPConfig | None],
) -> None:
    """Register the workspace tools against ``mcp``."""

    @mcp.tool()
    async def set_session(ctx: Context, name: str) -> dict:
        """Activate (or create) a named session.

        Sessions are directories under the sessions root that hold a piece of
        work's inputs, graphs, and metadata. First call with a fresh name
        creates the directory layout; subsequent calls with the same name
        just switch active state in memory.

        Resets the in-memory conversational state (``latest``,
        ``prev_1`` .. ``prev_4``) so the new activation starts with no
        aliases. Does not affect on-disk graphs or ``cache_index.json``.

        If the session's recorded CDP version differs from the currently
        installed one, a one-line warning naming both versions appears
        in the response's ``warnings`` list. This is advisory —
        activation proceeds regardless.

        Returns a small dict describing the activated session. Raises a
        tool error on invalid names or filesystem failures.
        """
        try:
            session, created = sessions.set_active(name)
        except SessionNameError as e:
            raise ToolError(str(e)) from e
        except SessionInitError as e:
            raise ToolError(str(e)) from e
        latest_tracker.clear()
        warnings: list[str] = []
        mismatch = cdp_version_mismatch_warning(session, cdp_config_provider())
        if mismatch is not None:
            warnings.append(mismatch)
        return _set_session_response(session, created=created, warnings=warnings)

    @mcp.tool()
    async def describe_workspace(ctx: Context) -> dict:
        """Return situational awareness for the active session.

        With no session active, returns a small dict listing any sessions
        already on disk plus a hint to call :func:`set_session`. With a
        session active, returns the session's path, creation timestamp, CDP
        version captured at creation, a flat listing of input filenames,
        a flat listing of envelope filenames (``.brk`` and similar), and
        a recursive disk-usage estimate.
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

    @mcp.tool()
    async def read_envelope(ctx: Context, name: str) -> dict:
        """Read a text artifact from the active session's ``envelopes/``.

        Useful for inspecting user-supplied breakpoint (``.brk``) files
        before feeding them to ``process()``, or for confirming the
        engine-compiled ``.brk`` content that ``process()`` writes
        whenever you pass a breakpoint list. Phase 1b supports ``.brk``
        and ``.txt`` extensions.

        Args:
            name: A bare basename inside ``envelopes/``. Path separators
                and ``..`` are rejected — point at a file directly in
                the envelopes directory.

        Returns a dict with ``name``, ``path``, ``size_bytes``,
        ``content`` (UTF-8 text, truncated at 64 KiB), and ``truncated``
        (bool). Raises a tool error when no session is active, the name
        is invalid, the extension is unsupported, or the file doesn't
        exist.
        """
        session = sessions.active
        if session is None:
            raise ToolError(
                "No active session. Call set_session(<name>) first."
            )
        return _read_envelope(session, name)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _set_session_response(
    session: Session,
    *,
    created: bool,
    warnings: list[str],
) -> dict:
    return {
        "name": session.name,
        "path": str(session.root),
        "created": created,
        "cdp_version": session.config.cdp_version,
        "inputs_dir": str(session.inputs_dir),
        "graphs_count": _count_dirs(session.graphs_dir),
        "warnings": warnings,
    }


def _describe_active(session: Session, available_sessions: list[str]) -> dict:
    input_files = _list_input_files(session)
    envelope_files = _list_envelope_files(session)
    return {
        "active_session": session.name,
        "session_path": str(session.root),
        "session_created_at": session.config.created_at.isoformat(),
        "cdp_version_at_creation": session.config.cdp_version,
        "input_files": input_files,
        "input_count": len(input_files),
        "envelope_files": envelope_files,
        "envelope_count": len(envelope_files),
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


def _list_envelope_files(session: Session) -> list[str]:
    """Sorted basenames in ``envelopes/``. Files only — skips subdirs."""
    if not session.envelopes_dir.exists():
        return []
    return sorted(
        p.name for p in session.envelopes_dir.iterdir() if p.is_file()
    )


# Cap envelope content returned by read_envelope. Realistic .brk files are
# at most a few KB; this is defensive against pathological cases.
_READ_ENVELOPE_MAX_BYTES = 64 * 1024
_READ_ENVELOPE_ALLOWED_EXTENSIONS = (".brk", ".txt")


def _read_envelope(session: Session, name: str) -> dict:
    """Implement read_envelope's body. Lives at module scope so tests
    can exercise the validation directly if needed."""
    if "/" in name or "\\" in name or name in ("", ".", "..") or name.startswith("."):
        raise ToolError(
            f"Invalid envelope name {name!r}: must be a bare basename "
            "inside envelopes/ (no path separators, no '..')."
        )
    suffix = Path(name).suffix.lower()
    if suffix not in _READ_ENVELOPE_ALLOWED_EXTENSIONS:
        raise ToolError(
            f"Unsupported envelope extension {suffix!r}: "
            f"read_envelope accepts {_READ_ENVELOPE_ALLOWED_EXTENSIONS}."
        )
    target = session.envelopes_dir / name
    if not target.is_file():
        raise ToolError(
            f"Envelope file not found: {target}. "
            f"Call describe_workspace() to list available envelope files."
        )
    raw = target.read_bytes()
    truncated = len(raw) > _READ_ENVELOPE_MAX_BYTES
    payload = raw[:_READ_ENVELOPE_MAX_BYTES] if truncated else raw
    content = payload.decode("utf-8", errors="replace")
    return {
        "name": name,
        "path": str(target),
        "size_bytes": len(raw),
        "content": content,
        "truncated": truncated,
    }


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
