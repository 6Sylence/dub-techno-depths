"""AI music generation via the ElevenLabs Music API (Eleven Music v2).

Eleven Music is trained on licensed data and cleared for broad commercial use on
paid plans, and it exposes an official HTTP API — so it can drive the daily
pipeline (unlike Suno, which has no official API). We generate a few tracks per
video from EDM / bass-boosted / car-music prompts and let the pipeline stitch
them into the mix.

Cost note: every call spends ElevenLabs credits, so the number and length of
tracks per video is configurable (AI_TRACKS / AI_TRACK_SECONDS). The renderer
falls back to the procedural engine if the API is unavailable, so a missing key,
spent credits or an API error never breaks the daily upload.

Requires the ELEVENLABS_API_KEY environment variable (a GitHub repo secret).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.elevenlabs.io/v1/music"
SUB_URL = "https://api.elevenlabs.io/v1/user/subscription"
# Measured empirically: Eleven Music v2 costs ~824 credits per minute
# (412 credits / 30 s). Used to keep monthly spend inside the plan.
CREDITS_PER_SECOND = 14.0
CREDIT_RESERVE = 3000          # always leave this many credits unspent


class AIMusicError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())


def remaining_credits() -> int | None:
    """Credits left this billing period, or None if it can't be read."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        return None
    try:
        req = urllib.request.Request(
            SUB_URL, headers={"xi-api-key": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode())
        return int(d["character_limit"]) - int(d["character_count"])
    except Exception:                                          # never fail on the check
        return None


def build_prompt(preset: dict, primary: str, variant: str = "") -> str:
    """Craft a text prompt in the bass-boosted car-music EDM lane, themed by the
    preset and varied per track so no two generations are alike."""
    bpm = int(preset.get("audio", {}).get("bpm", 128))
    title = preset.get("title", "EDM")
    mood = (primary or "energy").lower()
    extra = f" {variant}." if variant else ""
    return (
        f"Bass-boosted EDM / Melbourne bounce / electro house in the style of a "
        f"'car music' bass-boosted mix. Huge punchy kick, deep boosted sub bass, "
        f"a bouncing detuned 'donk' bassline, bright detuned supersaw drop lead, "
        f"a catchy repeating topline hook, hard festival drop, loud commercial "
        f"master. "
        # Original anthem-style vocal hooks that FEEL familiar in the genre — an
        # earworm crowd chant using only generic party shout phrases ("let's go",
        # "hands up", "hey!", "oh-oh-oh", "here we go", "jump") and catchy 'na-na'/
        # 'oh-oh' vowel chants that stick on first listen.
        f"Add an infectious, sing-along anthem vocal hook: catchy gang/crowd "
        f"chants and 'oh-oh-oh' / 'na-na-na' vowel hooks using only generic party "
        f"shout phrases (let's go, hands up, hey, jump, here we go), stadium-anthem "
        f"energy, instantly memorable. "
        # Legal + Content-ID safety: 100% original, never a real song.
        f"The vocal hook and melody must be 100% original and must NOT imitate, "
        f"quote, interpolate or resemble any existing song, artist, lyric or "
        f"melody. "
        f"{title} vibe, {mood}. Around {bpm} BPM.{extra}"
    )


def generate_track(prompt: str, length_ms: int, out_path: str | Path,
                   output_format: str = "mp3_44100_128", timeout: int = 300) -> Path:
    """Generate one track and write the audio bytes to ``out_path``.

    Raises AIMusicError on any failure (so the caller can fall back)."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise AIMusicError("ELEVENLABS_API_KEY not set")

    length_ms = int(max(3000, min(int(length_ms), 600000)))     # API bounds: 3s..10min
    url = f"{API_URL}?output_format={output_format}"
    body = json.dumps({
        "prompt": prompt,
        "music_length_ms": length_ms,
        "model_id": "music_v2",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read()
    except urllib.error.HTTPError as exc:                       # surface the API's message
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise AIMusicError(f"ElevenLabs HTTP {exc.code}: {detail}") from exc
    except Exception as exc:                                    # network / timeout / etc.
        raise AIMusicError(f"ElevenLabs request failed: {exc}") from exc

    if "json" in ctype or "application/json" in ctype:          # not raw audio
        raise AIMusicError(f"ElevenLabs returned JSON, not audio: "
                           f"{data.decode('utf-8', 'replace')[:400]}")
    if not data or len(data) < 2000:                            # too small to be audio
        raise AIMusicError(f"ElevenLabs returned {len(data)} bytes (not audio)")
    out = Path(out_path)
    out.write_bytes(data)
    return out


def generate_tracks(preset: dict, primary: str, n_tracks: int, track_seconds: float,
                     out_dir: str | Path, seed: int = 0) -> list[Path]:
    """Generate ``n_tracks`` varied tracks; returns the list of written files.

    Any track that fails is skipped; the caller decides what to do with a short
    (or empty) list."""
    variants = [
        "darker and heavier", "brighter and euphoric", "harder and more aggressive",
        "bouncier and more playful", "bigger festival drop", "more vocal-driven",
        "deeper rolling bass", "peak-time and relentless",
    ]
    out_dir = Path(out_dir)
    files: list[Path] = []

    # Credit guard: keep spend inside the plan. If the remaining balance can't
    # cover n_tracks x track_seconds (plus a reserve), shrink the length — and
    # if needed the track count — so late-month runs still produce music instead
    # of failing. Falls through untouched if the balance can't be read.
    rem = remaining_credits()
    if rem is not None:
        budget = max(0, rem - CREDIT_RESERVE)
        affordable_s = budget / CREDITS_PER_SECOND
        want_s = n_tracks * track_seconds
        if affordable_s < want_s:
            if affordable_s < 20:                              # basically nothing left
                print(f"    [credit guard] only ~{int(rem)} credits left; "
                      f"skipping AI music this run")
                return []
            # keep the track count if we can still give each >=45s, else drop count
            per = affordable_s / n_tracks
            if per < 45:
                n_tracks = max(1, int(affordable_s // 60))
                per = affordable_s / n_tracks
            track_seconds = max(30.0, per)
            print(f"    [credit guard] ~{int(rem)} credits left -> "
                  f"{n_tracks} x {track_seconds:.0f}s to stay in budget")

    length_ms = int(track_seconds * 1000)
    for i in range(n_tracks):
        variant = variants[(seed + i) % len(variants)]
        prompt = build_prompt(preset, primary, variant)
        dest = out_dir / f"ai_track_{i:02d}.mp3"
        try:
            files.append(generate_track(prompt, length_ms, dest))
            print(f"    AI track {i + 1}/{n_tracks}: {variant}")
        except AIMusicError as exc:
            print(f"    AI track {i + 1}/{n_tracks} failed: {exc}")
    return files
