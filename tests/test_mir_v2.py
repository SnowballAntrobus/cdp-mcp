"""MIR v2 upgrade tests (docs/mir-gap-analysis.md).

Scorecard: flatness_db separates noise from tone by >30 dB where
centroid/zcr conflate the two; rolloff-85 orders low tone < high tone <
noise; crest reads transient-ness. Verbose: the 16-point trajectory
sees a scramble-like sequence that whole-file means are blind to;
inharmonicity separates detuned partials from a harmonic series;
stereo_width separates dual-mono from decorrelated stereo; pyin f0
lands on a 220 Hz sine (generous tolerances — platform variance).
Cache keys are bumped to v2, and cluster() with the 33-dim vector is
still deterministic and still separates test_cluster.py's three
synthetic groups.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP

# Import analysis first (it imports visualization) to pin matplotlib's
# backend — same import-order rule as test_analysis.py.
from cdp_mcp.analysis import extract_scorecard, extract_verbose
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import analyze as analyze_module
from cdp_mcp.tools import cluster as cluster_module

_SR = 22050

# Stretched-partial multipliers — bell-like, off the harmonic series
# (the stretch spectrum claim from gap analysis §3.b).
_DETUNED_MULTIPLIERS = [1.0, 2.13, 3.29, 4.48, 5.71, 6.97, 8.27, 9.61]


# ---------------------------------------------------------------------------
# Synthetic material
# ---------------------------------------------------------------------------


def _sine(freq: float, seconds: float = 2.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(_SR * seconds)) / _SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _partials(multipliers: list[float], f0: float = 220.0, seconds: float = 2.0) -> np.ndarray:
    """Sum of partials at ``f0 * multipliers`` with 1/n amplitudes."""
    t = np.arange(int(_SR * seconds)) / _SR
    y = np.zeros_like(t)
    for i, m in enumerate(multipliers):
        y += (1.0 / (i + 1)) * np.sin(2 * np.pi * f0 * m * t)
    return (0.4 * y / np.abs(y).max()).astype(np.float32)


def _noise(seconds: float = 2.0, amp: float = 0.3, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(int(_SR * seconds))).astype(np.float32)


def _click_train(seconds: float = 2.0, rate_hz: float = 6.0) -> np.ndarray:
    """4 ms noise-burst clicks — the gap analysis's clicks.wav recipe."""
    rng = np.random.default_rng(1)
    y = np.zeros(int(_SR * seconds), dtype=np.float32)
    burst = int(0.004 * _SR)
    for i in range(0, y.size, int(_SR / rate_hz)):
        n = min(burst, y.size - i)
        y[i : i + n] = 0.8 * rng.standard_normal(n).astype(np.float32)
    return y


def _scramble_like(seconds: float = 2.0, n_segments: int = 8) -> np.ndarray:
    """Concatenated different-frequency segments (200 / 4000 Hz
    alternating) — the seq.wav pattern whose centroid trajectory a
    whole-file mean cannot see (gap analysis §3.f)."""
    seg = int(_SR * seconds) // n_segments
    t = np.arange(seg) / _SR
    parts = [
        (0.5 * np.sin(2 * np.pi * (200.0 if i % 2 == 0 else 4000.0) * t))
        for i in range(n_segments)
    ]
    return np.concatenate(parts).astype(np.float32)


def _write(path: Path, y: np.ndarray) -> Path:
    sf.write(str(path), y, _SR)
    return path


def _total_variation(values: list[float]) -> float:
    return float(np.abs(np.diff(np.asarray(values))).sum())


# ---------------------------------------------------------------------------
# Scorecard v2 fields
# ---------------------------------------------------------------------------


def test_flatness_db_separates_noise_from_sine(tmp_path):
    """The D1 axis: >30 dB of separation where centroid/zcr conflate
    "noisier" with "brighter" (gap analysis §3.a)."""
    s_noise = extract_scorecard(_write(tmp_path / "noise.wav", _noise()))
    s_sine = extract_scorecard(_write(tmp_path / "sine.wav", _sine(220.0)))
    assert s_noise.spectral_flatness_db - s_sine.spectral_flatness_db > 30.0
    # Absolute reads match the docstring guidance: noise near 0 dB,
    # pitched material very negative.
    assert s_noise.spectral_flatness_db > -12.0
    assert s_sine.spectral_flatness_db < -40.0
    assert s_sine.spectral_flatness_db >= -120.0  # floored, JSON-finite


def test_rolloff85_sane_ordering(tmp_path):
    """Spectral edge orders low tone < high tone < noise, inside (0, sr/2]."""
    lo = extract_scorecard(_write(tmp_path / "lo.wav", _sine(220.0)))
    hi = extract_scorecard(_write(tmp_path / "hi.wav", _sine(2000.0)))
    wide = extract_scorecard(_write(tmp_path / "noise.wav", _noise()))
    assert 0.0 < lo.spectral_rolloff85_hz < hi.spectral_rolloff85_hz
    assert hi.spectral_rolloff85_hz < wide.spectral_rolloff85_hz <= _SR / 2
    # A pure sine's rolloff sits near the sine itself (±1 bin fuzz).
    assert lo.spectral_rolloff85_hz == pytest.approx(220.0, abs=60.0)


def test_crest_db_click_train_vs_sustained_tone(tmp_path):
    clicks = extract_scorecard(_write(tmp_path / "clicks.wav", _click_train()))
    tone = extract_scorecard(_write(tmp_path / "tone.wav", _sine(220.0)))
    assert clicks.crest_db is not None and tone.crest_db is not None
    assert clicks.crest_db > tone.crest_db + 10.0
    # Derivation is exactly peak - RMS.
    assert clicks.crest_db == pytest.approx(clicks.peak_dbfs - clicks.rms_db)


def test_crest_db_none_for_digital_silence(tmp_path):
    silent = tmp_path / "silent.wav"
    sf.write(str(silent), np.zeros(int(_SR * 1.0), dtype=np.float32), _SR)
    s = extract_scorecard(silent)
    assert s.peak_dbfs is None
    assert s.crest_db is None


# ---------------------------------------------------------------------------
# Verbose v2 block
# ---------------------------------------------------------------------------


def test_trajectory_shape_and_lengths(tmp_path):
    v = extract_verbose(_write(tmp_path / "sine.wav", _sine(220.0)))
    traj = v["trajectory"]
    assert traj["points"] == 16
    for key in ("rms_db", "centroid_hz", "flatness_db"):
        assert len(traj[key]) == 16
        assert all(x == round(x, 2) for x in traj[key])  # 2 dp
    assert all(x >= -120.0 for x in traj["rms_db"])  # floored


def test_trajectory_short_file_degrades_gracefully(tmp_path):
    v = extract_verbose(_write(tmp_path / "short.wav", _sine(440.0, seconds=0.15)))
    traj = v["trajectory"]
    assert 4 <= traj["points"] < 16
    for key in ("rms_db", "centroid_hz", "flatness_db"):
        assert len(traj[key]) == traj["points"]


def test_trajectory_total_variation_scramble_vs_steady(tmp_path):
    """The D7 fix: a scramble-like sequence and a steady tone are nearly
    identical in whole-file means, but the centroid trajectory's total
    variation separates them by orders of magnitude (§3.f)."""
    v_seq = extract_verbose(_write(tmp_path / "seq.wav", _scramble_like()))
    v_steady = extract_verbose(_write(tmp_path / "steady.wav", _sine(200.0)))
    tv_seq = _total_variation(v_seq["trajectory"]["centroid_hz"])
    tv_steady = _total_variation(v_steady["trajectory"]["centroid_hz"])
    assert tv_seq > 5000.0  # measured ~26 kHz
    assert tv_seq > 10.0 * tv_steady  # measured ratio ~400x


def test_inharmonicity_detuned_partials_vs_harmonic(tmp_path):
    """The D6 axis: partials off the harmonic series score well above a
    true harmonic series (§3.b: 0.0019 -> 0.0140 on stretch spectrum)."""
    harmonic = _partials([float(n) for n in range(1, 9)])
    detuned = _partials(_DETUNED_MULTIPLIERS)
    inh_h = extract_verbose(_write(tmp_path / "harm.wav", harmonic))["inharmonicity"]
    inh_d = extract_verbose(_write(tmp_path / "det.wav", detuned))["inharmonicity"]
    assert inh_h is not None and inh_d is not None
    assert inh_h < 0.008  # measured ~0.003
    assert inh_d > 0.008  # measured ~0.012
    assert inh_d > 2.0 * inh_h


def test_roughness_and_attack_click_train_vs_tone(tmp_path):
    """D3/D4: envelope modulation and attack sharpness are high for a
    click train, low for a sustained harmonic tone (§3.c)."""
    v_clicks = extract_verbose(_write(tmp_path / "clicks.wav", _click_train()))
    v_tone = extract_verbose(
        _write(tmp_path / "tone.wav", _partials([float(n) for n in range(1, 9)]))
    )
    assert v_clicks["roughness"] > 0.3  # measured ~0.67
    assert v_tone["roughness"] < 0.1  # measured ~0.02
    assert v_clicks["attack_sharpness"] > 0.8  # measured 1.0
    assert v_tone["attack_sharpness"] < 0.4  # measured ~0.16


def test_stereo_width_dual_mono_vs_decorrelated(tmp_path):
    base = _noise(seed=3)
    dual = np.stack([base, base], axis=1)
    decorr = np.stack([_noise(seed=4), _noise(seed=5)], axis=1)
    v_dual = extract_verbose(_write(tmp_path / "dual.wav", dual))
    v_dec = extract_verbose(_write(tmp_path / "dec.wav", decorr))
    v_mono = extract_verbose(_write(tmp_path / "mono.wav", base))
    assert v_dual["stereo_width"] == pytest.approx(0.0, abs=0.05)
    assert v_dec["stereo_width"] > 0.3  # measured ~0.99
    assert v_mono["stereo_width"] is None


def test_f0_block_on_220_sine(tmp_path):
    """pyin lands on a clean sine. Generous tolerances on purpose —
    pyin has platform/version variance (the 2% bound is the spec)."""
    v = extract_verbose(_write(tmp_path / "sine.wav", _sine(220.0)))
    f0 = v["f0"]
    assert f0["median_hz"] == pytest.approx(220.0, rel=0.02)
    assert f0["voiced_fraction"] > 0.75  # near 1 on a clean sine
    assert f0["range_hz"] is not None and f0["range_hz"] < 20.0


def test_f0_block_degrades_on_unpitched_material(tmp_path):
    v = extract_verbose(_write(tmp_path / "clicks.wav", _click_train()))
    f0 = v["f0"]
    assert f0["voiced_fraction"] < 0.5
    # median/range may be None when nothing tracks; never raise.
    assert set(f0) == {"median_hz", "range_hz", "voiced_fraction"}


def test_verbose_v1_keys_untouched(tmp_path):
    """The v2 block is additive — every v1 key is still present."""
    v = extract_verbose(_write(tmp_path / "sine.wav", _sine(220.0)))
    for key in ("mfcc_mean", "mfcc_std", "chroma_mean", "tempo_bpm",
                "n_channels", "per_channel"):
        assert key in v
    for key in ("trajectory", "inharmonicity", "roughness",
                "attack_sharpness", "stereo_width", "f0"):
        assert key in v


# ---------------------------------------------------------------------------
# Cache keys bumped
# ---------------------------------------------------------------------------


def test_cache_feature_set_literals_bumped_to_v2():
    """Old v1 cache entries must orphan: the analyze tool's feature_set
    literals are concise_v2 / verbose_v2 and the v1 strings are gone."""
    source = Path(analyze_module.__file__).read_text()
    assert '"concise_v2"' in source
    assert '"verbose_v2"' in source
    # No code path may still pass a v1 feature_set string (prose
    # mentions in comments are fine; string literals are not).
    assert '"concise_v1"' not in source
    assert '"verbose_v1"' not in source


# ---------------------------------------------------------------------------
# cluster() with the 33-dim v2 vector
# ---------------------------------------------------------------------------


@pytest.fixture
def cluster_harness(tmp_path):
    mcp = FastMCP("test-cdp-mir-v2-cluster")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    sessions = SessionManager(sessions_root, lambda: None)
    tracker = LatestTracker()
    cluster_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: None,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions


async def _call_cluster(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "cluster", args, context=None, convert_result=False
    )


def _write_three_groups(session) -> dict[str, list[str]]:
    """test_cluster.py's fixture pattern: 3 low sines, 3 noises, 3 click
    trains, 0.5 s each."""
    material: dict[str, list[np.ndarray]] = {"sine": [], "noise": [], "click": []}
    for freq in (108.0, 110.0, 112.0):
        material["sine"].append(_sine(freq, seconds=0.5))
    for i in range(3):
        material["noise"].append(_noise(seconds=0.5, seed=i))
    for period in (0.04, 0.05, 0.06):
        y = np.zeros(int(_SR * 0.5), dtype=np.float32)
        y[:: int(_SR * period)] = 0.9
        material["click"].append(y)
    names: dict[str, list[str]] = {}
    for group, signals in material.items():
        names[group] = []
        for i, y in enumerate(signals):
            filename = f"{group}_{i}.wav"
            sf.write(str(session.inputs_dir / filename), y, _SR)
            names[group].append(filename)
    return names


def test_cluster_v2_vector_is_33_dim(tmp_path):
    path = _write(tmp_path / "probe.wav", _sine(220.0, seconds=0.5))
    vec = cluster_module._extract_features(path)
    assert vec.shape == (33,)
    assert np.all(np.isfinite(vec))


async def test_cluster_v2_still_separates_three_groups(cluster_harness):
    mcp, sessions = cluster_harness
    session, _ = sessions.set_active("s1")
    names = _write_three_groups(session)
    refs = [n for group in names.values() for n in group]

    payload = await _call_cluster(mcp, {"targets": refs})
    assert payload["status"] == "ok"
    assert payload["n_targets"] == 9
    assert payload["k"] in {2, 3, 4}

    label_of = {m: c["label"] for c in payload["clusters"] for m in c["members"]}
    sine_labels = {label_of[r] for r in names["sine"]}
    noise_labels = {label_of[r] for r in names["noise"]}
    assert len(sine_labels) == 1  # all three sines share one cluster
    assert sine_labels.isdisjoint(noise_labels)  # no sine sits with noise
    for c in payload["clusters"]:
        assert c["medoid"] in c["members"]


async def test_cluster_v2_deterministic_under_fixed_seed(cluster_harness):
    mcp, sessions = cluster_harness
    session, _ = sessions.set_active("s1")
    names = _write_three_groups(session)
    refs = [n for group in names.values() for n in group]

    payload_1 = await _call_cluster(mcp, {"targets": refs, "seed": 42})
    payload_2 = await _call_cluster(mcp, {"targets": refs, "seed": 42})
    assert payload_1["status"] == payload_2["status"] == "ok"
    assert payload_1["k"] == payload_2["k"]
    assert payload_1["clusters"] == payload_2["clusters"]
    assert payload_1["pca_coords"] == payload_2["pca_coords"]
