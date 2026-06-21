"""
Video assembler — produces the actual TikTok video.

Format: 9:16 slideshow with narration audio overlay, motion, and burned-in
captions so the video lands even for the ~70% of TikTok viewers watching muted.

Slide sequence:
  0: Hook (2.5s)   — full-bleed text, instant curiosity
  1: Reveal (3.5s) — game thumbnail + title, slow Ken Burns zoom
  2: Stats (3.5s)  — visits, players, favorites in cards
  3: Features (4s) — 3 bullet points from description/AI
  4: Rating (5s)   — score COUNTS UP, label appears, verdict
  5: CTA (2.5s)    — follow prompt, brand colors

Motion: every slide gets a subtle Ken Burns zoom; slides crossfade.
Captions: the narration is split across the slides and burned into the
          lower third with a readable plate.
Audio: gTTS narration (or ElevenLabs for premium), synced to the slides.

Every motion/caption effect degrades gracefully: if a moviepy effect raises,
the slide falls back to its static frame so a render never fully fails.
"""
from __future__ import annotations

import io
import math
import os
import random
import re
import textwrap
from pathlib import Path
from typing import Optional

import numpy as np
import requests
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
CROSSFADE = 0.35  # seconds of crossfade between slides


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
    # Vectorized vertical gradient (was a 1920-iteration Python loop)
    ys = np.linspace(0.0, 1.0, H).reshape(H, 1)
    c1 = np.array(color1, dtype=np.float32)
    c2 = np.array(color2, dtype=np.float32)
    rows = (c1 * (1 - ys) + c2 * ys).astype(np.uint8)  # (H, 3)
    arr = np.repeat(rows[:, None, :], W, axis=1)        # (H, W, 3)
    return Image.fromarray(arr, "RGB")


def _load_game_image(path: Optional[Path], url: Optional[str]) -> Optional[Image.Image]:
    if path and Path(path).exists():
        try:
            return Image.open(path).convert("RGB")
        except Exception:
            pass
    if url:
        try:
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


def _split_narration(script: str, n: int) -> list[str]:
    """
    Split the narration into ~n caption chunks for the content slides.
    Splits on sentence boundaries, then balances into n groups by length.
    """
    if not script:
        return [""] * n
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", script.strip()) if p.strip()]
    if not parts:
        return [""] * n
    # Greedy balanced grouping into n buckets
    target = max(1, len(parts) // n)
    chunks: list[str] = []
    cur: list[str] = []
    for p in parts:
        cur.append(p)
        if len(cur) >= target and len(chunks) < n - 1:
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    while len(chunks) < n:
        chunks.append("")
    return chunks[:n]


def _draw_caption_band(img: Image.Image, text: str, y_center: int = H - 230) -> Image.Image:
    """
    Burn a readable caption into the lower third — the key upgrade for the
    ~70% of viewers who watch muted. Translucent rounded plate + bold text
    with a heavy outline so it reads over any background.
    """
    if not text:
        return img
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    font = _load_font(50, bold=True)
    lines = _wrap_lines(text, max_chars=28)[:3]
    line_h = 66
    block_h = len(lines) * line_h
    plate_top = y_center - block_h // 2 - 24
    plate_bot = y_center + block_h // 2 + 24

    # Plate
    odraw.rounded_rectangle(
        [50, plate_top, W - 50, plate_bot], radius=28, fill=(0, 0, 0, 140)
    )

    # Text with outline
    for i, line in enumerate(lines):
        ly = plate_top + 24 + i * line_h
        bbox = odraw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        lx = (W - tw) // 2
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2)):
            odraw.text((lx + dx, ly + dy), line, font=font, fill=(0, 0, 0, 230))
        odraw.text((lx, ly), line, font=font, fill=(255, 255, 255, 255))

    return Image.alpha_composite(base, overlay).convert("RGB")


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
                VideoClip,
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

        # Split narration across the 4 content slides (reveal/stats/features/rating)
        captions = _split_narration(tts_script, 4)

        slide_specs = [
            ("hook", self._slide_hook(hook_text, settings), 0.06),
            ("reveal", _draw_caption_band(self._slide_reveal(game_name, game_img, score), captions[0]), 0.07),
            ("stats", _draw_caption_band(self._slide_stats(game_name, visits, active_players, favorites, game_img), captions[1]), 0.05),
            ("features", _draw_caption_band(self._slide_features(game_name, features or [], game_img), captions[2]), 0.06),
            # rating handled specially below (animated count-up)
            ("cta", self._slide_cta(settings), 0.06),
        ]

        durations = TIMINGS
        clips = []

        # Build static slides with Ken Burns motion
        order = ["hook", "reveal", "stats", "features"]
        for name, img, amp in [s for s in slide_specs if s[0] in order]:
            dur = durations[name]
            clips.append(self._motion_clip(ImageClip, CompositeVideoClip, img, dur, amp))

        # Rating slide: animated score count-up via per-frame rendering
        rating_caption = captions[3]
        rating_clip = self._rating_clip(
            VideoClip, ImageClip, CompositeVideoClip,
            score, label, verdict, game_img, settings, rating_caption,
        )
        clips.append(rating_clip)

        # CTA slide
        cta_img = [s for s in slide_specs if s[0] == "cta"][0][1]
        clips.append(self._motion_clip(ImageClip, CompositeVideoClip, cta_img, durations["cta"], 0.05))

        # Concatenate with crossfades (fallback to hard cuts if it errors)
        video = self._concat_with_crossfade(concatenate_videoclips, clips)

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
        log.info("video.assembled", path=str(output_path), duration=video.duration)
        return output_path

    # ── Motion / composition helpers ──────────────────────────────────

    def _motion_clip(self, ImageClip, CompositeVideoClip, img: Image.Image, dur: float, amp: float):
        """
        Ken Burns: slowly zoom into the frame over its duration. Zooming up
        and center-compositing on a W×H canvas crops to the center, producing
        a smooth push-in. Falls back to a static clip on any error.
        """
        arr = _pil_to_array(img)
        try:
            base = ImageClip(arr).set_duration(dur)
            zoomed = base.resize(lambda t: 1.0 + amp * _ease_in_out(min(1.0, t / dur)))
            comp = CompositeVideoClip([zoomed.set_position("center")], size=(W, H)).set_duration(dur)
            return comp
        except Exception as exc:
            log.warning("video.motion_failed", error=str(exc))
            return ImageClip(arr).set_duration(dur)

    def _rating_clip(
        self, VideoClip, ImageClip, CompositeVideoClip,
        score, label, verdict, game_img, settings, caption,
    ):
        """
        The payoff slide. The score counts up from 0 over the first ~1.2s
        (the single biggest retention lever — viewers stay for the number),
        then the label + verdict snap in and hold.
        """
        dur = TIMINGS["rating"]
        count_up = 1.2

        # Pre-render the final, fully-revealed frame once (also the fallback)
        final_img = _draw_caption_band(
            self._slide_rating(score, label, verdict, game_img, settings,
                               shown_score=score, reveal=True),
            caption,
        )
        final_arr = _pil_to_array(final_img)

        try:
            # Cache intermediate frames so make_frame stays cheap
            cache: dict[int, np.ndarray] = {}

            def make_frame(t: float) -> np.ndarray:
                if t >= count_up:
                    return final_arr
                prog = _ease_in_out(t / count_up)
                shown = round(score * prog, 1)
                key = int(shown * 10)
                if key not in cache:
                    frame = self._slide_rating(
                        score, label, verdict, game_img, settings,
                        shown_score=shown, reveal=False,
                    )
                    cache[key] = _pil_to_array(frame)
                return cache[key]

            return VideoClip(make_frame, duration=dur)
        except Exception as exc:
            log.warning("video.rating_animation_failed", error=str(exc))
            return ImageClip(final_arr).set_duration(dur)

    def _concat_with_crossfade(self, concatenate_videoclips, clips):
        try:
            faded = [clips[0]]
            for c in clips[1:]:
                faded.append(c.crossfadein(CROSSFADE))
            return concatenate_videoclips(faded, method="compose", padding=-CROSSFADE)
        except Exception as exc:
            log.warning("video.crossfade_failed", error=str(exc))
            return concatenate_videoclips(clips, method="compose")

    # ── Audio ─────────────────────────────────────────────────────────

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
        resp = requests.post(
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

        # Subtle diagonal stripes — draw on RGBA overlay so alpha blending works
        stripe_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(stripe_layer)
        for i in range(0, W, 60):
            sdraw.line([(i, 0), (i + 40, H)], fill=(255, 255, 255, 18), width=1)
        bg = Image.alpha_composite(bg.convert("RGBA"), stripe_layer).convert("RGB")

        draw = ImageDraw.Draw(bg)
        font_large = _load_font(96, bold=True)
        font_small = _load_font(52)

        lines = _wrap_lines(hook_text or "Nobody talks about this Roblox game...", max_chars=16)
        total_h = len(lines) * 120
        start_y = H // 2 - total_h // 2

        for i, line in enumerate(lines[:4]):
            y = start_y + i * 120
            _draw_centered(draw, line, W // 2, y, font_large, (255, 255, 255))

        _draw_centered(draw, "Rating reveal at the end 👀", W // 2, H - 220, font_small, (255, 215, 0))
        return bg

    def _slide_reveal(self, name: str, game_img: Optional[Image.Image], score: float) -> Image.Image:
        bg = Image.new("RGB", (W, H), (8, 8, 20))

        if game_img:
            filled = _cover_fill(game_img, W, H)
            blurred = filled.filter(ImageFilter.GaussianBlur(12))
            dark = Image.new("RGB", (W, H), (0, 0, 10))
            bg = Image.blend(blurred, dark, 0.55)

            showcase_h = int(W * 9 / 16)
            showcase = _cover_fill(game_img, W - 60, showcase_h - 20)
            sy = H // 2 - showcase_h // 2
            mask = Image.new("L", showcase.size, 0)
            mdraw = ImageDraw.Draw(mask)
            mdraw.rounded_rectangle([0, 0, showcase.width, showcase.height], radius=24, fill=255)
            bg.paste(showcase, (30, sy), mask)

        draw = ImageDraw.Draw(bg)
        title_font = _load_font(88, bold=True)
        name_y = int(H * 0.74)
        for i, line in enumerate(_wrap_lines(name, 16)[:2]):
            _draw_centered(draw, line, W // 2, name_y + i * 100, title_font, (255, 255, 255))

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

        block_h = 260
        start_y = int(H * 0.34)

        for i, (stat_label, stat_val, stat_color) in enumerate(stats):
            cy = start_y + i * block_h
            draw.rounded_rectangle(
                [60, cy - 100, W - 60, cy + 130], radius=20, fill=(20, 22, 40),
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
        """
        Top ~45%: the game image, faded smoothly into the dark background.
        Bottom: header + up to 3 feature bullets.

        (Previously this ran a broken per-row blend that washed the image to
        black and discarded a computed-but-unused gradient. Now it uses a
        single vectorized vertical alpha fade.)
        """
        bg = Image.new("RGB", (W, H), (5, 8, 20))
        band_h = int(H * 0.45)

        if game_img:
            filled = _cover_fill(game_img, W, band_h)
            # Vertical alpha fade: opaque at top → transparent into the bg by band bottom
            fade = np.linspace(0, 255, band_h, dtype=np.uint8)        # 0=keep image … 255=bg
            alpha = np.repeat(fade[:, None], W, axis=1)               # (band_h, W)
            img_arr = np.array(filled).astype(np.float32)
            bg_top = np.array(bg.crop((0, 0, W, band_h))).astype(np.float32)
            a = (alpha[:, :, None] / 255.0)
            blended = (img_arr * (1 - a) + bg_top * a).astype(np.uint8)
            bg.paste(Image.fromarray(blended, "RGB"), (0, 0))

        draw = ImageDraw.Draw(bg)
        header_font = _load_font(62, bold=True)
        feat_font = _load_font(54)

        _draw_centered(draw, "WHY IT'S WORTH IT", W // 2, int(H * 0.52), header_font, (255, 215, 0))

        defaults = [
            "Massive active community",
            "Frequent game updates",
            "High replay value",
        ]
        display = [f for f in (features or []) if f][:3] or defaults

        for i, feat in enumerate(display):
            y = int(H * 0.60) + i * 120
            _draw_centered(draw, f"✓ {feat[:40]}", W // 2, y, feat_font, (220, 240, 255))

        return bg

    def _slide_rating(
        self,
        score: float,
        label: str,
        verdict: str,
        game_img: Optional[Image.Image],
        settings,
        shown_score: Optional[float] = None,
        reveal: bool = True,
    ) -> Image.Image:
        """
        Rating reveal. `shown_score` lets the assembler render intermediate
        count-up frames; `reveal` gates the label/verdict so they only appear
        once the number lands.
        """
        display_val = score if shown_score is None else shown_score
        score_color = (50, 205, 50) if score >= 9 else (255, 215, 0) if score >= 7 else (220, 60, 30)
        bg = _make_gradient_bg((10, 10, 25), (score_color[0] // 4, score_color[1] // 4, score_color[2] // 4))
        draw = ImageDraw.Draw(bg)

        header_font = _load_font(58, bold=True)
        _draw_centered(draw, "OUR VERDICT", W // 2, 160, header_font, (180, 180, 220))

        # Giant score
        score_font = _load_font(320, bold=True)
        _draw_centered(draw, f"{display_val:.1f}", W // 2, H // 2 - 100, score_font, score_color, shadow_offset=8)

        ten_font = _load_font(100)
        bbox = draw.textbbox((0, 0), f"{display_val:.1f}", font=score_font)
        sw = bbox[2] - bbox[0]
        draw.text(
            (W // 2 + sw // 2 + 10, H // 2 - 100 + 120),
            "/10", font=ten_font, fill=(160, 160, 180),
        )

        if reveal:
            label_clean = "HIDDEN GEM" if "GEM" in label else label.split(" ")[0]
            badge_font = _load_font(68, bold=True)
            bbox = draw.textbbox((0, 0), label_clean, font=badge_font)
            bw = bbox[2] - bbox[0] + 60
            bh = bbox[3] - bbox[1] + 30
            bx = (W - bw) // 2
            by = H // 2 + 140
            draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=18, fill=score_color)
            draw.text((bx + 30, by + 15), label_clean, font=badge_font, fill=(255, 255, 255))

            verdict_font = _load_font(48)
            for i, line in enumerate(_wrap_lines(verdict[:80], max_chars=26)[:2]):
                _draw_centered(draw, line, W // 2, int(H * 0.80) + i * 60, verdict_font, (200, 200, 220))

        return bg

    def _slide_cta(self, settings) -> Image.Image:
        bg = _make_gradient_bg(settings.brand_primary_rgb, (10, 10, 30))

        # Twinkling star particles — draw on RGBA overlay so alpha blending works
        star_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(star_layer)
        rng = random.Random(42)
        for _ in range(40):
            sx = rng.randint(0, W)
            sy = rng.randint(0, H)
            r = rng.randint(2, 6)
            a = rng.randint(60, 180)
            sdraw.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(255, 255, 255, a))
        bg = Image.alpha_composite(bg.convert("RGBA"), star_layer).convert("RGB")
        draw = ImageDraw.Draw(bg)

        cta_font = _load_font(90, bold=True)
        sub_font = _load_font(56)
        handle_font = _load_font(72, bold=True)
        accent = settings.brand_accent_rgb

        _draw_centered(draw, "Follow us for", W // 2, H // 2 - 200, sub_font, (200, 200, 240))
        _draw_centered(draw, "daily Roblox", W // 2, H // 2 - 90, cta_font, (255, 255, 255))
        _draw_centered(draw, "hidden gems 💎", W // 2, H // 2 + 60, cta_font, accent)
        _draw_centered(draw, settings.CHANNEL_HANDLE, W // 2, H // 2 + 220, handle_font, (255, 255, 255))
        return bg
