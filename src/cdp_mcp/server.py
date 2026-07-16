"""FastMCP server assembly.

All logging here goes to ``sys.stderr``. The MCP stdio transport uses stdout
for JSON-RPC traffic — any stray write to stdout will corrupt the protocol
and break the client connection silently. Tool implementations must obey the
same rule.

Module-import-time work:
    - Build the FastMCP instance.
    - Load the knowledge index and register the introspection tools.
    - Detect CDP once and memoize the result (or the failure message).
    - Resolve the sessions root, build the SessionManager, register the
      workspace tools.

``create_server()`` only handles startup-time *logging*; all heavy lifting
above runs deterministically at import.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import prompts
from .config import CDPConfig, CDPConfigError, detect_cdp
from .graph import LatestTracker
from .knowledge.loader import KnowledgeIndex
from .session import SessionManager
from .tools import analyze as analyze_module
from .tools import batch as batch_module
from .tools import breakpoint as breakpoint_module
from .tools import cleanup as cleanup_module
from .tools import cluster as cluster_module
from .tools import compare as compare_module
from .tools import data_files as data_files_module
from .tools import docs as docs_module
from .tools import examples as examples_module
from .tools import execute as execute_module
from .tools import graph_tool as graph_module
from .tools import introspection, workspace
from .tools import journal as journal_module
from .tools import process as process_module
from .tools import progression as progression_module
from .tools import provenance as provenance_module
from .tools import search_programs as search_programs_module
from .tools import segments as segments_module
from .tools import session_config as session_config_module
from .tools import sweep as sweep_module
from .tools import tagging as tagging_module
from .tools import templates as templates_module
from .tools import timeline as timeline_module
from .tools import visualize as visualize_module

mcp = FastMCP("cdp-mcp")

# Knowledge index — built once, captured by closure into the introspection
# tools. Loader logs "[cdp-mcp] Loaded N knowledge entries" to stderr.
_index = KnowledgeIndex.load()
introspection.register(mcp, _index)

# breakpoint() — pure envelope constructor; only dependency is the
# knowledge index (for construction-time breakpoint_capable validation).
breakpoint_module.register(mcp, _index)


# CDP detection. We do it once at import so the SessionManager has a
# deterministic CDP version to capture into new sessions' config.json,
# even when set_session is called minutes after server startup. The error
# message (if any) is stashed for create_server() to log.
try:
    _cdp_config: CDPConfig | None = detect_cdp()
    _cdp_error: str | None = None
except CDPConfigError as _e:
    _cdp_config = None
    _cdp_error = str(_e)


def _resolve_sessions_root() -> Path:
    """Pick the sessions root from $CDP_MCP_SESSIONS_ROOT or fall back to ~."""
    raw = os.environ.get("CDP_MCP_SESSIONS_ROOT")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "cdp_sessions").resolve()


_sessions_root = _resolve_sessions_root()
_session_manager = SessionManager(_sessions_root, lambda: _cdp_config)

# In-memory "recent successful nodes" deque, shared by Task 5+ tools. Reset
# on each server process start AND on every set_session() call — "latest"
# and "prev_1..prev_4" are conversational state, not session state.
_latest_tracker = LatestTracker()

# Cache root for content-addressable artifacts (Phase 1b cache, etc.). The
# directory is created at startup so the path-scope security check has a
# stable, resolved directory to validate against from day one, even before
# any caching actually happens.
_cache_root = (Path.home() / ".cdp_mcp" / "cache").resolve()
_cache_root.mkdir(parents=True, exist_ok=True)

workspace.register(
    mcp,
    _session_manager,
    latest_tracker=_latest_tracker,
    cdp_config_provider=lambda: _cdp_config,
    cache_root=_cache_root,
)

execute_module.register(
    mcp,
    sessions=_session_manager,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)

process_module.register(
    mcp,
    sessions=_session_manager,
    knowledge_index=_index,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)

graph_module.register(
    mcp,
    sessions=_session_manager,
    knowledge_index=_index,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)

batch_module.register(
    mcp,
    sessions=_session_manager,
    knowledge_index=_index,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)

visualize_module.register(
    mcp,
    sessions=_session_manager,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)

analyze_module.register(
    mcp,
    sessions=_session_manager,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)

# Observation track (Phase 2): segments / compare / progression share
# visualize's dependency shape; cluster (Phase 3) joins them.
for _obs_module in (
    segments_module, compare_module, progression_module, cluster_module,
):
    _obs_module.register(
        mcp,
        sessions=_session_manager,
        cdp_config_provider=lambda: _cdp_config,
        latest_tracker=_latest_tracker,
        cache_root=_cache_root,
    )

# Phase 3: docs search, provenance, data files.
docs_module.register(
    mcp,
    docs_root_provider=lambda: docs_module.derive_docs_root(
        _cdp_config.cdp_path if _cdp_config else None
    ),
    index_path=_cache_root.parent / "docs_index.sqlite",
    cdp_config_provider=lambda: _cdp_config,
)

provenance_module.register(
    mcp,
    sessions=_session_manager,
    latest_tracker=_latest_tracker,
)

data_files_module.register(
    mcp,
    sessions=_session_manager,
)

# Phase 4: sweep, session lifecycle, cleanup, templates, prompts.
sweep_module.register(
    mcp,
    sessions=_session_manager,
    knowledge_index=_index,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)
tagging_module.register(mcp, sessions=_session_manager, latest_tracker=_latest_tracker)
journal_module.register(mcp, sessions=_session_manager)
session_config_module.register(mcp, sessions=_session_manager)
cleanup_module.register(
    mcp,
    sessions=_session_manager,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)
templates_module.register(mcp, sessions=_session_manager)
prompts.register(mcp)

# Phase 5: packaged examples library (cdp://examples/*, read via read_doc).
examples_module.register(mcp)

# Phase 6: gesture construction + discoverability.
timeline_module.register(
    mcp,
    sessions=_session_manager,
    knowledge_index=_index,
    cdp_config_provider=lambda: _cdp_config,
    latest_tracker=_latest_tracker,
    cache_root=_cache_root,
)
search_programs_module.register(
    mcp,
    knowledge_index=_index,
    index_path=_cache_root.parent / "programs_index.sqlite",
)
search_programs_module.register_prompt(mcp)


def create_server() -> FastMCP:
    """Log startup status to stderr and return the configured server."""
    if _cdp_config is not None:
        print(
            f"[cdp-mcp] CDP_PATH={_cdp_config.cdp_path} "
            f"version={_cdp_config.version}",
            file=sys.stderr,
        )
        print(
            f"[cdp-mcp] Detected binaries: "
            f"{', '.join(_cdp_config.detected_binaries[:5])}",
            file=sys.stderr,
        )
    else:
        print(f"[cdp-mcp] WARNING: {_cdp_error}", file=sys.stderr)
        print(
            "[cdp-mcp] Server starting anyway; introspection and workspace "
            "tools will work but execute/process will fail.",
            file=sys.stderr,
        )
    print(f"[cdp-mcp] Sessions root: {_sessions_root}", file=sys.stderr)
    print(f"[cdp-mcp] Cache root: {_cache_root}", file=sys.stderr)
    print(
        "[cdp-mcp] Conversational state (latest, prev_1..prev_4) is "
        "per-process and resets on server restart and on every "
        "set_session() call.",
        file=sys.stderr,
    )
    return mcp
