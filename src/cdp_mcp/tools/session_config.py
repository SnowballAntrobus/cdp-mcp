"""Session-scoped settings and file listing: ``set_config()`` /
``list_session_files()``.

Phase 4. Two small self-service tools:

- ``set_config(key, value)`` — persist a user-adjustable setting into
  the session's ``config.json`` under the ``user_config`` dict (see
  :class:`~cdp_mcp.session.SessionConfig`). Phase 4 allowlists the two
  disk-budget knobs; this tool only stores and returns them — budget
  *consumption* (enforcement) lands with the ``cleanup()`` tool.
- ``list_session_files(pattern)`` — glob over the session tree
  (excluding ``tmp/``) with relative paths and sizes, so the LLM can
  answer "what's on disk?" without shelling out or walking
  ``describe_workspace``'s coarser summary.

Failures follow the house structured-error convention:
``{"status": "failed", "errors": [ErrorEntry...]}``.
"""

from __future__ import annotations

import asyncio
import math

from mcp.server.fastmcp import Context, FastMCP

from ..schema import ErrorEntry
from ..session import Session, SessionManager, SessionNotActiveError
from ..utils import atomic_write_text

# Allowed set_config keys → human-readable constraint (used in error
# messages). Values are validated by _validate_value: finite float > 0.
_ALLOWED_KEYS = {
    "disk_budget_soft_gb": "float > 0",
    "disk_budget_hard_gb": "float > 0",
}

# list_session_files response cap. Sessions with more matching files get
# the first 500 (sorted) plus truncated=true.
_MAX_LISTING_ENTRIES = 500


def register(mcp: FastMCP, *, sessions: SessionManager) -> None:
    """Register ``set_config`` and ``list_session_files`` against ``mcp``."""

    @mcp.tool()
    async def set_config(ctx: Context, key: str, value: float) -> dict:
        """Persist a user-adjustable setting for the active session.

        Allowed keys (Phase 4): ``disk_budget_soft_gb`` and
        ``disk_budget_hard_gb`` — both floats > 0, in gigabytes. They
        are stored in the session's ``config.json`` under
        ``user_config`` and survive server restarts and session
        re-activation. Setting a key overwrites its previous value.

        Note: this tool only *stores* the budgets; enforcement
        (warnings and refusals as the session tree approaches the
        budgets) is the ``cleanup()`` tool's job.

        Returns ``{status: "ok", config}`` where ``config`` is the full
        ``user_config`` dict after the write. Unknown keys return
        ``config_key_unknown`` listing the allowed keys; non-positive
        or non-numeric values return ``config_value_invalid``.
        """
        try:
            session = sessions.require_active()
        except SessionNotActiveError as e:
            return _failed([ErrorEntry(
                type="no_active_session",
                message=str(e),
                fix="Call set_session('<name>') first.",
            )])
        if key not in _ALLOWED_KEYS:
            allowed = ", ".join(
                f"{k} ({v})" for k, v in sorted(_ALLOWED_KEYS.items())
            )
            return _failed([ErrorEntry(
                type="config_key_unknown",
                message=f"Unknown config key {key!r}.",
                fix=f"Allowed keys: {allowed}.",
            )])
        value_error = _validate_value(key, value)
        if value_error is not None:
            return _failed([value_error])
        # config.json rewrite is disk work — off the event loop.
        return await asyncio.to_thread(_set_config, session, key, float(value))

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


def _validate_value(key: str, value: object) -> ErrorEntry | None:
    """Phase 4 keys share one constraint: finite float > 0."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        return ErrorEntry(
            type="config_value_invalid",
            message=(
                f"{key} must be a finite number > 0; got {value!r}."
            ),
            fix="Pass a positive number of gigabytes, e.g. 2.5.",
        )
    return None


def _set_config(session: Session, key: str, value: float) -> dict:
    """Update the in-memory SessionConfig and atomically rewrite
    config.json — same serialization the SessionManager uses at
    creation time, so re-activation round-trips the value."""
    session.config.user_config[key] = value
    try:
        atomic_write_text(
            session.config_path,
            session.config.model_dump_json(indent=2) + "\n",
        )
    except OSError as e:
        return _failed([ErrorEntry(
            type="config_write_failed",
            message=f"could not write {session.config_path}: {e}",
            fix="Check disk space and permissions on the session directory.",
        )])
    return {
        "status": "ok",
        "config": dict(session.config.user_config),
    }


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
