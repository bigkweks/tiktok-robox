"""
Photo carousel generator — the viral format.

Produces a 6-slide TikTok photo carousel that replicates the exact format
proven to hit 118.5K views with 23.9% Search traffic:

  Slide 0: Title card — white background, bold text hierarchy, emoji spheres
            "actually good ROBLOX games to play | Part N | {Edition}"
  Slide 1-5: Game slides — Roblox game-page aesthetic (white header with
             game icon + name + creator + maturity tag, full-width game
             thumbnail, score text burned into the bottom of the thumbnail)

Why this works (from the viral post analytics):
  - White title slide pattern-interrupts a dark TikTok feed → stops scroll
  - Game slides look like genuine Roblox app screenshots → instant trust
  - 23.9% traffic came from Search: "roblox games to play with friends"
    because the series title IS the search query
  - "Part N" forces follows from viewers who want Part 2
  - 5 games × 1 slide = max swipe incentive per carousel
  - Casual caption text ("i spent 30+ hours in") feels personal, not branded
"""
from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import structlog
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import get_settings

log = structlog.get_logger(__name__)

W, H = 1080, 1920  # TikTok portrait

EDITIONS = [
    "Friends edition",
    "Hidden Gems",
    "Horror edition",
    "Solo edition",
    "Anime edition",
    "PvP edition",
    "Underrated edition",
    "Hidden Gems vol. 2",
]


@dataclass
class CarouselGame:
    name: str
    creator: str
    score: float
    carousel_caption: str      # short casual line: "GTA in roblox"
    like_ratio: float          # 0.0–1.0
    active_players: int
    thumbnail_url: Optional[str]
    icon_url: Optional[str]
    genre: Optional[str]
    visits: int


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    settings = get_settings()
    font_dir = Path(settings.ASSETS_DIR, "fonts")
    candidates = [
        font_dir / ("bold.ttf" if bold else "regular.ttf"),
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _fetch_image(url: str) -> Optional[Image.Image]:
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None


def _cover_fill(img: Image.Image, w: int, h: int) -> Image.Image:
    ratio = max(w / img.width, h / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - w) // 2, (nh - h) // 2
    return img.crop((x, y, x + w, y + h))


def _draw_text_outlined(
    draw: ImageDraw.Draw,
    text: str,
    x: int, y: int,
    font: ImageFont.ImageFont,
    fill=(255, 255, 255),
    stroke_fill=(0, 0, 0),
    stroke_width: int = 5,
    anchor: str = "la",
) -> None:
    draw.text((x, y), text, font=font, fill=stroke_fill, stroke_width=stroke_width, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _draw_centered(
    draw: ImageDraw.Draw,
    text: str,
    cx: int, cy: int,
    font: ImageFont.ImageFont,
    fill=(0, 0, 0),
    stroke_fill: Optional[tuple] = None,
    stroke_width: int = 0,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = cx - tw // 2, cy - th // 2
    if stroke_fill:
        draw.text((x, y), text, font=font, fill=stroke_fill, stroke_width=stroke_width)
    draw.text((x, y), text, font=font, fill=fill)


def _draw_emoji_sphere(img: Image.Image, cx: int, cy: int, r: int, expression: str = "surprised") -> Image.Image:
    """
    Draw a 3D-looking blue emoji sphere (like the viral post's stickers).
    expression: 'surprised' (O mouth, wide eyes) or 'laugh' (big grin, squint)
    """
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Shadow
    for i in range(6, 0, -1):
        alpha = int(30 * (1 - i / 6))
        d.ellipse([cx - r + i, cy - r + i, cx + r + i, cy + r + i], fill=(0, 0, 0, alpha))

    # Main blue sphere (gradient sim via concentric circles)
    for i in range(r, 0, -2):
        t = i / r
        blue = int(40 + t * 150)
        rb = int(50 + (1 - t) * 120)
        alpha = 255 if i < r else 220
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=(rb, rb + 20, min(255, blue + 80), alpha))

    # Highlight (top-left gloss)
    hl_r = r // 4
    hl_x, hl_y = cx - r // 3, cy - r // 3
    d.ellipse([hl_x - hl_r, hl_y - hl_r, hl_x + hl_r, hl_y + hl_r], fill=(220, 235, 255, 160))

    if expression == "surprised":
        # Wide open eyes
        eye_r = r // 7
        for ex in [cx - r // 3, cx + r // 3]:
            ey = cy - r // 6
            d.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=(255, 255, 255, 240))
            # pupil
            pr = eye_r // 2
            d.ellipse([ex - pr, ey - pr, ex + pr, ey + pr], fill=(20, 20, 20, 255))
        # O-shaped mouth
        m_r = r // 5
        d.ellipse([cx - m_r, cy + r // 5 - m_r, cx + m_r, cy + r // 5 + m_r],
                  fill=(30, 20, 20, 220))
    else:  # laugh / grin
        # Squinting eyes (lines)
        eye_y = cy - r // 5
        for ex in [cx - r // 3, cx + r // 3]:
            d.arc([ex - r // 6, eye_y - r // 10, ex + r // 6, eye_y + r // 10],
                  start=200, end=340, fill=(20, 20, 20, 220), width=6)
        # Big grin
        m_w = r // 2
        m_y = cy + r // 5
        d.arc([cx - m_w, m_y - r // 6, cx + m_w, m_y + r // 6],
              start=0, end=180, fill=(30, 20, 20, 220), width=8)
        # Teeth
        d.chord([cx - m_w + 8, m_y - r // 6 + 4, cx + m_w - 8, m_y + 4],
                start=0, end=180, fill=(255, 255, 255, 220))

    return Image.alpha_composite(img.convert("RGBA"), layer)


def _maturity_color(genre: Optional[str]) -> tuple[int, int, int]:
    g = (genre or "").lower()
    if any(x in g for x in ("horror", "military", "fighting", "fps")):
        return (220, 80, 30)  # orange-red = Moderate
    return (50, 160, 80)  # green = Minimal


def _format_active(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.0f}K"
    return str(n)


class CarouselGenerator:
    def __init__(self):
        self._settings = get_settings()

    def generate(
        self,
        games: list[CarouselGame],
        edition: str = "Friends edition",
        part_number: int = 1,
        output_dir: Optional[Path] = None,
        slug: str = "carousel",
    ) -> list[Path]:
        """
        Generate a 6-slide carousel (title + up to 5 game slides).
        Returns list of image paths in slide order.
        """
        if output_dir is None:
            output_dir = Path(self._settings.OUTPUT_DIR, "carousels", slug)
        output_dir.mkdir(parents=True, exist_ok=True)

        slides: list[Path] = []

        # Slide 0: title card
        title_path = output_dir / "slide_00_title.png"
        if not title_path.exists():
            self._make_title_slide(edition, part_number).save(str(title_path))
        slides.append(title_path)

        # Slides 1-5: one per game
        for i, game in enumerate(games[:5]):
            path = output_dir / f"slide_{i+1:02d}_{game.name[:20].replace(' ', '_')}.png"
            if not path.exists():
                img = self._make_game_slide(game)
                img.save(str(path))
            slides.append(path)
            log.info("carousel.slide_saved", slide=i + 1, game=game.name, path=str(path))

        log.info("carousel.complete", slides=len(slides), edition=edition, part=part_number)
        return slides

    # ── Title slide ───────────────────────────────────────────────────

    def _make_title_slide(self, edition: str, part_number: int) -> Image.Image:
        img = Image.new("RGB", (W, H), (255, 255, 255))

        # Emoji spheres
        img = _draw_emoji_sphere(img, cx=W - 160, cy=200, r=190, expression="surprised")
        img = _draw_emoji_sphere(img, cx=160, cy=H - 240, r=190, expression="laugh")

        draw = ImageDraw.Draw(img)

        font_big = _load_font(230, bold=True)
        font_med = _load_font(112, bold=True)
        font_small = _load_font(82)
        font_ed = _load_font(92, bold=True)

        cy = H // 2 - 160
        _draw_centered(draw, "actually good", W // 2, cy, font_med, fill=(20, 20, 20))
        _draw_centered(draw, "ROBLOX", W // 2, cy + 170, font_big, fill=(15, 15, 15))
        _draw_centered(draw, "games to play", W // 2, cy + 380, font_med, fill=(20, 20, 20))
        _draw_centered(draw, f"part {part_number}", W // 2, cy + 530, font_small, fill=(140, 140, 140))

        # Edition badge
        badge_font = _load_font(78, bold=True)
        badge_text = edition
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        bw = bbox[2] - bbox[0] + 60
        bh = bbox[3] - bbox[1] + 28
        bx = (W - bw) // 2
        by = cy + 610
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=24, fill=(235, 235, 235))
        draw.text((bx + 30, by + 14), badge_text, font=badge_font, fill=(30, 30, 30))

        # "swipe for all games" hint at bottom
        hint_font = _load_font(58)
        _draw_centered(draw, "swipe to see all 5 games →", W // 2, H - 140, hint_font, fill=(180, 180, 180))

        return img

    # ── Game slide ────────────────────────────────────────────────────

    def _make_game_slide(self, game: CarouselGame) -> Image.Image:
        img = Image.new("RGB", (W, H), (250, 250, 252))

        # ── Header: game info ─────────────────────────────────────────
        # White card for header
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, W, 340], fill=(255, 255, 255))

        # Game icon
        icon = self._fetch_icon(game.icon_url, game.name)
        if icon:
            icon_size = 170
            icon_resized = icon.resize((icon_size, icon_size), Image.LANCZOS)
            # Rounded mask
            mask = Image.new("L", (icon_size, icon_size), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, icon_size, icon_size], radius=30, fill=255)
            bg = Image.new("RGB", (icon_size, icon_size), (200, 200, 210))
            bg.paste(icon_resized.convert("RGB"), (0, 0))
            img.paste(bg, (50, 82), mask)

        # Game name (may need wrapping)
        name_font = _load_font(64, bold=True)
        small_name_font = _load_font(52, bold=True)
        creator_font = _load_font(50)
        badge_font = _load_font(42, bold=True)

        name = game.name
        name_x = 250
        # If name too long, use smaller font
        bbox = draw.textbbox((0, 0), name, font=name_font)
        if bbox[2] - bbox[0] > W - name_x - 30:
            name_font_use = small_name_font
        else:
            name_font_use = name_font

        # Truncate name if still too long
        while draw.textbbox((0, 0), name, font=name_font_use)[2] > W - name_x - 20:
            name = name[:-1]
        if name != game.name:
            name = name[:-3] + "..."

        draw.text((name_x, 88), name, font=name_font_use, fill=(10, 10, 10))
        draw.text((name_x, 170), game.creator or "Roblox", font=creator_font, fill=(100, 100, 110))

        # Maturity badge
        mat_color = _maturity_color(game.genre)
        mat_label = "Moderate" if mat_color[0] > 100 else "Minimal"
        mbbox = draw.textbbox((0, 0), f"Maturity: {mat_label}", font=badge_font)
        mw = mbbox[2] - mbbox[0] + 20
        draw.rounded_rectangle([name_x, 232, name_x + mw, 232 + 44], radius=8, fill=(240, 240, 240))
        draw.text((name_x + 10, 235), f"Maturity: {mat_label}", font=badge_font, fill=mat_color)

        # Thin separator
        draw.line([(0, 340), (W, 340)], fill=(220, 220, 225), width=2)

        # ── Thumbnail ─────────────────────────────────────────────────
        thumb_h = 608  # 16:9 at 1080 width
        thumb_top = 342
        thumb = self._fetch_thumbnail(game.thumbnail_url)
        if thumb:
            filled = _cover_fill(thumb.convert("RGB"), W, thumb_h)
            img.paste(filled, (0, thumb_top))
        else:
            # Placeholder gradient
            from src.content.video_assembler import _make_gradient_bg  # local import avoids circular
            ph = _make_gradient_bg((60, 60, 80), (30, 30, 50))
            ph = ph.resize((W, thumb_h), Image.LANCZOS)
            img.paste(ph, (0, thumb_top))

        # ── Score overlay on thumbnail ─────────────────────────────────
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)

        # Semi-transparent bottom scrim on thumbnail for text legibility
        scrim_top = thumb_top + thumb_h - 220
        scrim_bot = thumb_top + thumb_h
        for row in range(scrim_top, scrim_bot):
            t = (row - scrim_top) / (scrim_bot - scrim_top)
            alpha = int(t * 160)
            od.line([(0, row), (W, row)], fill=(0, 0, 0, alpha))

        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Score + caption text
        score_str = f"{game.score:.1f}/10"
        # Remove trailing .0 for round numbers to look more casual
        if score_str.endswith(".0/10"):
            score_str = score_str.replace(".0/10", "/10")

        score_font = _load_font(90, bold=True)
        cap_font = _load_font(76, bold=True)
        caption = game.carousel_caption or ""

        # Line 1: score
        text_y = thumb_top + thumb_h - 190
        _draw_text_outlined(draw, score_str, 44, text_y, score_font,
                            fill=(255, 255, 255), stroke_fill=(0, 0, 0), stroke_width=6)

        # Line 2: caption (may wrap)
        if caption:
            import textwrap
            cap_lines = textwrap.wrap(caption, width=22)[:2]
            for li, line in enumerate(cap_lines):
                _draw_text_outlined(draw, line, 44, text_y + 105 + li * 90, cap_font,
                                    fill=(255, 255, 255), stroke_fill=(0, 0, 0), stroke_width=5)

        # ── Stats row ─────────────────────────────────────────────────
        stats_y = thumb_top + thumb_h + 12
        stats_font = _load_font(54)
        like_pct = f"{game.like_ratio * 100:.0f}%"
        active_str = _format_active(game.active_players)

        draw.rectangle([0, stats_y, W, stats_y + 100], fill=(255, 255, 255))

        # 👍 like% | 👥 active | 🔔 Notify | ⭐ Fav
        col_w = W // 4
        items = [
            (f"👍  {like_pct}", (40, 40, 40)),
            (f"👥  {active_str} active", (40, 40, 40)),
            ("🔔  Notify", (80, 80, 100)),
            ("⭐  Fav", (80, 80, 100)),
        ]
        for ci, (txt, col) in enumerate(items):
            tx = ci * col_w + col_w // 2
            ty = stats_y + 50
            _draw_centered(draw, txt, tx, ty, stats_font, fill=col)

        draw.line([(0, stats_y), (W, stats_y)], fill=(220, 220, 225), width=1)
        draw.line([(0, stats_y + 100), (W, stats_y + 100)], fill=(220, 220, 225), width=1)

        return img

    # ── Asset fetching ────────────────────────────────────────────────

    def _fetch_thumbnail(self, url: Optional[str]) -> Optional[Image.Image]:
        if not url:
            return None
        return _fetch_image(url)

    def _fetch_icon(self, url: Optional[str], name: str) -> Optional[Image.Image]:
        if url:
            img = _fetch_image(url)
            if img:
                return img
        # Fallback: colored square with first letter
        icon = Image.new("RGBA", (170, 170), self._initial_color(name))
        d = ImageDraw.Draw(icon)
        f = _load_font(100, bold=True)
        letter = name[0].upper() if name else "R"
        _draw_centered(d, letter, 85, 85, f, fill=(255, 255, 255))
        return icon

    @staticmethod
    def _initial_color(name: str) -> tuple[int, int, int, int]:
        colors = [
            (108, 99, 255, 255), (255, 101, 132, 255), (0, 180, 130, 255),
            (255, 160, 0, 255), (60, 140, 220, 255), (180, 60, 220, 255),
        ]
        return colors[sum(ord(c) for c in name) % len(colors)]
