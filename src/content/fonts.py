"""
Shared font + emoji rendering.

Bundles the Poppins family (assets/fonts) so output looks like real
social content, not a generic system render. Real color emoji come from
Noto Color Emoji (renders at 109px native, upscaled crisply on demand).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src.config import get_settings

# Poppins weight → filename
_POPPINS = {
    "black": "Poppins-Black.ttf",
    "extrabold": "Poppins-ExtraBold.ttf",
    "bold": "Poppins-Bold.ttf",
    "semibold": "Poppins-SemiBold.ttf",
    "medium": "Poppins-Medium.ttf",
    "regular": "Poppins-Regular.ttf",
}

# System fallbacks if the bundled fonts are missing
_FALLBACK = {
    "black": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "extrabold": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "bold": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "semibold": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "medium": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "regular": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
}

_NOTO_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
_EMOJI_NATIVE = 109  # Noto Color Emoji only rasterizes at this pixel size


@lru_cache(maxsize=64)
def load_font(weight: str = "bold", size: int = 48) -> ImageFont.FreeTypeFont:
    """Load a Poppins weight at the given size, falling back to system fonts."""
    weight = weight.lower()
    font_dir = Path(get_settings().ASSETS_DIR, "fonts")
    candidates = [
        font_dir / _POPPINS.get(weight, _POPPINS["bold"]),
        Path(_FALLBACK.get(weight, _FALLBACK["bold"])),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


@lru_cache(maxsize=128)
def emoji_image(char: str, size: int) -> Optional[Image.Image]:
    """
    Render a single emoji to a transparent RGBA image at `size` px.
    Returns None if emoji rendering isn't available.
    """
    if not Path(_NOTO_EMOJI).exists():
        return None
    try:
        font = ImageFont.truetype(_NOTO_EMOJI, _EMOJI_NATIVE)
        tmp = Image.new("RGBA", (_EMOJI_NATIVE + 40, _EMOJI_NATIVE + 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(tmp)
        d.text(
            ((_EMOJI_NATIVE + 40) // 2, (_EMOJI_NATIVE + 40) // 2),
            char, font=font, embedded_color=True, anchor="mm",
        )
        bbox = tmp.getbbox()
        if bbox:
            tmp = tmp.crop(bbox)
        return tmp.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def paste_emoji(canvas: Image.Image, char: str, x: int, y: int, size: int,
                anchor: str = "center", rotate: float = 0.0) -> Image.Image:
    """
    Paste an emoji onto `canvas` (RGB or RGBA). (x, y) is the anchor point.
    anchor: 'center' | 'tl'. Returns the (possibly new) canvas.
    """
    em = emoji_image(char, size)
    if em is None:
        return canvas
    if rotate:
        em = em.rotate(rotate, expand=True, resample=Image.BICUBIC)
    if anchor == "center":
        px, py = x - em.width // 2, y - em.height // 2
    else:
        px, py = x, y
    base = canvas.convert("RGBA")
    base.alpha_composite(em, (px, py))
    return base.convert(canvas.mode)
