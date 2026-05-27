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
from typing import Any, Literal

import soundfile as sf
from mcp.server.fastmcp import Context, FastMCP

from ..breakpoint_compiler import compile_breakpoint_value, is_breakpoint_value
from ..config import CDPConfig
from ..duration_preflight import check_duration_preflight
from ..error_parsing import parse_cdp_errors
from ..graph import (
    GraphDir,
    LatestTracker,
    ReferenceResolutionError,
    build_context_block,
    lookup_source_wav_duration,
    resolve_target,
    verify_output,
)
from ..knowledge.loader import KnowledgeIndex
from ..limits import OUTPUT_FILE_SIZE_CAP_BYTES
from ..processing import build_cdp_argv, validate_params
from ..pvoc import maybe_insert_pvoc, read_ana_duration
from ..schema import (
    CompiledBreakpoint,
    ContextBlock,
    ErrorEntry,
    InputRecord,
    NodeLineage,
    ResultEnvelope,
)
from ..security import SecurityError, validate_command
from ..session import Session, SessionManager, SessionNotActiveError
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

    # 6.5. Pre-flight duration prediction. Catches runaway durations
    # before CDP spawns; the disk watchdog (Task 7) is the reactive
    # complement for cases pre-flight can't predict.
    preflight_errors = await check_duration_preflight(
        entry=entry,
        params=params_dict,
        resolved_inputs=resolved_inputs,
        session_root=session.root,
        cdp_path=cdp.cdp_path,
        cdp_version=cdp.version,
        ana_duration_cache_dir=session.tmp_dir / "ana_durations",
    )
    if preflight_errors:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=None,
            errors=preflight_errors,
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

    # 8.5. Compile breakpoint parameters (Task 8). For each list / .brk
    # path-valued param, validate breakpoint_capable, resolve the
    # source duration, run the compiler, and mutate params_dict to
    # point at the compiled .brk file so build_cdp_argv renders it.
    breakpoint_errors: list[ErrorEntry] = []
    breakpoint_warnings: list[str] = []
    compiled_breakpoints: dict[str, CompiledBreakpoint] = {}
    for param_name, spec in entry.parameters.items():
        value = params_dict.get(param_name)
        if value is None or not is_breakpoint_value(value):
            continue
        if not spec.breakpoint_capable:
            breakpoint_errors.append(ErrorEntry(
                type="param_breakpoint_not_capable",
                message=(
                    f"Parameter {param_name!r} got a breakpoint value but "
                    f"its breakpoint_capable flag is false."
                ),
                fix=(
                    f"Either pass a constant numeric value, or update "
                    f"the entry to set "
                    f"parameters.{param_name}.breakpoint_capable to true "
                    f"(curation change)."
                ),
            ))
            continue
        src_duration, src_kind = await _resolve_source_duration(
            session=session,
            post_pvoc_paths=post_pvoc_paths,
            pvoc_source_nodes=pvoc_source_nodes,
            graph_dir=graph_dir,
            cdp_path=cdp.cdp_path,
            cdp_version=cdp.version,
        )
        result = compile_breakpoint_value(
            param_name=param_name,
            param_spec=spec,
            value=value,
            source_duration_s=src_duration,
            source_kind=src_kind,
            session_root=session.root,
            envelopes_dir=session.envelopes_dir,
        )
        breakpoint_errors.extend(result.errors)
        breakpoint_warnings.extend(result.warnings)
        if result.record is not None and result.compiled_path is not None:
            params_dict[param_name] = result.compiled_path
            compiled_breakpoints[param_name] = result.record

    if breakpoint_errors:
        return _failed_envelope(
            session,
            latest_tracker,
            active_graph=graph_dir.id,
            errors=breakpoint_errors,
            warnings=param_warnings + breakpoint_warnings,
        )

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
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_source_duration(
    *,
    session: Session,
    post_pvoc_paths: list[Path],
    pvoc_source_nodes: list[str | None],
    graph_dir: GraphDir,
    cdp_path: Path,
    cdp_version: str,
) -> tuple[
    float | None,
    Literal["input_wav", "pvoc_lineage", "ana_sfprops"] | None,
]:
    """Best-effort source-audio duration for breakpoint compilation.

    Order of attempts:

    1. ``.wav`` input → read via ``sf.info``; tag ``input_wav``.
    2. ``.ana`` from a same-graph auto-PVOC node → look up the node's
       recorded ``source_wav_duration_s``; tag ``pvoc_lineage``.
    3. ``.ana`` with no same-graph PVOC node (pre-converted .ana in
       ``inputs/``, or cross-graph reference) → shell out to
       ``sfprops -d`` via :func:`pvoc.read_ana_duration`; tag
       ``ana_sfprops``. Phase 2 Task 2.

    Returns ``(None, None)`` only when every attempt fails — the caller
    then surfaces ``param_breakpoint_no_source_duration``. Cross-graph
    lineage walking remains out of scope.
    """
    if not post_pvoc_paths:
        return None, None
    first = post_pvoc_paths[0]
    if first.suffix.lower() == ".wav":
        try:
            return float(sf.info(str(first)).duration), "input_wav"
        except Exception:  # noqa: BLE001
            return None, None
    if first.suffix.lower() == ".ana":
        node_id = pvoc_source_nodes[0] if pvoc_source_nodes else None
        if node_id:
            duration = lookup_source_wav_duration(
                session, graph_dir.id, node_id
            )
            if duration is not None:
                return duration, "pvoc_lineage"
        # Fallback: pre-converted or cross-graph .ana — shell out.
        cache_dir = session.tmp_dir / "ana_durations"
        cache_dir.mkdir(parents=True, exist_ok=True)
        d = await read_ana_duration(
            first,
            session_root=session.root,
            cdp_path=cdp_path,
            cache_dir=cache_dir,
            cdp_version=cdp_version,
        )
        if d is not None:
            return d, "ana_sfprops"
    return None, None


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
