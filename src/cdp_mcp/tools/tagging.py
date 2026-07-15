"""The ``tag()`` MCP tool — durable labels for session files.

Phase 4. Graph ids are timestamps and node ids are counters — neither
survives in the LLM's memory once the conversational window scrolls.
Tags are the human/LLM-meaningful layer on top: ``tag("latest",
["drone", "keeper"])`` today lets ``tags.json`` answer "which file was
the keeper?" next week.

Storage is ``<session>/tags.json`` (created empty at session init;
see :mod:`cdp_mcp.session`), shape
``{"<relative-path-from-session-root>": ["tag1", ...]}`` — written
atomically, deduplicated, sorted. Targets resolve through the shared
reference grammar (:func:`~cdp_mcp.graph.resolve_target`), so aliases
(``latest``, ``prev_N``, ``latest_batch[i]``) and graph refs all work.

Failures follow the house structured-error convention:
``{"status": "failed", "errors": [ErrorEntry...]}``.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from ..graph import LatestTracker, ReferenceResolutionError, resolve_target
from ..schema import ErrorEntry
from ..session import Session, SessionManager, SessionNotActiveError
from ..utils import atomic_write_text

# Tags are bare lowercase identifiers: letters / digits / underscore /
# hyphen, 1..32 chars. No spaces, no path characters, no unicode games —
# they must survive round-trips through JSON, prose, and shell-adjacent
# contexts unchanged.
_TAG_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


async def tag_impl(
    ctx: Context,
    target: str,
    tags: list[str],
    remove: bool = False,
    *,
    sessions: SessionManager,
    latest_tracker: LatestTracker,
) -> dict:
    """Implementation of ``tag()``."""
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _failed([ErrorEntry(
            type="no_active_session",
            message=str(e),
            fix="Call set_session('<name>') first.",
        )])

    bad = [
        t for t in (tags or [])
        if not isinstance(t, str) or not _TAG_RE.fullmatch(t)
    ]
    if bad:
        return _failed([ErrorEntry(
            type="tag_invalid",
            message=(
                f"Invalid tag(s) {bad!r}: tags must match "
                f"{_TAG_RE.pattern} (lowercase letters, digits, '_', "
                "'-'; 1..32 chars)."
            ),
            fix="Use short lowercase identifiers like 'drone' or 'take-2'.",
        )])

    try:
        resolved = resolve_target(target, session, latest_tracker)
    except ReferenceResolutionError as e:
        return _failed([ErrorEntry(
            type="reference_resolution",
            message=str(e),
            fix=(
                "Check the reference: 'latest', '<graph_id>:<node_id>', "
                "an absolute path, or a filename inside the session's "
                "inputs/ directory."
            ),
        )])

    # tags.json read/write is disk work — off the event loop, matching
    # the house convention for sync filesystem access.
    return await asyncio.to_thread(
        _apply, session, resolved, list(tags or []), remove
    )


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    latest_tracker: LatestTracker,
) -> None:
    """Register the ``tag`` tool against ``mcp``."""

    @mcp.tool()
    async def tag(
        ctx: Context,
        target: str,
        tags: list[str],
        remove: bool = False,
    ) -> dict:
        """Attach durable, human-meaningful tags to any session file.

        ``target`` accepts the same reference grammar as every other
        tool: ``latest``, ``prev_N``, ``latest_batch[i]``,
        ``<graph_id>:<node_id>``, or a session input filename. Tags are
        stored in the session's ``tags.json`` keyed by
        session-relative path, so they survive server restarts and
        conversational-window scroll — tag the keepers as you find
        them, then recover them next session.

        Tags are lowercase identifiers (letters, digits, ``_``, ``-``;
        1..32 chars) — anything else returns ``tag_invalid``. Adding is
        idempotent (deduplicated, sorted); ``remove=True`` removes the
        listed tags instead (a file with no tags left drops out of
        ``tags.json`` entirely).

        Query mode: an empty ``tags`` list changes nothing and returns
        the current state — the resolved target's tags, the per-tag
        counts in ``all_tags``, plus the full ``tag_map``
        (``{relative_path: [tags]}``) for the whole session.

        Returns ``{status, path (session-relative), tags (current for
        that file), all_tags: {tag: count}}``.
        """
        return await tag_impl(
            ctx,
            target,
            tags,
            remove,
            sessions=sessions,
            latest_tracker=latest_tracker,
        )


# ---------------------------------------------------------------------------
# Implementation (sync — runs inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _apply(
    session: Session,
    resolved: Path,
    tags: list[str],
    remove: bool,
) -> dict:
    """Load, mutate (unless querying), and atomically rewrite tags.json."""
    session_root = session.root.resolve()
    try:
        rel = resolved.resolve().relative_to(session_root).as_posix()
    except ValueError:
        # resolve_target's containment check makes this unreachable in
        # practice; keep the boundary loud rather than crashing.
        return _failed([ErrorEntry(
            type="tag_target_outside_session",
            message=(
                f"Resolved target {resolved} is outside the session "
                f"tree ({session_root})."
            ),
            fix="Reference a file inside the active session.",
        )])

    tag_map, error = _load_tag_map(session)
    if error is not None:
        return _failed([error])

    if tags:
        current = set(tag_map.get(rel, []))
        if remove:
            current -= set(tags)
        else:
            current |= set(tags)
        if current:
            tag_map[rel] = sorted(current)
        else:
            tag_map.pop(rel, None)
        try:
            atomic_write_text(
                session.tags_path,
                json.dumps(tag_map, indent=2, sort_keys=True) + "\n",
            )
        except OSError as e:
            return _failed([ErrorEntry(
                type="tags_write_failed",
                message=f"could not write {session.tags_path}: {e}",
                fix=(
                    "Check disk space and permissions on the session "
                    "directory."
                ),
            )])

    response = {
        "status": "ok",
        "path": rel,
        "tags": tag_map.get(rel, []),
        "all_tags": _tag_counts(tag_map),
    }
    if not tags:
        # Query mode (empty tags): fold list_tags() in — the full map,
        # unchanged.
        response["tag_map"] = tag_map
    return response


def _load_tag_map(session: Session) -> tuple[dict, ErrorEntry | None]:
    """Read tags.json into ``{rel_path: [tags]}``. Missing file → empty
    map (sessions created before Phase 4 layouts, or hand-built test
    sessions). Unreadable/corrupt → structured error; we refuse to
    silently clobber user tags."""
    path = session.tags_path
    if not path.exists():
        return {}, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {}, ErrorEntry(
            type="tags_file_unreadable",
            message=f"could not read {path}: {e}",
            fix=(
                "Inspect tags.json on disk — it may be corrupt. Fix or "
                "delete it (deleting loses existing tags)."
            ),
        )
    if not isinstance(raw, dict):
        return {}, ErrorEntry(
            type="tags_file_unreadable",
            message=f"{path} does not contain a JSON object.",
            fix=(
                "Inspect tags.json on disk — the expected shape is "
                '{"<relative-path>": ["tag", ...]}.'
            ),
        )
    cleaned = {
        k: sorted({t for t in v if isinstance(t, str)})
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, list)
    }
    return cleaned, None


def _tag_counts(tag_map: dict[str, list[str]]) -> dict[str, int]:
    counts = Counter(t for tags in tag_map.values() for t in tags)
    return dict(sorted(counts.items()))


def _failed(errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "errors": [e.model_dump(mode="json") for e in errors],
    }
