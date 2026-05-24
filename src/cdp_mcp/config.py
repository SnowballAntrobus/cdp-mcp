"""CDP install detection.

Resolves the ``CDP_PATH`` environment variable, sanity-checks that it points at
a real CDP binary directory, and best-effort captures the CDP version string.
"""

from __future__ import annotations

import os
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
    """Best-effort CDP version probe. Returns ``"unknown"`` on any failure."""
    cdp_binary = cdp_path / "cdp"
    if not cdp_binary.exists():
        return "unknown"
    try:
        result = subprocess.run(
            [str(cdp_binary), "--version"],
            capture_output=True,
            text=True,
            timeout=_VERSION_PROBE_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"

    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return "unknown"
    # Some CDP builds print a banner with multiple lines; take the first
    # non-empty line as the version-ish string.
    return output.splitlines()[0].strip() or "unknown"
