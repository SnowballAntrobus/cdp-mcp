"""The ``graph()`` MCP tool — declarative multi-node DAGs.

Phase 2 Task 11a ships the ``dry_run=True`` half: structural validation
(node specs, reference resolution, cycle detection), per-node validation
through the same :func:`~cdp_mcp.tools.node_validation.validate_node`
chain that drives ``process()``, and **per-node duration predictions**
chained through the DAG — one node's predicted output duration feeds the
next node's pre-flight, so the report says *which* node would exceed the
cap, not just "somewhere in the graph violates a guardrail."

Full execution is the next Phase 2 task; calling with ``dry_run=False``
returns a structured ``graph_execution_not_implemented`` error rather
than raising, so the LLM gets an actionable redirect.

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
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..config import CDPConfig
from ..graph import LatestTracker, build_context_block
from ..knowledge.loader import KnowledgeIndex
from ..schema import ContextBlock, ErrorEntry
from ..session import SessionManager, SessionNotActiveError
from .node_validation import validate_node

_ALLOWED_NODE_KEYS = frozenset({"id", "op", "in", "params", "output_name"})
_RESERVED_IDS = frozenset({"latest", "prev_1", "prev_2", "prev_3", "prev_4"})


async def graph_impl(
    ctx: Context,
    inputs: dict[str, str] | None,
    nodes: list[dict[str, Any]],
    output: str | None = None,
    dry_run: bool = False,
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

    # 2. Task 11a boundary: only dry-run is implemented.
    if not dry_run:
        return _failure(
            session, latest_tracker,
            [ErrorEntry(
                type="graph_execution_not_implemented",
                message=(
                    "graph() full execution is not implemented yet — "
                    "Task 11a ships validation and duration prediction "
                    "only."
                ),
                fix=(
                    "Call graph(..., dry_run=True) to validate the DAG "
                    "and see per-node duration predictions, then run the "
                    "nodes as chained process() calls (reference the "
                    "previous output via 'latest')."
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
        entry = knowledge_index.get(program, mode)
        if entry is None or not entry.curated:
            graph_errors.append(ErrorEntry(
                type="not_curated",
                message=(
                    f"node {nid!r}: no curated knowledge entry for "
                    f"{program!r} {mode!r}."
                ),
                fix=(
                    "Use list_programs() to see curated entries. graph() "
                    "only orchestrates curated programs."
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

    # 6. Per-node dry-run validation in topological order, chaining
    # predicted durations into downstream pre-flight.
    results: dict[str, Any] = {}
    reports: list[dict] = []
    dead: set[str] = set()  # failed or skipped — downstream can't validate
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
            timeout_seconds=120.0,
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

    status = "ok" if not dead else "failed"
    return {
        "status": status,
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
    ) -> dict:
        """Validate (and later: execute) a declarative multi-node DAG.

        **Currently dry-run only**: call with ``dry_run=True`` to check a
        whole processing chain before running anything — reference
        resolution, parameter validation, cycle detection, auto-PVOC
        planning, and **per-node duration predictions** chained through
        the DAG (so you see *which* node would exceed the duration cap).
        Full execution is coming; until then run the validated chain as
        successive ``process()`` calls using the ``"latest"`` alias.

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
            sessions=sessions,
            knowledge_index=knowledge_index,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )
