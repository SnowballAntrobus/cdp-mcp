"""Graph templates: ``save_graph()`` / ``load_graph()`` / ``list_graphs()``.

A *template* is a reusable ``graph()`` definition — the ``{inputs,
nodes, output}`` dict that ``graph()`` accepts — saved under
``<session>/templates/<name>.json`` (the directory exists from session
init). Templates capture the SHAPE of a chain, not its results:
``load_graph()`` returns the definition for the caller to (optionally
tweak and) pass back to ``graph()``; it never executes anything itself.

Only ``graph()``-created graph directories can be saved: their
``graph.json`` carries a ``nodes`` list. ``process()`` / ``batch()``
write single-op ``graph.json`` shapes without ``nodes`` — there is no
chain to template there, so ``save_graph`` refuses them with
``template_source_missing`` rather than inventing a wrapper node.

Override merging in ``load_graph`` is deep dict-into-dict, keyed by node
id: ``overrides={"nodes": {"b1": {"params": {"blurring": 80}}}}``
replaces only ``b1``'s ``blurring`` key, leaving its other params, its
``in`` list, and every other node untouched. ``inputs`` merges per key;
``output`` replaces.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..schema import ErrorEntry
from ..session import Session, SessionManager, SessionNotActiveError
from ..utils import atomic_write_text
from .cleanup import graph_tags
from .workspace import _node_sort_key

_LOAD_GRAPH_HINT = (
    "Pass definition['inputs'], definition['nodes'], and "
    "definition['output'] to graph() to execute — dry_run=True first to "
    "validate against the current session's files."
)

_ALLOWED_OVERRIDE_KEYS = frozenset({"inputs", "nodes", "output"})


class TemplateNameError(ValueError):
    """Raised when a template name fails validation."""


def _normalize_template_name(name: str) -> str:
    """Validate ``name`` (write_data_file's bare-basename rules) and
    return the stem — a trailing ``.json`` is accepted and stripped so
    ``save_graph("fog.json")`` and ``save_graph("fog")`` are the same
    template rather than a ``fog.json.json`` surprise."""
    if (
        not isinstance(name, str)
        or "/" in name
        or "\\" in name
        or name in ("", ".", "..")
        or name.startswith(".")
    ):
        raise TemplateNameError(
            f"Invalid template name {name!r}: must be a bare basename "
            "inside templates/ (no path separators, no '..', no leading "
            "dot)."
        )
    stem = name[: -len(".json")] if name.endswith(".json") else name
    if not stem or stem.startswith("."):
        raise TemplateNameError(
            f"Invalid template name {name!r}: nothing left after "
            "stripping the '.json' extension."
        )
    return stem


def _read_graph_definition(graph_root: Path) -> dict | None:
    """Parse ``graph.json`` and return it only if it's a graph() -shaped
    definition (a dict with a ``nodes`` list). ``None`` for missing /
    unreadable files and for process()/batch() shapes."""
    try:
        doc = json.loads((graph_root / "graph.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), list):
        return None
    return doc


def _deep_merge(base: dict, override: dict) -> dict:
    """Dict-into-dict merge: nested dicts recurse, everything else
    (scalars, lists — e.g. a node's ``in`` list) is replaced whole."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# save_graph
# ---------------------------------------------------------------------------


def _save_graph(session: Session, name: str, graph_id: str | None) -> dict:
    try:
        stem = _normalize_template_name(name)
    except TemplateNameError as e:
        return _failed([ErrorEntry(
            type="invalid_template_name",
            message=str(e),
            fix="Pass a plain name like 'fog_texture' (stored as <name>.json).",
        )])

    if graph_id is not None:
        graph_root = session.graphs_dir / graph_id
        if not graph_root.is_dir():
            return _failed([ErrorEntry(
                type="graph_not_found",
                message=f"No graph directory {graph_id!r} in this session.",
                fix=(
                    "Call list_graphs() or describe_workspace() to see "
                    "the session's graph ids."
                ),
            )])
        doc = _read_graph_definition(graph_root)
        if doc is None:
            return _failed([ErrorEntry(
                type="template_source_missing",
                message=(
                    f"Graph {graph_id!r} has no graph()-shaped graph.json "
                    "(a definition with a 'nodes' list). process()/batch() "
                    "graphs record a single op, not a reusable chain."
                ),
                fix=(
                    "Save a graph()-created graph, or rebuild the chain "
                    "via graph() first."
                ),
            )])
        source_id = graph_id
    else:
        # Most recent graph()-created dir. Graph ids are minted with a
        # UTC timestamp prefix (graph._make_graph_id), so reverse name
        # sort IS reverse chronological — stabler than mtime, which
        # later writes can touch.
        source_id, doc = None, None
        if session.graphs_dir.exists():
            for p in sorted(session.graphs_dir.iterdir(), reverse=True):
                if not p.is_dir():
                    continue
                doc = _read_graph_definition(p)
                if doc is not None:
                    source_id = p.name
                    break
        if source_id is None or doc is None:
            return _failed([ErrorEntry(
                type="template_source_missing",
                message=(
                    "No graph()-created graph (graph.json with a 'nodes' "
                    "list) exists in this session to save."
                ),
                fix=(
                    "Run graph() first, or pass graph_id= explicitly if "
                    "you believe one exists."
                ),
            )])

    definition = {
        "inputs": doc.get("inputs") or {},
        "nodes": doc["nodes"],
        "output": doc.get("output"),
    }
    target = session.templates_dir / f"{stem}.json"
    overwritten = target.exists()
    try:
        session.templates_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            target, json.dumps(definition, indent=2, sort_keys=True) + "\n"
        )
    except OSError as e:
        return _failed([ErrorEntry(
            type="template_write_failed",
            message=f"could not write {target}: {e}",
            fix="Check disk space and permissions on the session directory.",
        )])
    return {
        "status": "ok",
        "name": stem,
        "path": str(target),
        "source_graph_id": source_id,
        "node_count": len(definition["nodes"]),
        "overwritten": overwritten,
    }


# ---------------------------------------------------------------------------
# load_graph
# ---------------------------------------------------------------------------


def _load_graph(session: Session, name: str, overrides: dict | None) -> dict:
    try:
        stem = _normalize_template_name(name)
    except TemplateNameError as e:
        return _failed([ErrorEntry(
            type="invalid_template_name",
            message=str(e),
            fix="Pass the name save_graph() reported (bare, no path).",
        )])

    path = session.templates_dir / f"{stem}.json"
    if not path.is_file():
        available = sorted(p.stem for p in session.templates_dir.glob("*.json"))
        return _failed([ErrorEntry(
            type="template_not_found",
            message=f"No template {stem!r} in this session.",
            fix=(
                f"Available templates: {available}. "
                "Call list_graphs() for details, or save_graph(name) first."
            ),
        )])
    try:
        definition = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return _failed([ErrorEntry(
            type="template_unreadable",
            message=f"could not parse template {stem!r}: {e}",
            fix="Re-save it with save_graph(), or fix the JSON by hand.",
        )])
    if not isinstance(definition, dict) or not isinstance(
        definition.get("nodes"), list
    ):
        return _failed([ErrorEntry(
            type="template_unreadable",
            message=(
                f"template {stem!r} is not a graph definition "
                "(expected a dict with a 'nodes' list)."
            ),
            fix="Re-save it with save_graph().",
        )])

    if overrides is not None:
        merged, errors = _apply_overrides(definition, overrides)
        if errors:
            return _failed(errors)
        definition = merged

    return {
        "status": "ok",
        "name": stem,
        "definition": definition,
        "hint": _LOAD_GRAPH_HINT,
    }


def _apply_overrides(
    definition: dict, overrides: object
) -> tuple[dict, list[ErrorEntry]]:
    """Merge ``overrides`` into a copy of ``definition``.

    All-at-once error reporting: every unknown key / unknown node id is
    collected before returning, so the caller fixes one response, not a
    whack-a-mole series.
    """
    errors: list[ErrorEntry] = []
    if not isinstance(overrides, dict):
        return definition, [ErrorEntry(
            type="invalid_overrides",
            message=f"overrides must be a dict; got {overrides!r}.",
            fix=(
                'Shape: {"nodes": {"<node_id>": {"params": {...}}}, '
                '"inputs": {...}, "output": "<node_id>"}.'
            ),
        )]
    unknown = set(overrides) - _ALLOWED_OVERRIDE_KEYS
    if unknown:
        errors.append(ErrorEntry(
            type="invalid_overrides",
            message=f"overrides has unknown key(s): {sorted(unknown)}.",
            fix=f"Allowed keys: {sorted(_ALLOWED_OVERRIDE_KEYS)}.",
        ))

    merged = dict(definition)

    if "inputs" in overrides:
        value = overrides["inputs"]
        if not isinstance(value, dict):
            errors.append(ErrorEntry(
                type="invalid_overrides",
                message=f"overrides['inputs'] must be a dict; got {value!r}.",
                fix='Example: {"inputs": {"src": "other.wav"}}.',
            ))
        else:
            base = merged.get("inputs")
            merged["inputs"] = _deep_merge(
                base if isinstance(base, dict) else {}, value
            )

    if "nodes" in overrides:
        value = overrides["nodes"]
        if not isinstance(value, dict):
            errors.append(ErrorEntry(
                type="invalid_overrides",
                message=(
                    "overrides['nodes'] must be a dict keyed by node id; "
                    f"got {value!r}."
                ),
                fix='Example: {"nodes": {"b1": {"params": {"blurring": 80}}}}.',
            ))
        else:
            nodes = [dict(n) if isinstance(n, dict) else n for n in merged["nodes"]]
            by_id = {
                n["id"]: i
                for i, n in enumerate(nodes)
                if isinstance(n, dict) and isinstance(n.get("id"), str)
            }
            for node_id, node_override in value.items():
                if node_id not in by_id:
                    errors.append(ErrorEntry(
                        type="unknown_override_node",
                        message=(
                            f"overrides['nodes'] names {node_id!r}, which is "
                            f"not a node id in this template "
                            f"(nodes: {sorted(by_id)})."
                        ),
                        fix="Override existing node ids only.",
                    ))
                    continue
                if not isinstance(node_override, dict):
                    errors.append(ErrorEntry(
                        type="invalid_overrides",
                        message=(
                            f"overrides['nodes'][{node_id!r}] must be a "
                            f"dict; got {node_override!r}."
                        ),
                        fix='Example: {"params": {"blurring": 80}}.',
                    ))
                    continue
                idx = by_id[node_id]
                nodes[idx] = _deep_merge(nodes[idx], node_override)
            merged["nodes"] = nodes

    if "output" in overrides:
        merged["output"] = overrides["output"]

    return merged, errors


# ---------------------------------------------------------------------------
# list_graphs
# ---------------------------------------------------------------------------


def _list_graphs(session: Session, tag: str | None, include_templates: bool) -> dict:
    warnings: list[str] = []

    templates: list[dict] = []
    if include_templates:
        for p in sorted(session.templates_dir.glob("*.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                nodes = doc.get("nodes") if isinstance(doc, dict) else None
                if not isinstance(nodes, list):
                    raise ValueError("no 'nodes' list")
            except (OSError, json.JSONDecodeError, ValueError) as e:
                warnings.append(f"skipping unreadable template {p.name!r}: {e}")
                continue
            templates.append({
                "name": p.stem,
                "node_count": len(nodes),
                "ops": [
                    n.get("op") for n in nodes if isinstance(n, dict)
                ],
            })

    tags_by_graph = graph_tags(session)
    graphs: list[dict] = []
    if session.graphs_dir.exists():
        for graph_root in sorted(session.graphs_dir.iterdir()):
            if not graph_root.is_dir():
                continue
            graph_tag_set = tags_by_graph.get(graph_root.name, set())
            if tag is not None and tag not in graph_tag_set:
                continue
            graphs.append({
                "id": graph_root.name,
                "primary_output": _primary_output(graph_root),
                "tags": sorted(graph_tag_set),
            })

    return {
        "status": "ok",
        "templates": templates,
        "graphs": graphs,
        "warnings": warnings,
    }


def _primary_output(graph_root: Path) -> str | None:
    """Highest-numbered node's filename — the same primary-output rule
    as workspace._history (main op outrank auto-PVOC nodes)."""
    try:
        index = json.loads(
            (graph_root / "node_index.json").read_text(encoding="utf-8")
        )
        if isinstance(index, dict) and index:
            return index[max(index, key=_node_sort_key)]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Failure envelope + registration
# ---------------------------------------------------------------------------


def _failed(errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "errors": [e.model_dump(mode="json") for e in errors],
    }


def _no_active_session(e: Exception) -> dict:
    return _failed([ErrorEntry(
        type="no_active_session",
        message=str(e),
        fix="Call set_session('<name>') first.",
    )])


def register(mcp: FastMCP, *, sessions: SessionManager) -> None:
    """Register the template tools against ``mcp``."""

    @mcp.tool()
    async def save_graph(
        ctx: Context, name: str, graph_id: str | None = None
    ) -> dict:
        """Save a graph()'s definition as a reusable named template.

        Copies the ``{inputs, nodes, output}`` definition from a
        graph()-created graph directory into
        ``<session>/templates/<name>.json``. Templates capture the shape
        of a chain, not its results — load one back with ``load_graph``
        and hand the definition to ``graph()`` against new material.

        Args:
            name: Bare template name (no path separators, no leading
                dot); stored as ``<name>.json``. Overwriting an existing
                template is allowed and flagged.
            graph_id: The graph directory to save. Default: the most
                recent graph()-created graph in this session. Graphs made
                by ``process()``/``batch()`` record a single op rather
                than a chain and are refused
                (``template_source_missing``).

        Returns ``{status, name, path, source_graph_id, node_count,
        overwritten}`` or a structured failure.
        """
        try:
            session = sessions.require_active()
        except SessionNotActiveError as e:
            return _no_active_session(e)
        return await asyncio.to_thread(_save_graph, session, name, graph_id)

    @mcp.tool()
    async def load_graph(
        ctx: Context, name: str, overrides: dict[str, Any] | None = None
    ) -> dict:
        """Load a saved template, optionally tweaked — does NOT execute.

        Returns the stored ``{inputs, nodes, output}`` definition for
        YOU to pass to ``graph()`` (dry_run first to validate against
        the current session). ``overrides`` deep-merges per node id:

        ``{"nodes": {"b1": {"params": {"blurring": 80}}},
        "inputs": {"src": "other.wav"}, "output": "b2"}``

        replaces only ``b1``'s ``blurring`` param (its other params and
        every other node stay as saved), remaps the ``src`` input, and
        redesignates the output node. Dicts merge key-by-key; scalars
        and lists (e.g. a node's ``in``) replace whole. Unknown override
        keys or node ids are structured errors, reported all at once.

        Returns ``{status, name, definition, hint}`` or a structured
        failure (``template_not_found`` lists what IS available).
        """
        try:
            session = sessions.require_active()
        except SessionNotActiveError as e:
            return _no_active_session(e)
        return await asyncio.to_thread(_load_graph, session, name, overrides)

    @mcp.tool()
    async def list_graphs(
        ctx: Context, tag: str | None = None, include_templates: bool = True
    ) -> dict:
        """List saved templates and this session's graph directories.

        Templates report ``{name, node_count, ops}`` (the op strings of
        their nodes). Graphs report ``{id, primary_output, tags}`` —
        the primary output is the highest-numbered node's filename (the
        main op; auto-PVOC nodes get lower numbers), addressable as
        ``<graph_id>:<node_id>``; tags come from the session's
        ``tags.json``.

        Args:
            tag: When set, only graphs any of whose files carry this tag
                are listed (templates are unaffected by the filter).
            include_templates: Pass ``False`` to list graph directories
                only.

        Returns ``{status, templates, graphs, warnings}``.
        """
        try:
            session = sessions.require_active()
        except SessionNotActiveError as e:
            return _no_active_session(e)
        return await asyncio.to_thread(
            _list_graphs, session, tag, include_templates
        )
