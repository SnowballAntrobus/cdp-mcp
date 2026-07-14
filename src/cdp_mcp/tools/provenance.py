"""The ``why()`` MCP tool — provenance chain for any output.

Resolves the target through the shared reference grammar
(:func:`~cdp_mcp.graph.resolve_target`), then walks *backwards* through
the per-graph ``lineage.json`` records that
:meth:`~cdp_mcp.graph.GraphDir.add_node` writes (shape:
``{"nodes": {"<node_id>": NodeLineage-dict}}``). Each hop is one of:

- an upstream node in the **same graph** (``InputRecord.source_node`` set —
  most commonly an auto-inserted PVOC node);
- a node in **another graph** (the input path points inside a different
  ``<session>/graphs/<id>/`` directory — located via that graph's
  ``node_index.json``);
- a **terminal source** (session input, or any file the walk can't map to
  a graph node) — emitted as a ``kind="source"`` chain entry.

The walk is depth-capped at :data:`_MAX_DEPTH` (with a truncation
warning) and cycle-guarded on ``(graph_id, node_id)`` so tampered or
corrupt lineage files can never hang the tool. Returns a plain dict —
this is a read-only introspection tool, so it doesn't use the
ResultEnvelope shape — but failures still follow the house structured-
error convention: ``{"status": "failed", "errors": [ErrorEntry...]}``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from pydantic import ValidationError

from ..graph import LatestTracker, ReferenceResolutionError, resolve_target
from ..schema import ErrorEntry, InputRecord, NodeLineage
from ..session import Session, SessionManager, SessionNotActiveError
from ..utils import sha256_file

# Maximum number of node entries the walk will emit before stopping with
# a truncation warning. Real chains are a handful of hops; the cap is
# defensive against pathological or hand-edited lineage files.
_MAX_DEPTH = 25

_TRUNCATION_WARNING = (
    f"provenance chain truncated at depth {_MAX_DEPTH} — "
    "the walk stopped before reaching every source."
)

# Hashes in chain entries are abbreviated to this many hex chars: enough
# to disambiguate, short enough to keep the response readable.
_SHA_PREFIX_LEN = 12


async def why_impl(
    ctx: Context,
    target: str,
    *,
    sessions: SessionManager,
    latest_tracker: LatestTracker,
) -> dict:
    """Implementation of ``why()``.

    Exposed at module scope so callers can invoke without going through
    the MCP protocol layer. The ``@mcp.tool()`` wrapper inside
    :func:`register` is a thin closure that rebinds the deps from
    server-startup state and delegates here.
    """
    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _failed(
            target,
            None,
            [
                ErrorEntry(
                    type="no_active_session",
                    message=str(e),
                    fix="Call set_session('<name>') first.",
                )
            ],
        )

    # 2. Resolve target through the shared reference grammar.
    try:
        resolved = resolve_target(target, session, latest_tracker)
    except ReferenceResolutionError as e:
        return _failed(
            target,
            None,
            [
                ErrorEntry(
                    type="reference_resolution",
                    message=str(e),
                    fix=(
                        "Check the reference: 'latest', "
                        "'<graph_id>:<node_id>', an absolute path, "
                        "or a filename inside the session's "
                        "inputs/ directory."
                    ),
                )
            ],
        )

    # 3. Walk the lineage on disk — JSON reads plus (for a direct source
    # target) one sha256 are sync disk work that must not starve MCP
    # heartbeats, so the whole build runs off the event loop.
    return await asyncio.to_thread(_build_result, session, target, resolved)


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    latest_tracker: LatestTracker,
) -> None:
    """Register the ``why`` tool against ``mcp``.

    Thin wrapper around :func:`why_impl`.
    """

    @mcp.tool()
    async def why(ctx: Context, target: str) -> dict:
        """Full provenance for any output — which program, which params,
        which inputs, all the way back to source audio.

        ``target`` accepts a session input filename, a
        ``<graph_id>:<node_id>`` reference, or the ``latest`` /
        ``prev_N`` / ``latest_batch[i]`` aliases — the same grammar as
        every other tool.

        Returns ``{status, target, resolved_path, chain, warnings,
        errors}``. ``chain`` is ordered from the resolved target down to
        its sources (leaf-last):

        - ``kind="node"`` entries carry ``graph_id``, ``node_id``,
          ``program`` (a short argv[0..1] summary like ``"blur blur"``),
          the exact ``argv``, the ``params`` snapshot, ``output_sha256``
          (12-char prefix), ``cache_hit``, ``started_at``, and
          ``duration_ms``.
        - ``kind="source"`` entries are terminal files (session inputs,
          or anything the walk can't map to a graph node) with ``path``
          and a 12-char ``sha256`` prefix captured at execution time.

        The walk follows same-graph upstream nodes (auto-PVOC included)
        and crosses graph boundaries when an input came from another
        graph's node. Depth is capped at 25 with a truncation warning;
        cycles stop the walk with a warning instead of hanging.
        """
        return await why_impl(
            ctx, target, sessions=sessions, latest_tracker=latest_tracker
        )


# ---------------------------------------------------------------------------
# Chain construction (sync — runs inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _build_result(session: Session, target: str, resolved: Path) -> dict:
    warnings: list[str] = []
    chain: list[dict] = []
    # Per-call memo of graph_id -> lineage "nodes" dict (or None when the
    # file is missing/unreadable) so a diamond-shaped chain reads each
    # lineage.json once.
    lineage_cache: dict[str, dict | None] = {}

    ref = _graph_ref_for_path(session, resolved)
    if ref is None:
        # Session input (or any non-graph file inside the session tree):
        # a terminal source node — hash the actual bytes on disk.
        chain.append(_source_entry(str(resolved), _file_sha_prefix(resolved)))
        return _ok(target, resolved, chain, warnings)

    graph_id, node_id = ref
    if node_id is None:
        warnings.append(
            f"{resolved.name} lives in graph {graph_id!r} but is not in "
            "its node_index.json — treating it as a source."
        )
        chain.append(_source_entry(str(resolved), _file_sha_prefix(resolved)))
        return _ok(target, resolved, chain, warnings)

    lineage, problem = _lineage_entry(session, graph_id, node_id, lineage_cache)
    if lineage is None:
        # The *target's own* lineage is unreadable — that's a hard
        # failure, not a degraded chain.
        return _failed(
            target,
            resolved,
            [
                ErrorEntry(
                    type="lineage_missing",
                    message=problem or "lineage record unavailable",
                    fix=(
                        "The graph's lineage.json is missing, unreadable, "
                        "or has no entry for this node — provenance for "
                        "it cannot be reconstructed."
                    ),
                )
            ],
        )

    visited: set[tuple[str, str]] = set()
    _emit_node(
        session,
        graph_id,
        node_id,
        lineage,
        chain=chain,
        warnings=warnings,
        visited=visited,
        lineage_cache=lineage_cache,
        depth=1,
    )
    return _ok(target, resolved, chain, warnings)


def _emit_node(
    session: Session,
    graph_id: str,
    node_id: str,
    lineage: NodeLineage,
    *,
    chain: list[dict],
    warnings: list[str],
    visited: set[tuple[str, str]],
    lineage_cache: dict[str, dict | None],
    depth: int,
) -> None:
    """Append this node's chain entry, then recurse into its inputs."""
    visited.add((graph_id, node_id))
    chain.append(_node_entry(graph_id, node_id, lineage))

    for rec in lineage.inputs:
        upstream = _upstream_ref(session, graph_id, rec)
        if upstream is None:
            # Session input, absent file, or otherwise unmappable —
            # terminal source using the sha recorded at execution time.
            chain.append(_source_entry(rec.path, _sha_prefix(rec.sha256)))
            continue

        up_graph, up_node = upstream
        if (up_graph, up_node) in visited:
            warnings.append(
                f"cycle detected: {up_graph}:{up_node} already appears "
                "upstream — stopping the walk there."
            )
            continue
        if depth + 1 > _MAX_DEPTH:
            if _TRUNCATION_WARNING not in warnings:
                warnings.append(_TRUNCATION_WARNING)
            continue

        up_lineage, problem = _lineage_entry(
            session, up_graph, up_node, lineage_cache
        )
        if up_lineage is None:
            # Mid-chain gaps degrade gracefully: warn and fall back to a
            # terminal source built from the input record we do have.
            warnings.append(f"{problem} — treating the input as a source.")
            chain.append(_source_entry(rec.path, _sha_prefix(rec.sha256)))
            continue

        _emit_node(
            session,
            up_graph,
            up_node,
            up_lineage,
            chain=chain,
            warnings=warnings,
            visited=visited,
            lineage_cache=lineage_cache,
            depth=depth + 1,
        )


def _upstream_ref(
    session: Session,
    graph_id: str,
    rec: InputRecord,
) -> tuple[str, str] | None:
    """Map one input record to the ``(graph_id, node_id)`` that made it.

    ``source_node`` non-null → upstream node in the *same* graph. Else,
    the path may point inside another graph's directory (cross-graph
    reference) — located via that graph's ``node_index.json``. ``None``
    means the input is a terminal source.
    """
    if rec.source_node is not None:
        return graph_id, rec.source_node
    ref = _graph_ref_for_path(session, Path(rec.path))
    if ref is None or ref[1] is None:
        return None
    return ref[0], ref[1]


# ---------------------------------------------------------------------------
# On-disk lookups
# ---------------------------------------------------------------------------


def _graph_ref_for_path(
    session: Session,
    path: Path,
) -> tuple[str, str | None] | None:
    """Locate ``path`` inside ``<session>/graphs/<id>/``.

    Returns ``None`` when the path isn't inside any graph directory,
    ``(graph_id, node_id)`` when it maps to an indexed node, and
    ``(graph_id, None)`` when it's inside a graph directory but not in
    that graph's ``node_index.json``.
    """
    if not path.is_absolute():
        return None
    graphs_root = session.graphs_dir.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(graphs_root):
        return None
    rel = resolved.relative_to(graphs_root)
    if len(rel.parts) < 2:
        return None
    graph_id = rel.parts[0]
    filename = str(Path(*rel.parts[1:]))
    return graph_id, _node_id_for_filename(session, graph_id, filename)


def _node_id_for_filename(
    session: Session,
    graph_id: str,
    filename: str,
) -> str | None:
    """Reverse-lookup ``filename`` in a graph's ``node_index.json``."""
    index_path = session.graphs_dir / graph_id / "node_index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(index, dict):
        return None
    for node_id, fname in index.items():
        if fname == filename:
            return node_id
    return None


def _lineage_entry(
    session: Session,
    graph_id: str,
    node_id: str,
    lineage_cache: dict[str, dict | None],
) -> tuple[NodeLineage | None, str | None]:
    """Load one node's :class:`NodeLineage` from its graph's lineage.json.

    Returns ``(lineage, None)`` on success or ``(None, problem)`` with a
    human-readable message when the file is missing/unreadable, the node
    has no entry (crash between the index and lineage writes), or the
    entry doesn't parse.
    """
    nodes = _lineage_nodes(session, graph_id, lineage_cache)
    if nodes is None:
        lineage_path = session.graphs_dir / graph_id / "lineage.json"
        return None, (
            f"graph {graph_id!r} has no readable lineage.json "
            f"(expected at {lineage_path})"
        )
    raw = nodes.get(node_id)
    if raw is None:
        return None, (
            f"lineage.json for graph {graph_id!r} has no entry for "
            f"node {node_id!r}"
        )
    try:
        return NodeLineage.model_validate(raw), None
    except ValidationError as e:
        return None, (
            f"lineage entry for {graph_id}:{node_id} does not parse as "
            f"a NodeLineage record: {e}"
        )


def _lineage_nodes(
    session: Session,
    graph_id: str,
    lineage_cache: dict[str, dict | None],
) -> dict | None:
    """Read (memoized) the ``nodes`` mapping of a graph's lineage.json."""
    if graph_id in lineage_cache:
        return lineage_cache[graph_id]
    path = session.graphs_dir / graph_id / "lineage.json"
    nodes: dict | None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        raw = doc.get("nodes") if isinstance(doc, dict) else None
        nodes = raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        nodes = None
    lineage_cache[graph_id] = nodes
    return nodes


# ---------------------------------------------------------------------------
# Chain-entry / response builders
# ---------------------------------------------------------------------------


def _node_entry(graph_id: str, node_id: str, lineage: NodeLineage) -> dict:
    return {
        "kind": "node",
        "graph_id": graph_id,
        "node_id": node_id,
        "program": _program_summary(lineage.argv),
        "argv": lineage.argv,
        "params": lineage.params,
        "output_sha256": _sha_prefix(lineage.output_sha256),
        "cache_hit": lineage.cache_hit,
        "started_at": lineage.started_at.isoformat(),
        "duration_ms": lineage.duration_ms,
    }


def _source_entry(path: str, sha_prefix: str | None) -> dict:
    return {"kind": "source", "path": path, "sha256": sha_prefix}


def _program_summary(argv: list[str]) -> str:
    """Short human-readable ``"<program> <mode>"`` summary from argv[0..1].

    Skips the Apple Silicon ``arch -x86_64`` wrapper prefix when present
    (lineage records store the exact subprocess argv, wrapper included).
    """
    tokens = list(argv)
    if tokens and Path(tokens[0]).name == "arch":
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):
            tokens = tokens[1:]
    if not tokens:
        return ""
    return " ".join([Path(tokens[0]).name, *tokens[1:2]])


def _sha_prefix(sha: str | None) -> str | None:
    if not sha:
        return None
    return sha[:_SHA_PREFIX_LEN]


def _file_sha_prefix(path: Path) -> str | None:
    """Hash a terminal source file on disk. ``None`` if unreadable."""
    try:
        return _sha_prefix(sha256_file(path))
    except OSError:
        return None


def _ok(target: str, resolved: Path, chain: list[dict], warnings: list[str]) -> dict:
    return {
        "status": "ok",
        "target": target,
        "resolved_path": str(resolved),
        "chain": chain,
        "warnings": warnings,
        "errors": [],
    }


def _failed(target: str, resolved: Path | None, errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "target": target,
        "resolved_path": str(resolved) if resolved is not None else None,
        "chain": [],
        "warnings": [],
        "errors": [e.model_dump(mode="json") for e in errors],
    }
