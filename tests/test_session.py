"""Unit tests for cdp_mcp.session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdp_mcp.config import CDPConfig
from cdp_mcp.session import (
    Session,
    SessionConfig,
    SessionManager,
    SessionNameError,
    SessionNotActiveError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_cdp() -> CDPConfig:
    return CDPConfig(cdp_path=Path("/tmp/fake"), version="8.0.1-fake", detected_binaries=["blur"])


@pytest.fixture
def manager_with_cdp(tmp_path):
    return SessionManager(tmp_path, lambda: _fake_cdp())


@pytest.fixture
def manager_no_cdp(tmp_path):
    return SessionManager(tmp_path, lambda: None)


# ---------------------------------------------------------------------------
# __init__ filesystem behavior
# ---------------------------------------------------------------------------


def test_manager_init_creates_sessions_root(tmp_path):
    root = tmp_path / "nested" / "sessions"
    assert not root.exists()
    SessionManager(root, lambda: None)
    assert root.is_dir()


# ---------------------------------------------------------------------------
# set_active — happy path
# ---------------------------------------------------------------------------


def test_set_active_creates_subdirectories(manager_with_cdp, tmp_path):
    session, created = manager_with_cdp.set_active("frog_v1")
    assert created is True
    assert isinstance(session, Session)
    for sub in ("inputs", "graphs", "templates", "envelopes", "tmp"):
        assert (tmp_path / "frog_v1" / sub).is_dir()


def test_set_active_writes_round_trippable_config(manager_with_cdp, tmp_path):
    session, _ = manager_with_cdp.set_active("frog_v1")
    raw = session.config_path.read_text(encoding="utf-8")
    reloaded = SessionConfig.model_validate_json(raw)
    assert reloaded.session_name == "frog_v1"
    assert reloaded.cdp_version == "8.0.1-fake"
    # Datetime round-trips through ISO 8601.
    assert reloaded.created_at == session.config.created_at


def test_set_active_writes_empty_tags_json(manager_with_cdp):
    session, _ = manager_with_cdp.set_active("frog_v1")
    contents = session.tags_path.read_text(encoding="utf-8")
    assert contents == "{}\n"
    # And it parses as JSON for sanity.
    assert json.loads(contents) == {}


def test_set_active_writes_journal_with_header(manager_with_cdp):
    session, _ = manager_with_cdp.set_active("frog_v1")
    journal = session.journal_path.read_text(encoding="utf-8")
    assert journal.startswith("# Session: frog_v1\n")
    assert "Created:" in journal


# ---------------------------------------------------------------------------
# set_active — reload behavior
# ---------------------------------------------------------------------------


def test_set_active_reload_preserves_existing_config(manager_with_cdp):
    session1, created1 = manager_with_cdp.set_active("frog_v1")
    assert created1 is True
    original_config_text = session1.config_path.read_text(encoding="utf-8")

    session2, created2 = manager_with_cdp.set_active("frog_v1")
    assert created2 is False
    assert session2.config_path.read_text(encoding="utf-8") == original_config_text
    assert session2.config.created_at == session1.config.created_at


def test_switching_sessions_leaves_previous_untouched(manager_with_cdp):
    a, _ = manager_with_cdp.set_active("alpha")
    a_config_before = a.config_path.read_text(encoding="utf-8")
    a_journal_before = a.journal_path.read_text(encoding="utf-8")

    b, _ = manager_with_cdp.set_active("beta")
    assert manager_with_cdp.active.name == "beta"
    # alpha's files unchanged
    assert a.config_path.read_text(encoding="utf-8") == a_config_before
    assert a.journal_path.read_text(encoding="utf-8") == a_journal_before
    # beta is a sibling on disk
    assert b.root.parent == a.root.parent


# ---------------------------------------------------------------------------
# set_active — name validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "foo bar",        # whitespace
        "../escape",      # path traversal
        ".",              # current dir
        ".hidden",        # leading dot
        "-leading-dash",  # leading dash
        "a" * 65,         # too long
        "with/slash",     # slash
    ],
)
def test_set_active_rejects_invalid_names(manager_with_cdp, bad_name):
    with pytest.raises(SessionNameError):
        manager_with_cdp.set_active(bad_name)


def test_set_active_accepts_max_length_name(manager_with_cdp):
    name = "a" + "b" * 63  # 64 chars total
    session, _ = manager_with_cdp.set_active(name)
    assert session.name == name


# ---------------------------------------------------------------------------
# require_active
# ---------------------------------------------------------------------------


def test_require_active_raises_when_no_session(manager_with_cdp):
    with pytest.raises(SessionNotActiveError):
        manager_with_cdp.require_active()


def test_require_active_returns_after_set(manager_with_cdp):
    session, _ = manager_with_cdp.set_active("x1")
    assert manager_with_cdp.require_active() is session


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def test_list_sessions_sorted_and_dirs_only(manager_with_cdp, tmp_path):
    manager_with_cdp.set_active("zeta")
    manager_with_cdp.set_active("alpha")
    # Drop a stray file in the sessions root — it should be ignored.
    (tmp_path / "not-a-session.txt").write_text("hi")
    assert manager_with_cdp.list_sessions() == ["alpha", "zeta"]


# ---------------------------------------------------------------------------
# CDP version capture
# ---------------------------------------------------------------------------


def test_cdp_version_unknown_when_provider_returns_none(manager_no_cdp):
    session, _ = manager_no_cdp.set_active("nocdp")
    assert session.config.cdp_version == "unknown"


def test_cdp_version_taken_from_provider(manager_with_cdp):
    session, _ = manager_with_cdp.set_active("withcdp")
    assert session.config.cdp_version == "8.0.1-fake"


# ---------------------------------------------------------------------------
# SessionInitError
# ---------------------------------------------------------------------------


def test_session_init_error_when_root_is_unwritable(tmp_path):
    # Make the sessions root a regular file so subdirectory creation fails.
    blocker = tmp_path / "blocked_root"
    blocker.write_text("not a dir")
    # SessionManager.__init__ will call mkdir(parents=True, exist_ok=True);
    # if `blocker` is a file, that raises FileExistsError immediately.
    with pytest.raises((FileExistsError, OSError)):
        SessionManager(blocker, lambda: None)
