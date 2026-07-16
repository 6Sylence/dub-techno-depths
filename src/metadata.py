"""Deterministic YouTube metadata for Dub Techno Depths.

Same contract as the ambient channel's module: fully reproducible for a given
(preset, date), rotating headline keywords so repeated presets never publish
identical titles.
"""

from __future__ import annotations

import datetime as _dt
import os

CHANNEL_NAME = "Dub Techno Depths"

# Localized title phrase + short description per language (YouTube shows these
# to viewers browsing in that language; defaultLanguage="en" is set on upload).
LOCALES = {
    "es": ("mix para concentrarse y trabajar",
           "Dub techno hipnótico para concentrarse, programar y estudiar. "
           "Un mix nuevo cada día — suscríbete. 🔔"),
    "pt": ("mix para foco e trabalho",
           "Dub techno hipnótico para foco, programação e estudo. "
           "Um mix novo todos os dias — inscreva-se. 🔔"),
    "de": ("Mix zum Konzentrieren und Arbeiten",
           "Hypnotischer Dub Techno zum Konzentrieren, Programmieren und Lernen. "
           "Jeden Tag ein neuer Mix — abonnieren. 🔔"),
    "fr": ("mix pour la concentration et le travail",
           "Dub techno hypnotique pour la concentration, le code et l'étude. "
           "Un nouveau mix chaque jour — abonnez-vous. 🔔"),
    "ja": ("集中・作業用ミックス",
           "集中、コーディング、勉強のためのヒプノティックなダブテクノ。毎日新しいミックスを公開 — チャンネル登録お願いします。🔔"),
    "hi": ("फोकस और काम के लिए मिक्स",
           "फोकस, कोडिंग और पढ़ाई के लिए सम्मोहक डब टेक्नो। हर दिन नया मिक्स — सब्सक्राइब करें। 🔔"),
}


def _localizations(preset: dict, dur: str) -> dict:
    emoji = preset.get("emoji", "")
    out = {}
    for lang, (phrase, desc) in LOCALES.items():
        title = f"{preset['title']} {emoji} {phrase} | {dur}"
        out[lang] = {"title": title[:100].strip(), "description": desc}
    return out


def _affiliate_block() -> str:
    return os.environ.get("AFFILIATE_BLOCK", "").strip()

GENERIC_TAGS = [
    "dub techno", "techno mix", "deep techno", "minimal techno",
    "focus music", "study music", "coding music", "work music",
    "electronic music", "techno 2026", "deep house mix", "productivity music",
    "no copyright techno", "background music",
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

    title = f"{preset['title']} Mix {emoji} {primary} | Hypnotic Deep Beats | {dur}"
    title = title[:100].strip()

    description = f"""{preset['title']} {emoji} — {dur} of deep, hypnotic dub techno for {primary.lower()}, coding, studying and late-night work sessions.

Endless dubbed-out chords, a warm rolling sub and that four-to-the-floor pulse — engineered to hold your focus without ever demanding your attention. Press play, sink in, get things done.

▶ Best experienced
• At a moderate volume, as a background pulse.
• With headphones for the full stereo delay field.
• On repeat — the mix loops seamlessly.

🎛️ About this channel
Every mix on {CHANNEL_NAME} is generated from scratch — 100% original, procedurally synthesized music and visuals. Nothing is sampled or borrowed, so every track is unique to this channel and completely copyright-safe.

🔔 New mixes daily. Subscribe and turn on notifications.

#dubtechno #techno #{primary.lower().replace(' ', '')} #focusmusic #deeptechno #codingmusic
"""

    tags = []
    for w in words:
        tags.append(w.lower())
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
        marker = "🎛️ About this channel"
        description = description.replace(marker, aff + "\n\n" + marker)

    return {
        "title": title,
        "description": description,
        "tags": final,
        "categoryId": "10",
        "privacyStatus": privacy,
        "thumbnail_title": preset["title"],
        "thumbnail_subtitle": f"{primary} • {dur}",
        "localizations": _localizations(preset, dur),
        "playlist": preset["title"] + " Mixes",
    }


def build_shorts_metadata(preset: dict, date: _dt.date,
                          privacy: str = "public") -> dict:
    words = preset["theme_words"]
    primary = words[date.timetuple().tm_yday % len(words)]
    emoji = preset.get("emoji", "")

    title = f"{preset['title']} {emoji} 60s Deep Loop #shorts"
    title = title[:100].strip()

    description = f"""{preset['title']} {emoji} — a 60-second hypnotic loop. {primary} mode: ON.

🎛️ The full-length mix is on the channel — perfect for deep work, coding and study. Subscribe for a new mix every day 🔔

Every beat on {CHANNEL_NAME} is 100% original, procedurally generated techno — unique to this channel.

#shorts #dubtechno #techno #{primary.lower().replace(' ', '')} #focus #deeptechno
"""

    tags = ["shorts", "dub techno", "techno shorts", "deep techno",
            preset["title"].lower(), primary.lower(), "techno loop", "focus music"]
    return {
        "title": title,
        "description": description.strip(),
        "tags": tags,
        "categoryId": "10",
        "privacyStatus": privacy,
    }
