"""Test-suite-wide fixtures.

The sessions root is redirected to a temporary directory for the whole
pytest session so that importing :mod:`cdp_mcp.server` (which constructs a
``SessionManager`` at module-import time) never touches the developer's
real ``~/cdp_sessions/``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_sessions_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("cdp_sessions_root")
    previous = os.environ.get("CDP_MCP_SESSIONS_ROOT")
    os.environ["CDP_MCP_SESSIONS_ROOT"] = str(root)
    yield root
    if previous is None:
        os.environ.pop("CDP_MCP_SESSIONS_ROOT", None)
    else:
        os.environ["CDP_MCP_SESSIONS_ROOT"] = previous


@pytest.fixture(autouse=True, scope="session")
def _disable_apple_silicon_arch_wrapping():
    """Disable ``arch -x86_64`` wrapping for the full pytest session.

    The venv's Python interpreter that exec-runs ``fake_subprocess.py`` is
    arm64-native, not a fat binary; wrapping it with ``arch -x86_64`` would
    fail with "Bad CPU type in executable". Production CDP binaries are
    x86 and the wrapper works correctly against them.

    The handful of tests in ``test_subprocess_core.py`` that exercise the
    arch-detection logic itself use ``monkeypatch.delenv()`` to remove this
    env var for their duration; monkeypatch restores it at teardown, so
    this session fixture stays effective for the rest of the run.
    """
    previous = os.environ.get("CDP_MCP_DISABLE_ARCH_X86_64")
    os.environ["CDP_MCP_DISABLE_ARCH_X86_64"] = "1"
    yield
    if previous is None:
        os.environ.pop("CDP_MCP_DISABLE_ARCH_X86_64", None)
    else:
        os.environ["CDP_MCP_DISABLE_ARCH_X86_64"] = previous


@pytest.fixture(scope="session")
def real_cdp_path() -> Path | None:
    """Return the real CDP installation root, or ``None`` if not configured.

    Used by the acceptance test (``tests/test_acceptance.py``) to skip
    cleanly when ``$CDP_PATH`` is unset or doesn't contain the binaries
    the chain needs. Returns ``None`` instead of skipping at fixture
    scope so the call site can attach a context-specific skip reason.

    The frog chain in the acceptance test uses ``blur``, ``pvoc``,
    ``modify``, and ``extend``. All four must be present.
    """
    env = os.environ.get("CDP_PATH")
    if not env:
        return None
    p = Path(env)
    if not p.is_dir():
        return None
    required = ["blur", "pvoc", "modify", "extend"]
    if not all((p / name).is_file() for name in required):
        return None
    return p
