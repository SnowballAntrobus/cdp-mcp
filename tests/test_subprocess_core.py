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


# ---------------------------------------------------------------------------
# CDP-quirk fake flags
# ---------------------------------------------------------------------------


async def test_cdp_refuse_clobber_noop_when_file_missing(tmp_path):
    """When the path does not exist, --cdp-refuse-clobber is a no-op and
    the rest of the flag chain runs normally."""
    out = tmp_path / "out.ana"
    assert not out.exists()
    result = await run_cdp_command(
        _fake_argv("--cdp-refuse-clobber", str(out), "--write-ana", str(out)),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0
    assert out.exists() and out.stat().st_size > 100


async def test_cdp_refuse_clobber_exits_255_when_file_exists(tmp_path):
    """When the path exists, fake bails with exit 255 and the canonical
    'cannot create output' stderr message, mirroring CDP r8 pvoc synth.
    The pre-existing file is untouched.
    """
    out = tmp_path / "out.ana"
    out.write_bytes(b"pre-existing-bytes")
    result = await run_cdp_command(
        _fake_argv("--cdp-refuse-clobber", str(out), "--write-ana", str(out)),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 255
    assert "cannot create output" in result.stderr.lower()
    assert out.read_bytes() == b"pre-existing-bytes"


@pytest.mark.skipif(sys.platform == "win32", reason="SIGILL not on Windows")
async def test_cdp_sigill_on_dot_path_triggers_on_dotted_ancestry(tmp_path):
    """Absolute path with '.' in any ancestor directory → SIGILL.
    The subprocess exit code is negative (the signal number) on POSIX.
    """
    result = await run_cdp_command(
        _fake_argv("--cdp-sigill-on-dot-path", "/some/dotted.dir/frog.wav"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code is not None
    assert result.exit_code < 0


@pytest.mark.skipif(sys.platform == "win32", reason="SIGILL not on Windows")
async def test_cdp_sigill_on_dot_path_passes_clean_absolute_path(tmp_path):
    """Absolute path with no '.' in ancestry → no SIGILL, normal exit."""
    result = await run_cdp_command(
        _fake_argv("--cdp-sigill-on-dot-path", "/some/clean/dir/frog.wav"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0


@pytest.mark.skipif(sys.platform == "win32", reason="SIGILL not on Windows")
async def test_cdp_sigill_on_dot_path_passes_relative_path(tmp_path):
    """A relative path is never absolute, never triggers SIGILL — even if
    it happens to contain '.' in a directory name."""
    result = await run_cdp_command(
        _fake_argv("--cdp-sigill-on-dot-path", "frog_v0.1/inputs/frog.wav"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0


@pytest.mark.skipif(sys.platform == "win32", reason="SIGILL not on Windows")
async def test_cdp_sigill_on_dot_path_dotted_basename_alone_is_fine(tmp_path):
    """A '.' in basename (file extension) does NOT trigger; only '.' in
    ancestor directory names is the bug being simulated."""
    result = await run_cdp_command(
        _fake_argv("--cdp-sigill-on-dot-path", "/some/clean/dir/frog.wav"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0


async def test_cdp_silent_output_writes_silent_wav(tmp_path):
    """--cdp-silent-output writes an all-zero wav, distinct from
    --write-wav (which produces non-silent ±8000 frames)."""
    import wave

    out = tmp_path / "silent.wav"
    result = await run_cdp_command(
        _fake_argv("--cdp-silent-output", str(out)),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        frames = w.readframes(w.getnframes())
    assert frames == bytes(len(frames))  # all-zero payload


async def test_parse_known_args_lets_unrecognized_flags_pass(tmp_path):
    """parse_args → parse_known_args widening: unknown flags no longer
    error. --cdp-sigill-on-dot-path scans the leftover positional args."""
    result = await run_cdp_command(
        _fake_argv("--this-flag-does-not-exist", "value", "--exit", "0"),
        cwd=tmp_path,
        timeout_seconds=10.0,
        ctx=None,
    )
    assert result.exit_code == 0
