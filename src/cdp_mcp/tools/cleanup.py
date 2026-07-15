"""Lifecycle tools: ``cleanup()`` and ``cleanup_cache()``.

Two deletion levers with deliberately different units of work:

- ``cleanup(predicate)`` — deletes **whole graph directories** under the
  active session's ``graphs/``. Never individual files: a graph dir is
  the atomic provenance unit (``graph.json`` + ``node_index.json`` +
  ``lineage.json`` + outputs), and partial deletion would leave lineage
  records pointing at ghosts. Simpler and safer.
- ``cleanup_cache(predicate?)`` — deletes **individual files** inside
  the global derivative cache tiers (``~/.cdp_mcp/cache/<tier>/``).
  Cache entries are pure functions of their inputs, so file-level
  eviction is always safe; anything evicted is recomputed on demand.

Both default to ``dry_run=True`` — deletion is opt-in per call.

**Dependency safety (design deviation, documented).** Design-doc Task 14
committed a maintained ``dependency_index.json``; it was deferred to
Phase 4 alongside this consumer, and Phase 4 builds the dependency view
*on the fly* instead: before deleting, every surviving graph's
``lineage.json`` is scanned and any candidate graph owning a file
referenced by a survivor's ``inputs[].path`` is refused. This trades a
per-cleanup scan (cheap: sessions hold tens of graphs, lineage files are
KB-sized) for zero index-maintenance burden and no staleness bugs. The
scan runs to a fixpoint so protection cascades: if survivor C depends on
candidate B and B depends on candidate A, both B and A are refused.

**Tags are keep signals.** ``tags.json`` (session root; keys are
session-relative file paths, values are tag lists) marks curated
keepers. A graph carrying any tag is refused unless the predicate
explicitly selects by one of that graph's tags — ``{"tag": "reject"}``
deletes graphs tagged ``reject``, but ``{"age_days": 30}`` skips them.

**cleanup_cache predicate honesty.** The design doc's grammar included
``cdp_version`` / ``lib_version`` predicates. They are NOT supported
here: cache filenames are opaque content hashes with the versions baked
into the key, so selecting by version would need a metadata sidecar
written at populate time. Recorded as future work; ``tier`` /
``age_days`` / ``size_gt_mb`` cover the practical eviction cases
(post-upgrade eviction ≈ ``{"tier": "pvoc"}`` after a CDP upgrade).
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from mcp.server.fastmcp import Context, FastMCP

from ..cache import _KNOWN_TIERS
from ..graph import LatestTracker
from ..schema import ErrorEntry
from ..session import Session, SessionManager, SessionNotActiveError
from ..utils import atomic_write_text

_GRAPH_PREDICATE_KEYS = frozenset(
    {"glob", "tag", "age_days", "graph_id", "and", "or", "not"}
)
_CACHE_PREDICATE_KEYS = frozenset(
    {"tier", "age_days", "size_gt_mb", "and", "or", "not"}
)

_SECONDS_PER_DAY = 86400.0


class PredicateError(ValueError):
    """Raised when a cleanup predicate fails grammar validation."""


# ---------------------------------------------------------------------------
# Predicate grammar (shared validation walker, per-domain leaf sets)
# ---------------------------------------------------------------------------


def _validate_predicate(
    pred: object, allowed: frozenset[str], where: str = "predicate"
) -> None:
    """Recursively validate a predicate dict against ``allowed`` leaf keys.

    All-at-once shape checking happens up front so evaluation can assume
    well-formed input; raises :class:`PredicateError` with a message
    naming the offending subtree.
    """
    if not isinstance(pred, dict) or len(pred) != 1:
        raise PredicateError(
            f"{where} must be a dict with exactly one key "
            f"(one of {sorted(allowed)}); got {pred!r}."
        )
    key, value = next(iter(pred.items()))
    if key not in allowed:
        raise PredicateError(
            f"{where}: unknown predicate key {key!r}; allowed: {sorted(allowed)}."
        )
    if key in ("and", "or"):
        if not isinstance(value, list) or not value:
            raise PredicateError(
                f"{where}[{key!r}] must be a non-empty list of predicates."
            )
        for i, sub in enumerate(value):
            _validate_predicate(sub, allowed, f"{where}[{key!r}][{i}]")
    elif key == "not":
        _validate_predicate(value, allowed, f"{where}['not']")
    elif key in ("glob", "tag", "graph_id"):
        if not isinstance(value, str) or not value:
            raise PredicateError(
                f"{where}[{key!r}] must be a non-empty string; got {value!r}."
            )
    elif key == "tier":
        if value not in _KNOWN_TIERS:
            raise PredicateError(
                f"{where}['tier'] must be one of {sorted(_KNOWN_TIERS)}; "
                f"got {value!r}."
            )
    else:  # age_days / size_gt_mb
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise PredicateError(
                f"{where}[{key!r}] must be a non-negative number; got {value!r}."
            )


def _explicit_tags(pred: dict) -> set[str]:
    """Every tag literal named anywhere in the predicate tree.

    Naming a tag — even under ``not`` or inside a branch that doesn't
    end up matching — is treated as explicit intent to reason about that
    tag, which waives the blanket tag-protection for graphs carrying it.
    Documented rule, chosen for predictability over cleverness.
    """
    key, value = next(iter(pred.items()))
    if key in ("and", "or"):
        out: set[str] = set()
        for sub in value:
            out |= _explicit_tags(sub)
        return out
    if key == "not":
        return _explicit_tags(value)
    if key == "tag":
        return {value}
    return set()


# ---------------------------------------------------------------------------
# tags.json helpers (shared with tools.templates)
# ---------------------------------------------------------------------------


def load_tags(session: Session) -> dict[str, list[str]]:
    """Read ``tags.json`` defensively: missing / unparseable / non-dict
    → ``{}``. Values are normalized to lists of strings (a bare string
    value is treated as a single tag); malformed entries are dropped."""
    try:
        doc = json.loads(session.tags_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in doc.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str):
            out[key] = [value]
        elif isinstance(value, list):
            tags = [t for t in value if isinstance(t, str)]
            if tags:
                out[key] = tags
    return out


def _graph_id_for_tag_key(key: str) -> str | None:
    """Owning graph id for a session-relative tag path, or ``None`` for
    non-graph files (inputs, envelopes, ...)."""
    parts = PurePosixPath(key).parts
    if len(parts) >= 2 and parts[0] == "graphs":
        return parts[1]
    return None


def graph_tags(session: Session) -> dict[str, set[str]]:
    """Map each graph id to the union of tags carried by any of its files."""
    result: dict[str, set[str]] = {}
    for key, tags in load_tags(session).items():
        gid = _graph_id_for_tag_key(key)
        if gid is None:
            continue
        result.setdefault(gid, set()).update(tags)
    return result


def _prune_tag_entries(
    session: Session, deleted_ids: set[str], warnings: list[str]
) -> None:
    """Drop tags.json entries whose paths point into deleted graph dirs.

    Operates on the raw document (unknown value shapes are preserved
    verbatim) so cleanup never launders someone else's data. Write
    failures degrade to a warning — the graphs are already gone and a
    stale tag entry is harmless (load_tags callers tolerate it)."""
    try:
        doc = json.loads(session.tags_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(doc, dict):
        return
    kept = {
        key: value
        for key, value in doc.items()
        if not (isinstance(key, str) and _graph_id_for_tag_key(key) in deleted_ids)
    }
    if len(kept) == len(doc):
        return
    try:
        atomic_write_text(
            session.tags_path, json.dumps(kept, indent=2, sort_keys=True) + "\n"
        )
    except OSError as e:
        warnings.append(f"could not rewrite tags.json after deletion: {e}")


# ---------------------------------------------------------------------------
# cleanup() — graph-directory eviction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GraphInfo:
    id: str
    root: Path
    mtime: float
    tags: frozenset[str]


def _matches_graph(pred: dict, info: _GraphInfo, now: float) -> bool:
    key, value = next(iter(pred.items()))
    if key == "and":
        return all(_matches_graph(sub, info, now) for sub in value)
    if key == "or":
        return any(_matches_graph(sub, info, now) for sub in value)
    if key == "not":
        return not _matches_graph(value, info, now)
    if key == "glob":
        return fnmatch.fnmatch(info.id, value)
    if key == "tag":
        return value in info.tags
    if key == "graph_id":
        return info.id == value
    if key == "age_days":
        return (now - info.mtime) > value * _SECONDS_PER_DAY
    raise AssertionError(f"unvalidated predicate key {key!r}")  # pragma: no cover


def _referenced_graph_ids(session: Session, graph_id: str) -> set[str]:
    """Graph ids (other than ``graph_id`` itself) whose files appear in
    this graph's ``lineage.json`` ``inputs[].path`` records.

    Unreadable / missing / malformed lineage contributes nothing — a
    survivor with no readable lineage can't testify about dependencies,
    and refusing ALL deletion on that basis would make cleanup useless
    the moment one lineage file corrupts. Self-references (auto-PVOC
    nodes feeding the main op in the same graph) are excluded: a graph
    consuming its own files doesn't pin itself.
    """
    lineage_path = session.graphs_dir / graph_id / "lineage.json"
    graphs_root = session.graphs_dir.resolve()
    refs: set[str] = set()
    try:
        doc = json.loads(lineage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return refs
    nodes = doc.get("nodes") if isinstance(doc, dict) else None
    if not isinstance(nodes, dict):
        return refs
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, list):
            continue
        for rec in inputs:
            if not isinstance(rec, dict):
                continue
            raw = rec.get("path")
            if not isinstance(raw, str) or not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                # Lineage records absolute paths; tolerate relative ones
                # (hand-edited files) by anchoring at the session root.
                path = session.root / path
            try:
                resolved = path.resolve()
            except OSError:  # pragma: no cover — resolve() rarely raises
                continue
            if not resolved.is_relative_to(graphs_root):
                continue
            rel = resolved.relative_to(graphs_root)
            if rel.parts and rel.parts[0] != graph_id:
                refs.add(rel.parts[0])
    return refs


def _dir_size(root: Path) -> int:
    """Recursive file-size sum; mirrors workspace._disk_usage."""
    total = 0
    for f in root.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                continue
    return total


def _run_cleanup(session: Session, predicate: dict, dry_run: bool) -> dict:
    """Select → protect → (maybe) delete. Sync; runs in a worker thread."""
    now = time.time()
    tags_by_graph = graph_tags(session)
    infos: list[_GraphInfo] = []
    if session.graphs_dir.exists():
        for p in sorted(session.graphs_dir.iterdir()):
            if not p.is_dir():
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = now
            infos.append(_GraphInfo(
                id=p.name,
                root=p,
                mtime=mtime,
                tags=frozenset(tags_by_graph.get(p.name, ())),
            ))
    by_id = {info.id: info for info in infos}
    all_ids = set(by_id)
    candidates = {info.id for info in infos if _matches_graph(predicate, info, now)}

    # Tag protection: tags are keep signals unless explicitly selected.
    protected: dict[str, dict] = {}
    explicit = _explicit_tags(predicate)
    for gid in sorted(candidates):
        graph_tag_set = by_id[gid].tags
        if graph_tag_set and not (graph_tag_set & explicit):
            protected[gid] = {
                "id": gid,
                "reason": "tagged",
                "tags": sorted(graph_tag_set),
            }

    # Dependency protection, run to fixpoint: protecting a graph makes it
    # a survivor, and a survivor's references protect ITS upstream
    # candidates in the next pass (C→B→A cascade).
    refs_by_graph = {gid: _referenced_graph_ids(session, gid) for gid in all_ids}
    while True:
        deletable = candidates - protected.keys()
        survivors = all_ids - deletable
        newly_protected = False
        for gid in sorted(deletable):
            dependents = sorted(s for s in survivors if gid in refs_by_graph[s])
            if dependents:
                protected[gid] = {
                    "id": gid,
                    "reason": "referenced_by_survivor",
                    "dependents": dependents,
                }
                newly_protected = True
        if not newly_protected:
            break

    to_delete = sorted(candidates - protected.keys())
    warnings: list[str] = []
    deleted: list[str] = []
    freed_bytes = 0
    if dry_run:
        deleted = to_delete
        freed_bytes = sum(_dir_size(by_id[gid].root) for gid in to_delete)
    else:
        for gid in to_delete:
            size = _dir_size(by_id[gid].root)
            try:
                shutil.rmtree(by_id[gid].root)
            except OSError as e:
                warnings.append(f"could not delete graph {gid!r}: {e}")
                continue
            deleted.append(gid)
            freed_bytes += size
        _prune_tag_entries(session, set(deleted), warnings)

    return {
        "status": "ok",
        "dry_run": dry_run,
        "deleted": deleted,
        "protected": [protected[gid] for gid in sorted(protected)],
        "freed_bytes": freed_bytes,
        "warnings": warnings,
    }


async def cleanup_impl(
    ctx: Context,
    predicate: dict,
    dry_run: bool = True,
    *,
    sessions: SessionManager,
    latest_tracker: LatestTracker,
) -> dict:
    """Implementation of ``cleanup()``. Module-scope for direct testing."""
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _failed([ErrorEntry(
            type="no_active_session",
            message=str(e),
            fix="Call set_session('<name>') first.",
        )])
    try:
        _validate_predicate(predicate, _GRAPH_PREDICATE_KEYS)
    except PredicateError as e:
        return _failed([ErrorEntry(
            type="invalid_predicate",
            message=str(e),
            fix=(
                'Predicates are single-key dicts: {"glob": "*batch*"}, '
                '{"tag": "reject"}, {"age_days": 30}, '
                '{"graph_id": "<exact>"}, composed via '
                '{"and"|"or": [...]} and {"not": {...}}.'
            ),
        )])
    # Disk walk + deletion off the event loop (house convention: sync
    # filesystem work must not stall MCP heartbeats).
    result = await asyncio.to_thread(_run_cleanup, session, predicate, dry_run)
    if not dry_run:
        # Prune conversational slots for deleted graphs WITHOUT
        # renumbering (design Rule 3): holes stay holes.
        for gid in result["deleted"]:
            latest_tracker.remove(gid)
    return result


# ---------------------------------------------------------------------------
# cleanup_cache() — file-level eviction inside the global cache tiers
# ---------------------------------------------------------------------------


def _matches_cache_file(pred: dict, tier: str, size: int, mtime: float, now: float) -> bool:
    key, value = next(iter(pred.items()))
    if key == "and":
        return all(_matches_cache_file(sub, tier, size, mtime, now) for sub in value)
    if key == "or":
        return any(_matches_cache_file(sub, tier, size, mtime, now) for sub in value)
    if key == "not":
        return not _matches_cache_file(value, tier, size, mtime, now)
    if key == "tier":
        return tier == value
    if key == "age_days":
        return (now - mtime) > value * _SECONDS_PER_DAY
    if key == "size_gt_mb":
        return size > value * 1024 * 1024
    raise AssertionError(f"unvalidated predicate key {key!r}")  # pragma: no cover


def _run_cleanup_cache(
    cache_root: Path, predicate: dict | None, dry_run: bool
) -> dict:
    """Scan the known tiers, match, (maybe) delete. Sync; worker thread."""
    now = time.time()
    per_tier: dict[str, dict] = {}
    warnings: list[str] = []
    deleted_count = 0
    freed_bytes = 0
    for tier in _KNOWN_TIERS:
        tier_dir = cache_root / tier
        file_count = 0
        byte_count = 0
        matches: list[tuple[Path, int]] = []
        if tier_dir.exists():
            for p in tier_dir.rglob("*"):
                if not p.is_file():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                file_count += 1
                byte_count += st.st_size
                if predicate is not None and _matches_cache_file(
                    predicate, tier, st.st_size, st.st_mtime, now
                ):
                    matches.append((p, st.st_size))
        matched_bytes = sum(size for _, size in matches)
        if dry_run:
            deleted_count += len(matches)
            freed_bytes += matched_bytes
        else:
            for p, size in matches:
                try:
                    p.unlink()
                except OSError as e:
                    warnings.append(f"could not delete cache file {p}: {e}")
                    continue
                deleted_count += 1
                freed_bytes += size
        per_tier[tier] = {
            # Pre-deletion snapshot (scan time), so a real run's response
            # shows what the matched files were evicted FROM.
            "files": file_count,
            "bytes": byte_count,
            "matched_files": len(matches),
            "matched_bytes": matched_bytes,
        }
    return {
        "status": "ok",
        "dry_run": dry_run,
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
        "per_tier": per_tier,
        "warnings": warnings,
    }


async def cleanup_cache_impl(
    ctx: Context,
    predicate: dict | None = None,
    dry_run: bool = True,
    *,
    cache_root: Path,
) -> dict:
    """Implementation of ``cleanup_cache()``. Module-scope for direct testing."""
    if predicate is None and not dry_run:
        return _failed([ErrorEntry(
            type="predicate_required",
            message=(
                "cleanup_cache(dry_run=False) without a predicate would "
                "evict the entire cache — refused."
            ),
            fix=(
                'Pass a predicate (e.g. {"tier": "pvoc"} or '
                '{"age_days": 90}); to really clear everything, use '
                '{"or": [{"tier": t} for every tier]} explicitly.'
            ),
        )])
    if predicate is not None:
        try:
            _validate_predicate(predicate, _CACHE_PREDICATE_KEYS)
        except PredicateError as e:
            return _failed([ErrorEntry(
                type="invalid_predicate",
                message=str(e),
                fix=(
                    'Cache predicates are single-key dicts: {"tier": '
                    f'one of {sorted(_KNOWN_TIERS)}}}, {{"age_days": N}}, '
                    '{"size_gt_mb": N}, composed via {"and"|"or": [...]} '
                    'and {"not": {...}}.'
                ),
            )])
    return await asyncio.to_thread(_run_cleanup_cache, cache_root, predicate, dry_run)


# ---------------------------------------------------------------------------
# Failure envelope + registration
# ---------------------------------------------------------------------------


def _failed(errors: list[ErrorEntry]) -> dict:
    return {
        "status": "failed",
        "errors": [e.model_dump(mode="json") for e in errors],
    }


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``cleanup`` and ``cleanup_cache`` tools against ``mcp``."""

    @mcp.tool()
    async def cleanup(
        ctx: Context, predicate: dict, dry_run: bool = True
    ) -> dict:
        """Delete graph directories from the active session, safely.

        The unit of deletion is a WHOLE graph directory (its outputs,
        ``graph.json``, ``node_index.json``, ``lineage.json``) — never
        individual files. ``dry_run=True`` (the default) reports what
        WOULD be deleted without touching disk; pass ``dry_run=False``
        to actually delete.

        ``predicate`` is a single-key dict:

        - ``{"glob": "*batch*"}`` — match against graph directory names.
        - ``{"tag": "reject"}`` — graphs any of whose files carry the tag.
        - ``{"age_days": 30}`` — directories older than N days (mtime).
        - ``{"graph_id": "<exact id>"}`` — one specific graph.
        - ``{"and": [...]}`` / ``{"or": [...]}`` / ``{"not": {...}}`` —
          boolean composition.

        Two protections can refuse a selected graph (reported under
        ``protected`` with a ``reason``, never silently skipped):

        - ``referenced_by_survivor`` — some surviving graph's lineage
          records an input file inside this graph, so deleting it would
          orphan provenance; ``dependents`` lists the surviving graph
          ids. Delete the dependents first (or select them too).
        - ``tagged`` — the graph's files carry tags (tags are keep
          signals). Waived when the predicate explicitly names one of
          the graph's tags via a ``{"tag": ...}`` clause.

        A real run also prunes the conversational ``latest`` /
        ``prev_N`` slots pointing at deleted graphs (holes are not
        renumbered) and removes ``tags.json`` entries for deleted files.

        Returns ``{status, dry_run, deleted: [ids], protected:
        [{id, reason, dependents?|tags?}], freed_bytes, warnings}``.
        In dry-run, ``deleted`` and ``freed_bytes`` describe what a real
        run would do.
        """
        return await cleanup_impl(
            ctx, predicate, dry_run,
            sessions=sessions, latest_tracker=latest_tracker,
        )

    @mcp.tool()
    async def cleanup_cache(
        ctx: Context, predicate: dict | None = None, dry_run: bool = True
    ) -> dict:
        """Report on — or evict files from — the global derivative cache.

        The cache (``pvoc`` / ``analysis`` / ``visualizations`` /
        ``audition`` tiers) holds pure-function artifacts, so eviction
        is always safe: anything removed is recomputed on demand.
        Deletion is file-level within tiers.

        With no ``predicate`` (and ``dry_run=True``, the default) this
        is a pure report: per-tier file counts and byte totals. With a
        predicate, matching files are reported (dry run) or deleted
        (``dry_run=False``). A real run without a predicate is refused —
        "evict everything" must be spelled explicitly.

        ``predicate`` is a single-key dict:

        - ``{"tier": "pvoc"}`` — one of pvoc / analysis /
          visualizations / audition. The practical post-CDP-upgrade
          eviction lever.
        - ``{"age_days": 90}`` — files older than N days (mtime).
        - ``{"size_gt_mb": 100}`` — individual files larger than N MB.
        - ``{"and": [...]}`` / ``{"or": [...]}`` / ``{"not": {...}}``.

        The design doc's ``cdp_version`` / ``lib_version`` predicates
        are NOT supported: cache keys are opaque hashes with versions
        baked in, so version-selective eviction would need a metadata
        sidecar (recorded as future work). Use ``{"tier": ...}`` after
        an upgrade instead.

        Returns ``{status, dry_run, deleted_count, freed_bytes,
        per_tier: {tier: {files, bytes, matched_files, matched_bytes}},
        warnings}``. ``files`` / ``bytes`` are pre-deletion snapshots.
        """
        return await cleanup_cache_impl(
            ctx, predicate, dry_run, cache_root=cache_root,
        )
