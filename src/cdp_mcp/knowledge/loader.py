"""Knowledge-index loader.

Scans :mod:`cdp_mcp.knowledge.data` (curated entries) and
``data_uncurated/`` (auto-generated long-tail stubs from
``scripts/generate_uncurated_entries.py``) for ``*.json`` files, validates
each through :class:`~cdp_mcp.schema.KnowledgeEntry`, and exposes lookup
helpers used by the introspection tools.

Uncurated entries carry ``curated: false`` and surface only through
``list_programs(curated_only=False)`` — ``process()`` hard-gates on
``entry.curated``, so loading them here widens discovery without widening
execution.

Failure mode is intentionally tolerant: malformed entries log a warning to
``sys.stderr`` and are skipped — the server still starts. We never write
diagnostics to stdout (it carries MCP JSON-RPC traffic; see ``server.py``).
"""

from __future__ import annotations

import json
import sys
from importlib.resources import as_file, files
from typing import Literal

from pydantic import ValidationError

from ..schema import KnowledgeEntry


class SubmodeAmbiguousError(LookupError):
    """Raised by :meth:`KnowledgeIndex.get` when ``(program, mode)`` has
    multiple entries (distinct submodes) and the caller didn't pick one.

    Carries the sorted curated submode list (``None`` first) so tool
    surfaces can tell the LLM exactly which values are valid — the
    structured ``submode_required`` error is built from this.
    """

    def __init__(
        self, program: str, mode: str, submodes: list[int | None]
    ) -> None:
        self.program = program
        self.mode = mode
        self.submodes = submodes
        super().__init__(
            f"{program!r} {mode!r} has multiple curated submodes "
            f"{submodes}; pass submode=<n> to choose one."
        )


def _submode_sort_key(entry: KnowledgeEntry) -> tuple[bool, int]:
    """Deterministic submode ordering: ``None`` first, then ascending ints."""
    return (
        entry.submode is not None,
        entry.submode if entry.submode is not None else 0,
    )


class KnowledgeIndex:
    """In-memory index of curated CDP knowledge entries.

    Entries are keyed by ``(program, mode, submode)`` — one CDP program
    mode can be curated in several submodes (e.g. ``filter bank`` submode
    1 today, siblings in later tranches), and each submode is a distinct
    entry with its own parameter semantics. A duplicate triple warns to
    stderr and keeps the first entry seen (consistent with the loader's
    tolerant failure mode).

    Construct via :meth:`load` rather than directly — ``load`` is the entry
    point that walks the packaged ``data/`` directory.
    """

    def __init__(self, entries: list[KnowledgeEntry]) -> None:
        self._by_key: dict[tuple[str, str, int | None], KnowledgeEntry] = {}
        self._by_pair: dict[tuple[str, str], list[KnowledgeEntry]] = {}
        self._by_category: dict[str, list[KnowledgeEntry]] = {}
        for entry in entries:
            key = (entry.program, entry.mode, entry.submode)
            if key in self._by_key:
                print(
                    f"[cdp-mcp] WARNING: duplicate knowledge entry for "
                    f"program={entry.program!r} mode={entry.mode!r} "
                    f"submode={entry.submode!r}; keeping the first, "
                    f"skipping the later one.",
                    file=sys.stderr,
                )
                continue
            self._by_key[key] = entry
            self._by_pair.setdefault(
                (entry.program, entry.mode), []
            ).append(entry)
            self._by_category.setdefault(entry.category, []).append(entry)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(cls) -> KnowledgeIndex:
        """Load all entries from the packaged ``data/`` and
        ``data_uncurated/`` directories.

        ``data/`` holds the curated entries; ``data_uncurated/`` holds
        auto-generated long-tail stubs (``curated: false``, empty
        parameter dicts) that exist for discovery only. The uncurated
        directory is optional — absent, nothing is loaded from it.

        Uses :func:`importlib.resources.files` so it works equally from an
        editable install and an installed wheel. Bad entries are logged and
        skipped, not raised.
        """
        entries: list[KnowledgeEntry] = []
        for subdir in ("data", "data_uncurated"):
            data_root = files("cdp_mcp.knowledge").joinpath(subdir)
            # ``as_file`` materializes the resource to a real filesystem
            # path when the package is installed inside a zip; for editable
            # installs it's a no-op that returns the existing path.
            try:
                with as_file(data_root) as data_dir:
                    if not data_dir.is_dir():
                        continue
                    json_paths = sorted(p for p in data_dir.glob("*.json"))
                    for path in json_paths:
                        try:
                            raw = path.read_text(encoding="utf-8")
                            entries.append(
                                KnowledgeEntry.model_validate_json(raw)
                            )
                        except (
                            ValidationError, json.JSONDecodeError, OSError
                        ) as e:
                            print(
                                f"[cdp-mcp] WARNING: skipping malformed "
                                f"knowledge entry {path.name}: {e}",
                                file=sys.stderr,
                            )
            except FileNotFoundError:
                # Zip-backed installs raise here for a missing resource
                # directory; a missing data_uncurated/ is not an error.
                continue
        print(f"[cdp-mcp] Loaded {len(entries)} knowledge entries", file=sys.stderr)
        return cls(entries)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(
        self, program: str, mode: str, submode: int | None = None
    ) -> KnowledgeEntry | None:
        """Look up an entry by ``(program, mode[, submode])``.

        With ``submode`` given, this is an exact triple lookup — ``None``
        if absent. With ``submode=None`` the pair resolves as:

        - 0 entries → ``None``;
        - exactly 1 entry → that entry (regardless of its submode), so
          single-submode pairs keep the pre-submode-keying call shape;
        - >1 entries → :class:`SubmodeAmbiguousError` carrying the sorted
          curated submode list — the caller must pick one.
        """
        if submode is not None:
            return self._by_key.get((program, mode, submode))
        matches = self._by_pair.get((program, mode), [])
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        # Ambiguous pair. Report the curated submodes (that's what the
        # caller can actually run); fall back to all submodes in the
        # degenerate all-uncurated case so the error is never empty.
        curated = [e for e in matches if e.curated] or matches
        submodes = [e.submode for e in sorted(curated, key=_submode_sort_key)]
        raise SubmodeAmbiguousError(program, mode, submodes)

    def get_pair(self, program: str, mode: str) -> list[KnowledgeEntry]:
        """All entries for ``(program, mode)``, sorted by submode
        (``None`` first). Empty list if the pair is unknown."""
        return sorted(
            self._by_pair.get((program, mode), []), key=_submode_sort_key
        )

    def list_entries(
        self,
        category: str | None = None,
        domain: Literal["time", "spectral"] | None = None,
        curated_only: bool = True,
    ) -> list[KnowledgeEntry]:
        """Return entries matching the optional filters.

        Filters compose with AND semantics — passing both ``category`` and
        ``domain`` returns only entries that match both.
        """
        if category is not None:
            candidates = list(self._by_category.get(category, []))
        else:
            candidates = list(self._by_key.values())

        if domain is not None:
            candidates = [e for e in candidates if e.domain == domain]
        if curated_only:
            candidates = [e for e in candidates if e.curated]
        # Stable, deterministic order for tests + LLM scanability. The
        # submode component keeps multi-submode pairs deterministic too
        # (None first, then ascending).
        candidates.sort(
            key=lambda e: (e.program, e.mode, *_submode_sort_key(e))
        )
        return candidates

    def categories(self) -> list[str]:
        """Sorted unique category names present in the loaded entries."""
        return sorted(self._by_category.keys())
