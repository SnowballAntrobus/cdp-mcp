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
from dataclasses import dataclass
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
    # Disk watchdog (Task 7): True when the expected output crossed the
    # size cap and the subprocess was SIGKILL'd. ``triggered_at_bytes``
    # records the size that triggered the kill. Both defaulted so
    # existing callers and test fixtures don't need to change.
    size_cap_exceeded: bool = False
    triggered_at_bytes: int | None = None


# ---------------------------------------------------------------------------
# Disk watchdog (Task 7)
# ---------------------------------------------------------------------------


@dataclass
class _WatchdogState:
    """Mutable state shared between the watchdog and run_cdp_command."""

    size_cap_exceeded: bool = False
    triggered_at_bytes: int | None = None


async def _disk_watchdog(
    proc: asyncio.subprocess.Process,
    output_path: Path,
    size_cap_bytes: int,
    state: _WatchdogState,
    poll_interval_s: float,
) -> None:
    """Poll output file size; SIGKILL if it exceeds the cap.

    Returns when either the cap is crossed (after SIGKILL) or when the
    surrounding ``run_cdp_command`` cancels this task on natural exit.

    Race condition tolerated: if the subprocess exits naturally with a
    file that's already over cap, the watchdog records the violation
    in ``state`` but skips the redundant kill (proc.returncode is not
    None).
    """
    while True:
        await asyncio.sleep(poll_interval_s)
        try:
            size = os.path.getsize(output_path)
        except (FileNotFoundError, OSError):
            # Subprocess hasn't started writing yet, or a transient stat
            # failure. Keep polling.
            continue
        if size > size_cap_bytes:
            state.size_cap_exceeded = True
            state.triggered_at_bytes = size
            if proc.returncode is None:
                proc.kill()
            return


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
    output_path: Path | None = None,
    size_cap_bytes: int | None = None,
    watchdog_poll_interval_s: float = 1.0,
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
        output_path: Path the run is expected to produce. Required to
            enable the disk watchdog; ``execute()`` passes ``None`` since
            it has no engine-known output and skips watchdog protection.
        size_cap_bytes: Output file size cap. When both this and
            ``output_path`` are non-None, the watchdog polls the output
            file's size every ``watchdog_poll_interval_s`` and SIGKILLs
            the subprocess if it exceeds the cap. Partial output is
            unlinked after the kill.
        watchdog_poll_interval_s: Polling interval, seconds. Production
            default 1.0; tests pass smaller values (e.g. 0.05) for fast
            iteration.

    Returns:
        A :class:`SubprocessResult` with both streams captured, the
        wrapped argv, exit code (or None on timeout), duration, and
        watchdog state (``size_cap_exceeded`` + ``triggered_at_bytes``).
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

    # Disk watchdog (Task 7) — only active when both output_path AND
    # size_cap_bytes are supplied. execute() passes neither and skips
    # watchdog protection entirely.
    watchdog_state = _WatchdogState()
    watchdog_task: asyncio.Task | None = None
    if output_path is not None and size_cap_bytes is not None:
        watchdog_task = asyncio.create_task(_disk_watchdog(
            proc=proc,
            output_path=output_path,
            size_cap_bytes=size_cap_bytes,
            state=watchdog_state,
            poll_interval_s=watchdog_poll_interval_s,
        ))

    timed_out = False
    exit_code: int | None
    try:
        exit_code = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        await proc.wait()
        exit_code = None

    # Cancel the watchdog (no-op if it already returned on a cap-cross).
    if watchdog_task is not None and not watchdog_task.done():
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass

    # Stream consumers finish naturally when the pipes close. Cancel the
    # progress emitter explicitly and absorb the CancelledError.
    progress_task.cancel()
    try:
        await progress_task
    except asyncio.CancelledError:
        pass

    stdout_bytes = await stdout_task
    stderr_bytes = await stderr_task

    # Remove partial output if the watchdog fired. Best-effort: if
    # unlink fails (e.g. permission, transient FS issue), we proceed —
    # the caller already knows the cap was exceeded.
    if watchdog_state.size_cap_exceeded and output_path is not None:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass

    end_ns = time.monotonic_ns()
    duration_ms = (end_ns - start_ns) // 1_000_000

    return SubprocessResult(
        argv=wrapped_argv,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=exit_code,
        duration_ms=int(duration_ms),
        timed_out=timed_out,
        size_cap_exceeded=watchdog_state.size_cap_exceeded,
        triggered_at_bytes=watchdog_state.triggered_at_bytes,
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
