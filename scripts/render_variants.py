#!/usr/bin/env python3
"""
Render demo slides for all three carousel variants (editorial v2).

Usage:  python scripts/render_variants.py

Outputs to output/variant_demos/ — one folder per variant.
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

OUT = Path("output/variant_demos")


def render_scout():
    v = ScoutReportVariant()
    folder = OUT / "1_scout_report"
    folder.mkdir(parents=True, exist_ok=True)

    print("  ▸ cover …")
    _render_html(v.cover_html(
        hook_main="The games",
        hook_em="worth your night",
        sub="five Roblox titles I actually sat down and played — "
            "logged, scored, and written up.",
        part=12,
    )).save(str(folder / "slide_00_cover.png"))

    print("  ▸ game slide …")
    _render_html(v.game_slide_html(
        name="Tower of",
        name_em="Misery",
        creator="xXBuilderXx",
        score=9.2,
        verdict="the most mechanically honest obby on the platform right now — "
                "every checkpoint is earned",
        hours=23,
        active_label="14K",
        like_pct=94,
        visits_label="3.7M",
        note1="checkpoints feel earned, never handed out — real tension on every jump",
        note2="level design is sharper than most studio-funded obbies",
        part=12, index=1,
    )).save(str(folder / "slide_01_game.png"))
    print(f"  ✓ {folder}")


def render_tier():
    v = TierDropVariant()
    folder = OUT / "2_tier_drop"
    folder.mkdir(parents=True, exist_ok=True)

    print("  ▸ cover …")
    _render_html(v.cover_html(
        tagline="you have been sleeping on every single one of these",
        part=12,
    )).save(str(folder / "slide_00_cover.png"))

    print("  ▸ S-tier slide …")
    _render_html(v.game_slide_html(
        name="Tower of Misery",
        creator="xXBuilderXx",
        tier="S",
        why="three hours in and I genuinely could not bring myself to log off",
        visits_label="3.7M",
        active_label="14K",
        part=12, index=1,
    )).save(str(folder / "slide_01_s_tier.png"))

    print("  ▸ A-tier slide …")
    _render_html(v.game_slide_html(
        name="Nocturnia: Shadow Realms",
        creator="DarkCraft Studios",
        tier="A+",
        why="the best horror atmosphere on Roblox since the early Doors days",
        visits_label="1.2M",
        active_label="8K",
        part=12, index=2,
    )).save(str(folder / "slide_02_a_tier.png"))
    print(f"  ✓ {folder}")


def render_grade():
    v = GradeReportVariant()
    folder = OUT / "3_grade_report"
    folder.mkdir(parents=True, exist_ok=True)

    print("  ▸ cover …")
    _render_html(v.cover_html(
        l1="the official",
        l3="game grades",
        sub="nobody asked for a grading scale. I built one anyway, "
            "and these five earned their marks.",
        part=12,
    )).save(str(folder / "slide_00_cover.png"))

    print("  ▸ S grade slide …")
    _render_html(v.game_slide_html(
        name="Tower of Misery",
        creator="xXBuilderXx",
        overall="S",
        subgrades={"Fun": "S", "Value": "A+", "Original": "A+", "Social": "B"},
        assessment="Mechanically sound in ways most funded studios miss. "
                   "The tower design alone earns the S.",
        visits_label="3.7M",
        recommended=True,
        part=12, index=1,
    )).save(str(folder / "slide_01_s_grade.png"))

    print("  ▸ A+ grade slide …")
    _render_html(v.game_slide_html(
        name="Nocturnia: Shadow Realms",
        creator="DarkCraft Studios",
        overall="A+",
        subgrades={"Fun": "A+", "Value": "S", "Original": "S", "Social": "C"},
        assessment="Exceeds expectation in atmosphere and worldbuilding. "
                   "Solo play is where this one truly shines.",
        visits_label="1.2M",
        recommended=True,
        part=12, index=2,
    )).save(str(folder / "slide_02_a_grade.png"))
    print(f"  ✓ {folder}")


def main():
    print("\n🎨  Rendering 3 editorial carousel variants …\n")
    print("① SCOUT REPORT (dark dossier · Fraunces + Space Grotesk)")
    render_scout()
    print("\n② TIER DROP (black stage · flat stamped tiers)")
    render_tier()
    print("\n③ GRADE REPORT (cream certificate · Fraunces serif)")
    render_grade()
    print("\n✅  8 slides → output/variant_demos/\n")


if __name__ == "__main__":
    main()
