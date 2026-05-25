"""Shared filesystem and hashing helpers.

These utilities started life inside :mod:`cdp_mcp.session` (Task 3) and were
promoted here in Task 4 so :mod:`cdp_mcp.graph` can share the atomic-write
pattern without circular imports. Anything else in the project that writes
on-disk metadata should call :func:`atomic_write_text` rather than rolling
its own write.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` via a tmp file + :func:`os.replace`.

    Canonical pattern for any on-disk metadata cdp-mcp writes — ``config.json``,
    ``node_index.json``, ``lineage.json``, ``graph.json``, etc. Atomic on
    POSIX and Windows: the rename either completes or doesn't, and a
    half-written file is never visible at the target path.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path, chunk_size: int = 65536) -> str:
    """Compute the sha256 hex digest of a file, chunked for memory safety.

    Used by the lineage layer (input + output provenance) and — in Phase 1b —
    by the content-addressable cache. ``chunk_size`` defaults to 64 KiB which
    is well-suited to typical audio file I/O.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
