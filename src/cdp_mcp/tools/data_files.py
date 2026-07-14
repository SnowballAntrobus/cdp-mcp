"""The ``write_data_file()`` MCP tool — auxiliary text/data inputs.

Several CDP programs consume small text/data files alongside their audio
inputs — ``tesselate`` takes pattern/time data, ``newmorph2`` takes note
lists, many programs take ``.brk`` breakpoint or ``.dat`` grid files.
This tool writes such content into ``<session>/data/`` so the returned
path can be fed straight to ``process()`` / ``execute()`` params.

Validation mirrors ``read_envelope``'s bare-basename rules plus an
extension allowlist and a UTF-8 byte-length cap. Overwrites are allowed
(curation workflows iterate on the same file name) and flagged in the
response. The security gate (:func:`cdp_mcp.security.validate_command`
path-scope check) allows any path inside the session tree, so files in
``data/`` pass ``validate_command`` without changes.

Failures follow the house structured-error convention:
``{"status": "failed", "errors": [ErrorEntry...]}``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from ..schema import ErrorEntry
from ..session import Session, SessionManager, SessionNotActiveError
from ..utils import atomic_write_text

_ALLOWED_EXTENSIONS = frozenset({".txt", ".dat", ".csv", ".brk"})

# UTF-8 byte-length cap. Realistic CDP data files are a few KB; 4 MiB is
# defensive headroom against pathological content.
_MAX_DATA_FILE_BYTES = 4 * 1024 * 1024


def register(mcp: FastMCP, *, sessions: SessionManager) -> None:
    """Register the ``write_data_file`` tool against ``mcp``."""

    @mcp.tool()
    async def write_data_file(ctx: Context, name: str, content: str) -> dict:
        """Write an auxiliary text/data input file for CDP programs.

        Programs like ``tesselate`` and ``newmorph2`` take small
        text/data files (note lists, time grids, pattern data,
        breakpoint tables) alongside their audio inputs. This writes
        ``content`` into the active session's ``data/`` directory; the
        returned ``path`` can be passed straight to ``process()`` /
        ``execute()`` params.

        Args:
            name: A bare basename inside ``data/`` — path separators,
                ``..``, and leading dots are rejected. Allowed
                extensions: ``.txt``, ``.dat``, ``.csv``, ``.brk``.
            content: UTF-8 text, capped at 4 MiB.

        Returns ``{status: "ok", path, size_bytes, overwritten}`` on
        success. Overwriting an existing file is allowed (idempotent
        curation workflows) and reported via ``overwritten: true``. On
        failure returns ``{status: "failed", errors: [...]}`` with a
        structured entry (``invalid_data_file_name``,
        ``unsupported_data_file_extension``, ``data_file_too_large``,
        ``no_active_session``, ...).
        """
        try:
            session = sessions.require_active()
        except SessionNotActiveError as e:
            return _failed(
                [
                    ErrorEntry(
                        type="no_active_session",
                        message=str(e),
                        fix="Call set_session('<name>') first.",
                    )
                ]
            )
        # The write itself is disk work — off the event loop, matching
        # the house convention for sync filesystem access.
        return await asyncio.to_thread(_write_data_file, session, name, content)


# ---------------------------------------------------------------------------
# Implementation (sync — runs inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _write_data_file(session: Session, name: str, content: str) -> dict:
    """Validate + atomically write one data file. Lives at module scope
    so tests can exercise the validation directly if needed."""
    if "/" in name or "\\" in name or name in ("", ".", "..") or name.startswith("."):
        return _failed(
            [
                ErrorEntry(
                    type="invalid_data_file_name",
                    message=(
                        f"Invalid data file name {name!r}: must be a bare "
                        "basename inside data/ (no path separators, no "
                        "'..', no leading dot)."
                    ),
                    fix="Pass a plain filename like 'grid.dat' or 'notes.txt'.",
                )
            ]
        )

    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        return _failed(
            [
                ErrorEntry(
                    type="unsupported_data_file_extension",
                    message=(
                        f"Unsupported data file extension {suffix!r}: "
                        f"write_data_file accepts "
                        f"{sorted(_ALLOWED_EXTENSIONS)}."
                    ),
                    fix="Use one of the allowed extensions.",
                )
            ]
        )

    size_bytes = len(content.encode("utf-8"))
    if size_bytes > _MAX_DATA_FILE_BYTES:
        return _failed(
            [
                ErrorEntry(
                    type="data_file_too_large",
                    message=(
                        f"content is {size_bytes:,} bytes as UTF-8; the "
                        f"cap is {_MAX_DATA_FILE_BYTES:,} bytes."
                    ),
                    fix=(
                        "Split the data across smaller files or trim the "
                        "content."
                    ),
                )
            ]
        )

    data_dir = session.root / "data"
    target = data_dir / name
    overwritten = target.exists()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, content)
    except OSError as e:
        return _failed(
            [
                ErrorEntry(
                    type="data_file_write_failed",
                    message=f"could not write {target}: {e}",
                    fix=(
                        "Check disk space and permissions on the session "
                        "directory."
                    ),
                )
            ]
        )

    return {
        "status": "ok",
        "path": str(target),
        "size_bytes": size_bytes,
        "overwritten": overwritten,
    }


def _failed(errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "errors": [e.model_dump(mode="json") for e in errors],
    }
