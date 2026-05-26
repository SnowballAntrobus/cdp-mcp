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


# ---------------------------------------------------------------------------
# Path-component version fallback (stock CDP r8 has no `cdp` binary, so the
# version label has to come from the install directory name)
# ---------------------------------------------------------------------------


def _make_canonical_binaries(cdp_dir: Path) -> None:
    """Create canonical binaries detect_cdp() looks for, with NO `cdp` binary."""
    for name in ("housekeep", "blur", "modify", "pvoc"):
        _make_executable(cdp_dir / name)


@pytest.mark.parametrize(
    "dir_name,expected",
    [
        ("cdpr8", "r8"),
        ("cdpr7", "r7"),
        ("cdp8", "r8"),
        ("cdp_r8", "r8"),
        ("cdp-r8", "r8"),
        ("CDPR8", "r8"),
        ("Cdp-R8", "r8"),
        ("cdpr8.1", "r8.1"),
        ("cdpr8.x", "r8.x"),
    ],
)
def test_detect_cdp_version_from_path_component(
    tmp_path, monkeypatch, dir_name, expected
):
    """When cdp_path's ancestry contains a recognizable CDP release directory
    name, the version is derived from it."""
    install_root = tmp_path / dir_name / "_cdp" / "_cdprogs"
    install_root.mkdir(parents=True)
    _make_canonical_binaries(install_root)
    monkeypatch.setenv("CDP_PATH", str(install_root))
    cfg = detect_cdp()
    assert cfg.version == expected


def test_detect_cdp_version_falls_back_when_no_pattern_matches(
    tmp_path, monkeypatch
):
    """Custom install layouts that don't match the cdp[r]?N pattern fall
    through to "unknown"."""
    install_root = tmp_path / "sound-tools" / "custom_install"
    install_root.mkdir(parents=True)
    _make_canonical_binaries(install_root)
    monkeypatch.setenv("CDP_PATH", str(install_root))
    cfg = detect_cdp()
    assert cfg.version == "unknown"


def test_detect_cdp_version_path_innermost_wins(tmp_path, monkeypatch):
    """When multiple ancestor directories match (unusual but possible), the
    one closest to cdp_path takes precedence."""
    install_root = tmp_path / "cdpr8" / "extras" / "cdpr7" / "_cdprogs"
    install_root.mkdir(parents=True)
    _make_canonical_binaries(install_root)
    monkeypatch.setenv("CDP_PATH", str(install_root))
    cfg = detect_cdp()
    assert cfg.version == "r7"


def test_detect_cdp_version_probe_takes_precedence_over_path(
    tmp_path, monkeypatch
):
    """If a real `cdp` binary exists and emits a version, that wins over the
    path heuristic. Custom builds and wrappers that DO expose --version
    are believed."""
    install_root = tmp_path / "cdpr8" / "_cdprogs"
    install_root.mkdir(parents=True)
    _make_canonical_binaries(install_root)
    _make_executable(install_root / "cdp")
    monkeypatch.setenv("CDP_PATH", str(install_root))

    class FakeResult:
        stdout = "CDP 9.0.0-custom\n"
        stderr = ""

    monkeypatch.setattr(
        "cdp_mcp.config.subprocess.run",
        lambda *_a, **_k: FakeResult(),
    )
    cfg = detect_cdp()
    assert cfg.version == "CDP 9.0.0-custom"  # NOT "r8"


def test_detect_cdp_version_path_heuristic_on_empty_probe_output(
    tmp_path, monkeypatch
):
    """A `cdp` binary that exists but emits nothing → fall back to the path
    heuristic, NOT to "unknown" immediately."""
    install_root = tmp_path / "cdpr8" / "_cdprogs"
    install_root.mkdir(parents=True)
    _make_canonical_binaries(install_root)
    _make_executable(install_root / "cdp")
    monkeypatch.setenv("CDP_PATH", str(install_root))

    class FakeResult:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        "cdp_mcp.config.subprocess.run",
        lambda *_a, **_k: FakeResult(),
    )
    cfg = detect_cdp()
    assert cfg.version == "r8"


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
