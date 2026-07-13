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

import asyncio
import json
import re
from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from ..cache import cache_size_bytes
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
    cache_root: Path,
) -> None:
    """Register the workspace tools against ``mcp``.

    ``cache_root`` is the global derivative-artifact cache root (e.g.
    ``~/.cdp_mcp/cache``); ``describe_workspace`` reports its per-tier
    byte counts so users can see disk pressure.
    """

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
        a flat listing of envelope filenames (``.brk`` and similar), a
        ``history`` mapping of every graph ID in the session to its
        primary output filename (explicit recall for graphs that have
        scrolled out of the conversational ``recent_graphs`` window —
        reference them as ``<graph_id>:<node_id>``), a recursive
        disk-usage estimate, and a ``cache`` block summarising per-tier
        byte counts of the global derivative-artifact cache.
        """
        active = sessions.active
        available = sessions.list_sessions()
        # Disk walks (cache rglob + recursive session du) run off the
        # event loop — a multi-GB session tree or cache on a slow disk
        # would otherwise stall MCP heartbeats. (Phase 2 hardening, M2.)
        cache_block = await asyncio.to_thread(_cache_block, cache_root)
        if active is None:
            return {
                "active_session": None,
                "available_sessions": available,
                "cache": cache_block,
                "hint": "Call set_session(name) to activate or create one.",
            }
        return await asyncio.to_thread(
            _describe_active, active, available, cache_block
        )

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


def _describe_active(
    session: Session,
    available_sessions: list[str],
    cache_block: dict,
) -> dict:
    input_files = _list_input_files(session)
    envelope_files = _list_envelope_files(session)
    history = _history(session)
    return {
        "active_session": session.name,
        "session_path": str(session.root),
        "session_created_at": session.config.created_at.isoformat(),
        "cdp_version_at_creation": session.config.cdp_version,
        "input_files": input_files,
        "input_count": len(input_files),
        "envelope_files": envelope_files,
        "envelope_count": len(envelope_files),
        "graph_count": len(history),
        "history": history,
        "disk_usage_bytes": _disk_usage(session.root),
        "available_sessions": available_sessions,
        "cache": cache_block,
    }


def _history(session: Session) -> dict[str, str | None]:
    """Compressed mapping of every session graph ID to its primary output.

    The design-doc-committed "explicit recall" complement to the
    in-memory ``recent_graphs`` deque: built from the filesystem at call
    time, so it survives server restarts and covers graphs that have
    scrolled out of the conversational window. The primary output is the
    highest-numbered node's filename (the main op — auto-PVOC nodes get
    lower numbers); reference it as ``<graph_id>:<node_id>`` or by name.
    Unreadable/empty ``node_index.json`` → ``None`` (the graph directory
    exists but has no addressable output — e.g. a validation-stage
    failure).
    """
    if not session.graphs_dir.exists():
        return {}
    result: dict[str, str | None] = {}
    for graph_root in sorted(session.graphs_dir.iterdir()):
        if not graph_root.is_dir():
            continue
        index_path = graph_root / "node_index.json"
        primary: str | None = None
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(index, dict) and index:
                primary = index[max(index, key=_node_sort_key)]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            primary = None
        result[graph_root.name] = primary
    return result


def _node_sort_key(node_id: str) -> tuple[int, str]:
    """Order node IDs numerically (``n2`` > ``n1``, ``n10`` > ``n9``),
    falling back to lexicographic for non-conforming IDs."""
    m = re.match(r"n(\d+)", node_id)
    return (int(m.group(1)) if m else -1, node_id)


def _cache_block(cache_root: Path) -> dict:
    """Per-tier byte counts plus a derived total.

    Keys mirror :data:`cdp_mcp.cache._KNOWN_TIERS` with ``_bytes``
    suffixes (``pvoc_bytes``, ``analysis_bytes``, …) so the LLM can
    parse them without guessing the tier name conventions.
    """
    sizes = cache_size_bytes(cache_root)
    block = {f"{tier}_bytes": n for tier, n in sizes.items()}
    block["total_bytes"] = sum(sizes.values())
    return block


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
    # Cap the READ, not just the response: the old read_bytes() loaded a
    # pathological multi-GB file fully into RAM before truncating.
    # (Phase 2 hardening, M2.)
    size_bytes = target.stat().st_size
    truncated = size_bytes > _READ_ENVELOPE_MAX_BYTES
    with target.open("rb") as fh:
        payload = fh.read(_READ_ENVELOPE_MAX_BYTES)
    content = payload.decode("utf-8", errors="replace")
    return {
        "name": name,
        "path": str(target),
        "size_bytes": size_bytes,
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
