"""Deterministic YouTube metadata for the bass-boosted EDM channel.

Reproducible per (preset, date); rotating headline keywords so a repeated preset
never publishes an identical title. Titles stay English for every locale (the
hook keywords — "bass boosted", "car music", "EDM" — pull clicks worldwide);
only the description is localized. The title mirrors the proven high-energy
formula of the top bass-boosted / car-music channels.
"""

from __future__ import annotations

import datetime as _dt
import os

CHANNEL_NAME = "Bass Boosted Nation"

LOCALES = {
    "es": "EDM con bass boosted, bounce y electro house para el coche, el gimnasio y la fiesta. Un mix nuevo cada día — suscríbete. 🔔",
    "pt": "EDM com bass boosted, bounce e electro house para o carro, a academia e a festa. Um mix novo todos os dias — inscreva-se. 🔔",
    "de": "Bass-Boosted EDM, Bounce und Electro House fürs Auto, Gym und die Party. Jeden Tag ein neuer Mix — abonnieren. 🔔",
    "fr": "EDM bass boosted, bounce et electro house pour la voiture, la salle et la fête. Un nouveau mix chaque jour — abonnez-vous. 🔔",
    "ru": "Bass boosted EDM, bounce и electro house для машины, зала и вечеринки. Новый микс каждый день — подписывайтесь. 🔔",
    "pt-BR": "EDM bass boosted, bounce e electro house pro carro, a academia e a festa. Mix novo todo dia — inscreva-se. 🔔",
}


def _localizations(title: str) -> dict:
    return {lang: {"title": title, "description": desc} for lang, desc in LOCALES.items()}


def _affiliate_block() -> str:
    return os.environ.get("AFFILIATE_BLOCK", "").strip()


GENERIC_TAGS = [
    "bass boosted", "bass boosted music", "bass boosted car music",
    "bass boosted songs", "car music", "car music mix", "bass boosted mix 2026",
    "car music mix 2026", "edm", "edm mix", "edm 2026", "melbourne bounce",
    "bounce", "electro house", "big room", "festival mix", "gym workout music",
    "workout music", "gym music", "gaming music", "party mix", "bass music",
    "no copyright edm", "bass boosted 2026",
]


def _hours_label(seconds: float) -> str:
    hours = seconds / 3600.0
    if hours >= 1:
        h = round(hours)
        return f"{h} Hour" + ("s" if h != 1 else "")
    return f"{round(seconds / 60)} Min"


AURA_TAGS = [
    "aura", "aura phonk", "phonk", "dreamy phonk", "aesthetic phonk",
    "drift phonk", "phonk mix", "phonk mix 2026", "aura phonk mix",
    "atmospheric phonk", "ambient phonk", "chill phonk", "night phonk",
    "aura aesthetic", "aura edit", "sigma phonk", "phonk music",
    "aura farming", "phonk 2026", "no copyright phonk",
]

AURA_LOCALES = {
    "es": "Aura phonk soñador y atmosférico — phonk estético para conducir de noche, estudiar o desconectar. Un mix nuevo cada día. 🔔",
    "pt": "Aura phonk sonhador e atmosférico — phonk estético para dirigir à noite, estudar ou relaxar. Um mix novo todo dia. 🔔",
    "fr": "Aura phonk onirique et atmosphérique — phonk esthétique pour rouler la nuit, étudier ou décompresser. Un nouveau mix chaque jour. 🔔",
    "de": "Verträumter, atmosphärischer Aura-Phonk — ästhetischer Phonk fürs Nachtfahren, Lernen oder Chillen. Jeden Tag ein neuer Mix. 🔔",
    "ru": "Мечтательный атмосферный aura phonk — эстетичный фонк для ночной езды и релакса. Новый микс каждый день. 🔔",
}


def _aura_metadata(preset: dict, date: _dt.date, target_seconds: float,
                   privacy: str) -> dict:
    words = preset["theme_words"]
    primary = words[date.timetuple().tm_yday % len(words)]
    emoji = preset.get("emoji", "🌌")
    dur = _hours_label(target_seconds)
    year = date.year

    title = f"{emoji} Aura Phonk Mix {year} — {primary} | Dreamy Aesthetic Phonk"[:100].strip()

    description = f"""{emoji} Aura Phonk Mix {year} — {dur} of dreamy, atmospheric phonk. Reverb-soaked 808s, soft cowbell melodies and glowing ethereal pads for that late-night 'aura' aesthetic.

Perfect for night drives, studying, gaming or locking in. It loops seamlessly.

🎧 About this channel
Every mix on {CHANNEL_NAME} is generated from scratch — 100% original music and visuals, no samples and no re-uploads, completely copyright-safe.

🔔 New mixes every day. Subscribe and turn on notifications.

#aura #phonk #auraphonk #dreamyphonk #{primary.lower().replace(' ', '')} #aesthetic"""
    description = description.strip()
    aff = _affiliate_block()
    if aff:
        description = description.replace("🎧 About this channel", aff + "\n\n🎧 About this channel")

    tags, seen, final, budget = [w.lower() for w in words] + [preset["title"].lower()] + AURA_TAGS, set(), [], 0
    for t in tags:
        if t in seen:
            continue
        seen.add(t)
        if budget + len(t) + 1 > 480:
            break
        final.append(t)
        budget += len(t) + 1

    loc = {lang: {"title": title, "description": desc} for lang, desc in AURA_LOCALES.items()}
    return {
        "title": title, "description": description, "tags": final,
        "categoryId": "10", "privacyStatus": privacy,
        "thumbnail_title": preset["title"], "thumbnail_subtitle": f"{primary} • {dur}",
        "localizations": loc, "playlist": "Aura Phonk",
    }


def build_metadata(preset: dict, date: _dt.date, target_seconds: float,
                   privacy: str = "public") -> dict:
    if preset.get("genre") == "aura_phonk":
        return _aura_metadata(preset, date, target_seconds, privacy)
    words = preset["theme_words"]
    primary = words[date.timetuple().tm_yday % len(words)]
    emoji = preset.get("emoji", "")
    dur = _hours_label(target_seconds)
    year = date.year

    # Front-load "Bass Boosted" (the niche's #1 search term) in every title, then
    # the rotating use-case keyword ("Gym Workout", "Car Music", "Gaming"…) and a
    # keyword cluster that mirrors the top car-music channels. Rotation keeps a
    # repeated preset from ever publishing the same title.
    title = f"🔊 Bass Boosted {preset['title']} Mix {year} {emoji} {primary} | Car Music, EDM & Bounce"
    if len(title) > 100:
        title = f"🔊 Bass Boosted {preset['title']} Mix {year} {emoji} {primary} | EDM & Bounce"
    title = title[:100].strip()

    description = f"""🔊 {preset['title']} Mix {year} {emoji} — {dur} of bass-boosted EDM, Melbourne bounce and electro house. Huge kicks, a bouncing donk bass and hard-hitting drops made to turn up in the car, the gym or the party.

Crank it up 🔥 It loops seamlessly, so the energy never drops.

🚗 Best with
• A subwoofer or good headphones — this is built for bass.
• Volume UP. It's a bass-boosted mix.
• On repeat — hours of drops.

🎧 About this channel
Every mix on {CHANNEL_NAME} is generated from scratch — 100% original, procedurally produced music and visuals. No samples, no re-uploads, no filler — every track is unique to this channel and completely copyright-safe.

🔔 New bass-boosted mixes every single day. Subscribe and turn on notifications.

#bassboosted #carmusic #edm #{primary.lower().replace(' ', '')} #bounce #electrohouse
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

    title = f"🔊 Bass Boosted {preset['title']} {emoji} Car Music EDM #shorts"
    title = title[:100].strip()

    description = f"""🔊 {preset['title']} {emoji} — a 60-second bass-boosted EDM loop to {primary.lower()}.

🎧 The full-length mix is on the channel — perfect for the car, the gym and the party. Subscribe for a new mix every day 🔔

Every track on {CHANNEL_NAME} is 100% original and procedurally produced — unique to this channel.

#shorts #bassboosted #carmusic #edm #{primary.lower().replace(' ', '')} #bounce
"""

    tags = ["shorts", "bass boosted", "car music", "edm", preset["title"].lower(),
            primary.lower(), "bounce", "electro house", "edm mix"]
    return {
        "title": title,
        "description": description.strip(),
        "tags": tags,
        "categoryId": "10",
        "privacyStatus": privacy,
    }
