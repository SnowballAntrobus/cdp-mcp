"""Pre-subprocess validation and planning for curated node invocations.

Factored out of :func:`cdp_mcp.tools.process.process_impl` so the same
validation-and-planning chain drives ``process()``, ``graph(dry_run=True)``,
``graph()`` full execution, and ``batch()`` — each consumer can call
:func:`validate_node` rather than reimplementing (and inevitably drifting
from) the validator.

This module is a pure refactor. Every step that lived as a numbered
section in ``process_impl`` (arity check → PVOC auto-insert → breakpoint
compile → argv build → security validate) lives here now, *unchanged in
behavior*. Tests stayed where they were — the existing process-tool
tests are the regression suite for this code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import soundfile as sf
from mcp.server.fastmcp import Context

from ..breakpoint_compiler import compile_breakpoint_value, is_breakpoint_value
from ..config import CDPConfig
from ..duration_preflight import check_duration_preflight
from ..graph import (
    GraphDir,
    LatestTracker,
    ReferenceResolutionError,
    lookup_source_wav_duration,
    resolve_target,
)
from ..processing import build_cdp_argv, validate_params
from ..pvoc import maybe_insert_pvoc, read_ana_duration
from ..schema import CompiledBreakpoint, ErrorEntry, KnowledgeEntry
from ..security import SecurityError, validate_command
from ..session import Session

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Output of :func:`validate_node`.

    Carries ``errors`` and ``warnings`` always; everything else is
    populated on the success path. When ``errors`` is non-empty, the
    caller routes to its failure envelope and reads ``graph_dir`` to
    populate ``active_graph`` (matching the pre-refactor behavior of
    surfacing the partial graph dir for failures from step 8 onward).

    Failure-stage mapping for ``graph_dir`` (preserves the contract
    established by the original ``process_impl``):

    - Arity / resolve / params / preflight errors → ``graph_dir`` is None
      (failure occurred before the graph directory was created).
    - PVOC / breakpoint / argv / security errors → ``graph_dir`` is set
      (failure occurred after step 7 created the graph directory).
    """

    errors: list[ErrorEntry]
    warnings: list[str]
    graph_dir: GraphDir | None = None
    planned_argv: list[str] | None = None
    output_path: Path | None = None
    main_node_id: str | None = None
    out_filename: str | None = None
    # Lineage inputs — flow into the main node's lineage after the
    # subprocess completes. None on early failure.
    post_pvoc_paths: list[Path] | None = None
    pvoc_source_nodes: list[str | None] | None = None
    compiled_breakpoints: dict[str, CompiledBreakpoint] = field(default_factory=dict)
    params_for_lineage: dict[str, Any] | None = None  # the mutated params dict
    # Informational — useful for Task 11a's graph(dry_run=True) reporting.
    predicted_duration_s: float | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def validate_node(
    *,
    ctx: Context,
    entry: KnowledgeEntry,
    inputs: list[str],
    params: dict[str, Any],
    output_name: str | None,
    timeout_seconds: float,
    session: Session,
    cdp: CDPConfig,
    latest_tracker: LatestTracker,
    cache_root: Path,
    dry_run: bool = False,
) -> ValidationResult:
    """Run pre-subprocess validation and planning for a single node.

    Default (``dry_run=False``): creates the graph directory, writes
    ``graph.json``, runs auto-PVOC where domains don't match, compiles
    breakpoint parameters to ``.brk`` files, builds the main op argv,
    and runs it through the security boundary. Returns a
    :class:`ValidationResult` carrying a planned argv plus all metadata
    the caller needs for subprocess execution and lineage construction.

    ``dry_run=True``: pure validation without side effects (no graph
    directory, no PVOC subprocesses, no breakpoint files written).
    Raises :class:`NotImplementedError` in Task 3 — Task 11a implements
    the dry-run semantics for ``graph()`` pre-execution checks. The
    parameter is in the signature now so Task 11a lands without forcing
    a follow-up signature edit at every caller.

    ``latest_tracker`` is taken (not used by validation itself) because
    :func:`resolve_target` consumes it to resolve the ``"latest"``
    reference.
    """
    if dry_run:
        raise NotImplementedError(
            "validate_node(dry_run=True) is reserved for Task 11a "
            "(graph dry-run pre-execution checks)."
        )

    params_dict = params  # caller-owned; we mutate this in step 8.5
    warnings: list[str] = []

    # 4. Arity normalize + check.
    if entry.input_arity in ("N", "variable"):
        return ValidationResult(
            errors=[
                ErrorEntry(
                    type="unsupported_arity",
                    message=(
                        f"Entry {entry.program} {entry.mode} has variable "
                        f"input arity ({entry.input_arity!r}); not supported "
                        f"in Phase 1a."
                    ),
                    fix="Use execute() for variable-arity CDP commands.",
                )
            ],
            warnings=warnings,
        )
    if len(inputs) != entry.input_arity:
        return ValidationResult(
            errors=[
                ErrorEntry(
                    type="arity_mismatch",
                    message=(
                        f"Entry {entry.program} {entry.mode} expects "
                        f"{entry.input_arity} input(s); got {len(inputs)}."
                    ),
                    fix=(
                        f"Pass exactly {entry.input_arity} input "
                        "reference(s)."
                    ),
                )
            ],
            warnings=warnings,
        )

    # 5. Resolve inputs.
    try:
        resolved_inputs = [
            resolve_target(ref, session, latest_tracker) for ref in inputs
        ]
    except ReferenceResolutionError as e:
        return ValidationResult(
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
            warnings=warnings,
        )

    # 6. Validate params.
    param_errors, param_warnings = validate_params(entry, params_dict)
    if param_errors:
        return ValidationResult(
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
        return ValidationResult(
            errors=preflight_errors,
            warnings=param_warnings,
        )

    # 7. Create graph dir + write graph.json (user intent).
    slug = f"{entry.program}-{entry.mode}"
    graph_dir = GraphDir(session, slug)
    # ``input`` field of graph.json reflects the original ref(s) the
    # caller supplied (not the resolved paths). When the caller passed
    # a single ref, surface it as a string; when multiple, as a list.
    original_input_ref: str | list[str] = (
        inputs[0] if len(inputs) == 1 else list(inputs)
    )
    graph_dir.set_graph_definition(
        {
            "program": entry.program,
            "mode": entry.mode,
            "input": original_input_ref,
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
            return ValidationResult(
                errors=(
                    [pvoc_result.error_entry]
                    if pvoc_result.error_entry is not None
                    else []
                ),
                warnings=param_warnings,
                graph_dir=graph_dir,
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
        return ValidationResult(
            errors=breakpoint_errors,
            warnings=param_warnings + breakpoint_warnings,
            graph_dir=graph_dir,
        )

    # 9. Build main op argv.
    main_node_id = f"n{counter}"
    out_ext = ".ana" if entry.domain == "spectral" else ".wav"
    normalized_name, name_error = _normalize_output_name(
        output_name, out_ext
    )
    if name_error is not None:
        return ValidationResult(
            errors=[name_error],
            warnings=param_warnings,
            graph_dir=graph_dir,
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
        return ValidationResult(
            errors=e.errors,
            warnings=param_warnings,
            graph_dir=graph_dir,
        )

    # Preserve pre-refactor behavior: on the success path the envelope's
    # ``warnings`` field carries only ``param_warnings``;
    # ``breakpoint_warnings`` is silently dropped. The combined list
    # only surfaces on the breakpoint-errors failure path above. (Likely
    # a latent quirk worth a follow-up, but Task 3 is a pure refactor —
    # no drive-by behavior changes.)
    return ValidationResult(
        errors=[],
        warnings=param_warnings,
        graph_dir=graph_dir,
        planned_argv=validated,
        output_path=output_path,
        main_node_id=main_node_id,
        out_filename=out_filename,
        post_pvoc_paths=post_pvoc_paths,
        pvoc_source_nodes=pvoc_source_nodes,
        compiled_breakpoints=compiled_breakpoints,
        params_for_lineage=params_dict,
    )


# ---------------------------------------------------------------------------
# Helpers (moved from process.py — used only internally by validate_node)
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

    Note (multi-input): this resolver is hardcoded to ``post_pvoc_paths[0]``
    (input 1). It does **not** read a parameter's ``breakpoint_duration_source``
    field. The only curated multi-input breakpoint-capable entry,
    ``combine cross``, declares ``breakpoint_duration_source: "input1"`` — which
    *coincides* with this ``[0]`` default, so it resolves correctly today. Honoring
    ``input2``/``max``/``min`` is deferred Task 8 work with no current consumer;
    don't assume the field is being consumed until that lands.
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
