"""Cloned-voice narration via the ElevenLabs Text-to-Speech API.

Used by the "trap mafia" lane: a short Spanish spoken hook in the channel
owner's cloned voice, mixed over the AI-generated trap beat as a recurring
vocal tag (like the vocal drops the big bass-boosted channels use).

The voice is resolved by NAME at runtime (env VOICE_NAME, e.g.
"ALVARO ROMERO MIÑANO") so no id has to be hard-coded. Everything here is
best-effort: if the key, the voice or the API is unavailable the caller just
publishes the instrumental beat, so an upload never breaks over the voice.

Requires ELEVENLABS_API_KEY (the same secret the music engine uses).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

VOICES_URL = "https://api.elevenlabs.io/v1/voices"
TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Multilingual model handles Spanish and cloned voices.
TTS_MODEL = "eleven_multilingual_v2"


class AIVoiceError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())


def resolve_voice_id(name: str) -> str | None:
    """Look up a voice id by (case-insensitive) name. Returns None if the key is
    missing, the request fails, or no voice matches."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key or not name:
        return None
    try:
        req = urllib.request.Request(
            VOICES_URL, headers={"xi-api-key": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None
    want = name.strip().lower()
    voices = data.get("voices", []) if isinstance(data, dict) else []
    for v in voices:                                           # exact name first
        if str(v.get("name", "")).strip().lower() == want:
            return v.get("voice_id")
    for v in voices:                                           # then a loose contains
        if want in str(v.get("name", "")).strip().lower():
            return v.get("voice_id")
    return None


def tts(text: str, voice_id: str, out_path: str | Path,
        model: str = TTS_MODEL, timeout: int = 120) -> Path:
    """Synthesize ``text`` in the given voice to an mp3. Raises AIVoiceError."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise AIVoiceError("ELEVENLABS_API_KEY not set")
    if not voice_id:
        raise AIVoiceError("no voice_id")
    url = TTS_URL.format(voice_id=voice_id) + "?output_format=mp3_44100_128"
    body = json.dumps({
        "text": text,
        "model_id": model,
        # A touch of stability with expression, and a bit of style for attitude.
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.85,
                            "style": 0.35, "use_speaker_boost": True},
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
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise AIVoiceError(f"ElevenLabs TTS HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise AIVoiceError(f"ElevenLabs TTS request failed: {exc}") from exc
    if "json" in ctype:
        raise AIVoiceError(f"TTS returned JSON, not audio: "
                           f"{data.decode('utf-8', 'replace')[:300]}")
    if not data or len(data) < 1500:
        raise AIVoiceError(f"TTS returned {len(data)} bytes (not audio)")
    out = Path(out_path)
    out.write_bytes(data)
    return out


# Original Spanish spoken lyrics for the trap-mafia lane, written as a small song
# arrangement: an INTRO tag (brand), a punchy HOOK (the repeated "chorus" line)
# and a BAR (a verse line). One set is picked per upload by seed; the three lines
# are placed at spaced points over the beat so it feels arranged, not looped.
# Clean / monetization-safe: attitude about bass, cars, the night and the grind —
# no profanity, no explicit violence or drugs.
_LYRIC_SETS = [
    {"intro": "Bass Boosted Nation. Sube el volumen, esto es la mafia del bajo.",
     "hook":  "El ochocientos ocho manda, en la noche mando yo.",
     "bar":   "Luces de neón, motor en marcha; la ciudad es mía esta noche."},
    {"intro": "Bass Boosted Nation. Bajos que rompen el asfalto.",
     "hook":  "A todo gas, sin frenos, el bajo no para.",
     "bar":   "Vengo del barrio y no me rindo; esto es solo el principio."},
    {"intro": "Bass Boosted Nation. Aura, motor y bajo.",
     "hook":  "La calle es mía, nadie me para.",
     "bar":   "Trabajo en silencio, hablo con hechos; el ritmo es mi respeto."},
    {"intro": "Bass Boosted Nation. Sientes el bajo en el pecho.",
     "hook":  "De noche brillo más, la ciudad es mi trono.",
     "bar":   "Poco a poco, paso a paso, construyendo mi imperio."},
    {"intro": "Bass Boosted Nation. Enciende el motor, sube el volumen.",
     "hook":  "El trap retumba fuerte, la mafia del bajo despierta.",
     "bar":   "Neón y asfalto mojado; esta noche todo es nuestro."},
    {"intro": "Bass Boosted Nation. Esto suena a calle, esto suena a mafia.",
     "hook":  "Bajo pesado, cabeza fría, nunca me paran.",
     "bar":   "Del cero a la cima, sin atajos; el bajo es mi firma."},
]


def lyric_lines(seed: int = 0) -> list[str]:
    s = _LYRIC_SETS[seed % len(_LYRIC_SETS)]
    return [s["intro"], s["hook"], s["bar"]]


def generate_lines(out_dir: str | Path, seed: int = 0,
                   voice_name: str | None = None) -> list[Path] | None:
    """Resolve the cloned voice by name and synthesize the three arranged lines
    (intro / hook / bar). Returns the list of mp3 clips in order, or None if the
    voice/TTS is unavailable (caller then just uses the instrumental beat)."""
    name = voice_name or os.environ.get("VOICE_NAME", "").strip()
    if not available() or not name:
        return None
    vid = resolve_voice_id(name)
    if not vid:
        print(f"    [voice] voice '{name}' not found on this ElevenLabs account; "
              f"publishing the instrumental beat")
        return None
    clips: list[Path] = []
    for i, text in enumerate(lyric_lines(seed)):
        dest = Path(out_dir) / f"voice_{i}.mp3"
        try:
            tts(text, vid, dest)
            clips.append(dest)
        except AIVoiceError as exc:
            print(f"    [voice] TTS line {i} failed ({exc})")
    if not clips:
        print("    [voice] no voice lines synthesized; publishing the instrumental beat")
        return None
    print(f"    [voice] cloned-voice arrangement ready ({name}): {len(clips)} line(s)")
    return clips
