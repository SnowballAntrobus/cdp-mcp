"""The ``cluster()`` MCP tool — group batch variants for audition triage.

Phase 3. After ``batch()`` produces 10-40 variants, auditioning every
one wastes the user's time and the conversation's context window.
``cluster()`` groups the variants by timbral similarity so the user
auditions ONE representative per cluster — the medoid — instead of
everything. Workflow: batch → cluster → compare medoids → keep winners.

Features per target: MFCC(13) means + stds + spectral-centroid mean +
RMS mean, plus the MIR v2 additions — flatness-dB mean + std, rolloff-85
mean, centroid-trajectory total variation, and rms-trajectory range
(33 dims) — standardized, PCA-reduced, then agglomerative (Ward)
clustering. When ``k`` is omitted, a silhouette scan over 2..min(6, N-1)
picks the best-separated cluster count. The medoid of each cluster is
the member with the smallest mean euclidean distance to its co-members
in the scaled-PCA space. Deterministic for a fixed ``seed``.

Same target grammar and auto-synth behavior as :func:`analyze`, plus
the literal string ``"latest_batch"`` meaning every element of the most
recent ``batch()`` call.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import librosa
import numpy as np
from mcp.server.fastmcp import Context, FastMCP

from ..analysis import trajectory_frames
from ..config import CDPConfig
from ..graph import (
    LatestTracker,
    ReferenceResolutionError,
    build_context_block,
    resolve_target,
)
from ..progress import run_with_progress
from ..pvoc import PVOCFailedError, synth_for_audition
from ..schema import ContextBlock, ErrorEntry
from ..security import SecurityError
from ..session import SessionManager, SessionNotActiveError

_SPECTRAL_SUFFIXES = frozenset({".ana", ".pvx"})
_MIN_TARGETS = 3
_MAX_AUTO_K = 6
_MAX_PCA_COMPONENTS = 8


async def cluster_impl(
    ctx: Context,
    targets: list[str] | str,
    k: int | None = None,
    seed: int = 42,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> dict:
    """Implementation of ``cluster()``.

    Exposed at module scope so callers can invoke without going through
    the MCP protocol layer. The ``@mcp.tool()`` wrapper inside
    :func:`register` is a thin closure that rebinds the deps from
    server-startup state and delegates here.

    Groups the targets by timbral similarity and names one medoid per
    cluster — the single file worth auditioning for that cluster.

    ``targets`` is either the literal string ``"latest_batch"`` (every
    element of the most recent ``batch()``) or a list of references
    (session input filenames, ``<graph_id>:<node_id>``, ``latest`` /
    ``prev_N`` / ``latest_batch[i]`` aliases). ``.ana`` / ``.pvx``
    targets are auto-synthesized to temporary ``.wav`` files first.
    """
    # 1. Require active session.
    try:
        session = sessions.require_active()
    except SessionNotActiveError as e:
        return _no_session_failure(latest_tracker, seed, str(e))

    # 2. Expand "latest_batch" / validate the targets shape.
    if isinstance(targets, str):
        if targets != "latest_batch":
            return _failure(session, latest_tracker, seed, [ErrorEntry(
                type="invalid_targets",
                message=(
                    f"targets was the string {targets!r}; the only string "
                    "form accepted is the literal 'latest_batch'."
                ),
                fix=(
                    "Pass 'latest_batch' to cluster the whole last batch, "
                    "or a list of references."
                ),
            )])
        if latest_tracker.latest_batch is None:
            return _failure(session, latest_tracker, seed, [ErrorEntry(
                type="batch_not_available",
                message=(
                    "targets='latest_batch' but no batch() has run in this "
                    "server session."
                ),
                fix=(
                    "Run batch() first, or pass an explicit list of "
                    "references."
                ),
            )])
        graph_id, node_ids = latest_tracker.latest_batch
        refs = [f"{graph_id}:{node_id}" for node_id in node_ids]
    else:
        if not all(isinstance(t, str) for t in targets):
            return _failure(session, latest_tracker, seed, [ErrorEntry(
                type="invalid_targets",
                message="every element of targets must be a string reference.",
                fix=(
                    "Pass references like 'frog.wav', '<graph_id>:<node_id>', "
                    "'latest', or 'latest_batch[i]'."
                ),
            )])
        refs = list(targets)

    # 3. Enough material to cluster? Fewer than 3 points can't form
    # more than trivial groups (and silhouette needs 2 <= k <= N-1).
    if len(refs) < _MIN_TARGETS:
        return _failure(
            session, latest_tracker, seed,
            [ErrorEntry(
                type="cluster_too_few",
                message=(
                    f"clustering needs at least {_MIN_TARGETS} targets; got "
                    f"{len(refs)}."
                ),
                fix=(
                    "Pass more targets — with 1-2 files, compare() them "
                    "directly instead."
                ),
            )],
            n_targets=len(refs),
        )

    # 4. Validate k. k=1 is rejected — one cluster tells you nothing;
    # k > N can't partition N points.
    if k is not None and (k < 2 or k > len(refs)):
        return _failure(
            session, latest_tracker, seed,
            [ErrorEntry(
                type="invalid_k",
                message=(
                    f"k={k} is out of range for {len(refs)} targets; k must "
                    "be between 2 and the number of targets."
                ),
                fix=(
                    "Pass k in [2, n_targets], or omit k to auto-select "
                    "via silhouette scan."
                ),
            )],
            n_targets=len(refs),
        )

    # 5. Resolve every target; auto-synth spectral inputs (same step as
    # analyze()).
    resolved: list[Path] = []
    for ref in refs:
        try:
            audio_path = resolve_target(ref, session, latest_tracker)
        except ReferenceResolutionError as e:
            return _failure(
                session, latest_tracker, seed,
                [ErrorEntry(
                    type="reference_resolution",
                    message=str(e),
                    fix=(
                        "Check the reference: 'latest', "
                        "'<graph_id>:<node_id>', an absolute path, or "
                        "a filename inside the session's inputs/ "
                        "directory."
                    ),
                )],
                n_targets=len(refs),
            )
        if audio_path.suffix.lower() in _SPECTRAL_SUFFIXES:
            cdp = cdp_config_provider()
            if cdp is None:
                return _failure(
                    session, latest_tracker, seed,
                    [ErrorEntry(
                        type="cdp_not_configured",
                        message=(
                            f"Cannot auto-synth spectral target {ref!r} — "
                            "CDP is not configured on this server."
                        ),
                        fix=(
                            "Set CDP_PATH and restart the server, or "
                            "pass .wav targets."
                        ),
                    )],
                    n_targets=len(refs),
                )
            try:
                audio_path, _sub = await synth_for_audition(
                    audio_path,
                    session=session,
                    cdp_path=cdp.cdp_path,
                    cache_root=cache_root,
                    cdp_version=cdp.version,
                    ctx=ctx,
                )
            except (PVOCFailedError, SecurityError) as e:
                return _failure(
                    session, latest_tracker, seed,
                    [ErrorEntry(
                        type="pvoc_failed",
                        message=f"target {ref!r}: {e}",
                        fix=(
                            "Check the input .ana file; if pvoc synth "
                            "fails on a known-good spectral file, this "
                            "is a CDP-side issue, not the tool."
                        ),
                    )],
                    n_targets=len(refs),
                )
        resolved.append(audio_path)

    # 6. Extract one feature vector per target — off the event loop via
    # run_with_progress so MCP heartbeats don't starve on long files.
    vectors: list[np.ndarray] = []
    for i, (ref, audio_path) in enumerate(zip(refs, resolved, strict=True)):
        try:
            vec = await run_with_progress(
                ctx,
                f"extracting cluster features ({i + 1}/{len(refs)})",
                _extract_features,
                audio_path,
            )
        except Exception as e:  # noqa: BLE001 — soundfile/librosa raise a zoo
            # Corrupt/truncated/unsupported audio must surface as a
            # structured error, not a raw protocol error. (Phase 2
            # hardening, M3.)
            return _failure(
                session, latest_tracker, seed,
                [ErrorEntry(
                    type="cluster_failed",
                    message=(
                        f"feature extraction failed on target {ref!r} "
                        f"({audio_path.name}): {type(e).__name__}: {e}"
                    ),
                    fix=(
                        "The audio file may be corrupt, truncated, or in "
                        "an unsupported encoding. Check it with analyze() "
                        "or visualize(), or drop it from targets."
                    ),
                )],
                n_targets=len(refs),
            )
        vectors.append(vec)

    # 7. Scale → PCA → (silhouette scan) → agglomerative → medoids. All
    # sync CPU (sklearn), pushed off the event loop like extraction.
    try:
        k_final, clusters, pca_coords, warnings = await run_with_progress(
            ctx,
            "clustering targets",
            _cluster_sync,
            refs,
            np.vstack(vectors),
            k,
            seed,
        )
    except Exception as e:  # noqa: BLE001 — sklearn raises a zoo (M3)
        return _failure(
            session, latest_tracker, seed,
            [ErrorEntry(
                type="cluster_failed",
                message=f"clustering failed: {type(e).__name__}: {e}",
                fix=(
                    "Try passing an explicit k, or drop degenerate targets "
                    "(e.g. digital silence) from the list."
                ),
            )],
            n_targets=len(refs),
        )

    return {
        "status": "ok",
        "n_targets": len(refs),
        "k": k_final,
        "clusters": clusters,
        "pca_coords": pca_coords,
        "warnings": warnings,
        "errors": [],
        "seed": seed,
        "context": build_context_block(
            session, latest_tracker, active_graph=None
        ).model_dump(mode="json"),
    }


def register(
    mcp: FastMCP,
    *,
    sessions: SessionManager,
    cdp_config_provider: Callable[[], CDPConfig | None],
    latest_tracker: LatestTracker,
    cache_root: Path,
) -> None:
    """Register the ``cluster`` tool against ``mcp``.

    Thin wrapper around :func:`cluster_impl`.
    """

    @mcp.tool()
    async def cluster(
        ctx: Context,
        targets: list[str] | str,
        k: int | None = None,
        seed: int = 42,
    ) -> dict:
        """Group processed variants by timbral similarity — audition less.

        The triage step between exploration and selection: after
        ``batch()`` produces 10-40 variants, call
        ``cluster("latest_batch")`` to group them, then audition ONE
        file per cluster — each cluster's ``medoid`` — with
        ``compare()`` / ``analyze()`` and keep the winners. Workflow:
        batch → cluster → compare the medoids → keep.

        ``targets`` is either the literal string ``"latest_batch"``
        (every element of the most recent ``batch()`` call) or an
        explicit list of references (session input filenames,
        ``<graph_id>:<node_id>``, ``latest`` / ``prev_N`` /
        ``latest_batch[i]`` aliases). At least 3 targets are required.
        ``.ana`` / ``.pvx`` targets are auto-synthesized to temporary
        ``.wav`` files first.

        Each target reduces to a 33-dim timbre vector (13 MFCC means +
        13 MFCC stds + spectral-centroid mean + RMS mean + flatness-dB
        mean/std + rolloff-85 mean + centroid-trajectory total
        variation + rms-trajectory range), standardized and
        PCA-reduced, then grouped with agglomerative clustering. The
        MIR v2 vector separates noisy-vs-tonal and ordered-vs-scrambled
        variants that the earlier Phase 3 28-dim vector conflated —
        groupings may therefore differ from pre-v2 runs on the same
        material. ``k`` (>= 2) fixes the cluster count; when omitted, a
        silhouette scan over 2..min(6, N-1) picks the best-separated k.
        Results are deterministic for a fixed ``seed``.

        Returns ``clusters`` — each with ``members``, ``size``, and its
        ``medoid`` (the member closest to its cluster's co-members: the
        one file worth auditioning per cluster) — plus ``pca_coords``,
        a 2-D coordinate per target for reasoning about relative
        similarity.
        """
        return await cluster_impl(
            ctx,
            targets,
            k,
            seed,
            sessions=sessions,
            cdp_config_provider=cdp_config_provider,
            latest_tracker=latest_tracker,
            cache_root=cache_root,
        )


# ---------------------------------------------------------------------------
# Sync pipeline (runs in a thread via run_with_progress)
# ---------------------------------------------------------------------------


def _extract_features(audio_path: Path) -> np.ndarray:
    """33-dim timbre vector (MIR v2).

    The Phase 3 28-dim core (MFCC(13) means + stds + centroid mean +
    RMS mean) plus the gap-analysis §4.5 additions: flatness-dB
    mean + std (D1 — a noisy pad and a bright tone no longer
    co-cluster), rolloff-85 mean (D2 spectral edge), and — from the
    shared 16-point trajectory (:func:`~cdp_mcp.analysis.
    trajectory_frames`, same frame math as ``analyze(verbose=True)``)
    — centroid total variation and rms-dB range (D7 — ordered vs
    scrambled variants were previously indistinguishable, §3.f).

    Mono downmix at native sample rate. Raises whatever librosa /
    soundfile raise on unreadable audio — the tool layer converts to
    structured ``cluster_failed`` errors.
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
    rms = librosa.feature.rms(y=y)
    # Per-frame flatness in dB (floored) — matches the scorecard's
    # convention; linear flatness spans 1e-9..0.9 and would let a few
    # noise frames dominate mean/std.
    flatness_db = 10.0 * np.log10(
        np.maximum(librosa.feature.spectral_flatness(y=y)[0], 1e-12)
    )
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=0.85)
    rms_traj, centroid_traj, _flatness_traj = trajectory_frames(y, sr)
    centroid_tv = (
        float(np.abs(np.diff(centroid_traj)).sum()) if centroid_traj.size > 1 else 0.0
    )
    rms_range = (
        float(rms_traj.max() - rms_traj.min()) if rms_traj.size > 0 else 0.0
    )
    return np.concatenate([
        mfcc.mean(axis=1),
        mfcc.std(axis=1),
        [float(centroid.mean())],
        [float(rms.mean())],
        [float(flatness_db.mean())],
        [float(flatness_db.std())],
        [float(rolloff.mean())],
        [centroid_tv],
        [rms_range],
    ]).astype(np.float64)


def _cluster_sync(
    refs: list[str],
    features: np.ndarray,
    k: int | None,
    seed: int,
) -> tuple[int, list[dict], dict[str, list[float]], list[str]]:
    """StandardScaler → PCA → agglomerative clustering → medoids.

    When ``k`` is None, every candidate in 2..min(6, N-1) is clustered
    and scored with the silhouette coefficient; the best-scoring k wins
    (ties break toward the smaller k — the scan ascends and only a
    strictly better score displaces the incumbent). Cluster labels are
    renumbered by first appearance in ``refs`` order, and the medoid of
    each cluster is the member minimizing mean euclidean distance to
    its co-members in the scaled-PCA space. Deterministic for fixed
    inputs and ``seed`` — agglomerative (Ward) clustering has no
    randomness, and PCA's full SVD is sign-stabilized.
    """
    # Lazy import: scikit-learn is heavy and cluster() is the only
    # consumer; keep server startup unburdened.
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    n = features.shape[0]
    scaled = StandardScaler().fit_transform(features)
    n_components = min(_MAX_PCA_COMPONENTS, scaled.shape[1], n - 1)
    coords = PCA(n_components=n_components, random_state=seed).fit_transform(scaled)

    warnings: list[str] = []
    if k is None:
        best_k, best_score = 2, -math.inf
        for candidate in range(2, min(_MAX_AUTO_K, n - 1) + 1):
            labels = AgglomerativeClustering(n_clusters=candidate).fit_predict(coords)
            try:
                score = float(silhouette_score(coords, labels))
            except ValueError:
                continue
            if math.isfinite(score) and score > best_score:
                best_k, best_score = candidate, score
        if not math.isfinite(best_score):
            warnings.append(
                "silhouette scan was degenerate (identical or near-identical "
                "targets); defaulting to k=2."
            )
        k = best_k

    labels = AgglomerativeClustering(n_clusters=k).fit_predict(coords)

    # Renumber cluster labels by first appearance in refs order so the
    # output is stable across runs (sklearn's label numbering is
    # arbitrary).
    order: dict[int, int] = {}
    for lab in labels:
        if int(lab) not in order:
            order[int(lab)] = len(order)
    members_by_label: list[list[int]] = [[] for _ in range(len(order))]
    for i, lab in enumerate(labels):
        members_by_label[order[int(lab)]].append(i)

    clusters: list[dict] = []
    for new_label, member_idx in enumerate(members_by_label):
        medoid_idx = member_idx[0]
        if len(member_idx) > 1:
            pts = coords[member_idx]
            dists = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
            # Mean distance to co-members (self-distance is 0; divide by
            # the co-member count). argmin ties break to the first
            # member — deterministic.
            mean_d = dists.sum(axis=1) / (len(member_idx) - 1)
            medoid_idx = member_idx[int(np.argmin(mean_d))]
        clusters.append({
            "label": new_label,
            "members": [refs[i] for i in member_idx],
            "medoid": refs[medoid_idx],
            "size": len(member_idx),
        })

    pca_coords = {
        refs[i]: [round(float(coords[i, 0]), 4), round(float(coords[i, 1]), 4)]
        for i in range(n)
    }
    return k, clusters, pca_coords, warnings


# ---------------------------------------------------------------------------
# Failure payloads
# ---------------------------------------------------------------------------


def _no_session_failure(
    latest_tracker: LatestTracker, seed: int, message: str
) -> dict:
    return {
        "status": "failed",
        "n_targets": 0,
        "k": None,
        "clusters": [],
        "pca_coords": {},
        "warnings": [],
        "errors": [ErrorEntry(
            type="no_active_session",
            message=message,
            fix="Call set_session('<name>') first.",
        ).model_dump()],
        "seed": seed,
        "context": ContextBlock(
            active_graph=None,
            latest=latest_tracker.latest,
            recent_graphs=[],
            available_sources=[],
        ).model_dump(mode="json"),
    }


def _failure(
    session,
    latest_tracker: LatestTracker,
    seed: int,
    errors: list[ErrorEntry],
    n_targets: int = 0,
) -> dict:
    return {
        "status": "failed",
        "n_targets": n_targets,
        "k": None,
        "clusters": [],
        "pca_coords": {},
        "warnings": [],
        "errors": [e.model_dump() for e in errors],
        "seed": seed,
        "context": build_context_block(
            session, latest_tracker, active_graph=None
        ).model_dump(mode="json"),
    }
