"""Async subprocess runner with periodic MCP progress reporting.

This module provides :func:`run_cdp_command`, the single entry point every
later task uses to spawn a CDP binary. It handles:

- Apple Silicon ``arch -x86_64`` wrapping (auto-on, override via
  ``$CDP_MCP_DISABLE_ARCH_X86_64``).
- Concurrent stdout / stderr capture without buffering one to block the
  other.
- Periodic ``ctx.report_progress`` calls (an incrementing tick + the most
  recent stderr line as a message) so MCP clients don't time out during
  long CDP runs.
- SIGKILL on timeout with a clean ``timed_out=True`` result.

It does NOT resolve binary names — ``argv[0]`` must be an absolute path.
Binary resolution and command-line assembly are Task 5/6 concerns.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import Context
from pydantic import BaseModel

_PROGRESS_MESSAGE_MAX_CHARS = 200


class SubprocessResult(BaseModel):
    """The outcome of one :func:`run_cdp_command` invocation."""

    argv: list[str]  # exact argv after arch-prefix wrapping
    stdout: str
    stderr: str
    exit_code: int | None  # None if timed out
    duration_ms: int
    timed_out: bool


# ---------------------------------------------------------------------------
# Apple Silicon arch wrapping
# ---------------------------------------------------------------------------


def _should_wrap_arch_x86_64() -> bool:
    """Decide whether to prefix argv with ``arch -x86_64``.

    True on arm64 Darwin unless the user opts out via
    ``$CDP_MCP_DISABLE_ARCH_X86_64`` set to ``1`` / ``true`` / ``yes``.
    Users with native arm64 CDP builds set the override.
    """
    if os.environ.get("CDP_MCP_DISABLE_ARCH_X86_64", "").lower() in ("1", "true", "yes"):
        return False
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _apply_arch_prefix(argv: list[str]) -> list[str]:
    if _should_wrap_arch_x86_64():
        return ["arch", "-x86_64", *argv]
    return list(argv)


# ---------------------------------------------------------------------------
# run_cdp_command
# ---------------------------------------------------------------------------


async def run_cdp_command(
    argv: list[str],
    cwd: Path,
    timeout_seconds: float = 120.0,
    ctx: Context | None = None,
    progress_interval_seconds: float = 5.0,
) -> SubprocessResult:
    """Run a CDP subprocess asynchronously with progress reporting.

    Args:
        argv: Command and arguments. ``argv[0]`` MUST be an absolute path —
            binary resolution is the caller's responsibility.
        cwd: Working directory for the subprocess.
        timeout_seconds: Hard SIGKILL timeout. Default 120 s.
        ctx: Optional MCP Context. If provided, ``ctx.report_progress`` is
            called every ``progress_interval_seconds`` with the latest
            stderr line as the message.
        progress_interval_seconds: How often to emit progress. Default 5 s,
            matching the Claude Desktop ~60 s connection timeout headroom.

    Returns:
        A :class:`SubprocessResult` with both streams captured, the
        wrapped argv, exit code (or None on timeout), and duration.
    """
    wrapped_argv = _apply_arch_prefix(argv)
    start_ns = time.monotonic_ns()

    proc = await asyncio.create_subprocess_exec(
        *wrapped_argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
    )

    # Shared mutable state: stderr consumer writes the latest line, the
    # progress emitter reads it. Single-task-writer, single-task-reader —
    # no lock needed under cooperative async scheduling.
    state: dict[str, str] = {"latest_stderr_line": ""}

    stdout_task = asyncio.create_task(_read_all(proc.stdout))
    stderr_task = asyncio.create_task(_read_stderr_lines(proc.stderr, state))
    progress_task = asyncio.create_task(
        _emit_progress(ctx, state, progress_interval_seconds)
    )

    timed_out = False
    exit_code: int | None
    try:
        exit_code = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        await proc.wait()
        exit_code = None

    # Stream consumers finish naturally when the pipes close. Cancel the
    # progress emitter explicitly and absorb the CancelledError.
    progress_task.cancel()
    try:
        await progress_task
    except asyncio.CancelledError:
        pass

    stdout_bytes = await stdout_task
    stderr_bytes = await stderr_task

    end_ns = time.monotonic_ns()
    duration_ms = (end_ns - start_ns) // 1_000_000

    return SubprocessResult(
        argv=wrapped_argv,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=exit_code,
        duration_ms=int(duration_ms),
        timed_out=timed_out,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _read_all(stream: asyncio.StreamReader | None) -> bytes:
    if stream is None:
        return b""
    return await stream.read()


async def _read_stderr_lines(
    stream: asyncio.StreamReader | None,
    state: dict[str, str],
) -> bytes:
    """Consume stderr line-by-line, updating ``state['latest_stderr_line']``.

    Also accumulates raw bytes so the final :class:`SubprocessResult` can
    expose the full stderr. We can't both ``readline`` for progress AND
    ``read()`` for bulk, so we buffer here.
    """
    if stream is None:
        return b""
    chunks: list[bytes] = []
    while True:
        line = await stream.readline()
        if not line:
            break
        chunks.append(line)
        # Decode just for the progress message; full bytes are kept raw.
        decoded = line.decode("utf-8", errors="replace").rstrip()
        if decoded:
            state["latest_stderr_line"] = decoded
    return b"".join(chunks)


async def _emit_progress(
    ctx: Context | None,
    state: dict[str, str],
    interval_seconds: float,
) -> None:
    """Send periodic indeterminate progress notifications.

    A tick counter (1, 2, 3, …) is used as the ``progress`` value because
    ``mcp 1.27.1`` requires a non-None float. ``total=None`` keeps the
    progress indeterminate. The ``message`` is the latest stderr line so
    the client sees what the CDP binary is currently saying.

    Errors from the MCP client (e.g. disconnected) are swallowed after one
    stderr warning per subprocess invocation — they must never kill the
    underlying CDP run.
    """
    if ctx is None:
        return

    tick = 0
    failed_once = False
    while True:
        await asyncio.sleep(interval_seconds)
        tick += 1
        message = state["latest_stderr_line"][:_PROGRESS_MESSAGE_MAX_CHARS] or None
        try:
            await ctx.report_progress(
                progress=float(tick), total=None, message=message
            )
        except Exception as e:  # noqa: BLE001 — client disconnects, transport, etc.
            if not failed_once:
                print(
                    f"[cdp-mcp] WARNING: progress reporting failed: {e}; "
                    "suppressing further notices for this subprocess",
                    file=sys.stderr,
                )
                failed_once = True
