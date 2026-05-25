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


def test_all_five_entries_present(real_index):
    expected = {
        ("blur", "blur"),
        ("modify", "brassage"),
        ("morph", "morph"),
        ("extend", "loop"),
        ("filter", "sweeping"),
    }
    for program, mode in expected:
        assert real_index.get(program, mode) is not None, f"missing {program} {mode}"


def test_categories_sorted_and_unique(real_index):
    assert real_index.categories() == [
        "extend",
        "filter",
        "granular",
        "morph",
        "spectral-time",
    ]


def test_list_entries_by_category(real_index):
    entries = real_index.list_entries(category="filter")
    assert [(e.program, e.mode) for e in entries] == [("filter", "sweeping")]


def test_list_entries_by_domain_spectral(real_index):
    entries = real_index.list_entries(domain="spectral")
    keys = {(e.program, e.mode) for e in entries}
    assert keys == {("blur", "blur"), ("morph", "morph")}


def test_list_entries_filters_compose_and(real_index):
    # No spectral filter entry in Phase 1a.
    assert real_index.list_entries(category="filter", domain="spectral") == []


def test_curated_only_passthrough_includes_all(real_index):
    # All Phase 1a entries are curated, so curated_only=False just returns the
    # same set. The flag's behavior is exercised; the data doesn't (yet)
    # contain uncurated entries to filter out.
    assert len(real_index.list_entries(curated_only=False)) == 5
    assert len(real_index.list_entries(curated_only=True)) == 5


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
        def __init__(self, p):
            self._p = p

        def joinpath(self, *_parts):
            return self  # always return ourselves

        def glob(self, pattern):
            return self._p.glob(pattern)

    def fake_files(_pkg):
        return _FakeTraversable(tmp_path)

    monkeypatch.setattr(loader, "files", fake_files)
    monkeypatch.setattr(loader, "as_file", lambda x: _NoopCtx(tmp_path))

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
