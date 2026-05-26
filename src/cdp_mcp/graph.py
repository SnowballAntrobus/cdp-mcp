"""Graph directory bookkeeping, reference resolution, and output verification.

Three responsibilities under one roof for Phase 1a:

- :class:`GraphDir` — manages one ``<session>/graphs/<id>/`` directory and
  the metadata files within (``graph.json``, ``node_index.json``,
  ``lineage.json``).
- :class:`LatestTracker` — in-memory single-pointer "most recent successful
  node". Phase 1b will expand into a full ``recent_graphs`` deque.
- :func:`resolve_target` — turns a user-supplied reference (``"latest"``,
  ``"<graph_id>:n2"``, an absolute path, or a session-relative path) into
  an absolute :class:`~pathlib.Path` on disk.
- :func:`verify_output` — never-raises post-execution validity check on a
  CDP output file (existence + size + RMS for wav).

No tools are registered from this module; Tasks 5/6 import these primitives.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .schema import ContextBlock, NodeLineage, OutputVerification, RecentGraphEntry
from .session import Session
from .utils import atomic_write_text

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ReferenceResolutionError(Exception):
    """Raised when a reference can't be resolved to an existing file."""


# ---------------------------------------------------------------------------
# Graph directory
# ---------------------------------------------------------------------------


def _make_graph_id(slug: str) -> str:
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}"
    return f"{ts}-{slug}"


class GraphDir:
    """One graph directory under ``<session>/graphs/``.

    Allocated fresh at construction time. ``graph.json`` is opt-in
    (``set_graph_definition``); ``node_index.json`` and ``lineage.json`` are
    initialized empty and updated atomically as nodes complete.

    Not thread-safe — designed for sequential use within one graph build.
    """

    def __init__(self, session: Session, slug: str) -> None:
        self._session = session
        self._id = _make_graph_id(slug)
        self._root = session.graphs_dir / self._id
        # exist_ok=False so a collision is loud; with millisecond timestamps
        # this is vanishingly rare, and the caller is best positioned to retry.
        self._root.mkdir(parents=True, exist_ok=False)
        atomic_write_text(self.node_index_path, "{}\n")
        atomic_write_text(self.lineage_path, '{"nodes": {}}\n')

    @property
    def id(self) -> str:
        return self._id

    @property
    def root(self) -> Path:
        return self._root

    @property
    def node_index_path(self) -> Path:
        return self._root / "node_index.json"

    @property
    def lineage_path(self) -> Path:
        return self._root / "lineage.json"

    @property
    def graph_definition_path(self) -> Path:
        return self._root / "graph.json"

    def set_graph_definition(self, definition: dict) -> None:
        """Write ``graph.json``. Call once early in the graph's life."""
        atomic_write_text(
            self.graph_definition_path,
            json.dumps(definition, indent=2, sort_keys=True) + "\n",
        )

    def add_node(
        self,
        node_id: str,
        output_filename: str,
        lineage: NodeLineage,
    ) -> None:
        """Record a completed node.

        Two-step write: ``node_index.json`` then ``lineage.json``. A crash
        between the two leaves the node visible in the index without a
        lineage entry, which is acceptable for Phase 1a — downstream
        reference resolution still works.
        """
        index = self._read_json(self.node_index_path)
        index[node_id] = output_filename
        atomic_write_text(
            self.node_index_path,
            json.dumps(index, indent=2, sort_keys=True) + "\n",
        )

        lineage_data = self._read_json(self.lineage_path)
        nodes = lineage_data.setdefault("nodes", {})
        nodes[node_id] = lineage.model_dump(mode="json")
        atomic_write_text(
            self.lineage_path,
            json.dumps(lineage_data, indent=2, sort_keys=True) + "\n",
        )

    def get_node_output_path(self, node_id: str) -> Path | None:
        index = self._read_json(self.node_index_path)
        filename = index.get(node_id)
        if filename is None:
            return None
        return self._root / filename

    def node_ids(self) -> list[str]:
        return sorted(self._read_json(self.node_index_path).keys())

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# LatestTracker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Slot:
    """Internal deque entry — the wire shape is RecentGraphEntry, which is
    built positionally when assembling the context block."""

    graph_id: str
    node_id: str


class LatestTracker:
    """Length-5 deque of recent successful (graph, node) tuples.

    Provides positional aliases ``latest`` (deque[0]) and ``prev_1`` ..
    ``prev_4`` (deque[1..4]). Per-process state; not persisted; reset on
    every ``set_session()`` call so a fresh session activation starts with
    an empty conversational history (design-doc Rule 2).

    New actions push to the front via ``update()``; the oldest slot falls
    off when capacity is exceeded. Cleanup of a specific graph (Task 14+)
    sets the matching slot to ``None`` but does NOT shift adjacent slots —
    holes stay holes until aged off by new actions (Rule 3).
    """

    _CAPACITY = 5  # latest + prev_1..prev_4

    def __init__(self) -> None:
        self._deque: deque[_Slot | None] = deque(maxlen=self._CAPACITY)

    def update(self, graph_id: str, node_id: str) -> None:
        """Push a new successful (graph, node) to the front. Capacity-bounded;
        the oldest slot falls off when the deque was full."""
        self._deque.appendleft(_Slot(graph_id=graph_id, node_id=node_id))

    @property
    def latest(self) -> str | None:
        """Back-compat: return ``"<graph_id>:<node_id>"`` for slot 0, or
        ``None`` if the deque is empty or slot 0 is a hole."""
        if not self._deque:
            return None
        s = self._deque[0]
        if s is None:
            return None
        return f"{s.graph_id}:{s.node_id}"

    def get_slot(self, position: int) -> _Slot | None:
        """Return the slot at position N (0 = latest, 1 = prev_1, …) or
        ``None`` if out of range or a hole."""
        if position < 0 or position >= len(self._deque):
            return None
        return self._deque[position]

    def remove(self, graph_id: str) -> None:
        """Mark every slot pointing at ``graph_id`` as a hole. Other slots
        are NOT shifted to fill the gap. Used by the cleanup() transaction
        in Task 14+; no production caller exists in Phase 1b.
        """
        for i, slot in enumerate(self._deque):
            if slot is not None and slot.graph_id == graph_id:
                self._deque[i] = None

    def recent_entries(self) -> list[RecentGraphEntry]:
        """Materialize the deque as a list of RecentGraphEntry for the
        context block. Holes are skipped; non-hole entries keep their
        positional alias (``latest``, ``prev_1``, …) even when surrounded
        by holes — this matches design-doc Rule 3."""
        out: list[RecentGraphEntry] = []
        for i, slot in enumerate(self._deque):
            if slot is None:
                continue
            alias = "latest" if i == 0 else f"prev_{i}"
            out.append(RecentGraphEntry(
                id=slot.graph_id,
                output_node=slot.node_id,
                alias=alias,
            ))
        return out

    def clear(self) -> None:
        """Empty the deque. Called by ``set_session()`` so each session
        activation starts with fresh conversational state, and useful in
        tests."""
        self._deque.clear()


# ---------------------------------------------------------------------------
# Context block (shared by execute / process result envelopes)
# ---------------------------------------------------------------------------


def build_context_block(
    session: Session,
    latest_tracker: LatestTracker,
    active_graph: str | None = None,
) -> ContextBlock:
    """Build the context block returned with every action result.

    Phase 1b: ``active_graph`` from caller, ``latest`` from the tracker,
    ``recent_graphs`` populated from the tracker's deque (positional
    aliases ``latest``, ``prev_1`` .. ``prev_4``), and ``available_sources``
    is session inputs + recent graph refs, deduplicated and ordered with
    inputs first.

    The broader 15-most-recent filesystem scan + tagged keepers +
    auto-pinned nodes land in Task 8.
    """
    input_files: list[str] = []
    if session.inputs_dir.exists():
        input_files = sorted(
            p.name for p in session.inputs_dir.iterdir() if p.is_file()
        )

    recent = latest_tracker.recent_entries()
    recent_refs = [f"{e.id}:{e.output_node}" for e in recent]

    # Deduplicate while preserving order: input filenames first, then
    # graph refs. set() would lose order; this preserves the natural
    # reading.
    seen: set[str] = set()
    available: list[str] = []
    for s in input_files + recent_refs:
        if s in seen:
            continue
        seen.add(s)
        available.append(s)

    return ContextBlock(
        active_graph=active_graph,
        latest=latest_tracker.latest,
        recent_graphs=recent,
        available_sources=available,
    )


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------


def resolve_target(
    ref: str,
    session: Session,
    latest: LatestTracker,
) -> Path:
    """Turn a reference into an absolute path on disk.

    Accepted forms:
    - ``"latest"`` — follow :attr:`LatestTracker.latest`.
    - ``"<graph_id>:<node_id>"`` — look up via the graph's
      ``node_index.json``.
    - absolute path — returned as-is after existence check.
    - relative path — resolved against ``session.inputs_dir``.

    Phase 1a is permissive about absolute paths (existence check only);
    tighter constraints (must live inside the session tree or the CDP
    cache) belong in Task 5's ``execute()`` security boundary.

    Raises:
        ReferenceResolutionError: with a clear message including the ref.
    """
    if not isinstance(ref, str) or not ref:
        raise ReferenceResolutionError(f"Empty or non-string reference: {ref!r}")

    if ref == "latest":
        slot = latest.get_slot(0)
        if slot is None:
            raise ReferenceResolutionError(
                "Reference 'latest' has no value yet — no node has succeeded "
                "in this server session."
            )
        # Recurse once into the canonical "<graph_id>:<node_id>" form; the
        # ":" branch below handles the actual lookup.
        return resolve_target(f"{slot.graph_id}:{slot.node_id}", session, latest)

    if ref.startswith("prev_"):
        suffix = ref[len("prev_"):]
        if not suffix.isdigit():
            raise ReferenceResolutionError(
                f"Malformed prev reference {ref!r}: expected 'prev_1' .. 'prev_4'."
            )
        n = int(suffix)
        if n < 1 or n > 4:
            raise ReferenceResolutionError(
                f"prev_N reference {ref!r}: N must be 1..4 (got {n})."
            )
        slot = latest.get_slot(n)
        if slot is None:
            raise ReferenceResolutionError(
                f"Reference {ref!r} has no value — either fewer than {n + 1} "
                "successful actions in this session, the slot was removed by "
                "cleanup(), or this server process just started."
            )
        return resolve_target(f"{slot.graph_id}:{slot.node_id}", session, latest)

    if ":" in ref:
        graph_id, _, node_id = ref.partition(":")
        if not graph_id or not node_id:
            raise ReferenceResolutionError(
                f"Malformed graph reference {ref!r}: expected '<graph_id>:<node_id>'"
            )
        graph_root = session.graphs_dir / graph_id
        node_index_path = graph_root / "node_index.json"
        if not node_index_path.exists():
            raise ReferenceResolutionError(
                f"Reference {ref!r}: no such graph {graph_id!r} "
                f"(missing {node_index_path})"
            )
        try:
            index = json.loads(node_index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ReferenceResolutionError(
                f"Reference {ref!r}: could not read node_index.json: {e}"
            ) from e
        filename = index.get(node_id)
        if filename is None:
            raise ReferenceResolutionError(
                f"Reference {ref!r}: graph {graph_id!r} has no node {node_id!r}"
            )
        path = graph_root / filename
        if not path.exists():
            raise ReferenceResolutionError(
                f"Reference {ref!r}: indexed file does not exist at {path}"
            )
        return path

    path = Path(ref)
    if path.is_absolute():
        if not path.exists():
            raise ReferenceResolutionError(
                f"Absolute path reference {ref!r} does not exist."
            )
        return path

    # Relative — resolve against session.inputs_dir.
    candidate = session.inputs_dir / ref
    if not candidate.exists():
        raise ReferenceResolutionError(
            f"Reference {ref!r} not found in session inputs ({session.inputs_dir})"
        )
    return candidate


# ---------------------------------------------------------------------------
# Output verification
# ---------------------------------------------------------------------------


def verify_output(
    path: Path,
    silence_threshold_dbfs: float = -60.0,
    min_size_bytes: int = 100,
) -> OutputVerification:
    """Sanity-check a CDP output file. Never raises.

    Checks:
    - File exists.
    - File size > ``min_size_bytes`` (catches header-only / empty output).
    - For ``.wav``: RMS > ``silence_threshold_dbfs``.
    - For ``.ana``: size only (RMS isn't meaningful spectrally).

    Returns:
        :class:`OutputVerification` with ``ok=True`` only if every check
        passes. ``rms_dbfs`` is ``None`` for non-wav files, unreadable
        wavs, or silent wavs (rms = 0). Below-threshold but non-silent wavs
        get their dBFS reported plus an error string.
    """
    errors: list[str] = []
    exists = path.exists()
    if not exists:
        return OutputVerification(
            ok=False,
            exists=False,
            size_bytes=0,
            rms_dbfs=None,
            errors=[f"file does not exist: {path}"],
        )

    try:
        size_bytes = path.stat().st_size
    except OSError as e:
        return OutputVerification(
            ok=False,
            exists=True,
            size_bytes=0,
            rms_dbfs=None,
            errors=[f"could not stat file: {e}"],
        )

    if size_bytes <= min_size_bytes:
        errors.append(
            f"file size {size_bytes} bytes is below minimum {min_size_bytes}"
        )

    rms_dbfs: float | None = None
    if path.suffix.lower() == ".wav":
        rms_dbfs, rms_error = _compute_wav_rms_dbfs(path, silence_threshold_dbfs)
        if rms_error:
            errors.append(rms_error)

    return OutputVerification(
        ok=not errors,
        exists=True,
        size_bytes=size_bytes,
        rms_dbfs=rms_dbfs,
        errors=errors,
    )


def _compute_wav_rms_dbfs(
    path: Path,
    silence_threshold_dbfs: float,
) -> tuple[float | None, str | None]:
    """Read a wav file and compute RMS in dBFS.

    Returns ``(rms_dbfs, error_message)``:
    - On unreadable wav → ``(None, "could not read wav: ...")``
    - On silent wav (rms = 0) → ``(None, "silent (rms = 0)")``
    - On below-threshold but non-silent → ``(dbfs, "below silence threshold ...")``
    - On healthy wav → ``(dbfs, None)``

    Stereo content is flattened (not channel-averaged) before RMS — see the
    Task 4 plan for why: averaging cancels anti-correlated channels and
    underreports total signal energy.
    """
    # Lazy import: soundfile pulls in libsndfile via cffi; not free.
    import numpy as np
    import soundfile as sf

    try:
        samples, _sr = sf.read(str(path), dtype="float64")
    except Exception as e:  # noqa: BLE001 — soundfile raises a variety
        return None, f"could not read wav: {e}"

    flat = np.asarray(samples, dtype=np.float64).flatten()
    if flat.size == 0:
        return None, "wav contains no samples"

    rms = float(np.sqrt(np.mean(flat ** 2)))
    if rms == 0.0:
        return None, "silent (rms = 0)"

    dbfs = 20.0 * math.log10(rms)
    if dbfs < silence_threshold_dbfs:
        return dbfs, (
            f"below silence threshold {silence_threshold_dbfs} dBFS "
            f"(rms = {dbfs:.2f} dBFS)"
        )
    return dbfs, None
