"""Automatic PVOC insertion for ``process()``.

CDP splits its toolset into time-domain programs (``.wav`` in / out) and
spectral programs (``.ana`` in / out). To chain across the divide you have
to run ``pvoc anal`` (time → spectral) or ``pvoc synth`` (spectral → time)
between ops. :func:`maybe_insert_pvoc` automates that conversion when the
main op's domain doesn't match an input's actual extension. The inserted
PVOC node is recorded as a first-class node in the graph directory so its
output is addressable and its lineage is auditable, just like the main op.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import Context

from .graph import GraphDir
from .processing import _argv_path
from .schema import ErrorEntry, InputRecord, NodeLineage
from .security import SecurityError, validate_command
from .session import Session
from .subprocess_core import SubprocessResult, run_cdp_command
from .utils import sha256_file

# Map file extensions to CDP's domain vocabulary. Lowercased for comparison.
_TIME_EXTENSIONS = frozenset({".wav", ".aif", ".aiff", ".amb"})
_SPECTRAL_EXTENSIONS = frozenset({".ana", ".pvx"})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class PVOCResult:
    """Outcome of one :func:`maybe_insert_pvoc` call.

    - ``state == "skipped"``: input already matched target_domain;
      ``output_path == input_path``; no subprocess ran; no node was added.
    - ``state == "succeeded"``: PVOC subprocess ran successfully; the
      converted file is at ``output_path``; the node was recorded in the
      graph dir; ``node_id`` and ``lineage`` are populated.
    - ``state == "failed"``: PVOC subprocess ran but exited nonzero / timed
      out / verification failed, OR the input had an unrecognised
      extension. ``error_entry`` carries a structured reason; the caller
      should bail and surface that error to the LLM.
    """

    state: Literal["skipped", "succeeded", "failed"]
    output_path: Path
    node_id: str | None = None
    lineage: NodeLineage | None = None
    subprocess_result: SubprocessResult | None = None
    error_entry: ErrorEntry | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def maybe_insert_pvoc(
    input_path: Path,
    target_domain: Literal["time", "spectral"],
    graph_dir: GraphDir,
    node_id: str,
    cdp_path: Path,
    session_root: Path,
    cache_root: Path,
    cdp_version: str,
    timeout_seconds: float = 120.0,
    ctx: Context | None = None,
) -> PVOCResult:
    """Insert a ``pvoc anal`` or ``pvoc synth`` node if domains don't match.

    Args:
        input_path: Resolved absolute path of the upstream input.
        target_domain: Domain the consuming op needs (``"time"`` or
            ``"spectral"``).
        graph_dir: The graph the (potential) PVOC node is added to.
        node_id: Allocated node ID for the inserted PVOC node.
        cdp_path, session_root, cache_root: Passed to the security gate.
        cdp_version: Recorded into the lineage.
        timeout_seconds, ctx: Forwarded to ``run_cdp_command``.

    Returns a :class:`PVOCResult`. Skipped / succeeded paths produce a
    usable ``output_path``; failed paths carry an ``error_entry``.
    """
    input_domain = _domain_of(input_path)

    # Skip case — already in the target domain.
    if input_domain == target_domain:
        return PVOCResult(state="skipped", output_path=input_path)

    # Unknown extension can't be auto-converted.
    if input_domain == "unknown":
        return PVOCResult(
            state="failed",
            output_path=input_path,
            error_entry=ErrorEntry(
                type="unknown_input_domain",
                message=(
                    f"Cannot auto-insert PVOC for {input_path.name}: "
                    f"extension {input_path.suffix!r} is neither a known "
                    "time-domain nor spectral CDP file type."
                ),
                fix=(
                    "Convert the file to .wav / .aif / .aiff / .amb (time) "
                    "or .ana / .pvx (spectral) before passing it to "
                    "process(), or use execute() to run CDP directly."
                ),
            ),
        )

    # Pick direction.
    if input_domain == "time" and target_domain == "spectral":
        argv_template = ["pvoc", "anal", "1"]
        out_filename = f"{node_id}_pvoc-anal.ana"
    elif input_domain == "spectral" and target_domain == "time":
        argv_template = ["pvoc", "synth"]
        out_filename = f"{node_id}_pvoc-synth.wav"
    else:
        # Shouldn't reach here given the checks above, but be defensive.
        return PVOCResult(
            state="failed",
            output_path=input_path,
            error_entry=ErrorEntry(
                type="unsupported_domain_pair",
                message=(
                    f"No PVOC direction for input domain {input_domain!r} → "
                    f"target {target_domain!r}."
                ),
                fix="This indicates a bug in cdp-mcp. Please file an issue.",
            ),
        )

    output_path = graph_dir.root / out_filename
    # Use cwd-relative paths in the argv when the file lives inside the
    # session. See processing.build_cdp_argv docstring for why — same
    # CDP-quirk workaround applies to PVOC.
    argv = [
        *argv_template,
        _argv_path(input_path, session_root),
        _argv_path(output_path, session_root),
    ]

    # Security gate — paths are inside the session by construction, but the
    # rule is universal: every subprocess goes through validate_command.
    try:
        validated = validate_command(argv, cdp_path, session_root, cache_root)
    except SecurityError as e:
        return PVOCResult(
            state="failed",
            output_path=input_path,
            error_entry=ErrorEntry(
                type="pvoc_security",
                message=(
                    f"PVOC argv failed security validation; this should not "
                    f"happen in normal use: {[str(err.type) for err in e.errors]}"
                ),
                fix=(
                    "Likely a bug in cdp-mcp's PVOC argv assembly or in the "
                    "security boundary. Inspect the full error list."
                ),
            ),
        )

    started_at = datetime.now(timezone.utc)
    sub = await run_cdp_command(
        validated,
        cwd=session_root,  # match main op's cwd so relative paths resolve consistently
        timeout_seconds=timeout_seconds,
        ctx=ctx,
    )
    finished_at = datetime.now(timezone.utc)

    # Verify success: exit 0, not timed out, output file exists and is
    # non-empty. We deliberately *don't* run verify_output here for ana
    # files — Task 4's verify_output is for the final main-op output. For
    # PVOC intermediates, "exists and exit 0" is sufficient.
    if sub.timed_out or sub.exit_code != 0 or not output_path.exists():
        return PVOCResult(
            state="failed",
            output_path=input_path,
            node_id=node_id,
            subprocess_result=sub,
            error_entry=ErrorEntry(
                type="pvoc_failed",
                message=(
                    f"Auto-inserted PVOC step failed "
                    f"({argv_template[1]}) "
                    f"with exit_code={sub.exit_code}, timed_out={sub.timed_out}."
                ),
                fix=(
                    "Check the lineage entry for this PVOC node — stderr "
                    "typically explains the problem. Common causes: input "
                    "file unreadable, output directory not writable, or "
                    "CDP install missing the pvoc binary."
                ),
            ),
        )

    output_sha = sha256_file(output_path)
    input_sha = sha256_file(input_path)

    lineage = NodeLineage(
        argv=sub.argv,
        inputs=[
            InputRecord(
                path=str(input_path),
                sha256=input_sha,
                source_node=None,
            )
        ],
        output_path=str(output_path),
        output_sha256=output_sha,
        params={},  # PVOC currently runs with fixed flags; no user params
        cdp_version=cdp_version,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=sub.duration_ms,
        exit_code=sub.exit_code,
    )

    try:
        graph_dir.add_node(node_id, out_filename, lineage)
    except OSError as e:
        # Adding the node failed — the conversion succeeded but bookkeeping
        # didn't. Surface as a failure to the caller.
        print(
            f"[cdp-mcp] WARNING: pvoc output written but graph bookkeeping "
            f"failed for {node_id}: {e}",
            file=sys.stderr,
        )
        return PVOCResult(
            state="failed",
            output_path=input_path,
            node_id=node_id,
            subprocess_result=sub,
            lineage=lineage,
            error_entry=ErrorEntry(
                type="graph_bookkeeping_failed",
                message=f"PVOC ran but graph bookkeeping failed: {e}",
                fix="Inspect the graph directory on disk for clues.",
            ),
        )

    return PVOCResult(
        state="succeeded",
        output_path=output_path,
        node_id=node_id,
        lineage=lineage,
        subprocess_result=sub,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _domain_of(path: Path) -> Literal["time", "spectral", "unknown"]:
    suffix = path.suffix.lower()
    if suffix in _TIME_EXTENSIONS:
        return "time"
    if suffix in _SPECTRAL_EXTENSIONS:
        return "spectral"
    return "unknown"


# ---------------------------------------------------------------------------
# synth_for_audition — pure rendering aid (no graph node, no lineage)
# ---------------------------------------------------------------------------


class PVOCFailedError(Exception):
    """Raised when an audition-only PVOC synth doesn't produce usable output.

    Distinct from :class:`PVOCResult` (which is for the graph-node-producing
    :func:`maybe_insert_pvoc`): audition synth is a side-effect-free render
    aid, so failure surfaces as an exception that callers convert into a
    structured envelope error.
    """

    def __init__(self, message: str, subprocess_result: SubprocessResult | None = None):
        super().__init__(message)
        self.subprocess_result = subprocess_result


async def synth_for_audition(
    ana_path: Path,
    session: Session,
    cdp_path: Path,
    cache_root: Path,
    cdp_version: str,
    timeout_seconds: float = 60.0,
    ctx: Context | None = None,
) -> tuple[Path, SubprocessResult]:
    """Run ``pvoc synth`` on ``ana_path``, writing the wav into ``session.tmp_dir``.

    Used by :func:`visualize` and :func:`analyze` so they can render
    spectral files without polluting the graph. **No graph node, no
    lineage entry** — the temp wav is purely a rendering aid. It lives in
    ``session.tmp_dir`` until Phase 1b's ``cleanup()`` tool removes it.

    Output filename: ``<ana_path.stem>.wav``. Overwrites any existing file
    of the same name — last-write-wins is fine for transient renders, and
    avoids hash-suffix accumulation in ``tmp/``.

    Raises:
        PVOCFailedError: on non-zero exit, timeout, or missing output.
        SecurityError: if the constructed argv fails the security gate
            (should not happen in normal use; surfaces as a bug signal).
    """
    output_path = session.tmp_dir / f"{ana_path.stem}.wav"
    # Defensive — Task 3's _SUBDIRS already creates tmp/ at session init,
    # but a caller building a Session by hand might forget it.
    session.tmp_dir.mkdir(parents=True, exist_ok=True)

    argv = [
        "pvoc",
        "synth",
        _argv_path(ana_path, session.root),
        _argv_path(output_path, session.root),
    ]

    validated = validate_command(argv, cdp_path, session.root, cache_root)
    sub = await run_cdp_command(
        validated,
        cwd=session.root,
        timeout_seconds=timeout_seconds,
        ctx=ctx,
    )

    if sub.timed_out:
        raise PVOCFailedError(
            f"pvoc synth timed out after {timeout_seconds}s on {ana_path.name}",
            subprocess_result=sub,
        )
    if sub.exit_code != 0:
        raise PVOCFailedError(
            f"pvoc synth exited with code {sub.exit_code} on {ana_path.name}",
            subprocess_result=sub,
        )
    if not output_path.exists():
        raise PVOCFailedError(
            f"pvoc synth exited 0 but produced no output at {output_path}",
            subprocess_result=sub,
        )

    return output_path, sub
