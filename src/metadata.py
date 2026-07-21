"""Deterministic YouTube metadata for the techno channel.

Reproducible per (preset, date); rotating headline keywords so a repeated preset
never publishes an identical title. Titles stay English for every locale (the
hook keywords — "melodic techno", "deep", "mix" — are what pull clicks
worldwide); only the description is localized.
"""

from __future__ import annotations

import datetime as _dt
import os

CHANNEL_NAME = "Deep Techno Depths"

LOCALES = {
    "es": "Techno melódico, deep y dub para concentrarte, trabajar y perderte en la noche. Un mix nuevo cada día — suscríbete. 🔔",
    "pt": "Techno melódico, deep e dub para focar, trabalhar e mergulhar na noite. Um mix novo todos os dias — inscreva-se. 🔔",
    "de": "Melodic, Deep und Dub Techno zum Fokussieren, Arbeiten und Abtauchen. Jeden Tag ein neuer Mix — abonnieren. 🔔",
    "fr": "Techno mélodique, deep et dub pour se concentrer, travailler et plonger dans la nuit. Un nouveau mix chaque jour — abonnez-vous. 🔔",
    "ru": "Мелодик, дип и даб-техно для концентрации, работы и погружения в ночь. Новый микс каждый день — подписывайтесь. 🔔",
    "ja": "集中・作業・夜の没入のためのメロディック／ディープ／ダブ・テクノ。毎日新しいミックスを公開 — チャンネル登録お願いします。🔔",
}


def _localizations(title: str) -> dict:
    return {lang: {"title": title, "description": desc} for lang, desc in LOCALES.items()}


def _affiliate_block() -> str:
    return os.environ.get("AFFILIATE_BLOCK", "").strip()


GENERIC_TAGS = [
    "techno", "melodic techno", "deep techno", "dub techno", "hypnotic techno",
    "techno mix", "melodic techno mix", "deep techno mix", "afterlife",
    "techno music", "dark techno", "driving techno", "focus music",
    "music to work to", "no copyright techno", "background music",
]


def _hours_label(seconds: float) -> str:
    hours = seconds / 3600.0
    if hours >= 1:
        h = round(hours)
        return f"{h} Hour" + ("s" if h != 1 else "")
    return f"{round(seconds / 60)} Min"


def build_metadata(preset: dict, date: _dt.date, target_seconds: float,
                   privacy: str = "public") -> dict:
    words = preset["theme_words"]
    primary = words[date.timetuple().tm_yday % len(words)]
    emoji = preset.get("emoji", "")
    dur = _hours_label(target_seconds)

    title = f"{preset['title']} Mix {emoji} {primary} | {dur}"
    title = title[:100].strip()

    description = f"""{preset['title']} Mix {emoji} — {dur} of {preset['title'].lower()} for {primary.lower()}. Rolling sidechained bass, detuned analog chords swept through a resonant filter and the deep dub-delay echo that keeps it hypnotic.

Press play and let it roll while you work, focus, drive or lose yourself in the late-night hours. It loops seamlessly, so the groove never breaks.

🎚️ Best with
• Headphones or a decent speaker — the sub bass and stereo width carry the vibe.
• A steady volume, as a hypnotic background groove.
• On repeat — it's built to roll for hours.

🎧 About this channel
Every mix on {CHANNEL_NAME} is generated from scratch — 100% original, procedurally produced tracks and visuals. No samples, no re-uploads, no filler — every track is unique to this channel and completely copyright-safe.

🔔 New techno mixes every single day. Subscribe and turn on notifications.

#techno #melodictechno #deeptechno #{primary.lower().replace(' ', '')} #technomix #dubtechno
"""

    tags = [w.lower() for w in words]
    tags.append(preset["title"].lower())
    tags.append(preset["id"].replace("_", " "))
    tags.extend(GENERIC_TAGS)
    seen, final, budget = set(), [], 0
    for t in tags:
        if t in seen:
            continue
        seen.add(t)
        if budget + len(t) + 1 > 480:
            break
        final.append(t)
        budget += len(t) + 1

    description = description.strip()
    aff = _affiliate_block()
    if aff:
        marker = "🎧 About this channel"
        description = description.replace(marker, aff + "\n\n" + marker)

    return {
        "title": title,
        "description": description,
        "tags": final,
        "categoryId": "10",
        "privacyStatus": privacy,
        "thumbnail_title": preset["title"],
        "thumbnail_subtitle": f"{primary} • {dur}",
        "localizations": _localizations(title),
        "playlist": preset["title"],
    }


def build_shorts_metadata(preset: dict, date: _dt.date,
                          privacy: str = "public") -> dict:
    words = preset["theme_words"]
    primary = words[date.timetuple().tm_yday % len(words)]
    emoji = preset.get("emoji", "")

    title = f"{preset['title']} {emoji} 60s techno loop #shorts"
    title = title[:100].strip()

    description = f"""{preset['title']} {emoji} — a 60-second {preset['title'].lower()} loop for {primary.lower()}.

🎧 The full-length mix is on the channel — perfect for focus, work and late nights. Subscribe for a new mix every day 🔔

Every track on {CHANNEL_NAME} is 100% original and procedurally produced — unique to this channel.

#shorts #techno #melodictechno #deeptechno #{primary.lower().replace(' ', '')} #technomix
"""

    tags = ["shorts", "techno", "melodic techno", "deep techno", preset["title"].lower(),
            primary.lower(), "techno mix", "dub techno", "techno loop"]
    return {
        "title": title,
        "description": description.strip(),
        "tags": tags,
        "categoryId": "10",
        "privacyStatus": privacy,
    }
