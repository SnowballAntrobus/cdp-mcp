"""Unit tests for cdp_mcp.audio_align — pure numpy, no CDP, no soundfile."""

from __future__ import annotations

import numpy as np
import pytest

from cdp_mcp.audio_align import cosine_fade_out, pad_with_fade, truncate_with_fade

_SR = 44100
# 5 ms at 44.1 kHz → round(0.005 * 44100) = 220 samples.
_FADE_SAMPLES_5MS = round(0.005 * _SR)


# ---------------------------------------------------------------------------
# cosine_fade_out
# ---------------------------------------------------------------------------


def test_cosine_fade_out_window_shape_endpoints_and_monotonic():
    n, fade = 1000, 200
    x = np.ones(n, dtype=np.float64)
    out = cosine_fade_out(x, fade)

    # Pre-fade region untouched.
    assert np.all(out[: n - fade] == 1.0)
    # Window (== out tail, since x was all-ones) runs 1.0 → 0.0.
    window = out[n - fade:]
    assert window[0] == pytest.approx(1.0)
    assert window[-1] == pytest.approx(0.0, abs=1e-12)
    # Monotonically non-increasing across the fade.
    assert np.all(np.diff(window) <= 1e-12)


def test_cosine_fade_out_midpoint_half():
    fade = 201  # odd → exact middle index exists
    out = cosine_fade_out(np.ones(fade, dtype=np.float64), fade)
    assert out[(fade - 1) // 2] == pytest.approx(0.5, abs=1e-9)


def test_cosine_fade_out_does_not_mutate_input():
    x = np.ones(500, dtype=np.float64)
    x_copy = x.copy()
    cosine_fade_out(x, 100)
    assert np.array_equal(x, x_copy)


def test_cosine_fade_out_stereo_per_channel_broadcast():
    n, fade = 800, 150
    x = np.ones((n, 2), dtype=np.float64)
    # Make the two channels distinguishable in magnitude.
    x[:, 1] = 2.0
    out = cosine_fade_out(x, fade)

    assert out.shape == (n, 2)
    assert np.all(out[: n - fade, 0] == 1.0)
    assert np.all(out[: n - fade, 1] == 2.0)
    # Same fade window applied to each channel → channel-1 tail is 2× channel-0.
    np.testing.assert_allclose(out[n - fade:, 1], 2.0 * out[n - fade:, 0])
    assert out[-1, 0] == pytest.approx(0.0, abs=1e-12)
    assert out[-1, 1] == pytest.approx(0.0, abs=1e-12)


def test_cosine_fade_out_fade_ge_n_fades_whole_array():
    n = 100
    x = np.ones(n, dtype=np.float64)
    out = cosine_fade_out(x, fade_samples=10_000)  # >> n
    assert out.shape == (n,)
    assert out[0] == pytest.approx(1.0)
    assert out[-1] == pytest.approx(0.0, abs=1e-12)


def test_cosine_fade_out_fade_len_one_is_silence_no_div_by_zero():
    out = cosine_fade_out(np.ones(50, dtype=np.float64), fade_samples=1)
    assert out[-1] == 0.0
    assert np.all(out[:-1] == 1.0)


def test_cosine_fade_out_nonpositive_fade_returns_unmodified_copy():
    x = np.linspace(1.0, 2.0, 30, dtype=np.float64)
    out = cosine_fade_out(x, fade_samples=0)
    assert np.array_equal(out, x)
    assert out is not x  # copy, not the same buffer


def test_cosine_fade_out_empty_input():
    out = cosine_fade_out(np.zeros(0, dtype=np.float32), fade_samples=10)
    assert out.shape == (0,)


# ---------------------------------------------------------------------------
# pad_with_fade
# ---------------------------------------------------------------------------


def test_pad_with_fade_length_and_zero_pad():
    n, target = 5000, 8000
    x = np.ones(n, dtype=np.float64)
    out = pad_with_fade(x, target, _SR)

    assert out.shape == (target,)
    # Padded region is all zeros.
    assert np.all(out[n:] == 0.0)


def test_pad_with_fade_prefade_region_bit_identical():
    n, target = 5000, 8000
    rng = np.random.default_rng(0)
    x = rng.standard_normal(n).astype(np.float64)
    out = pad_with_fade(x, target, _SR)
    # Everything before the fade region is untouched.
    assert np.array_equal(out[: n - _FADE_SAMPLES_5MS], x[: n - _FADE_SAMPLES_5MS])


def test_pad_with_fade_last_original_sample_near_zero():
    n, target = 5000, 8000
    x = np.ones(n, dtype=np.float64)
    out = pad_with_fade(x, target, _SR)
    assert out[n - 1] == pytest.approx(0.0, abs=1e-9)


def test_pad_with_fade_stereo():
    n, target = 4000, 6000
    x = np.ones((n, 2), dtype=np.float64)
    out = pad_with_fade(x, target, _SR)
    assert out.shape == (target, 2)
    assert np.all(out[n:, :] == 0.0)
    assert out[n - 1, 0] == pytest.approx(0.0, abs=1e-9)
    assert out[n - 1, 1] == pytest.approx(0.0, abs=1e-9)


def test_pad_with_fade_equal_length_is_unmodified_copy():
    n = 3000
    x = np.linspace(-1.0, 1.0, n, dtype=np.float64)
    out = pad_with_fade(x, n, _SR)
    assert np.array_equal(out, x)
    assert out is not x


def test_pad_with_fade_target_less_than_len_raises():
    x = np.ones(5000, dtype=np.float64)
    with pytest.raises(ValueError):
        pad_with_fade(x, 4000, _SR)


def test_pad_with_fade_input_shorter_than_fade_region():
    n, target = 100, 500  # n < 220-sample fade region
    x = np.ones(n, dtype=np.float64)
    out = pad_with_fade(x, target, _SR)
    assert out.shape == (target,)
    # Whole signal faded → starts at 1.0, last real sample ≈ 0, then zeros.
    assert out[0] == pytest.approx(1.0)
    assert out[n - 1] == pytest.approx(0.0, abs=1e-9)
    assert np.all(out[n:] == 0.0)


def test_pad_with_fade_preserves_float32_dtype():
    x = np.ones(5000, dtype=np.float32)
    out = pad_with_fade(x, 8000, _SR)
    assert out.dtype == np.float32


def test_pad_with_fade_empty_input_yields_target_zeros():
    out = pad_with_fade(np.zeros(0, dtype=np.float32), 1000, _SR)
    assert out.shape == (1000,)
    assert np.all(out == 0.0)
    assert out.dtype == np.float32


def test_pad_with_fade_does_not_mutate_input():
    x = np.ones(5000, dtype=np.float64)
    x_copy = x.copy()
    pad_with_fade(x, 8000, _SR)
    assert np.array_equal(x, x_copy)


# ---------------------------------------------------------------------------
# truncate_with_fade
# ---------------------------------------------------------------------------


def test_truncate_with_fade_length_and_tail_fade():
    n, target = 8000, 5000
    x = np.ones(n, dtype=np.float64)
    out = truncate_with_fade(x, target, _SR)

    assert out.shape == (target,)
    # New tail tapers to ≈ 0.
    assert out[-1] == pytest.approx(0.0, abs=1e-9)
    # Region before the fade preserved from the truncated input (all ones).
    assert np.all(out[: target - _FADE_SAMPLES_5MS] == 1.0)


def test_truncate_with_fade_prefade_region_from_truncated_input():
    n, target = 8000, 5000
    rng = np.random.default_rng(1)
    x = rng.standard_normal(n).astype(np.float64)
    out = truncate_with_fade(x, target, _SR)
    keep = target - _FADE_SAMPLES_5MS
    assert np.array_equal(out[:keep], x[:keep])


def test_truncate_with_fade_target_greater_than_len_raises():
    x = np.ones(5000, dtype=np.float64)
    with pytest.raises(ValueError):
        truncate_with_fade(x, 6000, _SR)


def test_truncate_with_fade_equal_length_is_unmodified_copy():
    n = 5000
    x = np.linspace(-1.0, 1.0, n, dtype=np.float64)
    out = truncate_with_fade(x, n, _SR)
    assert np.array_equal(out, x)
    assert out is not x


def test_truncate_with_fade_stereo():
    n, target = 8000, 5000
    x = np.ones((n, 2), dtype=np.float64)
    out = truncate_with_fade(x, target, _SR)
    assert out.shape == (target, 2)
    assert out[-1, 0] == pytest.approx(0.0, abs=1e-9)
    assert out[-1, 1] == pytest.approx(0.0, abs=1e-9)


def test_truncate_with_fade_preserves_float32_dtype():
    x = np.ones(8000, dtype=np.float32)
    out = truncate_with_fade(x, 5000, _SR)
    assert out.dtype == np.float32


def test_truncate_with_fade_does_not_mutate_input():
    x = np.ones(8000, dtype=np.float64)
    x_copy = x.copy()
    truncate_with_fade(x, 5000, _SR)
    assert np.array_equal(x, x_copy)
