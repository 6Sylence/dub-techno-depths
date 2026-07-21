#!/usr/bin/env python3
"""One-shot channel branding: banner, description, keywords, country, trailer.

Run via the "Channel branding" workflow (uses the repo's YouTube secrets), or
locally with YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN exported.
Idempotent — safe to re-run after tweaking the constants below.

The avatar/profile picture is NOT settable through the YouTube Data API; that
one file is generated separately and uploaded by hand in YouTube Studio.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from src import video  # noqa: E402
from src.utils import load_presets  # noqa: E402
from src.upload_youtube import _service  # noqa: E402

CHANNEL_NAME = "Lofi Study Lounge"
TAGLINE = "Lofi hip hop beats to study, relax & sleep to — new mix every day"
SIGNATURE_PRESET = "lofi_study"     # warm amber banner art
TRAILER_VIDEO_ID = ""               # set to a video id once one is published
COUNTRY = "US"
DESCRIPTION = """Lofi hip hop beats to study, relax and sleep to — a new mix every single day.

Warm Rhodes chords, a soft boom-bap groove and cozy vinyl crackle: made to sit gently in the background while you study, work, read or drift off. Press play and stay in the zone.

Every mix on this channel is 100% original, procedurally produced music and visuals — unique to Lofi Study Lounge and completely copyright-safe. No samples, no re-uploads, no filler.

📅 Upload schedule (UTC)
• Every morning — a 1-hour mix to start the day
• Every afternoon — a 2-hour study session mix

🔔 Subscribe and turn on notifications — tomorrow's mix is already on its way."""
KEYWORDS = ('"lofi hip hop" "lofi beats" "study music" "chillhop" '
            '"beats to relax to" "beats to study to" "lofi radio" relax sleep focus')

BANNER_W, BANNER_H = 2560, 1440     # YouTube renders a 1546x423 safe strip centered


def build_banner(path: Path) -> Path:
    preset = next(p for p in load_presets(ROOT / "config" / "presets.yaml")
                  if p["id"] == SIGNATURE_PRESET)
    tmp = path.parent
    video.build_background(preset, tmp / "_b.png", width=BANNER_W, height=BANNER_H, seed=11)
    video.build_mist(preset, tmp / "_m.png", width=BANNER_W, height=BANNER_H, seed=11)
    video.build_effect_layer(preset, tmp / "_f.png", width=BANNER_W, height=BANNER_H, seed=11)

    img = Image.open(tmp / "_b.png").convert("RGBA").crop((0, 0, BANNER_W, BANNER_H))
    mist = Image.open(tmp / "_m.png").crop((400, 0, 400 + BANNER_W, BANNER_H))
    fx = Image.open(tmp / "_f.png").crop((0, 0, BANNER_W, BANNER_H))
    img = Image.alpha_composite(Image.alpha_composite(img, mist), fx)

    # Soft dark plate behind the text keeps it legible on any crop.
    plate = Image.new("RGBA", (BANNER_W, BANNER_H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.rectangle([0, BANNER_H // 2 - 190, BANNER_W, BANNER_H // 2 + 190],
                 fill=(0, 0, 0, 90))
    img = Image.alpha_composite(img, plate).convert("RGB")

    draw = ImageDraw.Draw(img)
    title_font = video._load_font(150)
    sub_font = video._load_font(56)

    def centered(text, font, y, fill):
        bb = draw.textbbox((0, 0), text, font=font)
        x = (BANNER_W - (bb[2] - bb[0])) // 2
        draw.text((x + 4, y + 4), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=fill)

    # Keep all text inside the centered 1546x423 mobile-safe area.
    centered(CHANNEL_NAME, title_font, BANNER_H // 2 - 130, (248, 248, 248))
    centered(TAGLINE, sub_font, BANNER_H // 2 + 55, (205, 215, 228))

    img.save(path, "JPEG", quality=92)
    for f in ("_b.png", "_m.png", "_f.png"):
        (tmp / f).unlink(missing_ok=True)
    return path


def main() -> int:
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    banner = build_banner(out / "banner.jpg")
    print(f"banner rendered: {banner}")

    youtube = _service()
    me = youtube.channels().list(part="brandingSettings", mine=True).execute()
    channel = me["items"][0]
    ch_id = channel["id"]
    branding = channel.get("brandingSettings", {})
    print(f"channel: {ch_id}")

    from googleapiclient.http import MediaFileUpload
    resp = youtube.channelBanners().insert(
        media_body=MediaFileUpload(str(banner), mimetype="image/jpeg")).execute()
    banner_url = resp["url"]
    print("banner uploaded")

    ch = branding.setdefault("channel", {})
    ch["description"] = DESCRIPTION
    ch["keywords"] = KEYWORDS
    ch["country"] = COUNTRY
    ch["defaultLanguage"] = "en"
    if TRAILER_VIDEO_ID:
        ch["unsubscribedTrailer"] = TRAILER_VIDEO_ID
    branding.setdefault("image", {})["bannerExternalUrl"] = banner_url

    youtube.channels().update(
        part="brandingSettings",
        body={"id": ch_id, "brandingSettings": branding},
    ).execute()
    print("channel branding updated: description, keywords, country, trailer, banner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
