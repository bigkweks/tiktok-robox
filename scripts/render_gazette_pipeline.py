#!/usr/bin/env python3
"""
End-to-end demo of the Gazette pipeline.

Simulates what the real pipeline does:
  1. Builds five CarouselGame objects (with realistic score/stat/breakdown data)
  2. Calls GazetteCarouselGenerator.generate() — the same call the pipeline makes
  3. Writes all slides to output/gazette_pipeline_demo/

In production the game data comes from the database (real Roblox discovery +
AI rating).  Here we use the synthetic demo scenes so the layout can be judged
with real game-shaped rasters before wiring the Roblox CDN.

Usage:  python scripts/render_gazette_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.content.carousel_generator import CarouselGame
from src.content.gazette_generator import GazetteCarouselGenerator
from scripts._demo_scenes import game_scene, roblox_hero

OUT = Path("output/gazette_pipeline_demo")
OUT.mkdir(parents=True, exist_ok=True)

# ── Demo art (production = real Roblox thumbnail URL from CDN) ────────────────
# We pass PIL images here so the demo works offline.  In production,
# GazetteCarouselGenerator receives thumbnail_url strings (http/https),
# and img_to_uri() passes them straight through to Chromium for real-CDN loading.
SCENES = {
    "jailbreak": game_scene("dusk", seed=7),
    "tower":     game_scene("obby", seed=11),
    "nocturnia": game_scene("horror", seed=23),
    "blox":      game_scene("obby", seed=31),
    "doors":     game_scene("horror", seed=17),
}

# Five games with realistic AI rating data.  Retention arc: opener strong,
# middle dips, best game last (the pipeline's _retention_order() does this in
# production — we replicate it manually here so the demo shows the same shape).
GAMES = [
    CarouselGame(
        name="Jailbreak",
        creator="Badimo",
        score=8.6,
        carousel_caption="GTA in roblox and it actually slaps",
        like_ratio=0.91,
        active_players=18_400,
        thumbnail_url=None,   # replaced below with PIL image
        icon_url=None,
        genre="Action",
        visits=8_300_000_000,
        blurb="Better open-world design than half the funded studios out there.",
        breakdown={
            "fun_factor": 9.0, "replayability": 8.8, "originality": 7.5,
            "visual_quality": 8.4, "community": 9.2,
        },
    ),
    CarouselGame(
        name="Blox Fruits",
        creator="mygame43",
        score=7.4,
        carousel_caption="anime grind but the combat is actually decent",
        like_ratio=0.84,
        active_players=61_000,
        thumbnail_url=None,
        icon_url=None,
        genre="RPG",
        visits=22_000_000_000,
        blurb="The numbers are enormous but the design hasn't kept up.",
        breakdown={
            "fun_factor": 7.8, "replayability": 8.2, "originality": 5.5,
            "visual_quality": 7.0, "community": 8.8,
        },
    ),
    CarouselGame(
        name="Nocturnia: Shadow Realms",
        creator="DarkCraft Studios",
        score=9.1,
        carousel_caption="horror that actually scared me",
        like_ratio=0.96,
        active_players=8_200,
        thumbnail_url=None,
        icon_url=None,
        genre="Horror",
        visits=1_200_000,
        blurb="Exceeds expectation in atmosphere and worldbuilding every single room.",
        breakdown={
            "fun_factor": 9.2, "replayability": 8.6, "originality": 9.5,
            "visual_quality": 9.0, "community": 8.0,
        },
    ),
    CarouselGame(
        name="Tower of Misery",
        creator="xXBuilderXx",
        score=9.6,
        carousel_caption="hardest obby on the platform right now",
        like_ratio=0.98,
        active_players=14_200,
        thumbnail_url=None,
        icon_url=None,
        genre="Obby",
        visits=3_700_000,
        blurb="Mechanically sound in ways most funded studios miss. The S is earned.",
        breakdown={
            "fun_factor": 9.8, "replayability": 9.4, "originality": 9.2,
            "visual_quality": 8.8, "community": 9.0,
        },
    ),
    CarouselGame(
        name="Doors",
        creator="LSPLASH",
        score=8.2,
        carousel_caption="horror puzzle that actually has depth",
        like_ratio=0.93,
        active_players=23_500,
        thumbnail_url=None,
        icon_url=None,
        genre="Horror",
        visits=2_100_000_000,
        blurb="The best horror atmosphere on Roblox since the early days.",
        breakdown={
            "fun_factor": 8.5, "replayability": 7.8, "originality": 8.8,
            "visual_quality": 8.6, "community": 8.2,
        },
    ),
]

# Patch in PIL scenes as if they were URLs (img_to_uri handles PIL→data URI)
SCENES_LIST = [
    SCENES["jailbreak"],
    SCENES["blox"],
    SCENES["nocturnia"],
    SCENES["tower"],
    SCENES["doors"],
]
for game, scene in zip(GAMES, SCENES_LIST):
    game.thumbnail_url = scene   # GazetteCarouselGenerator checks for http(s); PIL → embed


def main():
    print("\n📰  Gazette Pipeline Demo\n")
    print("  Games (retention arc):")
    for g in GAMES:
        print(f"    {g.score:.1f}  {g.name}")

    gen = GazetteCarouselGenerator()
    report = gen.generate(
        games=GAMES,
        edition="Hidden Gems",
        part_number=12,
        output_dir=OUT,
        slug="gazette_demo",
        cover_hook="no one is talking about these roblox games",
    )

    print(f"\n  Slides rendered ({len(report.slides)}):")
    for p in report.slides:
        print(f"    ✓ {p.name}")

    print(f"\n  Thumbnails OK : {report.successful_thumbnails} / {report.game_slide_count}")
    print(f"  Report OK     : {report.ok}")
    print(f"\n  → output/ → {OUT.relative_to('.')} /\n")


if __name__ == "__main__":
    main()
