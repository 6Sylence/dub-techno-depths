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
    "aura", "aura farming", "aura farm", "aura farming phonk",
    "aura farming music", "aura farming edit", "aura farming mix",
    "aura farming song", "aura phonk", "aura phonk mix", "aura mix",
    "aura edit", "aura aesthetic", "how to farm aura", "max aura",
    "phonk", "drift phonk", "sigma phonk", "sigma", "brazilian phonk",
    "phonk edit", "gym phonk", "phonk 2026", "no copyright phonk",
]

AURA_LOCALES = {
    "es": "Aura farming phonk — drift phonk con actitud, 808 potentes y cowbell para el gimnasio, conducir de noche o gaming. Un mix nuevo cada día. 🔔",
    "pt": "Aura farming phonk — drift phonk com atitude, 808 pesado e cowbell pra academia, dirigir à noite ou gaming. Um mix novo todo dia. 🔔",
    "fr": "Aura farming phonk — drift phonk avec de l'attitude, 808 lourdes et cowbell pour la muscu, rouler la nuit ou le gaming. Un nouveau mix chaque jour. 🔔",
    "de": "Aura-Farming-Phonk — Drift Phonk mit Attitude, harte 808 und Cowbell fürs Gym, Nachtfahren oder Gaming. Jeden Tag ein neuer Mix. 🔔",
    "ru": "Aura farming phonk — дрифт-фонк с характером, тяжёлые 808 и каубелл для зала, ночной езды и гейминга. Новый микс каждый день. 🔔",
}


def _aura_metadata(preset: dict, date: _dt.date, target_seconds: float,
                   privacy: str) -> dict:
    words = preset["theme_words"]
    primary = words[date.timetuple().tm_yday % len(words)]
    emoji = preset.get("emoji", "🌌")
    dur = _hours_label(target_seconds)
    year = date.year

    title = f"{emoji} AURA FARMING Mix {year} — {primary} | Aura Phonk to Farm Max Aura"[:100].strip()

    description = f"""{emoji} AURA FARMING Phonk Mix {year} — {dur} of pure aura. Hard, cocky drift phonk with heavy distorted 808s, aggressive cowbell melodies and dark cinematic visuals — the viral aura farming sound to max your aura.

This is your aura farming playlist: put it on for the gym, night drives, gaming or locking in and farm aura all day. It loops seamlessly, so the aura never stops.

🌌 What is aura farming? Doing everything with main-character energy. This mix is the soundtrack — sigma aura phonk, built to keep your aura at 100.

🎧 About this channel
Every aura farming mix on {CHANNEL_NAME} is generated from scratch — 100% original music and visuals, no samples and no re-uploads, completely copyright-safe.

🔔 New aura farming mixes every day. Subscribe and turn on notifications.

#aura #aurafarming #aurafarm #phonk #driftphonk #sigma #{primary.lower().replace(' ', '')}"""
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


TRAP_TAGS = [
    "trap", "trap mafia", "mafia trap", "trap bass boosted", "bass boosted trap",
    "trap español", "trap latino", "trap 2026", "trap pesado", "trap oscuro",
    "trap beat", "bass boosted", "trap music", "trap mix", "trap mix 2026",
    "type beat", "hard trap", "trap instrumental", "no copyright trap",
]

TRAP_LOCALES = {
    "es": "Trap mafia bass boosted en español — 808 pesados, hi-hats duros y voz en español. Un mix nuevo cada día. 🔔",
    "en": "Spanish mafia bass-boosted trap — heavy 808s, hard hi-hats and Spanish vocals. New mix every day. 🔔",
    "pt": "Trap mafia bass boosted em espanhol — 808 pesados e vocais em espanhol. Um mix novo todo dia. 🔔",
}


def _trap_metadata(preset: dict, date: _dt.date, target_seconds: float,
                   privacy: str) -> dict:
    words = preset["theme_words"]
    primary = words[date.timetuple().tm_yday % len(words)]
    emoji = preset.get("emoji", "🖤")
    dur = _hours_label(target_seconds)
    year = date.year

    title = f"{emoji} TRAP MAFIA Bass Boosted {year} — {primary} | Trap Español Pesado"[:100].strip()

    description = f"""{emoji} Trap Mafia Bass Boosted {year} — {dur} de trap oscuro en español con voz propia. 808 que revientan, hi-hats duros y atmósfera de mafia cinematográfica.

Para el coche, el gimnasio o para ir a lo tuyo. Se reproduce en bucle sin cortes.

🎧 Sobre el canal
Cada mix de {CHANNEL_NAME} está creado desde cero — música y voz 100% originales, sin samples ni reuploads, totalmente libre de copyright.

🔔 Mixes nuevos cada día. Suscríbete y activa la campana.

#trap #trapmafia #bassboosted #trapespañol #{primary.lower().replace(' ', '')} #traplatino"""
    description = description.strip()
    aff = _affiliate_block()
    if aff:
        description = description.replace("🎧 Sobre el canal", aff + "\n\n🎧 Sobre el canal")

    tags, seen, final, budget = [w.lower() for w in words] + [preset["title"].lower()] + TRAP_TAGS, set(), [], 0
    for t in tags:
        if t in seen:
            continue
        seen.add(t)
        if budget + len(t) + 1 > 480:
            break
        final.append(t)
        budget += len(t) + 1

    loc = {lang: {"title": title, "description": desc} for lang, desc in TRAP_LOCALES.items()}
    return {
        "title": title, "description": description, "tags": final,
        "categoryId": "10", "privacyStatus": privacy,
        "thumbnail_title": preset["title"], "thumbnail_subtitle": f"{primary} • {dur}",
        "localizations": loc, "playlist": "Trap Mafia",
    }


def build_metadata(preset: dict, date: _dt.date, target_seconds: float,
                   privacy: str = "public") -> dict:
    if preset.get("genre") == "aura_phonk":
        return _aura_metadata(preset, date, target_seconds, privacy)
    if preset.get("genre") == "trap_mafia":
        return _trap_metadata(preset, date, target_seconds, privacy)
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
