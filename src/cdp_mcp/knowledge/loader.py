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


class KnowledgeIndex:
    """In-memory index of curated CDP knowledge entries.

    Construct via :meth:`load` rather than directly — ``load`` is the entry
    point that walks the packaged ``data/`` directory.
    """

    def __init__(self, entries: list[KnowledgeEntry]) -> None:
        self._by_key: dict[tuple[str, str], KnowledgeEntry] = {}
        self._by_category: dict[str, list[KnowledgeEntry]] = {}
        for entry in entries:
            self._by_key[(entry.program, entry.mode)] = entry
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

    def get(self, program: str, mode: str) -> KnowledgeEntry | None:
        """Look up an entry by ``(program, mode)``. Returns ``None`` if absent."""
        return self._by_key.get((program, mode))

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
        # Stable, deterministic order for tests + LLM scanability.
        candidates.sort(key=lambda e: (e.program, e.mode))
        return candidates

    def categories(self) -> list[str]:
        """Sorted unique category names present in the loaded entries."""
        return sorted(self._by_category.keys())
