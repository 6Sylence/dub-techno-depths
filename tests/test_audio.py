"""Checks for the EDM engine. Run with: python -m tests.test_audio"""

from __future__ import annotations

import numpy as np

from src.audio import DEFAULT_SR, render_loop, snap_loop_seconds
from src.utils import load_presets

PRESET = next(p for p in load_presets("config/presets.yaml")
              if p["id"] == "bounce_night")["audio"]
BPM = PRESET["bpm"]


def test_snap():
    s = snap_loop_seconds(BPM, 300)
    bar = 4 * 60 / BPM
    assert abs(s / (8 * bar) - round(s / (8 * bar))) < 1e-9
    print(f"ok: snap 300s -> {s:.3f}s (whole 8-bar phrases)")


def test_shape_and_level():
    out = render_loop(PRESET, 24, seed=1)
    snapped = snap_loop_seconds(BPM, 24)
    assert out.dtype == np.int16
    assert out.ndim == 2 and out.shape[1] == 2
    assert abs(out.shape[0] - snapped * DEFAULT_SR) <= 1, out.shape
    assert np.abs(out).max() > 8000
    print("ok: shape/dtype/level")


def test_deterministic():
    a = render_loop(PRESET, 24, seed=42)
    b = render_loop(PRESET, 24, seed=42)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, render_loop(PRESET, 24, seed=43))
    print("ok: deterministic by seed")


def test_seamless():
    out = render_loop(PRESET, 24, seed=7).astype(np.float64)
    seam = abs(out[0, 0] - out[-1, 0])
    p999 = np.percentile(np.abs(np.diff(out[:, 0])), 99.9)
    assert seam <= p999 + 1, f"seam {seam} vs internal {p999}"
    print(f"ok: seamless (seam={seam:.0f} <= p99.9={p999:.0f})")


def test_groove():
    """Four-on-the-floor repeats every bar, so the envelope autocorrelation has a
    clear peak at the one-bar lag — verify that steady pulse is present."""
    x = render_loop(PRESET, 24, seed=42).astype(float)[:, 0]
    env = np.abs(x)
    env = env[: len(env) // 441 * 441].reshape(-1, 441).mean(1)
    env -= env.mean()
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    bar_lag = int(round(4 * 60 / BPM * 100))
    strength = ac[bar_lag - 4: bar_lag + 5].max() / ac[0]
    assert strength > 0.3, f"bar pulse too weak: {strength:.2f}"
    print(f"ok: clear bar-level groove (autocorr {strength:.2f})")


if __name__ == "__main__":
    test_snap()
    test_shape_and_level()
    test_deterministic()
    test_seamless()
    test_groove()
    print("\nall engine tests passed")
