"""The ``graph()`` MCP tool — declarative multi-node DAGs.

Task 11a shipped ``dry_run=True``: structural validation (node specs,
reference resolution, cycle detection), per-node validation through the
same :func:`~cdp_mcp.tools.node_validation.validate_node` chain that
drives ``process()``, and **per-node duration predictions** chained
through the DAG — one node's predicted output duration feeds the next
node's pre-flight, so the report says *which* node would exceed the cap.

Task 11b ships full execution: the dry-run pass runs first as execution
phase 1 (nothing spawns until the whole DAG validates clean), then nodes
execute in topological order into **one shared graph directory** through
the same :func:`~cdp_mcp.tools.node_execution.execute_validated_node`
path ``process()`` uses. A mid-graph runtime failure yields
``partial_success``: completed nodes stay on disk and addressable via
``<graph_id>:<node_id>``, downstream nodes are skipped, and ``latest``
points at the designated output node if it succeeded (else the last
successful node).

Reference grammar inside a graph (design doc, Graph Execution Semantics):

- **bare names** refer to this graph's own nodes or to keys of the
  ``inputs`` dict — never to files. External files must be declared in
  ``inputs`` (that's what it's for).
- ``<graph_id>:<node_id>`` — cross-graph references, always explicit.
- ``latest`` / ``prev_N`` aliases resolve through the conversational
  tracker, same as ``process()``.
"""

from __future__ import annotations

from collections import deque
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

_ALLOWED_NODE_KEYS = frozenset(
    {"id", "op", "in", "params", "output_name", "submode"}
)
_RESERVED_IDS = frozenset({"latest", "prev_1", "prev_2", "prev_3", "prev_4"})


async def graph_impl(
    ctx: Context,
    inputs: dict[str, str] | None,
    nodes: list[dict[str, Any]],
    output: str | None = None,
    dry_run: bool = False,
    timeout_seconds: float = 120.0,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> dict:
    """Implementation of ``graph()``. See :func:`register` for the
    MCP-visible docstring."""
    # 1. Session + CDP preconditions (mirrors process()).
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _no_session_failure(latest_tracker, str(e))
    cdp = cdp_config_provider()
    if cdp is None:
        return _failure(
            session, latest_tracker,
            [ErrorEntry(
                type="cdp_not_configured",
                message="CDP is not configured on this server.",
                fix=(
                    "Set the CDP_PATH environment variable to the "
                    "directory containing CDP binaries and restart the "
                    "server."
                ),
            )],
        )

    # 3. Structural validation of inputs/nodes/output.
    inputs_dict: dict[str, str] = inputs or {}
    graph_errors: list[ErrorEntry] = []
    _check_inputs_shape(inputs_dict, graph_errors)
    node_specs = _check_nodes_shape(nodes, inputs_dict, graph_errors)
    node_ids = [spec["id"] for spec in node_specs]
    id_set = set(node_ids)

    if output is not None and output not in id_set:
        graph_errors.append(ErrorEntry(
            type="graph_spec_error",
            message=(
                f"output {output!r} is not a node id in this graph "
                f"(nodes: {sorted(id_set)})."
            ),
            fix="Pass one of the graph's node ids as output.",
        ))

    # 4. Entry lookup + reference classification per node.
    entries: dict[str, Any] = {}
    deps: dict[str, list[str]] = {nid: [] for nid in id_set}
    refs: dict[str, list[str]] = {}
    for spec in node_specs:
        nid = spec["id"]
        program, mode = spec["_program"], spec["_mode"]
        # Lookup keyed by (program, mode, submode); a bad or ambiguous
        # submode is a validation-phase node error like any other
        # (submode_required / not_curated), caught before anything runs.
        entry, lookup_error = resolve_entry(
            knowledge_index, program, mode, spec["_submode"],
            where=f"node {nid!r}",
            not_curated_fix=(
                "Use list_programs() to see curated entries. graph() "
                "only orchestrates curated programs."
            ),
        )
        if lookup_error is not None:
            graph_errors.append(lookup_error)
            continue
        assert entry is not None  # resolve_entry contract
        # Arity-0 exclusion (Phase 5 wave 2a, documented choice): node
        # specs require a non-empty 'in' by construction, so a
        # generator node is inexpressible in graph()'s wiring grammar.
        # Refuse with the actionable route rather than letting the
        # per-node arity check emit a "pass exactly 0 inputs" paradox.
        if entry.input_arity == 0:
            graph_errors.append(ErrorEntry(
                type="arity_zero_unsupported",
                message=(
                    f"node {nid!r}: {program!r} {mode!r} is a generator "
                    "(input_arity 0); graph() nodes wire inputs and "
                    "cannot express a no-input entry."
                ),
                fix=(
                    "Run the generator first via process() with no "
                    "input argument, then reference its output in this "
                    "graph's inputs={...} dict."
                ),
            ))
            continue
        entries[nid] = entry
        in_refs = spec["_in"]
        refs[nid] = in_refs
        for ref in in_refs:
            if ref in id_set:
                if ref == nid:
                    graph_errors.append(ErrorEntry(
                        type="graph_topology_error",
                        message=f"node {nid!r} lists itself as an input.",
                        fix="A node cannot consume its own output.",
                    ))
                else:
                    deps[nid].append(ref)
            elif ref in inputs_dict:
                pass  # external file/ref — resolved at validation time
            elif ":" in ref or ref in _RESERVED_IDS:
                pass  # cross-graph ref or alias — resolve_target's job
            else:
                graph_errors.append(ErrorEntry(
                    type="graph_topology_error",
                    message=(
                        f"node {nid!r}: bare reference {ref!r} matches "
                        "neither a node id nor an inputs key."
                    ),
                    fix=(
                        "Bare names refer to this graph's nodes or to "
                        "keys of the inputs dict. Declare external files "
                        "in inputs={...}, or use '<graph_id>:<node_id>' "
                        "for cross-graph references."
                    ),
                ))

    # 5. Topological sort (Kahn; lexicographic tie-break for a stable
    # report order). Runs even with pending errors so cycle diagnostics
    # accumulate alongside spec problems — all-at-once reporting.
    topo_order, cycle_members = _topological_sort(node_ids, deps)
    if cycle_members:
        graph_errors.append(ErrorEntry(
            type="graph_topology_error",
            message=(
                f"dependency cycle among nodes: {sorted(cycle_members)}."
            ),
            fix=(
                "Break the cycle — a DAG node cannot (transitively) "
                "consume its own output."
            ),
        ))

    if graph_errors:
        return _failure(session, latest_tracker, graph_errors)

    # 6. Dry-run pass — per-node validation in topological order,
    # chaining predicted durations into downstream pre-flight. This is
    # execution phase 1 too: a full graph() run validates EVERYTHING
    # before spawning anything, so a mis-parameterized node 3 can't
    # leave nodes 1–2 half-executed on disk.
    reports, dead = await _dry_run_pass(
        ctx=ctx,
        node_specs=node_specs,
        topo_order=topo_order,
        deps=deps,
        refs=refs,
        id_set=id_set,
        inputs_dict=inputs_dict,
        entries=entries,
        session=session,
        cdp=cdp,
        latest_tracker=latest_tracker,
        cache_root=cache_root,
        timeout_seconds=timeout_seconds,
    )

    if dry_run:
        return {
            "status": "ok" if not dead else "failed",
            "dry_run": True,
            "topological_order": topo_order,
            "output": output,
            "nodes": reports,
            "errors": [],
            "warnings": [],
            "context": build_context_block(
                session, latest_tracker, active_graph=None
            ).model_dump(mode="json"),
        }

    if dead:
        return {
            "status": "failed",
            "dry_run": False,
            "topological_order": topo_order,
            "output": output,
            "nodes": reports,
            "errors": [ErrorEntry(
                type="graph_validation_failed",
                message=(
                    f"{len(dead)} node(s) failed pre-execution "
                    f"validation ({sorted(dead)}); nothing was executed."
                ),
                fix=(
                    "Fix the per-node errors reported in 'nodes' and "
                    "retry. graph() validates the whole DAG before "
                    "spawning anything."
                ),
            ).model_dump()],
            "warnings": [],
            "context": build_context_block(
                session, latest_tracker, active_graph=None
            ).model_dump(mode="json"),
        }

    # 7. Execution — one graph directory, nodes in topological order,
    # through the same execute_validated_node path process() uses.
    return await _execute_pass(
        ctx=ctx,
        inputs_dict=inputs_dict,
        nodes_raw=nodes,
        node_specs=node_specs,
        topo_order=topo_order,
        deps=deps,
        refs=refs,
        id_set=id_set,
        entries=entries,
        output=output,
        session=session,
        cdp=cdp,
        latest_tracker=latest_tracker,
        cache_root=cache_root,
        timeout_seconds=timeout_seconds,
    )


async def _dry_run_pass(
    *,
    ctx: Context,
    node_specs: list[dict],
    topo_order: list[str],
    deps: dict[str, list[str]],
    refs: dict[str, list[str]],
    id_set: set[str],
    inputs_dict: dict[str, str],
    entries: dict[str, Any],
    session,
    cdp: CDPConfig,
    latest_tracker: LatestTracker,
    cache_root: Path,
    timeout_seconds: float,
) -> tuple[list[dict], set[str]]:
    """Validate every node without side effects. Returns
    ``(reports, dead)`` where ``dead`` holds failed/skipped node ids."""
    results: dict[str, Any] = {}
    reports: list[dict] = []
    dead: set[str] = set()
    for nid in topo_order:
        spec = next(s for s in node_specs if s["id"] == nid)
        blocked_by = [d for d in deps[nid] if d in dead]
        if blocked_by:
            dead.add(nid)
            reports.append({
                "id": nid,
                "op": spec["op"],
                "status": "skipped",
                "errors": [],
                "warnings": [
                    f"skipped: upstream node(s) {sorted(blocked_by)} "
                    "failed validation."
                ],
                "planned_argv": None,
                "planned_output": None,
                "predicted_duration_s": None,
            })
            continue

        input_list: list[str | Path] = []
        overrides: list[float | None] = []
        for ref in refs[nid]:
            if ref in id_set:
                upstream = results[ref]
                input_list.append(upstream.output_path)
                overrides.append(upstream.predicted_duration_s)
            else:
                input_list.append(inputs_dict.get(ref, ref))
                overrides.append(None)

        vr = await validate_node(
            ctx=ctx,
            entry=entries[nid],
            inputs=input_list,
            params=dict(spec.get("params") or {}),
            output_name=spec.get("output_name"),
            timeout_seconds=timeout_seconds,
            session=session,
            cdp=cdp,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
            dry_run=True,
            indur_overrides=overrides,
        )
        results[nid] = vr
        ok = not vr.errors
        if not ok:
            dead.add(nid)
        reports.append({
            "id": nid,
            "op": spec["op"],
            "status": "ok" if ok else "failed",
            "errors": [e.model_dump() for e in vr.errors],
            "warnings": vr.warnings,
            "planned_argv": vr.planned_argv,
            "planned_output": vr.out_filename,
            "predicted_duration_s": vr.predicted_duration_s,
        })
    return reports, dead


async def _execute_pass(
    *,
    ctx: Context,
    inputs_dict: dict[str, str],
    nodes_raw: list[dict[str, Any]],
    node_specs: list[dict],
    topo_order: list[str],
    deps: dict[str, list[str]],
    refs: dict[str, list[str]],
    id_set: set[str],
    entries: dict[str, Any],
    output: str | None,
    session,
    cdp: CDPConfig,
    latest_tracker: LatestTracker,
    cache_root: Path,
    timeout_seconds: float,
) -> dict:
    """Execute a fully-validated DAG into one shared graph directory."""
    graph_dir = GraphDir(session, "graph")
    graph_dir.set_graph_definition({
        "inputs": inputs_dict,
        "nodes": nodes_raw,
        "output": output,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    })

    executed: dict[str, Path] = {}  # nid → real output path
    reports: list[dict] = []
    dead: set[str] = set()
    last_success: str | None = None
    for nid in topo_order:
        spec = next(s for s in node_specs if s["id"] == nid)
        blocked_by = [d for d in deps[nid] if d in dead]
        if blocked_by:
            dead.add(nid)
            reports.append(_exec_report(
                nid, spec["op"], "skipped",
                warnings=[
                    f"skipped: upstream node(s) {sorted(blocked_by)} failed."
                ],
            ))
            continue

        input_list: list[str | Path] = [
            executed[ref] if ref in id_set else inputs_dict.get(ref, ref)
            for ref in refs[nid]
        ]
        params = dict(spec.get("params") or {})
        validation = await validate_node(
            ctx=ctx,
            entry=entries[nid],
            inputs=input_list,
            params=params,
            output_name=spec.get("output_name"),
            timeout_seconds=timeout_seconds,
            session=session,
            cdp=cdp,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
            graph_dir=graph_dir,
            node_id_base=nid,
        )
        if validation.errors:
            # Shouldn't normally happen (the dry-run pass was clean) but
            # real PVOC runs can fail in ways planning can't predict.
            dead.add(nid)
            reports.append(_exec_report(
                nid, spec["op"], "failed",
                errors=[e.model_dump() for e in validation.errors],
                warnings=validation.warnings,
            ))
            continue

        outcome = await execute_validated_node(
            ctx=ctx,
            validation=validation,
            program=spec["_program"],
            mode=spec["_mode"],
            params=params,
            timeout_seconds=timeout_seconds,
            session=session,
            cdp=cdp,
        )
        errors = list(outcome.errors)
        if outcome.bookkeeping_error is not None:
            errors.append(outcome.bookkeeping_error)
        if outcome.success:
            assert validation.output_path is not None
            executed[nid] = validation.output_path
            last_success = nid
        else:
            dead.add(nid)
        reports.append(_exec_report(
            nid, spec["op"],
            "ok" if outcome.success else "failed",
            errors=[e.model_dump() for e in errors],
            warnings=validation.warnings,
            output=(
                str(validation.output_path) if outcome.success else None
            ),
            exit_code=outcome.subprocess_result.exit_code,
            duration_ms=outcome.subprocess_result.duration_ms,
        ))

    # Status + conversational state. `latest` points at the designated
    # output node when it succeeded, else the last successful node in
    # topological order (rule: `latest` only ever names a successfully
    # produced node).
    if not dead:
        status = "ok"
    elif executed:
        status = "partial_success"
    else:
        status = "failed"
    latest_node = (
        output if (output is not None and output in executed)
        else last_success
    )
    if latest_node is not None:
        latest_tracker.update(graph_dir.id, latest_node)

    output_path = (
        str(executed[output]) if (output is not None and output in executed)
        else (str(executed[last_success]) if last_success else None)
    )
    return {
        "status": status,
        "dry_run": False,
        "graph_id": graph_dir.id,
        "topological_order": topo_order,
        "output": output_path,
        "nodes": reports,
        "errors": [],
        "warnings": [],
        "context": build_context_block(
            session, latest_tracker, active_graph=graph_dir.id
        ).model_dump(mode="json"),
    }


def _exec_report(
    nid: str,
    op: str,
    status: str,
    *,
    errors: list | None = None,
    warnings: list | None = None,
    output: str | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
) -> dict:
    return {
        "id": nid,
        "op": op,
        "status": status,
        "errors": errors or [],
        "warnings": warnings or [],
        "output": output,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Structural validation helpers
# ---------------------------------------------------------------------------


def _check_inputs_shape(
    inputs_dict: dict[str, str], errors: list[ErrorEntry]
) -> None:
    for name, ref in inputs_dict.items():
        if not isinstance(name, str) or not name or ":" in name or "/" in name:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"inputs key {name!r} is not a valid bare name.",
                fix=(
                    "Input names are bare identifiers (no ':' or '/'), "
                    "used as references in nodes' 'in' fields."
                ),
            ))
        if name in _RESERVED_IDS:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"inputs key {name!r} shadows a reserved alias.",
                fix=f"Rename the input; reserved: {sorted(_RESERVED_IDS)}.",
            ))
        if not isinstance(ref, str) or not ref:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"inputs[{name!r}] must be a non-empty reference string.",
                fix=(
                    "Use a session input filename, an absolute in-session "
                    "path, '<graph_id>:<node_id>', or an alias."
                ),
            ))


def _check_nodes_shape(
    nodes: Any,
    inputs_dict: dict[str, str],
    errors: list[ErrorEntry],
) -> list[dict]:
    """Validate node-spec shape; return the usable specs with parsed
    ``_program`` / ``_mode`` / ``_in`` fields attached."""
    if not isinstance(nodes, list) or not nodes:
        errors.append(ErrorEntry(
            type="graph_spec_error",
            message="nodes must be a non-empty list of node specs.",
            fix=(
                'Each node spec is {"id": ..., "op": "<program> <mode>", '
                '"in": <ref or [refs]>, "params": {...}?, '
                '"output_name": ...?}.'
            ),
        ))
        return []

    specs: list[dict] = []
    seen_ids: set[str] = set()
    for i, spec in enumerate(nodes):
        where = f"nodes[{i}]"
        if not isinstance(spec, dict):
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where} is not a dict.",
                fix="Pass node specs as JSON objects.",
            ))
            continue
        unknown = set(spec) - _ALLOWED_NODE_KEYS
        if unknown:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where} has unknown key(s): {sorted(unknown)}.",
                fix=f"Allowed keys: {sorted(_ALLOWED_NODE_KEYS)}.",
            ))
            continue
        missing = {"id", "op", "in"} - set(spec)
        if missing:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where} is missing required key(s): {sorted(missing)}.",
                fix="Every node needs 'id', 'op', and 'in'.",
            ))
            continue

        nid = spec["id"]
        if (
            not isinstance(nid, str)
            or not nid
            or ":" in nid
            or "/" in nid
            or nid in _RESERVED_IDS
        ):
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where}: id {nid!r} is not a valid bare node id.",
                fix=(
                    "Node ids are non-empty bare names (no ':' or '/') "
                    f"and must not shadow {sorted(_RESERVED_IDS)}."
                ),
            ))
            continue
        if nid in seen_ids:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where}: duplicate node id {nid!r}.",
                fix="Node ids must be unique within the graph.",
            ))
            continue
        if nid in inputs_dict:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where}: node id {nid!r} collides with an inputs key.",
                fix="Node ids and input names share one namespace; rename one.",
            ))
            continue

        op = spec["op"]
        parts = op.split() if isinstance(op, str) else []
        if len(parts) != 2:
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where}: op {op!r} is not '<program> <mode>'.",
                fix='Example: "blur blur", "combine cross", "morph morph".',
            ))
            continue

        submode = spec.get("submode")
        if submode is not None and (
            not isinstance(submode, int) or isinstance(submode, bool)
        ):
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where}: submode {submode!r} is not an integer.",
                fix=(
                    "Pass submode as an integer (see "
                    "get_program_info(program, mode)), or omit it."
                ),
            ))
            continue

        raw_in = spec["in"]
        in_list = [raw_in] if isinstance(raw_in, str) else raw_in
        if (
            not isinstance(in_list, list)
            or not in_list
            or not all(isinstance(r, str) and r for r in in_list)
        ):
            errors.append(ErrorEntry(
                type="graph_spec_error",
                message=f"{where}: 'in' must be a reference or list of references.",
                fix="Use bare node/input names, aliases, or '<graph_id>:<node_id>'.",
            ))
            continue

        seen_ids.add(nid)
        enriched = dict(spec)
        enriched["_program"], enriched["_mode"] = parts
        enriched["_in"] = in_list
        enriched["_submode"] = submode
        specs.append(enriched)
    return specs


def _topological_sort(
    node_ids: list[str],
    deps: dict[str, list[str]],
) -> tuple[list[str], set[str]]:
    """Kahn's algorithm. Returns ``(order, cycle_members)`` — nodes left
    unprocessed are part of (or downstream of) a cycle."""
    indegree = {nid: 0 for nid in node_ids}
    dependents: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for nid in node_ids:
        for dep in deps.get(nid, []):
            indegree[nid] += 1
            dependents[dep].append(nid)
    ready = deque(sorted(nid for nid, deg in indegree.items() if deg == 0))
    order: list[str] = []
    while ready:
        nid = ready.popleft()
        order.append(nid)
        for dependent in sorted(dependents[nid]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    cycle_members = {nid for nid in node_ids if nid not in set(order)}
    return order, cycle_members


# ---------------------------------------------------------------------------
# Failure envelopes
# ---------------------------------------------------------------------------


def _failure(
    session,
    latest_tracker: LatestTracker,
    errors: list[ErrorEntry],
) -> dict:
    return {
        "status": "failed",
        "dry_run": True,
        "topological_order": [],
        "output": None,
        "nodes": [],
        "errors": [e.model_dump() for e in errors],
        "warnings": [],
        "context": build_context_block(
            session, latest_tracker, active_graph=None
        ).model_dump(mode="json"),
    }


def _no_session_failure(latest_tracker: LatestTracker, message: str) -> dict:
    return {
        "status": "failed",
        "dry_run": True,
        "topological_order": [],
        "output": None,
        "nodes": [],
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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    knowledge_index: KnowledgeIndex,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``graph`` tool against ``mcp``."""

    @mcp.tool()
    async def graph(
        ctx: Context,
        nodes: list[dict[str, Any]],
        inputs: dict[str, str] | None = None,
        output: str | None = None,
        dry_run: bool = False,
        timeout_seconds: float = 120.0,
    ) -> dict:
        """Execute (or dry-run) a declarative multi-node DAG.

        The whole DAG is validated *before anything runs* — reference
        resolution, parameter validation, cycle detection, auto-PVOC
        planning, and per-node duration predictions chained through the
        graph. Only a fully-clean validation proceeds to execution, in
        topological order, into one shared graph directory; every node
        (including auto-inserted PVOC conversions) is addressable
        afterwards as ``<graph_id>:<node_id>``.

        With ``dry_run=True``, validation is the whole job: you get
        per-node reports with ``planned_argv`` and
        ``predicted_duration_s`` and nothing touches disk — use this to
        check an ambitious chain (or see which node would blow the
        duration cap) before committing.

        If a node fails at runtime, the result is ``partial_success``:
        upstream results stay on disk and addressable, downstream nodes
        report ``skipped``, and ``latest`` points at the last
        successfully produced node. ``timeout_seconds`` applies per
        node.

        ``inputs`` names external sources: ``{"src": "frog.wav"}`` — a
        session input filename, ``<graph_id>:<node_id>`` reference, or
        ``latest``/``prev_N`` alias. ``nodes`` is a list of specs:

        ``{"id": "b1", "op": "blur blur", "in": "src",
        "params": {"blurring": 40}}``

        - ``id`` — bare name, unique in this graph.
        - ``op`` — ``"<program> <mode>"`` of a curated entry.
        - ``in`` — one reference or a list (multi-input ops). Bare names
          refer to this graph's nodes or ``inputs`` keys; cross-graph
          references are always explicit ``<graph_id>:<node_id>``.
        - ``params`` — same polymorphic parameters as ``process()``
          (constants, breakpoint tuple lists, ``.brk`` paths).
        - ``output_name`` — optional output filename, as in ``process()``.
        - ``submode`` — optional integer selecting among multiple curated
          submodes of the node's (program, mode); only needed when the
          pair is curated in more than one submode. A missing-but-needed
          or wrong submode fails validation (``submode_required`` /
          ``not_curated``) before anything runs.

        ``output`` optionally names the node whose result you intend as
        the graph's product (checked to exist; informational in dry-run).

        Returns per-node reports: ``status`` (ok / failed / skipped),
        ``errors`` with fixes, ``planned_argv``, ``planned_output``, and
        ``predicted_duration_s``. Nodes downstream of a failed node are
        reported as skipped rather than mis-validated.
        """
        return await graph_impl(
            ctx,
            inputs,
            nodes,
            output,
            dry_run,
            timeout_seconds,
            sessions=sessions,
            knowledge_index=knowledge_index,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )
