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

import hashlib
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import soundfile as sf
from mcp.server.fastmcp import Context

from .cache import (
    audition_cache_key,
    cache_lookup,
    cache_populate,
    materialize_cached_artifact,
    pvoc_cache_key,
)
from .graph import GraphDir
from .limits import OUTPUT_FILE_SIZE_CAP_BYTES
from .processing import _argv_path
from .schema import ErrorEntry, InputRecord, NodeLineage
from .security import SecurityError, validate_command
from .session import Session
from .subprocess_core import SubprocessResult, run_cdp_command
from .utils import atomic_write_text, sha256_file

# Map file extensions to CDP's domain vocabulary. Lowercased for comparison.
_TIME_EXTENSIONS = frozenset({".wav", ".aif", ".aiff", ".amb"})
_SPECTRAL_EXTENSIONS = frozenset({".ana", ".pvx"})

# CDP r8 defaults for ``pvoc anal`` — verified against the binary's usage
# banner (run ``pvoc anal`` with no args). Pinned here so the cache key,
# the argv build, and any future tests share one source of truth. Task 4
# keeps these hardcoded; Task 8 will expose ``_pvoc.window`` /
# ``_pvoc.overlap`` engine controls that override per-call.
_DEFAULT_PVOC_WINDOW = 1024     # "points": analysis FFT size (power of 2, 2-32768)
_DEFAULT_PVOC_OVERLAP = 3       # filter overlap factor (range 1-4)


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
    *,
    window: int = _DEFAULT_PVOC_WINDOW,
    overlap: int = _DEFAULT_PVOC_OVERLAP,
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
        window: ``pvoc anal -c`` flag (analysis FFT points). Always
            emitted in the anal argv so lineage shows exactly what was
            used; participates in the cache key. ``pvoc synth`` ignores
            this value (CDP synth reads the analysis params from the
            ``.ana`` file). Defaults to CDP r8's standard 1024. Task 8
            will route a user-supplied value here.
        overlap: ``pvoc anal -o`` flag (filter overlap factor). Same
            shape as ``window`` — emitted for anal, ignored by synth,
            in the cache key. Default 3.

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

    # Pick direction. Window/overlap are always emitted as explicit
    # ``-c<N>``/``-o<N>`` flags in the anal argv so the lineage matches
    # the cache key 1:1 — no "default-equals-implicit" elision. CDP r8
    # quirk: the flags MUST come AFTER the input/output positionals (a
    # flag in the middle gets interpreted as a filename), so they're
    # held in ``post_argv_flags`` and appended below.
    post_argv_flags: list[str] = []
    if input_domain == "time" and target_domain == "spectral":
        # ``"1"`` is the analysis MODE (1=STANDARD ANALYSIS in CDP r8's
        # pvoc anal banner; modes 2/3 are envelope/magnitude variants
        # out of scope for Phase 2).
        argv_template = ["pvoc", "anal", "1"]
        post_argv_flags = [f"-c{window}", f"-o{overlap}"]
        out_filename = f"{node_id}_pvoc-anal.ana"
        operation = "anal"
    elif input_domain == "spectral" and target_domain == "time":
        argv_template = ["pvoc", "synth"]
        out_filename = f"{node_id}_pvoc-synth.wav"
        operation = "synth"
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
        *post_argv_flags,
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

    # Cache check (Task 10). PVOC anal/synth output is a pure function of
    # input bytes + argv shape + CDP version. On hit, hardlink the cached
    # artifact into the graph dir and build a "cache_hit=True" lineage
    # entry without running any subprocess.
    input_sha = sha256_file(input_path)
    out_suffix = ".ana" if target_domain == "spectral" else ".wav"
    cache_key = pvoc_cache_key(
        input_sha, operation, window, overlap, cdp_version
    )
    cache = cache_lookup(cache_root, "pvoc", cache_key, out_suffix)

    if cache.hit:
        # Materialize and build a synthetic lineage entry. duration_ms=0
        # and started_at == finished_at == now() flag this as a cache hit
        # even before the cache_hit field is inspected.
        materialize_cached_artifact(cache.path, output_path)
        output_sha = sha256_file(output_path)
        source_duration = _try_read_wav_duration(input_path)
        now = datetime.now(timezone.utc)
        lineage = NodeLineage(
            argv=validated,
            inputs=[
                InputRecord(
                    path=str(input_path),
                    sha256=input_sha,
                    source_node=None,
                )
            ],
            output_path=str(output_path),
            output_sha256=output_sha,
            params={},
            cdp_version=cdp_version,
            started_at=now,
            finished_at=now,
            duration_ms=0,
            exit_code=0,
            source_wav_duration_s=source_duration,
            cache_hit=True,
        )
        try:
            graph_dir.add_node(node_id, out_filename, lineage)
        except OSError as e:
            print(
                f"[cdp-mcp] WARNING: pvoc cache-hit materialized but graph "
                f"bookkeeping failed for {node_id}: {e}",
                file=sys.stderr,
            )
            return PVOCResult(
                state="failed",
                output_path=input_path,
                node_id=node_id,
                lineage=lineage,
                error_entry=ErrorEntry(
                    type="graph_bookkeeping_failed",
                    message=(
                        f"PVOC cache hit materialized but graph bookkeeping "
                        f"failed: {e}"
                    ),
                    fix="Inspect the graph directory on disk for clues.",
                ),
            )
        return PVOCResult(
            state="succeeded",
            output_path=output_path,
            node_id=node_id,
            lineage=lineage,
        )

    started_at = datetime.now(timezone.utc)
    sub = await run_cdp_command(
        validated,
        cwd=session_root,  # match main op's cwd so relative paths resolve consistently
        timeout_seconds=timeout_seconds,
        ctx=ctx,
        output_path=output_path,
        size_cap_bytes=OUTPUT_FILE_SIZE_CAP_BYTES,
    )
    finished_at = datetime.now(timezone.utc)

    # size_cap_exceeded takes precedence over the generic PVOC failure
    # so the LLM sees the actionable cause rather than a confusing
    # "exited with code <signal>".
    if sub.size_cap_exceeded:
        return PVOCResult(
            state="failed",
            output_path=input_path,
            node_id=node_id,
            subprocess_result=sub,
            error_entry=ErrorEntry(
                type="size_cap_exceeded",
                message=(
                    f"PVOC output exceeded the {sub.triggered_at_bytes:,}-byte "
                    f"cap (limit: {OUTPUT_FILE_SIZE_CAP_BYTES:,} bytes); the "
                    f"subprocess was killed and partial output removed. "
                    f"PVOC artifacts can be 10-20x the source wav size — "
                    f"long stereo inputs are the usual cause."
                ),
                fix=(
                    "Use a shorter input, or set "
                    "CDP_MCP_OUTPUT_SIZE_CAP_BYTES in the environment to "
                    "raise the cap before starting the server."
                ),
            ),
        )

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

    # Task 8: record the source wav's duration on the PVOC node's lineage
    # so downstream breakpoint compilation can resolve relative-time
    # tuples against the original audio. Only meaningful when the input
    # was a .wav (PVOC anal direction); .ana inputs already have their
    # duration encoded indirectly via the source wav that produced them.
    source_duration = _try_read_wav_duration(input_path)

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
        source_wav_duration_s=source_duration,
        cache_hit=False,
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

    # Best-effort cache populate. Failure logs a stderr warning and
    # returns False; we still report success to the caller because the
    # in-graph output is correct regardless of cache state.
    cache_populate(cache.path, output_path)

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


def _try_read_wav_duration(input_path: Path) -> float | None:
    """Cheap best-effort duration probe for the PVOC source.

    Returns ``None`` for non-wav inputs (.ana inputs encode their
    duration indirectly via the source wav that produced them) or when
    ``soundfile.info`` raises. Downstream consumers (breakpoint
    compiler) treat ``None`` as "duration unknown" and emit an
    actionable error rather than guessing.
    """
    if input_path.suffix.lower() != ".wav":
        return None
    try:
        return float(sf.info(str(input_path)).duration)
    except Exception:  # noqa: BLE001 — soundfile raises a variety
        return None


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

    Output filename: ``<ana_path.stem>.wav``. On a cache miss the
    pre-existing wav (if any) is deleted first because CDP r8's
    ``pvoc synth`` refuses to overwrite existing files and exits 255.

    Cached at ``~/.cdp_mcp/cache/audition/<sha>.wav`` keyed by
    ``sha256(ana_bytes + cdp_version)`` (Task 11). A cache hit returns
    the cached path directly, skipping the subprocess entirely; a miss
    runs ``pvoc synth`` into ``session.tmp_dir`` (the cwd-relative
    argv path keeps Task 2's brassage-style path-mangling defense in
    play) and then populates the cache best-effort.

    Raises:
        PVOCFailedError: on non-zero exit, timeout, or missing output.
        SecurityError: if the constructed argv fails the security gate
            (should not happen in normal use; surfaces as a bug signal).
    """
    # Cache check (Task 11). On hit, return the cache path directly;
    # callers read via librosa (no writes), so no materialize needed.
    ana_sha = sha256_file(ana_path)
    cache = cache_lookup(
        cache_root, "audition", audition_cache_key(ana_sha, cdp_version), ".wav",
    )
    if cache.hit:
        return cache.path, SubprocessResult(
            argv=[],
            stdout="",
            stderr="(audition cache hit)",
            exit_code=0,
            duration_ms=0,
            timed_out=False,
        )

    output_path = session.tmp_dir / f"{ana_path.stem}.wav"
    # Defensive — Task 3's _SUBDIRS already creates tmp/ at session init,
    # but a caller building a Session by hand might forget it.
    session.tmp_dir.mkdir(parents=True, exist_ok=True)

    # CDP r8's pvoc synth refuses to clobber existing output files
    # (exits 255). Clear the way ourselves so the argv path is always
    # free when CDP looks.
    output_path.unlink(missing_ok=True)

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
        output_path=output_path,
        size_cap_bytes=OUTPUT_FILE_SIZE_CAP_BYTES,
    )

    if sub.size_cap_exceeded:
        raise PVOCFailedError(
            f"pvoc synth output exceeded {sub.triggered_at_bytes:,}-byte cap "
            f"(limit: {OUTPUT_FILE_SIZE_CAP_BYTES:,}) on {ana_path.name}; "
            f"killed before completion.",
            subprocess_result=sub,
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

    # Best-effort cache populate (Task 11). Failure logs a stderr
    # warning and returns False; the in-session output remains usable
    # regardless of cache state.
    cache_populate(cache.path, output_path)

    return output_path, sub


# ---------------------------------------------------------------------------
# read_ana_duration — header-only duration of a CDP .ana via sfprops -d
# ---------------------------------------------------------------------------


async def read_ana_duration(
    ana_path: Path,
    *,
    session_root: Path,
    cdp_path: Path,
    cache_dir: Path,
    cdp_version: str,
    timeout_seconds: float = 10.0,
    ctx: Context | None = None,
) -> float | None:
    """Header-only duration of a CDP ``.ana`` file via ``sfprops -d``.

    Never raises — returns ``None`` on any failure (missing binary,
    security-validation reject, non-zero exit, unparseable stdout,
    timeout, I/O error). The disk watchdog (Task 7) is the reactive
    safety net for the cases this can't predict.

    Investigation outcome (Phase 2 Task 2): the high-level design doc
    named ``dirsf`` as the candidate, but verification against r8
    revealed ``dirsf`` is a directory-listing utility, not a per-file
    header reader. ``pvoc info`` does not exist in r8 (modes are
    ``anal``/``synth``/``extract``). ``sfprops -d <path>`` is the right
    tool — exits 0 on success and writes exactly one float to stdout
    (e.g. ``"7.235465\\n"``); exits 1 on missing/corrupt file.
    Sub-second cost on a 10 MB ana.

    Cached at ``<cache_dir>/<sha>.duration`` keyed by
    ``sha256(ana_bytes + cdp_version)``. Cache hits skip the
    subprocess. Cache writes are non-fatal — failure logs to stderr
    and returns the live result anyway, matching the project-wide
    pattern from :func:`cache.cache_populate`.
    """
    # ---- Cache lookup -------------------------------------------------------
    try:
        ana_sha = sha256_file(ana_path)
    except OSError:
        return None
    cache_key = hashlib.sha256(
        f"{ana_sha}|{cdp_version}".encode("utf-8")
    ).hexdigest()
    cache_path = cache_dir / f"{cache_key}.duration"
    if cache_path.exists():
        try:
            cached = float(cache_path.read_text(encoding="utf-8").strip())
            if math.isfinite(cached) and cached >= 0:
                return cached
        except (OSError, ValueError):
            # Stale/corrupt cache entry — fall through to live shell-out.
            pass

    # ---- Shell out to sfprops -d -------------------------------------------
    argv = ["sfprops", "-d", _argv_path(ana_path, session_root)]
    try:
        validated = validate_command(argv, cdp_path, session_root, cache_dir)
    except SecurityError:
        return None
    try:
        sub = await run_cdp_command(
            validated,
            cwd=session_root,
            timeout_seconds=timeout_seconds,
            ctx=ctx,
        )
    except (OSError, FileNotFoundError):
        return None

    if sub.timed_out or sub.exit_code != 0:
        return None

    try:
        duration = float(sub.stdout.strip())
    except (ValueError, AttributeError):
        return None
    if not math.isfinite(duration) or duration < 0:
        return None

    # ---- Cache populate (non-fatal) ----------------------------------------
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(cache_path, f"{duration}\n")
    except OSError as e:
        print(
            f"[cdp-mcp] Warning: ana-duration cache populate failed for "
            f"{cache_path}: {e.__class__.__name__}: {e}. Result returned anyway.",
            file=sys.stderr,
        )

    return duration
