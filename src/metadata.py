"""Deterministic YouTube metadata for the lofi channel.

Reproducible per (preset, date); rotating headline keywords so a repeated preset
never publishes an identical title. Titles stay English for every locale (the
hook keywords — "study", "relax", "sleep" — are what pull clicks worldwide);
only the description is localized.
"""

from __future__ import annotations

import datetime as _dt
import os

CHANNEL_NAME = "Lofi Study Lounge"

LOCALES = {
    "es": "Beats lofi para estudiar, relajarte y dormir. Un mix nuevo cada día — suscríbete. 🔔",
    "pt": "Beats lofi para estudar, relaxar e dormir. Um mix novo todos os dias — inscreva-se. 🔔",
    "de": "Lofi-Beats zum Lernen, Entspannen und Einschlafen. Jeden Tag ein neuer Mix — abonnieren. 🔔",
    "fr": "Beats lofi pour étudier, se détendre et dormir. Un nouveau mix chaque jour — abonnez-vous. 🔔",
    "ja": "勉強・リラックス・睡眠のためのローファイビート。毎日新しいミックスを公開 — チャンネル登録お願いします。🔔",
    "hi": "पढ़ाई, आराम और नींद के लिए लोफ़ाई बीट्स। हर दिन नया मिक्स — सब्सक्राइब करें। 🔔",
}


def _localizations(title: str) -> dict:
    return {lang: {"title": title, "description": desc} for lang, desc in LOCALES.items()}


def _affiliate_block() -> str:
    return os.environ.get("AFFILIATE_BLOCK", "").strip()


GENERIC_TAGS = [
    "lofi hip hop", "lofi", "lofi beats", "lofi hip hop radio", "chillhop",
    "beats to study to", "beats to relax to", "study music", "study beats",
    "chill beats", "lofi radio", "relaxing music", "focus music",
    "no copyright lofi", "background music",
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

    title = f"{preset['title']} {emoji} lofi beats to {primary.lower()} to | {dur}"
    title = title[:100].strip()

    description = f"""{preset['title']} {emoji} — {dur} of lofi hip hop beats to {primary.lower()} to. Warm Rhodes chords, a soft boom-bap groove and cozy vinyl crackle to keep you in the zone.

Press play and let it roll in the background while you study, work, read or wind down. It loops seamlessly, so it never breaks the mood.

☕ Best with
• A comfortable volume, as a background groove.
• Headphones for the full warmth and vinyl texture.
• On repeat — it's built to loop for hours.

🎧 About this channel
Every mix on {CHANNEL_NAME} is generated from scratch — 100% original, procedurally produced beats and visuals. No samples, no re-uploads, no filler — every track is unique to this channel and completely copyright-safe.

🔔 New lofi mixes every single day. Subscribe and turn on notifications.

#lofi #lofihiphop #{primary.lower().replace(' ', '')} #studybeats #chillhop #lofiradio
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

    title = f"{preset['title']} {emoji} 60s lofi loop #shorts"
    title = title[:100].strip()

    description = f"""{preset['title']} {emoji} — a cozy 60-second lofi loop to {primary.lower()} to.

🎧 The full-length mix is on the channel — perfect for study, work and sleep. Subscribe for a new mix every day 🔔

Every beat on {CHANNEL_NAME} is 100% original and procedurally produced — unique to this channel.

#shorts #lofi #lofihiphop #{primary.lower().replace(' ', '')} #studybeats #chillhop
"""

    tags = ["shorts", "lofi", "lofi hip hop", "lofi beats", preset["title"].lower(),
            primary.lower(), "study beats", "chillhop", "lofi loop"]
    return {
        "title": title,
        "description": description.strip(),
        "tags": tags,
        "categoryId": "10",
        "privacyStatus": privacy,
    }
