"""The ``cdp://examples/*`` library — verified chain recipes.

Phase 5 deliverable (design list: "examples library, sourced from saved
graphs"). Each example is a package-shipped JSON carrying a ready-to-run
``graph()`` definition (``{inputs, nodes, output}``) plus the musical
intent, the material it suits, and provenance — every chain shipped here
has been executed end-to-end against real CDP (the Phase 1a acceptance
chain, the Phase 5 generalization matrix, or a tranche transcript; each
example's ``source`` field says which).

Two access points:

- :func:`list_examples` (MCP tool, registered here) — summaries with
  stable ``cdp://examples/<name>`` uris.
- ``read_doc`` (in :mod:`cdp_mcp.tools.docs`) dispatches any
  ``cdp://examples/...`` uri to :func:`read_example_uri` below, so the
  whole ``cdp://`` namespace reads through one tool. Examples are
  package data — unlike ``cdp://docs/*`` they never require a CDP
  manual install.

Examples capture the SHAPE of a chain, like session templates
(:mod:`cdp_mcp.tools.templates`), and are executed the same way: replace
``definition["inputs"]`` values with your session's input files and pass
``inputs`` / ``nodes`` / ``output`` to ``graph()`` — ``dry_run=True``
first to see per-node duration predictions against your actual file.
"""

from __future__ import annotations

import json
import logging
from importlib.resources import as_file, files

from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

_URI_PREFIX = "cdp://examples/"
_REQUIRED_KEYS = frozenset(
    {"name", "title", "material", "description", "source", "definition"}
)
_GRAPH_HINT = (
    "Replace definition['inputs'] values with your session input files, "
    "then pass definition['inputs'], definition['nodes'], and "
    "definition['output'] to graph() — dry_run=True first to validate "
    "and see per-node duration predictions for your actual input."
)

_cache: dict[str, dict] | None = None


def load_examples() -> dict[str, dict]:
    """All packaged examples, keyed by name, sorted; cached after the
    first call. Malformed files are logged and skipped, never raised —
    a bad example must not break server startup (mirrors the knowledge
    loader's policy)."""
    global _cache
    if _cache is not None:
        return _cache
    examples: dict[str, dict] = {}
    data_root = files("cdp_mcp.knowledge").joinpath("examples")
    try:
        with as_file(data_root) as data_dir:
            if data_dir.is_dir():
                for path in sorted(data_dir.glob("*.json")):
                    try:
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        missing = _REQUIRED_KEYS - raw.keys()
                        if missing:
                            raise ValueError(
                                f"missing keys: {sorted(missing)}"
                            )
                        if raw["name"] != path.stem:
                            raise ValueError(
                                f"name {raw['name']!r} != filename stem"
                            )
                        examples[raw["name"]] = raw
                    except (ValueError, OSError, json.JSONDecodeError) as e:
                        logger.warning(
                            "[cdp-mcp] Skipping malformed example %s: %s",
                            path.name,
                            e,
                        )
    except (OSError, FileNotFoundError):  # packaged dir absent entirely
        pass
    _cache = examples
    return examples


def read_example_uri(uri: str) -> dict:
    """Resolve one ``cdp://examples/<name>`` uri to its full payload.

    Called by ``read_doc``'s namespace dispatch. Returns the example's
    metadata, its ready-to-run ``definition``, and a usage hint — or a
    structured ``example_not_found`` error listing what does exist.
    """
    name = uri[len(_URI_PREFIX):].strip("/")
    example = load_examples().get(name)
    if example is None:
        known = ", ".join(load_examples()) or "(none packaged)"
        return {
            "status": "failed",
            "errors": [
                {
                    "type": "example_not_found",
                    "message": f"No example named {name!r}.",
                    "fix": (
                        "Call list_examples() and pass a returned uri "
                        f"verbatim. Packaged examples: {known}."
                    ),
                }
            ],
        }
    return {
        "status": "ok",
        "uri": _URI_PREFIX + name,
        "title": example["title"],
        "material": example["material"],
        "description": example["description"],
        "source": example["source"],
        "notes": example.get("notes", []),
        "definition": example["definition"],
        "hint": _GRAPH_HINT,
    }


def register(mcp: FastMCP) -> None:
    """Register the examples tool against ``mcp``."""

    @mcp.tool()
    async def list_examples(ctx: Context) -> dict:
        """List the packaged library of verified chain examples.

        Each example is a ready-to-run ``graph()`` definition with its
        musical intent, suitable material, and provenance — every chain
        has been executed end-to-end against real CDP before shipping.
        Returns summaries with ``uri``, ``name``, ``title``,
        ``material``, ``node_count``, and the ops used; pass a ``uri``
        to ``read_doc`` for the full definition and usage notes.
        """
        summaries = []
        for name, ex in load_examples().items():
            nodes = ex["definition"].get("nodes", [])
            summaries.append(
                {
                    "uri": _URI_PREFIX + name,
                    "name": name,
                    "title": ex["title"],
                    "material": ex["material"],
                    "node_count": len(nodes),
                    "ops": [n.get("op", "?") for n in nodes],
                }
            )
        return {
            "status": "ok",
            "example_count": len(summaries),
            "examples": summaries,
            "hint": (
                "read_doc(uri) returns the full definition; "
                + _GRAPH_HINT
            ),
        }
