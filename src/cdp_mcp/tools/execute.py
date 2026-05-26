"""The ``execute()`` MCP tool — the raw CDP escape hatch.

``execute(command)`` runs an arbitrary CDP command after three independent
security checks. It's the path the LLM reaches for when curation (via
``process()``, Task 6) gets in the way or when the program isn't curated.

Deliberately minimal — no graph directory, no ``latest`` tracking, no
output verification. Fire and return. Callers chain outputs by absolute
path if they want.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from ..config import CDPConfig
from ..error_parsing import parse_cdp_errors
from ..graph import LatestTracker, build_context_block
from ..schema import ContextBlock, ErrorEntry, ResultEnvelope
from ..security import SecurityError, validate_command
from ..session import SessionManager, SessionNotActiveError
from ..subprocess_core import run_cdp_command


async def execute_impl(
    ctx: Context,
    command: list[str],
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
    timeout_seconds: float = 120.0,
) -> dict:
    """Implementation of ``execute()``.

    Exposed at module scope so callers can invoke without going through the
    MCP protocol layer (acceptance tests, scripts). The ``@mcp.tool()``
    wrapper inside :func:`register` is a thin closure that rebinds these
    deps from the server-startup state and delegates here.

    Validates against three security checks before running:
    - ``argv[0]`` must resolve to a binary inside ``$CDP_PATH``
    - No shell metacharacters in any argument
    - Any path-like arg must resolve inside the active session or CDP cache

    Does NOT create a graph directory, track ``latest``, or verify output.
    For curated commands with full bookkeeping, use ``process()``.
    """
    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _envelope_failure(
            errors=[
                ErrorEntry(
                    type="no_active_session",
                    message=str(e),
                    fix="Call set_session('<name>') first.",
                )
            ],
            context=_no_session_context(latest_tracker),
        )

    # 2. Require CDP detected.
    cdp = cdp_config_provider()
    if cdp is None:
        return _envelope_failure(
            errors=[
                ErrorEntry(
                    type="cdp_not_configured",
                    message="CDP is not configured on this server.",
                    fix=(
                        "Set the CDP_PATH environment variable to the "
                        "directory containing CDP binaries and restart "
                        "the server."
                    ),
                )
            ],
            context=build_context_block(session, latest_tracker, active_graph=None),
        )

    # 3. Validate.
    try:
        validated = validate_command(
            command, cdp.cdp_path, session.root, cache_root
        )
    except SecurityError as e:
        return _envelope_failure(
            errors=e.errors,
            context=build_context_block(session, latest_tracker, active_graph=None),
        )

    # 4. Run.
    result = await run_cdp_command(
        validated,
        cwd=session.root,
        timeout_seconds=timeout_seconds,
        ctx=ctx,
    )

    # 5. Construct envelope.
    errors: list[ErrorEntry] = []
    if result.timed_out:
        errors.append(
            ErrorEntry(
                type="timeout",
                message=f"CDP did not finish within {timeout_seconds}s.",
                fix="Raise timeout_seconds or use a smaller input.",
            )
        )
    elif result.exit_code != 0:
        errors.append(
            ErrorEntry(
                type="subprocess_error",
                message=f"CDP exited with code {result.exit_code}.",
                fix=None,
            )
        )

    # Pattern-match specific CDP failure modes. execute() has no
    # engine-known expected output or verification, so
    # usage_banner_returned and silent_output won't fire here — only
    # output_exists and channel_mismatch are applicable.
    if not result.timed_out:
        errors.extend(parse_cdp_errors(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            expected_output=None,
            verification=None,
        ))

    status = "ok" if not errors else "failed"
    envelope = ResultEnvelope(
        status=status,
        output=None,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        errors=errors,
        warnings=[],
        cached=False,
        duration_ms=result.duration_ms,
        context=build_context_block(session, latest_tracker, active_graph=None),
    )
    return envelope.model_dump(mode="json")


def register(
    mcp: FastMCP,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``execute`` tool against ``mcp``.

    Thin wrapper around :func:`execute_impl` — the MCP-visible tool shape
    stays clean (no dependency-injection params leaking to the protocol),
    while the implementation lives at module scope for in-process callers.
    """

    @mcp.tool()
    async def execute(
        ctx: Context,
        command: list[str],
        timeout_seconds: float = 120.0,
    ) -> dict:
        """Run a CDP command directly (escape hatch).

        Validates against three security checks before running:
        - argv[0] must resolve to a binary inside $CDP_PATH
        - No shell metacharacters in any argument
        - Any path-like arg must resolve inside the active session or CDP cache

        Does NOT create a graph directory, track 'latest', or verify output.
        For curated commands with full bookkeeping, use process().
        """
        return await execute_impl(
            ctx,
            command,
            sessions=sessions,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
            timeout_seconds=timeout_seconds,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope_failure(
    errors: list[ErrorEntry],
    context: ContextBlock,
) -> dict:
    """Construct a failed-status envelope without a subprocess run."""
    return ResultEnvelope(
        status="failed",
        output=None,
        stdout="",
        stderr="",
        exit_code=None,
        errors=errors,
        warnings=[],
        cached=False,
        duration_ms=None,
        context=context,
    ).model_dump(mode="json")


def _no_session_context(latest_tracker: LatestTracker) -> ContextBlock:
    """ContextBlock for when there's no active session.

    Can't call ``build_context_block`` because it needs a Session to walk
    ``inputs_dir``. ``latest`` survives because it's tracker-state, not
    session-state.
    """
    return ContextBlock(
        active_graph=None,
        latest=latest_tracker.latest,
        recent_graphs=[],
        available_sources=[],
    )
