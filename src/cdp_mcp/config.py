"""CDP install detection.

Resolves the ``CDP_PATH`` environment variable, sanity-checks that it points at
a real CDP binary directory, and best-effort captures the CDP version string.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel

# Canonical CDP programs we expect to find inside ``CDP_PATH``. If none of these
# are present we assume the path is wrong rather than a CDP install we don't
# recognise. The list is intentionally short — we want a clear positive signal,
# not exhaustive coverage.
_CANONICAL_BINARIES = ("housekeep", "blur", "modify", "pvoc")

# Soft cap on how many detected binaries we record on the config object. Used
# only for the startup log line; not a correctness constraint.
_MAX_DETECTED_BINARIES = 32

_VERSION_PROBE_TIMEOUT_SECONDS = 5

# Matches canonical CDP release-naming pattern (cdpr8, cdp-r8, CDP_R8,
# cdpr8.1, etc.). Captured group becomes the version label after an "r"
# prefix. Stock CDP r8 has no `cdp` binary, so the version label has to
# come from the install directory name in practice.
_VERSION_PATH_RE = re.compile(
    r"^cdp[_-]?r?(\d+(?:\.[\w.]+)?)",
    re.IGNORECASE,
)


class CDPConfigError(Exception):
    """Raised when CDP_PATH is missing or does not look like a CDP install."""


class CDPConfig(BaseModel):
    """Validated CDP installation info."""

    cdp_path: Path
    version: str
    detected_binaries: list[str]


def detect_cdp() -> CDPConfig:
    """Resolve and validate the CDP install pointed at by ``$CDP_PATH``.

    Raises:
        CDPConfigError: if ``CDP_PATH`` is unset, the path doesn't exist, the
            path isn't a directory, or it contains none of the canonical CDP
            binaries.
    """
    raw = os.environ.get("CDP_PATH")
    if not raw:
        raise CDPConfigError("CDP_PATH environment variable not set")

    cdp_path = Path(raw).expanduser().resolve()
    if not cdp_path.exists():
        raise CDPConfigError(f"CDP_PATH does not exist: {cdp_path}")
    if not cdp_path.is_dir():
        raise CDPConfigError(f"CDP_PATH is not a directory: {cdp_path}")

    detected = _detect_binaries(cdp_path)
    if not any(name in detected for name in _CANONICAL_BINARIES):
        raise CDPConfigError(
            f"CDP_PATH does not appear to contain CDP binaries: {cdp_path}"
        )

    version = _detect_version(cdp_path)

    return CDPConfig(
        cdp_path=cdp_path,
        version=version,
        detected_binaries=detected,
    )


def _detect_binaries(cdp_path: Path) -> list[str]:
    """List executable files inside ``cdp_path``, capped for logging."""
    found: list[str] = []
    for entry in sorted(cdp_path.iterdir()):
        if len(found) >= _MAX_DETECTED_BINARIES:
            break
        if entry.is_file() and os.access(entry, os.X_OK):
            found.append(entry.name)
    return found


def _detect_version(cdp_path: Path) -> str:
    """Best-effort CDP version detection.

    Strategy, in order:

    1. ``cdp --version`` probe. Stock CDP r8 has no ``cdp`` binary (the
       closest names are ``cdparams``, ``cdparse``), but custom builds
       or wrappers may expose this.
    2. Path-component heuristic. Walk ``cdp_path.parts`` in reverse and
       match each component against the canonical CDP release-naming
       pattern. The first match yields ``f"r{captured}"``. Matches CDP's
       actual distribution model where the version lives in the
       directory name (``cdpr8/``, ``cdpr7/``).
    3. ``"unknown"`` sentinel. Still recorded in
       ``session.config.cdp_version`` for provenance; the mismatch
       warning in ``set_session()`` correctly skips when either side
       is ``"unknown"``.

    Never raises.
    """
    cdp_binary = cdp_path / "cdp"
    if cdp_binary.exists():
        try:
            result = subprocess.run(
                [str(cdp_binary), "--version"],
                capture_output=True,
                text=True,
                timeout=_VERSION_PROBE_TIMEOUT_SECONDS,
            )
            output = (result.stdout or result.stderr or "").strip()
            if output:
                first_line = output.splitlines()[0].strip()
                if first_line:
                    return first_line
        except (subprocess.SubprocessError, OSError):
            pass  # fall through to path heuristic

    # Path-component fallback: walk parts in reverse so the directory
    # closest to cdp_path wins on ambiguity (e.g.
    # /opt/cdpr8/extras/cdpr7/_cdprogs → r7).
    for part in reversed(cdp_path.parts):
        m = _VERSION_PATH_RE.match(part)
        if m:
            return f"r{m.group(1)}"
    return "unknown"
