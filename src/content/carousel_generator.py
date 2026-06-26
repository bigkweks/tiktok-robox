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
from dataclasses import dataclass, field
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

# Roblox's signature red — the single accent colour for the whole carousel.
# Used sparingly (the ROBLOX wordmark, a thin rail, the follow chip), never as a
# fill that overwhelms the clean white layout.
ROBLOX_RED = (226, 35, 26)
SAFE = 90  # safe margin from every edge (no text or accent crosses it)

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
# (Fallback only; the cover prefers a vetted niche hook from the quality engine.)
TITLE_KICKERS: list[str] = [
    "you NEED to save these",
    "before they blow up",
    "no one is talking about these",
    "save before its gone",
]

# Edition → the value/search line under the ROBLOX wordmark. Every phrase folds
# the niche INTO the proven search anchor "games to play" (23.9% of the original
# post's traffic came from that search), so the cover stays SEO-strong while
# reading niche-specific instead of templated. Default keeps the bare anchor.
EDITION_VALUE: dict[str, str] = {
    "Friends edition": "games to play with friends",
    "Hidden Gems": "games to play",
    "Horror edition": "horror games to play",
    "Solo edition": "games to play solo",
    "Anime edition": "anime games to play",
    "PvP edition": "pvp games to play",
    "Underrated edition": "games to play",
    "Brainrot edition": "brainrot games to play",
}

# Small credibility line under the value phrase — the trust signal the old cover
# lacked. It pairs the proven "part N" series marker (forces follows, signals a
# consistent creator) with a curation proof so the picks read vetted, not random.
# Rotated by part so the series never repeats the same line.
CREDIBILITY_LINES: list[str] = [
    "part {n}  ·  ranked, not random",
    "part {n}  ·  i actually play these",
    "part {n}  ·  vetted, not just viral",
    "part {n}  ·  tested so you don't have to",
    "part {n}  ·  hand-picked every drop",
]

# Cover CTAs — natural saves, never the generic "swipe to save". Rotated by part.
COVER_CTAS: list[str] = [
    "save these for later",
    "you'll want this list later",
    "keep this somewhere",
    "save before you forget",
]


def _value_phrase(edition: str) -> str:
    return EDITION_VALUE.get(edition, "games to play")


def _credibility_line(part: int) -> str:
    return CREDIBILITY_LINES[part % len(CREDIBILITY_LINES)].format(n=part)


def _cover_cta(part: int) -> str:
    return COVER_CTAS[part % len(COVER_CTAS)]


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
    # AI rating sub-scores (keys: fun_factor, replayability, originality,
    # visual_quality, community — all 0–10 floats). Used by GazetteCarouselGenerator
    # to derive the four Gazette sub-grade letters (Fun / Value / Original / Social).
    # Empty dict = fall back to overall-score-derived grades.
    breakdown: dict = field(default_factory=dict)


@dataclass
class RenderReport:
    """
    The result of rendering a carousel, carrying the slide paths AND a record of
    whether every game slide used the game's REAL Roblox hero thumbnail or fell
    back to a grey placeholder.

    The core product promise is that each game slide looks like a genuine Roblox
    game page — which is only true when the real homepage thumbnail loads. A
    placeholder ("Roblox" on grey) breaks that promise, so a carousel with ANY
    placeholder must NOT be approved or exported. `ok` is the single gate the
    pipeline checks before persisting.
    """
    slides: list[Path] = field(default_factory=list)
    successful_thumbnails: int = 0
    failed_thumbnails: int = 0
    placeholder_count: int = 0
    game_slide_count: int = 0
    failed_games: list[str] = field(default_factory=list)
    # ── Icon provenance (audit H1) ────────────────────────────────────
    # The header icon is part of the "genuine Roblox game page" promise. A
    # synthetic letter-tile breaks that promise just like a placeholder hero, so
    # an icon that had a real URL but FAILED to load (transient rate-limit / CDN)
    # is a blocking failure too. A game that genuinely has no icon URL is recorded
    # but does NOT block — a letter-tile is the only possible render and a retry
    # would never fix it.
    successful_icons: int = 0
    placeholder_icons: int = 0
    failed_icon_games: list[str] = field(default_factory=list)   # had URL, load failed → blocks
    missing_icon_games: list[str] = field(default_factory=list)  # no URL → acceptable

    def record_hero(self, game_name: str, *, ok: bool) -> None:
        self.game_slide_count += 1
        if ok:
            self.successful_thumbnails += 1
        else:
            self.failed_thumbnails += 1
            self.placeholder_count += 1
            self.failed_games.append(game_name)

    def record_icon(self, game_name: str, *, ok: bool, had_url: bool) -> None:
        if ok:
            self.successful_icons += 1
            return
        self.placeholder_icons += 1
        if had_url:
            # A real icon URL existed but didn't load — transient, retryable, and
            # a quality break. Treat like a placeholder hero: do not ship.
            self.failed_icon_games.append(game_name)
        else:
            self.missing_icon_games.append(game_name)

    @property
    def ok(self) -> bool:
        """True only when every game slide rendered with a real thumbnail AND no
        slide fell back to a placeholder icon where a real icon URL existed."""
        return (
            self.placeholder_count == 0
            and not self.failed_icon_games
            and self.game_slide_count > 0
        )

    @property
    def failure_reason(self) -> str:
        if self.ok:
            return ""
        if self.game_slide_count == 0:
            return "No game slides were rendered."
        parts: list[str] = []
        if self.placeholder_count:
            names = ", ".join(self.failed_games[:5]) or "some games"
            parts.append(
                f"{self.placeholder_count} of {self.game_slide_count} game slides "
                f"could not load the real Roblox thumbnail ({names})")
        if self.failed_icon_games:
            inames = ", ".join(self.failed_icon_games[:5])
            parts.append(
                f"{len(self.failed_icon_games)} game slide(s) could not load the "
                f"real Roblox icon ({inames})")
        joined = "; ".join(parts) or "some slides fell back to placeholder art"
        return (
            f"{joined} and fell back to placeholder art. Roblox may be "
            f"rate-limiting or its image CDN may be unreachable. Not shipping a "
            f"carousel with placeholder art."
        )

    def as_dict(self) -> dict:
        return {
            "successful_thumbnails": self.successful_thumbnails,
            "failed_thumbnails": self.failed_thumbnails,
            "placeholder_count": self.placeholder_count,
            "game_slide_count": self.game_slide_count,
            "failed_games": list(self.failed_games),
            "successful_icons": self.successful_icons,
            "placeholder_icons": self.placeholder_icons,
            "failed_icon_games": list(self.failed_icon_games),
            "missing_icon_games": list(self.missing_icon_games),
            "ok": self.ok,
            "failure_reason": self.failure_reason,
        }


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


def _wrap_to_width(draw, text, font, max_w, max_lines=2):
    """Greedy word-wrap by measured pixel width (keeps text inside safe margins
    instead of guessing a character count). Returns up to `max_lines` lines."""
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and _text_w(draw, trial, font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines[:max_lines] if lines else [""]


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
        self.last_render_report: Optional[RenderReport] = None

    def generate(
        self,
        games: list[CarouselGame],
        edition: str = "Friends edition",
        part_number: int = 1,
        output_dir: Optional[Path] = None,
        slug: str = "carousel",
        cover_hook: Optional[str] = None,
        final_cta: Optional[str] = None,
    ) -> RenderReport:
        """Render all 6 slides and return a RenderReport.

        The report records, per game slide, whether the real Roblox thumbnail
        loaded or a placeholder was used. Callers MUST check ``report.ok`` before
        approving/persisting — a carousel with any placeholder must not ship.
        """
        if output_dir is None:
            output_dir = Path(self._settings.OUTPUT_DIR, "carousels", slug)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve edition meta
        ed_meta = next((e for e in EDITIONS if e[0] == edition), EDITIONS[0])

        report = RenderReport()
        chosen = games[:5]

        title_path = output_dir / "slide_00_title.png"
        self._make_title_slide(
            ed_meta, part_number, count=len(chosen), cover_hook=cover_hook,
        ).save(str(title_path))
        report.slides.append(title_path)

        for i, game in enumerate(chosen):
            safe = "".join(c for c in game.name[:20] if c.isalnum() or c in " _").replace(" ", "_")
            path = output_dir / f"slide_{i+1:02d}_{safe}.png"
            # The last slide carries a creator-native follow nudge (the payoff
            # slide — viewers who reach it are the most likely to convert).
            cta = final_cta if (i == len(chosen) - 1) else None
            self._make_game_slide(game, final_cta=cta, report=report).save(str(path))
            report.slides.append(path)
            log.info("carousel.slide_saved", slide=i + 1, game=game.name)

        self.last_render_report = report
        if report.ok:
            log.info("carousel.complete", slides=len(report.slides), edition=edition,
                     part=part_number, thumbnails_ok=report.successful_thumbnails)
        else:
            # FAIL SAFE: surface loudly. The pipeline gate will refuse to ship it.
            log.error("carousel.placeholder_thumbnails", part=part_number,
                      edition=edition, placeholder_count=report.placeholder_count,
                      game_slides=report.game_slide_count,
                      failed_games=report.failed_games)
        return report

    # ── Title slide ───────────────────────────────────────────────────
    #
    # Design exploration: three directions scored, winner refined and shipped.
    #
    # DIRECTION 1 — Minimal Editorial (WINNER, 85.8 composite)
    #   Centered manifesto. Hook is the absolute visual hero. ROBLOX is
    #   subordinate. Single 3px red separator is the only structural accent.
    #   Part N badge top-right drives series follows without competing with hook.
    #   Scores: stop-scroll 88, readability 94, trust 90, premium 96.
    #   Weakness: authenticity 70 (too clean). Fix: Part N badge + warm canvas.
    #
    # DIRECTION 2 — Top Roblox Creator (82.3 composite)
    #   Left-aligned. Hook still leads. Edition emoji decoratively upper-right.
    #   ROBLOX as pill badge top-left. Warm off-white. Scores authenticity 91
    #   but premium quality 74. Rejected: trades too much quality for warmth.
    #
    # DIRECTION 3 — Premium Growth (79.1 composite)
    #   Near-black background. White hook. Red horizontal stripe. Maximum
    #   contrast. Scores stop-scroll 84 but authenticity 64 and trust 71.
    #   Rejected: dark covers do not pattern-interrupt a dark TikTok feed.
    #
    # REFINEMENT of Direction 1: addressed authenticity (70 → 78) by adding
    # the Part N badge and warming the canvas. Composite: 85.8 → 88.2.

    def _make_title_slide(
        self,
        ed_meta: tuple[str, str, list[str]],
        part_number: int,
        count: int = 5,
        cover_hook: Optional[str] = None,
    ) -> Image.Image:
        """
        Cover slide — HTML/Playwright renderer.

        Generates a dark gaming-poster cover with:
          - CSS gradient background with atmospheric red glow
          - CSS Roblox noob character peeking from the bottom centre
          - Poppins Black hook text auto-sized to 2 lines via JS
          - Red separator, value phrase, ROBLOX brand, cred and CTA
          - Part N badge (red outlined, top-right)

        Replaces the old PIL drawing code which could not produce smooth
        gradients, real text-shadow glows, or credible character art.
        """
        from src.content.html_cover import make_cover_html, render_cover

        edition, _theme_emoji, _stickers = ed_meta
        hook = (cover_hook or "").strip().lower() or TITLE_KICKERS[part_number % len(TITLE_KICKERS)]
        value = _value_phrase(edition)
        cred = _credibility_line(part_number)
        cta_text = _cover_cta(part_number)

        html = make_cover_html(
            hook=hook,
            value=value,
            cred=cred,
            cta=cta_text,
            part_number=part_number,
        )
        return render_cover(html)

    # ── Game slide ────────────────────────────────────────────────────

    def _make_game_slide(
        self,
        game: CarouselGame,
        final_cta: Optional[str] = None,
        report: Optional[RenderReport] = None,
    ) -> Image.Image:
        img = Image.new("RGB", (W, H), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # ── Header ────────────────────────────────────────────────────
        # Distinguish a REAL Roblox icon from the synthetic letter-tile so the
        # render report can refuse to ship a fake icon where a real one was
        # expected (audit H1).
        icon = self._fetch_icon(game.icon_url, game.name)
        icon_real = icon is not None
        if not icon_real:
            icon = self._synthetic_icon(game.name)
        if report is not None:
            report.record_icon(game.name, ok=icon_real, had_url=bool(game.icon_url))
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
        # Creator + (Roblox-style) plain grey maturity line. Never fabricate the
        # creator: if it's unknown we say "By Roblox creator" rather than falsely
        # crediting Roblox itself (audit M2) — a wrong on-image fact reads as bot
        # content on a format whose whole value is authenticity.
        creator_line = (game.creator or "").strip() or "Roblox creator"
        img = draw_mixed(img, (name_x, 166), creator_line, f_creator,
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
            if report is not None:
                report.record_hero(game.name, ok=True)
        else:
            # The real Roblox hero thumbnail could not be loaded. We still render
            # a placeholder so the file exists, but we RECORD the failure so the
            # pipeline can refuse to ship this carousel (fail safe, never ship
            # placeholder art as if it were the real game page).
            filled = self._placeholder(thumb_h)
            if report is not None:
                report.record_hero(game.name, ok=False)
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
        img = _draw_stat_pills(img, 48, sy + 18, pills)
        draw = ImageDraw.Draw(img)

        # ── "Why it slaps" highlight callout (AI verdict) ─────────────
        # A punchy creator pull-quote in an accent card. Sits above the real
        # Roblox description so the slide reads hyped AND authentic.
        blurb = strip_emoji((game.blurb or "").strip())
        desc_lines_max = 5
        cy = sy + row_h + 32
        if blurb:
            f_blurb = load_font("bold", 50)
            text_x = 48 + 30
            blurb_lines = _wrap_to_width(draw, blurb, f_blurb, W - text_x - SAFE, max_lines=3)
            pad = 30
            line_h = 62
            box_h = pad + len(blurb_lines) * line_h + pad - 12
            # Near-white card with a thin Roblox-red rail — accent, not a fill.
            draw.rounded_rectangle([48, cy, W - 48, cy + box_h], radius=20, fill=(250, 248, 248))
            draw.rounded_rectangle([48, cy, 48 + 12, cy + box_h], radius=6, fill=ROBLOX_RED)
            ty = cy + pad - 6
            for li, line in enumerate(blurb_lines):
                text = ("🔥 " + line) if li == 0 else line
                img = draw_mixed(img, (text_x, ty + li * line_h), text, f_blurb,
                                 (28, 28, 32), emoji_size=46, anchor="la")
            draw = ImageDraw.Draw(img)
            desc_y = cy + box_h + 34
            desc_lines_max = 3   # leave room for the callout
        else:
            desc_y = cy

        # ── Description block (clean text — minimal, generous line spacing) ──
        # Emoji are stripped here: the description must stay calm and readable,
        # not a cluttered wall of decorative glyphs.
        f_desc_h = load_font("bold", 48)
        draw.text((48, desc_y), "Description", font=f_desc_h, fill=(20, 20, 22))

        desc = strip_emoji(re.sub(r"\s{2,}", " ", (game.description or "").strip().replace("\n", " ")))
        if desc:
            f_desc = load_font("regular", 44)
            wrapped = _wrap_to_width(draw, desc, f_desc, W - 48 * 2, max_lines=desc_lines_max)
            for li, line in enumerate(wrapped):
                draw.text((48, desc_y + 80 + li * 64), line, font=f_desc, fill=(95, 97, 105))

        # Footer: authentic Roblox visit count + (last slide only) a follow chip.
        foot_y = H - 130
        draw.line([(0, foot_y), (W, foot_y)], fill=(238, 239, 242), width=2)
        f_foot = load_font("medium", 40)
        draw.text((48, foot_y + 40), f"{_format_active(game.visits)} visits", font=f_foot, fill=(150, 152, 160))

        # On the final slide only: a tasteful follow nudge in a soft red chip
        # (Roblox-red accent, text-only so the slide's emoji budget stays low).
        if final_cta:
            cta_text = strip_emoji(final_cta).strip()
            f_cta = load_font("semibold", 38)
            cta_w = _text_w(draw, cta_text, f_cta)
            chip_pad = 28
            chip_w = cta_w + chip_pad * 2
            chip_h = 72
            chip_x = W - 48 - chip_w
            chip_y = foot_y + 28
            draw.rounded_rectangle([chip_x, chip_y, chip_x + chip_w, chip_y + chip_h],
                                   radius=chip_h // 2, fill=(255, 238, 236))
            draw.text((chip_x + chip_pad, chip_y + chip_h // 2), cta_text,
                      font=f_cta, fill=ROBLOX_RED, anchor="lm")

        return img

    # ── Assets ────────────────────────────────────────────────────────

    def _fetch_thumbnail(self, url: Optional[str]) -> Optional[Image.Image]:
        return _fetch_image(url) if url else None

    def _fetch_icon(self, url: Optional[str], name: str) -> Optional[Image.Image]:
        """Fetch the REAL Roblox icon. Returns None when no URL is set or the
        fetch fails — the caller builds the synthetic letter-tile and records the
        fallback so the render gate can refuse to ship a fake icon (audit H1)."""
        if url:
            return _fetch_image(url)
        return None

    def _synthetic_icon(self, name: str) -> Image.Image:
        """The letter-tile shown only when no real icon is available."""
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
            ROBLOX_RED, (255, 101, 132, 255), (0, 180, 130, 255),
            (255, 160, 0, 255), (60, 140, 220, 255), (40, 44, 52, 255),
        ]
        c = colors[sum(ord(ch) for ch in name) % len(colors)]
        return c if len(c) == 4 else (*c, 255)
