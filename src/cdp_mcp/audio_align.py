"""Pure audio length-alignment primitives for multi-input PVOC wiring.

These three functions are the numeric core behind the ``"pad_with_fade"`` and
``"truncate_to_shortest"`` ``_pvoc.length_strategy`` values (design doc,
Multi-Input Conventions). They are deliberately pure: numpy in, numpy out — no
file I/O, no soundfile, no CDP, no session state. The consuming wiring
(Task 8: multi-input PVOC alignment) reads the input wavs, decides target
lengths and which input is shorter/longer, calls these primitives, and writes
the aligned audio back out. Keeping the math here means it's exhaustively
unit-testable in isolation.

Array layout is **channels-last** — ``(N,)`` for mono, ``(N, channels)`` for
multi-channel — matching ``soundfile.read``, which is how Task 8 reads the
audio that feeds these functions. (This differs from the channels-*first*
``(channels, N)`` layout that :mod:`cdp_mcp.analysis` and
:mod:`cdp_mcp.visualization` get from ``librosa.load``; those are a separate
observation-tool path. Task 8 must read via ``soundfile``, not ``librosa``.)

The fade is a raised-cosine (Hann-shaped) taper rather than a linear ramp: its
continuous first derivative at the boundaries produces fewer spectral
artifacts than a linear ramp's corners. The 5 ms default (~220 samples at
44.1 kHz) is long enough to kill the click at an audio→silence boundary and
short enough to be inaudible as a fade.
"""

from __future__ import annotations

import numpy as np

_DEFAULT_FADE_MS = 5.0


def cosine_fade_out(samples: np.ndarray, fade_samples: int) -> np.ndarray:
    """Return a copy of ``samples`` with a raised-cosine fade-out on its tail.

    The final ``fade_samples`` samples are multiplied by a window running from
    1.0 (unchanged) down to 0.0 (silence); everything before the fade region
    is bit-identical to the input. Shape ``(N,)`` or ``(N, channels)`` — the
    window broadcasts across channels. If ``fade_samples >= N`` the whole array
    is faded; ``fade_samples <= 0`` returns an unmodified copy. The input is
    never mutated.
    """
    out = samples.astype(np.result_type(samples.dtype, np.float32), copy=True)
    n = out.shape[0]
    if n == 0 or fade_samples <= 0:
        return out

    fade_len = min(fade_samples, n)
    if fade_len == 1:
        # Single-sample fade: straight to silence (the linspace below would be
        # a single point at angle 0 → weight 1.0, i.e. no fade, which isn't
        # what a fade-out means; and the closed-form i/(fade_len-1) divides by
        # zero). Collapse to a clean zero.
        window = np.zeros(1, dtype=out.dtype)
    else:
        window = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, fade_len)))
        window = window.astype(out.dtype)

    if out.ndim > 1:
        window = window.reshape(fade_len, *([1] * (out.ndim - 1)))

    out[n - fade_len:] *= window
    return out.astype(samples.dtype, copy=False)


def pad_with_fade(
    samples: np.ndarray,
    target_length: int,
    sr: int,
    fade_ms: float = _DEFAULT_FADE_MS,
) -> np.ndarray:
    """Fade ``samples``' tail, then zero-pad to ``target_length``.

    Lengthens the shorter input so it matches the longer one without a click at
    the audio→silence boundary. ``target_length`` must be ``>= len(samples)``
    (``ValueError`` otherwise — the caller's strategy logic guarantees this; we
    fail loud rather than silently truncate). If ``target_length`` equals the
    input length there is no boundary to smooth, so the input is returned as an
    unmodified copy with no fade. Returns the same dtype as the input and never
    mutates it.
    """
    n = samples.shape[0]
    if target_length < n:
        raise ValueError(
            f"pad_with_fade target_length ({target_length}) < input length ({n}); "
            "pad only lengthens the shorter input"
        )
    if target_length == n:
        return samples.copy()

    fade_samples = round(fade_ms / 1000.0 * sr)
    faded = cosine_fade_out(samples, fade_samples)

    pad = target_length - n
    pad_width = ((0, pad),) + ((0, 0),) * (samples.ndim - 1)
    return np.pad(faded, pad_width, mode="constant")


def truncate_with_fade(
    samples: np.ndarray,
    target_length: int,
    sr: int,
    fade_ms: float = _DEFAULT_FADE_MS,
) -> np.ndarray:
    """Truncate ``samples`` to ``target_length``, then fade the new tail.

    Shortens the longer input so it matches the shorter one without a click at
    the cut. ``target_length`` must be ``<= len(samples)`` (``ValueError``
    otherwise — mirror of :func:`pad_with_fade`). If ``target_length`` equals
    the input length the cut point is the natural end, so no discontinuity is
    introduced and the input is returned as an unmodified copy. Returns the
    same dtype as the input and never mutates it.
    """
    n = samples.shape[0]
    if target_length > n:
        raise ValueError(
            f"truncate_with_fade target_length ({target_length}) > input length ({n}); "
            "truncate only shortens the longer input"
        )
    if target_length == n:
        return samples.copy()

    fade_samples = round(fade_ms / 1000.0 * sr)
    return cosine_fade_out(samples[:target_length], fade_samples)
