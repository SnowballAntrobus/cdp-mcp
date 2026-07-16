"""Unit tests for cdp_mcp.knowledge.loader.KnowledgeIndex."""

from __future__ import annotations

import json

import pytest

from cdp_mcp.knowledge.loader import KnowledgeIndex


@pytest.fixture(scope="module")
def real_index():
    return KnowledgeIndex.load()


# ---------------------------------------------------------------------------
# Real packaged index
# ---------------------------------------------------------------------------


def test_all_curated_entries_present(real_index):
    expected = {
        ("blur", "blur"),
        ("modify", "brassage"),
        ("morph", "morph"),
        ("extend", "loop"),
        ("filter", "sweeping"),
        ("combine", "cross"),
    }
    for program, mode in expected:
        assert real_index.get(program, mode) is not None, f"missing {program} {mode}"


def test_categories_sorted_and_unique(real_index):
    assert real_index.categories() == [
        "distort",
        "edit",
        "envelope",
        "extend",
        "filter",
        "granular",
        "mix",
        "modify",
        "morph",
        "spectral-frequency",
        "spectral-time",
        "synthesis",
        "texture",
        "uncurated",
    ]


def test_list_entries_by_category(real_index):
    entries = real_index.list_entries(category="filter")
    # bank appears once per curated submode since Phase 5 wave 3.
    assert [(e.program, e.mode, e.submode) for e in entries] == [
        ("filter", "bank", 1), ("filter", "bank", 5), ("filter", "bank", 6),
        ("filter", "lohi", 1), ("filter", "sweeping", 2),
    ]


def test_list_entries_by_domain_spectral(real_index):
    entries = real_index.list_entries(domain="spectral")
    keys = {(e.program, e.mode) for e in entries}
    assert keys == {
        ("blur", "avrg"), ("blur", "blur"), ("blur", "drunk"),
        ("blur", "scatter"), ("combine", "cross"), ("combine", "diff"),
        ("blur", "spread"), ("blur", "suppress"),
        ("combine", "interleave"), ("combine", "max"),
        ("analjoin", "join"), ("formants", "get"), ("formants", "put"),
        ("formants", "vocode"), ("pitch", "tune"), ("spec", "grab"),
        ("strange", "shift"),
        ("focus", "accu"), ("focus", "exag"), ("focus", "fold"),
        ("focus", "step"), ("hilite", "trace"),
        ("morph", "bridge"), ("morph", "glide"), ("morph", "morph"), ("spec", "magnify"),
        ("specfnu", "specfnu"), ("strange", "glis"), ("strange", "invert"),
        ("stretch", "spectrum"), ("stretch", "time"),
        # --- Phase 5 wave 4 (tranche 10 ST-covered singles) ---
        ("blur", "chorus"), ("blur", "noise"), ("focus", "focus"),
        ("spec", "cut"), ("spec", "gain"), ("spectstr", "stretch"),
        ("strange", "waver"), ("repitch", "transpose"),
            # --- Wave 3 (tranche 17) ---
        ("spectrum", "fixed"),
    }


def test_list_entries_filters_compose_and(real_index):
    # No spectral filter entry in Phase 1a.
    assert real_index.list_entries(category="filter", domain="spectral") == []


def test_curated_only_passthrough_includes_all(real_index):
    # All curated entries are curated, so curated_only=False just returns the
    # same set. The flag's behavior is exercised; the data doesn't (yet)
    # contain uncurated entries to filter out.
    assert len(real_index.list_entries(curated_only=False)) == 374
    assert len(real_index.list_entries(curated_only=True)) == 248


def test_get_returns_none_for_missing(real_index):
    assert real_index.get("nonexistent", "mode") is None


# ---------------------------------------------------------------------------
# Malformed-entry handling
# ---------------------------------------------------------------------------


def test_malformed_entry_warns_and_skips(tmp_path, monkeypatch, capsys):
    """A bad JSON file next to a good one logs a warning and is skipped;
    the loader still returns a populated index for the good entries.

    We monkeypatch the loader's path resolver to point at our tmp_path.
    """
    # Write one good and one bad entry into tmp_path.
    good = {
        "program": "synth",
        "mode": "test",
        "category": "synthesis",
        "domain": "time",
        "input_arity": 0,
        "channel_constraint": "any",
        "input_format": ".wav",
        "output_format": ".wav",
        "duration_model": {"kind": "static"},
        "description": "x",
        "musical_use": "x",
        "parameters": {},
    }
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")

    # Patch the loader's importlib.resources call so it scans our tmp_path
    # instead of the packaged data directory. We replace the ``files()``
    # symbol bound inside the loader module.
    from cdp_mcp.knowledge import loader

    class _FakeTraversable:
        def __init__(self, p, live=True):
            self._p = p
            self._live = live

        def joinpath(self, *parts):
            # Only the curated data dir maps to tmp_path; the uncurated
            # dir (Phase 3) resolves to a dead traversable so the fake
            # doesn't serve every entry twice.
            live = bool(parts) and parts[-1] == "data"
            return _FakeTraversable(self._p, live=live)

        def glob(self, pattern):
            return self._p.glob(pattern) if self._live else iter(())

    def fake_files(_pkg):
        return _FakeTraversable(tmp_path)

    monkeypatch.setattr(loader, "files", fake_files)
    monkeypatch.setattr(
        loader,
        "as_file",
        lambda x: _NoopCtx(
            tmp_path if getattr(x, "_live", True)
            else tmp_path / "does_not_exist"
        ),
    )

    index = loader.KnowledgeIndex.load()

    # The good entry loaded; the bad one was skipped with a warning.
    assert index.get("synth", "test") is not None
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "bad.json" in err
    assert "Loaded 1 knowledge entries" in err


class _NoopCtx:
    """Drop-in for importlib.resources.as_file when we already have a path."""

    def __init__(self, p):
        self._p = p

    def __enter__(self):
        return self._p

    def __exit__(self, *_args):
        return False
