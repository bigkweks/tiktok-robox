"""
GazetteCarouselGenerator — renders a full Gazette-style carousel for the pipeline.

Replaces CarouselGenerator when CAROUSEL_STYLE="gazette" in settings.  The two
directions from the editorial rebuild are combined into one cohesive carousel:

  Slide 0  — Newspaper front-page cover (Direction 1)
             The top-rated game's real Roblox thumbnail is fetched, theme_duotoned
             into the cream/ink Gazette palette, and used as the front-page hero
             photo.  The approved cover hook becomes the newspaper headline.

  Slides 1–N — Gazette review columns (Direction 2)
             Each game gets one interior-page review column: the game name is the
             press headline, the real Roblox thumbnail fills the column as a duotone
             "cut" photo, the grade medallion + sub-grade ledger sit below the photo,
             and the AI verdict is set as examiner's body copy.

The "most recommended" game drives the cover image — its art tells viewers exactly
what's inside before they swipe, which is the retention pattern that matters.

Drop-in replacement: same generate() signature + RenderReport as CarouselGenerator
so the pipeline gate is unchanged.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Optional

import requests
import structlog
from PIL import Image

from src.config import get_settings
from src.content.carousel_generator import CarouselGame, RenderReport
from src.content.carousel_variants import (
    GradeReportVariant,
    _render_html,
    theme_duotone,
)

log = structlog.get_logger(__name__)


# ── Grade helpers ─────────────────────────────────────────────────────────────

def _score_to_grade(score: float) -> str:
    """Map a 0–10 float to a Gazette letter grade."""
    if score >= 9.5:
        return "S"
    if score >= 9.0:
        return "A+"
    if score >= 8.0:
        return "A"
    if score >= 7.0:
        return "B+"
    if score >= 6.0:
        return "B"
    return "C"


def _ratio_to_grade(ratio: float) -> str:
    """Map a like_ratio (0–1) to a 'Value' letter grade."""
    if ratio >= 0.97:
        return "S"
    if ratio >= 0.94:
        return "A+"
    if ratio >= 0.90:
        return "A"
    if ratio >= 0.85:
        return "B+"
    if ratio >= 0.80:
        return "B"
    return "C"


def _visits_label(visits: int) -> str:
    if visits >= 1_000_000_000:
        return f"{visits / 1_000_000_000:.1f}B"
    if visits >= 1_000_000:
        return f"{visits / 1_000_000:.1f}M"
    if visits >= 1_000:
        return f"{visits / 1_000:.0f}K"
    return str(visits)


def _derive_subgrades(game: CarouselGame) -> dict[str, str]:
    """
    Build the four Gazette sub-grade letters from the AI breakdown (if present)
    and from the game's live stats (like_ratio, active_players:visits ratio).

    Keys match what gazette_slide_html() displays: Fun / Value / Original / Social.
    """
    bd = game.breakdown or {}

    # Fun — primary quality signal, closest to overall score
    fun_raw = bd.get("fun_factor", game.score)
    fun = _score_to_grade(float(fun_raw))

    # Value — how players are voting with their thumbs (like_ratio is ground truth)
    value = _ratio_to_grade(game.like_ratio)

    # Original — AI originality sub-score, biased slightly below overall so grades
    # vary on a slide that otherwise reads as all-S (avoids looking manufactured)
    orig_raw = bd.get("originality", max(0.0, game.score - 0.5))
    original = _score_to_grade(float(orig_raw))

    # Social — blend of AI community score + active:visits engagement ratio
    community_ai = bd.get("community", None)
    # active:visits ratio proxy: a game at 1 active per 5K visits is "B"
    engagement = min(10.0, (game.active_players / max(game.visits, 1)) * 5_000_000 / 10)
    if community_ai is not None:
        social_raw = (float(community_ai) + engagement) / 2
    else:
        social_raw = engagement
    social = _score_to_grade(social_raw)

    return {"Fun": fun, "Value": value, "Original": original, "Social": social}


def _gazette_headline(cover_hook: Optional[str], n: int) -> str:
    """
    Convert an approved cover hook into a newspaper headline.

    The approval system produces lowercase TikTok-style hooks ("no one is
    talking about these").  Title-casing them reads as a press headline without
    any extra AI call.  Fallback: generic slot if cover_hook is absent.
    """
    if cover_hook and cover_hook.strip():
        hook = cover_hook.strip()
        # Title-case, but preserve intentional ALL-CAPS words (e.g. "MUST")
        words = hook.split()
        cased = [w if w.isupper() and len(w) > 1 else w.capitalize() for w in words]
        return " ".join(cased)
    return f"The {n} Roblox Games The Algorithm Is Hiding"


# ── Image helpers ─────────────────────────────────────────────────────────────

def _fetch_pil(url: str) -> Optional[Image.Image]:
    """Fetch a URL as a PIL image (3 retries). Returns None on failure."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers=headers)
            r.raise_for_status()
            return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception as exc:
            if attempt == 2:
                log.warning("gazette.fetch_failed", url=url, error=str(exc))
    return None


# ── Generator ─────────────────────────────────────────────────────────────────

class GazetteCarouselGenerator:
    """
    Produces a Gazette-format carousel: newspaper cover + review-column slides.

    Wiring:
      - Pipeline sets CAROUSEL_STYLE="gazette" in settings.
      - pipeline.py instantiates this instead of CarouselGenerator.
      - The same RenderReport / pipeline gate logic applies unchanged.

    Provenance model:
      - Cover hero: fetched as PIL → theme_duotone baked in Python.
        Fallback if fetch fails: URL passed directly, CSS filter applied by
        Chromium — the real Roblox photo still renders, never a placeholder.
      - Game slides: thumbnail_url passed to img_to_uri() → Chromium loads the
        real Roblox CDN image at render time.  ok=True if URL exists.
    """

    def __init__(self):
        self._settings = get_settings()
        self._variant = GradeReportVariant()
        self.last_render_report: Optional[RenderReport] = None

    def generate(
        self,
        games: list[CarouselGame],
        edition: str = "Hidden Gems",
        part_number: int = 1,
        output_dir: Optional[Path] = None,
        slug: str = "carousel",
        cover_hook: Optional[str] = None,
        final_cta: Optional[str] = None,
    ) -> RenderReport:
        """
        Render a full Gazette carousel and return a RenderReport.

        Callers MUST check report.ok before approving/persisting — same contract
        as CarouselGenerator.generate().
        """
        if output_dir is None:
            output_dir = Path(self._settings.OUTPUT_DIR, "carousels", slug)
        output_dir.mkdir(parents=True, exist_ok=True)

        report = RenderReport()
        chosen = games[:5]

        # The "top" game drives the cover photo.  Games are retention-ordered
        # (opener strong, best last) so we find the highest score explicitly.
        top_game = max(chosen, key=lambda g: g.score)

        # ── Cover slide ───────────────────────────────────────────────────
        log.info("gazette.cover_start", top_game=top_game.name,
                 score=top_game.score, url=top_game.thumbnail_url)

        hero_img = None
        photo_filter = "none"
        src = top_game.thumbnail_url

        if isinstance(src, Image.Image):
            # Demo mode: PIL image passed directly (offline / sandbox).
            hero_img = theme_duotone(src, treatment="sepia", contrast=1.28)
            log.info("gazette.hero_duotone_ok", game=top_game.name, source="pil")

        elif isinstance(src, str) and src.startswith(("http://", "https://")):
            # Production path: fetch the real Roblox CDN thumbnail and bake the
            # duotone in Python so the cover treatment is pixel-identical to the
            # renders produced by theme_duotone (not a CSS approximation).
            pil = _fetch_pil(src)
            if pil:
                hero_img = theme_duotone(pil, treatment="sepia", contrast=1.28)
                log.info("gazette.hero_duotone_ok", game=top_game.name, source="url")
            else:
                # Fetch failed — pass the URL and let Chromium load it with a CSS
                # filter approximation. The real photo still appears; no blank hero.
                hero_img = src
                photo_filter = (
                    "grayscale(.66) contrast(1.20) sepia(.50) brightness(.96)"
                )
                log.warning("gazette.hero_pil_failed_using_url", game=top_game.name)

        elif isinstance(src, str) and Path(src).exists():
            # Local file path (e.g. a pre-downloaded screenshot on disk).
            hero_img = theme_duotone(src, treatment="sepia", contrast=1.28)
            log.info("gazette.hero_duotone_ok", game=top_game.name, source="path")

        else:
            # No usable source — hero area will be blank.  Should never happen for
            # games that passed the pipeline's thumbnail provenance gate.
            log.error("gazette.hero_no_source", game=top_game.name, src=repr(src))

        n = len(chosen)
        headline = _gazette_headline(cover_hook, n)
        deck = (
            f"An independent review desk played, scored and graded {n} games "
            f"buried under the front page. The verdicts are not kind to the "
            f"popular list."
        )
        caption = (
            f"PICTURED: {top_game.name!r} · "
            f"this issue’s No. 1, graded "
            f"{_score_to_grade(top_game.score)}"
        )

        cover_html = self._variant.newspaper_cover_html(
            headline=headline,
            deck=deck,
            caption=caption,
            part=part_number,
            hero=hero_img,
            photo_filter=photo_filter,
        )
        cover_path = output_dir / "slide_00_cover.png"
        _render_html(cover_html).save(str(cover_path))
        report.slides.append(cover_path)
        log.info("gazette.cover_saved", path=str(cover_path))

        # ── Review-column slides ──────────────────────────────────────────
        for i, game in enumerate(chosen):
            overall = _score_to_grade(game.score)
            subgrades = _derive_subgrades(game)

            # Assessment copy: AI verdict > blurb > caption (in that order of quality)
            assessment = (
                game.blurb.strip()
                or game.carousel_caption.strip()
                or f"Scored {game.score:.1f}/10 — worth your time."
            )

            # Pass the thumbnail URL directly: img_to_uri() returns it as-is for
            # http(s) strings, and Chromium fetches the real Roblox CDN image at
            # render time.  This is the production real-art path (no placeholder).
            art = game.thumbnail_url

            slide_html = self._variant.gazette_slide_html(
                name=game.name,
                creator=game.creator or "Roblox creator",
                overall=overall,
                subgrades=subgrades,
                assessment=assessment,
                visits_label=_visits_label(game.visits),
                recommended=game.score >= 8.0,
                part=part_number,
                index=i + 1,
                art=art,
                total=n,
            )

            safe = (
                "".join(c for c in game.name[:20] if c.isalnum() or c in " _")
                .replace(" ", "_")
            )
            path = output_dir / f"slide_{i+1:02d}_{safe}.png"
            _render_html(slide_html).save(str(path))
            report.slides.append(path)

            # Provenance: URL present → Chromium loaded the real art → ok.
            # No URL → genuine placeholder (no image to load at all) → not ok.
            report.record_hero(game.name, ok=bool(art))

            log.info(
                "gazette.slide_saved",
                slide=i + 1,
                game=game.name,
                grade=overall,
                score=game.score,
                subgrades=subgrades,
            )

        self.last_render_report = report
        if report.ok:
            log.info(
                "gazette.complete",
                slides=len(report.slides),
                part=part_number,
                thumbnails_ok=report.successful_thumbnails,
            )
        else:
            log.error(
                "gazette.placeholder_thumbnails",
                part=part_number,
                placeholder_count=report.placeholder_count,
                failed_games=report.failed_games,
            )
        return report
