"""
Synthetic Roblox-style game scenes for the variant DEMO only.

The sandbox can't reach roblox.com, so we can't fetch real homepage thumbnails
here. These PIL-generated low-poly scenes stand in for them so the layout can be
judged WITH a real raster in place. In production the pipeline passes the real
Roblox thumbnail URL straight into the renderer (Chromium fetches it in the
Codespace) — see carousel_variants.img_to_uri.
"""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vgrad(w, h, top, bot):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        c = _lerp(top, bot, y / h)
        for x in range(w):
            px[x, y] = c
    return img


def _ridge(draw, w, base_y, amp, color, seed, steps=14):
    rng = random.Random(seed)
    pts = [(0, base_y + rng.randint(-amp, amp))]
    for i in range(1, steps + 1):
        x = int(w * i / steps)
        pts.append((x, base_y + rng.randint(-amp, amp)))
    pts += [(w, 1000), (0, 1000)]
    draw.polygon(pts, fill=color)


def game_scene(theme: str, seed: int = 7, w: int = 1280, h: int = 720) -> Image.Image:
    """Return a believable low-poly game scene for the given theme."""
    rng = random.Random(seed)

    if theme == "obby":
        sky_top, sky_bot = (95, 178, 232), (213, 238, 250)
        sun = (255, 247, 222)
        ranges = [((120, 165, 120), 470, 40), ((96, 150, 104), 540, 52),
                  ((74, 132, 88), 610, 60)]
        struct_cols = [(232, 104, 92), (244, 196, 84), (96, 168, 224), (140, 206, 130)]
        night = False
    elif theme == "horror":
        sky_top, sky_bot = (16, 18, 34), (44, 32, 58)
        sun = (196, 206, 232)  # moon
        ranges = [((26, 26, 44), 470, 46), ((18, 18, 34), 545, 56),
                  ((10, 10, 22), 620, 64)]
        struct_cols = [(14, 12, 22), (10, 9, 18), (20, 16, 28)]
        night = True
    else:  # generic adventure dusk
        sky_top, sky_bot = (58, 70, 122), (224, 150, 116)
        sun = (255, 224, 168)
        ranges = [((72, 70, 110), 470, 44), ((52, 52, 88), 545, 54),
                  ((34, 36, 66), 620, 62)]
        struct_cols = [(40, 42, 70), (30, 32, 56), (52, 50, 84)]
        night = False

    img = _vgrad(w, h, sky_top, sky_bot)
    draw = ImageDraw.Draw(img, "RGBA")

    # Celestial body + glow
    sx, sy, sr = int(w * 0.74), int(h * 0.30), 70
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(sr * 4, sr, -6):
        a = int(46 * (1 - (r - sr) / (sr * 3)))
        gd.ellipse([sx - r, sy - r, sx + r, sy + r], fill=sun + (max(a, 0),))
    glow = glow.filter(ImageFilter.GaussianBlur(20))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=sun)

    # Stars for night
    if night:
        for _ in range(90):
            x, y = rng.randint(0, w), rng.randint(0, int(h * 0.55))
            s = rng.choice([1, 1, 2, 2, 3])
            a = rng.randint(80, 200)
            draw.ellipse([x, y, x + s, y + s], fill=(255, 255, 255, a))

    # Mountain ranges (depth)
    for col, by, amp in ranges:
        _ridge(draw, w, by, amp, col, seed + by)

    # Foreground structures (towers / blocks)
    fg_y = 600
    n = rng.randint(4, 6)
    for i in range(n):
        bw = rng.randint(70, 150)
        bh = rng.randint(120, 300)
        bx = int(w * (i + rng.uniform(0.1, 0.7)) / n) - bw // 2
        col = struct_cols[i % len(struct_cols)]
        draw.rectangle([bx, fg_y - bh, bx + bw, fg_y + 140], fill=col)
        # lit windows on dark structures
        if night:
            for wy in range(fg_y - bh + 16, fg_y, 30):
                for wx in range(bx + 12, bx + bw - 12, 26):
                    if rng.random() < 0.35:
                        draw.rectangle([wx, wy, wx + 10, wy + 14],
                                       fill=(255, 206, 120, 230))
        else:
            # subtle top highlight
            draw.rectangle([bx, fg_y - bh, bx + bw, fg_y - bh + 8],
                           fill=(255, 255, 255, 60))

    # Ground
    ground = (54, 92, 60) if not night else (10, 12, 18)
    draw.rectangle([0, fg_y + 110, w, h], fill=ground)

    # Atmospheric haze band
    haze = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(haze)
    hc = (220, 230, 245, 50) if not night else (40, 46, 72, 70)
    hd.rectangle([0, fg_y - 30, w, fg_y + 120], fill=hc)
    haze = haze.filter(ImageFilter.GaussianBlur(30))
    img = Image.alpha_composite(img.convert("RGBA"), haze).convert("RGB")

    # Vignette
    vig = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-w * 0.2, -h * 0.2, w * 1.2, h * 1.2], fill=70)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    img = Image.composite(img, dark, vig.point(lambda p: 60 + p))

    return img


def game_icon(letter: str, accent: tuple[int, int, int], seed: int = 3,
              size: int = 512) -> Image.Image:
    """A rounded Roblox-style game icon: gradient field + emblem letter."""
    base = _lerp(accent, (20, 20, 28), 0.45)
    img = _vgrad(size, size, accent, base)
    draw = ImageDraw.Draw(img, "RGBA")
    # soft corner glow
    draw.ellipse([-size * .3, -size * .3, size * .6, size * .6],
                 fill=_lerp(accent, (255, 255, 255), 0.3) + (90,))
    # emblem letter
    from PIL import ImageFont
    try:
        f = ImageFont.truetype(
            "/home/user/tiktok-robox/assets/fonts/Poppins-Black.ttf", int(size * 0.62))
    except Exception:
        f = ImageFont.load_default()
    bb = draw.textbbox((0, 0), letter, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text(((size - tw) / 2 - bb[0], (size - th) / 2 - bb[1]), letter,
              font=f, fill=(255, 255, 255, 235))
    # rounded mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size],
                                           radius=int(size * 0.22), fill=255)
    out = Image.new("RGB", (size, size), (255, 255, 255))
    out.paste(img, (0, 0), mask)
    return out
