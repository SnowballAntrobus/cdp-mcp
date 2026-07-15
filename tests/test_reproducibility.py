"""Reproducibility round-trip — the provenance layer's load-bearing test.

Runs a real ``process()`` (blur blur on synthesized noise), then re-runs
the EXACT argv recorded in the output node's ``lineage.json`` via a bare
``subprocess`` in a fresh output directory, and asserts the two outputs
decode to bit-identical samples. This proves the lineage record alone is
sufficient to regenerate an output — no engine state required.

Comparison is over DECODED SAMPLES, not raw bytes: CDP r8 embeds a tick
counter in output headers (``docs/forensics.md`` P2-1), so raw files may
differ across tick boundaries while samples stay bit-identical. Spectral
``.ana`` outputs can't be decoded by libsndfile, so both sides are
rendered to wav via ``pvoc synth`` first (itself sample-deterministic —
forensics 5.5.2), then compared.

Gated on real CDP via the ``real_cdp_path`` fixture (skips cleanly when
``$CDP_PATH`` is unset); fixture pattern copied from
``tests/test_curation_formulas.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.process import process_impl

_SR = 44100


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


@pytest.fixture
def cdp_env(tmp_path, real_cdp_path):
    if real_cdp_path is None:
        pytest.skip("Real CDP not configured.")
    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: cdp_config)
    latest_tracker = LatestTracker()
    knowledge = KnowledgeIndex.load()
    session, _ = sessions.set_active("reproducibility_v1.0")
    return SimpleNamespace(
        sessions=sessions, session=session, latest_tracker=latest_tracker,
        knowledge=knowledge, cdp_config=cdp_config, cache_root=cache_root,
    )


def _write_noise(path, dur_s, seed=0):
    n = int(_SR * dur_s)
    sig = np.random.default_rng(seed).standard_normal(n).astype(np.float32) * 0.2
    sf.write(path, sig, _SR, subtype="FLOAT")


def _run_argv(argv: list[str], cwd: Path) -> None:
    """Run one recorded/derived argv from the session root, loudly."""
    proc = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, (
        f"argv {argv} exited {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def _decoded_sample_sha256(env, path: Path) -> str:
    """sha256 over decoded samples (+ samplerate), header-independent.

    ``.ana`` files are synthesized to wav via ``pvoc synth`` first (CDP
    refuses to overwrite, so the synth target must be fresh)."""
    p = Path(path)
    if p.suffix.lower() == ".ana":
        wav = p.with_name(p.stem + "_synthcheck.wav")
        assert not wav.exists()
        _run_argv(
            [
                str(env.cdp_config.cdp_path / "pvoc"),
                "synth",
                os.path.relpath(p, env.session.root),
                os.path.relpath(wav, env.session.root),
            ],
            cwd=env.session.root,
        )
        p = wav
    data, sr = sf.read(str(p), dtype="float32", always_2d=True)
    h = hashlib.sha256()
    h.update(str(sr).encode("ascii"))
    h.update(data.tobytes())
    return h.hexdigest()


@pytest.mark.timeout(120)
async def test_lineage_argv_regenerates_identical_samples(cdp_env):
    env = cdp_env
    _write_noise(env.session.inputs_dir / "in.wav", 2.0)

    # 1. Real process(): blur blur auto-PVOCs in.wav -> n1 (.ana) and
    # runs the main op -> n2 (.ana).
    r = await process_impl(
        _FakeCtx(), program="blur", mode="blur", input="in.wav",
        params={"blurring": 10},
        sessions=env.sessions, knowledge_index=env.knowledge,
        cdp_config_provider=lambda: env.cdp_config,
        latest_tracker=env.latest_tracker, cache_root=env.cache_root,
    )
    assert r["status"] == "ok", r["errors"]

    # 2. Read the output node's lineage record.
    ref = env.latest_tracker.latest
    assert ref is not None
    graph_id, node_id = ref.split(":", 1)
    lineage_doc = json.loads(
        (env.session.graphs_dir / graph_id / "lineage.json").read_text(
            encoding="utf-8"
        )
    )
    node = lineage_doc["nodes"][node_id]
    argv = node["argv"]
    original_out = Path(node["output_path"])
    assert original_out.exists()

    # 3. Re-run the EXACT argv with only the output path swapped into a
    # fresh directory. cwd = session root so the cwd-relative input
    # paths the engine records (brassage path-mangling defense,
    # forensics 5.1.6) resolve exactly as they did in the real run.
    fresh = env.session.tmp_dir / "repro"
    fresh.mkdir(parents=True)
    rerun_out = fresh / original_out.name
    rel_original = os.path.relpath(original_out, env.session.root)
    out_positions = [
        i for i, a in enumerate(argv)
        if a in (rel_original, str(original_out))
    ]
    assert len(out_positions) == 1, (
        f"expected exactly one argv element naming the output; argv={argv}"
    )
    rerun_argv = list(argv)
    rerun_argv[out_positions[0]] = os.path.relpath(rerun_out, env.session.root)
    _run_argv(rerun_argv, cwd=env.session.root)
    assert rerun_out.exists()
    assert rerun_out.stat().st_size > 0

    # 4. Decoded-sample equivalence (raw bytes may legitimately differ
    # across CDP tick-counter boundaries — P2-1 — so they are NOT
    # compared).
    sha_original = _decoded_sample_sha256(env, original_out)
    sha_rerun = _decoded_sample_sha256(env, rerun_out)
    assert sha_original == sha_rerun, (
        "re-running the lineage argv produced different decoded samples — "
        "the provenance record is not sufficient to regenerate this output."
    )
