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

# 1440p ("2K"): procedural art costs nothing to render larger, and YouTube
# assigns >=1440p uploads its higher-quality VP9 transcode — visibly better
# than the AVC it gives 1080p, even for viewers watching at 1080p.
WIDTH = 2560
HEIGHT = 1440
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
    max_alpha = int(vis.get("mist_opacity", 60))  # presets can ask for denser smoke
    rgba = np.zeros((height, width * 2, 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(tint[None, None, :], 0, 255).astype(np.uint8)
    rgba[..., 3] = (mist * max_alpha).astype(np.uint8)
    out = Path(path)
    Image.fromarray(rgba, "RGBA").save(out, "PNG")
    return out


# --------------------------------------------------------------------------- #
# Themed effect layers — each preset gets its own kind of motion so uploads
# don't all look alike. Every effect is drawn on ONE tile and duplicated along
# its scroll axis, so the loop stays mathematically seamless.
# --------------------------------------------------------------------------- #
# axis: which way the texture scrolls; wraps: tile-wraps per loop (speed);
# down: reverse direction (falling instead of rising / leftward drift).
EFFECTS = {
    "bubbles":   {"axis": "y", "wraps": 2, "down": False},
    "embers":    {"axis": "y", "wraps": 3, "down": False},
    "fireflies": {"axis": "y", "wraps": 1, "down": False},
    "snow":      {"axis": "y", "wraps": 1, "down": True},
    "rain":      {"axis": "y", "wraps": 6, "down": True},
    "stars":     {"axis": "x", "wraps": 1, "down": False},
}


def _draw_sprite(alpha, tints, x, y, sig_x, sig_y, peak, tint, width, height):
    """Add one anisotropic gaussian sprite, wrapped across both edges."""
    r_x, r_y = int(sig_x * 4) + 1, int(sig_y * 4) + 1
    yy, xx = np.mgrid[-r_y:r_y + 1, -r_x:r_x + 1]
    blob = peak * np.exp(-(xx**2 / (2 * sig_x**2) + yy**2 / (2 * sig_y**2)))
    for ox in (-width, 0, width):
        for oy in (-height, 0, height):
            cx, cy = int(x) + ox, int(y) + oy
            x0, x1 = max(0, cx - r_x), min(width, cx + r_x + 1)
            y0, y1 = max(0, cy - r_y), min(height, cy + r_y + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            bx0, by0 = x0 - (cx - r_x), y0 - (cy - r_y)
            patch = blob[by0:by0 + (y1 - y0), bx0:bx0 + (x1 - x0)]
            alpha[y0:y1, x0:x1] += patch
            tints[y0:y1, x0:x1] += patch[..., None] * tint[None, None, :]


def build_effect_layer(preset: dict, path: str | Path,
                       width: int = WIDTH, height: int = HEIGHT,
                       seed: int | None = None) -> Path:
    """Render the preset's themed effect layer (RGBA, tiled along its axis)."""
    rng = np.random.default_rng(None if seed is None else seed + 202)
    vis = preset["visual"]
    kind = vis.get("effect", "bubbles")
    density = float(vis.get("effect_density", 1.0))
    scale = (width * height) / (1920 * 1080)

    alpha = np.zeros((height, width))
    tints = np.zeros((height, width, 3))
    accent = _hex_to_rgb(vis["palette"][-1])
    pale = np.array([235.0, 238.0, 245.0])

    if kind == "rain":
        n = int(110 * density * scale)
        for _ in range(n):
            tint = pale * rng.uniform(0.75, 1.0)
            _draw_sprite(alpha, tints, rng.uniform(0, width), rng.uniform(0, height),
                         rng.uniform(0.6, 1.1), rng.uniform(14, 34),
                         rng.uniform(0.2, 0.5), tint, width, height)
        max_a = 110
    elif kind == "embers":
        n = int(45 * density * scale)
        warm = [np.array([255.0, 150.0, 60.0]), np.array([255.0, 100.0, 40.0]),
                np.array([255.0, 190.0, 90.0])]
        for _ in range(n):
            tint = warm[int(rng.integers(0, len(warm)))] * rng.uniform(0.7, 1.0)
            _draw_sprite(alpha, tints, rng.uniform(0, width), rng.uniform(0, height),
                         (s := rng.uniform(1.2, 5.0)), s * rng.uniform(1.0, 1.6),
                         rng.uniform(0.35, 1.0), tint, width, height)
        max_a = 170
    elif kind == "fireflies":
        n = int(26 * density * scale)
        glow = np.array([220.0, 255.0, 140.0])
        for _ in range(n):
            _draw_sprite(alpha, tints, rng.uniform(0, width), rng.uniform(0, height),
                         (s := rng.uniform(1.0, 3.2)), s,
                         rng.uniform(0.3, 0.9), glow * rng.uniform(0.7, 1.0),
                         width, height)
        max_a = 150
    elif kind == "snow":
        n = int(70 * density * scale)
        for _ in range(n):
            _draw_sprite(alpha, tints, rng.uniform(0, width), rng.uniform(0, height),
                         (s := rng.uniform(1.2, 4.0)), s,
                         rng.uniform(0.3, 0.8), pale, width, height)
        max_a = 140
    elif kind == "stars":
        n = int(160 * density * scale)
        for _ in range(n):
            big = rng.random() < 0.08
            s = rng.uniform(1.6, 3.4) if big else rng.uniform(0.5, 1.1)
            tint = pale if rng.random() < 0.8 else accent * 0.5 + pale * 0.5
            _draw_sprite(alpha, tints, rng.uniform(0, width), rng.uniform(0, height),
                         s, s, rng.uniform(0.5, 1.0) if big else rng.uniform(0.3, 0.9),
                         tint, width, height)
        max_a = 190
    else:  # "bubbles" — the classic soft bokeh
        n = int(34 * density * scale)
        tint_base = accent * 0.3 + pale * 0.7
        for _ in range(n):
            _draw_sprite(alpha, tints, rng.uniform(0, width), rng.uniform(0, height),
                         (s := rng.uniform(2.0, 11.0)), s,
                         rng.uniform(0.25, 0.9), tint_base, width, height)
        max_a = 150

    a = np.clip(alpha, 0, 1)
    rgb = np.zeros((height, width, 3))
    mask = alpha > 1e-6
    rgb[mask] = tints[mask] / alpha[mask][:, None]
    tile = np.zeros((height, width, 4), dtype=np.uint8)
    tile[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    tile[..., 3] = (a * max_a).astype(np.uint8)

    axis = EFFECTS.get(kind, EFFECTS["bubbles"])["axis"]
    rgba = np.vstack([tile, tile]) if axis == "y" else np.hstack([tile, tile])
    out = Path(path)
    Image.fromarray(rgba, "RGBA").save(out, "PNG")
    return out


# --------------------------------------------------------------------------- #
# ffmpeg command builders (returned as arg lists; the pipeline runs them)
# --------------------------------------------------------------------------- #
def build_loop_clip_cmd(bg_png: str, mist_png: str, effect_png: str,
                        wav: str, preset: dict, loop_seconds: float,
                        out_mp4: str, width: int = WIDTH, height: int = HEIGHT,
                        fps: int = FPS) -> list[str]:
    """ffmpeg command producing one seamless animated audio+video loop clip.

    Three layers move at different speeds/directions for a parallax feel:
      - background gradient scrolls 1 tile per loop (crop window),
      - mist drifts the opposite way, 2 tiles per loop (overlay x),
      - the themed effect layer moves per its EFFECTS spec (rain falls fast,
        embers rise, stars drift sideways, …).
    Every rate is an integer number of tile-wraps per loop, so the final frame
    equals the first and the extended video loops without any visible seam.
    Overlays are cheap pixel ops — encode stays near real-time.
    """
    vis = preset["visual"]
    vignette_angle = 0.15 + 0.5 * float(vis.get("vignette", 0.5))  # radians-ish

    spec = EFFECTS.get(vis.get("effect", "bubbles"), EFFECTS["bubbles"])
    if spec["axis"] == "y":
        step = spec["wraps"] * height
        pos = (f"-{height}+mod({step}*t/{loop_seconds}\\,{height})" if spec["down"]
               else f"-mod({step}*t/{loop_seconds}\\,{height})")
        fx_overlay = f"overlay=x=0:y='{pos}'"
    else:
        step = spec["wraps"] * width
        pos = (f"-{width}+mod({step}*t/{loop_seconds}\\,{width})" if spec["down"]
               else f"-mod({step}*t/{loop_seconds}\\,{width})")
        fx_overlay = f"overlay=x='{pos}':y=0"

    x_bg = f"mod({width}*t/{loop_seconds}\\,{width})"
    x_mist = f"-mod({2 * width}*t/{loop_seconds}\\,{width})"
    fc = (
        f"[0:v]crop={width}:{height}:x='{x_bg}':y=0[base];"
        f"[base][1:v]overlay=x='{x_mist}':y=0[m];"
        f"[m][2:v]{fx_overlay}[p];"
        f"[p]vignette=a={vignette_angle:.4f},format=yuv420p[v]"
    )
    return [
        "ffmpeg", "-y",
        "-loop", "1", "-i", bg_png,
        "-loop", "1", "-i", mist_png,
        "-loop", "1", "-i", effect_png,
        "-i", wav,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "3:a",
        "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20", "-maxrate", "4500k", "-bufsize", "9000k",
        "-r", str(fps), "-t", f"{loop_seconds}",
        "-c:a", "aac", "-b:a", "256k",
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
    """1280x720 thumbnail: full themed scene (bg + mist + effect) + typography.

    Compositing the same layers the video uses makes the thumbnail an honest,
    distinctive still of that day's scene instead of a bare gradient — each
    preset (rain streaks, embers, stars…) reads differently in the feed.
    """
    tw, th = 1280, 720
    tmp = Path(path)
    bg_p = tmp.with_suffix(".bg.png")
    mist_p = tmp.with_suffix(".mist.png")
    fx_p = tmp.with_suffix(".fx.png")
    build_background(preset, bg_p, width=tw, height=th, seed=seed)
    build_mist(preset, mist_p, width=tw, height=th, seed=seed)
    build_effect_layer(preset, fx_p, width=tw, height=th, seed=seed)

    img = Image.open(bg_p).convert("RGBA").crop((tw // 3, 0, tw // 3 + tw, th))
    mist = Image.open(mist_p).crop((tw // 2, 0, tw // 2 + tw, th))
    fx = Image.open(fx_p).crop((0, 0, tw, th))
    img = Image.alpha_composite(Image.alpha_composite(img, mist), fx)

    # Darken the lower band for text legibility (soft vertical ramp).
    grad = np.zeros((th, tw), dtype=np.uint8)
    ys = np.arange(th)
    ramp = np.clip((ys - th * 0.40) / (th * 0.60), 0, 1) * 165
    grad[:] = ramp[:, None].astype(np.uint8)
    dark = Image.new("RGBA", (tw, th), (0, 0, 0, 255))
    dark.putalpha(Image.fromarray(grad, "L"))
    img = Image.alpha_composite(img, dark).convert("RGB")

    draw = ImageDraw.Draw(img)
    title_font = _load_font(100)
    sub_font = _load_font(44)
    accent = tuple(int(c) for c in _hex_to_rgb(preset["visual"]["palette"][-1]) * 0.5 + 128)

    tb = draw.textbbox((0, 0), title, font=title_font)
    tx = (tw - (tb[2] - tb[0])) // 2
    ty = int(th * 0.52)
    # accent bar above the title anchors the composition and brands the preset
    bar_w = min(tb[2] - tb[0], 420)
    draw.rectangle([(tw - bar_w) // 2, ty - 26, (tw + bar_w) // 2, ty - 16], fill=accent)
    draw.text((tx + 4, ty + 4), title, font=title_font, fill=(0, 0, 0))
    draw.text((tx, ty), title, font=title_font, fill=(248, 248, 248))

    sb = draw.textbbox((0, 0), subtitle, font=sub_font)
    sx = (tw - (sb[2] - sb[0])) // 2
    sy = int(th * 0.76)
    draw.text((sx + 3, sy + 3), subtitle, font=sub_font, fill=(0, 0, 0))
    draw.text((sx, sy), subtitle, font=sub_font, fill=(205, 215, 225))

    out = Path(path)
    img.save(out, "JPEG", quality=92)
    for p in (bg_p, mist_p, fx_p):
        p.unlink(missing_ok=True)
    return out
