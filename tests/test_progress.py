"""Unit tests for cdp_mcp.progress.run_with_progress."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from cdp_mcp.progress import run_with_progress

# ---------------------------------------------------------------------------
# Basic behavior
# ---------------------------------------------------------------------------


async def test_no_ctx_just_runs_in_thread_and_returns():
    """ctx=None: runs the fn in a thread, returns its result, no progress."""

    def add(a: int, b: int) -> int:
        return a + b

    result = await run_with_progress(None, "x", add, 2, 3)
    assert result == 5


async def test_with_ctx_fast_fn_returns_result():
    """Fast fn finishes before any heartbeat tick; no progress call needed."""
    ctx = AsyncMock()
    result = await run_with_progress(ctx, "fast", lambda: 42, interval_seconds=10.0)
    assert result == 42
    # Fast function shouldn't have had time to emit any heartbeat.
    ctx.report_progress.assert_not_called()


async def test_event_loop_stays_responsive_during_blocking_work():
    """While a slow sync fn runs in a thread, the event loop must still
    process other async tasks. Without asyncio.to_thread this test would
    hang because the side task could never run.
    """
    ctx = AsyncMock()
    sentinel = []

    async def side_task():
        await asyncio.sleep(0.05)
        sentinel.append("ran")

    side = asyncio.create_task(side_task())
    # Block for 0.3s in a thread; event loop should still service `side`.
    await run_with_progress(ctx, "blocking", time.sleep, 0.3, interval_seconds=10.0)
    await side
    assert sentinel == ["ran"]


# ---------------------------------------------------------------------------
# Heartbeat emission
# ---------------------------------------------------------------------------


async def test_heartbeat_fires_for_slow_work():
    """A fn that runs for >2 intervals should produce ≥1 progress call."""
    ctx = AsyncMock()
    await run_with_progress(
        ctx, "rendering", time.sleep, 0.25, interval_seconds=0.1
    )
    assert ctx.report_progress.await_count >= 1
    # Each call: progress as a float, total=None, message starts with label.
    for call in ctx.report_progress.await_args_list:
        kwargs = call.kwargs
        assert isinstance(kwargs["progress"], float)
        assert kwargs["total"] is None
        assert kwargs["message"].startswith("rendering")


async def test_progress_failure_does_not_kill_work(capsys):
    """A disconnected client (raising ctx.report_progress) must not kill
    the underlying blocking work. The fn still finishes; one warning per
    call is logged to stderr (not per-tick flooding).
    """
    ctx = AsyncMock()
    ctx.report_progress.side_effect = ConnectionError("client gone")

    result = await run_with_progress(
        ctx, "rendering", lambda: time.sleep(0.25) or "done",
        interval_seconds=0.1,
    )
    assert result == "done"

    captured = capsys.readouterr()
    warnings = [
        line for line in captured.err.splitlines()
        if "progress reporting failed" in line
    ]
    # One warning per invocation, even though multiple ticks fired.
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Exception propagation
# ---------------------------------------------------------------------------


async def test_fn_exception_propagates():
    """If the wrapped fn raises, the caller sees the original exception."""
    ctx = AsyncMock()

    def bad():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await run_with_progress(ctx, "x", bad)
