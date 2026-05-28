"""Tests for the global derivative-artifact cache module."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cdp_mcp import cache as cache_mod
from cdp_mcp.cache import (
    _LIB_VERSIONS,
    _compose_key,
    _format_window,
    _lib_versions_for_tier,
    analysis_cache_key,
    audition_cache_key,
    cache_lookup,
    cache_populate,
    cache_populate_json,
    cache_size_bytes,
    materialize_cached_artifact,
    pvoc_cache_key,
    visualization_cache_key,
)

# ---------------------------------------------------------------------------
# Key composition
# ---------------------------------------------------------------------------


def test_compose_key_separator_prevents_boundary_collision():
    """``"abc" + "def"`` must not hash the same as ``"ab" + "cdef"``.

    The null-byte separator inside ``_compose_key`` is what guarantees
    this — without it, both hash the same string ``"abcdef"``.
    """
    assert _compose_key("abc", "def") != _compose_key("ab", "cdef")


def test_compose_key_deterministic():
    assert _compose_key("a", "b", "c") == _compose_key("a", "b", "c")


def test_format_window_distinguishes_none_from_zero():
    """``t_start=None`` and ``t_start=0.0`` shouldn't share a cache slot."""
    assert _format_window(None, None) != _format_window(0.0, 0.0)


# ---------------------------------------------------------------------------
# Per-tier key builders
# ---------------------------------------------------------------------------


def test_pvoc_cache_key_deterministic():
    a = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=3, cdp_version="r8")
    b = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=3, cdp_version="r8")
    assert a == b


def test_pvoc_cache_key_sensitive_to_operation():
    """anal and synth share audio + version + window + overlap but
    must produce distinct keys."""
    a = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=3, cdp_version="r8")
    b = pvoc_cache_key("audio_sha", "synth", window=1024, overlap=3, cdp_version="r8")
    assert a != b


def test_pvoc_cache_key_sensitive_to_cdp_version():
    a = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=3, cdp_version="r8")
    b = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=3, cdp_version="r9")
    assert a != b


def test_pvoc_cache_key_sensitive_to_audio():
    a = pvoc_cache_key("sha_a", "anal", window=1024, overlap=3, cdp_version="r8")
    b = pvoc_cache_key("sha_b", "anal", window=1024, overlap=3, cdp_version="r8")
    assert a != b


def test_pvoc_cache_key_sensitive_to_window():
    """Phase 2 Task 4: changing the analysis window must invalidate the
    cached .ana — otherwise Task 8's user-controllable ``_pvoc.window``
    would silently serve a stale entry produced at the previous window."""
    a = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=3, cdp_version="r8")
    b = pvoc_cache_key("audio_sha", "anal", window=2048, overlap=3, cdp_version="r8")
    assert a != b


def test_pvoc_cache_key_sensitive_to_overlap():
    """Phase 2 Task 4: same as the window case for the overlap factor."""
    a = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=3, cdp_version="r8")
    b = pvoc_cache_key("audio_sha", "anal", window=1024, overlap=4, cdp_version="r8")
    assert a != b


def test_pvoc_cache_key_invariant_when_defaults_match():
    """Two key calls using the pinned default constants produce the
    same key. Trips a test failure if the defaults ever silently shift
    (which would invalidate every existing PVOC cache entry in one go)."""
    from cdp_mcp.pvoc import _DEFAULT_PVOC_OVERLAP, _DEFAULT_PVOC_WINDOW
    a = pvoc_cache_key(
        "audio_sha", "anal",
        window=_DEFAULT_PVOC_WINDOW,
        overlap=_DEFAULT_PVOC_OVERLAP,
        cdp_version="r8",
    )
    b = pvoc_cache_key(
        "audio_sha", "anal",
        window=_DEFAULT_PVOC_WINDOW,
        overlap=_DEFAULT_PVOC_OVERLAP,
        cdp_version="r8",
    )
    assert a == b


def test_analysis_cache_key_includes_librosa_version(monkeypatch):
    """A simulated librosa version bump invalidates analysis cache entries.

    This is the load-bearing guarantee: when users upgrade librosa, old
    scorecards mustn't be served from cache because the numbers may shift.
    """
    monkeypatch.setitem(_LIB_VERSIONS, "librosa", "99.99")
    a = analysis_cache_key("audio_sha", "concise_v1", None, None)
    monkeypatch.setitem(_LIB_VERSIONS, "librosa", "0.10")
    b = analysis_cache_key("audio_sha", "concise_v1", None, None)
    assert a != b


def test_analysis_cache_key_sensitive_to_window():
    a = analysis_cache_key("audio_sha", "concise_v1", None, None)
    b = analysis_cache_key("audio_sha", "concise_v1", 1.0, 2.0)
    assert a != b


def test_visualization_cache_key_ignores_pyloudnorm(monkeypatch):
    """pyloudnorm affects analysis (loudness) but not the spectrogram —
    bumping its version mustn't invalidate visualization entries."""
    monkeypatch.setitem(_LIB_VERSIONS, "pyloudnorm", "0.1.0")
    a = visualization_cache_key("audio_sha", "mel", None, None, "rp")
    monkeypatch.setitem(_LIB_VERSIONS, "pyloudnorm", "0.2.0")
    b = visualization_cache_key("audio_sha", "mel", None, None, "rp")
    assert a == b


def test_visualization_cache_key_sensitive_to_render_params():
    a = visualization_cache_key("audio_sha", "mel", None, None, "rp_a")
    b = visualization_cache_key("audio_sha", "mel", None, None, "rp_b")
    assert a != b


def test_audition_cache_key_deterministic():
    a = audition_cache_key("ana_sha", "r8")
    b = audition_cache_key("ana_sha", "r8")
    assert a == b


def test_audition_cache_key_sensitive_to_ana_sha():
    a = audition_cache_key("sha_one", "r8")
    b = audition_cache_key("sha_two", "r8")
    assert a != b


def test_audition_cache_key_sensitive_to_cdp_version():
    a = audition_cache_key("ana_sha", "r8")
    b = audition_cache_key("ana_sha", "r9")
    assert a != b


def test_audition_cache_key_distinct_from_other_tiers():
    """Same audio sha through different per-tier builders yields
    different keys — the tier-prefix component prevents accidental
    cross-tier collisions (e.g., same .ana hash showing up as both a
    pvoc-synth key and an audition key would otherwise collide on the
    bytes content)."""
    ana_sha = "abc"
    pvoc_k = pvoc_cache_key(ana_sha, "synth", window=1024, overlap=3, cdp_version="r8")
    audition_k = audition_cache_key(ana_sha, "r8")
    assert pvoc_k != audition_k


def test_lib_versions_for_tier_excludes_irrelevant_libs():
    """visualizations doesn't depend on pyloudnorm or scipy."""
    s = _lib_versions_for_tier("visualizations")
    assert "pyloudnorm" not in s
    assert "scipy" not in s
    assert "librosa" in s
    assert "matplotlib" in s


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_cache_lookup_miss_returns_target_path(tmp_path):
    result = cache_lookup(tmp_path, "pvoc", "deadbeef", ".ana")
    assert result.hit is False
    assert result.path == tmp_path / "pvoc" / "deadbeef.ana"
    assert not result.path.exists()
    # Tier dir was created so callers can write to the target.
    assert result.path.parent.is_dir()


def test_cache_lookup_hit_returns_existing_path(tmp_path):
    tier_dir = tmp_path / "pvoc"
    tier_dir.mkdir()
    (tier_dir / "deadbeef.ana").write_bytes(b"fake ana data")
    result = cache_lookup(tmp_path, "pvoc", "deadbeef", ".ana")
    assert result.hit is True
    assert result.path.read_bytes() == b"fake ana data"


# ---------------------------------------------------------------------------
# Populate
# ---------------------------------------------------------------------------


def test_cache_populate_atomic(tmp_path):
    source = tmp_path / "src.bin"
    source.write_bytes(b"hello-cached")
    target = tmp_path / "pvoc" / "key.ana"
    assert cache_populate(target, source) is True
    assert target.read_bytes() == b"hello-cached"
    # No .tmp residue left behind.
    assert not (tmp_path / "pvoc" / "key.ana.tmp").exists()


def test_cache_populate_json_writes_json(tmp_path):
    target = tmp_path / "analysis" / "key.json"
    payload = {"scorecard": {"duration_s": 1.5}, "warnings": []}
    assert cache_populate_json(target, payload) is True
    # Round-trip.
    import json
    assert json.loads(target.read_text()) == payload


def test_cache_populate_failure_returns_false_with_warning(tmp_path, capsys):
    """Permission failure → False return + stderr warning, no raise.

    Uses a read-only directory rather than ``/proc`` (which doesn't
    exist on macOS).
    """
    if os.geteuid() == 0:
        pytest.skip("Root can write through 0o500 perms — skip.")
    source = tmp_path / "src.bin"
    source.write_bytes(b"hello")
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)  # readable + executable, NOT writable
    try:
        target = readonly / "key.ana"
        ok = cache_populate(target, source)
        assert ok is False
        err = capsys.readouterr().err
        assert "cache populate failed" in err.lower()
    finally:
        # Restore so pytest can clean up tmp_path.
        readonly.chmod(0o700)


# ---------------------------------------------------------------------------
# Materialize
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform.startswith("win"), reason="hardlink test is POSIX-only"
)
def test_materialize_hardlinks_on_posix(tmp_path):
    src = tmp_path / "cache" / "x.ana"
    src.parent.mkdir()
    src.write_bytes(b"shared data")
    dst = tmp_path / "graph" / "n1.ana"
    dst.parent.mkdir()
    materialize_cached_artifact(src, dst)
    assert dst.exists()
    # Same inode → hardlink (not copy).
    assert src.stat().st_ino == dst.stat().st_ino


def test_materialize_falls_back_to_copy_when_link_fails(tmp_path):
    """If ``os.link`` raises (cross-FS in production), shutil.copy2 kicks in.

    Simulated by patching ``os.link`` to raise.
    """
    src = tmp_path / "cache" / "x.ana"
    src.parent.mkdir()
    src.write_bytes(b"shared data")
    dst = tmp_path / "graph" / "n1.ana"
    dst.parent.mkdir()
    with patch("cdp_mcp.cache.os.link", side_effect=OSError("simulated cross-FS")):
        materialize_cached_artifact(src, dst)
    assert dst.exists()
    assert dst.read_bytes() == b"shared data"
    # Different inode → copy, not hardlink.
    assert src.stat().st_ino != dst.stat().st_ino


def test_materialize_overwrites_existing_dst(tmp_path):
    """A stale file at ``dst`` (left over from a prior cache attempt) is
    replaced. Otherwise ``os.link`` would raise FileExistsError."""
    src = tmp_path / "cache" / "x.ana"
    src.parent.mkdir()
    src.write_bytes(b"new content")
    dst = tmp_path / "graph" / "n1.ana"
    dst.parent.mkdir()
    dst.write_bytes(b"stale content")
    materialize_cached_artifact(src, dst)
    assert dst.read_bytes() == b"new content"


# ---------------------------------------------------------------------------
# Size reporting
# ---------------------------------------------------------------------------


def test_cache_size_bytes_empty(tmp_path):
    sizes = cache_size_bytes(tmp_path)
    assert sizes == {
        "pvoc": 0, "analysis": 0, "visualizations": 0, "audition": 0,
    }


def test_cache_size_bytes_counts_files(tmp_path):
    (tmp_path / "pvoc").mkdir()
    (tmp_path / "pvoc" / "a.ana").write_bytes(b"x" * 100)
    (tmp_path / "pvoc" / "b.ana").write_bytes(b"x" * 200)
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "a.json").write_text("x" * 50)
    sizes = cache_size_bytes(tmp_path)
    assert sizes["pvoc"] == 300
    assert sizes["analysis"] == 50
    assert sizes["visualizations"] == 0
    assert sizes["audition"] == 0


def test_cache_size_bytes_ignores_unknown_tiers(tmp_path):
    """An unknown subdir under cache_root shouldn't contribute to totals."""
    (tmp_path / "rogue").mkdir()
    (tmp_path / "rogue" / "x").write_bytes(b"x" * 10_000)
    sizes = cache_size_bytes(tmp_path)
    # No "rogue" key, no contribution to known tiers.
    assert "rogue" not in sizes
    assert sum(sizes.values()) == 0


def test_cache_size_bytes_nonexistent_root_returns_zeros(tmp_path):
    """Calling on a path that doesn't exist yet returns the zero dict."""
    sizes = cache_size_bytes(tmp_path / "does-not-exist")
    assert sizes == {
        "pvoc": 0, "analysis": 0, "visualizations": 0, "audition": 0,
    }


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------


def test_lib_versions_populated():
    """At least librosa + numpy + matplotlib should be detectable in dev."""
    assert _LIB_VERSIONS["librosa"] != "unknown"
    assert _LIB_VERSIONS["numpy"] != "unknown"
    assert _LIB_VERSIONS["matplotlib"] != "unknown"


def test_known_tiers_constant_includes_audition():
    """Task 11 (audition cache) lands in the same tier registry; declare
    it from day one so describe_workspace's cache block is stable."""
    assert "audition" in cache_mod._KNOWN_TIERS


# ---------------------------------------------------------------------------
# Path object compatibility
# ---------------------------------------------------------------------------


def test_cache_lookup_accepts_pathlib_path(tmp_path):
    """``cache_lookup`` must take a ``Path``, not just a string."""
    assert isinstance(tmp_path, Path)
    result = cache_lookup(tmp_path, "pvoc", "key", ".ana")
    assert isinstance(result.path, Path)
