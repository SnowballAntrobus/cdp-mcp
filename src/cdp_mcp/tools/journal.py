"""The ``journal()`` MCP tool — append-only session notebook.

Phase 4. ``<session>/journal.md`` exists from session init (see
:mod:`cdp_mcp.session`); this tool appends timestamped one-line entries
(``- [<ISO-8601Z>] <note>``) so aesthetic judgments — "variant 3 too
harsh, keep the 40-window blur" — survive the conversational window and
server restarts. Called with no note, it returns the journal text
instead: the read side of the same memory.

Failures follow the house structured-error convention:
``{"status": "failed", "errors": [ErrorEntry...]}``.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from mcp.server.fastmcp import Context, FastMCP

from ..schema import ErrorEntry
from ..session import Session, SessionManager, SessionNotActiveError

# Per-note cap. Journal entries are one-line judgments, not essays; 4 KiB
# is defensive headroom against pathological content.
_MAX_NOTE_BYTES = 4 * 1024

# Read cap for the no-note (read) path. Journals are meant to stay small;
# a 32 KiB window is hundreds of entries.
_MAX_READ_BYTES = 32 * 1024


async def journal_impl(
    ctx: Context,
    note: str | None = None,
    *,
    sessions: SessionManager,
) -> dict:
    """Implementation of ``journal()``."""
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _failed([ErrorEntry(
            type="no_active_session",
            message=str(e),
            fix="Call set_session('<name>') first.",
        )])
    # Journal reads/appends are disk work — off the event loop, matching
    # the house convention for sync filesystem access.
    if note is None or note == "":
        return await asyncio.to_thread(_read_journal, session)
    return await asyncio.to_thread(_append_note, session, note)


def register(mcp: FastMCP, *, sessions: SessionManager) -> None:
    """Register the ``journal`` tool against ``mcp``."""

    @mcp.tool()
    async def journal(ctx: Context, note: str | None = None) -> dict:
        """Append a note to the session journal — or read it back.

        With a ``note``, appends one timestamped entry
        (``- [<ISO-8601Z>] <note>``) to the session's ``journal.md``.
        Use it to record aesthetic judgments and decisions the context
        window will forget: what worked, what to avoid, which variant
        won. Newlines in the note are collapsed to spaces (one entry =
        one line); notes are capped at 4 KiB
        (``journal_note_too_large``). Returns ``{status, entry_count,
        path}``.

        With no ``note`` (or an empty string), returns the full journal
        text without writing: ``{status, content, truncated,
        entry_count, path}``. Content is capped at 32 KiB with
        ``truncated: true`` beyond that.
        """
        return await journal_impl(ctx, note, sessions=sessions)


# ---------------------------------------------------------------------------
# Implementation (sync — runs inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _append_note(session: Session, note: str) -> dict:
    # One entry = one line: collapse newline runs (\n, \r\n, \r) to a
    # single space so entry counting (lines starting "- [") stays
    # truthful.
    cleaned = re.sub(r"[\r\n]+", " ", note).strip()
    size_bytes = len(cleaned.encode("utf-8"))
    if size_bytes > _MAX_NOTE_BYTES:
        return _failed([ErrorEntry(
            type="journal_note_too_large",
            message=(
                f"note is {size_bytes:,} bytes as UTF-8; the per-note "
                f"cap is {_MAX_NOTE_BYTES:,} bytes."
            ),
            fix="Trim the note — journal entries are one-line judgments.",
        )])

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"- [{ts}] {cleaned}\n"
    try:
        # Plain append, not atomic rewrite: the journal is append-only
        # by contract, and a torn write can lose at most this one line.
        with session.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as e:
        return _failed([ErrorEntry(
            type="journal_write_failed",
            message=f"could not append to {session.journal_path}: {e}",
            fix="Check disk space and permissions on the session directory.",
        )])
    return {
        "status": "ok",
        "entry_count": _entry_count(session),
        "path": str(session.journal_path),
    }


def _read_journal(session: Session) -> dict:
    path = session.journal_path
    if not path.exists():
        # Sessions created before Phase 4 layouts or hand-built test
        # sessions; an empty journal, not an error.
        return {
            "status": "ok",
            "content": "",
            "truncated": False,
            "entry_count": 0,
            "path": str(path),
        }
    try:
        size_bytes = path.stat().st_size
        # Cap the READ, not just the response (house convention from
        # read_envelope): never load a pathological file fully into RAM.
        with path.open("rb") as fh:
            payload = fh.read(_MAX_READ_BYTES)
    except OSError as e:
        return _failed([ErrorEntry(
            type="journal_read_failed",
            message=f"could not read {path}: {e}",
            fix="Check permissions on the session directory.",
        )])
    return {
        "status": "ok",
        "content": payload.decode("utf-8", errors="replace"),
        "truncated": size_bytes > _MAX_READ_BYTES,
        "entry_count": _entry_count(session),
        "path": str(path),
    }


def _entry_count(session: Session) -> int:
    """Count journal entries (lines starting ``- [``). Line-by-line so a
    large journal never loads fully into memory. Never raises."""
    try:
        with session.journal_path.open(encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if line.startswith("- ["))
    except OSError:
        return 0


def _failed(errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "errors": [e.model_dump(mode="json") for e in errors],
    }
