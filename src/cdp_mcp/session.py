"""Session abstraction and filesystem layout.

A *session* is a named directory under the sessions root (``~/cdp_sessions/``
by default, or ``$CDP_MCP_SESSIONS_ROOT``) that holds a user's working
materials for one piece or experiment. Every CDP operation that produces or
consumes files (Task 4+) lives inside the active session.

Phase 1a provides:

- a :class:`SessionManager` that creates new sessions or switches between
  existing ones, with strict name validation;
- a :class:`SessionConfig` written to ``config.json`` on first creation;
- the canonical subdirectory layout (``inputs/``, ``graphs/``, ``templates/``,
  ``envelopes/``, ``tmp/``) plus empty ``tags.json`` and a stub ``journal.md``.

No tool registration here — see :mod:`cdp_mcp.tools.workspace`.
"""

from __future__ import annotations

import platform
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from . import __version__ as _cdp_mcp_version
from .config import CDPConfig
from .utils import atomic_write_text

# Session names: leading alphanumeric, then alphanumeric / underscore /
# hyphen / dot. Max 64 chars. Rejects path traversal, whitespace, slashes,
# and leading dot/hyphen names that would look like hidden files or flags.
_SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")

_SUBDIRS = ("inputs", "graphs", "templates", "envelopes", "tmp")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SessionNameError(Exception):
    """Raised when a session name fails validation."""


class SessionNotActiveError(Exception):
    """Raised when an operation requires an active session but none is set."""


class SessionInitError(Exception):
    """Raised when creating or writing a session directory fails."""


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


class SessionConfig(BaseModel):
    """On-disk session metadata, written once at session creation."""

    session_name: str
    created_at: datetime  # ISO 8601, UTC
    cdp_version: str  # "unknown" if CDP wasn't configured at creation time
    python_version: str
    cdp_mcp_version: str
    # User-adjustable settings persisted by set_config() (Phase 4).
    # Absent from pre-Phase-4 config.json files; defaults to {} on load.
    user_config: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """In-memory view of an active session.

    All ``<dir>_dir`` properties are computed from ``root`` rather than
    stored, so they stay consistent if the root is ever resolved differently.
    """

    name: str
    root: Path
    config: SessionConfig

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def graphs_dir(self) -> Path:
        return self.root / "graphs"

    @property
    def templates_dir(self) -> Path:
        return self.root / "templates"

    @property
    def envelopes_dir(self) -> Path:
        return self.root / "envelopes"

    @property
    def tmp_dir(self) -> Path:
        return self.root / "tmp"

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def tags_path(self) -> Path:
        return self.root / "tags.json"

    @property
    def journal_path(self) -> Path:
        return self.root / "journal.md"


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Owns the on-disk sessions root and tracks the currently active session.

    Constructed once at server startup (see :mod:`cdp_mcp.server`). The
    ``cdp_config_provider`` indirection is so tests can inject a fake CDP
    config without needing the real binaries on disk.
    """

    def __init__(
        self,
        sessions_root: Path,
        cdp_config_provider: Callable[[], CDPConfig | None],
    ) -> None:
        self.sessions_root = sessions_root
        self._cdp_config_provider = cdp_config_provider
        self._active: Session | None = None
        # __init__ touches the filesystem ONLY to create the sessions root.
        # Per-session directories are created lazily in set_active.
        sessions_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active(self, name: str) -> tuple[Session, bool]:
        """Activate the named session, creating it on disk if absent.

        Returns ``(session, created)`` where ``created`` is ``True`` only
        when the session's ``config.json`` did not exist before this call.

        Raises:
            SessionNameError: if ``name`` fails validation.
            SessionInitError: if the directory or config write fails.
        """
        _validate_name(name)
        session_root = self.sessions_root / name
        config_path = session_root / "config.json"

        existed = config_path.exists()
        if existed:
            config = self._load_existing(config_path)
        else:
            try:
                self._create_layout(session_root)
                config = self._build_fresh_config(name)
                atomic_write_text(
                    config_path,
                    config.model_dump_json(indent=2) + "\n",
                )
                # journal.md and tags.json are sibling artifacts written at
                # creation time; not part of the SessionConfig contract.
                atomic_write_text(
                    session_root / "tags.json", "{}\n"
                )
                atomic_write_text(
                    session_root / "journal.md",
                    _initial_journal(name, config.created_at),
                )
            except OSError as e:
                raise SessionInitError(
                    f"Failed to create session {name!r} at {session_root}: {e}"
                ) from e

        session = Session(name=name, root=session_root, config=config)
        self._active = session
        return session, not existed

    @property
    def active(self) -> Session | None:
        return self._active

    def require_active(self) -> Session:
        """Return the active session or raise :class:`SessionNotActiveError`."""
        if self._active is None:
            raise SessionNotActiveError(
                "No session is active. Call set_session(name) first."
            )
        return self._active

    def list_sessions(self) -> list[str]:
        """Sorted list of session directory names on disk. Ignores files."""
        if not self.sessions_root.exists():
            return []
        return sorted(
            p.name for p in self.sessions_root.iterdir() if p.is_dir()
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_fresh_config(self, name: str) -> SessionConfig:
        cdp = self._cdp_config_provider()
        cdp_version = cdp.version if cdp is not None else "unknown"
        return SessionConfig(
            session_name=name,
            created_at=datetime.now(timezone.utc),
            cdp_version=cdp_version,
            python_version=platform.python_version(),
            cdp_mcp_version=_cdp_mcp_version,
        )

    @staticmethod
    def _load_existing(config_path: Path) -> SessionConfig:
        return SessionConfig.model_validate_json(
            config_path.read_text(encoding="utf-8")
        )

    @staticmethod
    def _create_layout(session_root: Path) -> None:
        session_root.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (session_root / sub).mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _SESSION_NAME_RE.fullmatch(name):
        raise SessionNameError(
            f"Invalid session name {name!r}: must match "
            f"{_SESSION_NAME_RE.pattern}"
        )


def _initial_journal(name: str, created_at: datetime) -> str:
    return (
        f"# Session: {name}\n"
        f"\n"
        f"Created: {created_at.isoformat()}\n"
        f"\n"
    )


def cdp_version_mismatch_warning(
    session: Session,
    current_cdp_config: CDPConfig | None,
) -> str | None:
    """Return a warning message if the session's recorded CDP version
    differs from the currently detected one.

    Returns ``None`` when no comparison applies: no CDP currently
    configured, either side is the ``"unknown"`` sentinel (legacy
    sessions, custom install layouts the detector couldn't parse, or
    CDP unavailable at session creation), or exact match.

    Pure over its inputs; never raises.
    """
    if current_cdp_config is None:
        return None
    recorded = session.config.cdp_version
    current = current_cdp_config.version
    if recorded == "unknown" or current == "unknown":
        return None
    if recorded == current:
        return None
    return (
        f"CDP version mismatch: session {session.name!r} was created "
        f"with {recorded!r}; current install is {current!r}. "
        f"Reproducibility may be affected — older cached artifacts or "
        f"curated knowledge entries may not match exactly. Consider "
        f"regenerating outputs you intend to use further. Proceeding "
        f"anyway."
    )
