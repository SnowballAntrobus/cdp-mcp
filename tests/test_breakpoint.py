"""Tests for the breakpoint() DSL constructor (Phase 2 Task 6).

Three tiers:
  * Pure shape generators — structure, math, determinism (no CDP).
  * Validation pipeline — entry/param/capability/shape-args/range (no CDP).
  * End-to-end — breakpoint() output fed to process() against real CDP.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.config import detect_cdp
from cdp_mcp.graph import LatestTracker
from cdp_mcp.knowledge.loader import KnowledgeIndex
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import breakpoint as bp
from cdp_mcp.tools.breakpoint import breakpoint_impl
from cdp_mcp.tools.process import process_impl

_EPS = bp._EDGE_EPS


@pytest.fixture(scope="module")
def index() -> KnowledgeIndex:
    return KnowledgeIndex.load()


# ---------------------------------------------------------------------------
# Shape generators — structure + math
# ---------------------------------------------------------------------------


def _times(pts):
    return [p[0] for p in pts]


def _vals(pts):
    return [p[1] for p in pts]


def test_linear_two_points_exact():
    pts = bp._shape_linear(start=200, end=4000, duration_relative=1.0)
    assert pts == [[0.0, 200.0], [1.0, 4000.0]]


def test_linear_respects_duration_relative():
    pts = bp._shape_linear(start=0, end=10, duration_relative=0.5)
    assert pts[0][0] == 0.0
    assert pts[-1][0] == 0.5


def test_exponential_structure_and_endpoints():
    pts = bp._shape_exponential(
        start=0, end=100, duration_relative=1.0, curve=2.0, points=12
    )
    assert len(pts) == 12
    assert pts[0] == [0.0, 0.0]
    assert pts[-1][0] == 1.0
    assert pts[-1][1] == pytest.approx(100.0)
    assert _times(pts) == sorted(_times(pts))  # monotonic times


def test_exponential_curve_gt_1_is_concave_up():
    """curve > 1 → slow start: the midpoint value sits below the linear
    midpoint (which would be 50 for a 0→100 ramp)."""
    pts = bp._shape_exponential(
        start=0, end=100, duration_relative=1.0, curve=2.0, points=3
    )
    # points=3 → u = 0, 0.5, 1.0; midpoint value = 100 * 0.5**2 = 25.
    assert pts[1][1] == pytest.approx(25.0)


def test_exponential_curve_lt_1_is_concave_down():
    pts = bp._shape_exponential(
        start=0, end=100, duration_relative=1.0, curve=0.5, points=3
    )
    # midpoint value = 100 * 0.5**0.5 ≈ 70.71 > 50.
    assert pts[1][1] > 50.0


def test_sigmoid_endpoints_hit_exactly():
    pts = bp._shape_sigmoid(
        start=200, end=4000, duration_relative=1.0, steepness=6.0, points=12
    )
    assert pts[0][1] == pytest.approx(200.0)
    assert pts[-1][1] == pytest.approx(4000.0)


def test_sigmoid_midpoint_near_center():
    pts = bp._shape_sigmoid(
        start=0, end=100, duration_relative=1.0, steepness=6.0, points=3
    )
    # By symmetry the logistic midpoint normalizes to 0.5 → value 50.
    assert pts[1][1] == pytest.approx(50.0, abs=1e-6)


def test_pulse_train_alternates_low_high():
    pts = bp._shape_pulse_train(
        low=0.0, high=1.0, duration_relative=1.0, count=4, duty=0.5
    )
    vals = set(_vals(pts))
    assert vals == {0.0, 1.0}
    assert _times(pts) == sorted(_times(pts))


def test_pulse_train_has_sharp_edges():
    """Each transition is a straddle pair separated by exactly the edge
    epsilon — well above the compiler's 1e-6 dedup threshold."""
    pts = bp._shape_pulse_train(
        low=0.0, high=1.0, duration_relative=1.0, count=2, duty=0.5
    )
    # Find a falling edge: a [t-eps, high] immediately followed by [t, low].
    found_sharp = False
    for a, b in zip(pts, pts[1:], strict=False):
        gap = b[0] - a[0]
        if 0 < gap <= _EPS + 1e-9 and a[1] != b[1]:
            found_sharp = True
            assert gap > 1e-6  # clears dedup
    assert found_sharp


def test_step_explicit_values():
    pts = bp._shape_step(
        start=None, end=None, steps=None, values=[10, 20, 30],
        duration_relative=1.0,
    )
    assert set(_vals(pts)) == {10.0, 20.0, 30.0}
    assert pts[0][0] == 0.0
    assert pts[-1][0] == 1.0


def test_step_generated_form_level_count():
    pts = bp._shape_step(
        start=0, end=30, steps=4, values=None, duration_relative=1.0,
    )
    # 4 levels linearly: 0, 10, 20, 30.
    assert set(_vals(pts)) == {0.0, 10.0, 20.0, 30.0}


def test_random_reproducible_with_seed():
    a = bp._shape_random(low=0, high=1, duration_relative=1.0, points=8, seed=42)
    b = bp._shape_random(low=0, high=1, duration_relative=1.0, points=8, seed=42)
    assert a == b


def test_random_differs_across_seeds():
    a = bp._shape_random(low=0, high=1, duration_relative=1.0, points=8, seed=42)
    b = bp._shape_random(low=0, high=1, duration_relative=1.0, points=8, seed=43)
    assert a != b


def test_random_values_within_range():
    pts = bp._shape_random(low=5, high=10, duration_relative=1.0, points=20, seed=1)
    for _, v in pts:
        assert 5.0 <= v <= 10.0


def test_random_does_not_touch_global_rng():
    """Instance-scoped default_rng must not perturb numpy's global RNG —
    Task 2.5 found global RNG mutation is a contamination vector."""
    np.random.seed(123)
    before = np.random.get_state()[1][:5].copy()
    bp._shape_random(low=0, high=1, duration_relative=1.0, points=8, seed=42)
    after = np.random.get_state()[1][:5]
    assert (before == after).all()


# ---------------------------------------------------------------------------
# Validation pipeline
# ---------------------------------------------------------------------------


async def test_unknown_program_mode_not_curated(index):
    r = await breakpoint_impl(
        "linear", "nope", "nope", "x", start=0, end=1, knowledge_index=index
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "not_curated"


async def test_unknown_param(index):
    r = await breakpoint_impl(
        "linear", "filter", "sweeping", "nonexistent",
        start=0, end=1, knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "unknown_parameter"


async def test_not_breakpoint_capable_rejected(index):
    """filter sweeping.gain is not breakpoint-capable (Task 5)."""
    r = await breakpoint_impl(
        "linear", "filter", "sweeping", "gain",
        start=0.1, end=1.0, knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "param_breakpoint_not_capable"
    assert r["breakpoints"] is None


async def test_missing_shape_kwargs(index):
    """exponential needs start+end; omit them → breakpoint_shape_args."""
    r = await breakpoint_impl(
        "exponential", "filter", "sweeping", "lofrq", knowledge_index=index
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "breakpoint_shape_args"


async def test_unknown_shape(index):
    r = await breakpoint_impl(
        "zigzag", "filter", "sweeping", "lofrq",
        start=0, end=1, knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "breakpoint_shape_args"


async def test_anchor_over_max_fails(index):
    """acuity has max=1.0; an explicit end=5.0 is deliberate over-range →
    fail (not clamp)."""
    r = await breakpoint_impl(
        "linear", "filter", "sweeping", "acuity",
        start=0.1, end=5.0, knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "param_out_of_range"


async def test_anchor_below_min_fails(index):
    """acuity has min=0.0001; start=0 is below it → fail."""
    r = await breakpoint_impl(
        "linear", "filter", "sweeping", "acuity",
        start=0.0, end=0.5, knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "param_out_of_range"


async def test_in_range_anchors_succeed(index):
    r = await breakpoint_impl(
        "sigmoid", "filter", "sweeping", "acuity",
        start=0.1, end=0.9, knowledge_index=index,
    )
    assert r["status"] == "ok"
    assert r["point_count"] == 12
    assert r["target"] == "filter sweeping.acuity"


async def test_generated_value_clamped_with_warning(index, monkeypatch):
    """Defensive clamp path: force a shape generator to emit an over-range
    value while anchors stay in-range, and confirm clamp+warning (not fail).

    sweepfrq has max=200.0. We monkeypatch the linear generator to emit a
    value above max even though the anchors are within range."""
    def fake_linear(*, start, end, duration_relative):
        return [[0.0, start], [duration_relative, 9999.0]]  # over max=200

    monkeypatch.setattr(bp, "_shape_linear", fake_linear)
    r = await breakpoint_impl(
        "linear", "filter", "sweeping", "sweepfrq",
        start=1.0, end=50.0, knowledge_index=index,
    )
    assert r["status"] == "ok"
    assert any("clamped" in w for w in r["warnings"])
    # The 9999 got clamped down to the max.
    assert max(v for _, v in r["breakpoints"]) == 200.0


@pytest.mark.parametrize("dr", [1.5, 2.0])
async def test_duration_relative_over_one_rejected(index, dr):
    """duration_relative > 1 would make generated times exceed the
    compiler's relative [0,1] range — guarded early."""
    r = await breakpoint_impl(
        "linear", "filter", "sweeping", "lofrq",
        start=200, end=4000, duration_relative=dr, knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "breakpoint_shape_args"


# ---------------------------------------------------------------------------
# custom shape — agent-authored points with the same early validation
# ---------------------------------------------------------------------------


async def test_custom_happy_path_sorted(index):
    """Unsorted input is returned sorted by time; values preserved exactly."""
    r = await breakpoint_impl(
        "custom", "filter", "sweeping", "lofrq",
        pairs=[[0.5, 4000], [0.0, 200], [1.0, 300]],
        knowledge_index=index,
    )
    assert r["status"] == "ok"
    assert r["breakpoints"] == [[0.0, 200.0], [0.5, 4000.0], [1.0, 300.0]]
    assert r["point_count"] == 3
    assert r["target"] == "filter sweeping.lofrq"


async def test_custom_non_capable_param_rejected(index):
    r = await breakpoint_impl(
        "custom", "filter", "sweeping", "gain",
        pairs=[[0.0, 0.1], [1.0, 1.0]], knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "param_breakpoint_not_capable"
    assert r["breakpoints"] is None


async def test_custom_missing_pairs(index):
    r = await breakpoint_impl(
        "custom", "filter", "sweeping", "lofrq", knowledge_index=index
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "breakpoint_shape_args"


async def test_custom_single_point_rejected(index):
    r = await breakpoint_impl(
        "custom", "filter", "sweeping", "lofrq",
        pairs=[[0.0, 200]], knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "breakpoint_shape_args"


@pytest.mark.parametrize("bad_pairs", [
    [[0.0, 200], [1.0]],          # wrong length
    [[0.0, 200], 5],              # bare number
    [[0.0, 200], [1.0, "x"]],     # non-numeric value
    [[0.0, 200], ["x", 300]],     # non-numeric time
    [[0.0, 200], [1.0, True]],    # bool value (rejected like the compiler)
])
async def test_custom_malformed_pair_value_type(index, bad_pairs):
    r = await breakpoint_impl(
        "custom", "filter", "sweeping", "lofrq",
        pairs=bad_pairs, knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "param_breakpoint_value_type"


async def test_custom_time_out_of_range(index):
    r = await breakpoint_impl(
        "custom", "filter", "sweeping", "lofrq",
        pairs=[[0.0, 200], [1.5, 300]], knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "param_breakpoint_time_out_of_range"


async def test_custom_value_out_of_range_fails(index):
    """acuity max=1.0; a custom point at 5.0 is explicit intent → fail."""
    r = await breakpoint_impl(
        "custom", "filter", "sweeping", "acuity",
        pairs=[[0.0, 0.1], [1.0, 5.0]], knowledge_index=index,
    )
    assert r["status"] == "failed"
    assert r["errors"][0]["type"] == "param_out_of_range"


# ---------------------------------------------------------------------------
# End-to-end: breakpoint() → process() against real CDP
# ---------------------------------------------------------------------------


@pytest.fixture
def cdp_env(tmp_path, real_cdp_path):
    """Minimal session wiring for the breakpoint→process round-trip."""
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
    session, _ = sessions.set_active("breakpoint_e2e_v1.0")

    sr = 44100
    n = int(sr * 2.0)
    rng = np.random.default_rng(seed=42)
    noise = rng.standard_normal(n).astype(np.float32) * 0.3
    env = np.exp(-3.0 * np.linspace(0.0, 1.0, n)).astype(np.float32)
    sf.write(session.inputs_dir / "in.wav", noise * env, sr, subtype="FLOAT")

    return SimpleNamespace(
        sessions=sessions, session=session, latest_tracker=latest_tracker,
        knowledge=knowledge, cdp_config=cdp_config, cache_root=cache_root,
    )


class _FakeCtx:
    async def report_progress(self, *a, **kw):
        return None


@pytest.mark.timeout(60)
async def test_breakpoint_into_process_records_lineage(cdp_env):
    """The full loop: build an exponential lofrq envelope, feed it to
    process(), confirm CDP runs and the compiled breakpoint is recorded."""
    import json

    env = cdp_env
    knowledge = env.knowledge

    bp_result = await breakpoint_impl(
        "exponential", "filter", "sweeping", "lofrq",
        start=200, end=4000, knowledge_index=knowledge,
    )
    assert bp_result["status"] == "ok"
    breakpoints = bp_result["breakpoints"]

    ctx = _FakeCtx()
    deps = dict(
        sessions=env.sessions,
        knowledge_index=knowledge,
        cdp_config_provider=lambda: env.cdp_config,
        latest_tracker=env.latest_tracker,
        cache_root=env.cache_root,
    )
    r = await process_impl(
        ctx, program="filter", mode="sweeping", input="in.wav",
        params={
            "acuity": 0.1, "gain": 0.44, "lofrq": breakpoints,
            "hifrq": 4000.0, "sweepfrq": 1.0,
        },
        **deps,
    )
    assert r["status"] == "ok", r["errors"]
    graph_id = r["context"]["active_graph"]
    doc = json.loads(
        (env.session.graphs_dir / graph_id / "lineage.json").read_text()
    )
    main_node = next(
        n for n in doc["nodes"].values() if n["argv"][0].endswith("/filter")
    )
    assert "lofrq" in main_node["compiled_breakpoints"]
    assert main_node["compiled_breakpoints"]["lofrq"]["sha256"] != ""


@pytest.mark.timeout(60)
async def test_rejection_never_reaches_process(cdp_env):
    """A non-capable param fails at breakpoint() — the LLM never builds an
    envelope to pass to process()."""
    env = cdp_env
    r = await breakpoint_impl(
        "linear", "filter", "sweeping", "gain",
        start=0.1, end=1.0, knowledge_index=env.knowledge,
    )
    assert r["status"] == "failed"
    assert r["breakpoints"] is None
    assert r["errors"][0]["type"] == "param_breakpoint_not_capable"


@pytest.mark.timeout(60)
async def test_custom_into_process_records_lineage(cdp_env):
    """A freeform custom envelope flows through process() the same as a
    named shape — the full 'verbal description → arbitrary shape' loop."""
    import json

    env = cdp_env
    knowledge = env.knowledge

    bp_result = await breakpoint_impl(
        "custom", "filter", "sweeping", "lofrq",
        pairs=[[0.0, 200], [0.5, 4000], [0.51, 4000], [1.0, 300]],
        knowledge_index=knowledge,
    )
    assert bp_result["status"] == "ok"
    breakpoints = bp_result["breakpoints"]

    ctx = _FakeCtx()
    deps = dict(
        sessions=env.sessions,
        knowledge_index=knowledge,
        cdp_config_provider=lambda: env.cdp_config,
        latest_tracker=env.latest_tracker,
        cache_root=env.cache_root,
    )
    r = await process_impl(
        ctx, program="filter", mode="sweeping", input="in.wav",
        params={
            "acuity": 0.1, "gain": 0.44, "lofrq": breakpoints,
            "hifrq": 4000.0, "sweepfrq": 1.0,
        },
        **deps,
    )
    assert r["status"] == "ok", r["errors"]
    graph_id = r["context"]["active_graph"]
    doc = json.loads(
        (env.session.graphs_dir / graph_id / "lineage.json").read_text()
    )
    main_node = next(
        n for n in doc["nodes"].values() if n["argv"][0].endswith("/filter")
    )
    assert "lofrq" in main_node["compiled_breakpoints"]
