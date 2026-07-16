"""Checks for the dub techno engine. Run with: python -m tests.test_audio"""

from __future__ import annotations

import numpy as np

from src.audio import DEFAULT_SR, render_loop, snap_loop_seconds

PRESET = {"bpm": 122, "chord": "m7"}


def test_snap():
    s = snap_loop_seconds(122, 300)
    bar = 4 * 60 / 122
    assert abs(s / (8 * bar) - round(s / (8 * bar))) < 1e-9, "not whole phrases"
    print(f"ok: snap 300s -> {s:.3f}s (whole 8-bar phrases)")


def test_shape_and_level():
    out = render_loop(PRESET, 16, seed=1)
    snapped = snap_loop_seconds(122, 16)
    assert out.dtype == np.int16
    assert out.ndim == 2 and out.shape[1] == 2
    assert abs(out.shape[0] - snapped * DEFAULT_SR) <= 1, out.shape
    assert np.abs(out).max() > 8000, "too quiet"
    print("ok: shape/dtype/level")


def test_deterministic():
    a = render_loop(PRESET, 16, seed=42)
    b = render_loop(PRESET, 16, seed=42)
    assert np.array_equal(a, b)
    c = render_loop(PRESET, 16, seed=43)
    assert not np.array_equal(a, c)
    print("ok: deterministic by seed")


def test_seamless():
    out = render_loop(PRESET, 16, seed=7).astype(np.float64)
    internal = np.abs(np.diff(out[:, 0]))
    seam = abs(out[0, 0] - out[-1, 0])
    p999 = np.percentile(internal, 99.9)
    assert seam <= p999 + 1, f"seam {seam} vs internal {p999}"
    print(f"ok: seamless (seam={seam:.0f} <= p99.9={p999:.0f})")


def test_has_pulse():
    a = render_loop(PRESET, 16, seed=42).astype(float)[:, 0]
    env = np.abs(a)
    env = env[: len(env) // 441 * 441].reshape(-1, 441).mean(1)
    env -= env.mean()
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    bf = int(round(60 / 122 * 100))
    strength = ac[bf - 5: bf + 6].max() / ac[0]
    assert strength > 0.3, f"beat too weak: {strength:.2f}"
    print(f"ok: clear pulse at 122bpm (autocorr {strength:.2f})")


if __name__ == "__main__":
    test_snap()
    test_shape_and_level()
    test_deterministic()
    test_seamless()
    test_has_pulse()
    print("\nall engine tests passed")
