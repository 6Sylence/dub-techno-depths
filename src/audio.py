"""Procedural deep / dub / melodic techno engine.

Everything is synthesized from scratch with numpy — punchy tuned kicks, a rolling
sidechained sub bass, detuned analog-style saw stabs and pads pushed through a
resonant filter that sweeps, the signature dub-delay chord echo, algorithmic
reverb and a breakdown-driven arrangement — so the output is 100% original and
copyright-safe, yet moves and breathes like a real track instead of a flat loop.

Public entry points (unchanged contract):
  snap_loop_seconds(bpm, seconds) -> quantize to whole 8-bar phrases.
  render_loop(preset, seconds, sr, seed) -> a seamless stereo int16 (N, 2) loop.

Seamlessness is structural: every note/echo is added with a circular
``_wrap_add``; every continuous process (EQ, reverb, filter sweep) is a circular
operation (full-buffer FFT, circular convolution, or an FFT-sweep with wrapped
edges); pads are raised-cosine swells that are silent at their ends; and every
LFO completes a whole number of cycles across the loop. So an hour of repeats
has no audible seam, while filter movement and breakdowns keep it from droning.
"""

from __future__ import annotations

import numpy as np

DEFAULT_SR = 44_100

# Chord voicings as semitone offsets from the root (minor-leaning techno palette).
QUALITIES = {
    "min":    [0, 3, 7],
    "min7":   [0, 3, 7, 10],
    "min9":   [0, 3, 7, 10, 14],
    "min11":  [0, 3, 7, 10, 14, 17],
    "minadd9": [0, 3, 7, 14],
    "sus2":   [0, 2, 7],
    "sus4":   [0, 5, 7],
    "maj7":   [0, 4, 7, 11],
    "maj9":   [0, 4, 7, 11, 14],
}


# --------------------------------------------------------------------------- #
# Core helpers (all circular -> seam-safe)
# --------------------------------------------------------------------------- #
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


def _reso_lp(x, cutoff_hz, sr, res=0.0, order=4):
    """Static resonant low-pass (a spectral peak at the cutoff). Full-buffer FFT,
    so it is circular and seam-safe — used per note where the cutoff is fixed."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    g = 1.0 / (1.0 + (f / cutoff_hz) ** order)
    if res > 0:
        g = g * (1.0 + res * np.exp(-((f - cutoff_hz) / (cutoff_hz * 0.18 + 1.0)) ** 2))
    return np.fft.irfft(spec * g, n=x.size)


def _svf_sweep(x, cutoff, sr, res=0.0, order=4, frame=4096, hop=2048):
    """Time-varying resonant low-pass via an STFT whose cutoff moves per frame —
    this is the filter *movement* that makes techno hypnotic. Edges are wrapped
    (circular padding) so the swept signal still loops without a seam.

    ``cutoff`` is a scalar or a per-sample array (an LFO / envelope)."""
    n = x.size
    if np.isscalar(cutoff):
        cutoff = np.full(n, float(cutoff))
    pad = frame
    xp = np.concatenate([x[-pad:], x, x[:pad]])
    cp = np.concatenate([cutoff[-pad:], cutoff, cutoff[:pad]])
    win = np.hanning(frame)
    starts = np.arange(0, xp.size - frame, hop)
    frames = np.stack([xp[s:s + frame] for s in starts]) * win        # (F, frame)
    spec = np.fft.rfft(frames, axis=1)                                # (F, bins)
    f = np.fft.rfftfreq(frame, 1.0 / sr)[None, :]                     # (1, bins)
    fc = np.maximum(cp[starts + frame // 2], 30.0)[:, None]          # (F, 1)
    g = 1.0 / (1.0 + (f / fc) ** order)
    if res > 0:
        g = g * (1.0 + res * np.exp(-((f - fc) / (fc * 0.22 + 1.0)) ** 2))
    out = np.fft.irfft(spec * g, n=frame, axis=1) * win
    y = np.zeros(xp.size)
    wsum = np.zeros(xp.size)
    w2 = win ** 2
    for i, s in enumerate(starts):
        y[s:s + frame] += out[i]
        wsum[s:s + frame] += w2
    wsum[wsum < 1e-9] = 1.0
    y = y / wsum
    return y[pad:pad + n]


def _reverb(x, sr, rng, time=2.0, damp=3800, mix=0.28):
    """Algorithmic reverb by circular convolution with a synthetic decaying-noise
    impulse — circular, so the lush tail wraps around the loop with no seam."""
    L = int(time * sr)
    idx = np.arange(L)
    ir = rng.standard_normal(L) * np.exp(-idx / (0.32 * time * sr))
    ir = _lowpass_fft(ir, damp, sr)
    pre = int(0.006 * sr)
    ir[:pre] *= np.linspace(0.0, 1.0, pre)               # soft onset, no click
    ir = ir / (np.sqrt(np.sum(ir ** 2)) + 1e-9)
    irn = np.zeros(x.size)
    irn[:min(L, x.size)] = ir[:min(L, x.size)]
    wet = np.fft.irfft(np.fft.rfft(x) * np.fft.rfft(irn), n=x.size)
    wet = _normalize(wet, np.max(np.abs(x)) + 1e-9)
    return x * (1.0 - mix) + wet * mix


def _dub_delay(x, sr, bpm, div=0.75, feedback=0.42, damp=2400, taps=16):
    """The dub-techno signature: a tempo-synced feedback echo whose repeats get
    darker and quieter. np.roll is circular, so the trailing echoes wrap the loop
    seamlessly. Returns the wet-only echo signal (mix it under the dry stab)."""
    d = int(div * (60.0 / bpm) * sr)
    if d <= 0:
        return np.zeros_like(x)
    echoes = np.zeros_like(x)
    tap = x.copy()
    for k in range(1, taps + 1):
        tap = _lowpass_fft(np.roll(tap, d), damp, sr) * feedback
        echoes += tap
        if feedback ** k < 0.01:
            break
    return echoes


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


def _saw(freq, t):
    """Naive saw in [-1, 1] (harsh highs get tamed by the filters downstream)."""
    return 2.0 * (freq * t - np.floor(freq * t + 0.5))


def snap_loop_seconds(bpm: float, seconds: float) -> float:
    """Quantize ``seconds`` to a whole number of 8-bar phrases at ``bpm``."""
    bar = 4 * 60.0 / bpm
    phrase = 8 * bar
    phrases = max(1, round(seconds / phrase))
    return phrases * phrase


def _eq(x, sr):
    """Master corrective EQ: high-pass the sub rumble, tame the low-mid mud and
    lift a little air so the mix reads clean and 'produced' on any system."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    g = f ** 2 / (f ** 2 + 28.0 ** 2)                        # HPF ~28 Hz
    g *= 1.0 - 0.30 * np.exp(-((f - 260.0) / 150.0) ** 2)    # -mud ~260 Hz
    g *= 1.0 + 0.12 * (f / (f + 9000.0))                     # gentle air shelf
    return np.fft.irfft(spec * g, n=x.size)


# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #
def _kick(sr, rng, punch=1.0, deep=0.5, sat=0.4):
    """Tuned, punchy techno kick: fast pitch drop into a round sustain, a noise
    transient click, and tanh saturation for weight. ``deep`` lengthens/rounds
    it (dub); ``punch`` raises the attack pitch (driving)."""
    n = int(0.55 * sr)
    idx = np.arange(n)
    f0 = 105.0 + 130.0 * punch
    fb = 44.0 + 8.0 * (1.0 - deep)
    pitch = fb + (f0 - fb) * np.exp(-idx / (0.020 * sr))
    body = np.sin(2 * np.pi * np.cumsum(pitch) / sr)
    body *= np.exp(-idx / ((0.13 + 0.16 * deep) * sr))
    click = _highpass_fft(rng.standard_normal(n), 3200, sr) * np.exp(-idx / (0.004 * sr))
    k = body + 0.5 * click
    drive = 1.6 + 2.0 * sat
    k = np.tanh(k * drive) / np.tanh(drive)
    return _lowpass_fft(k, 4200, sr) * 0.92


def _clap(sr, rng):
    n = int(0.42 * sr)
    idx = np.arange(n)
    noise = _bandpass(rng.standard_normal(n), 1100, 3600, sr)
    env = np.zeros(n)
    for off, g in ((0, 1.0), (int(0.010 * sr), 0.9), (int(0.020 * sr), 0.8)):
        e = np.zeros(n)
        e[off:] = np.exp(-np.arange(n - off) / (0.011 * sr))
        env += g * e
    env += 0.3 * np.exp(-idx / (0.12 * sr))                  # room tail
    return _normalize(noise * env) * 0.5


def _hat(sr, rng, open_=False):
    dur = 0.13 if open_ else 0.04
    n = int(dur * sr)
    idx = np.arange(n)
    x = rng.standard_normal(n) * np.exp(-idx / (sr * (0.055 if open_ else 0.012)))
    return _normalize(_highpass_fft(x, 8200, sr)) * (0.34 if open_ else 0.30)


def _rim(sr, rng):
    n = int(0.05 * sr)
    idx = np.arange(n)
    tone = np.sin(2 * np.pi * 1750 * idx / sr) * np.exp(-idx / (0.006 * sr))
    noise = _bandpass(rng.standard_normal(n), 2000, 5500, sr) * np.exp(-idx / (0.004 * sr))
    return _normalize(tone + 0.5 * noise) * 0.38


def _bass_note(sr, freq, dur, mode="roll", detune=0.006):
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    if mode == "reese":
        tone = (_saw(freq * (1 - detune), t) + _saw(freq * (1 + detune), t)
                + 0.7 * _saw(freq, t))
        tone = _lowpass_fft(tone, freq * 6 + 320, sr)
    else:
        tone = np.sin(2 * np.pi * freq * t) + 0.22 * np.sin(4 * np.pi * freq * t)
    env = np.minimum(idx / (0.008 * sr), 1.0) * np.exp(-idx / (0.42 * sr))
    return _lowpass_fft(np.tanh(tone * 1.2) * env, 280, sr)


def _stab(sr, root_midi, quality, dur, cutoff, res, detune=0.008):
    """Short detuned-saw chord stab through a resonant low-pass — the body the
    dub delay then throws into the distance."""
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    tone = np.zeros(n)
    for semi in QUALITIES[quality]:
        f = _midi_hz(root_midi + semi)
        tone += _saw(f * (1 - detune), t) + _saw(f * (1 + detune), t)
    env = np.minimum(idx / (0.004 * sr), 1.0) * np.exp(-idx / (0.11 * sr))
    return _normalize(_reso_lp(tone * env, cutoff, sr, res=res))


def _pad_swell(sr, root_midi, quality, dur, cutoff, detune=0.010, octave=True):
    """A slow raised-cosine swell (silent at both ends, so it wraps) of a wide,
    detuned saw chord — the deep atmosphere under everything."""
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    tone = np.zeros(n)
    voices = QUALITIES[quality]
    for semi in voices:
        for dt in (-detune, detune):
            tone += _saw(_midi_hz(root_midi + semi) * (1 + dt), t)
    if octave:
        tone += 0.6 * _saw(_midi_hz(root_midi - 12), t)
    env = np.sin(np.pi * idx / n) ** 1.4                    # 0 at both ends
    return _reso_lp(tone * env, cutoff, sr) / max(len(voices), 1)


def _pluck(sr, freq, dur, cutoff=None):
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    tone = _saw(freq, t) + 0.5 * np.sin(2 * np.pi * freq * t)
    env = np.minimum(idx / (0.003 * sr), 1.0) * np.exp(-idx / (0.16 * sr))
    return _reso_lp(tone * env, cutoff or (freq * 5 + 900), sr, res=0.35)


def _riser(sr, dur, rng):
    n = int(dur * sr)
    idx = np.arange(n)
    x = _bandpass(rng.standard_normal(n), 600, 8000, sr)
    return _normalize(x * (idx / n) ** 2) * 0.5


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #
def render_loop(preset: dict, seconds: float, sr: int = DEFAULT_SR,
                seed: int | None = None) -> np.ndarray:
    """Render a seamless stereo techno loop. Returns int16 (N, 2).

    ``preset`` (the ``audio`` section) supports:
      bpm, progression [[root_midi, quality], ...], style (dub|melodic|driving),
      kick_gain, kick_punch, kick_deep, bass_gain, bass_mode (roll|reese),
      stab_gain, pad_gain, arp_gain, filter_base, filter_lfo, resonance,
      delay_div, delay_feedback, delay_gain, reverb, hat_gain, master_cut.
    """
    rng = np.random.default_rng(seed)
    bpm = float(preset.get("bpm", 124))
    seconds = snap_loop_seconds(bpm, seconds)
    n = int(round(seconds * sr))

    beat = 60.0 / bpm
    beat_s = beat * sr
    bar_s = 4 * beat_s
    six = bar_s / 16.0                          # samples per 16th note
    n_bars = int(round(seconds / (4 * beat)))
    n_phrases = max(1, n_bars // 8)

    style = preset.get("style", "dub")
    prog = preset["progression"]

    # Interior breakdowns (never straddling the loop seam, so tiling stays clean).
    break_phrases = set()
    if n_phrases >= 6:
        for base_p in range(0, n_phrases, 8):
            p = base_p + 6
            if 0 < p < n_phrases - 1:
                break_phrases.add(p)

    drums = np.zeros(n)
    bass = np.zeros(n)
    stab = np.zeros(n)
    pad = np.zeros(n)
    arp = np.zeros(n)

    hat_gain = float(preset.get("hat_gain", 1.0))
    bass_mode = preset.get("bass_mode", "roll")
    stab_cut = float(preset.get("stab_cut", 2600))
    resonance = float(preset.get("resonance", 0.5))
    pcut = float(preset.get("pad_cut", 1400))
    pad_dur = 2 * (4 * beat)

    # Precompute each voice ONCE and reuse it (with small gain/selection jitter
    # for humanization). Synthesizing every hit from scratch means thousands of
    # FFTs; caching cuts the render from minutes to seconds with no audible loss.
    kick = _kick(sr, rng,
                 punch=float(preset.get("kick_punch", 1.0)),
                 deep=float(preset.get("kick_deep", 0.5)),
                 sat=float(preset.get("kick_sat", 0.4))) * float(preset.get("kick_gain", 1.0))
    clap_pool = [_clap(sr, rng) for _ in range(6)]
    hat_c_pool = [_hat(sr, rng, open_=False) for _ in range(8)]
    hat_o_pool = [_hat(sr, rng, open_=True) for _ in range(6)]
    rim_pool = [_rim(sr, rng) for _ in range(4)]
    riser = _riser(sr, 2 * beat, rng)

    stab_cache, pad_cache, bass_cache, pluck_cache = {}, {}, {}, {}
    for root, qual in prog:
        if (root, qual) not in stab_cache:
            stab_cache[(root, qual)] = _stab(sr, root, qual, beat * 0.9, stab_cut, resonance)
            pad_cache[(root, qual)] = _pad_swell(sr, root, qual, pad_dur, pcut)
        if root not in bass_cache:
            bass_cache[root] = _bass_note(sr, _midi_hz(root - 12), beat * 0.6, bass_mode)

    def _pick(pool):
        return pool[int(rng.integers(0, len(pool)))]

    for b in range(n_bars):
        base = b * bar_s
        root, qual = prog[b % len(prog)]
        phrase = b // 8
        is_break = phrase in break_phrases
        last_bar_of_break = is_break and (b % 8 == 7)

        # --- drums: four-on-the-floor (muted through breakdowns) --------------
        if not is_break:
            for beat_i in range(4):
                _wrap_add(drums, kick, base + beat_i * beat_s)
            for step in (4, 12):                                # clap backbeat
                _wrap_add(drums, _pick(clap_pool), base + step * six)
            for step in range(0, 16, 2):                        # offbeat hats
                op = (step % 4 == 2)                            # open on the '&'
                h = _pick(hat_o_pool if op else hat_c_pool) * hat_gain * rng.uniform(0.75, 1.0)
                _wrap_add(drums, h, base + step * six)
            if style == "driving" and b % 2 == 1:               # ride ticks
                for step in (6, 14):
                    _wrap_add(drums, _pick(rim_pool) * 0.7, base + step * six)
        else:
            for step in range(4, 16, 4):                        # sparse soft hats
                _wrap_add(drums, _pick(hat_c_pool) * hat_gain * 0.4, base + step * six)

        # --- bass: rolling offbeat 16ths, sidechained later ------------------
        if not is_break:
            for step in (2, 6, 10, 14):
                if rng.random() < 0.9:
                    _wrap_add(bass, bass_cache[root] * rng.uniform(0.9, 1.0),
                              base + step * six)

        # --- stab: syncopated dub chord (feeds the delay) --------------------
        stab_steps = (6, 14) if style != "melodic" else (6,)
        for step in stab_steps:
            if is_break and step != 6:
                continue
            _wrap_add(stab, stab_cache[(root, qual)] * rng.uniform(0.85, 1.0),
                      base + step * six)

        # --- pad: a 2-bar swell every 2 bars (deep atmosphere) ---------------
        if b % 2 == 0:
            _wrap_add(pad, pad_cache[(root, qual)], base)

        # --- arp: melodic 16th-note arpeggio ---------------------------------
        if style == "melodic":
            notes = [root + s for s in QUALITIES[qual]]
            for step in range(16):
                if rng.random() < 0.8:
                    m = notes[step % len(notes)] + (12 if step % 8 >= 4 else 0)
                    if m not in pluck_cache:
                        pluck_cache[m] = _pluck(sr, _midi_hz(m), beat * 0.5)
                    _wrap_add(arp, pluck_cache[m], base + step * six)

        # --- riser into the drop at the end of a breakdown -------------------
        if last_bar_of_break:
            _wrap_add(drums, riser, base + 8 * six)

    # --- process stems ------------------------------------------------------
    # Stab: dub delay echoes + reverb — the hypnotic tail.
    stab = _normalize(stab) * float(preset.get("stab_gain", 0.9))
    wet = _dub_delay(stab, sr, bpm,
                     div=float(preset.get("delay_div", 0.75)),
                     feedback=float(preset.get("delay_feedback", 0.42)))
    stab = stab + wet * float(preset.get("delay_gain", 0.9))
    stab = _reverb(stab, sr, rng, time=2.2, mix=0.22)

    # Pad: slow filter sweep + big reverb so the bed evolves and blooms.
    pad = _normalize(pad) * float(preset.get("pad_gain", 0.6))
    lfo_cycles = int(preset.get("filter_lfo_cycles", max(2, n_phrases // 4)))
    fbase = float(preset.get("filter_base", 900))
    fdepth = float(preset.get("filter_depth", 1500))
    cutoff_env = fbase + fdepth * (0.5 + 0.5 * np.sin(
        2 * np.pi * lfo_cycles * np.arange(n) / n))
    pad = _svf_sweep(pad, cutoff_env, sr, res=0.2)
    pad = _reverb(pad, sr, rng, time=3.0, damp=3000, mix=0.42)

    arp = _reverb(_normalize(arp) * float(preset.get("arp_gain", 0.0)),
                  sr, rng, time=1.8, mix=0.3) if style == "melodic" else arp * 0.0

    # --- sidechain: duck the tonal elements under every kick ----------------
    pump = np.ones(n)
    duck_len = int(0.26 * sr)
    depth = float(preset.get("sidechain", 0.55))
    duck = 1.0 - depth * np.exp(-np.arange(duck_len) / (0.09 * sr))
    for b in range(n_bars):
        if (b // 8) in break_phrases:
            continue
        for beat_i in range(4):
            s = int(b * bar_s + beat_i * beat_s) % n
            e = min(s + duck_len, n)
            pump[s:e] = np.minimum(pump[s:e], duck[: e - s])

    bass = _normalize(bass) * float(preset.get("bass_gain", 0.9))

    music = (drums * 0.9
             + pump * (bass + stab + pad + arp))

    # --- master chain -------------------------------------------------------
    mono = _eq(music, sr)
    # Slow master filter open/close across the loop — the whole track breathes.
    if preset.get("master_sweep", True):
        mcycles = int(preset.get("master_sweep_cycles", 2))
        mbase = float(preset.get("master_sweep_base", 5000))
        mdepth = float(preset.get("master_sweep_depth", 3500))
        menv = mbase + mdepth * (0.5 + 0.5 * np.sin(
            2 * np.pi * mcycles * np.arange(n) / n - np.pi / 2))
        mono = _svf_sweep(mono, menv, sr, res=0.0, order=2)
    mono = _lowpass_fft(mono, float(preset.get("master_cut", 15000)), sr, order=2)

    # Soft-knee peak limiter (rounds peaks, leaves the body clean).
    drive = 1.0 / max(np.percentile(np.abs(mono), 99.5), 1e-9)
    mono = mono * drive
    over = np.abs(mono) > 0.8
    mono[over] = np.sign(mono[over]) * (0.8 + 0.2 * np.tanh((np.abs(mono[over]) - 0.8) / 0.2))

    # --- stereo: keep the low end mono, widen the highs (Haas, circular) ----
    low = _lowpass_fft(mono, 200, sr)
    high = mono - low
    d = int(0.007 * sr)
    high_r = np.roll(high, d)
    left = low + high
    right = low + 0.35 * high + 0.65 * high_r
    stereo = np.stack([left, right], axis=1)
    stereo = _normalize(stereo, peak=0.9)
    return (stereo * 32767.0).astype(np.int16)
