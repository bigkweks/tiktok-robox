"""
Shared font + emoji rendering.

Bundles the Poppins family (assets/fonts) so output looks like real
social content, not a generic system render. Real color emoji come from
Noto Color Emoji (renders at 109px native, upscaled crisply on demand).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from src.config import get_settings

# A single emoji "cluster": a pictographic base codepoint, plus any trailing
# variation selectors / skin-tone modifiers, plus any ZWJ-joined continuations
# (e.g. ⚔️ = U+2694 U+FE0F, 👁️ = U+1F441 U+FE0F, family/profession ZWJ runs).
#
# Deliberately scoped to the pictographic blocks that the Poppins/Liberation
# text fonts CANNOT render (those show as tofu). Plain text arrows like
# "→" (U+2192) are excluded so they keep rendering with the text font.
_EMOJI_CORE = (
    r"[\U0001F000-\U0001FAFF"   # SMP emoji (faces, objects, symbols)
    r"\U00002600-\U000026FF"    # Miscellaneous Symbols (⚔ ⭐-adjacent, ⚠ …)
    r"\U00002700-\U000027BF"    # Dingbats (✅ ✂ …)
    r"\U00002B00-\U00002BFF"    # ⭐ (U+2B50), arrows-in-box, stars
    r"\U0001F1E6-\U0001F1FF]"   # regional indicators (flags)
)
_EMOJI_MODS = "[️\U0001F3FB-\U0001F3FF]*"  # variation selector + skin tones
EMOJI_PATTERN = re.compile(
    _EMOJI_CORE + _EMOJI_MODS + "(?:‍" + _EMOJI_CORE + _EMOJI_MODS + ")*"
)

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

_NOTO_EMOJI_CANDIDATES = [
    # Bundled in repo (works everywhere including Render)
    str(Path(get_settings().ASSETS_DIR, "fonts", "NotoColorEmoji.ttf")),
    # System install (local dev after apt-get install fonts-noto-color-emoji)
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
]
_NOTO_EMOJI = next((p for p in _NOTO_EMOJI_CANDIDATES if Path(p).exists()), "")
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
    if not _NOTO_EMOJI:
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


# ── Mixed text + emoji rendering ──────────────────────────────────────────
# The text fonts (Poppins/Liberation) have no emoji glyphs, so drawing a string
# that contains emoji with a single draw.text() call renders the emoji as tofu
# (□). These helpers split a string into text runs and emoji runs, draw the text
# with the font and composite real color emoji from Noto in their place.


def contains_emoji(text: str) -> bool:
    """True if the string contains at least one renderable emoji cluster."""
    return bool(text) and EMOJI_PATTERN.search(text) is not None


def strip_emoji(text: str) -> str:
    """Remove emoji clusters from a string and tidy the leftover whitespace."""
    if not text:
        return text
    cleaned = EMOJI_PATTERN.sub("", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _segment(text: str) -> list[tuple[bool, str]]:
    """Split into ordered (is_emoji, chunk) runs."""
    segments: list[tuple[bool, str]] = []
    last = 0
    for m in EMOJI_PATTERN.finditer(text):
        if m.start() > last:
            segments.append((False, text[last:m.start()]))
        segments.append((True, m.group()))
        last = m.end()
    if last < len(text):
        segments.append((False, text[last:]))
    return segments


def measure_mixed(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                  emoji_size: int) -> int:
    """Total pixel width of a mixed text+emoji string when drawn with draw_mixed."""
    width = 0
    for is_emoji, chunk in _segment(text):
        if is_emoji:
            width += emoji_size
        else:
            width += int(draw.textlength(chunk, font=font))
    return width


def draw_mixed(img: Image.Image, xy: tuple[int, int], text: str,
               font: ImageFont.FreeTypeFont, fill, *, emoji_size: Optional[int] = None,
               anchor: str = "la", shadow_offset: int = 0,
               shadow_fill=(0, 0, 0, 160)) -> Image.Image:
    """
    Draw a string that may contain emoji, left-anchored at top-left `xy`
    (anchor "la"); use anchor "mm" to center on `xy`. Text runs are drawn with
    `font`; emoji runs are composited as real color glyphs. Returns the image
    (RGBA work is internal; the returned image keeps the input mode).
    """
    if not text:
        return img
    mode = img.mode
    base = img.convert("RGBA")
    draw = ImageDraw.Draw(base)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    if emoji_size is None:
        emoji_size = int(line_h * 0.92)

    total_w = measure_mixed(draw, text, font, emoji_size)
    x, y = xy
    if "m" in anchor:  # horizontal middle
        x -= total_w // 2
    if anchor.endswith("m"):  # vertical middle
        y -= line_h // 2

    cursor = x
    for is_emoji, chunk in _segment(text):
        if is_emoji:
            em = emoji_image(chunk, emoji_size)
            if em is not None:
                ey = y + (line_h - emoji_size) // 2
                base.alpha_composite(em, (int(cursor), int(ey)))
            cursor += emoji_size
        else:
            if shadow_offset:
                draw.text((cursor + shadow_offset, y + shadow_offset), chunk,
                          font=font, fill=shadow_fill)
            draw.text((cursor, y), chunk, font=font, fill=fill)
            cursor += int(draw.textlength(chunk, font=font))

    return base.convert(mode)
