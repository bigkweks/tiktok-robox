#!/usr/bin/env python3
"""
Render demo slides for all three carousel variants.

Usage:  python scripts/render_variants.py

Outputs slides to output/variant_demos/  — one folder per variant.
Each variant gets: cover + 1 demo game slide.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.content.carousel_variants import (
    ScoutReportVariant,
    TierDropVariant,
    GradeReportVariant,
    _render_html,
)


# ── Demo game data ────────────────────────────────────────────────────────────

DEMO_GAME_1 = {
    "name": "Tower of Misery",
    "creator": "xXBuilderXx",
    "score": 9.2,
    "verdict": "the most mechanically satisfying obby on the platform right now",
    "hours_tested": 23,
    "active": 14,
    "like_pct": 94,
    "visits_m": 3.7,
    "why1": "checkpoints feel earned, not handed out — real tension",
    "why2": "surprisingly polished level design for a solo dev",
    "tier": "S",
    "why_tier": "3 hours in and i genuinely could not log off",
    "overall_grade": "S",
    "subgrades": {"Fun": "S", "Value": "A+", "Unique": "A+", "Social": "B"},
    "assessment": "Mechanically sound in ways most funded studios miss. Tower design alone earns the S.",
    "recommended": True,
}

DEMO_GAME_2 = {
    "name": "Nocturnia: Shadow Realms",
    "creator": "DarkCraft Studios",
    "score": 8.6,
    "verdict": "horror that actually scared me — twice",
    "hours_tested": 17,
    "active": 8,
    "like_pct": 89,
    "visits_m": 1.2,
    "why1": "atmosphere is genuinely unsettling — uses sound design most Roblox horror ignores",
    "why2": "each area tells its own story without a single text block",
    "tier": "A+",
    "why_tier": "best horror atmosphere since the early Doors days",
    "overall_grade": "A+",
    "subgrades": {"Fun": "A+", "Value": "S", "Unique": "S", "Social": "C"},
    "assessment": "Exceeds expectations in atmosphere and worldbuilding. Solo play is where this shines.",
    "recommended": True,
}

OUT = Path("output/variant_demos")


def render_variant1():
    v = ScoutReportVariant()
    folder = OUT / "1_scout_report"
    folder.mkdir(parents=True, exist_ok=True)

    print("  ▸ Scout Report — cover …")
    cover = v.cover_html(
        hook="games i spent 23+ hours testing so you don't have to",
        value="actually good roblox games to play",
        part=12,
    )
    _render_html(cover).save(str(folder / "slide_00_cover.png"))

    print("  ▸ Scout Report — game slide …")
    g = DEMO_GAME_1
    slide = v.game_slide_html(
        name=g["name"], creator=g["creator"], score=g["score"],
        verdict=g["verdict"], hours_tested=g["hours_tested"],
        active=g["active"], like_pct=g["like_pct"],
        visits_m=g["visits_m"], why1=g["why1"], why2=g["why2"],
        part=12, index=1,
    )
    _render_html(slide).save(str(folder / "slide_01_game.png"))
    print(f"  ✓ Scout Report → {folder}")


def render_variant2():
    v = TierDropVariant()
    folder = OUT / "2_tier_drop"
    folder.mkdir(parents=True, exist_ok=True)

    print("  ▸ Tier Drop — cover …")
    cover = v.cover_html(
        hook="you're sleeping on every single one of these",
        part=12,
    )
    _render_html(cover).save(str(folder / "slide_00_cover.png"))

    print("  ▸ Tier Drop — S-tier game slide …")
    g = DEMO_GAME_1
    slide_s = v.game_slide_html(
        name=g["name"], creator=g["creator"],
        tier="S", why=g["why_tier"],
        visits_m=g["visits_m"], active=g["active"],
        part=12, index=1,
    )
    _render_html(slide_s).save(str(folder / "slide_01_s_tier.png"))

    print("  ▸ Tier Drop — A+ game slide …")
    g2 = DEMO_GAME_2
    slide_a = v.game_slide_html(
        name=g2["name"], creator=g2["creator"],
        tier="A+", why=g2["why_tier"],
        visits_m=g2["visits_m"], active=g2["active"],
        part=12, index=2,
    )
    _render_html(slide_a).save(str(folder / "slide_02_a_tier.png"))
    print(f"  ✓ Tier Drop → {folder}")


def render_variant3():
    v = GradeReportVariant()
    folder = OUT / "3_grade_report"
    folder.mkdir(parents=True, exist_ok=True)

    print("  ▸ Grade Report — cover …")
    cover = v.cover_html(
        hook="nobody asked but i graded these anyway",
        part=12,
    )
    _render_html(cover).save(str(folder / "slide_00_cover.png"))

    print("  ▸ Grade Report — S grade game slide …")
    g = DEMO_GAME_1
    slide_s = v.game_slide_html(
        name=g["name"], creator=g["creator"],
        overall_grade=g["overall_grade"], subgrades=g["subgrades"],
        assessment=g["assessment"], visits_m=g["visits_m"],
        recommended=g["recommended"], part=12, index=1,
    )
    _render_html(slide_s).save(str(folder / "slide_01_s_grade.png"))

    print("  ▸ Grade Report — A+ grade game slide …")
    g2 = DEMO_GAME_2
    slide_a = v.game_slide_html(
        name=g2["name"], creator=g2["creator"],
        overall_grade=g2["overall_grade"], subgrades=g2["subgrades"],
        assessment=g2["assessment"], visits_m=g2["visits_m"],
        recommended=g2["recommended"], part=12, index=2,
    )
    _render_html(slide_a).save(str(folder / "slide_02_a_grade.png"))
    print(f"  ✓ Grade Report → {folder}")


def main():
    print("\n🎨  Rendering 3 carousel variants …\n")

    print("① SCOUT REPORT (dark · reviewer-authority)")
    render_variant1()

    print("\n② TIER DROP (dramatic · competitive ranking)")
    render_variant2()

    print("\n③ GRADE REPORT (white · academic authority)")
    render_variant3()

    print("\n✅  All 8 slides saved to output/variant_demos/")
    print("   Open them with any image viewer.\n")


if __name__ == "__main__":
    main()
