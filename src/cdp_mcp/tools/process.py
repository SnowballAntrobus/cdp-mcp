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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..config import CDPConfig
from ..error_parsing import parse_cdp_errors
from ..graph import (
    LatestTracker,
    build_context_block,
    verify_output,
)
from ..knowledge.loader import KnowledgeIndex
from ..limits import OUTPUT_FILE_SIZE_CAP_BYTES
from ..schema import (
    ContextBlock,
    ErrorEntry,
    InputRecord,
    NodeLineage,
    ResultEnvelope,
)
from ..session import SessionManager, SessionNotActiveError
from ..subprocess_core import run_cdp_command
from ..utils import sha256_file
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

    # validate_node populates all of these on the success path; bind to
    # local names so the unchanged step 11+ code below reads as before.
    graph_dir = validation.graph_dir
    assert graph_dir is not None  # success path invariant
    assert validation.planned_argv is not None
    assert validation.output_path is not None
    assert validation.main_node_id is not None
    assert validation.out_filename is not None
    assert validation.post_pvoc_paths is not None
    assert validation.pvoc_source_nodes is not None
    validated = validation.planned_argv
    output_path = validation.output_path
    main_node_id = validation.main_node_id
    out_filename = validation.out_filename
    post_pvoc_paths = validation.post_pvoc_paths
    pvoc_source_nodes = validation.pvoc_source_nodes
    compiled_breakpoints = validation.compiled_breakpoints
    param_warnings = validation.warnings

    # 11. Run main op.
    started_at = datetime.now(timezone.utc)
    sub = await run_cdp_command(
        validated,
        cwd=session.root,
        timeout_seconds=timeout_seconds,
        ctx=ctx,
        output_path=output_path,
        size_cap_bytes=OUTPUT_FILE_SIZE_CAP_BYTES,
    )
    finished_at = datetime.now(timezone.utc)

    # 12. Verify output (Task 4).
    verification = verify_output(output_path)

    # 13. Build main node lineage.
    output_sha: str | None = None
    if verification.exists and verification.size_bytes > 0:
        try:
            output_sha = sha256_file(output_path)
        except OSError:
            output_sha = None

    main_inputs = [
        InputRecord(
            path=str(p),
            sha256=sha256_file(p) if p.exists() else "",
            source_node=src,
        )
        for p, src in zip(post_pvoc_paths, pvoc_source_nodes, strict=False)
    ]
    lineage = NodeLineage(
        argv=validated,
        inputs=main_inputs,
        output_path=str(output_path),
        output_sha256=output_sha,
        params=params_dict,
        cdp_version=cdp.version,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=sub.duration_ms,
        exit_code=sub.exit_code,
        compiled_breakpoints=compiled_breakpoints,
    )

    try:
        graph_dir.add_node(main_node_id, out_filename, lineage)
    except OSError as e:
        # Bookkeeping write failed; surface as a structured error.
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=graph_dir.id,
            errors=[
                ErrorEntry(
                    type="graph_bookkeeping_failed",
                    message=(
                        f"Main op ran but lineage write failed: {e}"
                    ),
                    fix="Inspect the graph directory on disk for clues.",
                )
            ],
            warnings=param_warnings,
        )

    # 14 + 15: status, latest, errors aggregation.
    result_errors: list[ErrorEntry] = []
    # size_cap_exceeded takes precedence over the generic subprocess_error
    # that the SIGKILL would otherwise produce — the specific signal is
    # more actionable than "exited with code <signal>".
    if sub.size_cap_exceeded:
        result_errors.append(
            ErrorEntry(
                type="size_cap_exceeded",
                message=(
                    f"output file exceeded the {sub.triggered_at_bytes:,}-byte "
                    f"cap (limit: {OUTPUT_FILE_SIZE_CAP_BYTES:,} bytes); "
                    f"the subprocess was killed and partial output removed."
                ),
                fix=(
                    "Reduce the parameters that drive output size (counts, "
                    "multipliers, time spans), or use a shorter input. To "
                    "raise the cap for this work, set "
                    "CDP_MCP_OUTPUT_SIZE_CAP_BYTES in the environment "
                    "before starting the server."
                ),
            )
        )
    elif sub.timed_out:
        result_errors.append(
            ErrorEntry(
                type="timeout",
                message=(
                    f"{program} {mode} did not finish within "
                    f"{timeout_seconds}s."
                ),
                fix=(
                    "Raise timeout_seconds or use a smaller / shorter "
                    "input."
                ),
            )
        )
    elif sub.exit_code != 0:
        result_errors.append(
            ErrorEntry(
                type="subprocess_error",
                message=f"CDP exited with code {sub.exit_code}.",
                fix=None,
            )
        )
    if (
        not verification.ok
        and sub.exit_code == 0
        and not sub.timed_out
        and not sub.size_cap_exceeded
    ):
        # CDP succeeded but the output doesn't look healthy.
        result_errors.append(
            ErrorEntry(
                type="output_verification_failed",
                message=(
                    "Output file did not pass verification: "
                    + "; ".join(verification.errors)
                ),
                fix=(
                    "Inspect the output file directly; CDP exited 0 "
                    "but the result is empty, silent, or otherwise "
                    "unusable."
                ),
            )
        )

    # Pattern-match specific CDP failure modes into structured entries.
    # Skip on timeout — partial output isn't worth second-guessing.
    if not sub.timed_out:
        result_errors.extend(parse_cdp_errors(
            stdout=sub.stdout,
            stderr=sub.stderr,
            exit_code=sub.exit_code,
            expected_output=output_path,
            verification=verification,
        ))

    success = (
        sub.exit_code == 0 and not sub.timed_out and verification.ok
    )
    status: str = "ok" if success else "failed"

    if success:
        latest_tracker.update(graph_dir.id, main_node_id)

    # 16. Envelope.
    envelope = ResultEnvelope(
        status=status,  # type: ignore[arg-type]  # Literal narrowed at runtime
        output=str(output_path) if success else None,
        stdout=sub.stdout,
        stderr=sub.stderr,
        exit_code=sub.exit_code,
        errors=result_errors,
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


