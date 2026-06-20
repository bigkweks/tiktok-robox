#!/usr/bin/env python3
"""One-shot DB init and seed script."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.database.connection import init_db
from src.database.models import ModelWeights
from src.database.connection import get_session


async def main():
    settings = get_settings()
    settings.ensure_dirs()
    await init_db()
    print("✓ Database schema created")

    # Insert default model weights
    async with get_session() as session:
        from sqlalchemy import select
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
            print("✓ Default model weights seeded")
        else:
            print("  Model weights already exist, skipping")

    print("\n✓ Initialization complete. Run 'python main.py serve' to start.")


if __name__ == "__main__":
    asyncio.run(main())
