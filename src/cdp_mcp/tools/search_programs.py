"""The ``search_programs`` tool + the ``recommend_transforms`` prompt.

``search_programs`` is the discoverability layer over the CURATED
knowledge: 338 entries is too much context to list, and ``search_docs``
greps the official manual — which describes every program
indiscriminately and never sees the curated ``musical_use`` /
``description`` / parameter-description text. This tool searches that
curated text via :mod:`cdp_mcp.knowledge.search_index` (FTS5, bm25),
mirroring the docs tools' shape: dependencies captured by closure in
:func:`register`, lazy ``ensure_index`` on every call (knowledge changes
only when the package does, so this is one fingerprint pass), builds off
the event loop via ``asyncio.to_thread``, plain-dict results, structured
``{status: "failed"}`` dicts instead of exceptions for environment
failures.

``recommend_transforms_prompt`` is the matching workflow prompt — the
sample-driven discovery path (analyze → classify the material → search →
vet → audition). It is intentionally NOT registered by :func:`register`;
the integrator calls :func:`register_prompt` alongside the existing
:mod:`cdp_mcp.prompts` registrations.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from ..knowledge import search_index
from ..knowledge.loader import KnowledgeIndex

# Defensive cap on the limit argument — there are only a few hundred
# curated entries; nobody needs more than this per query.
_MAX_SEARCH_LIMIT = 50


def register(
    mcp: FastMCP,
    *,
    knowledge_index: KnowledgeIndex,
    index_path: Path,
) -> None:
    """Register the ``search_programs`` tool against ``mcp``.

    ``knowledge_index`` is the loaded curated knowledge; ``index_path``
    is where the FTS5 database lives (built lazily on first search,
    rebuilt only when the knowledge fingerprint changes).
    """

    async def _ready_index() -> dict | None:
        """Bring the index up to date; a structured error dict on failure."""
        try:
            await asyncio.to_thread(
                search_index.ensure_index, knowledge_index, index_path
            )
        except (OSError, sqlite3.Error) as e:
            return {
                "status": "failed",
                "errors": [
                    {
                        "type": "search_index_unavailable",
                        "message": (
                            f"Building the program search index failed: {e}"
                        ),
                        "fix": (
                            f"Check that {index_path.parent} is writable. "
                            "Until then, browse with list_categories() / "
                            "list_programs(category=...) and "
                            "get_program_info() instead."
                        ),
                    }
                ],
            }
        return None

    @mcp.tool()
    async def search_programs(
        ctx: Context,
        query: str,
        limit: int = 8,
        category: str | None = None,
        domain: Literal["time", "spectral"] | None = None,
    ) -> dict:
        """Search the CURATED CDP knowledge by musical intent.

        This searches what each curated program is FOR — its name,
        category, description, musical_use, parameter descriptions, and
        known_issues — so a musical description finds programs.
        Contrast: ``search_docs`` greps the official manual (reference
        prose, covers uncurated programs indiscriminately);
        ``list_programs`` browses by category. Start HERE when you have
        a sound-design goal in words and don't yet know the program.

        Plain keywords work best (FTS5 operators are neutralized), and
        one idea is worth several angles — "granular stutter",
        "metallic shimmer", "time-stretch keep pitch" each surface a
        different family. Natural phrases are fine too: when the exact
        word combination matches nothing, the terms are OR-composed and
        ranked, so the informative words still win.

        Returns ``status``, ``query``, ``result_count``, and
        ``results``: each hit carries ``program``/``mode``/``submode``
        (exactly the ``get_program_info`` key), ``category``,
        ``domain``, ``score`` (more negative is better), ``snippet``
        (matched terms wrapped in ``[`` ``]``), and the entry's
        ``musical_use`` (truncated ~200 chars) — enough to judge
        whether to pull the full entry with ``get_program_info``.
        ``category`` and ``domain`` filter with AND semantics; an
        unknown ``category`` adds a warning listing the valid ones.
        """
        error = await _ready_index()
        if error is not None:
            return error
        limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        warnings: list[str] = []
        if category is not None and category not in knowledge_index.categories():
            warnings.append(
                f"Unknown category {category!r} — no entry has it. Valid "
                f"categories: {', '.join(knowledge_index.categories())}."
            )
        results = await asyncio.to_thread(
            search_index.search, index_path, query, limit, category, domain
        )
        payload = {
            "status": "ok",
            "query": query,
            "result_count": len(results),
            "results": results,
        }
        if warnings:
            payload["warnings"] = warnings
        return payload


# ---------------------------------------------------------------------------
# recommend_transforms workflow prompt
# ---------------------------------------------------------------------------


def recommend_transforms_prompt(
    input_file: str = "<input_file>",
    goal: str = "a musically interesting transformation",
) -> str:
    """The ``recommend_transforms`` prompt text — the sample-driven
    discovery recipe. Kept as a plain function (like the docstring says:
    NOT registered by :func:`register`) so the integrator wires it via
    :func:`register_prompt` next to the existing prompt registrations.
    """
    return f"""\
Recommend CDP transforms for {input_file!r}, aiming for: {goal}.

1. analyze({input_file!r}, verbose=True) and read the 13-field
   scorecard. The class-defining fields: onset_count and crest_db
   (articulation), spectral_flatness_db (pitched vs noisy), duration_s,
   and n_channels (some curated ops are mono- or stereo-only). Let the
   numbers, not assumptions, drive step 2.

2. Classify the material as ONE of four classes:
   - PITCHED SUSTAIN — low flatness, few onsets, steady level. Pitch,
     formant, and spectral ops thrive; grain/syllable ops see one event.
   - ARTICULATED WITH SILENCES — several onsets separated by real
     silence (speech, plucked phrases). The grain / envspeak / stutter
     family works as designed here, and only here.
   - BROADBAND BED — high flatness, drifting level, no true silences
     (field recordings, pads). Filters, blur, and brassage territory.
   - SHORT ONE-SHOT — under ~1 s, a single event. bounce / stretch /
     extend-loop territory.
   Landmines the tools will NOT catch for you:
   - Grain ops need REAL silences. On a drifting bed they don't refuse:
     the level dips below their gate and the quiet material is silently
     DISCARDED (measured -23% duration on a field-recording bed).
   - Retime/onset ops need literal zero samples between events — if the
     "silences" are merely quiet, gate the file first.
   - FOF/formant ops (the specfnu family) want pitched material but
     never check — on noise they run happily and return garbage.

3. Run 2-4 search_programs() queries from different angles: the user's
   own descriptive words, then those words crossed with the material
   class (e.g. "granular stutter", "metallic shimmer", "time-stretch
   keep pitch"). Each angle surfaces a different program family.

4. get_program_info() the top candidates. Check known_issues and
   channel_constraint against the scorecard from step 1, and drop
   anything that fights the material class from step 2.

5. Audition instead of asserting: sweep() the strongest candidate
   across 4-6 parameter values (or batch() two or three rival ops on
   the same input), then compare() the favorites against the source and
   tag() the keepers with a one-line why.

Also: list_examples() holds verified multi-op chains if one op isn't
enough; and if this session already has tagged sound objects or journal
notes, read them first — recommend transforms that will cohere with the
material that's already there."""


def register_prompt(mcp: FastMCP) -> None:
    """Register the ``recommend_transforms`` prompt template against
    ``mcp`` — called by the integrator next to ``prompts.register``."""

    @mcp.prompt(title="Recommend transforms")
    def recommend_transforms(
        input_file: str, goal: str = "a musically interesting transformation"
    ) -> str:
        """Sample-driven discovery: analyze the material, classify it,
        search the curated knowledge, vet candidates, audition a sweep."""
        return recommend_transforms_prompt(input_file, goal)
