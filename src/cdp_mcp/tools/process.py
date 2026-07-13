"""The ``process()`` MCP tool — curated CDP invocation with PVOC auto-insertion.

The main attraction of Phase 1a. Where ``execute()`` (Task 5) is the raw
escape hatch, ``process()`` is the curated path: it looks up the knowledge
entry, validates params against the entry's ``ParameterSpec``, automatically
inserts ``pvoc anal`` or ``pvoc synth`` nodes when input domains don't
match, runs each node through the security boundary, and records full
lineage in a fresh graph directory.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..config import CDPConfig
from ..graph import LatestTracker, build_context_block
from ..knowledge.loader import KnowledgeIndex
from ..schema import ContextBlock, ErrorEntry, ResultEnvelope
from ..session import SessionManager, SessionNotActiveError
from .node_execution import execute_validated_node
from .node_validation import validate_node


async def process_impl(
    ctx: Context,
    program: str,
    mode: str,
    input: str | list[str],
    params: dict[str, Any] | None = None,
    output_name: str | None = None,
    timeout_seconds: float = 120.0,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> dict:
    """Implementation of ``process()``.

    Exposed at module scope so callers can invoke without going through
    the MCP protocol layer (acceptance tests, scripts). The
    ``@mcp.tool()`` wrapper inside :func:`register` is a thin closure
    that rebinds the deps from server-startup state and delegates here.

    Looks up the (program, mode) pair in the knowledge index, validates
    params against the entry's ParameterSpec, auto-inserts PVOC nodes
    when input domains don't match, runs each node through the security
    boundary, and records full lineage in a fresh graph directory under
    the active session.

    On success, ``latest`` updates to the main op's node, ``output``
    in the envelope is the absolute path to the main op's output file,
    and ``context.active_graph`` is the new graph's id.

    ``output_name`` is normalized to carry the right extension before
    the argv reaches CDP: omit the extension and the appropriate one
    (``.wav`` for time-domain programs, ``.ana`` for spectral) is
    appended automatically. Passing a mismatched audio extension
    (e.g. ``.aiff``) returns a structured ``invalid_output_name``
    error rather than silently rewriting the name.
    """
    params_dict: dict[str, Any] = params or {}

    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _failed_envelope_no_session(latest_tracker, str(e))

    # 2. Require CDP detected.
    cdp = cdp_config_provider()
    if cdp is None:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=None,
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
        )

    # 3. Knowledge lookup.
    entry = knowledge_index.get(program, mode)
    if entry is None or not entry.curated:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=None,
            errors=[
                ErrorEntry(
                    type="not_curated",
                    message=(
                        f"No curated knowledge entry for "
                        f"{program!r} {mode!r}."
                    ),
                    fix=(
                        "Use list_programs() to see curated entries. "
                        "For uncurated CDP programs, use execute()."
                    ),
                )
            ],
        )

    # 4–10: pre-subprocess validation and planning, factored out so the
    # same chain serves graph(dry_run=True) and batch() without drift.
    validation = await validate_node(
        ctx=ctx,
        entry=entry,
        inputs=[input] if isinstance(input, str) else list(input),
        params=params_dict,
        output_name=output_name,
        timeout_seconds=timeout_seconds,
        session=session,
        cdp=cdp,
        latest_tracker=latest_tracker,
        cache_root=cache_root,
    )
    if validation.errors:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=validation.graph_dir.id if validation.graph_dir else None,
            errors=validation.errors,
            warnings=validation.warnings,
        )

    # validate_node populates all of these on the success path.
    graph_dir = validation.graph_dir
    assert graph_dir is not None  # success path invariant
    assert validation.output_path is not None
    assert validation.main_node_id is not None
    param_warnings = validation.warnings

    # 11–15: subprocess run, verification, lineage, error aggregation —
    # extracted to execute_validated_node (Task 11b) so graph()/batch()
    # execute through exactly this code path.
    outcome = await execute_validated_node(
        ctx=ctx,
        validation=validation,
        program=program,
        mode=mode,
        params=params_dict,
        timeout_seconds=timeout_seconds,
        session=session,
        cdp=cdp,
    )
    if outcome.bookkeeping_error is not None:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=graph_dir.id,
            errors=[outcome.bookkeeping_error],
            warnings=param_warnings,
        )

    sub = outcome.subprocess_result
    if outcome.success:
        latest_tracker.update(graph_dir.id, validation.main_node_id)

    # 16. Envelope.
    envelope = ResultEnvelope(
        status="ok" if outcome.success else "failed",
        output=str(validation.output_path) if outcome.success else None,
        stdout=sub.stdout,
        stderr=sub.stderr,
        exit_code=sub.exit_code,
        errors=outcome.errors,
        warnings=param_warnings,
        cached=False,
        duration_ms=sub.duration_ms,
        context=build_context_block(
            session, latest_tracker, active_graph=graph_dir.id
        ),
    )
    return envelope.model_dump(mode="json")


def register(
    mcp: FastMCP,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``process`` tool against ``mcp``.

    Thin wrapper around :func:`process_impl` — the MCP-visible shape
    stays free of dependency-injection params, while the implementation
    lives at module scope for in-process callers (acceptance test, etc).
    """

    @mcp.tool()
    async def process(
        ctx: Context,
        program: str,
        mode: str,
        input: str | list[str],
        params: dict[str, Any] | None = None,
        output_name: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict:
        """Run a curated CDP program with full bookkeeping.

        Looks up the (program, mode) pair in the knowledge index, validates
        params against the entry's ParameterSpec, auto-inserts PVOC nodes
        when input domains don't match, runs each node through the security
        boundary, and records full lineage in a fresh graph directory under
        the active session.

        On success, ``latest`` updates to the main op's node, ``output``
        in the envelope is the absolute path to the main op's output file,
        and ``context.active_graph`` is the new graph's id.

        Use this for curated programs (those with ``curated: true`` in the
        knowledge index). For uncurated programs or raw escape hatches,
        use ``execute()``.

        ``output_name`` is normalized to carry the right extension before
        the argv reaches CDP: omit the extension and the appropriate one
        (``.wav`` for time-domain programs, ``.ana`` for spectral) is
        appended automatically. Passing a mismatched audio extension
        (e.g. ``.aiff``) returns a structured ``invalid_output_name``
        error rather than silently rewriting the name.
        """
        return await process_impl(
            ctx,
            program,
            mode,
            input,
            params,
            output_name,
            timeout_seconds,
            sessions=sessions,
            knowledge_index=knowledge_index,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )


# ---------------------------------------------------------------------------
# Failure-envelope helpers
# ---------------------------------------------------------------------------


def _failed_envelope_no_session(
    latest_tracker: LatestTracker, message: str
) -> dict:
    """Construct a failed envelope when there's no active session."""
    return ResultEnvelope(
        status="failed",
        output=None,
        stdout="",
        stderr="",
        exit_code=None,
        errors=[
            ErrorEntry(
                type="no_active_session",
                message=message,
                fix="Call set_session('<name>') first.",
            )
        ],
        warnings=[],
        cached=False,
        duration_ms=None,
        context=ContextBlock(
            active_graph=None,
            latest=latest_tracker.latest,
            recent_graphs=[],
            available_sources=[],
        ),
    ).model_dump(mode="json")


def _failed_envelope(
    session,
    latest_tracker: LatestTracker,
    active_graph: str | None,
    errors: list[ErrorEntry],
    warnings: list[str] | None = None,
) -> dict:
    """Construct a failed envelope when a session is active.

    ``active_graph`` is the graph id if one was created before failure
    (PVOC failures, security failures after graph creation), else ``None``.
    """
    return ResultEnvelope(
        status="failed",
        output=None,
        stdout="",
        stderr="",
        exit_code=None,
        errors=errors,
        warnings=warnings or [],
        cached=False,
        duration_ms=None,
        context=build_context_block(
            session, latest_tracker, active_graph=active_graph
        ),
    ).model_dump(mode="json")


