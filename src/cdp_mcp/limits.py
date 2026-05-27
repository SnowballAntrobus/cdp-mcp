"""Resource limits, with env-var overrides for the values users
typically want to tune.

Defaults match the project's tuned resource caps; override via the
corresponding ``CDP_MCP_*`` env variable below. Invalid values
(non-numeric, non-positive) fall back to defaults with a stderr
warning, matching the codebase's existing env-var resolution
pattern. Edit env vars manually — they're a developer/operator
tuning surface, not LLM-tunable.

Two limits:

- ``OUTPUT_DURATION_CAP_S`` — predicted output duration cap, seconds.
  Used by ``duration_preflight.check_duration_preflight``. Default 300s.
- ``OUTPUT_FILE_SIZE_CAP_BYTES`` — output file size cap. Enforced by
  the disk watchdog in ``subprocess_core.run_cdp_command``. Default 1 GB.
"""

from __future__ import annotations

import os
import sys


def _resolve_positive_float(env_var: str, default: float, label: str) -> float:
    """Read a positive float from ``env_var`` or fall back to ``default``.

    Invalid values (non-numeric, non-positive) emit a stderr warning
    naming the env var and label, then return ``default``. Never raises.
    """
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        print(
            f"[cdp-mcp] Warning: ignoring {env_var}={raw!r} ({label}): "
            f"not a number. Using default {default}.",
            file=sys.stderr,
        )
        return default
    if value <= 0:
        print(
            f"[cdp-mcp] Warning: ignoring {env_var}={raw!r} ({label}): "
            f"must be positive. Using default {default}.",
            file=sys.stderr,
        )
        return default
    return value


OUTPUT_DURATION_CAP_S: float = _resolve_positive_float(
    "CDP_MCP_DURATION_CAP_S", 300.0, "output duration cap, seconds",
)

OUTPUT_FILE_SIZE_CAP_BYTES: int = int(_resolve_positive_float(
    "CDP_MCP_OUTPUT_SIZE_CAP_BYTES", 1_073_741_824.0,
    "output file size cap, bytes",
))
