"""Procedural bass-boosted EDM / Melbourne-bounce / electro-house engine.

Everything is synthesized from scratch with numpy — a huge punchy kick, the
signature pitched "donk" bounce bass on the offbeats, detuned supersaw drop
chords, a catchy pluck lead, hard sidechain pump, snare-roll builds and riser
sweeps into the drop — so the output is 100% original and copyright-safe, yet
hits with the loud, bass-heavy energy of the big car-music mixes.

Public entry points (unchanged contract):
  snap_loop_seconds(bpm, seconds) -> quantize to whole 8-bar phrases.
  render_loop(preset, seconds, sr, seed) -> a seamless stereo int16 (N, 2) loop.

Seamlessness is structural: every hit/echo is added with a circular
``_wrap_add``; every continuous process (EQ, reverb, filter sweep) is circular
(full-buffer FFT / circular convolution / wrapped-edge STFT); every LFO does a
whole number of cycles across the loop; and builds/breakdowns sit in the loop
interior, never on the seam — so an hour of repeats loops without a click while
the drops keep it energetic.
"""

from __future__ import annotations

import numpy as np

DEFAULT_SR = 44_100

# Chord voicings as semitone offsets from the root.
QUALITIES = {
    "min":    [0, 3, 7],
    "min7":   [0, 3, 7, 10],
    "min9":   [0, 3, 7, 10, 14],
    "sus2":   [0, 2, 7],
    "sus4":   [0, 5, 7],
    "maj":    [0, 4, 7],
    "maj7":   [0, 4, 7, 11],
    "maj9":   [0, 4, 7, 11, 14],
    "add9":   [0, 4, 7, 14],
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
    so it is circular and seam-safe."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    g = 1.0 / (1.0 + (f / cutoff_hz) ** order)
    if res > 0:
        g = g * (1.0 + res * np.exp(-((f - cutoff_hz) / (cutoff_hz * 0.18 + 1.0)) ** 2))
    return np.fft.irfft(spec * g, n=x.size)


def _svf_sweep(x, cutoff, sr, res=0.0, order=4, frame=4096, hop=2048):
    """Time-varying resonant low-pass via an STFT whose cutoff moves per frame —
    the classic EDM filter sweep. Edges wrap (circular padding) so the swept
    signal still loops without a seam. ``cutoff`` is scalar or per-sample."""
    n = x.size
    if np.isscalar(cutoff):
        cutoff = np.full(n, float(cutoff))
    pad = frame
    xp = np.concatenate([x[-pad:], x, x[:pad]])
    cp = np.concatenate([cutoff[-pad:], cutoff, cutoff[:pad]])
    win = np.hanning(frame)
    starts = np.arange(0, xp.size - frame, hop)
    frames = np.stack([xp[s:s + frame] for s in starts]) * win
    spec = np.fft.rfft(frames, axis=1)
    f = np.fft.rfftfreq(frame, 1.0 / sr)[None, :]
    fc = np.maximum(cp[starts + frame // 2], 30.0)[:, None]
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
    return (y / wsum)[pad:pad + n]


def _reverb(x, sr, rng, time=1.6, damp=4200, mix=0.22):
    """Algorithmic reverb by circular convolution with a synthetic decaying-noise
    impulse — circular, so the tail wraps the loop with no seam."""
    L = int(time * sr)
    idx = np.arange(L)
    ir = rng.standard_normal(L) * np.exp(-idx / (0.30 * time * sr))
    ir = _lowpass_fft(ir, damp, sr)
    pre = int(0.006 * sr)
    ir[:pre] *= np.linspace(0.0, 1.0, pre)
    ir = ir / (np.sqrt(np.sum(ir ** 2)) + 1e-9)
    irn = np.zeros(x.size)
    irn[:min(L, x.size)] = ir[:min(L, x.size)]
    wet = np.fft.irfft(np.fft.rfft(x) * np.fft.rfft(irn), n=x.size)
    wet = _normalize(wet, np.max(np.abs(x)) + 1e-9)
    return x * (1.0 - mix) + wet * mix


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
    return 2.0 * (freq * t - np.floor(freq * t + 0.5))


def snap_loop_seconds(bpm: float, seconds: float) -> float:
    """Quantize ``seconds`` to a whole number of 8-bar phrases at ``bpm``."""
    bar = 4 * 60.0 / bpm
    phrase = 8 * bar
    phrases = max(1, round(seconds / phrase))
    return phrases * phrase


def _eq(x, sr, bass_boost=0.35):
    """Master EQ: keep the deep sub, BOOST the low end (bass-boosted), tame the
    low-mid mud so the bass stays punchy, and lift a bright air shelf."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    g = f ** 2 / (f ** 2 + 26.0 ** 2)                        # HPF ~26 Hz (keep sub)
    g *= 1.0 + bass_boost * (65.0 ** 2 / (f ** 2 + 65.0 ** 2))  # tight low-shelf boost
    g *= 1.0 - 0.28 * np.exp(-((f - 320.0) / 180.0) ** 2)    # -mud, keeps bass clean
    g *= 1.0 + 0.55 * (f / (f + 6000.0))                     # bright air/high shelf
    return np.fft.irfft(spec * g, n=x.size)


# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #
def _kick(sr, rng, punch=1.2, sub=0.7, sat=0.6):
    """Big EDM kick: snappy click, fast pitch drop, and a rounded sub tail so it
    reads huge on a subwoofer."""
    n = int(0.5 * sr)
    idx = np.arange(n)
    f0 = 150.0 + 140.0 * punch
    fb = 46.0
    pitch = fb + (f0 - fb) * np.exp(-idx / (0.016 * sr))
    body = np.sin(2 * np.pi * np.cumsum(pitch) / sr) * np.exp(-idx / (0.11 * sr))
    tail = np.sin(2 * np.pi * fb * idx / sr) * np.exp(-idx / (0.19 * sr)) * sub
    click = _highpass_fft(rng.standard_normal(n), 3500, sr) * np.exp(-idx / (0.003 * sr))
    k = body + tail + 0.55 * click
    drive = 1.8 + 2.4 * sat
    k = np.tanh(k * drive) / np.tanh(drive)
    k *= np.minimum(idx / (0.0015 * sr), 1.0)     # 1.5 ms attack: no hard step at t=0
    return _lowpass_fft(k, 5200, sr) * 0.95


def _donk(sr, freq, dur, rng, drive=1.8):
    """The Melbourne-bounce 'donk': a pitched, punchy offbeat bass hit. A saw+
    square with a fast octave pitch-drop, band-limited and slightly overdriven,
    with a short percussive decay — the boing that makes it bounce."""
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    pitch = freq * (1.0 + 1.0 * np.exp(-idx / (0.014 * sr)))     # drop ~1 octave
    ph = 2 * np.pi * np.cumsum(pitch) / sr
    tone = _saw(1.0, ph / (2 * np.pi)) + 0.6 * np.sign(np.sin(ph))
    env = np.minimum(idx / (0.004 * sr), 1.0) * np.exp(-idx / (0.11 * sr))
    env *= np.minimum((n - idx) / (0.008 * sr), 1.0)             # release to 0 at end
    tone = np.tanh(tone * drive) * env
    return _bandpass(tone, 70, 900, sr)


def _sub(sr, freq, dur):
    """Clean sine sub that holds the low end under the donk on the downbeats."""
    n = int(dur * sr)
    idx = np.arange(n)
    env = np.minimum(idx / (0.006 * sr), 1.0) * np.exp(-idx / (0.5 * sr))
    env *= np.minimum((n - idx) / (0.015 * sr), 1.0)            # release to 0 at end
    return _lowpass_fft(np.sin(2 * np.pi * freq * idx / sr) * env, 150, sr)


def _supersaw(sr, root, quality, dur, cutoff, detune=0.012, voices=7):
    """Big detuned-saw chord (the festival/big-room drop chord)."""
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    tone = np.zeros(n)
    for semi in QUALITIES[quality]:
        f = _midi_hz(root + semi)
        for v in range(voices):
            dt = detune * (v - (voices - 1) / 2) / max((voices - 1) / 2, 1)
            tone += _saw(f * (1 + dt), t)
    env = np.minimum(idx / (0.008 * sr), 1.0) * np.minimum((n - idx) / (0.02 * sr), 1.0)
    return _reso_lp(tone * env, cutoff, sr, res=0.25) / (len(QUALITIES[quality]) * voices)


def _pluck(sr, freq, dur, cutoff=None):
    """Bright pluck lead for the topline riff."""
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    tone = _saw(freq, t) + _saw(freq * 1.005, t) + 0.5 * np.sin(2 * np.pi * freq * t)
    env = np.minimum(idx / (0.003 * sr), 1.0) * np.exp(-idx / (0.14 * sr))
    env *= np.minimum((n - idx) / (0.006 * sr), 1.0)           # release to 0 at end
    return _reso_lp(tone * env, cutoff or (freq * 6 + 1200), sr, res=0.4) * 0.6


def _clap(sr, rng):
    n = int(0.34 * sr)
    idx = np.arange(n)
    noise = _bandpass(rng.standard_normal(n), 1200, 4200, sr)
    env = np.zeros(n)
    for off, g in ((0, 1.0), (int(0.009 * sr), 0.9), (int(0.018 * sr), 0.8)):
        e = np.zeros(n)
        e[off:] = np.exp(-np.arange(n - off) / (0.010 * sr))
        env += g * e
    env += 0.28 * np.exp(-idx / (0.10 * sr))
    return _normalize(noise * env) * 0.55


def _snare(sr, rng):
    n = int(0.16 * sr)
    idx = np.arange(n)
    noise = _bandpass(rng.standard_normal(n), 1400, 6500, sr) * np.exp(-idx / (0.05 * sr))
    body = np.sin(2 * np.pi * 220 * idx / sr) * np.exp(-idx / (0.05 * sr))
    return _normalize(0.8 * noise + 0.4 * body) * 0.5


def _hat(sr, rng, open_=False):
    dur = 0.14 if open_ else 0.035
    n = int(dur * sr)
    idx = np.arange(n)
    x = rng.standard_normal(n) * np.exp(-idx / (sr * (0.06 if open_ else 0.010)))
    return _normalize(_highpass_fft(x, 8500, sr)) * (0.42 if open_ else 0.38)


def _sweep(sr, dur, rng, up=True):
    """White-noise riser (up) or downsweep for build/drop transitions."""
    n = int(dur * sr)
    idx = np.arange(n)
    x = _bandpass(rng.standard_normal(n), 600, 9000, sr)
    env = (idx / n) ** 2 if up else (1 - idx / n) ** 2
    return _normalize(x * env) * 0.5


def _impact(sr, rng):
    """Sub boom + noise splash on the drop's downbeat."""
    n = int(1.0 * sr)
    idx = np.arange(n)
    boom = np.sin(2 * np.pi * (90 * np.exp(-idx / (0.2 * sr)) + 45) * idx / sr) * np.exp(-idx / (0.4 * sr))
    splash = _bandpass(rng.standard_normal(n), 800, 8000, sr) * np.exp(-idx / (0.25 * sr))
    return _normalize(boom + 0.4 * splash) * 0.8


# Vowel formant triples (F1, F2, F3) in Hz — the resonances that make a vowel.
VOWELS = {
    "ah": (800.0, 1150.0, 2800.0),
    "oh": (400.0, 800.0, 2600.0),
    "eh": (500.0, 1700.0, 2500.0),
    "oo": (330.0, 800.0, 2400.0),
}


def _formant(x, fc, bw, sr):
    """Isolate a formant band (a soft spectral peak) — circular, seam-safe."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    g = np.exp(-((f - fc) / bw) ** 2)
    return np.fft.irfft(spec * g, n=x.size)


def _vocal(sr, freq, dur, rng, vowel="ah"):
    """Synthetic vocal chop: a glottal saw run through vowel formants, with light
    vibrato and a breathy onset — a wordless 'aah/ooh' hook, 100% original."""
    n = int(dur * sr)
    idx = np.arange(n)
    t = idx / sr
    vib = 1.0 + 0.012 * np.sin(2 * np.pi * 5.5 * t)             # vocal vibrato
    src = _saw(freq, t * vib) + 0.3 * _saw(2 * freq, t * vib)
    f1, f2, f3 = VOWELS.get(vowel, VOWELS["ah"])
    voiced = (_formant(src, f1, 90, sr)
              + 0.7 * _formant(src, f2, 130, sr)
              + 0.35 * _formant(src, f3, 180, sr))
    breath = _bandpass(rng.standard_normal(n), 2000, 6000, sr) * np.exp(-idx / (0.02 * sr)) * 0.15
    env = np.minimum(idx / (0.02 * sr), 1.0) * np.exp(-idx / (0.28 * sr))
    env *= np.minimum((n - idx) / (0.02 * sr), 1.0)            # release to 0 at end
    return _normalize((voiced + breath) * env)


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #
def render_loop(preset: dict, seconds: float, sr: int = DEFAULT_SR,
                seed: int | None = None) -> np.ndarray:
    """Render a seamless stereo bass-boosted EDM loop. Returns int16 (N, 2).

    ``preset`` (the ``audio`` section) supports:
      bpm, progression [[root_midi, quality], ...], style (bounce|bigroom|electro),
      kick_gain, kick_punch, kick_sub, donk_gain, donk_drive, sub_gain,
      chord_gain, chord_cut, lead_gain, hat_gain, sidechain, bass_boost,
      loudness, filter_base, filter_depth, master_cut.
    """
    rng = np.random.default_rng(seed)
    bpm = float(preset.get("bpm", 126))
    seconds = snap_loop_seconds(bpm, seconds)
    n = int(round(seconds * sr))

    beat = 60.0 / bpm
    beat_s = beat * sr
    bar_s = 4 * beat_s
    six = bar_s / 16.0
    n_bars = int(round(seconds / (4 * beat)))
    n_phrases = max(1, n_bars // 8)

    style = preset.get("style", "bounce")
    prog = preset["progression"]

    # Interior build/breakdown phrases (away from the seam) for drop dynamics.
    break_phrases = set()
    if n_phrases >= 6:
        for base_p in range(0, n_phrases, 8):
            p = base_p + 6
            if 0 < p < n_phrases - 1:
                break_phrases.add(p)

    drums = np.zeros(n)
    subb = np.zeros(n)
    donkb = np.zeros(n)
    chords = np.zeros(n)
    lead = np.zeros(n)
    vox = np.zeros(n)
    fx = np.zeros(n)

    hat_gain = float(preset.get("hat_gain", 1.0))
    chord_cut = float(preset.get("chord_cut", 4200))
    donk_drive = float(preset.get("donk_drive", 1.8))

    # Precompute voices once (with jitter on placement) -> fast render.
    kick = _kick(sr, rng, punch=float(preset.get("kick_punch", 1.2)),
                 sub=float(preset.get("kick_sub", 0.7))) * float(preset.get("kick_gain", 1.0))
    clap_pool = [_clap(sr, rng) for _ in range(4)]
    snare_pool = [_snare(sr, rng) for _ in range(4)]
    hat_c_pool = [_hat(sr, rng, open_=False) for _ in range(8)]
    hat_o_pool = [_hat(sr, rng, open_=True) for _ in range(4)]
    riser = _sweep(sr, 2 * beat, rng, up=True)
    impact = _impact(sr, rng)

    donk_cache, chord_cache, sub_cache, pluck_cache, vox_cache = {}, {}, {}, {}, {}
    vocal_gain = float(preset.get("vocal_gain", 0.0))
    vowel = preset.get("vowel", "ah")
    for root, qual in prog:
        if (root, qual) not in chord_cache:
            chord_cache[(root, qual)] = _supersaw(sr, root, qual, 4 * beat, chord_cut)
        if root not in donk_cache:
            donk_cache[root] = _donk(sr, _midi_hz(root - 12), beat * 0.5, rng, donk_drive)
            sub_cache[root] = _sub(sr, _midi_hz(root - 12), beat * 0.9)

    def _pick(pool):
        return pool[int(rng.integers(0, len(pool)))]

    def _vox_note(m):
        if m not in vox_cache:
            vox_cache[m] = _vocal(sr, _midi_hz(m), beat * 0.9, rng, vowel)
        return vox_cache[m]

    lead_gain_base = float(preset.get("lead_gain", 0.7))

    # A catchy 2-bar lead motif that REPEATS across the track (transposed to each
    # bar's chord) — the memorable topline hook that defines the car-music EDM
    # sound. Seeded, so every track in a mix gets a different hook.
    mrng = np.random.default_rng((seed or 0) + 4242)
    motif = []
    mi = int(mrng.integers(0, 4))
    for st in range(32):                                # 32 sixteenths = 2 bars
        if mrng.random() < 0.5:
            mi = int(np.clip(mi + mrng.integers(-2, 3), 0, 6))
            motif.append((st, mi))

    for b in range(n_bars):
        base = b * bar_s
        root, qual = prog[b % len(prog)]
        phrase = b // 8
        is_break = phrase in break_phrases
        last_bar_of_break = is_break and (b % 8 == 7)

        # --- drums --------------------------------------------------------
        if not is_break:
            for step in (0, 4, 8, 12):                        # four-on-the-floor
                _wrap_add(drums, kick, base + step * six)
            for step in (4, 12):                              # clap on 2 & 4
                _wrap_add(drums, _pick(clap_pool), base + step * six)
            for step in range(0, 16, 2):                      # driving hats
                op = (step % 4 == 2)                          # open on the '&'
                h = _pick(hat_o_pool if op else hat_c_pool) * hat_gain * rng.uniform(0.8, 1.0)
                _wrap_add(drums, h, base + step * six)
        elif last_bar_of_break:
            roll = snare_pool[0]                              # snare-roll build-up
            steps = 32 if (b % 2 == 0) else 16
            for i in range(steps):
                g = 0.4 + 0.6 * (i / steps)
                _wrap_add(drums, _pick(snare_pool) * g, base + i * (bar_s / steps))
        else:
            for step in (0, 8):
                _wrap_add(drums, _pick(hat_c_pool) * hat_gain * 0.5, base + step * six)

        # --- low end: kick-synced sub + offbeat donk bounce (separate buses
        #     so the deep sub is not swamped by the low-mid donk) -------------
        if not is_break:
            for step in (0, 4, 8, 12):                        # deep sub on the beat
                _wrap_add(subb, sub_cache[root], base + step * six)
            donk_steps = (2, 6, 10, 14) if style != "electro" else (2, 3, 6, 10, 11, 14)
            for step in donk_steps:
                _wrap_add(donkb, donk_cache[root] * rng.uniform(0.9, 1.0), base + step * six)

        # --- drop chords (supersaw) --------------------------------------
        cg = float(preset.get("chord_gain", 0.8)) * (0.6 if is_break else 1.0)
        _wrap_add(chords, chord_cache[(root, qual)] * cg, base)

        # --- lead: catchy melodic hook (repeats every 2 bars, follows chords) --
        if not is_break and lead_gain_base > 0:
            pool = ([root + 12 + s for s in QUALITIES[qual]]
                    + [root + 24 + s for s in QUALITIES[qual][:2]])
            for mst, mi_ in motif:
                if mst // 16 != (b % 2):                # this note's bar in the 2-bar motif
                    continue
                m = pool[mi_ % len(pool)]
                if m not in pluck_cache:
                    pluck_cache[m] = _pluck(sr, _midi_hz(m), beat * 0.5)
                _wrap_add(lead, pluck_cache[m] * lead_gain_base, base + (mst % 16) * six)

        # --- vocal chop hook (the 'voices') ------------------------------
        if vocal_gain > 0 and not is_break:
            vnotes = [root + 12 + s for s in QUALITIES[qual]]
            vpattern = ((0, 0), (6, 2), (8, 1), (14, 2)) if b % 2 == 0 else ((4, 1), (10, 0))
            for step, deg in vpattern:
                if rng.random() < 0.9:
                    _wrap_add(vox, _vox_note(vnotes[deg % len(vnotes)]) * vocal_gain,
                              base + step * six)

        # --- transitions: riser into the drop, impact on the drop -------
        if last_bar_of_break:
            _wrap_add(fx, riser, base + 8 * six)
        if is_break and (b % 8 == 0):                         # downsweep into break
            _wrap_add(fx, _sweep(sr, 2 * beat, rng, up=False), base)
        if (phrase - 1) in break_phrases and (b % 8 == 0):    # drop hit
            _wrap_add(fx, impact, base)

    # --- sidechain: hard pump on every kick (the EDM 'breathe') ----------
    pump = np.ones(n)
    duck_len = int(0.30 * sr)
    depth = float(preset.get("sidechain", 0.8))
    duck = 1.0 - depth * np.exp(-np.arange(duck_len) / (0.10 * sr))
    for b in range(n_bars):
        if (b // 8) in break_phrases:
            continue
        for step in (0, 4, 8, 12):
            s = int(base := b * bar_s + step * six) % n
            e = min(s + duck_len, n)
            pump[s:e] = np.minimum(pump[s:e], duck[: e - s])

    # --- process stems ---------------------------------------------------
    chords = _reverb(_normalize(chords), sr, rng, time=1.6, mix=0.18)
    lead = _reverb(_normalize(lead) if lead.any() else lead, sr, rng, time=1.4, mix=0.22)
    if vox.any():                                                # vocal chops: slap delay + reverb
        d = int(0.75 * beat_s)
        vox = vox + np.roll(_lowpass_fft(vox, 3500, sr), d) * 0.35
        vox = _reverb(_normalize(vox), sr, rng, time=1.8, mix=0.3)
    fx = _normalize(fx) if fx.any() else fx

    # Low end split by role: the deep sub plays WITH the kick and must stay OUT
    # of the sidechain (ducking it there would cancel it); the offbeat donk sits
    # inside the pump so it 'breathes' between kicks — the classic bounce feel.
    bass_boost = float(preset.get("bass_boost", 0.45))
    subb = _normalize(subb)
    donkb = _normalize(donkb) if donkb.any() else donkb
    sub_mix = subb * float(preset.get("sub_gain", 0.8)) * 1.5
    sub_mix = sub_mix + _lowpass_fft(subb, 85, sr) * (1.0 * bass_boost)
    donk_mix = donkb * float(preset.get("donk_gain", 1.0))

    music = (drums * float(preset.get("kick_bus", 1.0))
             + sub_mix * float(preset.get("low_bus", 1.5))
             + pump * (donk_mix * float(preset.get("donk_bus", 1.2))
                       + chords * float(preset.get("chord_bus", 0.8)) + lead + vox)
             + fx * 0.9)

    # --- master ----------------------------------------------------------
    mono = _eq(music, sr, bass_boost=bass_boost)
    mono = _lowpass_fft(mono, float(preset.get("master_cut", 17000)), sr, order=2)

    loud = float(preset.get("loudness", 1.3))
    thr = 0.60
    drive = loud / max(np.percentile(np.abs(mono), 99.0), 1e-9)
    mono = mono * drive
    over = np.abs(mono) > thr
    mono[over] = np.sign(mono[over]) * (thr + (1.0 - thr) * np.tanh((np.abs(mono[over]) - thr) / (1.0 - thr)))

    # --- stereo: mono low end, widened highs (Haas, circular) -----------
    low = _lowpass_fft(mono, 190, sr)
    high = mono - low
    d = int(0.007 * sr)
    high_r = np.roll(high, d)
    left = low + high
    right = low + 0.35 * high + 0.65 * high_r
    stereo = np.stack([left, right], axis=1)
    stereo = _normalize(stereo, peak=0.97)
    return (stereo * 32767.0).astype(np.int16)


def render_mix(presets: list, total_seconds: float, sr: int = DEFAULT_SR,
               seed: int | None = None, track_seconds: float = 180.0,
               max_block: float = 1200.0) -> np.ndarray:
    """Render a DJ-style MIX of several different tracks (not one repeated loop).

    Each track uses a different preset, a transposed key and its own seed, so the
    music actually changes every few minutes like the reference 1-3h mixes. The
    tracks are equal-power crossfaded, and the whole block is wrap-seamless (its
    tail crossfades into its head) so the pipeline can tile it to any length with
    no click. Returns int16 (M, 2); M ~= min(total_seconds, max_block).
    """
    base_seed = int(seed if seed is not None else 0)
    block = min(float(total_seconds), max_block)
    n_tracks = max(1, int(round(block / track_seconds)))
    xf = int(1.5 * sr)

    npre = len(presets)
    # A preset order that visits every preset with no immediate repeat: step by a
    # stride coprime to the count so consecutive tracks are always a different
    # preset. Start offset varies the daily rotation.
    stride = next((k for k in (5, 4, 3, 2) if npre % k), 1)
    order = [(base_seed + i * stride) % npre for i in range(n_tracks)]

    segs = []
    prev_key = None
    prev_style = None
    for i in range(n_tracks):
        p = presets[order[i]]
        trng = np.random.default_rng(base_seed + 7919 * (i + 1))
        ap = dict(p["audio"])

        # Different KEY from the previous track.
        key = int(trng.integers(-4, 5))
        while key == prev_key:
            key = int(trng.integers(-4, 5))
        prev_key = key
        ap["progression"] = [[r + key, q] for r, q in ap["progression"]]

        # Different TEMPO (±4 BPM) so no two tracks share a groove feel.
        ap["bpm"] = float(ap.get("bpm", 126)) + int(trng.integers(-4, 5))

        # Vary the CHARACTER: lead brightness, vocal presence, and occasionally
        # swap the style, so even a repeated preset never sounds like last time.
        ap["lead_gain"] = float(ap.get("lead_gain", 0.7)) * float(trng.uniform(0.75, 1.25))
        base_vox = float(ap.get("vocal_gain", 0.0))
        ap["vocal_gain"] = 0.0 if (base_vox > 0 and trng.random() < 0.25) else base_vox * float(trng.uniform(0.8, 1.2))
        if trng.random() < 0.3:
            style = ap.get("style", "bounce")
            alts = [s for s in ("bounce", "bigroom", "electro") if s != style and s != prev_style]
            if alts:
                ap["style"] = alts[int(trng.integers(0, len(alts)))]
        prev_style = ap.get("style", "bounce")

        s = (base_seed + 1 + i * 101) % (2 ** 31)
        segs.append(render_loop(ap, track_seconds, sr=sr, seed=s).astype(np.float64))

    if n_tracks == 1:
        return segs[0].astype(np.int16)

    lens = [s.shape[0] for s in segs]
    total_n = sum(lens) - xf * n_tracks                        # each junction (incl. wrap) overlaps xf
    fin = np.linspace(0.0, 1.0, xf)[:, None]
    fout = fin[::-1]
    out = np.zeros((total_n, 2))
    pos = 0
    for seg in segs:
        seg[:xf] *= fin
        seg[-xf:] *= fout
        L = seg.shape[0]
        end = pos + L
        if end <= total_n:
            out[pos:end] += seg
        else:                                                  # wrap the tail into the head
            first = total_n - pos
            out[pos:] += seg[:first]
            out[: end - total_n] += seg[first:]
        pos += L - xf

    peak = np.max(np.abs(out))
    if peak > 32767.0:
        out *= 32767.0 / peak
    return out.astype(np.int16)
