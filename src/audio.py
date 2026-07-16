"""Procedural dub techno engine.

Everything is synthesized from scratch with numpy — kick, sub bass, dub chord
stabs through a ping-pong feedback delay, hi-hats, pads and vinyl crackle — so
the output is 100% original and copyright-safe.

The public entry points are :func:`snap_loop_seconds` (quantize a requested
duration to whole 8-bar phrases so the loop is musically seamless) and
:func:`render_loop` (render one stereo loop). Reverb/delay tails are wrapped
around to the start of the buffer, so the clip joins itself perfectly and the
pipeline can repeat it for hours without a seam.
"""

from __future__ import annotations

import numpy as np

DEFAULT_SR = 44_100

# Root notes (Hz) the daily seed picks from — all deep, sub-friendly keys.
ROOTS = {"A1": 55.00, "G1": 49.00, "F1": 43.65, "C2": 65.41, "D2": 73.42}

# Chord voicings as ratios over the root (x2 = one octave up for the stab).
CHORDS = {
    "m7":  [2.0, 2.378, 2.996, 3.564],          # minor 7th — the dub classic
    "m9":  [2.0, 2.378, 2.996, 4.490],          # minor add9, dreamier
    "sus": [2.0, 2.670, 2.996, 4.000],          # suspended, neutral tension
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _normalize(x, peak=1.0):
    m = np.max(np.abs(x))
    return x if m < 1e-9 else x * (peak / m)


def _lowpass_fft(x, cutoff_hz, sr):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    spec *= 1.0 / (1.0 + (freqs / cutoff_hz) ** 2)
    return np.fft.irfft(spec, n=x.size)


def _highpass_fft(x, cutoff_hz, sr):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    ratio = (freqs / cutoff_hz) ** 2
    spec *= ratio / (1.0 + ratio)
    return np.fft.irfft(spec, n=x.size)


def _wrap_add(buf: np.ndarray, event: np.ndarray, start: int) -> None:
    """Add ``event`` into circular buffer ``buf`` starting at ``start``.

    Anything that runs past the end wraps to the beginning — this is what makes
    delay/reverb tails loop seamlessly instead of being cut at the seam.
    """
    n = buf.shape[0]
    start = start % n
    end = start + event.shape[0]
    if end <= n:
        buf[start:end] += event
    else:
        first = n - start
        buf[start:] += event[:first]
        buf[: end - n] += event[first:]


def snap_loop_seconds(bpm: float, seconds: float) -> float:
    """Quantize ``seconds`` to a whole number of 8-bar phrases at ``bpm``."""
    bar = 4 * 60.0 / bpm
    phrase = 8 * bar
    phrases = max(1, round(seconds / phrase))
    return phrases * phrase


# --------------------------------------------------------------------------- #
# Instruments — each returns a mono event array to place on the grid
# --------------------------------------------------------------------------- #
def _kick(sr, punch=1.0):
    dur = 0.28
    t = np.arange(int(dur * sr)) / sr
    freq = 140.0 * np.exp(-t * 30.0) + 44.0          # pitch drop 140 -> 44 Hz
    phase = 2 * np.pi * np.cumsum(freq) / sr
    body = np.sin(phase) * np.exp(-t * 9.0)
    click = np.random.default_rng(0).standard_normal(int(0.004 * sr)) * 0.4
    out = body * punch
    out[: click.size] += click * punch
    return out


def _sub_note(sr, freq, dur):
    t = np.arange(int(dur * sr)) / sr
    env = np.minimum(t * 80, 1.0) * np.exp(-t * 6.0)
    x = np.sin(2 * np.pi * freq * t)
    return np.tanh(x * 1.5) * env                    # gentle saturation


def _chord_stab(sr, root, ratios, rng, dur=0.42, bright=2400.0):
    """Detuned band-limited saw chord through a lowpass — the dub stab."""
    t = np.arange(int(dur * sr)) / sr
    out = np.zeros(t.size)
    for r in ratios:
        f = root * r * (1.0 + rng.uniform(-0.002, 0.002))
        for k in range(1, 9):                        # band-limited saw-ish
            out += np.sin(2 * np.pi * f * k * t) / k
    env = np.minimum(t * 200, 1.0) * np.exp(-t * 7.0)
    out = _lowpass_fft(out * env, bright, sr)
    return _normalize(out)


def _hat(sr, rng, open_=False):
    dur = 0.09 if open_ else 0.03
    n = int(dur * sr)
    x = rng.standard_normal(n) * np.exp(-np.arange(n) / (sr * (0.03 if open_ else 0.008)))
    x = _highpass_fft(x, 6000, sr)
    x = _lowpass_fft(x, 12000, sr)                    # tame the fizz
    return _normalize(x, peak=0.5)


def _crackle(n, sr, rng, density=1.2):
    """Vinyl surface noise — sparse filtered ticks over faint hiss."""
    out = rng.standard_normal(n) * 0.012             # hiss bed
    n_ticks = int(density * n / sr)
    for _ in range(n_ticks):
        pos = int(rng.integers(0, n - 50))
        tick = rng.standard_normal(rng.integers(8, 40)) * rng.uniform(0.1, 0.5)
        out[pos:pos + tick.size] += tick
    return _lowpass_fft(out, 7500, sr)


# --------------------------------------------------------------------------- #
# The renderer
# --------------------------------------------------------------------------- #
def render_loop(preset: dict, seconds: float, sr: int = DEFAULT_SR,
                seed: int | None = None) -> np.ndarray:
    """Render a seamless stereo dub techno loop. Returns int16 (N, 2).

    ``preset`` (the ``audio`` section of a config preset) supports:
      bpm, chord ("m7"|"m9"|"sus"), bright (chord LP cutoff), delay_beats,
      delay_fb, kick_gain, sub_gain, chord_gain, hat_gain, pad_gain,
      crackle_gain, stab_slots (16th-grid indices per 2 bars).
    """
    rng = np.random.default_rng(seed)
    bpm = float(preset.get("bpm", 122))
    seconds = snap_loop_seconds(bpm, seconds)
    n = int(round(seconds * sr))

    beat = 60.0 / bpm
    spb = beat * sr                                   # samples per beat
    n_beats = int(round(seconds / beat))
    n_bars = n_beats // 4
    six = spb / 4.0                                   # samples per 16th

    root = ROOTS[rng.choice(list(ROOTS))]
    ratios = CHORDS[preset.get("chord", rng.choice(["m7", "m9"]))]

    kick_bus = np.zeros(n)
    bass_bus = np.zeros(n)
    chord_l = np.zeros(n)
    chord_r = np.zeros(n)
    hat_bus = np.zeros(n)

    # --- kick: four to the floor -------------------------------------------
    kick = _kick(sr, punch=float(preset.get("kick_gain", 1.0)))
    for b in range(n_beats):
        _wrap_add(kick_bus, kick, int(b * spb))

    # --- sub bass: offbeat 8ths on the root --------------------------------
    sub = _sub_note(sr, root, beat * 0.6)
    for b in range(n_beats):
        _wrap_add(bass_bus, sub, int((b + 0.5) * spb))

    # --- dub chord stabs + ping-pong feedback delay ------------------------
    stab_slots = preset.get("stab_slots", [2, 11, 23])   # 16ths per 2 bars
    stab = _chord_stab(sr, root, ratios, rng,
                       bright=float(preset.get("bright", 2400)))
    delay_s = float(preset.get("delay_beats", 0.75)) * beat   # dotted 8th
    fb = float(preset.get("delay_fb", 0.55))
    d_samp = int(delay_s * sr)
    for two_bar in range(max(1, n_bars // 2)):
        base = two_bar * 32 * six
        for slot in stab_slots:
            if rng.random() < 0.12:                  # occasional skipped hit
                continue
            pos = int(base + slot * six)
            vel = rng.uniform(0.7, 1.0)
            _wrap_add(chord_l, stab * vel, pos)
            # echoes alternate L/R and darken as they repeat (dub!)
            echo = _lowpass_fft(stab, 1800, sr)
            for k in range(1, 8):
                g = vel * (fb ** k)
                if g < 0.02:
                    break
                target = chord_r if k % 2 else chord_l
                _wrap_add(target, echo * g, pos + k * d_samp)

    # --- hats: offbeat 8ths, light velocity humanization -------------------
    hat_gain = float(preset.get("hat_gain", 0.5))
    if hat_gain > 0:
        for b in range(n_beats):
            h = _hat(sr, rng, open_=(b % 8 == 7))
            _wrap_add(hat_bus, h * hat_gain * rng.uniform(0.6, 1.0),
                      int((b + 0.5) * spb))

    # --- pad + vinyl crackle atmosphere -------------------------------------
    pad_gain = float(preset.get("pad_gain", 0.25))
    t_all = np.arange(n) / sr
    pad = np.zeros(n)
    if pad_gain > 0:
        for r in ratios[:3]:
            pad += np.sin(2 * np.pi * (root * r / 2) * t_all)
        # loop-periodic swell (integer cycles per loop -> seamless)
        swell = 0.6 + 0.4 * np.sin(2 * np.pi * 2 * t_all / seconds)
        pad = _lowpass_fft(pad * swell, 900, sr)
        pad = _normalize(pad)
    crackle = _crackle(n, sr, rng) * float(preset.get("crackle_gain", 0.5))

    # --- sidechain pump: everything but the kick ducks after each kick ------
    pump = np.ones(n)
    duck_len = int(0.30 * sr)
    duck = 1.0 - 0.62 * np.exp(-np.arange(duck_len) / (0.09 * sr))
    for b in range(n_beats):
        s = int(b * spb) % n
        e = min(s + duck_len, n)
        pump[s:e] = np.minimum(pump[s:e], duck[: e - s])
        if s + duck_len > n:                          # wrap the duck too
            rest = s + duck_len - n
            pump[:rest] = np.minimum(pump[:rest], duck[duck_len - rest:])

    sub_g = float(preset.get("sub_gain", 0.9))
    chd_g = float(preset.get("chord_gain", 1.0))

    left = (kick_bus * 1.1
            + pump * (bass_bus * sub_g + chord_l * chd_g
                      + pad * pad_gain) + crackle * 0.5 + hat_bus * 0.35)
    right = (kick_bus * 1.1
             + pump * (bass_bus * sub_g + chord_r * chd_g
                       + pad * pad_gain) + crackle * 0.45 + hat_bus * 0.4)

    stereo = np.stack([left, right], axis=1)
    stereo = np.tanh(stereo / max(np.percentile(np.abs(stereo), 99.5), 1e-9) * 1.2)
    stereo = _normalize(stereo, peak=0.89)
    return (stereo * 32767.0).astype(np.int16)
