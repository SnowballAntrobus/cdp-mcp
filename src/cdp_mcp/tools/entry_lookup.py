"""Shared curated-entry lookup for the execution tool surface.

The knowledge index keys entries by ``(program, mode, submode)``, so
``process()`` / ``batch()`` / ``sweep()`` / ``breakpoint()`` / ``graph()``
all resolve entries through this one helper, which translates the
loader's lookup semantics into the structured error vocabulary:

- ``submode_required`` — the pair has multiple curated submodes and the
  call didn't pick one. The message lists the curated submodes; the fix
  says to pass ``submode=<n>`` and to consult
  ``get_program_info(program, mode)`` for per-submode descriptions.
- ``not_curated`` — no curated entry at the requested key. When an
  explicit submode missed, the message additionally names the submodes
  that ARE curated for the pair (if any).
"""

from __future__ import annotations

from ..knowledge.loader import KnowledgeIndex, SubmodeAmbiguousError
from ..schema import ErrorEntry, KnowledgeEntry

_DEFAULT_NOT_CURATED_FIX = (
    "Use list_programs() to see curated entries. For uncurated CDP "
    "programs, use execute()."
)


def resolve_entry(
    knowledge_index: KnowledgeIndex,
    program: str,
    mode: str,
    submode: int | None = None,
    *,
    where: str = "",
    not_curated_fix: str = _DEFAULT_NOT_CURATED_FIX,
) -> tuple[KnowledgeEntry | None, ErrorEntry | None]:
    """Look up a curated entry; return ``(entry, None)`` or ``(None, error)``.

    ``where`` prefixes messages for multi-node callers (``graph()`` passes
    ``node '<id>'``). ``not_curated_fix`` lets each tool keep its own
    actionable fix text for the missing-entry case.
    """
    prefix = f"{where}: " if where else ""
    try:
        entry = knowledge_index.get(program, mode, submode)
    except SubmodeAmbiguousError as e:
        listed = ", ".join(str(s) for s in e.submodes)
        return None, ErrorEntry(
            type="submode_required",
            message=(
                f"{prefix}{program!r} {mode!r} is curated in multiple "
                f"submodes: [{listed}]. Pick one explicitly."
            ),
            fix=(
                f"Pass submode=<n> (one of [{listed}]). Consult "
                f"get_program_info({program!r}, {mode!r}) for per-submode "
                "descriptions."
            ),
        )
    if entry is not None and entry.curated:
        return entry, None

    if submode is not None:
        curated_submodes = [
            e.submode
            for e in knowledge_index.get_pair(program, mode)
            if e.curated
        ]
        if curated_submodes:
            listed = ", ".join(str(s) for s in curated_submodes)
            message = (
                f"{prefix}No curated knowledge entry for {program!r} "
                f"{mode!r} submode {submode}. Curated submode(s) for this "
                f"pair: [{listed}]."
            )
        else:
            message = (
                f"{prefix}No curated knowledge entry for {program!r} "
                f"{mode!r} submode {submode} (no submode of this pair is "
                "curated)."
            )
    else:
        message = (
            f"{prefix}No curated knowledge entry for {program!r} {mode!r}."
        )
    return None, ErrorEntry(
        type="not_curated", message=message, fix=not_curated_fix
    )
