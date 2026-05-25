"""Test-suite-wide fixtures.

The sessions root is redirected to a temporary directory for the whole
pytest session so that importing :mod:`cdp_mcp.server` (which constructs a
``SessionManager`` at module-import time) never touches the developer's
real ``~/cdp_sessions/``.
"""

from __future__ import annotations

import os

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
