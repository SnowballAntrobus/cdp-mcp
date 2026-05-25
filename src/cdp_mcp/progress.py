"""Helpers for running CPU-bound work without starving the asyncio event loop.

MCP tools are async, but some of the work they do (matplotlib rendering,
librosa feature extraction, sha256 hashing on big files) is synchronous and
CPU-bound. Running such work directly inside an async tool blocks the event
loop, which starves MCP heartbeats — long renders look like crashes to
Claude Desktop and trigger its per-tool-call timeout even though the work
is still progressing.

:func:`run_with_progress` is the fix: push the blocking call into a thread
via :func:`asyncio.to_thread`, and fire periodic ``ctx.report_progress``
notifications from the main coroutine so the MCP connection stays visibly
alive. Mirrors the keepalive pattern in :func:`cdp_mcp.subprocess_core.run_cdp_command`.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server.fastmcp import Context

_PROGRESS_INTERVAL_SECONDS = 5.0
_PROGRESS_MESSAGE_MAX_CHARS = 200

_T = TypeVar("_T")


async def run_with_progress(
    ctx: Context | None,
    label: str,
    fn: Callable[..., _T],
    *args: Any,
    interval_seconds: float = _PROGRESS_INTERVAL_SECONDS,
) -> _T:
    """Run a blocking function in a thread while emitting MCP progress heartbeats.

    Args:
        ctx: MCP context to send progress on. ``None`` skips progress
            reporting and just runs ``fn`` in a thread (useful in tests).
        label: Short message shown in each progress update — appears in the
            Claude Desktop UI alongside the ticking counter, e.g.
            ``"rendering spectrogram"``.
        fn: Synchronous callable to run off the event loop.
        *args: Positional args forwarded to ``fn``.
        interval_seconds: How often the heartbeat fires. Default 5 s matches
            ``run_cdp_command``'s default and Claude Desktop's keepalive
            window.

    Returns:
        Whatever ``fn(*args)`` returned.
    """
    if ctx is None:
        return await asyncio.to_thread(fn, *args)

    work_task = asyncio.create_task(asyncio.to_thread(fn, *args))
    heartbeat_task = asyncio.create_task(
        _emit_heartbeat(ctx, label, interval_seconds)
    )
    try:
        return await work_task
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


async def _emit_heartbeat(
    ctx: Context, label: str, interval_seconds: float
) -> None:
    """Loop firing progress notifications until cancelled.

    Same error-tolerance pattern as
    :func:`cdp_mcp.subprocess_core._emit_progress` — swallow exceptions
    from a disconnected client, log one warning, then continue. The work
    coroutine must never be killed by progress-side failures.
    """
    tick = 0
    failed_once = False
    while True:
        await asyncio.sleep(interval_seconds)
        tick += 1
        message = label[:_PROGRESS_MESSAGE_MAX_CHARS]
        try:
            await ctx.report_progress(
                progress=float(tick), total=None, message=message
            )
        except Exception as e:  # noqa: BLE001 — client disconnects, transport, etc.
            if not failed_once:
                print(
                    f"[cdp-mcp] WARNING: progress reporting failed: {e}; "
                    "suppressing further notices for this task",
                    file=sys.stderr,
                )
                failed_once = True
