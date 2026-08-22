"""AI thumbnail hero images via Cloudflare Workers AI (FLUX-1-schnell).

Generates a striking, genre-aware hero image per video that the thumbnail
builder composites the brand mark and title over. Uses Cloudflare Workers AI,
which has a generous free tier and a simple HTTP API — so it can run in the
daily GitHub Actions pipeline.

Needs two repo secrets:
  CF_ACCOUNT_ID   your Cloudflare account id
  CF_API_TOKEN    an API token with the "Workers AI" permission

Everything is best-effort: if the secrets are missing or the API errors, the
pipeline falls back to the existing procedural thumbnail, so an upload never
breaks over the AI image.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "@cf/black-forest-labs/flux-1-schnell"
API_URL = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"


class AIImageError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("CF_ACCOUNT_ID", "").strip()
                and os.environ.get("CF_API_TOKEN", "").strip())


# Base subject per genre, then several interchangeable STYLE variants. The
# learner (src/insights.py) tracks which style index earns the most views and
# biases new uploads toward it, so covers improve over time; an exploration
# share keeps trying fresh looks. TREND_TERMS rotate a current-aesthetic phrase.
_SUBJECT = {
    "aura_phonk": ("A blacked-out generic sports car on a wet neon street at night, "
                   "glowing headlight rings, vivid purple green and yellow aura smoke "
                   "swirling around it, dreamy phonk 'aura farming' aesthetic"),
    "trap_mafia": ("An aggressive matte black muscle car, dark cinematic mafia "
                   "atmosphere, wet asphalt at night, moody and menacing"),
    "_default":   ("A sleek generic supercar on a neon-lit city highway at night, "
                   "glossy reflections on wet asphalt, high-energy car-music vibe"),
}
_STYLES = {
    "aura_phonk": [
        "low wide angle, deep neon reflections, heavy colored smoke, rim light",
        "front three-quarter hero shot, glowing rings, rain and drifting mist",
        "rear view with long-exposure light trails and cyberpunk city bokeh",
    ],
    "trap_mafia": [
        "doing a burnout, thick red and gold tyre smoke, sparks and embers, low angle",
        "front three-quarter, dramatic rim light, fog, glowing wheels, menacing pose",
        "sideways drift, tyre smoke, neon reflections on wet asphalt, motion energy",
    ],
    "_default": [
        "rear view, long-exposure light trails, electric blue and cyan glow",
        "front three-quarter, wet city street, vivid cyan neon reflections",
        "low dramatic angle, sunset-to-night gradient sky, lens flare",
    ],
}
TREND_TERMS = [
    "trending cinematic look", "hyper-detailed 8k", "moody teal-and-orange grade",
    "dramatic volumetric lighting", "bold high-contrast poster composition",
    "aesthetic neon color pop",
]
_COMMON = ("Ultra high detail, cinematic dramatic lighting, bold high contrast, "
           "vibrant, professional YouTube music thumbnail, no text, no watermark, "
           "no logos, unbranded, 16:9 wide composition.")


def _styles_for(preset: dict) -> list[str]:
    return _STYLES.get(preset.get("genre"), _STYLES["_default"])


def n_styles(preset: dict) -> int:
    return len(_styles_for(preset))


def thumbnail_prompt(preset: dict, primary: str, style_idx: int = 0,
                     trend_idx: int | None = None) -> str:
    """Genre-aware text-to-image prompt for the thumbnail hero. ``style_idx``
    selects one of the genre's style variants; a rotating trend term is appended.
    No text (the title is drawn on top), unbranded (copyright-safe), 16:9."""
    genre = preset.get("genre")
    subject = _SUBJECT.get(genre, _SUBJECT["_default"])
    styles = _styles_for(preset)
    style = styles[style_idx % len(styles)]
    trend = TREND_TERMS[(trend_idx if trend_idx is not None else 0) % len(TREND_TERMS)]
    return f"{subject}, {style}. {trend}. {_COMMON}"


def generate(prompt: str, out_path: str | Path, steps: int = 6,
             timeout: int = 120) -> Path:
    """Generate one image and write it to ``out_path`` (JPEG). Raises AIImageError."""
    acct = os.environ.get("CF_ACCOUNT_ID", "").strip()
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not acct or not token:
        raise AIImageError("CF_ACCOUNT_ID / CF_API_TOKEN not set")
    url = API_URL.format(acct=acct, model=MODEL)
    body = json.dumps({"prompt": prompt, "steps": int(max(1, min(steps, 8)))}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise AIImageError(f"Cloudflare AI HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise AIImageError(f"Cloudflare AI request failed: {exc}") from exc

    if not payload.get("success", True):
        raise AIImageError(f"Cloudflare AI error: {str(payload.get('errors'))[:300]}")
    b64 = (payload.get("result") or {}).get("image")
    if not b64:
        raise AIImageError(f"no image in response: {json.dumps(payload)[:300]}")
    try:
        data = base64.b64decode(b64)
    except Exception as exc:
        raise AIImageError(f"bad base64 image: {exc}") from exc
    if len(data) < 2000:
        raise AIImageError(f"image too small ({len(data)} bytes)")
    out = Path(out_path)
    out.write_bytes(data)
    return out


def generate_thumbnail_hero(preset: dict, primary: str, out_dir: str | Path,
                            seed: int = 0, style_idx: int = 0,
                            trend_idx: int | None = None) -> Path | None:
    """Generate the thumbnail hero image, or None if AI images are unavailable /
    the request fails (caller falls back to the procedural thumbnail)."""
    if not available():
        return None
    dest = Path(out_dir) / "hero.jpg"
    try:
        generate(thumbnail_prompt(preset, primary, style_idx, trend_idx), dest)
        print(f"    [thumb] AI hero image ready (Cloudflare Workers AI) "
              f"style={style_idx}")
        return dest
    except AIImageError as exc:
        print(f"    [thumb] AI image failed ({exc}); using the procedural thumbnail")
        return None
