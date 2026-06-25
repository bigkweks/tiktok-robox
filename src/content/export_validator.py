"""
Export validation — the last line of defence before slides leave the app.

No carousel may be exported/published if it is structurally broken. This checks
the things that would visibly embarrass the brand on TikTok:

  - wrong dimensions (TikTok expects a 1080×1920 9:16 frame; an off-size image
    gets letterboxed or cropped, clipping titles)
  - missing / unreadable / corrupt slide files
  - effectively blank slides (a render that silently failed)
  - placeholder hero art (the grey "Roblox" fallback) leaking into an export

It returns a structured result with a clear reason, so both the pipeline
(pre-persist) and the dashboard (pre-export) can refuse a bad carousel and tell
the user exactly why — fail safe, never ship broken content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import structlog
from PIL import Image

log = structlog.get_logger(__name__)

EXPORT_W, EXPORT_H = 1080, 1920          # TikTok 9:16
# The grey placeholder hero fill (carousel_generator._placeholder) is ~(40,42,60)
# at the top. If a slide's hero band is dominated by that flat grey, the real
# thumbnail never loaded.
_PLACEHOLDER_RGB = (40, 42, 60)


@dataclass
class ExportValidation:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    checked: int = 0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reasons": list(self.reasons), "checked": self.checked}


def _is_blank(img: Image.Image) -> bool:
    """A render that produced an effectively single-colour frame is blank."""
    small = img.convert("RGB").resize((24, 24))
    colors = small.getcolors(24 * 24) or []
    if not colors:
        return False
    dominant = max(colors, key=lambda c: c[0])[0]
    return dominant > (24 * 24) * 0.99      # >99% one colour → blank


def _looks_like_placeholder_hero(img: Image.Image) -> bool:
    """Sample the hero band of a game slide; if it's the flat placeholder grey,
    the real Roblox thumbnail didn't load. (Title slide is white, so this only
    trips on game slides.)"""
    rgb = img.convert("RGB")
    band = rgb.crop((0, 330, EXPORT_W, 330 + 700)).resize((20, 20))
    raw = band.tobytes()                    # R,G,B,R,G,B… (avoids deprecated getdata)
    px = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)]
    close = sum(1 for r, g, b in px
                if abs(r - _PLACEHOLDER_RGB[0]) < 14
                and abs(g - _PLACEHOLDER_RGB[1]) < 14
                and abs(b - _PLACEHOLDER_RGB[2]) < 22)
    return close > len(px) * 0.85           # band is overwhelmingly placeholder grey


def validate_carousel_export(
    slide_paths: Sequence[str | Path],
    *,
    expected_size: tuple[int, int] = (EXPORT_W, EXPORT_H),
    check_placeholder: bool = True,
) -> ExportValidation:
    """Validate every slide of a carousel for export. Returns ok=False with
    human reasons if anything would ship broken."""
    reasons: list[str] = []
    checked = 0

    if not slide_paths:
        return ExportValidation(ok=False, reasons=["No slides to export."], checked=0)

    for i, sp in enumerate(slide_paths):
        label = "title slide" if i == 0 else f"game slide {i}"
        if not sp:
            reasons.append(f"{label}: missing path")
            continue
        path = Path(sp)
        if not path.exists():
            reasons.append(f"{label}: file is missing on disk ({path.name})")
            continue
        try:
            with Image.open(path) as img:
                img.load()
                checked += 1
                if img.size != expected_size:
                    reasons.append(
                        f"{label}: wrong dimensions {img.size}, expected "
                        f"{expected_size} — would be cropped/letterboxed on TikTok")
                if _is_blank(img):
                    reasons.append(f"{label}: render is blank")
                if check_placeholder and i > 0 and _looks_like_placeholder_hero(img):
                    reasons.append(
                        f"{label}: hero is the grey placeholder — the real Roblox "
                        f"thumbnail never loaded")
        except Exception as exc:
            reasons.append(f"{label}: unreadable/corrupt image ({exc})")

    ok = not reasons
    if not ok:
        log.error("export.validation_failed", reasons=reasons, checked=checked)
    return ExportValidation(ok=ok, reasons=reasons, checked=checked)


__all__ = ["ExportValidation", "validate_carousel_export", "EXPORT_W", "EXPORT_H"]
