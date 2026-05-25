"""Three-check security boundary for user-supplied CDP command arrays.

This module is the gatekeeper between the LLM and ``run_cdp_command``. Every
:func:`validate_command` call independently runs three checks, collects every
violation, and raises :class:`SecurityError` with the full list. Callers can
return all violations to the LLM in one envelope rather than rejecting one
issue at a time.

The checks:

1. **Binary location** — ``argv[0]`` must be a bare CDP program name or an
   absolute path that lives inside ``$CDP_PATH``. The resolved absolute
   path replaces ``command[0]`` in the returned list.
2. **Shell metacharacters** — any element of ``command[1:]`` containing
   ``;|&$`><()\\n\\r\\0`` is rejected, one ``ErrorEntry`` per offending arg.
3. **Path scope** — any element of ``command[1:]`` that looks like a
   filesystem path must resolve inside the session tree or the CDP cache.

The module is pure validation — no subprocess, no network, only
``Path.resolve()`` for path normalization (which never raises for
non-existent files in modern Python).
"""

from __future__ import annotations

import os
from pathlib import Path

from .schema import ErrorEntry

# Outright denylist of shell metacharacters and control characters. CDP
# arguments legitimately use spaces, dots, hyphens, digits — so an allowlist
# would be either too restrictive or too permissive. This denylist covers
# every realistic command-injection vector while leaving CDP's argument
# space intact.
_REJECTED_CHARS = frozenset(";|&$`><()\n\r\0")

# CDP file extensions used by the path-scope heuristic to decide whether an
# argument deserves a scope check. Derived from CDP's filestxt.htm
# documentation, broken out by category:
_PATH_LIKE_EXTENSIONS = frozenset({
    # Audio (sound files)
    ".wav", ".aif", ".aiff", ".amb",
    # Spectral analysis (PVOC, PVOC-EX)
    ".ana", ".pvx",
    # Envelope: binary .env / .evl, breakpoint .brk
    ".env", ".evl", ".brk",
    # Formant binary, pitch trace binary, transposition data
    ".for", ".frq", ".trn",
    # Tuning, mix file variants
    ".tun", ".mix", ".mmx",
    # Batch, Soundshaper preset data, generic text
    ".bat", ".dat", ".txt",
})


class SecurityError(Exception):
    """Raised when :func:`validate_command` finds at least one violation.

    Carries a list of :class:`~cdp_mcp.schema.ErrorEntry` records so the
    caller can return all violations to the LLM in one envelope.
    """

    def __init__(self, errors: list[ErrorEntry]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} security violation(s)")


def validate_command(
    command: list[str],
    cdp_path: Path,
    session_root: Path,
    cache_root: Path,
) -> list[str]:
    """Run the three security checks and return a validated command.

    Args:
        command: The raw ``argv``-style array from the caller.
        cdp_path: Absolute path to the directory holding CDP binaries.
        session_root: Already-``.resolve()``-d active session root. The
            validator does NOT re-resolve.
        cache_root: Already-``.resolve()``-d CDP cache root. Same caveat.

    Returns:
        A copy of ``command`` with ``argv[0]`` replaced by its absolute,
        resolved path inside ``cdp_path`` (satisfying ``run_cdp_command``'s
        absolute-argv[0] contract).

    Raises:
        SecurityError: with the full list of :class:`ErrorEntry` on any
        violation. All three checks run to completion regardless.
    """
    if not command:
        raise SecurityError(
            [
                ErrorEntry(
                    type="empty_command",
                    message="Command is empty.",
                    fix="Pass at least one element (the CDP program name).",
                )
            ]
        )

    errors: list[ErrorEntry] = []

    resolved_binary, binary_error = _check_binary(command[0], cdp_path)
    if binary_error is not None:
        errors.append(binary_error)

    errors.extend(_check_metacharacters(command[1:]))
    errors.extend(_check_path_scope(command[1:], session_root, cache_root))

    if errors:
        raise SecurityError(errors)

    validated = list(command)
    # binary_error was None, so resolved_binary is guaranteed set.
    assert resolved_binary is not None
    validated[0] = str(resolved_binary)
    return validated


# ---------------------------------------------------------------------------
# Check 1: binary location
# ---------------------------------------------------------------------------


def _check_binary(
    argv0: str,
    cdp_path: Path,
) -> tuple[Path | None, ErrorEntry | None]:
    """Resolve ``argv0`` against ``cdp_path``.

    Returns ``(resolved_path, None)`` on success or
    ``(None, ErrorEntry)`` on failure.
    """
    fix = (
        f"Use a bare CDP program name (e.g. 'blur', 'modify') or an absolute "
        f"path inside $CDP_PATH ({cdp_path})."
    )

    if not isinstance(argv0, str) or not argv0:
        return None, ErrorEntry(
            type="binary_not_in_cdp_path",
            message=f"argv[0] is empty or not a string: {argv0!r}",
            fix=fix,
        )

    has_separator = "/" in argv0 or "\\" in argv0
    candidate_path = Path(argv0)

    if not has_separator:
        # Bare name — look it up inside cdp_path.
        candidate = cdp_path / argv0
    elif candidate_path.is_absolute():
        # Absolute path — must live inside cdp_path.
        candidate = candidate_path
    else:
        # Relative with directory component (../bin/foo, ./blur) — malformed.
        return None, ErrorEntry(
            type="binary_not_in_cdp_path",
            message=(
                f"argv[0]={argv0!r} is a relative path with a directory "
                "component; only bare names or absolute paths inside $CDP_PATH "
                "are allowed."
            ),
            fix=fix,
        )

    if not candidate.exists():
        return None, ErrorEntry(
            type="binary_not_in_cdp_path",
            message=f"argv[0]={argv0!r}: file not found at {candidate}",
            fix=fix,
        )

    resolved = candidate.resolve()
    if not resolved.is_relative_to(cdp_path):
        return None, ErrorEntry(
            type="binary_not_in_cdp_path",
            message=(
                f"argv[0]={argv0!r} resolves to {resolved}, which is outside "
                f"$CDP_PATH ({cdp_path})."
            ),
            fix=fix,
        )

    if not os.access(resolved, os.X_OK):
        return None, ErrorEntry(
            type="binary_not_in_cdp_path",
            message=f"argv[0]={argv0!r} ({resolved}) is not executable.",
            fix=fix,
        )

    return resolved, None


# ---------------------------------------------------------------------------
# Check 2: shell metacharacters
# ---------------------------------------------------------------------------


def _check_metacharacters(rest: list[str]) -> list[ErrorEntry]:
    """One ErrorEntry per arg that contains any rejected character."""
    errors: list[ErrorEntry] = []
    for i, arg in enumerate(rest, start=1):  # index 1 = first arg after argv[0]
        if not isinstance(arg, str):
            continue
        found = sorted({c for c in arg if c in _REJECTED_CHARS})
        if not found:
            continue
        rendered = ", ".join(repr(c) for c in found)
        errors.append(
            ErrorEntry(
                type="metacharacter_rejected",
                message=(
                    f"Argument at index {i} contains rejected character(s): "
                    f"{rendered}"
                ),
                fix=(
                    "Remove the listed character(s) from the argument. "
                    "cdp-mcp does not invoke a shell, so these characters "
                    "cannot serve any legitimate purpose in CDP arguments."
                ),
            )
        )
    return errors


# ---------------------------------------------------------------------------
# Check 3: path scope
# ---------------------------------------------------------------------------


def _is_path_like(arg: str) -> bool:
    if "/" in arg or "\\" in arg:
        return True
    if arg.startswith("~"):
        return True
    return Path(arg).suffix.lower() in _PATH_LIKE_EXTENSIONS


def _check_path_scope(
    rest: list[str],
    session_root: Path,
    cache_root: Path,
) -> list[ErrorEntry]:
    """One ErrorEntry per path-like arg that resolves outside the allowed roots."""
    errors: list[ErrorEntry] = []
    fix = (
        f"Files must live inside the active session tree ({session_root}) or "
        f"the CDP cache ({cache_root}). Use a session-relative path or move "
        "the file into the session."
    )
    for i, arg in enumerate(rest, start=1):
        if not isinstance(arg, str) or not _is_path_like(arg):
            continue
        candidate = Path(arg).expanduser()
        if not candidate.is_absolute():
            # CDP runs with cwd=session.root, so relative paths resolve there.
            candidate = session_root / candidate
        # .resolve() normalizes .., follows existing symlinks, and does NOT
        # raise for non-existent paths in modern Python.
        resolved = candidate.resolve()
        if resolved.is_relative_to(session_root) or resolved.is_relative_to(cache_root):
            continue
        errors.append(
            ErrorEntry(
                type="path_outside_session",
                message=(
                    f"Argument at index {i} ({arg!r}) resolves to {resolved}, "
                    "which is outside the session and cache."
                ),
                fix=fix,
            )
        )
    return errors
