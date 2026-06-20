"""
Video assembler — produces the actual TikTok video.

Format: 9:16 slideshow with narration audio overlay.
Duration: 18–22 seconds (optimal for TikTok completion rate).

Slide sequence:
  0: Hook (2.5s)   — full-bleed text, instant curiosity
  1: Reveal (3.5s) — game thumbnail + title fade in
  2: Stats (3.5s)  — visits, players, favorites with animation feel
  3: Features (4s) — 3 bullet points from description/AI
  4: Rating (5s)   — score counts up, label appears, verdict
  5: CTA (2.5s)    — follow prompt, brand colors

Audio: gTTS narration synchronized to slides (or ElevenLabs for premium).
Captions: burned-in word-level captions for silent viewers (70% of TikTok).
"""
from __future__ import annotations

import io
import math
import os
import textwrap
from pathlib import Path
from typing import Optional

import numpy as np
import structlog
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.config import get_settings

log = structlog.get_logger(__name__)

W, H = 1080, 1920
FPS = 30

TIMINGS = {
    "hook": 2.5,
    "reveal": 3.5,
    "stats": 3.5,
    "features": 4.0,
    "rating": 5.0,
    "cta": 2.5,
}
TOTAL_DURATION = sum(TIMINGS.values())  # ~21.5s


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    settings = get_settings()
    font_dir = Path(settings.ASSETS_DIR, "fonts")
    candidates = [
        font_dir / ("bold.ttf" if bold else "regular.ttf"),
        font_dir / ("Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf"),
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _pil_to_array(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))


def _ease_in_out(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _make_gradient_bg(
    color1: tuple[int, int, int],
    color2: tuple[int, int, int],
    alpha: float = 1.0,
) -> Image.Image:
    bg = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        r = int(_lerp(color1[0], color2[0], t))
        g = int(_lerp(color1[1], color2[1], t))
        b = int(_lerp(color1[2], color2[2], t))
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return bg


def _load_game_image(path: Optional[Path], url: Optional[str]) -> Optional[Image.Image]:
    if path and Path(path).exists():
        try:
            return Image.open(path).convert("RGB")
        except Exception:
            pass
    if url:
        try:
            import requests
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception:
            pass
    return None


def _cover_fill(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    ratio = max(target_w / img.width, target_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    x_off = (new_w - target_w) // 2
    y_off = (new_h - target_h) // 2
    return img.crop((x_off, y_off, x_off + target_w, y_off + target_h))


def _draw_centered(draw, text, cx, cy, font, fill, shadow_offset=4):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = cx - tw // 2, cy - th // 2
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0, 160))
    draw.text((x, y), text, font=font, fill=fill)


def _wrap_lines(text: str, max_chars: int = 22) -> list[str]:
    return textwrap.fill(text, width=max_chars).split("\n")


def _format_number(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    elif n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


class VideoAssembler:
    def __init__(self):
        self._settings = get_settings()

    def assemble(
        self,
        universe_id: str,
        game_name: str,
        score: float,
        label: str,
        verdict: str,
        hook_text: str,
        visits: int,
        active_players: int,
        favorites: int,
        tts_script: str,
        thumbnail_path: Optional[Path],
        thumbnail_url: Optional[str],
        features: Optional[list[str]] = None,
    ) -> Optional[Path]:
        """
        Build the complete TikTok video.
        Returns the path to the output .mp4 file.
        """
        try:
            from moviepy.editor import (  # noqa: PLC0415
                AudioFileClip,
                CompositeVideoClip,
                ImageClip,
                concatenate_videoclips,
            )
        except ImportError:
            log.error("video.moviepy_not_available")
            return None

        output_dir = Path(self._settings.OUTPUT_DIR, "videos")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{universe_id}.mp4"

        if output_path.exists():
            log.info("video.already_exists", path=str(output_path))
            return output_path

        game_img = _load_game_image(thumbnail_path, thumbnail_url)
        settings = self._settings

        slides = [
            self._slide_hook(hook_text, settings),
            self._slide_reveal(game_name, game_img, score),
            self._slide_stats(game_name, visits, active_players, favorites, game_img),
            self._slide_features(game_name, features or [], game_img),
            self._slide_rating(score, label, verdict, game_img, settings),
            self._slide_cta(settings),
        ]

        slide_durations = list(TIMINGS.values())
        clips = [
            ImageClip(_pil_to_array(slide)).set_duration(dur)
            for slide, dur in zip(slides, slide_durations)
        ]

        video = concatenate_videoclips(clips, method="compose")

        # ── Audio ─────────────────────────────────────────────────────
        audio_path = self._generate_audio(universe_id, tts_script)
        if audio_path and audio_path.exists():
            try:
                audio = AudioFileClip(str(audio_path))
                if audio.duration > video.duration:
                    audio = audio.subclip(0, video.duration)
                video = video.set_audio(audio)
            except Exception as exc:
                log.warning("video.audio_attach_failed", error=str(exc))

        video.write_videofile(
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="fast",
            logger=None,
        )
        log.info("video.assembled", path=str(output_path), duration=TOTAL_DURATION)
        return output_path

    def _generate_audio(self, universe_id: str, script: str) -> Optional[Path]:
        audio_dir = Path(self._settings.OUTPUT_DIR, "audio")
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{universe_id}.mp3"

        if audio_path.exists():
            return audio_path

        provider = self._settings.TTS_PROVIDER
        try:
            if provider == "elevenlabs" and self._settings.ELEVENLABS_API_KEY:
                return self._tts_elevenlabs(script, audio_path)
            return self._tts_gtts(script, audio_path)
        except Exception as exc:
            log.warning("video.tts_failed", provider=provider, error=str(exc))
            return None

    def _tts_gtts(self, script: str, output: Path) -> Path:
        from gtts import gTTS  # noqa: PLC0415
        tts = gTTS(text=script, lang="en", slow=False)
        tts.save(str(output))
        log.info("video.tts_gtts_done", path=str(output))
        return output

    def _tts_elevenlabs(self, script: str, output: Path) -> Path:
        import requests as req  # noqa: PLC0415
        resp = req.post(
            "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
            headers={
                "xi-api-key": self._settings.ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": script,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=30,
        )
        resp.raise_for_status()
        output.write_bytes(resp.content)
        log.info("video.tts_elevenlabs_done", path=str(output))
        return output

    # ── Slide builders ────────────────────────────────────────────────

    def _slide_hook(self, hook_text: str, settings) -> Image.Image:
        bg = _make_gradient_bg(settings.brand_primary_rgb, (10, 10, 30))
        draw = ImageDraw.Draw(bg)

        # Decorative lines
        for i in range(0, W, 60):
            draw.line([(i, 0), (i + 40, H)], fill=(255, 255, 255, 15), width=1)

        font_large = _load_font(96, bold=True)
        font_small = _load_font(52)

        lines = _wrap_lines(hook_text or "Nobody talks about this Roblox game...", max_chars=16)
        total_h = len(lines) * 120
        start_y = H // 2 - total_h // 2

        for i, line in enumerate(lines[:4]):
            y = start_y + i * 120
            _draw_centered(draw, line, W // 2, y, font_large, (255, 255, 255))

        # Watch time hook: "Rating reveal at the end 👀"
        _draw_centered(draw, "Rating reveal at the end 👀", W // 2, H - 220, font_small, (255, 215, 0))

        return bg

    def _slide_reveal(self, name: str, game_img: Optional[Image.Image], score: float) -> Image.Image:
        bg = Image.new("RGB", (W, H), (8, 8, 20))

        if game_img:
            filled = _cover_fill(game_img, W, H)
            blurred = filled.filter(ImageFilter.GaussianBlur(12))
            dark = Image.new("RGB", (W, H), (0, 0, 10))
            bg = Image.blend(blurred, dark, 0.55)

            # Center showcase image (16:9 cropped)
            showcase_h = int(W * 9 / 16)
            showcase = _cover_fill(game_img, W - 60, showcase_h - 20)
            sy = H // 2 - showcase_h // 2
            # Rounded-corner effect via mask
            mask = Image.new("L", showcase.size, 0)
            mdraw = ImageDraw.Draw(mask)
            mdraw.rounded_rectangle([0, 0, showcase.width, showcase.height], radius=24, fill=255)
            bg.paste(showcase, (30, sy), mask)

        draw = ImageDraw.Draw(bg)

        # Game title
        title_font = _load_font(88, bold=True)
        name_y = int(H * 0.78)
        for i, line in enumerate(_wrap_lines(name, 16)[:2]):
            _draw_centered(draw, line, W // 2, name_y + i * 100, title_font, (255, 255, 255))

        # "Reviewing..." tag
        tag_font = _load_font(50)
        _draw_centered(draw, "Reviewing 🔍", W // 2, int(H * 0.12), tag_font, (200, 200, 200))

        return bg

    def _slide_stats(
        self,
        name: str,
        visits: int,
        active: int,
        favorites: int,
        game_img: Optional[Image.Image],
    ) -> Image.Image:
        bg = Image.new("RGB", (W, H), (8, 10, 24))
        if game_img:
            filled = _cover_fill(game_img.filter(ImageFilter.GaussianBlur(30)), W, H)
            dark = Image.new("RGB", (W, H), (5, 5, 20))
            bg = Image.blend(filled, dark, 0.70)

        draw = ImageDraw.Draw(bg)

        label_font = _load_font(52)
        value_font = _load_font(110, bold=True)
        header_font = _load_font(62, bold=True)

        _draw_centered(draw, "THE NUMBERS", W // 2, 140, header_font, (255, 215, 0))

        stats = [
            ("👁️ VISITS", _format_number(visits), (100, 200, 255)),
            ("👥 ACTIVE NOW", _format_number(active), (100, 255, 150)),
            ("⭐ FAVORITES", _format_number(favorites), (255, 215, 50)),
        ]

        block_h = 280
        start_y = H // 2 - (len(stats) * block_h) // 2

        for i, (stat_label, stat_val, stat_color) in enumerate(stats):
            cy = start_y + i * block_h

            # Card bg
            card_x0, card_x1 = 60, W - 60
            draw.rounded_rectangle(
                [card_x0, cy - 100, card_x1, cy + 130],
                radius=20,
                fill=(20, 22, 40),
            )
            _draw_centered(draw, stat_label, W // 2, cy - 50, label_font, (170, 170, 200))
            _draw_centered(draw, stat_val, W // 2, cy + 40, value_font, stat_color)

        return bg

    def _slide_features(
        self,
        name: str,
        features: list[str],
        game_img: Optional[Image.Image],
    ) -> Image.Image:
        bg = Image.new("RGB", (W, H), (5, 8, 20))
        if game_img:
            filled = _cover_fill(game_img, W, int(H * 0.45))
            bg.paste(filled, (0, 0))
            # Gradient overlay
            grad = _make_gradient_bg((0, 0, 0), (5, 8, 20))
            grad.putalpha(180)
            if grad.mode != "RGB":
                grad = grad.convert("RGB")
            for y in range(int(H * 0.45)):
                alpha = int(y / (H * 0.45) * 220)
                row = Image.new("RGB", (W, 1), (5, 8, 20))
                bg.paste(Image.blend(
                    Image.new("RGB", (W, 1), (0, 0, 0)),
                    row, min(1.0, alpha / 255)
                ), (0, y))

        draw = ImageDraw.Draw(bg)
        header_font = _load_font(62, bold=True)
        feat_font = _load_font(54)

        _draw_centered(draw, "WHY IT'S WORTH IT", W // 2, int(H * 0.52), header_font, (255, 215, 0))

        defaults = [
            "Massive active community",
            "Frequent game updates",
            "High replay value",
        ]
        display = (features or defaults)[:3]

        for i, feat in enumerate(display):
            y = int(H * 0.60) + i * 130
            feat_text = f"✓ {feat[:40]}"
            _draw_centered(draw, feat_text, W // 2, y, feat_font, (220, 240, 255))

        return bg

    def _slide_rating(
        self,
        score: float,
        label: str,
        verdict: str,
        game_img: Optional[Image.Image],
        settings,
    ) -> Image.Image:
        score_color = (50, 205, 50) if score >= 9 else (255, 215, 0) if score >= 7 else (220, 60, 30)
        bg = _make_gradient_bg((10, 10, 25), (score_color[0]//4, score_color[1]//4, score_color[2]//4))
        draw = ImageDraw.Draw(bg)

        # "OUR VERDICT" header
        header_font = _load_font(58, bold=True)
        _draw_centered(draw, "OUR VERDICT", W // 2, 160, header_font, (180, 180, 220))

        # Giant score
        score_font = _load_font(320, bold=True)
        _draw_centered(draw, f"{score:.1f}", W // 2, H // 2 - 100, score_font, score_color, shadow_offset=8)

        # /10
        ten_font = _load_font(100)
        bbox = draw.textbbox((0, 0), f"{score:.1f}", font=score_font)
        sw = bbox[2] - bbox[0]
        draw.text(
            (W // 2 + sw // 2 + 10, H // 2 - 100 + 120),
            "/10",
            font=ten_font,
            fill=(160, 160, 180),
        )

        # Label badge
        label_clean = "HIDDEN GEM" if "GEM" in label else label.split(" ")[0]
        badge_font = _load_font(68, bold=True)
        bbox = draw.textbbox((0, 0), label_clean, font=badge_font)
        bw = bbox[2] - bbox[0] + 60
        bh = bbox[3] - bbox[1] + 30
        bx = (W - bw) // 2
        by = H // 2 + 140
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=18, fill=score_color)
        draw.text((bx + 30, by + 15), label_clean, font=badge_font, fill=(255, 255, 255))

        # Verdict
        verdict_font = _load_font(48)
        v_lines = _wrap_lines(verdict[:80], max_chars=26)
        for i, line in enumerate(v_lines[:2]):
            _draw_centered(draw, line, W // 2, int(H * 0.82) + i * 60, verdict_font, (200, 200, 220))

        return bg

    def _slide_cta(self, settings) -> Image.Image:
        bg = _make_gradient_bg(settings.brand_primary_rgb, (10, 10, 30))
        draw = ImageDraw.Draw(bg)

        # Animated-feel sparkle pattern
        import random  # noqa: PLC0415
        rng = random.Random(42)
        for _ in range(40):
            sx = rng.randint(0, W)
            sy = rng.randint(0, H)
            r = rng.randint(2, 6)
            a = rng.randint(60, 180)
            draw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 255, 255, a))

        cta_font = _load_font(90, bold=True)
        sub_font = _load_font(56)
        handle_font = _load_font(72, bold=True)
        accent = settings.brand_accent_rgb

        _draw_centered(draw, "Follow us for", W // 2, H // 2 - 200, sub_font, (200, 200, 240))
        _draw_centered(draw, "daily Roblox", W // 2, H // 2 - 90, cta_font, (255, 255, 255))
        _draw_centered(draw, "hidden gems 💎", W // 2, H // 2 + 60, cta_font, accent)
        _draw_centered(draw, settings.CHANNEL_HANDLE, W // 2, H // 2 + 220, handle_font, (255, 255, 255))

        return bg
