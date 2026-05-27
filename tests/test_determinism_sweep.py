"""Phase 2 Task 1 — Determinism sweep of Phase 1a curated entries.

PVOC ``anal`` and ``synth`` are byte-verified deterministic (Phase 1b
§5.5). The other five Phase 1a curated entries — ``blur blur``,
``extend loop``, ``filter sweeping``, ``modify brassage``, and
``morph morph`` (sm1) — are *presumed* deterministic but have never
been byte-compared. Phase 4 Task 12 (process-output cache reactivation)
cannot proceed without that verification: a content-addressed cache
that materializes outputs by hardlink is only safe on byte-deterministic
entries. The high-level design doc moved this sweep from Phase 3 →
Phase 2 explicitly to gate Task 12.

The test runs each curated entry twice with a representative param
config on a synthetic input and byte-compares the outputs. To genuinely
exercise CDP twice — rather than measuring cache materialization — the
paired invocations use **two distinct ``cache_root`` paths**; the PVOC
cache (keyed on ``audio_sha256 + argv_discriminator + cdp_version``)
would otherwise short-circuit the second call.

On hash mismatch the diagnostic helper classifies the divergence as
``non_deterministic_samples`` (decoded sample arrays differ) or
``non_deterministic_header_only`` (samples equal, raw bytes differ —
likely an embedded timestamp or UUID in a chunk header). The
classification is embedded in the failure message so a CI failure is
self-explanatory.

Findings are pinned in ``docs/phase-2-determinism.md``. The
``DETERMINISM_EXPECTATIONS`` table below is the source of truth; any
change to it pairs with an update to that doc.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.pvoc import synth_for_audition
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.process import process_impl


_PARAMS_FIXTURE = Path(__file__).parent / "fixtures" / "determinism_params.json"


# Expectation table — pinning a status here is a curation decision and
# changes should pair with a docs/phase-2-determinism.md update. Do not
# flip an entry from "deterministic" to a "non_deterministic_*" value
# to make a failing test pass; that's a forensic finding and warrants
# human review per the Phase 1b handoff posture on novel CDP behavior.
DETERMINISM_EXPECTATIONS = {
    ("blur",   "blur"):     "deterministic",
    ("extend", "loop"):     "deterministic",
    ("filter", "sweeping"): "deterministic",
    ("modify", "brassage"): "deterministic",
    ("morph",  "morph"):    "deterministic",
}


class FakeContext:
    """Stub MCP Context — same swallow stub as ``test_acceptance.py``."""

    async def report_progress(self, *args, **kwargs):
        return None


def _make_noise_burst(seed: int) -> tuple[np.ndarray, int]:
    """2 s mono 44.1 kHz noise burst with exponential-decay envelope.

    Same shape as ``acceptance_env``'s frog stand-in. The seed
    parameterizes the underlying RNG so the morph morph case can use
    two distinguishable inputs (seed=42 primary, seed=43 secondary).
    """
    sr = 44100
    samples = int(sr * 2.0)
    rng = np.random.default_rng(seed=seed)
    noise = rng.standard_normal(samples).astype(np.float32) * 0.3
    envelope = np.exp(-3.0 * np.linspace(0.0, 1.0, samples)).astype(np.float32)
    return noise * envelope, sr


@pytest.fixture
def determinism_env(tmp_path, real_cdp_path):
    """Wire up dependencies and lay down two synthetic inputs.

    Mirrors ``acceptance_env`` with two differences:

    * Session name is ``determinism_sweep_v1.0`` — dotted, so the
      ``modify brassage`` parametrization also exercises the Task 6.1
      cwd-relative argv fix.
    * A second input ``frog_stand_in_b.wav`` (seed=43) is written for
      the ``morph morph`` two-input case.

    ``cache_base`` is returned instead of a single ``cache_root``; the
    test resolves two distinct sub-roots under it (``cache_a`` and
    ``cache_b``) so paired ``process_impl`` calls actually re-run CDP.
    """
    if real_cdp_path is None:
        pytest.skip(
            "Real CDP not configured. Set $CDP_PATH to a directory "
            "containing blur, pvoc, modify, extend, morph, and filter binaries."
        )

    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_base = tmp_path / "cdp_mcp_cache"
    cache_base.mkdir()

    sessions = SessionManager(sessions_root, lambda: cdp_config)
    latest_tracker = LatestTracker()
    knowledge = KnowledgeIndex.load()

    session_name = "determinism_sweep_v1.0"
    session, _created = sessions.set_active(session_name)

    primary, sr = _make_noise_burst(seed=42)
    sf.write(session.inputs_dir / "frog_stand_in.wav", primary, sr, subtype="FLOAT")
    secondary, _ = _make_noise_burst(seed=43)
    sf.write(session.inputs_dir / "frog_stand_in_b.wav", secondary, sr, subtype="FLOAT")

    return SimpleNamespace(
        sessions=sessions,
        session=session,
        session_name=session_name,
        latest_tracker=latest_tracker,
        knowledge=knowledge,
        cdp_config=cdp_config,
        cache_base=cache_base,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_params(program: str, mode: str) -> tuple[str | list[str], dict]:
    data = json.loads(_PARAMS_FIXTURE.read_text())
    entry = data[f"{program} {mode}"]
    return entry["input"], entry["params"]


async def _classify_byte_diff(
    path_a: Path,
    path_b: Path,
    env: SimpleNamespace,
    ctx: FakeContext,
) -> str:
    """Decide whether a byte mismatch is samples-level or header-only.

    For ``.wav`` outputs: read samples directly. For ``.ana`` outputs:
    audition-synth both via ``pvoc.synth_for_audition`` (itself byte-
    deterministic per Phase 1b §5.5.2, so any diff in the synthed wavs
    reflects a diff in the underlying frames). Samples are read into
    memory immediately after each synth call because both synth calls
    write to the same ``session.tmp_dir / "<stem>.wav"`` path — the
    second call would clobber the first otherwise.
    """
    suffix = path_a.suffix
    if suffix == ".wav":
        samples_a, sr_a = sf.read(path_a)
        samples_b, sr_b = sf.read(path_b)
    elif suffix == ".ana":
        cache_diag = env.cache_base / "cache_diag"
        cache_diag.mkdir(exist_ok=True)
        wav_a, _ = await synth_for_audition(
            path_a,
            env.session,
            env.cdp_config.cdp_path,
            cache_diag,
            env.cdp_config.version,
            ctx=ctx,
        )
        samples_a, sr_a = sf.read(wav_a)
        wav_b, _ = await synth_for_audition(
            path_b,
            env.session,
            env.cdp_config.cdp_path,
            cache_diag,
            env.cdp_config.version,
            ctx=ctx,
        )
        samples_b, sr_b = sf.read(wav_b)
    else:
        return f"unsupported_output_format:{suffix}"

    if sr_a == sr_b and np.array_equal(samples_a, samples_b):
        return "non_deterministic_header_only"
    return "non_deterministic_samples"


@pytest.mark.parametrize(
    ("program", "mode"),
    list(DETERMINISM_EXPECTATIONS.keys()),
    ids=[f"{p}_{m}" for (p, m) in DETERMINISM_EXPECTATIONS.keys()],
)
@pytest.mark.timeout(120)
async def test_determinism_sweep(determinism_env, program, mode):
    """Run one curated entry twice and byte-compare its outputs.

    Two distinct ``cache_root`` paths force CDP to re-run from scratch
    on the second invocation; otherwise PVOC cache hits would short-
    circuit the second call and we'd only be measuring cache
    materialization, not CDP-level determinism.
    """
    env = determinism_env
    ctx = FakeContext()
    cdp_provider = lambda: env.cdp_config  # noqa: E731

    input_arg, params = _load_params(program, mode)
    expectation = DETERMINISM_EXPECTATIONS[(program, mode)]

    cache_root_a = env.cache_base / "cache_a"
    cache_root_b = env.cache_base / "cache_b"
    cache_root_a.mkdir()
    cache_root_b.mkdir()

    deps_a = {
        "sessions": env.sessions,
        "knowledge_index": env.knowledge,
        "cdp_config_provider": cdp_provider,
        "latest_tracker": env.latest_tracker,
        "cache_root": cache_root_a,
    }
    deps_b = {**deps_a, "cache_root": cache_root_b}

    r_a = await process_impl(
        ctx, program=program, mode=mode, input=input_arg, params=params, **deps_a,
    )
    assert r_a["status"] == "ok", (
        f"{program} {mode} run A failed under '{env.session_name}': {r_a}"
    )

    r_b = await process_impl(
        ctx, program=program, mode=mode, input=input_arg, params=params, **deps_b,
    )
    assert r_b["status"] == "ok", (
        f"{program} {mode} run B failed under '{env.session_name}': {r_b}"
    )

    path_a = Path(r_a["output"])
    path_b = Path(r_b["output"])
    sha_a = _sha256(path_a)
    sha_b = _sha256(path_b)

    if sha_a == sha_b:
        observed = "deterministic"
    else:
        observed = await _classify_byte_diff(path_a, path_b, env, ctx)

    assert observed == expectation, (
        f"{program} {mode}: expected '{expectation}', observed '{observed}'.\n"
        f"  run A: sha256={sha_a}, output={path_a}\n"
        f"  run B: sha256={sha_b}, output={path_b}\n"
        f"  This is a forensic finding — do not flip the expectation "
        f"table without human review (see docs/phase-2-determinism.md)."
    )
