#!/usr/bin/env python3
"""Refresh the thumbnails of already-published videos to the new look.

The video footage of a published upload can't be changed, but its thumbnail can.
This regenerates a car-photo thumbnail (rotated from assets/car_backgrounds/)
with the big preset title and the cyan brand mark, then sets it on each PUBLIC
video via the Data API. Safe and reversible — it only touches thumbnails.

Env:
  YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN  (as usual)
  LIMIT     max videos to touch this run (default: all)
  DRY_RUN   "true" → render + report but don't upload (default: false)
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import video  # noqa: E402
from src.upload_youtube import _service  # noqa: E402

PRESETS = {p["title"].lower(): p for p in
           yaml.safe_load(open(ROOT / "config" / "presets.yaml"))["presets"]}


def _match_preset(title: str):
    """Map a video title to its preset. Titles read "🔊 {Preset} Mix 2026 …" so
    we match only the part before "Mix" — the theme word after it (e.g. a
    "Bounce"/"Festival" tag) can collide with another preset's name otherwise."""
    head = re.split(r"\bmix\b", title, 1, re.I)[0].lower()
    for name, preset in PRESETS.items():
        if name in head:
            return preset
    return None


def _fit_font(d, txt, target_w, start):
    """Largest font whose text width fits target_w."""
    size = start
    while size > 20:
        f = video._load_font(size)
        b = d.textbbox((0, 0), txt, font=f, stroke_width=max(2, size // 22))
        if b[2] - b[0] <= target_w:
            return f
        size -= 4
    return video._load_font(size)


def _car_thumb(title: str, subtitle: str, img_path: Path, tw=1280, th=720) -> Image.Image:
    im = Image.open(img_path).convert("RGB")
    scale = max(tw / im.width, th / im.height)
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                   Image.LANCZOS)
    l, t = (im.width - tw) // 2, (im.height - th) // 2
    im = im.crop((l, t, l + tw, t + th))
    d = ImageDraw.Draw(im, "RGBA")
    for y in range(int(th * 0.55), th):                        # bottom scrim
        a = int(200 * ((y - th * 0.55) / (th * 0.45)))
        d.line([(0, y), (tw, y)], fill=(0, 0, 0, a))
    f = _fit_font(d, title, int(tw * 0.9), int(th * 0.16))
    b = d.textbbox((0, 0), title, font=f, stroke_width=max(2, th // 110))
    ty = int(th * 0.60)
    d.text(((tw - (b[2] - b[0])) // 2, ty), title, font=f, fill=(255, 255, 255, 255),
           stroke_width=max(2, th // 110), stroke_fill=(0, 180, 255, 255))
    if subtitle:
        fs = video._load_font(int(th * 0.058))
        sb = d.textbbox((0, 0), subtitle, font=fs)
        d.text(((tw - (sb[2] - sb[0])) // 2, ty + int(th * 0.17)), subtitle,
               font=fs, fill=(0, 210, 255, 255))
    return video._brand_overlay(im, variant="center")


def main() -> int:
    lib = video._background_library()
    if not lib:
        print("no car backgrounds in assets/car_backgrounds/ — nothing to do", file=sys.stderr)
        return 1
    dry = os.environ.get("DRY_RUN", "false").lower() == "true"
    limit = int(os.environ.get("LIMIT", "0")) or None

    yt = _service()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        resp = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                       maxResults=50, pageToken=token).execute()
        ids += [it["contentDetails"]["videoId"] for it in resp["items"]]
        token = resp.get("nextPageToken")
        if not token:
            break

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    # State file: video IDs already given the new thumbnail, so spaced re-runs
    # skip them instead of burning YouTube's burst budget re-setting done ones.
    state_path = Path(os.environ.get("STATE_FILE", str(ROOT / "scripts" / "thumb_done.txt")))
    done_ids = set(state_path.read_text().split()) if state_path.exists() else set()

    def _set_with_retry(vid: str, path: Path) -> bool:
        """Set one thumbnail; short backoff on the 429 burst limit, then give up
        (a later run retries) so a run never stalls to the job timeout."""
        for attempt in range(3):
            try:
                yt.thumbnails().set(
                    videoId=vid,
                    media_body=MediaFileUpload(str(path), mimetype="image/jpeg")).execute()
                return True
            except HttpError as exc:
                if getattr(exc, "resp", None) is not None and exc.resp.status == 429:
                    wait = 15 * (attempt + 1)
                    print(f"    rate-limited on {vid}; waiting {wait}s "
                          f"(try {attempt + 1}/3)…", flush=True)
                    time.sleep(wait)
                    continue
                print(f"    error on {vid}: {exc}", flush=True)
                return False
        print(f"    still rate-limited on {vid} — leaving for a later run", flush=True)
        return False

    done = skipped = failed = already = 0
    for i in range(0, len(ids), 50):
        info = yt.videos().list(part="status,snippet", id=",".join(ids[i:i + 50])).execute()
        for v in info["items"]:
            if v["status"].get("privacyStatus") != "public":
                continue
            if v["id"] in done_ids:
                already += 1
                continue
            title = v["snippet"]["title"]
            preset = _match_preset(title)
            if not preset:
                print(f"  skip (no preset match): {title[:50]}")
                skipped += 1
                continue
            dur = re.search(r"(\d+)\s*hour", title, re.I)
            sub = "BASS BOOSTED" + (f" • {dur.group(1)} HOUR" if dur else "")
            img = lib[(done + failed) % len(lib)]
            thumb = _car_thumb(preset["title"].upper(), sub, img)
            tmp = Path(tempfile.mkdtemp()) / f"{v['id']}.jpg"
            thumb.save(tmp, "JPEG", quality=90)
            if dry:
                print(f"  [dry] would set {v['id']}  {preset['title']:<13} <- {img.name}")
                done += 1
            elif _set_with_retry(v["id"], tmp):
                print(f"  set {v['id']}  {preset['title']:<13} <- {img.name}", flush=True)
                done += 1
                done_ids.add(v["id"])
                state_path.write_text("\n".join(sorted(done_ids)) + "\n")
                time.sleep(6)                                  # ease the burst limit
            else:
                failed += 1
            if limit and done >= limit:
                print(f"\nreached LIMIT={limit}")
                break
        else:
            continue
        break
    print(f"\ndone: {done} new{' (dry run)' if dry else ''}, {already} already done, "
          f"{skipped} skipped, {failed} still rate-limited (a later run finishes those)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
