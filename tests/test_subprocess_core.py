"""Unit tests for cdp_mcp.subprocess_core."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cdp_mcp.subprocess_core import (
    _apply_arch_prefix,
    _should_wrap_arch_x86_64,
    run_cdp_command,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "fake_subprocess.py"


@pytest.fixture(autouse=True)
def _disable_arch_wrapping(monkeypatch):
    """Disable Apple Silicon arch -x86_64 wrapping for tests that exec
    ``sys.executable``.

    The venv's Python is arm64-native (not a fat binary), so wrapping it
    with ``arch -x86_64`` fails with "Bad CPU type in executable" — that's
    a property of the test fixture, not the production code path.

    The explicit ``test_arch_*`` tests below use ``monkeypatch`` to set the
    env var to specific values; their setenv calls override this autouse
    fixture for the duration of those tests.
    """
    monkeypatch.setenv("CDP_MCP_DISABLE_ARCH_X86_64", "1")


def _fake_argv(*extra: str) -> list[str]:
    return [sys.executable, str(_FIXTURE), *extra]


# ---------------------------------------------------------------------------
# Happy path / exit codes
# ---------------------------------------------------------------------------


async def test_happy_path_captures_streams_and_exit_code(tmp_path):
    result = await run_cdp_command(
        _fake_argv("--stdout", "hello-stdout", "--stderr", "hello-stderr"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0
    assert not result.timed_out
    assert "hello-stdout" in result.stdout
    assert "hello-stderr" in result.stderr
    assert result.duration_ms > 0


async def test_nonzero_exit_code(tmp_path):
    result = await run_cdp_command(
        _fake_argv("--exit", "7"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 7
    assert not result.timed_out


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.timeout(5)
async def test_timeout_kills_subprocess(tmp_path):
    result = await run_cdp_command(
        _fake_argv("--sleep", "5"),
        cwd=tmp_path,
        timeout_seconds=0.5,
        ctx=None,
    )
    assert result.timed_out is True
    assert result.exit_code is None
    # Duration should be close to the timeout, well under the --sleep.
    assert result.duration_ms < 3000


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------


async def test_progress_reported_with_latest_stderr(tmp_path):
    ctx = AsyncMock()
    result = await run_cdp_command(
        _fake_argv("--stderr-lines", "3", "--stderr-line-prefix", "phase"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=ctx,
        progress_interval_seconds=1.0,
    )
    assert result.exit_code == 0
    # --stderr-lines 3 sleeps ~3 s; we should see at least 2 progress calls.
    assert ctx.report_progress.await_count >= 2
    # Each call has progress (float), total=None, message=latest stderr line.
    for call in ctx.report_progress.await_args_list:
        kwargs = call.kwargs
        assert isinstance(kwargs["progress"], float)
        assert kwargs["total"] is None
    # At least one message should be one of the emitted stderr lines.
    messages = [c.kwargs.get("message") for c in ctx.report_progress.await_args_list]
    assert any(m and m.startswith("phase ") for m in messages)


async def test_progress_skipped_when_ctx_none(tmp_path):
    # No way to "verify" no calls happened on a None context, but we can at
    # least confirm the subprocess runs to completion without raising.
    result = await run_cdp_command(
        _fake_argv("--stderr-lines", "2"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
        progress_interval_seconds=0.5,
    )
    assert result.exit_code == 0


async def test_progress_failure_does_not_kill_subprocess(tmp_path, capsys):
    # Simulate a disconnected client: report_progress raises every call.
    ctx = AsyncMock()
    ctx.report_progress.side_effect = ConnectionError("client gone")
    result = await run_cdp_command(
        _fake_argv("--stderr-lines", "3", "--stderr-line-prefix", "x"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=ctx,
        progress_interval_seconds=0.5,
    )
    assert result.exit_code == 0  # subprocess still completed
    captured = capsys.readouterr()
    # Exactly one warning line per invocation, even though multiple ticks fired.
    warnings = [
        line for line in captured.err.splitlines()
        if "progress reporting failed" in line
    ]
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Encoding edge case
# ---------------------------------------------------------------------------


async def test_non_utf8_stdout_does_not_crash(tmp_path):
    # 0xFF is a lone byte invalid in UTF-8; we expect it to be replaced.
    result = await run_cdp_command(
        _fake_argv("--raw-stdout-bytes", "ff"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0
    # The replacement character (U+FFFD) signals successful error="replace" decoding.
    assert "�" in result.stdout


# ---------------------------------------------------------------------------
# Apple Silicon wrapping
# ---------------------------------------------------------------------------


def test_arch_wrap_on_arm64_darwin(monkeypatch):
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.system", lambda: "Darwin")
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.machine", lambda: "arm64")
    monkeypatch.delenv("CDP_MCP_DISABLE_ARCH_X86_64", raising=False)
    assert _should_wrap_arch_x86_64() is True
    assert _apply_arch_prefix(["/bin/ls"]) == ["arch", "-x86_64", "/bin/ls"]


def test_arch_no_wrap_on_intel_darwin(monkeypatch):
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.system", lambda: "Darwin")
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.machine", lambda: "x86_64")
    monkeypatch.delenv("CDP_MCP_DISABLE_ARCH_X86_64", raising=False)
    assert _should_wrap_arch_x86_64() is False
    assert _apply_arch_prefix(["/bin/ls"]) == ["/bin/ls"]


def test_arch_no_wrap_on_linux(monkeypatch):
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.system", lambda: "Linux")
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.machine", lambda: "x86_64")
    monkeypatch.delenv("CDP_MCP_DISABLE_ARCH_X86_64", raising=False)
    assert _should_wrap_arch_x86_64() is False
    assert _apply_arch_prefix(["/bin/ls"]) == ["/bin/ls"]


def test_arch_env_disables_wrap(monkeypatch):
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.system", lambda: "Darwin")
    monkeypatch.setattr("cdp_mcp.subprocess_core.platform.machine", lambda: "arm64")
    for v in ("1", "true", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("CDP_MCP_DISABLE_ARCH_X86_64", v)
        assert _should_wrap_arch_x86_64() is False, f"value {v!r} should disable"
        assert _apply_arch_prefix(["/bin/ls"]) == ["/bin/ls"]
