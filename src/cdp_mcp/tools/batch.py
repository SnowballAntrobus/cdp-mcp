"""The ``batch()`` MCP tool — N ``process()``-equivalent runs, one graph.

Phase 2. Exploration primitive: run the same curated (program, mode,
params) over a list of inputs — parameter constant, material varying —
and get every result in ONE graph directory without evicting the
conversational context (a 10-element batch pushes a single synthetic
``recent_graphs`` entry; design-doc Context Block rule 6).

Contracts (design doc, Tool Surface § batch):

- **Validate everything first, execute nothing on any validation
  failure.** Each element runs through ``validate_node(dry_run=True)``;
  one bad element short-circuits the whole batch before any subprocess.
- **Runtime failures don't cascade** — elements are independent, so a
  mid-batch CDP failure yields ``partial_success`` with the survivors
  on disk.
- Node ids are ``n1_batch_0`` … ``n1_batch_{N-1}`` (auto-PVOC nodes
  derive ``n1_batch_i_pvoc1``; the design sketch showed ``n0_batch_i``
  for these — the derived-suffix scheme shipped instead, uniform with
  ``graph()``).
- ``latest`` is untouched; elements resolve via ``latest_batch[i]`` or
  ``<graph_id>:n1_batch_i``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..config import CDPConfig
from ..graph import GraphDir, LatestTracker, build_context_block
from ..knowledge.loader import KnowledgeIndex
from ..schema import ContextBlock, ErrorEntry
from ..session import SessionManager, SessionNotActiveError
from .node_execution import execute_validated_node
from .node_validation import validate_node


async def batch_impl(
    ctx: Context,
    program: str,
    mode: str,
    inputs: list[str | list[str]],
    params: dict[str, Any] | None = None,
    timeout_seconds: float = 120.0,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> dict:
    """Implementation of ``batch()``."""
    params_dict: dict[str, Any] = params or {}

    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _no_session_failure(latest_tracker, str(e))
    cdp = cdp_config_provider()
    if cdp is None:
        return _failure(session, latest_tracker, [ErrorEntry(
            type="cdp_not_configured",
            message="CDP is not configured on this server.",
            fix=(
                "Set the CDP_PATH environment variable to the directory "
                "containing CDP binaries and restart the server."
            ),
        )])

    entry = knowledge_index.get(program, mode)
    if entry is None or not entry.curated:
        return _failure(session, latest_tracker, [ErrorEntry(
            type="not_curated",
            message=f"No curated knowledge entry for {program!r} {mode!r}.",
            fix=(
                "Use list_programs() to see curated entries. For "
                "uncurated CDP programs, use execute()."
            ),
        )])

    if not isinstance(inputs, list) or not inputs:
        return _failure(session, latest_tracker, [ErrorEntry(
            type="batch_spec_error",
            message="inputs must be a non-empty list of input references.",
            fix=(
                "Pass one reference per batch element (or a list of "
                "references per element for multi-input programs)."
            ),
        )])

    elements: list[list[str]] = [
        [e] if isinstance(e, str) else list(e) for e in inputs
    ]
    node_ids = [f"n1_batch_{i}" for i in range(len(elements))]

    # Phase A — validate every element without side effects. Any failure
    # short-circuits the whole batch: nothing has executed, nothing is
    # on disk, fix and resubmit.
    validation_reports: list[dict] = []
    any_invalid = False
    for i, element in enumerate(elements):
        vr = await validate_node(
            ctx=ctx,
            entry=entry,
            inputs=list(element),
            params=dict(params_dict),
            output_name=None,
            timeout_seconds=timeout_seconds,
            session=session,
            cdp=cdp,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
            dry_run=True,
        )
        ok = not vr.errors
        any_invalid = any_invalid or not ok
        validation_reports.append({
            "index": i,
            "input": inputs[i],
            "node_id": node_ids[i],
            "status": "ok" if ok else "failed",
            "errors": [e.model_dump() for e in vr.errors],
            "warnings": vr.warnings,
            "predicted_duration_s": vr.predicted_duration_s,
        })
    if any_invalid:
        bad = [r["index"] for r in validation_reports if r["status"] != "ok"]
        return {
            "status": "failed",
            "graph_id": None,
            "batch_size": len(elements),
            "elements": validation_reports,
            "errors": [ErrorEntry(
                type="batch_validation_failed",
                message=(
                    f"element(s) {bad} failed validation; the whole batch "
                    "was short-circuited — nothing executed."
                ),
                fix=(
                    "Fix the per-element errors in 'elements' and resubmit "
                    "the batch."
                ),
            ).model_dump()],
            "warnings": [],
            "context": build_context_block(
                session, latest_tracker, active_graph=None
            ).model_dump(mode="json"),
        }

    # Phase B — execute all elements into one shared graph directory.
    graph_dir = GraphDir(session, f"batch-{program}-{mode}")
    graph_dir.set_graph_definition({
        "program": program,
        "mode": mode,
        "inputs": inputs,
        "params": params_dict,
        "batch_size": len(elements),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    })

    reports: list[dict] = []
    succeeded = 0
    for i, element in enumerate(elements):
        validation = await validate_node(
            ctx=ctx,
            entry=entry,
            inputs=list(element),
            params=dict(params_dict),
            output_name=None,
            timeout_seconds=timeout_seconds,
            session=session,
            cdp=cdp,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
            graph_dir=graph_dir,
            node_id_base=node_ids[i],
        )
        if validation.errors:
            # Rare (phase A was clean) but real PVOC runs can fail in
            # ways planning couldn't predict.
            reports.append({
                "index": i,
                "input": inputs[i],
                "node_id": node_ids[i],
                "status": "failed",
                "errors": [e.model_dump() for e in validation.errors],
                "warnings": validation.warnings,
                "output": None,
            })
            continue
        outcome = await execute_validated_node(
            ctx=ctx,
            validation=validation,
            program=program,
            mode=mode,
            params=dict(params_dict),
            timeout_seconds=timeout_seconds,
            session=session,
            cdp=cdp,
        )
        errors = list(outcome.errors)
        if outcome.bookkeeping_error is not None:
            errors.append(outcome.bookkeeping_error)
        if outcome.success:
            succeeded += 1
        reports.append({
            "index": i,
            "input": inputs[i],
            "node_id": node_ids[i],
            "status": "ok" if outcome.success else "failed",
            "errors": [e.model_dump() for e in errors],
            "warnings": validation.warnings,
            "output": (
                str(validation.output_path) if outcome.success else None
            ),
            "exit_code": outcome.subprocess_result.exit_code,
            "duration_ms": outcome.subprocess_result.duration_ms,
        })

    # One atomic context event for the whole batch; `latest` untouched.
    latest_tracker.record_batch(graph_dir.id, node_ids)

    if succeeded == len(elements):
        status = "ok"
    elif succeeded:
        status = "partial_success"
    else:
        status = "failed"
    return {
        "status": status,
        "graph_id": graph_dir.id,
        "batch_size": len(elements),
        "elements": reports,
        "errors": [],
        "warnings": [],
        "context": build_context_block(
            session, latest_tracker, active_graph=graph_dir.id
        ).model_dump(mode="json"),
    }


def _failure(session, latest_tracker, errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "graph_id": None,
        "batch_size": 0,
        "elements": [],
        "errors": [e.model_dump() for e in errors],
        "warnings": [],
        "context": build_context_block(
            session, latest_tracker, active_graph=None
        ).model_dump(mode="json"),
    }


def _no_session_failure(latest_tracker: LatestTracker, message: str) -> dict:
    return {
        "status": "failed",
        "graph_id": None,
        "batch_size": 0,
        "elements": [],
        "errors": [ErrorEntry(
            type="no_active_session",
            message=message,
            fix="Call set_session('<name>') first.",
        ).model_dump()],
        "warnings": [],
        "context": ContextBlock(
            active_graph=None,
            latest=latest_tracker.latest,
            recent_graphs=[],
            available_sources=[],
        ).model_dump(mode="json"),
    }


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``batch`` tool against ``mcp``."""

    @mcp.tool()
    async def batch(
        ctx: Context,
        program: str,
        mode: str,
        inputs: list[str | list[str]],
        params: dict[str, Any] | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict:
        """Run one curated program over MANY inputs — exploration in bulk.

        Same (program, mode, params) applied to each entry of ``inputs``
        (a reference per element; a list of references per element for
        multi-input programs). All results land in one graph directory
        as nodes ``n1_batch_0`` … ``n1_batch_{N-1}``.

        Every element is validated *before anything runs* — one invalid
        element short-circuits the whole batch with per-element error
        reports and nothing on disk. Runtime failures don't cascade:
        elements are independent, so survivors stay (``partial_success``).

        Context semantics: the batch is ONE conversational event —
        ``latest`` still points at your last single-output action, and
        the batch's results are addressed as ``latest_batch[0]``,
        ``latest_batch[1]``, … (or ``<graph_id>:n1_batch_i``) in
        ``process()`` / ``visualize()`` / ``analyze()`` calls.

        ``params`` accepts the same polymorphic values as ``process()``
        (constants, breakpoint tuple lists, ``.brk`` paths); relative
        breakpoint envelopes are compiled per-element against each
        input's own duration. ``timeout_seconds`` applies per element.
        """
        return await batch_impl(
            ctx,
            program,
            mode,
            inputs,
            params,
            timeout_seconds,
            sessions=sessions,
            knowledge_index=knowledge_index,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )
