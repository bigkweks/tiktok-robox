#!/usr/bin/env python3
"""One-shot DB init and seed script."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    # ── Friendly checks before touching anything ──────────────────────
    env_file = Path(".env")
    if not env_file.exists():
        print("")
        print("ERROR: No .env file found.")
        print("")
        print("Fix it:")
        print("  1. In the file list on the left, find '.env.example'")
        print("  2. Right-click it and choose 'Copy'")
        print("  3. Right-click the empty space and choose 'Paste'")
        print("  4. Rename the copy to just:  .env")
        print("  5. Open .env and paste your sk-ant- key on the ANTHROPIC_API_KEY line")
        print("  6. Run this script again")
        sys.exit(1)

    from src.config import get_settings
    from src.database.connection import init_db, get_session
    from src.database.models import ModelWeights
    from sqlalchemy import select

    settings = get_settings()

    if not settings.ANTHROPIC_API_KEY or not settings.ANTHROPIC_API_KEY.startswith("sk-ant-"):
        print("")
        print("WARNING: ANTHROPIC_API_KEY is missing or looks wrong.")
        print("The database will still be created, but AI features won't")
        print("work until you add your real sk-ant-... key to the .env file.")
        print("")

    print("Setting up folders...")
    settings.ensure_dirs()
    print("  Folders ready.")

    print("Creating database tables...")
    await init_db()
    print("  Database schema created.")

    print("Seeding default scoring weights...")
    async with get_session() as session:
        existing = await session.scalar(select(ModelWeights).limit(1))
        if not existing:
            session.add(ModelWeights(
                weight_growth_velocity=settings.WEIGHT_GROWTH_VELOCITY,
                weight_engagement_ratio=settings.WEIGHT_ENGAGEMENT_RATIO,
                weight_novelty=settings.WEIGHT_NOVELTY,
                weight_retention_proxy=settings.WEIGHT_RETENTION_PROXY,
                weight_update_freshness=settings.WEIGHT_UPDATE_FRESHNESS,
                weight_cross_platform=settings.WEIGHT_CROSS_PLATFORM,
                update_reason="initial_seed",
            ))
            print("  Default weights seeded.")
        else:
            print("  Weights already exist, skipping.")

    print("")
    print("==============================================")
    print("  Setup complete!")
    print("")
    print("  Next steps:")
    print("    python main.py discover    (find games)")
    print("    python main.py generate 5  (make content)")
    print("    python main.py serve       (open dashboard)")
    print("==============================================")
    print("")


if __name__ == "__main__":
    asyncio.run(main())
