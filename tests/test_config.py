"""Unit tests for cdp_mcp.config.detect_cdp()."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from cdp_mcp.config import CDPConfigError, detect_cdp


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _stub_cdp_dir(root: Path, names: tuple[str, ...] = ("housekeep", "blur")) -> Path:
    for name in names:
        _make_executable(root / name)
    return root


def test_detect_cdp_returns_config_when_path_valid(tmp_path, monkeypatch):
    _stub_cdp_dir(tmp_path)
    monkeypatch.setenv("CDP_PATH", str(tmp_path))

    cfg = detect_cdp()

    assert cfg.cdp_path == tmp_path.resolve()
    assert "housekeep" in cfg.detected_binaries
    assert "blur" in cfg.detected_binaries
    # No ``cdp`` binary present, so version probe should fall back.
    assert cfg.version == "unknown"


def test_detect_cdp_raises_when_env_unset(monkeypatch):
    monkeypatch.delenv("CDP_PATH", raising=False)
    with pytest.raises(CDPConfigError, match="not set"):
        detect_cdp()


def test_detect_cdp_raises_when_env_empty(monkeypatch):
    monkeypatch.setenv("CDP_PATH", "")
    with pytest.raises(CDPConfigError, match="not set"):
        detect_cdp()


def test_detect_cdp_raises_when_path_missing(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("CDP_PATH", str(missing))
    with pytest.raises(CDPConfigError, match="does not exist"):
        detect_cdp()


def test_detect_cdp_raises_when_path_is_not_directory(tmp_path, monkeypatch):
    f = tmp_path / "afile"
    f.write_text("hi")
    monkeypatch.setenv("CDP_PATH", str(f))
    with pytest.raises(CDPConfigError, match="not a directory"):
        detect_cdp()


def test_detect_cdp_raises_when_no_canonical_binaries(tmp_path, monkeypatch):
    # Make some files but none of the canonical names.
    _make_executable(tmp_path / "definitely-not-a-cdp-binary")
    monkeypatch.setenv("CDP_PATH", str(tmp_path))
    with pytest.raises(CDPConfigError, match="does not appear to contain CDP binaries"):
        detect_cdp()


def test_detect_cdp_version_unknown_when_cdp_binary_absent(tmp_path, monkeypatch):
    _stub_cdp_dir(tmp_path)
    monkeypatch.setenv("CDP_PATH", str(tmp_path))
    cfg = detect_cdp()
    assert cfg.version == "unknown"


def test_detect_cdp_version_unknown_when_probe_times_out(tmp_path, monkeypatch):
    _stub_cdp_dir(tmp_path)
    # Place a ``cdp`` file so the probe is attempted.
    _make_executable(tmp_path / "cdp")
    monkeypatch.setenv("CDP_PATH", str(tmp_path))

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="cdp", timeout=5)

    monkeypatch.setattr("cdp_mcp.config.subprocess.run", fake_run)
    cfg = detect_cdp()
    assert cfg.version == "unknown"


def test_detect_cdp_version_parsed_from_first_line(tmp_path, monkeypatch):
    _stub_cdp_dir(tmp_path)
    _make_executable(tmp_path / "cdp")
    monkeypatch.setenv("CDP_PATH", str(tmp_path))

    class FakeResult:
        stdout = "CDP 7.1.0\nMore banner text\n"
        stderr = ""

    monkeypatch.setattr(
        "cdp_mcp.config.subprocess.run",
        lambda *_a, **_k: FakeResult(),
    )
    cfg = detect_cdp()
    assert cfg.version == "CDP 7.1.0"


def test_detect_cdp_expands_user_home(tmp_path, monkeypatch):
    _stub_cdp_dir(tmp_path)
    # Point HOME at tmp_path so ``~`` resolves there, then pass ``~`` as the env value.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CDP_PATH", "~")
    cfg = detect_cdp()
    assert cfg.cdp_path == tmp_path.resolve()


# Sanity: pytest_asyncio's auto mode shouldn't choke on these sync tests.
def test_module_imports_cleanly():
    import cdp_mcp.config as cfg_mod

    assert hasattr(cfg_mod, "detect_cdp")
