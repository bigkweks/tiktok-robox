#!/usr/bin/env python3
"""
TikTok Robox Pipeline — entry point.

Usage:
  python main.py serve        — start the full dashboard + pipeline
  python main.py discover     — run one discovery crawl and exit
  python main.py diagnose     — probe every Roblox endpoint + prove discovery works
  python main.py generate     — generate content for top unprocessed games
  python main.py score <uid>  — print viral score for a specific game
  python main.py init-db      — initialize the database schema
"""
from __future__ import annotations

import asyncio
import sys

import structlog
import uvicorn

# Configure structlog at import time so it's always set before any log call,
# regardless of how this module is loaded (CLI, uvicorn string import, etc.)
from src.logging_config import configure_logging as _configure_logging
_configure_logging()

log = structlog.get_logger(__name__)


def configure_logging() -> None:
    _configure_logging()


async def cmd_init_db() -> None:
    from src.database.connection import init_db
    from src.config import get_settings
    get_settings().ensure_dirs()
    await init_db()
    log.info("database.initialized")


async def cmd_discover() -> None:
    from src.discovery.trend_detector import TrendDetector
    from src.database.connection import init_db
    from src.config import get_settings
    get_settings().ensure_dirs()
    await init_db()
    detector = TrendDetector()
    stats = await detector.run_discovery()
    log.info("discovery.complete", **stats)


async def cmd_diagnose() -> None:
    """
    Probe every Roblox discovery endpoint and run a full discovery, printing a
    clear pass/fail report. Use this to prove discovery works in an environment
    that can actually reach roblox.com (e.g. Codespaces).
    """
    from src.config import get_settings
    from src.database.connection import init_db
    from src.discovery.roblox_client import RobloxClient, SEED_UNIVERSE_IDS
    from src.discovery.trend_detector import HIDDEN_GEM_KEYWORDS, TrendDetector

    def line(label: str, ok: bool, detail: str = "") -> None:
        mark = "✅ OK  " if ok else "❌ FAIL"
        print(f"  {mark}  {label:<32} {detail}")

    print("=" * 66)
    print("  ROBLOX DISCOVERY DIAGNOSTIC")
    print("=" * 66)
    print("Probing public endpoints (needs real network access to roblox.com)\n")

    async with RobloxClient() as c:
        details = await c.get_game_details_bulk(SEED_UNIVERSE_IDS[:3])
        sample = details[0] if details else {}
        line("[1] bulk game details", bool(details),
             f"{len(details)} games"
             + (f" | e.g. {sample.get('name')} visits={sample.get('visits'):,} "
                f"playing={sample.get('playing')}" if details else ""))

        votes = {}
        if details:
            votes = await c.get_votes_bulk([str(d.get("id")) for d in details])
        line("[2] bulk votes (engagement data)", bool(votes),
             f"{len(votes)} entries"
             + (f" | e.g. {list(votes.values())[0]}" if votes else " — engagement would be 0"))

        explore = await c.explore_discover(max_sorts=12)
        line("[3] explore-api homepage sorts", bool(explore),
             f"{len(explore)} universe ids  (PRIMARY source)")

        search = await c.omni_search(HIDDEN_GEM_KEYWORDS[0])
        line("[4] search-api omni-search", bool(search),
             f"{len(search)} ids for '{HIDDEN_GEM_KEYWORDS[0]}'  (SECONDARY source)")

        rec = await c.get_recommendations(SEED_UNIVERSE_IDS[0])
        line("[5] legacy recommendations", bool(rec),
             f"{len(rec)} ids" + ("" if rec else "  (expected dead — fine)"))

        glist = await c.try_games_list(genre_id=1)
        line("[6] legacy games/list", bool(glist),
             f"{len(glist)} ids" + ("" if glist else "  (expected dead — fine)"))

    print("\n" + "-" * 66)
    print("Running a full discovery + persisting to the database...\n")

    get_settings().ensure_dirs()
    await init_db()
    detector = TrendDetector()
    stats = await detector.run_discovery()
    print(f"  Discovery result: new={stats.get('new', 0)} "
          f"updated={stats.get('updated', 0)} skipped={stats.get('skipped', 0)}")

    candidates = await detector.get_top_unprocessed(limit=10)
    if candidates:
        print(f"\n  Top {len(candidates)} hidden-gem content candidates:")
        for g in candidates:
            print(f"    • {g.name[:32]:<32} "
                  f"visits={g.visits:>12,}  players={g.active_players:>6}  "
                  f"viral={g.viral_score:.2f}  like%={g.like_ratio * 100:.0f}")
    else:
        print("\n  ⚠️  No content candidates yet.")

    print("\n" + "=" * 66)
    total_new = stats.get("new", 0) + stats.get("updated", 0)
    if total_new > 0:
        print(f"  ✅ SUCCESS — discovery added/updated {total_new} real games.")
    else:
        print("  ❌ Discovery found 0 games. Check the [3]/[4] rows above:")
        print("     if those are FAIL, this environment cannot reach")
        print("     apis.roblox.com (network/firewall). Try again in Codespaces.")
    print("=" * 66)


async def cmd_generate(batch: int = 10) -> None:
    from src.scheduler.pipeline import Pipeline
    from src.config import get_settings
    get_settings().ensure_dirs()
    pipeline = Pipeline()
    await cmd_init_db()
    result = await pipeline.run_content_factory(batch_size=batch)
    log.info("generation.complete", **result)


def cmd_serve() -> None:
    from src.config import get_settings
    settings = get_settings()
    uvicorn.run(
        "src.api.dashboard:app",
        host=settings.DASHBOARD_HOST,
        port=settings.DASHBOARD_PORT,
        reload=False,
        log_level="info",
    )


def main() -> None:
    configure_logging()
    args = sys.argv[1:]
    command = args[0] if args else "serve"

    if command == "serve":
        cmd_serve()
    elif command == "discover":
        asyncio.run(cmd_discover())
    elif command == "diagnose":
        asyncio.run(cmd_diagnose())
    elif command == "generate":
        batch = int(args[1]) if len(args) > 1 else 10
        asyncio.run(cmd_generate(batch))
    elif command == "init-db":
        asyncio.run(cmd_init_db())
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
