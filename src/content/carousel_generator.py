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
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import structlog
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import get_settings
from src.content.fonts import (
    draw_mixed,
    emoji_image,
    load_font,
    measure_mixed,
    paste_emoji,
    strip_emoji,
)

log = structlog.get_logger(__name__)

W, H = 1080, 1920  # TikTok portrait

# (edition label, theme emoji, [sticker emoji — used as scattered face stickers])
# More stickers per edition = a denser, more expressive title slide. The title
# renderer scatters up to 4 of these around the type to stop the scroll.
EDITIONS: list[tuple[str, str, list[str]]] = [
    ("Friends edition", "🤿", ["🥹", "😭", "🫶", "😂"]),
    ("Hidden Gems", "💎", ["😳", "🤩", "👀", "🤯"]),
    ("Horror edition", "😱", ["😨", "💀", "🫣", "😰"]),
    ("Solo edition", "🎮", ["🥹", "🔥", "😮‍💨", "🫡"]),
    ("Anime edition", "⚔️", ["😮", "🔥", "🥶", "⚡"]),
    ("PvP edition", "🔪", ["😈", "😤", "💢", "🥵"]),
    ("Underrated edition", "🤫", ["🤨", "🤩", "👀", "🧐"]),
    ("Brainrot edition", "🤡", ["😭", "💀", "💀", "😵‍💫"]),
]

# Rotating scroll-stopper kickers shown above the title — these read like a real
# creator hyping the drop and create curiosity/FOMO before the type even lands.
TITLE_KICKERS: list[str] = [
    "you NEED to save these",
    "stop scrolling 🛑",
    "before they blow up",
    "no one is talking about these",
    "save before its gone",
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
    blurb: str = ""            # punchy AI "why it slaps" one-liner (highlighted callout)


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


def _active_label(n: int) -> str:
    """Roblox-style active count, e.g. '82.3K active', '1.2M active', '947 active'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M active"
    if n >= 1000:
        return f"{n / 1000:.1f}K active"
    return f"{n} active"


def _emoji_px(font: ImageFont.FreeTypeFont) -> int:
    """The emoji_size draw_mixed uses for this font, so measuring stays in sync."""
    ascent, descent = font.getmetrics()
    return int((ascent + descent) * 0.92)


def _mono_icon(char: str, size: int, color: tuple[int, int, int]) -> Optional[Image.Image]:
    """
    A single flat monochrome icon: the Noto emoji silhouette recolored to one
    grey. Roblox's stat row uses flat grey glyphs (not the playful color emoji),
    so flattening 👍/👥/🔔/⭐ to grey makes the row read as native Roblox UI.
    """
    em = emoji_image(char, size)
    if em is None:
        return None
    alpha = em.split()[3]
    solid = Image.new("RGBA", em.size, color + (255,))
    return Image.composite(solid, Image.new("RGBA", em.size, (0, 0, 0, 0)), alpha)


def _draw_stat_pills(
    img: Image.Image,
    x0: int,
    y: int,
    pills: list[list[tuple[str, str]]],
    *,
    pill_h: int = 74,
    icon_size: int = 40,
    gap: int = 12,
    pad_x: int = 24,
    pill_gap: int = 14,
    fill: tuple[int, int, int] = (240, 241, 243),
    ink: tuple[int, int, int] = (45, 47, 51),
    icon_col: tuple[int, int, int] = (64, 66, 70),
) -> Image.Image:
    """
    Draw a left-aligned row of Roblox-style grey pills. Each pill is a list of
    ('icon', emoji_char) / ('text', str) tokens, rendered with flat grey icons.
    Returns the (possibly new) image.
    """
    f = load_font("medium", 40)
    draw = ImageDraw.Draw(img)
    x = x0
    for tokens in pills:
        content_w = 0
        for i, (kind, val) in enumerate(tokens):
            content_w += icon_size if kind == "icon" else int(draw.textlength(val, font=f))
            if i < len(tokens) - 1:
                content_w += gap
        pw = content_w + pad_x * 2
        draw.rounded_rectangle([x, y, x + pw, y + pill_h], radius=pill_h // 2, fill=fill)
        cx = x + pad_x
        for kind, val in tokens:
            if kind == "icon":
                ic = _mono_icon(val, icon_size, icon_col)
                if ic is not None:
                    base = img.convert("RGBA")
                    base.alpha_composite(ic, (int(cx), int(y + (pill_h - icon_size) // 2)))
                    img = base.convert("RGB")
                    draw = ImageDraw.Draw(img)
                cx += icon_size + gap
            else:
                draw.text((cx, y + (pill_h - 40) // 2 - 4), val, font=f, fill=ink)
                cx += int(draw.textlength(val, font=f)) + gap
        x += pw + pill_gap
    return img


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
        self._make_title_slide(ed_meta, part_number, count=len(games[:5])).save(str(title_path))
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

    def _make_title_slide(
        self,
        ed_meta: tuple[str, str, list[str]],
        part_number: int,
        count: int = 5,
    ) -> Image.Image:
        edition, theme_emoji, stickers = ed_meta
        # Off-white background — pattern-interrupts the dark TikTok feed and
        # stops the thumb. A faint top-corner brand wash adds depth without
        # killing the bright "screenshot of a real list" feel.
        img = Image.new("RGB", (W, H), (250, 250, 252))

        ink = (15, 15, 18)
        grey = (150, 152, 160)
        BRAND = (124, 111, 255)   # the pipeline purple — pops on white

        # ── Scroll-stopper kicker pill (top) ──────────────────────────────
        # A bold colored chip that reads like a creator caption; rotates per
        # part so the series never looks copy-pasted.
        kicker = TITLE_KICKERS[part_number % len(TITLE_KICKERS)]
        f_kick = load_font("extrabold", 52)
        kdraw = ImageDraw.Draw(img)
        kw = measure_mixed(kdraw, kicker, f_kick, 52)
        kpad = 46
        kpill_w = kw + kpad * 2
        kpill_h = 104
        kx = (W - kpill_w) // 2
        ky = 250
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([kx, ky, kx + kpill_w, ky + kpill_h], radius=52, fill=(18, 18, 22))
        img = draw_mixed(img, (W // 2, ky + kpill_h // 2), kicker, f_kick,
                         (255, 255, 255), emoji_size=52, anchor="mm")
        draw = ImageDraw.Draw(img)

        # Type stack — Poppins, tight leading like the viral post
        f_pre = load_font("extrabold", 92)
        f_hero = load_font("black", 236)
        f_mid = load_font("extrabold", 98)
        f_part = load_font("semibold", 56)

        block_top = 600
        _centered(draw, "actually good", W // 2, block_top, f_pre, ink)

        # "ROBLOX" gets a punchy rounded highlight box behind it (white text on
        # brand fill) — the single biggest pop on the slide, like a marker
        # highlight over the key search phrase.
        hero_txt = "ROBLOX"
        hw = _text_w(draw, hero_txt, f_hero)
        hy = block_top + 116
        box_pad_x, box_pad_top, box_pad_bot = 40, 18, 60
        bx0 = (W - hw) // 2 - box_pad_x
        bx1 = (W + hw) // 2 + box_pad_x
        draw.rounded_rectangle(
            [bx0, hy + box_pad_top, bx1, hy + 236 + box_pad_bot - 60],
            radius=40, fill=BRAND,
        )
        _centered(draw, hero_txt, W // 2, hy, f_hero, (255, 255, 255))

        _centered(draw, "games to play", W // 2, block_top + 400, f_mid, ink)

        # "part N · N games" small grey, centered on its own line
        sub = f"part {part_number}  ·  {count} games"
        _centered(draw, sub, W // 2, block_top + 530, f_part, grey)

        # Edition pill with theme emoji
        f_ed = load_font("bold", 64)
        ed_text = edition
        ew = _text_w(draw, ed_text, f_ed)
        em_size = 70
        pad = 36
        pill_w = ew + em_size + pad * 2 + 22
        pill_h = 110
        px = (W - pill_w) // 2
        py = block_top + 620
        draw.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=28, fill=(24, 24, 28))
        draw.text((px + pad, py + (pill_h - 66) // 2 - 6), ed_text, font=f_ed, fill=(255, 255, 255))
        em = emoji_image(theme_emoji, em_size)
        if em:
            base = img.convert("RGBA")
            base.alpha_composite(em, (px + pad + ew + 16, py + (pill_h - em_size) // 2))
            img = base.convert("RGB")

        # Big sticker emoji scattered around the type — denser + more expressive
        # than the old two-sticker layout, slight tilts for that hand-placed feel.
        placements = [
            (965, 120, 220, -12),       # top-right corner, above the kicker pill
            (150, 505, 235, 12),        # mid-left, beside the ROBLOX box
            (930, 1180, 245, -10),      # right flank, by the edition pill
            (165, 1455, 235, 9),        # lower-left, above the CTA
        ]
        for i, (sx, sy, ssz, rot) in enumerate(placements):
            if i < len(stickers):
                img = paste_emoji(img, stickers[i], sx, sy, ssz, anchor="center", rotate=rot)

        # Bottom CTA — swipe + save, the two actions that drive the algorithm.
        # Real Noto color arrow (➡️) + hand (👇); the plain "→" would tofu.
        f_cta = load_font("extrabold", 58)
        img = draw_mixed(img, (W // 2, H - 175), "swipe ➡️ save the list 👇", f_cta,
                         (28, 28, 32), emoji_size=58, anchor="mm")

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
        f_creator = load_font("regular", 44)
        f_mat = load_font("regular", 40)
        maxw = W - name_x - 40

        # Keep the real Roblox name WITH its color emoji (e.g. "Sell Lemons 👍"),
        # rendered via draw_mixed so the emoji shows in color instead of tofu.
        name = (game.name or "").strip()
        f_use = f_name if measure_mixed(draw, name, f_name, _emoji_px(f_name)) <= maxw else f_name_sm
        truncated = False
        while measure_mixed(draw, name, f_use, _emoji_px(f_use)) > maxw and len(name) > 4:
            name = name[:-1]
            truncated = True
        if truncated:
            name = name.rstrip() + "…"
        img = draw_mixed(img, (name_x, 86), name, f_use, (15, 15, 17),
                         emoji_size=_emoji_px(f_use), anchor="la")
        # Creator + (Roblox-style) plain grey maturity line
        img = draw_mixed(img, (name_x, 166), (game.creator or "Roblox"), f_creator,
                         (120, 122, 130), emoji_size=_emoji_px(f_creator), anchor="la")
        draw = ImageDraw.Draw(img)
        mat_label, _ = _maturity(game.genre)
        draw.text((name_x, 236), f"Maturity: {mat_label}", font=f_mat, fill=(150, 152, 160))

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

        cap = strip_emoji(game.carousel_caption or "")
        cap_lines = textwrap.wrap(cap, width=27)[:2] if cap else []

        # Anchor the whole block so the last caption line clears the stats bar
        block_h = 96 + len(cap_lines) * 74
        y = thumb_top + thumb_h - block_h - 26
        draw.text((48, y), score_str, font=f_score, fill=(255, 255, 255),
                  stroke_width=3, stroke_fill=(0, 0, 0))
        for li, line in enumerate(cap_lines):
            draw.text((48, y + 98 + li * 74), line, font=f_cap, fill=(255, 255, 255),
                      stroke_width=3, stroke_fill=(0, 0, 0))

        # ── Roblox stat pills (the "like / active / notify / favorite" row) ──
        # Matches the real Roblox game-page control bar: left-aligned light-grey
        # pills with flat monochrome glyphs. Like pill shows 👍 % 👎 together.
        sy = thumb_top + thumb_h
        row_h = 110
        like_pct = f"{game.like_ratio * 100:.0f}%"
        pills: list[list[tuple[str, str]]] = [
            [("icon", "👍"), ("text", like_pct), ("icon", "👎")],
            [("icon", "👥"), ("text", _active_label(game.active_players))],
            [("icon", "🔔"), ("text", "Notify")],
            [("icon", "⭐")],
        ]
        img = _draw_stat_pills(img, 40, sy + 18, pills)
        draw = ImageDraw.Draw(img)

        # ── "Why it slaps" highlight callout (AI verdict) ─────────────
        # A punchy creator pull-quote in an accent card. Sits above the real
        # Roblox description so the slide reads hyped AND authentic.
        blurb = strip_emoji((game.blurb or "").strip())
        desc_lines_max = 5
        cy = sy + row_h + 32
        if blurb:
            f_blurb = load_font("bold", 50)
            blurb_lines = textwrap.wrap(blurb, width=30)[:3]
            pad = 30
            line_h = 62
            box_h = pad + len(blurb_lines) * line_h + pad - 12
            draw.rounded_rectangle([40, cy, W - 40, cy + box_h], radius=24, fill=(244, 242, 255))
            draw.rounded_rectangle([40, cy, 54, cy + box_h], radius=6, fill=(124, 111, 255))
            ty = cy + pad - 6
            for li, line in enumerate(blurb_lines):
                text = ("🔥 " + line) if li == 0 else line
                img = draw_mixed(img, (76, ty + li * line_h), text, f_blurb,
                                 (30, 26, 52), emoji_size=46, anchor="la")
            draw = ImageDraw.Draw(img)
            desc_y = cy + box_h + 34
            desc_lines_max = 3   # leave room for the callout
        else:
            desc_y = cy

        # ── Description block (real Roblox copy → authentic game-page feel) ──
        f_desc_h = load_font("bold", 48)
        draw.text((48, desc_y), "Description", font=f_desc_h, fill=(20, 20, 22))

        # Keep the real description's color emoji (🍋 💵 🤑 …) like the live
        # Roblox page — render each wrapped line through draw_mixed.
        desc = re.sub(r"\s{2,}", " ", (game.description or "").strip().replace("\n", " "))
        if desc:
            f_desc = load_font("regular", 44)
            es = _emoji_px(f_desc)
            wrapped = textwrap.wrap(desc, width=38)[:desc_lines_max]
            for li, line in enumerate(wrapped):
                img = draw_mixed(img, (48, desc_y + 78 + li * 60), line, f_desc,
                                 (95, 97, 105), emoji_size=es, anchor="la")
            draw = ImageDraw.Draw(img)

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
