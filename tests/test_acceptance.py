"""End-to-end acceptance test for Phase 1a.

Exercises the full Phase 1a workflow against real CDP under a dotted
session name (``frog_acceptance_v1.0``) — locks in Task 6.1's
path-mangling fix as a permanent regression check. Skipped cleanly when
``$CDP_PATH`` isn't set or doesn't contain the required binaries
(see the ``real_cdp_path`` fixture in ``conftest.py``).

The per-tool tests in ``test_execute.py`` / ``test_process.py`` /
``test_visualize.py`` / ``test_analyze.py`` use ``fake_subprocess.py``
to cover orchestration (graph dirs, lineage, latest tracker, security
boundary, PVOC auto-insertion, envelope shape). This test covers the
irreplaceable bit those fakes can't: real CDP binaries actually accepting
our argv shapes and producing audible audio across the curated chain.

Assertions are deliberately structural — graph dirs exist, lineage is
well-formed, files have plausible sizes, ``latest`` updates correctly,
cross-graph references resolve. Exact numerical assertions (RMS values,
PNG pixel dimensions) live in the per-tool tests; this test asks "did
the chain run cleanly," not "did the chain produce specific values."
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools.analyze import analyze_impl
from cdp_mcp.tools.process import process_impl
from cdp_mcp.tools.visualize import visualize_impl


class FakeContext:
    """Stub MCP Context for in-process invocation.

    ``run_cdp_command`` and ``run_with_progress`` call
    ``ctx.report_progress(progress, total, message)`` on a 5-second cadence
    to keep Claude Desktop's MCP client connection alive during long
    subprocess invocations. We're not running over MCP here, so swallow
    silently.
    """

    async def report_progress(self, *args, **kwargs):  # noqa: D401 — stub
        return None


@pytest.fixture
def acceptance_env(tmp_path, real_cdp_path):
    """Wire up dependencies the way ``server.py`` does at startup.

    Skips at fixture scope when CDP isn't available so the test body
    never runs in that case. The autouse ``_isolated_sessions_root``
    fixture already redirects ``$CDP_MCP_SESSIONS_ROOT`` for this run;
    we additionally root the SessionManager under ``tmp_path`` so each
    test invocation gets a clean slate.
    """
    if real_cdp_path is None:
        pytest.skip(
            "Real CDP not configured. Set $CDP_PATH to a directory "
            "containing blur, pvoc, modify, and extend binaries."
        )

    cdp_config = detect_cdp()
    sessions_root = tmp_path / "cdp_sessions"
    sessions_root.mkdir()
    cache_root = tmp_path / "cdp_mcp_cache"
    cache_root.mkdir()

    sessions = SessionManager(sessions_root, lambda: cdp_config)
    latest_tracker = LatestTracker()
    knowledge = KnowledgeIndex.load()

    # Dotted session name — exercises Task 6.1's path-mangling fix.
    session_name = "frog_acceptance_v1.0"
    session, _created = sessions.set_active(session_name)

    # Synthetic ~2-second textured noise burst as a frog stand-in. Deterministic
    # seed so the test is reproducible across machines. Mono, 44.1 kHz, with
    # a decaying envelope to give the spectral ops something to chew on.
    sr = 44100
    duration_s = 2.0
    samples = int(sr * duration_s)
    rng = np.random.default_rng(seed=42)
    noise = rng.standard_normal(samples).astype(np.float32) * 0.3
    envelope = np.exp(-3.0 * np.linspace(0.0, 1.0, samples)).astype(np.float32)
    audio = noise * envelope

    input_filename = "frog_stand_in.wav"
    sf.write(session.inputs_dir / input_filename, audio, sr, subtype="FLOAT")

    return SimpleNamespace(
        sessions=sessions,
        session=session,
        session_name=session_name,
        latest_tracker=latest_tracker,
        knowledge=knowledge,
        cdp_config=cdp_config,
        cache_root=cache_root,
        input_filename=input_filename,
    )


@pytest.mark.timeout(180)
async def test_frog_acceptance_chain(acceptance_env):
    """Canonical frog chain end-to-end against real CDP.

    Chain: blur blur → visualize → analyze → modify brassage →
    extend loop → visualize → analyze → cross-graph visualize.

    Timeout raised from the suite-wide 30 s default because the chain
    fires 6+ real CDP subprocess invocations plus librosa feature work,
    each well under a second but cumulatively above the default. 180 s
    is a generous ceiling — a healthy run finishes in well under 30.
    """
    env = acceptance_env
    ctx = FakeContext()
    cdp_provider = lambda: env.cdp_config  # noqa: E731

    process_deps = {
        "sessions": env.sessions,
        "knowledge_index": env.knowledge,
        "cdp_config_provider": cdp_provider,
        "latest_tracker": env.latest_tracker,
        "cache_root": env.cache_root,
    }
    obs_deps = {
        "sessions": env.sessions,
        "cdp_config_provider": cdp_provider,
        "latest_tracker": env.latest_tracker,
        "cache_root": env.cache_root,
    }

    # ------------------------------------------------------------------
    # Step 1: blur blur — spectral op on a .wav. Auto-inserts pvoc anal.
    # ------------------------------------------------------------------
    r1 = await process_impl(
        ctx,
        program="blur",
        mode="blur",
        input=env.input_filename,
        params={"blurring": 10},
        **process_deps,
    )
    assert r1["status"] == "ok", f"blur blur failed: {r1}"
    assert r1["output"].endswith(".ana")
    graph_1_id = r1["context"]["active_graph"]
    graph_1_dir = env.session.graphs_dir / graph_1_id

    node_index_1 = json.loads((graph_1_dir / "node_index.json").read_text())
    assert set(node_index_1.keys()) == {"n1", "n2"}, (
        f"Expected n1 (pvoc) + n2 (blur); got {list(node_index_1.keys())}"
    )
    assert "pvoc" in node_index_1["n1"]
    assert "blur" in node_index_1["n2"]
    for required in ("graph.json", "node_index.json", "lineage.json"):
        assert (graph_1_dir / required).is_file(), (
            f"Missing {required} in {graph_1_dir}"
        )

    # ------------------------------------------------------------------
    # Step 2: visualize the blur output — auto-synths .ana → temp .wav.
    # ------------------------------------------------------------------
    vis_1 = await visualize_impl(ctx, target="latest", **obs_deps)
    assert isinstance(vis_1, list) and len(vis_1) == 2, (
        f"Expected [Image, envelope]; got {vis_1}"
    )
    vis_envelope_1 = vis_1[1]
    assert vis_envelope_1["status"] == "ok"
    assert vis_envelope_1["auto_synthed"] is True
    png_path_1 = Path(vis_envelope_1["output"])
    assert png_path_1.is_file()
    assert png_path_1.stat().st_size > 10_000

    # ------------------------------------------------------------------
    # Step 3: analyze the blur output — same auto-synth path.
    # ------------------------------------------------------------------
    ana_1 = await analyze_impl(ctx, target="latest", **obs_deps)
    assert ana_1["status"] == "ok"
    assert "analysis" in ana_1
    assert ana_1["analysis"]["duration_s"] > 0
    assert ana_1["analysis"]["n_channels"] == 1

    # ------------------------------------------------------------------
    # Step 4: modify brassage — time op on .ana, auto-inserts pvoc synth.
    # The dotted session name (frog_acceptance_v1.0) is what makes this
    # the Task 6.1 regression check: before the cwd-relative argv fix,
    # brassage crashed with SIGILL on any absolute path whose ancestry
    # contained a dot.
    # ------------------------------------------------------------------
    r2 = await process_impl(
        ctx,
        program="modify",
        mode="brassage",
        input="latest",
        params={"velocity": 0.5},
        **process_deps,
    )
    assert r2["status"] == "ok", (
        f"modify brassage failed under dotted session name "
        f"'{env.session_name}' (Task 6.1 regression): {r2}"
    )
    assert r2["output"].endswith(".wav")
    graph_2_id = r2["context"]["active_graph"]
    graph_2_dir = env.session.graphs_dir / graph_2_id
    node_index_2 = json.loads((graph_2_dir / "node_index.json").read_text())
    assert "pvoc" in node_index_2["n1"]
    assert "brassage" in node_index_2["n2"]

    # Cross-node lineage: brassage's input should source_node="n1" (the
    # auto-inserted pvoc synth from the same graph).
    lineage_2 = json.loads((graph_2_dir / "lineage.json").read_text())
    brassage_inputs = lineage_2["nodes"]["n2"]["inputs"]
    assert any(
        inp.get("source_node") == "n1" for inp in brassage_inputs
    ), f"brassage lineage missing source_node='n1': {brassage_inputs}"

    # ------------------------------------------------------------------
    # Step 5: extend loop — time op on .wav, no PVOC needed.
    # ------------------------------------------------------------------
    r3 = await process_impl(
        ctx,
        program="extend",
        mode="loop",
        input="latest",
        params={"cnt": 4, "start": 0.0, "len": 300.0},  # len is ms, not s
        **process_deps,
    )
    assert r3["status"] == "ok", f"extend loop failed: {r3}"
    graph_3_id = r3["context"]["active_graph"]
    graph_3_dir = env.session.graphs_dir / graph_3_id
    node_index_3 = json.loads((graph_3_dir / "node_index.json").read_text())
    assert set(node_index_3.keys()) == {"n1"}, (
        f"Expected single n1 node (no PVOC); got {list(node_index_3.keys())}"
    )

    # ------------------------------------------------------------------
    # Step 6: visualize + analyze the final wav. No auto-synth this time.
    # ------------------------------------------------------------------
    vis_final = await visualize_impl(ctx, target="latest", **obs_deps)
    assert vis_final[1]["status"] == "ok"
    assert vis_final[1]["auto_synthed"] is False

    ana_final = await analyze_impl(ctx, target="latest", **obs_deps)
    assert ana_final["status"] == "ok"
    assert ana_final["analysis"]["duration_s"] > 0

    # ------------------------------------------------------------------
    # Step 7: cross-graph reference — visualize the auto-inserted pvoc
    # synth from graph 2 directly. Exercises <graph_id>:nN resolution.
    # ------------------------------------------------------------------
    vis_cross = await visualize_impl(
        ctx, target=f"{graph_2_id}:n1", **obs_deps
    )
    assert vis_cross[1]["status"] == "ok", (
        f"Cross-graph reference failed: {vis_cross}"
    )

    # ------------------------------------------------------------------
    # Final structural assertions.
    # ------------------------------------------------------------------
    visualizations_dir = env.session.root / "visualizations"
    pngs = list(visualizations_dir.glob("*.png"))
    # Three visualize calls in the chain: after blur (step 2), after
    # extend loop (step 6), and cross-graph on graph_2:n1 (step 7).
    assert len(pngs) >= 3, (
        f"Expected ≥3 PNGs from visualize calls; got {len(pngs)}"
    )
    graph_dirs = list(env.session.graphs_dir.iterdir())
    assert len(graph_dirs) == 3, (
        f"Expected 3 graph dirs (blur, brassage, extend); got {len(graph_dirs)}"
    )
