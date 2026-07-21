"""Procedural lofi hip hop engine.

Everything is synthesized from scratch with numpy — soft boom-bap drums, a warm
sub bass, jazzy Rhodes-style electric-piano chords through tape warble, swung
hats, optional rain and heavy vinyl crackle — so the output is 100% original
and copyright-safe.

Public entry points (same contract as the other channels):
  snap_loop_seconds(bpm, seconds) -> quantize to whole 8-bar phrases.
  render_loop(preset, seconds, sr, seed) -> a seamless stereo int16 (N, 2) loop.

The loop snaps to whole bars, the 4-bar chord progression tiles it evenly, and
every reverb / note tail wraps around the buffer, so an hour of repeats has no
audible seam.
"""

from __future__ import annotations

import numpy as np

DEFAULT_SR = 44_100

# Jazzy chord qualities as semitone offsets from the root (lofi staples).
QUALITIES = {
    "maj7":  [0, 4, 7, 11],
    "min7":  [0, 3, 7, 10],
    "dom7":  [0, 4, 7, 10],
    "maj9":  [0, 4, 7, 11, 14],
    "min9":  [0, 3, 7, 10, 14],
    "dom9":  [0, 4, 7, 10, 14],
    "min11": [0, 3, 7, 10, 14, 17],
}


def _normalize(x, peak=1.0):
    m = np.max(np.abs(x))
    return x if m < 1e-9 else x * (peak / m)


def _lowpass_fft(x, cutoff_hz, sr, order=2):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    spec *= 1.0 / (1.0 + (freqs / cutoff_hz) ** order)
    return np.fft.irfft(spec, n=x.size)


def _highpass_fft(x, cutoff_hz, sr):
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    ratio = (freqs / cutoff_hz) ** 2
    spec *= ratio / (1.0 + ratio)
    return np.fft.irfft(spec, n=x.size)


def _bandpass(x, lo, hi, sr):
    return _highpass_fft(_lowpass_fft(x, hi, sr), lo, sr)


def _eq(x, sr):
    """Corrective master EQ (the pro-lofi cleanup): high-pass sub rumble, dip the
    300-500 Hz mud, and scoop the 800 Hz-1 kHz 'bark' where the Rhodes turns
    harsh/noisy — the band that made the sustained chords fatiguing."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    g = f ** 2 / (f ** 2 + 32.0 ** 2)                       # HPF ~32 Hz
    g *= 1.0 - 0.32 * np.exp(-((f - 380.0) / 190.0) ** 2)   # -mud ~380 Hz
    g *= 1.0 - 0.42 * np.exp(-((f - 950.0) / 420.0) ** 2)   # -bark ~950 Hz
    return np.fft.irfft(spec * g, n=x.size)


def _wrap_add(buf: np.ndarray, event: np.ndarray, start: int) -> None:
    """Add ``event`` into circular buffer ``buf`` at ``start``; overflow wraps."""
    n = buf.shape[0]
    start = int(start) % n
    end = start + event.shape[0]
    if end <= n:
        buf[start:end] += event
    else:
        first = n - start
        buf[start:] += event[:first]
        buf[: end - n] += event[first:]


def _midi_hz(midi):
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def snap_loop_seconds(bpm: float, seconds: float) -> float:
    """Quantize ``seconds`` to a whole number of 8-bar phrases at ``bpm``."""
    bar = 4 * 60.0 / bpm
    phrase = 8 * bar
    phrases = max(1, round(seconds / phrase))
    return phrases * phrase


# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #
def _ep_note(sr, freq, dur, t0, warble_hz, warble_depth, vel):
    """Warm Rhodes-ish electric-piano note: mostly fundamental + a soft 2nd, a
    brief attack tine, gentle tape warble, and a plucky decay so chords leave
    space between hits instead of droning. Per-note low-pass keeps it mellow."""
    n = int(dur * sr)
    idx = np.arange(n)
    t = (t0 + idx) / sr
    vib = 1.0 + 0.5 * warble_depth * np.sin(2 * np.pi * warble_hz * t)   # subtle
    phase = 2 * np.pi * freq * np.cumsum(vib) / sr
    tone = np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.05 * np.sin(3 * phase)
    tone += 0.12 * np.sin(4 * phase) * np.exp(-idx / (0.03 * sr))    # short soft tine
    env = np.minimum(idx / (0.015 * sr), 1.0) * np.exp(-idx / (0.48 * sr))  # plucky
    tone = _lowpass_fft(tone * env, min(freq * 7 + 400, 5500), sr)   # mellow warmth
    return tone * vel


def _kick(sr):
    n = int(0.34 * sr)
    idx = np.arange(n)
    freq = 48 + 45 * np.exp(-idx / (0.03 * sr))
    body = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-idx / (0.12 * sr))
    return _lowpass_fft(body, 700, sr) * 0.9


def _snare(sr, rng):
    n = int(0.2 * sr)
    idx = np.arange(n)
    noise = _bandpass(rng.standard_normal(n), 1200, 6000, sr) * np.exp(-idx / (0.09 * sr))
    body = np.sin(2 * np.pi * 185 * idx / sr) * np.exp(-idx / (0.07 * sr))
    mix = _lowpass_fft(0.7 * noise + 0.5 * body, 7500, sr)   # dusty, rolled-off
    return _normalize(mix) * 0.55


def _hat(sr, rng, open_=False):
    dur = 0.08 if open_ else 0.035
    n = int(dur * sr)
    idx = np.arange(n)
    x = rng.standard_normal(n) * np.exp(-idx / (sr * (0.03 if open_ else 0.01)))
    return _normalize(_bandpass(x, 5500, 11000, sr)) * (0.36 if open_ else 0.32)


def _bass(sr, freq, dur):
    n = int(dur * sr)
    idx = np.arange(n)
    env = np.minimum(idx / (0.01 * sr), 1.0) * np.exp(-idx / (0.5 * sr))
    tone = np.sin(2 * np.pi * freq * idx / sr) + 0.2 * np.sin(4 * np.pi * freq * idx / sr)
    return _lowpass_fft(np.tanh(tone * 1.3) * env, 320, sr)


def _crackle(n, sr, rng, density):
    """Vinyl *crackle*: sparse, short, warm pops — the character of a record,
    NOT a constant hiss wall. The faint tape hiss is added (and ducked under the
    music) separately by the renderer, the way real lofi records sit."""
    out = np.zeros(n)
    n_pops = int(7 * density * n / sr)          # ~7 pops/sec at density 1
    for _ in range(n_pops):
        pos = int(rng.integers(0, max(1, n - 20)))
        length = int(rng.integers(2, 12))       # very short clicks
        out[pos:pos + length] += rng.standard_normal(length) * rng.uniform(0.12, 0.5)
    return _lowpass_fft(out, 4200, sr)           # warm/dark, not fizzy


def _rain(n, sr, rng):
    body = _bandpass(rng.standard_normal(n), 400, 5000, sr)   # softer, darker
    return _normalize(body)


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #
def render_loop(preset: dict, seconds: float, sr: int = DEFAULT_SR,
                seed: int | None = None) -> np.ndarray:
    """Render a seamless stereo lofi loop. Returns int16 (N, 2).

    ``preset`` (the ``audio`` section) supports:
      bpm, progression [[root_midi, quality], ...] (4 bars), swing (0..0.5),
      warble, master_cut (Hz), crackle_gain, rain_gain, kick_gain, chord_gain,
      hat_gain, reverb.
    """
    rng = np.random.default_rng(seed)
    bpm = float(preset.get("bpm", 76))
    seconds = snap_loop_seconds(bpm, seconds)
    n = int(round(seconds * sr))

    beat = 60.0 / bpm
    bar = 4 * beat
    bar_s = bar * sr
    six = bar_s / 16.0                      # samples per 16th
    n_bars = int(round(seconds / bar))
    swing = float(preset.get("swing", 0.35)) * six

    prog = preset["progression"]
    warble_hz = rng.uniform(0.4, 0.7)
    warble_depth = float(preset.get("warble", 0.004))

    drums = np.zeros(n)
    bass = np.zeros(n)
    keys = np.zeros(n)

    kick = _kick(sr) * float(preset.get("kick_gain", 1.0))
    hat_gain = float(preset.get("hat_gain", 1.0))
    chord_gain = float(preset.get("chord_gain", 1.0))

    for b in range(n_bars):
        base = b * bar_s
        root_midi, quality = prog[b % len(prog)]

        # --- drums: soft boom-bap -----------------------------------------
        for step in (0, 10):                                   # kick
            if step == 10 and rng.random() < 0.15:
                continue
            _wrap_add(drums, kick, base + step * six)
        if b % 8 == 7 and rng.random() < 0.5:                  # occasional pickup kick
            _wrap_add(drums, kick, base + 14 * six)
        for step in (4, 12):                                   # snare backbeat
            _wrap_add(drums, _snare(sr, rng), base + step * six)
        for step in range(0, 16, 2):                           # swung hats
            off = swing if (step // 2) % 2 == 1 else 0.0
            h = _hat(sr, rng, open_=(step == 14)) * hat_gain * rng.uniform(0.6, 1.0)
            _wrap_add(drums, h, base + step * six + off)

        # --- bass: root on 1, ghost on the "and of 3" ---------------------
        bfreq = _midi_hz(root_midi - 12)
        _wrap_add(bass, _bass(sr, bfreq, beat * 1.5), base)
        if rng.random() < 0.6:
            _wrap_add(bass, _bass(sr, bfreq, beat * 0.6) * 0.7, base + 11 * six)

        # --- keys: jazzy chord held over the bar --------------------------
        for k, semi in enumerate(QUALITIES[quality]):
            freq = _midi_hz(root_midi + semi)
            vel = rng.uniform(0.55, 0.8) * (0.7 if k else 1.0)
            note = _ep_note(sr, freq, bar * 1.4, base, warble_hz, warble_depth, vel)
            _wrap_add(keys, note, base + int(0.01 * sr * k))   # slight strum
        if rng.random() < 0.35:                                # gentle re-hit
            for semi in QUALITIES[quality][:3]:
                note = _ep_note(sr, _midi_hz(root_midi + semi), beat * 2, base + 8 * six,
                                warble_hz, warble_depth, 0.4)
                _wrap_add(keys, note, base + 8 * six)

    keys = _normalize(keys) * chord_gain

    # --- lo-fi reverb on the keys: a couple of dark, quick echo taps -------
    # Kept short, dark (heavily low-passed) and low-gain so it colours the
    # chords without leaving a continuous bright wash smeared across the gaps.
    reverb = float(preset.get("reverb", 0.25))
    if reverb > 0:
        wet = np.zeros(n)
        tap = _lowpass_fft(keys, 1400, sr)
        for k in range(1, 4):
            _wrap_add(wet, tap * (reverb * 0.45 ** k), int(k * 0.095 * sr))
        keys = keys + wet

    # --- assemble + gentle sidechain duck under the kick ------------------
    pump = np.ones(n)
    duck_len = int(0.22 * sr)
    duck = 1.0 - 0.28 * np.exp(-np.arange(duck_len) / (0.07 * sr))
    for b in range(n_bars):
        s = int(b * bar_s) % n
        e = min(s + duck_len, n)
        pump[s:e] = np.minimum(pump[s:e], duck[: e - s])

    cg = float(preset.get("crackle_gain", 0.7))

    # Perceptual balance: keys carry the mids/highs, so lift them above the
    # bass/kick low end (which otherwise dominates the energy and muddies it).
    music = drums * 0.8 + pump * (bass * 0.3 + keys * 1.4)

    # Texture is sparse, transient vinyl pops ONLY — no continuous noise bed.
    # A steady filtered-noise "tape hiss" (however quiet) is exactly the
    # constant background sound the human ear locks onto and finds fatiguing,
    # so it is off by default; a preset can dial a faint whisper back in with
    # `hiss_gain`, and even then it is ducked hard under the music.
    hiss_gain = float(preset.get("hiss_gain", 0.0))
    if hiss_gain > 0:
        env = _lowpass_fft(np.abs(music), 6, sr)
        env = env / max(env.max(), 1e-9)
        hiss = _normalize(_lowpass_fft(rng.standard_normal(n), 2200, sr))
        hiss = hiss * 0.004 * hiss_gain * (1.0 - 0.85 * env)
    else:
        hiss = 0.0

    crackle = _crackle(n, sr, rng, 1.0) * cg * 0.5           # sparse warm pops
    ambience = _rain(n, sr, rng) * float(preset.get("rain_gain", 0.0)) * 0.35

    mono = music + crackle + hiss + ambience

    # --- master: corrective EQ -> dusty lowpass -> gentle tape saturation -----
    mono = _eq(mono, sr)
    mono = _lowpass_fft(mono, float(preset.get("master_cut", 6500)), sr, order=2)
    # Soft-knee limiter: leaves the sustained chords clean, only rounds peaks
    # (a hard tanh on everything would add a continuous distorted edge).
    drive = 1.0 / max(np.percentile(np.abs(mono), 99.0), 1e-9)
    mono = mono * drive
    mono = np.where(np.abs(mono) > 0.8, np.sign(mono) * (0.8 + 0.2 * np.tanh((np.abs(mono) - 0.8) / 0.2)), mono)

    # --- stereo: Haas widening on the keys/crackle ------------------------
    delay = int(0.008 * sr)
    right = np.concatenate([np.zeros(delay), mono[:-delay]])
    stereo = np.stack([mono, 0.5 * mono + 0.5 * right], axis=1)
    stereo = _normalize(stereo, peak=0.88)
    return (stereo * 32767.0).astype(np.int16)
