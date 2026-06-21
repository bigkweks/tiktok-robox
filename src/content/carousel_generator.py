"""
Photo carousel generator — the viral format.

Replicates the exact 6-slide photo carousel that hit 118.5K views with
23.9% Search traffic. Real Poppins type, real color emoji, and the game's
actual Roblox homepage thumbnail as the hero of every game slide.

  Slide 0: Title card — white background, bold type hierarchy, two big
            expressive emoji stickers (real Noto emoji, not drawn)
  Slide 1-5: Game slides — Roblox game-page aesthetic. White header (icon,
            name, creator, maturity tag), the game's real homepage thumbnail
            full-width, score + casual caption burned into the bottom,
            authentic Roblox stats row.

Why it works (from the post analytics):
  - White title slide pattern-interrupts a dark feed → stops the scroll
  - Game slides look like genuine Roblox app screenshots → instant trust
  - Title text IS the search query → 23.9% of traffic came from Search
  - "Part N" + edition forces follows for the next drop
  - Casual lowercase captions feel like a real player, never a brand
"""
from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import structlog
from PIL import Image, ImageDraw, ImageFilter

from src.config import get_settings
from src.content.fonts import emoji_image, load_font, paste_emoji

log = structlog.get_logger(__name__)

W, H = 1080, 1920  # TikTok portrait

# (edition label, snorkel/theme emoji, [sticker emoji top, sticker emoji bottom])
EDITIONS: list[tuple[str, str, list[str]]] = [
    ("Friends edition", "🤿", ["🥹", "😭"]),
    ("Hidden Gems", "💎", ["😳", "🤩"]),
    ("Horror edition", "😱", ["😨", "💀"]),
    ("Solo edition", "🎮", ["🥹", "🔥"]),
    ("Anime edition", "⚔️", ["😮", "🔥"]),
    ("PvP edition", "🔪", ["😈", "😤"]),
    ("Underrated edition", "🤫", ["🤨", "🤩"]),
    ("Brainrot edition", "🤡", ["😭", "💀"]),
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
    description: str = ""       # real Roblox description (fills the lower card)


def _fetch_image(url: str, retries: int = 2) -> Optional[Image.Image]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=15, headers=headers)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGBA")
        except Exception as exc:
            if attempt == retries:
                log.warning("carousel.image_fetch_failed", url=url, error=str(exc))
            continue
    return None


def _cover_fill(img: Image.Image, w: int, h: int) -> Image.Image:
    ratio = max(w / img.width, h / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - w) // 2, (nh - h) // 2
    return img.crop((x, y, x + w, y + h))


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _centered(draw, text, cx, y, font, fill, stroke=0, stroke_fill=(0, 0, 0)):
    w = _text_w(draw, text, font)
    draw.text((cx - w // 2, y), text, font=font, fill=fill,
              stroke_width=stroke, stroke_fill=stroke_fill)


def _maturity(genre: Optional[str]) -> tuple[str, tuple[int, int, int]]:
    g = (genre or "").lower()
    if any(x in g for x in ("horror", "military", "fighting", "fps")):
        return "Moderate", (224, 122, 36)
    return "Minimal", (45, 156, 78)


def _format_active(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
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
        if output_dir is None:
            output_dir = Path(self._settings.OUTPUT_DIR, "carousels", slug)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve edition meta
        ed_meta = next((e for e in EDITIONS if e[0] == edition), EDITIONS[0])

        slides: list[Path] = []

        title_path = output_dir / "slide_00_title.png"
        self._make_title_slide(ed_meta, part_number).save(str(title_path))
        slides.append(title_path)

        for i, game in enumerate(games[:5]):
            safe = "".join(c for c in game.name[:20] if c.isalnum() or c in " _").replace(" ", "_")
            path = output_dir / f"slide_{i+1:02d}_{safe}.png"
            self._make_game_slide(game).save(str(path))
            slides.append(path)
            log.info("carousel.slide_saved", slide=i + 1, game=game.name)

        log.info("carousel.complete", slides=len(slides), edition=edition, part=part_number)
        return slides

    # ── Title slide ───────────────────────────────────────────────────

    def _make_title_slide(self, ed_meta: tuple[str, str, list[str]], part_number: int) -> Image.Image:
        edition, theme_emoji, stickers = ed_meta
        img = Image.new("RGB", (W, H), (248, 249, 251))
        draw = ImageDraw.Draw(img)

        ink = (17, 17, 19)
        grey = (150, 152, 160)

        # Type stack — Poppins, tight leading like the viral post
        f_pre = load_font("extrabold", 92)
        f_hero = load_font("black", 230)
        f_mid = load_font("extrabold", 98)
        f_part = load_font("semibold", 60)

        block_top = 540
        _centered(draw, "actually good", W // 2, block_top, f_pre, ink)
        _centered(draw, "ROBLOX", W // 2, block_top + 120, f_hero, ink)
        _centered(draw, "games to play", W // 2, block_top + 378, f_mid, ink)

        # "part N" small grey, centered on its own line
        _centered(draw, f"part {part_number}", W // 2, block_top + 508, f_part, grey)

        # Edition pill with theme emoji
        f_ed = load_font("bold", 68)
        ed_text = edition
        ew = _text_w(draw, ed_text, f_ed)
        em_size = 74
        pad = 38
        pill_w = ew + em_size + pad * 2 + 22
        pill_h = 116
        px = (W - pill_w) // 2
        py = block_top + 600
        draw.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=28, fill=(24, 24, 28))
        draw.text((px + pad, py + (pill_h - 70) // 2 - 6), ed_text, font=f_ed, fill=(255, 255, 255))
        em = emoji_image(theme_emoji, em_size)
        if em:
            base = img.convert("RGBA")
            base.alpha_composite(em, (px + pad + ew + 16, py + (pill_h - em_size) // 2))
            img = base.convert("RGB")

        # Big sticker emoji — top-right and bottom-left, slight tilt for life
        img = paste_emoji(img, stickers[0], W - 230, 250, 360, anchor="center", rotate=-12)
        img = paste_emoji(img, stickers[1], 230, H - 320, 360, anchor="center", rotate=10)

        # subtle swipe hint
        draw = ImageDraw.Draw(img)
        f_hint = load_font("medium", 50)
        _centered(draw, "swipe →", W // 2, H - 150, f_hint, (190, 192, 200))

        return img

    # ── Game slide ────────────────────────────────────────────────────

    def _make_game_slide(self, game: CarouselGame) -> Image.Image:
        img = Image.new("RGB", (W, H), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # ── Header ────────────────────────────────────────────────────
        icon = self._fetch_icon(game.icon_url, game.name)
        if icon:
            isz = 168
            icon_r = icon.resize((isz, isz), Image.LANCZOS).convert("RGBA")
            mask = Image.new("L", (isz, isz), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, isz, isz], radius=34, fill=255)
            img.paste(icon_r.convert("RGB"), (48, 80), mask)

        name_x = 250
        f_name = load_font("bold", 62)
        f_name_sm = load_font("bold", 50)
        f_creator = load_font("regular", 46)
        f_badge = load_font("semibold", 40)

        # Fit name
        name = game.name
        f_use = f_name if _text_w(draw, name, f_name) <= W - name_x - 40 else f_name_sm
        while _text_w(draw, name, f_use) > W - name_x - 40 and len(name) > 4:
            name = name[:-1]
        if name != game.name:
            name = name.rstrip() + "…"
        draw.text((name_x, 86), name, font=f_use, fill=(15, 15, 17))
        draw.text((name_x, 162), game.creator or "Roblox", font=f_creator, fill=(120, 122, 130))

        mat_label, mat_color = _maturity(game.genre)
        mtxt = f"Maturity: {mat_label}"
        mw = _text_w(draw, mtxt, f_badge)
        draw.rounded_rectangle([name_x, 224, name_x + mw + 28, 224 + 52], radius=10, fill=(243, 244, 246))
        draw.text((name_x + 14, 232), mtxt, font=f_badge, fill=mat_color)

        # ── Thumbnail — THE HERO ──────────────────────────────────────
        thumb_top = 330
        thumb_h = 700
        thumb = self._fetch_thumbnail(game.thumbnail_url)
        if thumb:
            filled = _cover_fill(thumb.convert("RGB"), W, thumb_h)
        else:
            filled = self._placeholder(thumb_h)
        img.paste(filled, (0, thumb_top))

        # ── Burned-in score + caption (TikTok classic style) ──────────
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        # gradient scrim only across the bottom of the thumbnail
        scrim_h = 300
        s_top = thumb_top + thumb_h - scrim_h
        for r in range(scrim_h):
            a = int((r / scrim_h) ** 1.4 * 175)
            od.line([(0, s_top + r), (W, s_top + r)], fill=(0, 0, 0, a))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        score_str = f"{game.score:.1f}/10".replace(".0/10", "/10")
        f_score = load_font("extrabold", 88)
        f_cap = load_font("bold", 62)

        cap = game.carousel_caption or ""
        cap_lines = textwrap.wrap(cap, width=27)[:2] if cap else []

        # Anchor the whole block so the last caption line clears the stats bar
        block_h = 96 + len(cap_lines) * 74
        y = thumb_top + thumb_h - block_h - 26
        draw.text((48, y), score_str, font=f_score, fill=(255, 255, 255),
                  stroke_width=3, stroke_fill=(0, 0, 0))
        for li, line in enumerate(cap_lines):
            draw.text((48, y + 98 + li * 74), line, font=f_cap, fill=(255, 255, 255),
                      stroke_width=3, stroke_fill=(0, 0, 0))

        # ── Roblox stats row ──────────────────────────────────────────
        sy = thumb_top + thumb_h
        row_h = 110
        draw.rectangle([0, sy, W, sy + row_h], fill=(255, 255, 255))
        draw.line([(0, sy), (W, sy)], fill=(232, 233, 236), width=2)
        draw.line([(0, sy + row_h), (W, sy + row_h)], fill=(232, 233, 236), width=2)

        f_stat = load_font("medium", 48)
        like_pct = f"{game.like_ratio * 100:.0f}%"
        items = [
            ("👍", like_pct, (40, 40, 44)),
            ("👥", f"{_format_active(game.active_players)}", (40, 40, 44)),
            ("🔔", "Notify", (90, 92, 100)),
            ("⭐", "Fav", (90, 92, 100)),
        ]
        col_w = W // 4
        for ci, (emoji_ch, txt, col) in enumerate(items):
            cx = ci * col_w + col_w // 2
            tw = _text_w(draw, txt, f_stat)
            em_sz = 52
            total_w = em_sz + 12 + tw
            start_x = cx - total_w // 2
            em = emoji_image(emoji_ch, em_sz)
            if em:
                base = img.convert("RGBA")
                base.alpha_composite(em, (start_x, sy + (row_h - em_sz) // 2))
                img = base.convert("RGB")
                draw = ImageDraw.Draw(img)
            draw.text((start_x + em_sz + 12, sy + (row_h - 48) // 2 - 4), txt, font=f_stat, fill=col)

        # ── Description block (fills lower card like the viral post) ───
        desc_y = sy + row_h + 36
        f_desc_h = load_font("bold", 48)
        draw.text((48, desc_y), "Description", font=f_desc_h, fill=(20, 20, 22))

        desc = (game.description or "").strip().replace("\n", " ")
        if desc:
            f_desc = load_font("regular", 44)
            wrapped = textwrap.wrap(desc, width=42)[:6]
            for li, line in enumerate(wrapped):
                draw.text((48, desc_y + 78 + li * 60), line, font=f_desc, fill=(95, 97, 105))

        # bottom hairline + active player chip vibe (authentic Roblox footer)
        foot_y = H - 130
        draw.line([(0, foot_y), (W, foot_y)], fill=(238, 239, 242), width=2)
        f_foot = load_font("medium", 40)
        draw.text((48, foot_y + 40), f"{_format_active(game.visits)} visits", font=f_foot, fill=(150, 152, 160))

        return img

    # ── Assets ────────────────────────────────────────────────────────

    def _fetch_thumbnail(self, url: Optional[str]) -> Optional[Image.Image]:
        return _fetch_image(url) if url else None

    def _fetch_icon(self, url: Optional[str], name: str) -> Optional[Image.Image]:
        if url:
            img = _fetch_image(url)
            if img:
                return img
        icon = Image.new("RGBA", (168, 168), self._initial_color(name))
        d = ImageDraw.Draw(icon)
        f = load_font("black", 96)
        letter = (name[0].upper() if name else "R")
        bbox = d.textbbox((0, 0), letter, font=f)
        d.text(((168 - (bbox[2] - bbox[0])) // 2 - bbox[0],
                (168 - (bbox[3] - bbox[1])) // 2 - bbox[1]),
               letter, font=f, fill=(255, 255, 255))
        return icon

    def _placeholder(self, h: int) -> Image.Image:
        ys = list(range(h))
        img = Image.new("RGB", (W, h), (40, 42, 60))
        d = ImageDraw.Draw(img)
        for y in ys:
            t = y / h
            d.line([(0, y), (W, y)], fill=(int(40 + t * 20), int(42 + t * 18), int(60 + t * 30)))
        f = load_font("bold", 60)
        msg = "Roblox"
        bbox = d.textbbox((0, 0), msg, font=f)
        d.text(((W - (bbox[2] - bbox[0])) // 2, h // 2 - 40), msg, font=f, fill=(110, 112, 140))
        return img

    @staticmethod
    def _initial_color(name: str) -> tuple[int, int, int, int]:
        colors = [
            (108, 99, 255, 255), (255, 101, 132, 255), (0, 180, 130, 255),
            (255, 160, 0, 255), (60, 140, 220, 255), (180, 60, 220, 255),
        ]
        return colors[sum(ord(c) for c in name) % len(colors)]
