"""FastMCP server assembly.

All logging here goes to ``sys.stderr``. The MCP stdio transport uses stdout
for JSON-RPC traffic — any stray write to stdout will corrupt the protocol and
break the client connection silently. Tool implementations must obey the same
rule.
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from .config import CDPConfigError, detect_cdp
from .tools import introspection

mcp = FastMCP("cdp-mcp")
introspection.register(mcp)


def create_server() -> FastMCP:
    """Validate the CDP install, log status to stderr, return the server."""
    try:
        cfg = detect_cdp()
        print(
            f"[cdp-mcp] CDP_PATH={cfg.cdp_path} version={cfg.version}",
            file=sys.stderr,
        )
        print(
            f"[cdp-mcp] Detected binaries: {', '.join(cfg.detected_binaries[:5])}",
            file=sys.stderr,
        )
    except CDPConfigError as e:
        print(f"[cdp-mcp] WARNING: {e}", file=sys.stderr)
        print(
            "[cdp-mcp] Server starting anyway; introspection tools will work "
            "but execute/process will fail.",
            file=sys.stderr,
        )
    return mcp
