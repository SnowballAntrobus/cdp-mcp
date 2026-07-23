"""Phase 6b usage tripwire — the stereo seed-link trigger.

The dual-mono seed-link machinery is deferred behind a usage trigger:
a mono-only SEEDED stochastic entry receiving stereo material
(docs/phase-6-design.md §Reevaluation item 3). These tests pin the
tripwire that instruments that exact occurrence: validation returns a
structured ``stereo_seed_link_missing`` error whose fix instructs the
agent to notify the user (each report is the usage evidence the build
decision waits on) and carries the manual split/same-seed/merge
workaround. Non-seeded mono entries must NOT trip it — they keep the
ordinary runtime channel_mismatch path.
"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.node_validation import validate_node

_SR = 44100


@pytest.fixture
def env(tmp_path):
    cdp_dir = (tmp_path / "cdp").resolve()
    cdp_dir.mkdir()
    for name in ("scramble", "quirk", "pvoc"):
        stub = cdp_dir / name
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)
    cdp_cfg = CDPConfig(
        cdp_path=cdp_dir, version="fake",
        detected_binaries=["scramble", "quirk", "pvoc"],
    )
    sessions = SessionManager((tmp_path / "roots").resolve(), lambda: cdp_cfg)
    session, _ = sessions.set_active("seedlink_v1")
    rng = np.random.default_rng(seed=3)
    stereo = (rng.standard_normal((_SR, 2)) * 0.2).astype(np.float32)
    sf.write(session.inputs_dir / "st.wav", stereo, _SR, subtype="FLOAT")
    mono = (rng.standard_normal(_SR) * 0.2).astype(np.float32)
    sf.write(session.inputs_dir / "mono.wav", mono, _SR, subtype="FLOAT")
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    return {
        "session": session,
        "cdp": cdp_cfg,
        "knowledge": KnowledgeIndex.load(),
        "tracker": LatestTracker(),
        "cache_root": cache_root,
    }


async def _validate(env, entry, input_name, params):
    return await validate_node(
        ctx=None,
        entry=entry,
        inputs=[input_name],
        params=params,
        output_name=None,
        timeout_seconds=30.0,
        session=env["session"],
        cdp=env["cdp"],
        latest_tracker=env["tracker"],
        cache_root=env["cache_root"],
        dry_run=True,
    )


async def test_seeded_mono_entry_on_stereo_trips_the_tripwire(env):
    entry = env["knowledge"].get("scramble", "scramble", 9)
    assert entry.channel_constraint == "mono" and "seed" in entry.parameters
    vr = await _validate(env, entry, "st.wav", {"seed": 5})
    types = [e.type for e in vr.errors]
    assert "stereo_seed_link_missing" in types, types
    (err,) = [e for e in vr.errors if e.type == "stereo_seed_link_missing"]
    # The agent-facing contract: notify the user + the manual workaround.
    assert "NOTIFY THE USER" in err.fix
    assert "housekeep chans 3" in err.fix
    assert "SAME seed" in err.fix
    assert "submix interleave" in err.fix
    assert "2 channels" in err.message


async def test_seeded_mono_entry_on_mono_does_not_trip(env):
    entry = env["knowledge"].get("scramble", "scramble", 9)
    vr = await _validate(env, entry, "mono.wav", {"seed": 5})
    assert "stereo_seed_link_missing" not in [e.type for e in vr.errors]


async def test_unseeded_mono_entry_on_stereo_does_not_trip(env):
    # quirk quirk 1 is mono-only but has NO seed param — the seed-link
    # machinery could not help it (nothing to link), so the ordinary
    # runtime channel_mismatch path applies instead.
    entry = env["knowledge"].get("quirk", "quirk", 1)
    assert entry.channel_constraint == "mono"
    assert "seed" not in entry.parameters
    vr = await _validate(env, entry, "st.wav", {"powfac": 0.7})
    assert "stereo_seed_link_missing" not in [e.type for e in vr.errors]
