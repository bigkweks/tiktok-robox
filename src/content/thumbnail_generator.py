"""
Thumbnail generator.

Produces 9:16 TikTok-optimized cover images in two variants:
  A) Rating-focus: Large score + label dominates, game thumb in background
  B) Hook-focus: Bold statement text + game thumb, score is secondary

Design principles:
  - Mobile-first (viewed at ~300px wide on most phones)
  - 3-second rule: viewer understands the value in 3 seconds
  - Color coding: green=gem, gold=good, orange=decent, red=overhyped
  - Brand consistency: same font, same logo position, same color palette
  - High contrast text (min 4.5:1 contrast ratio for accessibility)
"""
from __future__ import annotations

import io
import textwrap
from pathlib import Path
from typing import Optional

import re

import requests
import structlog
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import get_settings

log = structlog.get_logger(__name__)

# Design constants
THUMB_W = 1080
THUMB_H = 1920

# Rating color scheme (score-based)
SCORE_COLORS = {
    "gem":     (50, 205, 50),     # 9.0+ → vivid green
    "good":    (255, 215, 0),     # 8.0+ → gold
    "decent":  (255, 140, 0),     # 7.0+ → orange
    "average": (255, 100, 0),     # 5.5+ → deep orange
    "bad":     (220, 20, 60),     # <5.5 → crimson
}

LABEL_COLORS = {
    "HIDDEN GEM 💎": (50, 205, 50),
    "ACTUALLY GOOD ✅": (255, 215, 0),
    "WORTH PLAYING 🎮": (255, 165, 0),
    "DECENT 😐": (255, 120, 0),
    "OVERHYPED ⚠️": (220, 80, 30),
    "SKIP IT ❌": (220, 20, 60),
}


def _get_score_color(score: float) -> tuple[int, int, int]:
    if score >= 9.0:
        return SCORE_COLORS["gem"]
    elif score >= 8.0:
        return SCORE_COLORS["good"]
    elif score >= 7.0:
        return SCORE_COLORS["decent"]
    elif score >= 5.5:
        return SCORE_COLORS["average"]
    else:
        return SCORE_COLORS["bad"]


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    # Shared Poppins loader (bundled) → clean, real-looking type
    from src.content.fonts import load_font as _shared
    return _shared("extrabold" if bold else "medium", size)


def _download_image(url: str) -> Optional[Image.Image]:
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as exc:
        log.warning("thumbnail.image_download_failed", url=url, error=str(exc))
        return None


def _load_image_from_path(path: Optional[Path]) -> Optional[Image.Image]:
    if path and Path(path).exists():
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            return None
    return None


def _draw_rounded_rect(
    draw: ImageDraw.Draw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple,
    alpha: int = 220,
) -> None:
    x0, y0, x1, y1 = xy
    fill_with_alpha = fill[:3] + (alpha,)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill_with_alpha)


def _draw_centered_text(
    draw: ImageDraw.Draw,
    text: str,
    cx: int,
    cy: int,
    font: ImageFont.ImageFont,
    fill: tuple,
    shadow: bool = True,
    shadow_offset: int = 3,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = cx - tw // 2, cy - th // 2

    if shadow:
        draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=font, fill=fill)


class ThumbnailGenerator:
    def __init__(self):
        self._settings = get_settings()

    def generate_variant_a(
        self,
        game_name: str,
        score: float,
        label: str,
        thumbnail_path: Optional[Path],
        thumbnail_url: Optional[str],
        output_path: Path,
    ) -> Path:
        """
        Variant A: Rating-dominant.
        Giant score number as the hero. Game thumbnail as background.
        Maximum impact for viewers who see the score first.
        """
        canvas = Image.new("RGBA", (THUMB_W, THUMB_H), (15, 15, 25, 255))

        # Load and place game thumbnail as blurred background
        game_img = _load_image_from_path(thumbnail_path) or (
            _download_image(thumbnail_url) if thumbnail_url else None
        )
        if game_img:
            # Scale to fill canvas
            ratio = max(THUMB_W / game_img.width, THUMB_H / game_img.height)
            new_w = int(game_img.width * ratio)
            new_h = int(game_img.height * ratio)
            game_img = game_img.resize((new_w, new_h), Image.LANCZOS)
            # Center crop
            x_off = (new_w - THUMB_W) // 2
            y_off = (new_h - THUMB_H) // 2
            game_img = game_img.crop((x_off, y_off, x_off + THUMB_W, y_off + THUMB_H))
            # Heavy blur for background
            blurred = game_img.filter(ImageFilter.GaussianBlur(radius=18))
            # Darken
            dark = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 160))
            bg = Image.alpha_composite(blurred, dark)
            canvas.paste(bg, (0, 0))

            # Place a crisp version in center (game showcase)
            showcase_w = int(THUMB_W * 0.88)
            showcase_h = int(showcase_w * (432 / 768))  # maintain 16:9 ratio
            sharp_img = game_img.resize((showcase_w, showcase_h), Image.LANCZOS)
            sx = (THUMB_W - showcase_w) // 2
            sy = int(THUMB_H * 0.28)

            # Drop shadow for showcase
            shadow_img = Image.new("RGBA", (showcase_w + 20, showcase_h + 20), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow_img)
            sd.rectangle([10, 10, showcase_w + 10, showcase_h + 10], fill=(0, 0, 0, 120))
            shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(8))
            canvas.paste(shadow_img, (sx - 10, sy - 10), shadow_img)
            canvas.paste(sharp_img, (sx, sy), sharp_img)

        draw = ImageDraw.Draw(canvas)
        score_color = _get_score_color(score)
        label_color = LABEL_COLORS.get(label, score_color)

        # ── Top: Channel brand strip ──────────────────────────────────
        brand_color = self._settings.brand_primary_rgb
        draw.rectangle([0, 0, THUMB_W, 110], fill=brand_color + (240,))
        channel_font = _load_font(52, bold=True)
        _draw_centered_text(draw, self._settings.channel_name_display, THUMB_W // 2, 55, channel_font, (255, 255, 255, 255), shadow=False)

        # ── Score: Giant number (anchor-positioned for predictable bounds) ─
        score_font = _load_font(250, bold=True)
        score_text = f"{score:.1f}"
        score_cy = int(THUMB_H * 0.17)
        # Shadow then fill, both center-anchored
        draw.text((THUMB_W // 2 + 6, score_cy + 6), score_text, font=score_font,
                  fill=(0, 0, 0, 150), anchor="mm")
        draw.text((THUMB_W // 2, score_cy), score_text, font=score_font,
                  fill=score_color + (255,), anchor="mm")

        # True pixel bounds of the drawn score
        sbbox = draw.textbbox((THUMB_W // 2, score_cy), score_text, font=score_font, anchor="mm")
        score_right = sbbox[2]
        score_bottom = sbbox[3]

        # /10 subscript aligned to the score's right edge
        sub_font = _load_font(72, bold=False)
        draw.text((score_right + 14, score_cy), "/10", font=sub_font,
                  fill=(200, 200, 200, 220), anchor="lm")

        # ── Label badge — sits cleanly below the score ────────────────
        label_clean = re.sub(r"[^\w\s]", "", label).strip() if label else "HIDDEN GEM"
        badge_font = _load_font(56, bold=True)
        lbbox = draw.textbbox((0, 0), label_clean, font=badge_font)
        bw, bh = lbbox[2] - lbbox[0] + 56, lbbox[3] - lbbox[1] + 34
        bx = (THUMB_W - bw) // 2
        by = score_bottom + 44
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=18, fill=label_color + (230,))
        draw.text((THUMB_W // 2, by + bh // 2), label_clean, font=badge_font,
                  fill=(255, 255, 255, 255), anchor="mm")

        # ── Game name ─────────────────────────────────────────────────
        name_font = _load_font(68, bold=True)
        name_y = int(THUMB_H * 0.82)
        wrapped = textwrap.fill(game_name, width=18)
        lines = wrapped.split("\n")
        for i, line in enumerate(lines[:2]):
            _draw_centered_text(draw, line, THUMB_W // 2, name_y + i * 78, name_font, (255, 255, 255, 255))

        # ── Bottom CTA strip ──────────────────────────────────────────
        cta_y = THUMB_H - 120
        draw.rectangle([0, cta_y, THUMB_W, THUMB_H], fill=(10, 10, 20, 230))
        cta_font = _load_font(44, bold=False)
        cta_color = self._settings.brand_accent_rgb
        _draw_centered_text(
            draw,
            f"Follow {self._settings.channel_handle_display} for more",
            THUMB_W // 2,
            cta_y + 60,
            cta_font,
            cta_color + (255,),
            shadow=False,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(str(output_path), "PNG", quality=95, optimize=True)
        log.info("thumbnail.variant_a_saved", path=str(output_path))
        return output_path

    def generate_variant_b(
        self,
        game_name: str,
        score: float,
        label: str,
        hook_text: str,
        thumbnail_path: Optional[Path],
        thumbnail_url: Optional[str],
        output_path: Path,
    ) -> Path:
        """
        Variant B: Hook-dominant.
        Bold statement text as hero. Score is secondary badge.
        Better for curiosity-gap style hooks ("Nobody talks about this...").
        """
        canvas = Image.new("RGBA", (THUMB_W, THUMB_H), (10, 10, 18, 255))

        game_img = _load_image_from_path(thumbnail_path) or (
            _download_image(thumbnail_url) if thumbnail_url else None
        )
        if game_img:
            ratio = max(THUMB_W / game_img.width, THUMB_H / game_img.height)
            new_w = int(game_img.width * ratio)
            new_h = int(game_img.height * ratio)
            game_img = game_img.resize((new_w, new_h), Image.LANCZOS)
            x_off = (new_w - THUMB_W) // 2
            y_off = (new_h - THUMB_H) // 2
            game_img = game_img.crop((x_off, y_off, x_off + THUMB_W, y_off + THUMB_H))

            # Top half: crisp game image
            top_img = game_img.crop((0, 0, THUMB_W, THUMB_H // 2))
            canvas.paste(top_img, (0, 0), top_img)

            # Gradient overlay on top half
            gradient = Image.new("RGBA", (THUMB_W, THUMB_H // 2), (0, 0, 0, 0))
            gd = ImageDraw.Draw(gradient)
            for i in range(THUMB_H // 2):
                alpha = int(40 + (i / (THUMB_H // 2)) * 140)
                gd.rectangle([0, i, THUMB_W, i + 1], fill=(0, 0, 0, alpha))
            canvas.alpha_composite(gradient, (0, 0))

            # Bottom half: dark bg with slight game blur
            bottom_blur = game_img.crop((0, THUMB_H // 2, THUMB_W, THUMB_H))
            bottom_blur = bottom_blur.filter(ImageFilter.GaussianBlur(25))
            dark_overlay = Image.new("RGBA", (THUMB_W, THUMB_H // 2), (0, 0, 0, 180))
            bottom_combined = Image.alpha_composite(bottom_blur, dark_overlay)
            canvas.paste(bottom_combined, (0, THUMB_H // 2), bottom_combined)

        draw = ImageDraw.Draw(canvas)
        score_color = _get_score_color(score)

        # ── Top brand ─────────────────────────────────────────────────
        draw.rectangle([0, 0, THUMB_W, 100], fill=self._settings.brand_primary_rgb + (220,))
        brand_font = _load_font(48, bold=True)
        _draw_centered_text(draw, self._settings.channel_name_display, THUMB_W // 2, 50, brand_font, (255, 255, 255, 255), shadow=False)

        # ── Hook text (top half, lower portion) ───────────────────────
        hook_font = _load_font(88, bold=True)
        clean_hook = hook_text.replace("...", "…") if hook_text else f"Is {game_name} worth it?"
        wrapped_hook = textwrap.fill(clean_hook, width=14)
        hook_lines = wrapped_hook.split("\n")
        hook_start_y = int(THUMB_H * 0.35)
        for i, line in enumerate(hook_lines[:3]):
            # Text shadow
            draw.text((THUMB_W // 2 - 1 + 4, hook_start_y + i * 100 + 4), line,
                      font=hook_font, fill=(0, 0, 0, 180), anchor="mm")
            draw.text((THUMB_W // 2 - 1, hook_start_y + i * 100), line,
                      font=hook_font, fill=(255, 255, 255, 255), anchor="mm")

        # ── Score badge (center divider) ──────────────────────────────
        badge_y = THUMB_H // 2 + 40
        draw.ellipse(
            [THUMB_W // 2 - 100, badge_y - 100, THUMB_W // 2 + 100, badge_y + 100],
            fill=score_color + (240,),
        )
        score_font = _load_font(90, bold=True)
        _draw_centered_text(draw, f"{score:.1f}", THUMB_W // 2, badge_y, score_font, (255, 255, 255, 255), shadow=False)

        # ── Game name ─────────────────────────────────────────────────
        name_font = _load_font(72, bold=True)
        name_y = int(THUMB_H * 0.73)
        wrapped_name = textwrap.fill(game_name, width=16)
        for i, line in enumerate(wrapped_name.split("\n")[:2]):
            _draw_centered_text(draw, line, THUMB_W // 2, name_y + i * 85, name_font, (255, 255, 255, 255))

        # ── Label ─────────────────────────────────────────────────────
        label_clean = re.sub(r"[^\w\s]", "", label).strip() if label else "HIDDEN GEM"
        label_font = _load_font(50, bold=True)
        label_color = LABEL_COLORS.get(label, score_color)
        bbox = draw.textbbox((0, 0), label_clean, font=label_font)
        bw = bbox[2] - bbox[0] + 40
        bh = bbox[3] - bbox[1] + 20
        bx = (THUMB_W - bw) // 2
        by = int(THUMB_H * 0.86)
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=12, fill=label_color + (220,))
        draw.text((bx + 20, by + 10), label_clean, font=label_font, fill=(255, 255, 255, 255))

        # ── CTA ───────────────────────────────────────────────────────
        cta_y = THUMB_H - 110
        draw.rectangle([0, cta_y, THUMB_W, THUMB_H], fill=(10, 10, 20, 230))
        cta_font = _load_font(40, bold=False)
        cta_color = self._settings.brand_accent_rgb
        _draw_centered_text(draw, f"Follow {self._settings.channel_handle_display} for more", THUMB_W // 2, cta_y + 55, cta_font, cta_color + (255,), shadow=False)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(str(output_path), "PNG", quality=95, optimize=True)
        log.info("thumbnail.variant_b_saved", path=str(output_path))
        return output_path

    def generate_both(
        self,
        game_name: str,
        universe_id: str,
        score: float,
        label: str,
        hook_text: str,
        thumbnail_path: Optional[Path],
        thumbnail_url: Optional[str],
    ) -> tuple[Path, Path]:
        """Generate both variants and return (path_a, path_b)."""
        from src.content.fonts import strip_emoji  # noqa: PLC0415
        # Roblox names / AI hooks may carry emoji the text font can't draw → tofu.
        game_name = strip_emoji(game_name) or game_name
        hook_text = strip_emoji(hook_text) if hook_text else hook_text
        thumb_dir = Path(self._settings.OUTPUT_DIR, "thumbnails", universe_id)
        path_a = thumb_dir / "variant_a.png"
        path_b = thumb_dir / "variant_b.png"

        self.generate_variant_a(game_name, score, label, thumbnail_path, thumbnail_url, path_a)
        self.generate_variant_b(game_name, score, label, hook_text, thumbnail_path, thumbnail_url, path_b)

        return path_a, path_b
