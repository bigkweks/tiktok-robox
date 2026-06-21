#!/usr/bin/env python3
"""
TikTok Robox Pipeline — entry point.

Usage:
  python main.py serve        — start the full dashboard + pipeline
  python main.py discover     — run one discovery crawl and exit
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
