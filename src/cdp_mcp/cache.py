"""Global derivative-artifact cache.

PVOC ``.ana`` files, MIR analysis JSON, and visualization PNGs are pure
functions of ``(input_bytes, parameters, software_versions)``. They're
identical across sessions, so we cache them globally under
``~/.cdp_mcp/cache/<tier>/<sha>.<ext>`` and share hits between sessions.

Cache key construction is per-tier:

- PVOC: ``sha256(audio_sha + argv_discriminator + cdp_version)``
- Analysis: ``sha256(audio_sha + feature_set + window + librosa-stack versions)``
- Visualization: ``sha256(audio_sha + mode + window + render_params + librosa+mpl versions)``

Files are written atomically (``.tmp`` + ``os.replace``) so concurrent
writers producing identical content don't corrupt each other.

Lifetime: derivative-cache files live as long as the cache root exists.
Phase 4 introduces ``cleanup_cache()`` with predicate-based eviction.

This module is consumed by:

- :mod:`cdp_mcp.pvoc` — PVOC anal/synth output cache.
- :mod:`cdp_mcp.tools.analyze` — scorecard JSON cache.
- :mod:`cdp_mcp.tools.visualize` — mel-spectrogram PNG cache.
- :mod:`cdp_mcp.pvoc` audition path — same module.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .utils import atomic_write_text

# ---------------------------------------------------------------------------
# Library versions (computed at import for cache-key invalidation)
# ---------------------------------------------------------------------------


def _safe_version(name: str) -> str:
    """Return the installed version of ``name`` or ``"unknown"`` if missing.

    Defensive: missing optional deps shouldn't crash the cache layer at
    import time.
    """
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# Module-level snapshot. Tests may monkeypatch entries.
_LIB_VERSIONS: dict[str, str] = {
    name: _safe_version(name)
    for name in ("librosa", "numpy", "scipy", "pyloudnorm", "matplotlib")
}


# Per-tier library relevance. Tiers not listed contribute nothing from
# _LIB_VERSIONS (e.g., PVOC isn't a Python computation).
_TIER_LIBS: dict[str, tuple[str, ...]] = {
    "analysis": ("librosa", "numpy", "scipy", "pyloudnorm"),
    "visualizations": ("librosa", "numpy", "matplotlib"),
}


# All known tiers — declared up front so cache_size_bytes can report
# zeros for tiers that haven't seen a write yet, and so an unknown
# subdir under cache_root doesn't accidentally count toward the totals.
_KNOWN_TIERS: tuple[str, ...] = ("pvoc", "analysis", "visualizations", "audition")


# ---------------------------------------------------------------------------
# Lookup result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheLookup:
    """Result of a :func:`cache_lookup` call.

    ``path`` is the canonical target either way — callers write to it on
    miss and read from it on hit. ``key`` is exposed for debugging and
    for downstream lineage capture.
    """

    hit: bool
    path: Path
    key: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cache_lookup(
    cache_root: Path,
    tier: str,
    key: str,
    suffix: str,
) -> CacheLookup:
    """Compute the canonical path for ``(tier, key, suffix)`` and check existence.

    Creates the tier subdirectory if missing — the security gate and other
    callers benefit from a stable resolved directory.

    Args:
        cache_root: The root cache directory (e.g. ``~/.cdp_mcp/cache``).
        tier: One of the known tiers (``"pvoc"``, ``"analysis"``,
            ``"visualizations"``, ``"audition"``).
        key: Output of one of the per-tier key builders below.
        suffix: File extension including leading dot (e.g. ``".ana"``).
    """
    tier_dir = _ensure_tier_dir(cache_root, tier)
    target = tier_dir / f"{key}{suffix}"
    return CacheLookup(hit=target.exists(), path=target, key=key)


def cache_populate(target_path: Path, source_path: Path) -> bool:
    """Copy ``source_path`` → ``target_path`` atomically.

    Writes to ``<target>.tmp`` and then ``os.replace``. Returns ``True``
    on success, ``False`` on any write failure (logged to stderr).

    Caching is best-effort, not load-bearing for correctness: callers use
    the freshly computed source path regardless of the return value.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        shutil.copy2(source_path, tmp)
        os.replace(tmp, target_path)
        return True
    except OSError as e:
        # Remove the .tmp residue if it landed; ignore secondary failure.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        print(
            f"[cdp-mcp] Warning: cache populate failed for {target_path}: "
            f"{e.__class__.__name__}: {e}. Result returned anyway.",
            file=sys.stderr,
        )
        return False


def cache_populate_json(target_path: Path, payload: dict) -> bool:
    """JSON-shaped variant of :func:`cache_populate`.

    Serializes ``payload`` with ``json.dumps`` and atomic-writes the
    result. Same best-effort semantics: any failure logs a stderr
    warning and returns ``False``.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_text(target_path, json.dumps(payload))
        return True
    except (OSError, TypeError, ValueError) as e:
        # Cleanup the .tmp residue if atomic_write_text raised mid-write.
        tmp = target_path.with_suffix(target_path.suffix + ".tmp")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        print(
            f"[cdp-mcp] Warning: cache populate (JSON) failed for "
            f"{target_path}: {e.__class__.__name__}: {e}. Result returned anyway.",
            file=sys.stderr,
        )
        return False


def materialize_cached_artifact(src: Path, dst: Path) -> None:
    """Move a cached artifact into a per-call location.

    Hardlink on POSIX (zero-cost-on-disk) when source and destination
    share a filesystem. Falls back to copy on any ``OSError``
    (cross-filesystem, permission, missing ``os.link``, etc.). On
    Windows where ``os.link`` may not be available or may fail on
    common filesystems, the copy fallback handles it transparently.

    Caller ensures ``dst.parent`` exists. ``dst`` is overwritten if
    present.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except (OSError, AttributeError):
        # Cross-FS or platform-without-hardlink — copy as a fallback.
        shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Per-tier key builders
# ---------------------------------------------------------------------------


def pvoc_cache_key(
    audio_sha256: str,
    operation: str,
    window: int,
    overlap: int,
    cdp_version: str,
) -> str:
    """Cache key for a PVOC anal/synth result.

    Only the CDP binary version matters as a software input — PVOC
    doesn't involve librosa / numpy / scipy.

    ``operation`` is ``"anal"`` or ``"synth"``. ``window`` (analysis
    FFT points, ``pvoc anal -c`` flag) and ``overlap`` (filter overlap
    factor, ``-o`` flag) are explicit so the key discriminates between
    `.ana` files produced at different analysis params — Phase 2 Task
    4 precondition for Task 8's user-facing ``_pvoc.window`` /
    ``_pvoc.overlap`` engine controls. Both values participate in the
    key even for ``"synth"`` (where CDP synth doesn't read them); the
    audio_sha256 of the ``.ana`` already implicitly captures the
    analysis params, so this is at worst no-op and at best
    future-proofs against any CDP-level dependency we don't currently
    know about.
    """
    return _compose_key(
        "pvoc",
        audio_sha256,
        operation,
        str(window),
        str(overlap),
        cdp_version,
    )


def analysis_cache_key(
    audio_sha256: str,
    feature_set: str,
    t_start: float | None,
    t_duration: float | None,
) -> str:
    """Cache key for an analysis scorecard.

    ``feature_set`` is a short string identifying the schema (Phase 1a:
    ``"concise_v1"``). Library versions affecting analysis flow in via
    :func:`_lib_versions_for_tier`.
    """
    return _compose_key(
        "analysis",
        audio_sha256,
        feature_set,
        _format_window(t_start, t_duration),
        _lib_versions_for_tier("analysis"),
    )


def audition_cache_key(ana_sha256: str, cdp_version: str) -> str:
    """Cache key for an audition synth result.

    ``synth_for_audition`` runs ``pvoc synth`` to convert a spectral
    ``.ana`` to a temporary ``.wav`` for ``visualize``/``analyze`` to
    render. Output is a pure function of (.ana bytes, CDP version);
    no Python libraries are involved.
    """
    return _compose_key("audition", ana_sha256, cdp_version)


def visualization_cache_key(
    audio_sha256: str,
    mode: str,
    t_start: float | None,
    t_duration: float | None,
    render_params_discriminator: str,
) -> str:
    """Cache key for a rendered spectrogram PNG.

    ``mode`` is the spectrogram type (Phase 1a: ``"mel"``).
    ``render_params_discriminator`` captures FFT size, hop, dpi, and the
    fig dimensions — currently locked constants in
    :mod:`cdp_mcp.visualization`, future user overrides land in the
    same string.
    """
    return _compose_key(
        "visualization",
        audio_sha256,
        mode,
        _format_window(t_start, t_duration),
        render_params_discriminator,
        _lib_versions_for_tier("visualizations"),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def cache_size_bytes(cache_root: Path) -> dict[str, int]:
    """Per-tier byte count plus a derived total.

    Tiers with no files report ``0``. Unknown subdirectories under the
    cache root are ignored — the dict always contains exactly the known
    tier keys.
    """
    sizes: dict[str, int] = {tier: 0 for tier in _KNOWN_TIERS}
    if not cache_root.exists():
        return sizes
    for tier in _KNOWN_TIERS:
        tier_dir = cache_root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.rglob("*"):
            if p.is_file():
                try:
                    sizes[tier] += p.stat().st_size
                except OSError:
                    continue
    return sizes


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _ensure_tier_dir(cache_root: Path, tier: str) -> Path:
    d = cache_root / tier
    d.mkdir(parents=True, exist_ok=True)
    return d


def _compose_key(*parts: str) -> str:
    """``sha256("\\x00".join(parts))`` — null-separated to prevent
    boundary collisions across adjacent string components.

    Example: ``"ab" + "cdef"`` and ``"abc" + "def"`` would hash the
    same without a separator; with the null byte they don't.
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _lib_versions_for_tier(tier: str) -> str:
    """Compact, deterministic string of the libs that affect ``tier``.

    Reads from the module-level ``_LIB_VERSIONS`` so tests can
    monkeypatch a single entry to simulate a library upgrade.
    """
    names = _TIER_LIBS.get(tier, ())
    return ",".join(f"{name}:{_LIB_VERSIONS[name]}" for name in sorted(names))


def _format_window(t_start: float | None, t_duration: float | None) -> str:
    """Stable string for an optional ``(t_start, t_duration)`` window.

    Floats are formatted with ``repr`` to avoid lossy rounding masking
    cache differences between e.g. 0.1 and 0.10000001.
    """
    s = "None" if t_start is None else repr(float(t_start))
    d = "None" if t_duration is None else repr(float(t_duration))
    return f"start={s}|dur={d}"
