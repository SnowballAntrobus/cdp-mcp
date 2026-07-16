"""The ``sweep()`` MCP tool — ONE source, MANY parameter variants, one graph.

Phase 4. This tool deliberately reverses a design-doc non-goal. The doc's
Non-Goals list included "Parameter sweep automation as a dedicated tool
(`batch` + `process` covers it)" — but real usage (session transcripts
reviewed 2026-07-14) showed the LLM hand-looping ``process()`` calls to
explore one sound across parameter settings, paying a full result
envelope (context block included) per variant and burning tokens on
mechanical repetition. ``sweep()`` is the inverse of ``batch()``: where
batch holds params constant and varies the material, sweep holds the
material constant and varies the params. Its per-variant reports are
compact by design — token economy is the tool's reason to exist.

Contracts (mirroring ``batch()``, design doc Tool Surface § batch):

- **Validate everything first, execute nothing on any validation
  failure.** Each variant runs through ``validate_node(dry_run=True)``;
  one bad variant short-circuits the whole sweep before any subprocess
  (``sweep_validation_failed``).
- **Runtime failures don't cascade** — variants are independent, so a
  mid-sweep CDP failure yields ``partial_success`` with the survivors
  on disk.
- Node ids are ``n1_sweep_0`` … ``n1_sweep_{N-1}`` (auto-PVOC nodes
  derive ``n1_sweep_i_pvoc1``, uniform with ``batch()``/``graph()``).
- The sweep is ONE atomic context event (``latest_tracker.record_batch``);
  ``latest`` is untouched and variants resolve via ``latest_batch[i]``
  or ``<graph_id>:n1_sweep_i``.
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
from .entry_lookup import resolve_entry
from .node_execution import execute_validated_node
from .node_validation import validate_node

# Variant-count bounds. Below 2 a sweep is just process(); above 32 the
# response stops being a readable exploration report and disk pressure
# from N outputs of one source becomes real.
_MIN_VARIANTS = 2
_MAX_VARIANTS = 32


async def sweep_impl(
    ctx: Context,
    program: str,
    mode: str,
    input: str,
    param_sets: list[dict[str, Any]],
    timeout_seconds: float = 120.0,
    submode: int | None = None,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> dict:
    """Implementation of ``sweep()``."""
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

    entry, lookup_error = resolve_entry(knowledge_index, program, mode, submode)
    if lookup_error is not None:
        return _failure(session, latest_tracker, [lookup_error])
    assert entry is not None  # resolve_entry contract

    # Arity-0 exclusion (Phase 5 wave 2a, documented choice): sweep()'s
    # signature requires ONE source reference; a generator has none, so
    # every variant would fail the arity check anyway. Refuse up front
    # with the actionable route instead of N confusing per-variant
    # errors. (A future parameter-exploration story for generators
    # belongs to a signature redesign, not a special-cased input.)
    if entry.input_arity == 0:
        return _failure(session, latest_tracker, [ErrorEntry(
            type="arity_zero_unsupported",
            message=(
                f"{program!r} {mode!r} is a generator (input_arity 0); "
                "sweep() holds one input constant and cannot express a "
                "no-input entry."
            ),
            fix=(
                "Run generators via process() with no input argument, "
                "once per parameter setting."
            ),
        )])

    if (
        not isinstance(param_sets, list)
        or not all(isinstance(p, dict) for p in param_sets)
        or not _MIN_VARIANTS <= len(param_sets) <= _MAX_VARIANTS
    ):
        return _failure(session, latest_tracker, [ErrorEntry(
            type="sweep_spec_error",
            message=(
                f"param_sets must be a list of {_MIN_VARIANTS}.."
                f"{_MAX_VARIANTS} params dicts (one full params dict per "
                "variant)."
            ),
            fix=(
                "Pass 2..32 dicts, each a complete params set for one "
                "variant. For a single variant use process(); for more "
                "than 32, split into multiple sweeps."
            ),
        )])

    variants: list[dict[str, Any]] = list(param_sets)
    node_ids = [f"n1_sweep_{i}" for i in range(len(variants))]

    # Phase A — validate every variant without side effects. Any failure
    # short-circuits the whole sweep: nothing has executed, nothing is
    # on disk, fix and resubmit.
    validation_reports: list[dict] = []
    any_invalid = False
    for i, variant in enumerate(variants):
        vr = await validate_node(
            ctx=ctx,
            entry=entry,
            inputs=[input],
            params=dict(variant),
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
            "params": variant,
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
            "sweep_size": len(variants),
            "variants": validation_reports,
            "errors": [ErrorEntry(
                type="sweep_validation_failed",
                message=(
                    f"variant(s) {bad} failed validation; the whole sweep "
                    "was short-circuited — nothing executed."
                ),
                fix=(
                    "Fix the per-variant errors in 'variants' and resubmit "
                    "the sweep."
                ),
            ).model_dump()],
            "warnings": [],
            "context": build_context_block(
                session, latest_tracker, active_graph=None
            ).model_dump(mode="json"),
        }

    # Phase B — execute all variants into one shared graph directory.
    graph_dir = GraphDir(session, f"sweep-{program}-{mode}")
    graph_dir.set_graph_definition({
        "program": program,
        "mode": mode,
        "input": input,
        "param_sets": param_sets,
        "sweep_size": len(variants),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    })

    reports: list[dict] = []
    succeeded = 0
    for i, variant in enumerate(variants):
        validation = await validate_node(
            ctx=ctx,
            entry=entry,
            inputs=[input],
            params=dict(variant),
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
                "params": variant,
                "node_id": node_ids[i],
                "status": "failed",
                "output": None,
                "exit_code": None,
                "duration_ms": None,
                "errors": [e.model_dump() for e in validation.errors],
                "warnings": validation.warnings,
            })
            continue
        outcome = await execute_validated_node(
            ctx=ctx,
            validation=validation,
            program=program,
            mode=mode,
            params=dict(variant),
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
            "params": variant,
            "node_id": node_ids[i],
            "status": "ok" if outcome.success else "failed",
            "output": (
                str(validation.output_path) if outcome.success else None
            ),
            "exit_code": outcome.subprocess_result.exit_code,
            "duration_ms": outcome.subprocess_result.duration_ms,
            "errors": [e.model_dump() for e in errors],
            "warnings": validation.warnings,
        })

    # One atomic context event for the whole sweep; `latest` untouched.
    latest_tracker.record_batch(graph_dir.id, node_ids)

    if succeeded == len(variants):
        status = "ok"
    elif succeeded:
        status = "partial_success"
    else:
        status = "failed"
    return {
        "status": status,
        "graph_id": graph_dir.id,
        "sweep_size": len(variants),
        "variants": reports,
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
        "sweep_size": 0,
        "variants": [],
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
        "sweep_size": 0,
        "variants": [],
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
    """Register the ``sweep`` tool against ``mcp``."""

    @mcp.tool()
    async def sweep(
        ctx: Context,
        program: str,
        mode: str,
        input: str,
        param_sets: list[dict[str, Any]],
        timeout_seconds: float = 120.0,
        submode: int | None = None,
    ) -> dict:
        """Explore ONE sound across parameter settings in a single call.

        The inverse of ``batch()``: same curated (program, mode) and the
        same ``input`` (any single reference — ``latest``, ``prev_N``,
        ``latest_batch[i]``, ``<graph_id>:<node_id>``, or a session
        input filename, exactly like ``process()``), applied once per
        entry of ``param_sets`` (2..32 dicts, each a complete params
        set for one variant). All results land in one graph directory
        as nodes ``n1_sweep_0`` … ``n1_sweep_{N-1}``. Then
        ``cluster()`` / ``compare()`` the results to hear the space.

        Every variant is validated *before anything runs* — one invalid
        variant short-circuits the whole sweep with per-variant error
        reports and nothing on disk. Runtime failures don't cascade:
        variants are independent, so survivors stay
        (``partial_success``).

        Context semantics: the sweep is ONE conversational event —
        ``latest`` still points at your last single-output action, and
        the sweep's results are addressed as ``latest_batch[0]``,
        ``latest_batch[1]``, … (or ``<graph_id>:n1_sweep_i``) in
        ``process()`` / ``visualize()`` / ``analyze()`` / ``compare()``
        calls, exactly like ``batch()``.

        Each ``param_sets`` entry accepts the same polymorphic values
        as ``process()`` params (constants, breakpoint tuple lists,
        ``.brk`` paths). ``timeout_seconds`` applies per variant.
        Per-variant reports are compact ({index, params, node_id,
        status, output, exit_code, duration_ms, errors, warnings}) —
        far cheaper than N ``process()`` envelopes.

        ``submode`` selects among multiple curated submodes of the same
        (program, mode) — only needed when the pair is curated in more
        than one submode (``submode_required`` lists the valid values).
        """
        return await sweep_impl(
            ctx,
            program,
            mode,
            input,
            param_sets,
            timeout_seconds,
            submode,
            sessions=sessions,
            knowledge_index=knowledge_index,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )
