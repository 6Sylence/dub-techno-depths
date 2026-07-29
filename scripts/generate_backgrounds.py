#!/usr/bin/env python3
"""Generate a library of copyright-safe car/garage background images.

Uses an OpenAI-compatible image API (default: gpt-image-1). Every prompt asks
for a GENERIC sports car — no real-brand logos, badges, marques or plates — so
the output stays original and safe to monetize, unlike the real car photos the
big bass-boosted channels reuse.

Env:
  OPENAI_API_KEY   required — your image-API key (stored as a GitHub secret)
  IMAGE_MODEL      default: gpt-image-1
  IMAGE_SIZE       default: 1536x1024   (cover-cropped to 16:9 at render time)
  IMAGE_BASE_URL   default: https://api.openai.com/v1
  BG_COUNT         default: 12          how many images to generate
  OUT_DIR          default: assets/car_backgrounds

Images are written as bg_01.jpg, bg_02.jpg, … (existing ones are left in place;
delete them first for a full refresh).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Copyright-safe prompts: generic, unbranded neon-garage / night-drive scenes.
PROMPTS = [
    "Rear view of a generic low-slung neon-lit sports car in a dark concrete "
    "garage, glowing red round taillights, cinematic moody lighting, teal and "
    "magenta rim light, volumetric haze, no logos, no text, original car design",
    "Two unbranded sports cars parked rear-to-camera in a dim underground "
    "parking garage, red taillight glow, overhead spotlight, desaturated cool "
    "tones with red accents, cinematic, no badges, no brand marks, no license plates",
    "Generic supercar silhouette from behind on a wet neon city street at night, "
    "reflections, cyan and pink signage bokeh, cinematic bass-music cover vibe, "
    "no logos, no text, original design",
    "Rear three-quarter of an unbranded tuned coupe in a smoky garage, neon "
    "underglow, red and blue light, dramatic contrast, film grain, no brand logos",
    "Low unbranded sports car facing away toward a glowing tunnel exit, long "
    "light trails, synthwave neon palette, cinematic, no text, no badges",
    "Aggressive generic street-racer rear end with big spoiler in a dark warehouse, "
    "red LED taillight bar, teal spotlights, haze, moody, no logos, original design",
]

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _post(url: str, key: str, body: dict, timeout: int = 180) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:               # surface the API's real message
        try:
            detail = exc.read().decode()[:400]
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None


def main() -> int:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("OPENAI_API_KEY not set — nothing to generate.", file=sys.stderr)
        return 1
    model = os.environ.get("IMAGE_MODEL", "dall-e-3")
    size = os.environ.get("IMAGE_SIZE", "1792x1024")
    base = os.environ.get("IMAGE_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    count = int(os.environ.get("BG_COUNT", "12"))
    out_dir = Path(os.environ.get("OUT_DIR", str(ROOT / "assets" / "car_backgrounds")))
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = len([p for p in out_dir.iterdir() if p.suffix.lower() in MIME])
    made = 0
    for i in range(count):
        prompt = PROMPTS[i % len(PROMPTS)]
        # No response_format: this endpoint rejects it. dall-e-3 returns a URL,
        # gpt-image-1 returns b64_json by default — the fetch below handles both.
        body = {"model": model, "prompt": prompt, "size": size, "n": 1}
        try:
            resp = _post(f"{base}/images/generations", key, body)
            item = resp["data"][0]
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
            else:                                   # some models return a URL
                with urllib.request.urlopen(item["url"], timeout=120) as r:
                    raw = r.read()
        except Exception as exc:                    # keep going; one bad call is fine
            print(f"  image {i + 1} failed: {exc}", file=sys.stderr)
            time.sleep(2)
            continue
        out = out_dir / f"bg_{existing + made + 1:02d}.jpg"
        out.write_bytes(raw)
        made += 1
        print(f"wrote {out.name} ({len(raw) // 1024} KB)")

    print(f"done: {made} image(s) in {out_dir}")
    return 0 if made else 1


if __name__ == "__main__":
    raise SystemExit(main())
