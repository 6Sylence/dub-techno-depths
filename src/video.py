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
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# 1440p ("2K"): our visuals are a smooth scrolling gradient, so 1440p looks
# essentially identical to 4K here while the per-frame 4K compositing (crop +
# 2 overlays + beat-pulse + vignette) was taking ~21 min per render on CI's
# 2-vCPU runners — too slow/expensive to run twice daily. 1440p still gets
# YouTube's better VP9 transcode, and the EDM titles never claimed "4K".
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


# Fixed channel brand mark — identical on every video/thumbnail so the channel
# is recognizable at a glance (like the big bass-boosted channels' logos).
BRAND_LINE1 = "BASS BOOSTED"
BRAND_LINE2 = "NATION"
# Named neon colours for the mark; pick with env BRAND_COLOR (default cyan).
BRAND_COLORS = {
    "cyan": (0, 210, 255),
    "pink": (255, 46, 120),
    "red": (255, 48, 62),
    "gold": (255, 178, 40),
    "green": (60, 255, 150),
}
BRAND_COLOR = BRAND_COLORS.get(os.environ.get("BRAND_COLOR", "cyan"), (0, 210, 255))
# Where the mark sits: "center" (top-centre lockup) or "corner" (compact,
# bottom-left, so it never covers the car). Override with env BRAND_VARIANT.
BRAND_VARIANT = os.environ.get("BRAND_VARIANT", "corner")


def _slant(im: "Image.Image", k: float = 0.10) -> "Image.Image":
    """Shear an image for a subtle italic lean (much gentler than before)."""
    w, h = im.size
    return im.transform((w + int(h * k), h), Image.AFFINE, (1, -k, 0, 0, 1, 0),
                        resample=Image.BICUBIC)


def _text_img(txt, font, fill, stroke_fill=None, sw=0) -> "Image.Image":
    """Render text to a tight transparent image (optional neon outline)."""
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    b = probe.textbbox((0, 0), txt, font=font, stroke_width=sw)
    im = Image.new("RGBA", (b[2] - b[0] + sw * 2 + 20, b[3] - b[1] + sw * 2 + 20), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10 - b[0], 10 - b[1]), txt, font=font, fill=fill,
                            stroke_width=sw, stroke_fill=stroke_fill)
    return im


def _emblem(d: "ImageDraw.ImageDraw", cx: int, cy: int, R: int, color) -> None:
    """A clean, modern music emblem: a bold neon ring with three rounded
    equalizer bars inside — reads clearly even at small corner sizes."""
    ring_w = max(3, int(R * 0.22))
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=color + (255,), width=ring_w)
    bar_w = max(2, int(R * 0.26))
    gap = max(2, int(R * 0.20))
    heights = (0.52, 1.0, 0.72)                               # EQ bars, middle tallest
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    x0 = cx - total_w // 2
    base_y = cy + int(R * 0.5)
    for i, hf in enumerate(heights):
        bx = x0 + i * (bar_w + gap)
        top = base_y - int(R * 0.98 * hf)
        d.rounded_rectangle([bx, top, bx + bar_w, base_y],
                            radius=bar_w // 2, fill=(255, 255, 255, 255))


def _brand_lockup(color=BRAND_COLOR) -> "Image.Image":
    """Build the tight brand lockup once (emblem + wordmark + spaced NATION with
    flanking rules) at a fixed reference resolution; callers scale/position it."""
    H0 = 1440
    canvas = Image.new("RGBA", (H0 * 2, H0), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    cx = H0
    R = int(H0 * 0.050)
    ey = int(H0 * 0.03) + R
    _emblem(d, cx, ey, R, color)

    f1 = _load_font(int(H0 * 0.088))                          # BASS BOOSTED (upright,
    wm = _text_img(BRAND_LINE1, f1, (255, 255, 255, 255), color + (255,),  # crisp thin
                   max(1, int(H0 * 0.0035)))                  # cyan keyline, no slant)
    wy = ey + R + int(H0 * 0.024)
    canvas.alpha_composite(wm, (cx - wm.width // 2, wy))

    f2 = _load_font(int(H0 * 0.052))                          # N A T I O N (spaced)
    tag = _text_img(" ".join(BRAND_LINE2), f2, color + (255,))
    ty = wy + wm.height + int(H0 * 0.008)
    canvas.alpha_composite(tag, (cx - tag.width // 2, ty))
    ry = ty + tag.height // 2                                 # thin flanking rules
    gap, rule = int(H0 * 0.024), int(H0 * 0.055)
    for sgn in (-1, 1):
        x0 = cx + sgn * (tag.width // 2 + gap)
        d.line([(x0, ry), (x0 + sgn * rule, ry)], fill=color + (230,),
               width=max(2, int(H0 * 0.004)))
    return canvas.crop(canvas.getbbox())


def _brand_overlay(img: "Image.Image", variant: str | None = None,
                   color=None) -> "Image.Image":
    """Composite the brand lockup with a soft dark halo (legibility over bright
    neon) and a single neon glow — crisp, not the old muddy double blur."""
    W, H = img.size
    variant = variant or BRAND_VARIANT
    bc = color or BRAND_COLOR
    lock = _brand_lockup(bc)
    tw = int(W * (0.22 if variant == "corner" else 0.33))
    th = max(1, int(lock.height * tw / lock.width))
    lock = lock.resize((tw, th), Image.LANCZOS)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pos = ((int(W * 0.035), H - th - int(H * 0.055)) if variant == "corner"
           else (W // 2 - tw // 2, int(H * 0.035)))
    layer.alpha_composite(lock, pos)
    mask = layer.split()[3]

    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))            # soft dark plate for legibility
    halo.paste((0, 0, 0, 255), (0, 0), mask)
    halo.putalpha(halo.split()[3].point(lambda a: int(a * 0.5)))
    halo = halo.filter(ImageFilter.GaussianBlur(max(6, W // 240)))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))            # symmetric neon glow (brand colour)
    glow.paste(bc + (255,), (0, 0), mask)
    glow = glow.filter(ImageFilter.GaussianBlur(max(4, W // 300)))
    glow.putalpha(glow.split()[3].point(lambda a: int(a * 0.6)))

    out = img.convert("RGBA")
    out = Image.alpha_composite(out, halo)
    out = Image.alpha_composite(out, glow)
    out = Image.alpha_composite(out, layer)
    return out.convert("RGB")


def _render_synthwave(vis: dict, width: int, height: int, seed: int | None) -> np.ndarray:
    """A synthwave scene: sunset sky + scanline sun + starfield + neon perspective
    grid + the fixed channel brand. Returns a single-tile (H, W, 3) uint8 image
    (static; the video animates mist/stars + beat pulse over it)."""
    rng = np.random.default_rng(seed)
    pal = vis["palette"]
    sky_top, sky_mid = _hex_to_rgb(pal[0]), _hex_to_rgb(pal[1])
    horizon, accent = _hex_to_rgb(pal[2]), _hex_to_rgb(pal[3])
    sun_top = np.clip(accent * 0.35 + np.array([255.0, 235.0, 150.0]) * 0.65, 0, 255)
    hy = int(height * 0.60)

    img = np.zeros((height, width, 3), float)
    for y in range(hy):                                        # sky gradient
        t = y / max(hy, 1)
        c = (sky_top * (1 - t / 0.6) + sky_mid * (t / 0.6) if t < 0.6
             else sky_mid * (1 - (t - 0.6) / 0.4) + horizon * ((t - 0.6) / 0.4))
        img[y] = c
    img[hy:] = _hex_to_rgb(pal[0]) * 0.5                        # dark ground
    base = Image.fromarray(np.clip(img, 0, 255).astype("uint8"), "RGB")

    d = ImageDraw.Draw(base)                                    # starfield
    for _ in range(int(width * height / 4200)):
        x, y = int(rng.integers(0, width)), int(rng.integers(0, int(hy * 0.92)))
        b = int(255 * rng.uniform(0.3, 0.9)); s = 0 if rng.random() < 0.85 else 1
        d.ellipse([x - s, y - s, x + s, y + s], fill=(b, b, b))

    glow = Image.new("RGB", (width, height), (0, 0, 0)); gd = ImageDraw.Draw(glow)
    cx, r = width // 2, int(height * 0.30)                      # scanline sun
    for i in range(r, 0, -1):
        t = i / r
        gd.ellipse([cx - i, hy - i, cx + i, hy + i],
                   fill=tuple(int(sun_top[k] * (1 - t) + horizon[k] * t) for k in range(3)))
    for k in range(18):
        yy = hy - r + int(r * 0.18) + int(k * (r * 1.05) / 18)
        if yy > hy - r:
            gd.rectangle([cx - r, yy, cx + r, yy + 1 + int(k * 0.55)], fill=(0, 0, 0))
    glow = glow.filter(ImageFilter.GaussianBlur(max(1, width // 640)))
    out = np.clip(np.asarray(base, float) + np.asarray(glow, float) * 0.9, 0, 255)

    grid = Image.new("RGB", (width, height), (0, 0, 0)); gr = ImageDraw.Draw(grid)
    gc = tuple(int(c) for c in accent); vx, vy = width // 2, hy
    for gx in range(-width, 2 * width, max(24, width // 40)):   # converging verticals
        gr.line([(gx, height), (vx, vy)], fill=gc, width=2)
    dep = 0.0
    for i in range(1, 30):                                      # perspective horizontals
        dep += i * 0.8
        yy = hy + int((height - hy) * (1 - 1 / (1 + dep * 0.045)))
        if yy < height:
            gr.line([(0, yy), (width, yy)], fill=gc, width=2)
    grid = grid.filter(ImageFilter.GaussianBlur(1))
    garr = np.asarray(grid, float); garr[:hy] = 0
    out = np.clip(out + garr, 0, 255)

    g = float(vis.get("grain", 0.04)) * 100.0
    if g > 0:
        out = np.clip(out + rng.normal(0.0, g, (height, width, 1)), 0, 255)
    scene = _brand_overlay(Image.fromarray(out.astype("uint8"), "RGB"))
    return np.asarray(scene, dtype="uint8")


# Optional libraries of copyright-safe background images. Drop 16:9 .jpg/.png
# files in assets/<lib>/ (supply your own, or generate them with
# scripts/generate_backgrounds.py). When the folder has images they replace the
# drawn synthwave scene as the video's static base; the brand mark, mist, stars
# and beat-pulse still composite on top. Empty/missing folder -> synthwave scene.
#
# The library is picked by genre: aura-phonk presets use aura_backgrounds
# (character / glowing-aura art), everything else uses car_backgrounds.
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_BG_LIBRARY_DIR = _ASSETS_DIR / "car_backgrounds"
_AURA_BG_LIBRARY_DIR = _ASSETS_DIR / "aura_backgrounds"


def _images_in(d: Path) -> list[Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def _background_library(preset: dict) -> list[Path]:
    """Pick the image library for this preset. Aura-phonk presets use dedicated
    aura_backgrounds art if any is present, otherwise they reuse the car photos
    (rendered with a darker cinematic grade — the 'aura car edit' look)."""
    if preset.get("genre") == "aura_phonk":
        return _images_in(_AURA_BG_LIBRARY_DIR) or _images_in(_BG_LIBRARY_DIR)
    return _images_in(_BG_LIBRARY_DIR)


def _render_library_bg(img_path: Path, width: int, height: int,
                       aura: bool = False) -> np.ndarray:
    """Cover-crop a library image to WxH, grade it for mood, and stamp the channel
    brand mark — the static base for the video. ``aura`` applies the dark, moody
    'aura car edit' grade (blacked-out, cool teal-blue, heavy vignette); otherwise
    the lighter car-music grade is used."""
    im = Image.open(img_path).convert("RGB")
    # cover-crop to the exact frame
    scale = max(width / im.width, height / im.height)
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                   Image.LANCZOS)
    left, top = (im.width - width) // 2, (im.height - height) // 2
    im = im.crop((left, top, left + width, top + height))
    arr = np.asarray(im, float)
    yy, xx = np.mgrid[0:height, 0:width]
    if aura:
        # Dark cinematic 'aura' grade: crush toward black, desaturate, push a cool
        # teal-blue tint and a heavy vignette so the subject glows out of shadow.
        vig = 1 - 0.6 * (((xx - width / 2) / (width / 1.5)) ** 2
                         + ((yy - height / 2) / (height / 1.35)) ** 2)
        arr = arr * np.clip(vig, 0.22, 1)[..., None] * 0.62
        gray = arr.mean(axis=2, keepdims=True)
        arr = gray + (arr - gray) * 0.6                        # desaturate ~40%
        arr = arr * np.array([0.82, 0.95, 1.12])[None, None, :]  # cool teal-blue
        arr = np.clip(arr - 8, 0, 255)                         # deepen the blacks
    else:
        # gentle vignette + slight darkening so overlays and the brand mark read
        vig = 1 - 0.35 * (((xx - width / 2) / (width / 1.5)) ** 2
                          + ((yy - height / 2) / (height / 1.4)) ** 2)
        arr = np.clip(arr * np.clip(vig, 0.45, 1)[..., None] * 0.92, 0, 255)
    scene = _brand_overlay(Image.fromarray(arr.astype("uint8"), "RGB"))
    return np.asarray(scene, dtype="uint8")


def build_background(preset: dict, path: str | Path,
                     width: int = WIDTH, height: int = HEIGHT,
                     seed: int | None = None) -> Path:
    """Render the background. Synthwave presets get a full static neon scene (one
    tile wide) — or, if a car-background library is present, a rotated photo of
    it; everything else gets the horizontally-tileable gradient."""
    vis = preset["visual"]
    if vis.get("style") == "synthwave":
        out = Path(path)
        lib = _background_library(preset)
        if lib:
            pick = lib[(0 if seed is None else int(seed)) % len(lib)]
            dark = preset.get("genre") in ("aura_phonk", "trap_mafia")
            Image.fromarray(_render_library_bg(pick, width, height, aura=dark),
                            "RGB").save(out, "PNG")
        else:
            Image.fromarray(_render_synthwave(vis, width, height, seed), "RGB").save(out, "PNG")
        return out
    rng = np.random.default_rng(seed)
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


# Vivid smoke palette for the aura-farming lane (purple / yellow / green /
# magenta / cyan). Any aura preset can override it with a `smoke_colors` list.
AURA_SMOKE_COLORS = ["#b026ff", "#ffe020", "#22ff66", "#ff2ea6", "#20e0ff"]


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

    # Vivid multicolour smoke: presets can list `smoke_colors` (e.g. purple,
    # yellow, green). Each colour rides its own set of periodic plume lobes, so
    # the layer stays x-tileable but shows distinct coloured smoke instead of a
    # single flat tint.
    smoke_colors = vis.get("smoke_colors") or (
        AURA_SMOKE_COLORS if preset.get("genre") == "aura_phonk" else None)
    if smoke_colors:
        cols = [_hex_to_rgb(c) for c in smoke_colors]
        # Thick "burnout" smoke: billowing turbulent clouds that rise from the
        # bottom (like tyre/exhaust smoke), tinted in vivid colours. Each pixel
        # takes the PURE colour of its strongest plume (no averaging, which would
        # grey the colours out).
        yn = (y / height)                          # 0 top .. 1 bottom
        rise = np.clip((yn - 0.10) / 0.90, 0, 1) ** 1.5   # dense low, fades upward
        best = np.zeros((height, width))
        color = np.zeros((height, width, 3))
        for i in range(9):
            cx = int(rng.integers(1, 3))           # big low-freq masses -> billows
            fy = rng.uniform(0.4, 1.1)
            ph_x, ph_y = rng.uniform(0, 2 * math.pi, 2)
            lobe = (np.sin(2 * math.pi * cx * x / width + ph_x)
                    * np.sin(2 * math.pi * fy * y / height + ph_y))
            # a finer octave adds turbulent smoke texture
            lobe += 0.5 * (np.sin(2 * math.pi * (cx + 2) * x / width + ph_y)
                           * np.sin(2 * math.pi * (fy + 1.3) * y / height + ph_x))
            lobe = np.clip(lobe, 0, None) * rise   # keep positive + weight to bottom
            col = cols[i % len(cols)]
            win = lobe > best
            best = np.where(win, lobe, best)
            color = np.where(win[..., None], col[None, None, :], color)
        thr = float(np.quantile(best, 0.5))        # clear gaps so the car still reads
        best = np.clip(best - thr, 0, None)
        mist = (best / max(best.max(), 1e-9)) ** 1.0
        mist = np.tile(mist, (1, 2))
        color = np.tile(color, (1, 2, 1))
        max_alpha = int(vis.get("smoke_opacity", 185))
        rgba = np.zeros((height, width * 2, 4), dtype=np.uint8)
        rgba[..., :3] = np.clip(color, 0, 255).astype(np.uint8)
        rgba[..., 3] = (mist * max_alpha).astype(np.uint8)
        img = Image.fromarray(rgba, "RGBA").filter(
            ImageFilter.GaussianBlur(max(2, width // 140)))   # soften into smoke
        out = Path(path)
        img.save(out, "PNG")
        return out

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

    # Beat pulse: a subtle brightness/saturation throb locked to the track BPM,
    # so the neon visuals pump with the drop (eval=frame -> per-frame expression).
    bpm = float(preset.get("audio", {}).get("bpm", 126))
    bps = bpm / 60.0
    pulse = float(vis.get("beat_pulse", 0.0))
    pulse_f = ""
    if pulse > 0:
        pulse_f = (f"eq=brightness='{pulse:.3f}*sin(2*PI*{bps:.4f}*t)':"
                   f"saturation='1+{pulse * 1.5:.3f}*sin(2*PI*{bps:.4f}*t)':eval=frame,")

    # Synthwave scenes are a single static tile (no horizontal scroll); the
    # motion comes from the drifting mist/stars overlays and the beat pulse.
    static_bg = vis.get("style") == "synthwave"
    x_bg = "0" if static_bg else f"mod({width}*t/{loop_seconds}\\,{width})"
    x_mist = f"-mod({2 * width}*t/{loop_seconds}\\,{width})"
    fc = (
        f"[0:v]crop={width}:{height}:x='{x_bg}':y=0[base];"
        f"[base][1:v]overlay=x='{x_mist}':y=0[m];"
        f"[m][2:v]{fx_overlay}[p];"
        f"[p]{pulse_f}vignette=a={vignette_angle:.4f},format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", bg_png,
        "-loop", "1", "-i", mist_png,
        "-loop", "1", "-i", effect_png,
    ]
    if wav is not None:
        cmd += ["-i", wav]
    cmd += [
        "-filter_complex", fc,
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "ultrafast",                 # 4K on 2-vCPU CI: speed first
        "-crf", "21", "-maxrate", "7000k", "-bufsize", "14000k",   # 4K headroom (bitrate-capped)
        "-r", str(fps), "-t", f"{loop_seconds}",
    ]
    if wav is not None:
        cmd += ["-map", "3:a", "-c:a", "aac", "-b:a", "256k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += [out_mp4]
    return cmd


def build_mux_loop_cmd(video_loop_mp4: str, audio_file: str, out_seconds: float | None,
                       out_mp4: str) -> list[str]:
    """Tile a (short, silent) video loop under a full-length audio mix.

    The video is stream-looped while the long audio plays over it once. Pass
    ``out_seconds`` to cut to a known length, or None to end exactly with the
    audio (``-shortest``, used when the audio length isn't known up front)."""
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_loop_mp4,
        "-i", audio_file,
        "-map", "0:v", "-map", "1:a",
    ]
    cmd += (["-t", f"{out_seconds}"] if out_seconds else ["-shortest"])
    cmd += [
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart",
        out_mp4,
    ]
    return cmd


def build_audio_concat_cmd(audio_files: list[str], out_file: str,
                           crossfade: float = 2.0) -> list[str]:
    """Stitch several tracks into one continuous audio file with short
    equal-power crossfades between them (a DJ-style blend)."""
    if len(audio_files) == 1:
        return ["ffmpeg", "-y", "-i", audio_files[0],
                "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out_file]
    inputs = []
    for f in audio_files:
        inputs += ["-i", f]
    parts, prev = [], "0:a"
    for i in range(1, len(audio_files)):
        label = "aout" if i == len(audio_files) - 1 else f"x{i}"
        parts.append(f"[{prev}][{i}:a]acrossfade=d={crossfade}:c1=tri:c2=tri[{label}]")
        prev = label
    return ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(parts),
            "-map", "[aout]", "-c:a", "aac", "-b:a", "256k",
            "-movflags", "+faststart", out_file]


def build_voice_mix_cmd(beat_file: str, voice_specs, out_file: str) -> list[str]:
    """Mix one or more spoken voice lines over the beat as an arrangement: each
    line comes in at its own offset, the beat ducks under the combined voice
    (sidechain compression) so the words cut through, then a limiter tames the
    peaks. Output length == beat length (the lines play once per looped block).

    ``voice_specs`` is a list of (path, delay_seconds) — e.g. an intro at 1.5s, a
    hook at 40% and a bar at 72% of the beat. A single spec also works.
    """
    if not voice_specs:
        raise ValueError("voice_specs is empty")
    inputs = ["-i", beat_file]
    parts, labels = [], []
    for i, (path, delay_s) in enumerate(voice_specs):
        inputs += ["-i", str(path)]
        idx = i + 1                                            # input 0 is the beat
        dms = int(max(0.0, float(delay_s)) * 1000)
        parts.append(f"[{idx}:a]adelay={dms}|{dms},volume=2.2[v{i}]")
        labels.append(f"[v{i}]")
    if len(labels) > 1:                                       # sum the lines into one voice bus
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0[voxsum]")
        vox = "[voxsum]"
    else:
        vox = labels[0]
    # apad pads the voice bus with trailing silence so the sidechain covers the
    # whole beat — otherwise sidechaincompress would end with the last line and
    # truncate the track.
    parts.append(f"{vox}apad,asplit=2[voxA][voxB]")
    parts.append("[0:a][voxA]sidechaincompress=threshold=0.04:ratio=8:attack=5:release=320[duck]")
    parts.append("[duck][voxB]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[a]")
    return ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[a]",
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out_file]


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


# --------------------------------------------------------------------------- #
# Bokeh "album-cover" thumbnail
# --------------------------------------------------------------------------- #
# A coherent cyan/blue defocused-city look, identical on every upload so the
# thumbnails read as one recognizable brand in the feed (the trick the big
# bass-boosted channels use). The skyline is drawn procedurally — building
# silhouettes with lit windows — then Gaussian-blurred into bokeh, so there is
# no real photo and nothing to license. The palette is deliberately fixed to
# cyan/blue regardless of the preset so the channel's still frames stay
# consistent; the preset only drives the title text.
BOKEH_STOPS = ["#04070f", "#071630", "#0b2547"]
BOKEH_WINDOW = [(60, 200, 255), (150, 225, 255), (90, 170, 255),
                (230, 245, 255), (255, 180, 95)]
BOKEH_DISC = [(40, 200, 255), (120, 210, 255), (70, 150, 255)]


def _bokeh_city(tw: int, th: int, rng: "np.random.Generator", blur: float) -> "Image.Image":
    """Procedural night skyline (lit windows) blurred into defocused city bokeh."""
    grad = _vertical_gradient(BOKEH_STOPS, th)
    base_arr = np.repeat(grad[:, None, :], tw, axis=1)
    base = Image.fromarray(np.clip(base_arr, 0, 255).astype("uint8"), "RGB")
    d = ImageDraw.Draw(base)
    x = -20
    while x < tw + 20:
        w = int(rng.integers(44, 120))
        bh = int(rng.integers(int(th * 0.28), int(th * 0.72)))
        top = th - bh
        d.rectangle([x, top, x + w, th], fill=(5, 12, 26))       # building silhouette
        cols = max(2, w // 15)
        rows = max(3, bh // 15)
        cw = (w - 10) / cols
        chh = (bh - 10) / rows
        for c in range(cols):
            for r in range(rows):
                if rng.random() < 0.55:                          # some windows lit
                    col = BOKEH_WINDOW[rng.integers(0, len(BOKEH_WINDOW))]
                    b = rng.uniform(0.35, 1.0)
                    col = tuple(int(v * b) for v in col)
                    wx = x + 5 + c * cw
                    wy = top + 5 + r * chh
                    d.rectangle([wx, wy, wx + cw * 0.62, wy + chh * 0.62], fill=col)
        x += w + int(rng.integers(-6, 8))
    return base.filter(ImageFilter.GaussianBlur(blur))           # defocus -> bokeh


def _bokeh_discs(tw: int, th: int, rng: "np.random.Generator", n: int) -> "Image.Image":
    """Big soft foreground bokeh discs for depth."""
    layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x = rng.uniform(0, tw)
        y = rng.uniform(0.25 * th, th)
        r = rng.uniform(40, 95)
        c = BOKEH_DISC[rng.integers(0, len(BOKEH_DISC))]
        a = int(rng.uniform(40, 90))
        d.ellipse([x - r, y - r, x + r, y + r], fill=c + (a,))
    return layer.filter(ImageFilter.GaussianBlur(28))


def _bokeh_base(tw: int, th: int, seed: int | None) -> "Image.Image":
    """Shared cyan/blue defocused-city background (vignette + title band)."""
    rng = np.random.default_rng(0 if seed is None else int(seed))
    img = _bokeh_city(tw, th, rng, blur=7).convert("RGBA")
    img = Image.alpha_composite(img, _bokeh_discs(tw, th, rng, 9))
    arr = np.asarray(img.convert("RGB"), dtype=np.float64)
    yy, xx = np.mgrid[0:th, 0:tw]
    vig = 1 - 0.55 * (((xx - tw / 2) / (tw / 1.6)) ** 2 + ((yy - th / 2) / (th / 1.35)) ** 2)
    arr = arr * np.clip(vig, 0.28, 1)[..., None]
    band = np.exp(-((np.arange(th) - th * 0.55) / (th * 0.19)) ** 2) * 160
    arr = np.clip(arr - band[:, None, None] * 0.55, 0, 255)
    return Image.fromarray(arr.astype("uint8"), "RGB")


def _render_city_bokeh(title: str, subtitle: str, tw: int, th: int,
                       seed: int | None, variant: int = 0) -> "Image.Image":
    """Premium cyan/blue city-bokeh thumbnail.

    Two interchangeable layouts so the channel can A/B its click-through rate
    while keeping one coherent palette:
      variant 0 — centred "album cover": wordmark, divider, title, metadata.
      variant 1 — bottom-left "magazine": left accent bar + big left-aligned
                  title, wordmark top-left, and a bright corner badge.
    """
    im = _bokeh_base(tw, th, seed)
    d = ImageDraw.Draw(im)
    cyan, bright, white = (120, 205, 255), (50, 205, 255), (246, 251, 255)
    meta = subtitle.upper()

    if variant == 1:
        # ---- Variant B: bottom-left magazine layout + corner badge ----
        mx = int(tw * 0.055)
        wf = _load_font(int(th * 0.05))
        d.text((mx, int(th * 0.09)), "BASS BOOSTED NATION", font=wf, fill=cyan)
        tf = _load_font(int(th * 0.165))
        tb = d.textbbox((0, 0), title, font=tf)
        ty = int(th * 0.60)
        bar_h = tb[3] - tb[1]
        d.rectangle([mx, ty, mx + 14, ty + bar_h + int(th * 0.02)], fill=bright)  # accent bar
        tx = mx + 34
        d.text((tx + 3, ty + 3), title, font=tf, fill=(0, 0, 0))
        d.text((tx, ty), title, font=tf, fill=white)
        mf = _load_font(int(th * 0.052))
        d.text((tx, ty + bar_h + int(th * 0.03)), meta, font=mf, fill=cyan)
        # Bright corner badge (badges lift CTR).
        badge = f"MIX {subtitle.split('•')[-1].strip()}" if "•" in subtitle else "NEW MIX"
        bff = _load_font(int(th * 0.044))
        bb = d.textbbox((0, 0), badge, font=bff)
        pad = int(th * 0.018)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        bx1 = tw - bw - 3 * pad - int(tw * 0.03)
        by1 = int(th * 0.085)
        d.rectangle([bx1, by1, bx1 + bw + 2 * pad, by1 + bh + 2 * pad], fill=bright)
        d.text((bx1 + pad, by1 + pad - bb[1]), badge, font=bff, fill=(4, 12, 26))
        return im

    # ---- Variant A: centred album cover ----
    cx = tw // 2
    bf = _load_font(int(th * 0.053))
    wm = "BASS BOOSTED NATION"
    b = d.textbbox((0, 0), wm, font=bf)
    d.text((cx - (b[2] - b[0]) // 2, int(th * 0.085)), wm, font=bf, fill=cyan)
    dy = int(th * 0.45)
    d.rectangle([cx - 95, dy, cx + 95, dy + 6], fill=bright)
    tf = _load_font(int(th * 0.156))
    tb = d.textbbox((0, 0), title, font=tf)
    tx = cx - (tb[2] - tb[0]) // 2
    d.text((tx + 3, dy + 28 + 3), title, font=tf, fill=(0, 0, 0))
    d.text((tx, dy + 28), title, font=tf, fill=white)
    mf = _load_font(int(th * 0.058))
    mb = d.textbbox((0, 0), meta, font=mf)
    d.text((cx - (mb[2] - mb[0]) // 2, dy + int(th * 0.25)), meta, font=mf, fill=(150, 205, 255))
    return im


def build_thumbnail(preset: dict, title: str, subtitle: str, path: str | Path,
                    seed: int | None = None, variant: int = 0) -> Path:
    """1280x720 thumbnail.

    Synthwave (bass-boosted) presets get the premium cyan/blue *city-bokeh*
    treatment. ``variant`` (0 or 1) picks between two layouts so the channel can
    A/B its click-through rate while keeping one coherent palette. Any other
    style falls back to compositing the day's scene layers with centred type.
    """
    tw, th = 1280, 720

    if preset["visual"].get("style") == "synthwave":
        img = _render_city_bokeh(title, subtitle, tw, th, seed, variant=variant)
        out = Path(path)
        img.save(out, "JPEG", quality=92)
        return out

    tmp = Path(path)
    bg_p = tmp.with_suffix(".bg.png")
    build_background(preset, bg_p, width=tw, height=th, seed=seed)

    mist_p = tmp.with_suffix(".mist.png")
    fx_p = tmp.with_suffix(".fx.png")
    build_mist(preset, mist_p, width=tw, height=th, seed=seed)
    build_effect_layer(preset, fx_p, width=tw, height=th, seed=seed)
    img = Image.open(bg_p).convert("RGBA").crop((tw // 3, 0, tw // 3 + tw, th))
    mist = Image.open(mist_p).crop((tw // 2, 0, tw // 2 + tw, th))
    fx = Image.open(fx_p).crop((0, 0, tw, th))
    img = Image.alpha_composite(Image.alpha_composite(img, mist), fx)
    extra = (mist_p, fx_p)

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
    for p in (bg_p, *extra):
        p.unlink(missing_ok=True)
    return out
