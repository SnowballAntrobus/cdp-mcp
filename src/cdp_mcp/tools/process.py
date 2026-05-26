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
from ..graph import (
    GraphDir,
    LatestTracker,
    ReferenceResolutionError,
    build_context_block,
    resolve_target,
    verify_output,
)
from ..knowledge.loader import KnowledgeIndex
from ..processing import build_cdp_argv, validate_params
from ..pvoc import maybe_insert_pvoc
from ..schema import ContextBlock, ErrorEntry, InputRecord, NodeLineage, ResultEnvelope
from ..security import SecurityError, validate_command
from ..session import SessionManager, SessionNotActiveError
from ..subprocess_core import run_cdp_command
from ..utils import sha256_file


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

    # 4. Arity normalize + check.
    inputs = [input] if isinstance(input, str) else list(input)
    if entry.input_arity in ("N", "variable"):
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=None,
            errors=[
                ErrorEntry(
                    type="unsupported_arity",
                    message=(
                        f"Entry {program} {mode} has variable input arity "
                        f"({entry.input_arity!r}); not supported in Phase 1a."
                    ),
                    fix="Use execute() for variable-arity CDP commands.",
                )
            ],
        )
    if len(inputs) != entry.input_arity:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=None,
            errors=[
                ErrorEntry(
                    type="arity_mismatch",
                    message=(
                        f"Entry {program} {mode} expects "
                        f"{entry.input_arity} input(s); got {len(inputs)}."
                    ),
                    fix=(
                        f"Pass exactly {entry.input_arity} input "
                        "reference(s)."
                    ),
                )
            ],
        )

    # 5. Resolve inputs.
    try:
        resolved_inputs = [
            resolve_target(ref, session, latest_tracker) for ref in inputs
        ]
    except ReferenceResolutionError as e:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=None,
            errors=[
                ErrorEntry(
                    type="reference_resolution",
                    message=str(e),
                    fix=(
                        "Check the reference: 'latest', "
                        "'<graph_id>:<node_id>', an absolute path, or "
                        "a filename inside the session's inputs/ "
                        "directory."
                    ),
                )
            ],
        )

    # 6. Validate params.
    param_errors, param_warnings = validate_params(entry, params_dict)
    if param_errors:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=None,
            errors=param_errors,
            warnings=param_warnings,
        )

    # 7. Create graph dir + write graph.json (user intent).
    slug = f"{entry.program}-{entry.mode}"
    graph_dir = GraphDir(session, slug)
    graph_dir.set_graph_definition(
        {
            "program": program,
            "mode": mode,
            "input": input,  # original ref(s), not resolved paths
            "params": params_dict,
            "output_name": output_name,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    # 8. PVOC auto-insert per input.
    counter = 1
    post_pvoc_paths: list[Path] = []
    pvoc_source_nodes: list[str | None] = []
    for resolved_path in resolved_inputs:
        pvoc_result = await maybe_insert_pvoc(
            input_path=resolved_path,
            target_domain=entry.domain,
            graph_dir=graph_dir,
            node_id=f"n{counter}",
            cdp_path=cdp.cdp_path,
            session_root=session.root,
            cache_root=cache_root,
            cdp_version=cdp.version,
            timeout_seconds=timeout_seconds,
            ctx=ctx,
        )
        if pvoc_result.state == "failed":
            return _failed_envelope(
                session,
                latest_tracker,
                active_graph=graph_dir.id,
                errors=[pvoc_result.error_entry]
                if pvoc_result.error_entry is not None
                else [],
                warnings=param_warnings,
            )
        post_pvoc_paths.append(pvoc_result.output_path)
        if pvoc_result.state == "succeeded":
            pvoc_source_nodes.append(pvoc_result.node_id)
            counter += 1
        else:
            pvoc_source_nodes.append(None)

    # 9. Build main op argv.
    main_node_id = f"n{counter}"
    out_ext = ".ana" if entry.domain == "spectral" else ".wav"
    normalized_name, name_error = _normalize_output_name(
        output_name, out_ext
    )
    if name_error is not None:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=graph_dir.id,
            errors=[name_error],
            warnings=param_warnings,
        )
    out_filename = normalized_name or f"{main_node_id}_{slug}{out_ext}"
    output_path = graph_dir.root / out_filename
    argv = build_cdp_argv(
        entry, post_pvoc_paths, output_path, params_dict, cwd=session.root
    )

    # 10. Security validation.
    try:
        validated = validate_command(
            argv, cdp.cdp_path, session.root, cache_root
        )
    except SecurityError as e:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=graph_dir.id,
            errors=e.errors,
            warnings=param_warnings,
        )

    # 11. Run main op.
    started_at = datetime.now(timezone.utc)
    sub = await run_cdp_command(
        validated,
        cwd=session.root,
        timeout_seconds=timeout_seconds,
        ctx=ctx,
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
    if sub.timed_out:
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
    if not verification.ok and sub.exit_code == 0 and not sub.timed_out:
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
# Helpers
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


# Audio extensions we recognize as "the user clearly meant a specific
# format." If output_name carries one of these and it isn't the one
# this program writes, we refuse rather than silently rewrite — better
# to surface the mismatch than to mint a wav named ``foo.aiff``.
_AUDIO_EXTENSIONS = frozenset({".wav", ".aif", ".aiff", ".ana", ".pvx"})


def _normalize_output_name(
    name: str | None, expected_ext: str
) -> tuple[str | None, ErrorEntry | None]:
    """Normalize a caller-supplied ``output_name`` to carry ``expected_ext``.

    Why this exists: CDP binaries (brassage at least) silently append
    ``.wav`` when the output argv is extensionless, but our verifier
    looks at exactly the path we passed — so an extensionless
    ``output_name`` made CDP write ``foo.wav`` while we checked ``foo``
    and reported ``output_verification_failed``. Controlling the
    extension on our side keeps the argv and the verifier in lockstep.

    Returns ``(normalized_name, error)``:

    - ``name is None`` → ``(None, None)``: caller didn't specify; let the
      auto-name path in :func:`process` fill in ``<node>_<slug>.<ext>``.
    - Already ends with ``expected_ext`` (case-insensitive) →
      ``(name, None)``.
    - No extension at all → ``(name + expected_ext, None)``.
    - Any other extension → ``(None, ErrorEntry)``. ``invalid_output_name``
      with a ``fix`` pointing at the right extension. We refuse rather
      than silently mutate because the user clearly intended a specific
      format we can't deliver here.
    """
    if name is None:
        return None, None
    suffix = Path(name).suffix
    if not suffix:
        return name + expected_ext, None
    if suffix.lower() == expected_ext.lower():
        return name, None
    return None, ErrorEntry(
        type="invalid_output_name",
        message=(
            f"output_name {name!r} has extension {suffix!r}; this "
            f"program writes {expected_ext} files."
        ),
        fix=(
            f"Pass output_name with no extension (the {expected_ext} "
            f"will be appended automatically) or with {expected_ext} "
            "explicitly."
        ),
    )
