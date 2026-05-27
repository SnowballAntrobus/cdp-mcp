"""Stress test for the MCP keepalive mechanism.

Runs a subprocess long enough to exceed Claude Desktop's per-tool
timeout (~60 s). Two things have to hold for the test to pass:

1. The subprocess completes successfully across a >60 s wall-clock.
2. ``ctx.report_progress`` fires multiple times during the run — these
   are the keepalive heartbeats. Without them, Claude Desktop would
   close the connection mid-call.

Marked ``@pytest.mark.slow`` so it doesn't run in the default
``pytest`` cycle (see ``pyproject.toml``). To run explicitly:

    pytest -m slow tests/test_stress.py

Why a fake subprocess instead of real CDP
-----------------------------------------

The original Phase 1b plan called for running ``pvoc anal`` on a
multi-minute audio file. On Apple Silicon M-series, a 10-minute mono
44.1 kHz wav analyzes in ~5 s — to push the run past 60 s we'd need
~2+ hours of audio (1.3+ GB wav, 13+ GB ``.ana``), which is
impractical on disk and slow to generate.

The keepalive mechanism (see ``cdp_mcp.subprocess_core._emit_progress``)
is **clock-driven**, not stderr- or CDP-driven: every
``progress_interval_seconds`` it calls ``ctx.report_progress`` with
the latest stderr line as the message. That code path exercises
identically whether the subprocess is real ``pvoc anal`` or
``tests/fixtures/fake_subprocess.py`` sleeping for 80 s.

This test uses the fixture sleep so the duration is deterministic
across machines and doesn't require ``$CDP_PATH``. The real-CDP
runtime characteristics are recorded in Tasks 10/11 verification.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from cdp_mcp.subprocess_core import run_cdp_command

_FIXTURE = (Path(__file__).parent / "fixtures" / "fake_subprocess.py").resolve()

# Subprocess sleep duration. Comfortably above Claude Desktop's ~60 s
# timeout so the test actually exercises the keepalive past that
# threshold. Bounded above by the SIGKILL timeout below.
_SLEEP_SECONDS = 80.0

# The recorded keepalive bound: at minimum the test must verify that
# the run completed at or above 60 s wall-clock. Below this we
# wouldn't have crossed Claude Desktop's timeout.
_MIN_DURATION_S = 60.0

# Upper bound for sanity — catches a future bug where the subprocess
# hangs and the test waits for the hard SIGKILL.
_MAX_DURATION_S = 120.0

# Minimum number of keepalive notifications during the run. With the
# default 5 s ``progress_interval_seconds`` and an 80 s sleep, we
# expect ~14–16 calls; 5 leaves headroom for cold-start jitter
# without false-failing. The point is to catch "keepalive completely
# broken" (zero or one calls), not to time-stamp every tick.
_MIN_PROGRESS_CALLS = 5


class _RecordingContext:
    """Duck-typed Context that records every ``report_progress`` call.

    ``subprocess_core._emit_progress`` only invokes
    ``.report_progress(...)``, so we don't need the full
    ``mcp.server.fastmcp.Context`` surface. The ``at`` monotonic
    timestamp is captured for diagnostic inspection on failure (e.g.,
    "all progress calls clustered at the start, then went silent").
    """

    def __init__(self) -> None:
        self.progress_calls: list[dict] = []

    async def report_progress(
        self,
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        self.progress_calls.append(
            {
                "progress": progress,
                "total": total,
                "message": message,
                "at": time.monotonic(),
            }
        )


@pytest.mark.slow
@pytest.mark.timeout(150)  # override pyproject.toml's suite-wide 30 s
async def test_mcp_keepalive_fires_through_long_subprocess(tmp_path):
    """Subprocess sleeps 80 s; keepalive must fire >=5 times.

    A 5 s ``progress_interval_seconds`` against an 80 s subprocess
    produces ~14–16 ``ctx.report_progress`` calls. Without the
    keepalive, Claude Desktop's ~60 s connection timeout would have
    closed the stream around the 12th progress tick. The test
    asserts both that the subprocess completed and that the keepalive
    actually fired during the run.
    """
    # fake_subprocess.py also emits stderr lines on a clock so the
    # ``message`` field of progress notifications has realistic content
    # (matches what real CDP analysis emits). Not strictly required —
    # the keepalive fires regardless of stderr — but worth recording.
    ctx = _RecordingContext()

    argv = [
        sys.executable,
        str(_FIXTURE),
        "--sleep", str(_SLEEP_SECONDS),
        "--stderr-lines", "20",
        "--stderr-line-prefix", "anal frame",
    ]

    started_at = time.monotonic()
    result = await run_cdp_command(
        argv=argv,
        cwd=tmp_path,
        # Hard SIGKILL ceiling well above the 120 s upper bound. If the
        # test would fail the upper bound, it's more useful to surface
        # the slow duration than to be killed mid-run.
        timeout_seconds=140.0,
        ctx=ctx,
        progress_interval_seconds=5.0,
        # Disk watchdog disabled — no output file expected.
        output_path=None,
        size_cap_bytes=None,
    )
    wall_clock_s = time.monotonic() - started_at

    assert result.exit_code == 0, (
        f"fake_subprocess exited {result.exit_code}. "
        f"stderr tail:\n{result.stderr[-500:]}"
    )
    assert not result.timed_out, (
        f"fake_subprocess hit the 140 s SIGKILL timeout. "
        f"Wall-clock {wall_clock_s:.1f} s. Either the system "
        f"clock is broken or the runtime regressed catastrophically."
    )

    duration_s = result.duration_ms / 1000
    if duration_s < _MIN_DURATION_S:
        pytest.fail(
            f"Run completed in {duration_s:.1f} s, below the "
            f"{_MIN_DURATION_S:.0f} s lower bound. The test isn't "
            f"actually exercising the keepalive across Claude "
            f"Desktop's ~60 s timeout. Either the subprocess "
            f"short-circuited or _SLEEP_SECONDS "
            f"({_SLEEP_SECONDS:.0f} s) was reduced."
        )
    if duration_s > _MAX_DURATION_S:
        pytest.fail(
            f"Run completed in {duration_s:.1f} s, above the "
            f"{_MAX_DURATION_S:.0f} s upper bound. Investigate "
            f"whether the subprocess hung or the system is under "
            f"unusual load."
        )

    assert len(ctx.progress_calls) >= _MIN_PROGRESS_CALLS, (
        f"Only {len(ctx.progress_calls)} progress call(s) during a "
        f"{duration_s:.1f} s run — the keepalive isn't firing "
        f"reliably. Claude Desktop would have disconnected mid-run. "
        f"Expected ~{int(duration_s / 5)} calls at the default 5 s "
        f"interval (>={_MIN_PROGRESS_CALLS} required)."
    )
