#!/usr/bin/env python3
"""
Render the Gazette (newspaper) cover with a REAL Roblox screenshot as the hero,
treated into the newspaper theme three ways so the colours match the cream/ink
front page.

Usage:  python scripts/render_newspaper.py

In production, swap `HERO_SRC` for the real Roblox homepage thumbnail (URL or
PIL image) of the drop's #1 game — theme_duotone maps it into the Gazette palette.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.content.carousel_variants import (
    GradeReportVariant, theme_duotone, _render_html,
)

OUT = Path("output/variant_demos/3_grade_report")
OUT.mkdir(parents=True, exist_ok=True)

HERO_SRC = "assets/demo/hero_jailbreak.jpg"

HEADLINE = "The 5 Roblox Games The Cops Can't Catch"
DECK = ("An independent review desk played, scored and graded the gems buried "
        "under the front page. The verdicts are not kind to the popular list.")
CAPTION = "PICTURED: this week's No. 1, graded S"

# Three theme-matched press treatments to choose from.
TREATMENTS = ["newsprint", "sepia", "ember"]


def main():
    v = GradeReportVariant()
    print("\n📰  Rendering Gazette cover · 3 theme-matched hero treatments\n")
    for t in TREATMENTS:
        hero = theme_duotone(HERO_SRC, treatment=t, contrast=1.30)
        html = v.newspaper_cover_html(
            headline=HEADLINE, deck=DECK, caption=CAPTION, part=12,
            hero=hero, photo_filter="none",   # duotone already baked in
        )
        path = OUT / f"slide_00_cover_{t}.png"
        _render_html(html).save(str(path))
        print(f"  ✓ {t:9s} → {path}")

    # Default cover = sepia (closest harmony with the cream stock)
    hero = theme_duotone(HERO_SRC, treatment="sepia", contrast=1.30)
    _render_html(v.newspaper_cover_html(
        headline=HEADLINE, deck=DECK, caption=CAPTION, part=12,
        hero=hero, photo_filter="none",
    )).save(str(OUT / "slide_00_cover.png"))
    print(f"  ✓ default   → {OUT / 'slide_00_cover.png'} (sepia)\n")


if __name__ == "__main__":
    main()
