"""Generative visuals + ffmpeg command construction.

The look is a calm, slowly drifting gradient. To make an infinite loop with no
visible seam, the background is rendered **horizontally tileable** (its right
half repeats its left half) and ffmpeg scrolls a 1920-wide window across exactly
one tile-width over the loop period — so the last frame equals the first.

Only Pillow/numpy are needed to build the still background (testable anywhere);
the motion, grain and vignette are applied by ffmpeg at render time.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1920
HEIGHT = 1080
FPS = 24


def _hex_to_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)


def _vertical_gradient(palette: list[str], h: int) -> np.ndarray:
    """Interpolate the palette stops down the image height -> (h, 3)."""
    stops = [_hex_to_rgb(c) for c in palette]
    positions = np.linspace(0.0, 1.0, len(stops))
    ys = np.linspace(0.0, 1.0, h)
    out = np.empty((h, 3))
    for c in range(3):
        out[:, c] = np.interp(ys, positions, [s[c] for s in stops])
    return out


def build_background(preset: dict, path: str | Path,
                     width: int = WIDTH, height: int = HEIGHT,
                     seed: int | None = None) -> Path:
    """Render a horizontally-tileable gradient background (width*2 wide)."""
    rng = np.random.default_rng(seed)
    vis = preset["visual"]
    tile_w = width          # motion tile == one screen width
    full_w = width * 2      # image holds two identical tiles for seamless scroll

    grad = _vertical_gradient(vis["palette"], height)          # (H, 3)
    img = np.repeat(grad[:, None, :], full_w, axis=1)          # (H, full_w, 3)

    # Horizontal light modulation: sines whose periods divide the tile width, so
    # the pattern is exactly periodic and the scroll stays seamless.
    x = np.arange(full_w)
    modulation = np.zeros(full_w)
    for cycles in (1, 2, 3):
        phase = rng.uniform(0, 2 * math.pi)
        amp = rng.uniform(0.04, 0.09) / cycles
        modulation += amp * np.sin(2 * math.pi * cycles * x / tile_w + phase)
    brightness = (1.0 + modulation)[None, :, None]
    img = img * brightness

    # Soft horizon glow band (constant across x -> trivially seamless), adds depth.
    yy = np.linspace(0, 1, height)
    band_center = rng.uniform(0.3, 0.55)
    glow = np.exp(-((yy - band_center) ** 2) / (2 * 0.09 ** 2))
    accent = _hex_to_rgb(vis["palette"][-1])
    img += glow[:, None, None] * accent[None, None, :] * 0.18

    # Bake a subtle film grain INTO the image (monochrome). Doing it here instead
    # of with ffmpeg's per-frame `noise` filter keeps the encode near-realtime and
    # the file small. Generated for one tile and repeated so it stays seamless.
    grain_std = float(vis.get("grain", 0.05)) * 100.0
    if grain_std > 0:
        tile_grain = rng.normal(0.0, grain_std, size=(height, tile_w, 1))
        img = img + np.tile(tile_grain, (1, full_w // tile_w, 3))

    img = np.clip(img, 0, 255).astype(np.uint8)
    out = Path(path)
    Image.fromarray(img, "RGB").save(out, "PNG")
    return out


def build_mist(preset: dict, path: str | Path,
               width: int = WIDTH, height: int = HEIGHT,
               seed: int | None = None) -> Path:
    """Render a drifting mist/aurora RGBA layer (width*2 wide, x-tileable).

    Built from products of sinusoids whose horizontal frequencies are integer
    cycles per tile, so the layer is exactly periodic in x and can scroll
    forever without a seam. ffmpeg drifts it at a different speed than the
    background for a parallax effect.
    """
    rng = np.random.default_rng(None if seed is None else seed + 101)
    vis = preset["visual"]
    x = np.arange(width)[None, :]
    y = np.arange(height)[:, None]

    field = np.zeros((height, width))
    for _ in range(7):
        cx = int(rng.integers(1, 5))              # integer cycles per tile -> periodic
        fy = rng.uniform(0.6, 2.8)
        ph_x, ph_y = rng.uniform(0, 2 * math.pi, 2)
        amp = rng.uniform(0.5, 1.0)
        field += (amp
                  * np.sin(2 * math.pi * cx * x / width + ph_x)
                  * np.sin(2 * math.pi * fy * y / height + ph_y))
    field -= field.min()
    field /= max(field.max(), 1e-9)
    mist = np.clip(field, 0, 1) ** 2.2            # keep only the bright patches
    mist = np.tile(mist, (1, 2))                  # duplicate tile -> exact x-periodicity

    tint = _hex_to_rgb(vis["palette"][-1]) * 0.55 + np.array([200.0, 210.0, 225.0]) * 0.45
    rgba = np.zeros((height, width * 2, 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(tint[None, None, :], 0, 255).astype(np.uint8)
    rgba[..., 3] = (mist * 60).astype(np.uint8)   # max ~24% opacity, subtle
    out = Path(path)
    Image.fromarray(rgba, "RGBA").save(out, "PNG")
    return out


def build_particles(preset: dict, path: str | Path,
                    width: int = WIDTH, height: int = HEIGHT,
                    seed: int | None = None) -> Path:
    """Render a floating-particles RGBA layer (height*2 tall, y-tileable).

    Soft bokeh dots drawn once in [0, height) then stacked twice vertically, so
    an upward scroll of exactly one tile loops seamlessly. Particles near the
    left/right edges are wrapped so nothing pops at the borders.
    """
    rng = np.random.default_rng(None if seed is None else seed + 202)
    vis = preset["visual"]
    alpha = np.zeros((height, width))
    n_particles = max(18, int(34 * (width * height) / (1920 * 1080)))
    for _ in range(n_particles):
        px = float(rng.uniform(0, width))
        py = float(rng.uniform(0, height))
        sigma = float(rng.uniform(2.0, 11.0))
        peak = float(rng.uniform(0.25, 0.9))
        r = int(sigma * 4)
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        blob = peak * np.exp(-(xx**2 + yy**2) / (2 * sigma**2))
        for ox in (-width, 0, width):             # horizontal wrap
            cx, cy = int(px) + ox, int(py)
            x0, x1 = max(0, cx - r), min(width, cx + r + 1)
            y0, y1 = max(0, cy - r), min(height, cy + r + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            bx0, by0 = x0 - (cx - r), y0 - (cy - r)
            alpha[y0:y1, x0:x1] += blob[by0:by0 + (y1 - y0), bx0:bx0 + (x1 - x0)]
    alpha = np.clip(alpha, 0, 1)

    tint = _hex_to_rgb(vis["palette"][-1]) * 0.3 + np.array([235.0, 238.0, 245.0]) * 0.7
    tile = np.zeros((height, width, 4), dtype=np.uint8)
    tile[..., :3] = np.clip(tint[None, None, :], 0, 255).astype(np.uint8)
    tile[..., 3] = (alpha * 150).astype(np.uint8)
    rgba = np.vstack([tile, tile])                # 2 tiles tall -> seamless rise
    out = Path(path)
    Image.fromarray(rgba, "RGBA").save(out, "PNG")
    return out


# --------------------------------------------------------------------------- #
# ffmpeg command builders (returned as arg lists; the pipeline runs them)
# --------------------------------------------------------------------------- #
def build_loop_clip_cmd(bg_png: str, mist_png: str, particles_png: str,
                        wav: str, preset: dict, loop_seconds: float,
                        out_mp4: str, width: int = WIDTH, height: int = HEIGHT,
                        fps: int = FPS) -> list[str]:
    """ffmpeg command producing one seamless animated audio+video loop clip.

    Three layers move at different speeds for a parallax feel:
      - background gradient scrolls 1 tile per loop (crop window),
      - mist drifts the opposite way, 2 tiles per loop (overlay x),
      - particles rise 2 tiles per loop (overlay y).
    Every rate is an integer number of tile-wraps per loop, so the final frame
    equals the first and the extended video loops without any visible seam.
    Overlays are cheap pixel ops — encode stays near real-time.
    """
    vis = preset["visual"]
    vignette_angle = 0.15 + 0.5 * float(vis.get("vignette", 0.5))  # radians-ish

    x_bg = f"mod({width}*t/{loop_seconds}\\,{width})"
    x_mist = f"-mod({2 * width}*t/{loop_seconds}\\,{width})"
    y_part = f"-mod({2 * height}*t/{loop_seconds}\\,{height})"
    fc = (
        f"[0:v]crop={width}:{height}:x='{x_bg}':y=0[base];"
        f"[base][1:v]overlay=x='{x_mist}':y=0[m];"
        f"[m][2:v]overlay=x=0:y='{y_part}'[p];"
        f"[p]vignette=a={vignette_angle:.4f},format=yuv420p[v]"
    )
    return [
        "ffmpeg", "-y",
        "-loop", "1", "-i", bg_png,
        "-loop", "1", "-i", mist_png,
        "-loop", "1", "-i", particles_png,
        "-i", wav,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "3:a",
        "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "23", "-maxrate", "3000k", "-bufsize", "6000k",
        "-r", str(fps), "-t", f"{loop_seconds}",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        out_mp4,
    ]


def build_extend_cmd(loop_mp4: str, target_seconds: float, out_mp4: str) -> list[str]:
    """Repeat the encoded loop to fill the full duration with no re-encode."""
    return [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", loop_mp4,
        "-t", f"{target_seconds}",
        "-c", "copy",
        "-movflags", "+faststart",
        out_mp4,
    ]


# --------------------------------------------------------------------------- #
# Thumbnail
# --------------------------------------------------------------------------- #
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in (
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_thumbnail(preset: dict, title: str, subtitle: str, path: str | Path,
                    seed: int | None = None) -> Path:
    """1280x720 thumbnail: background crop + large title text."""
    tw, th = 1280, 720
    bg_tmp = Path(path).with_suffix(".bg.png")
    build_background(preset, bg_tmp, width=tw, height=th, seed=seed)
    img = Image.open(bg_tmp).convert("RGB").crop((0, 0, tw, th))
    # Darken lower third for text legibility.
    overlay = Image.new("RGB", (tw, th), (0, 0, 0))
    mask = Image.new("L", (tw, th), 0)
    md = ImageDraw.Draw(mask)
    for y in range(th):
        md.line([(0, y), (tw, y)], fill=int(150 * max(0, (y - th * 0.35) / (th * 0.65))))
    img = Image.composite(overlay, img, mask)

    draw = ImageDraw.Draw(img)
    title_font = _load_font(96)
    sub_font = _load_font(46)

    def centered(text, font, y, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        x = (tw - w) // 2
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0))  # shadow
        draw.text((x, y), text, font=font, fill=fill)

    centered(title, title_font, th * 0.52, (245, 245, 245))
    centered(subtitle, sub_font, th * 0.74, (200, 210, 220))

    out = Path(path)
    img.save(out, "JPEG", quality=90)
    bg_tmp.unlink(missing_ok=True)
    return out
