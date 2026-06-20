"""
Pipeline orchestrator.

Wires all components together and runs them on schedule via APScheduler.

Schedule:
  Every 4h  → discovery run (crawl Roblox, score, update DB)
  Every 4h  → content factory (generate content for top unprocessed games)
  Every 12h → queue reprioritize + schedule posts
  Every 24h → analytics weight update
  Startup   → immediate discovery run if queue < 20 items
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from src.analytics.feedback_loop import FeedbackLoop
from src.capture.screenshot_engine import ScreenshotEngine
from src.config import get_settings
from src.content.description_engine import DescriptionEngine
from src.content.rating_engine import RatingEngine
from src.content.thumbnail_generator import ThumbnailGenerator
from src.content.video_assembler import VideoAssembler
from src.database.connection import get_session, init_db
from src.database.models import Content, Game
from src.discovery.trend_detector import TrendDetector
from src.queue.content_queue import ContentQueue

log = structlog.get_logger(__name__)


class Pipeline:
    def __init__(self):
        self._settings = get_settings()
        self._scheduler = AsyncIOScheduler()
        self._detector = TrendDetector()
        self._queue = ContentQueue()
        self._feedback = FeedbackLoop()
        self._rating = RatingEngine()
        self._description = DescriptionEngine()
        self._thumbgen = ThumbnailGenerator()
        self._video = VideoAssembler()
        self._running = False

    async def start(self) -> None:
        await init_db()
        self._settings.ensure_dirs()

        # Register scheduled jobs
        self._scheduler.add_job(
            self.run_discovery,
            "interval",
            hours=self._settings.DISCOVERY_INTERVAL_HOURS,
            id="discovery",
            name="Roblox Discovery Crawl",
            misfire_grace_time=300,
        )
        self._scheduler.add_job(
            self.run_content_factory,
            "interval",
            hours=self._settings.DISCOVERY_INTERVAL_HOURS,
            id="content_factory",
            name="Content Generation Factory",
            misfire_grace_time=300,
        )
        self._scheduler.add_job(
            self.run_queue_maintenance,
            "interval",
            hours=12,
            id="queue_maintenance",
            name="Queue Reprioritization",
        )
        self._scheduler.add_job(
            self.run_analytics_update,
            "interval",
            hours=24,
            id="analytics_update",
            name="Analytics Weight Update",
        )

        self._scheduler.start()
        self._running = True
        log.info("pipeline.started")

        # Run immediately on startup if queue is thin
        queue_size = await self._queue.queue_size()
        if queue_size < 20:
            log.info("pipeline.startup_discovery", queue_size=queue_size)
            asyncio.create_task(self.run_discovery())
            await asyncio.sleep(2)
            asyncio.create_task(self.run_content_factory())

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        self._running = False
        log.info("pipeline.stopped")

    # ── Job handlers ──────────────────────────────────────────────────

    async def run_discovery(self) -> dict:
        log.info("pipeline.discovery.start")
        try:
            stats = await self._detector.run_discovery()
            log.info("pipeline.discovery.complete", **stats)
            return stats
        except Exception as exc:
            log.error("pipeline.discovery.failed", error=str(exc))
            return {"error": str(exc)}

    async def run_content_factory(self, batch_size: int = 10) -> dict:
        """
        Generate content packages for the top unprocessed games.
        Each game gets: screenshots, thumbnail A+B, AI rating, captions, video.
        """
        log.info("pipeline.content_factory.start")
        games = await self._detector.get_top_unprocessed(limit=batch_size)
        if not games:
            log.info("pipeline.content_factory.no_games")
            return {"processed": 0}

        processed = 0
        for game in games:
            try:
                await self._generate_content_for_game(game)
                processed += 1
            except Exception as exc:
                log.error(
                    "pipeline.content_factory.game_failed",
                    game=game.name,
                    universe_id=game.universe_id,
                    error=str(exc),
                )

        log.info("pipeline.content_factory.complete", processed=processed, total=len(games))
        return {"processed": processed, "attempted": len(games)}

    async def run_queue_maintenance(self) -> None:
        await self._queue.reprioritize()
        scheduled = await self._queue.schedule_posts(days_ahead=14)
        log.info("pipeline.queue_maintenance.complete", newly_scheduled=scheduled)

    async def run_analytics_update(self) -> None:
        result = await self._feedback.run_weight_update()
        if result:
            log.info("pipeline.analytics_update.weights_updated")
        else:
            log.info("pipeline.analytics_update.no_update")

    # ── Content generation ────────────────────────────────────────────

    async def _generate_content_for_game(self, game: Game) -> Content:
        log.info("pipeline.generating", game=game.name, universe_id=game.universe_id)

        # 1. Download visual assets
        async with ScreenshotEngine() as screenshot:
            assets = await screenshot.capture_game_assets(
                universe_id=game.universe_id,
                thumbnail_url=game.thumbnail_url,
                icon_url=game.icon_url,
            )

        thumb_path = assets.get("thumbnail")
        game_thumb = Path(thumb_path) if thumb_path else None

        # 2. Generate AI rating (sync — Claude SDK)
        rating = self._rating.rate_game(
            name=game.name,
            description=game.description or "",
            visits=game.visits,
            active_players=game.active_players,
            favorites=game.favorites,
            like_ratio=game.like_ratio,
            genre=game.genre or "",
            created_at=str(game.created_at_roblox) if game.created_at_roblox else None,
            updated_at=str(game.updated_at_roblox) if game.updated_at_roblox else None,
            viral_score=game.viral_score,
        )

        # 3. Generate captions
        desc = self._description.generate(
            name=game.name,
            score=rating.score,
            label=rating.label,
            verdict=rating.verdict,
            visits=game.visits,
            genre=game.genre,
            hook_text=rating.tts_script[:80] if rating.tts_script else "",
            controversy_angle=rating.controversy_angle,
        )

        # 4. Generate thumbnails A + B
        thumb_a, thumb_b = self._thumbgen.generate_both(
            game_name=game.name,
            universe_id=game.universe_id,
            score=rating.score,
            label=rating.label,
            hook_text=rating.tts_script[:80] if rating.tts_script else "",
            thumbnail_path=game_thumb,
            thumbnail_url=game.thumbnail_url,
        )

        # 5. Compute TikTok performance predictions
        from src.discovery.viral_scorer import ViralScorer  # noqa: PLC0415
        async with get_session() as session:
            from sqlalchemy import select as sa_select  # noqa: PLC0415
            from src.database.models import ModelWeights  # noqa: PLC0415
            weights = await session.scalar(
                sa_select(ModelWeights).order_by(ModelWeights.updated_at.desc()).limit(1)
            )
        scorer = ViralScorer(weights=weights)
        from src.discovery.viral_scorer import ScoreBreakdown  # noqa: PLC0415
        breakdown = ScoreBreakdown(
            viral_score=game.viral_score,
            growth_velocity_score=game.growth_velocity_score,
            engagement_ratio_score=game.engagement_ratio_score,
            novelty_score=game.novelty_score,
            retention_proxy_score=game.retention_proxy_score,
            update_freshness_score=game.update_freshness_score,
        )
        predictions = scorer.predict_tiktok_performance(breakdown, rating.score, game.name)

        # 6. Assemble video (can take a minute)
        features = self._extract_features(game.description or "", 3)
        video_path = self._video.assemble(
            universe_id=game.universe_id,
            game_name=game.name,
            score=rating.score,
            label=rating.label,
            verdict=rating.verdict,
            hook_text=rating.tts_script[:100] if rating.tts_script else "",
            visits=game.visits,
            active_players=game.active_players,
            favorites=game.favorites,
            tts_script=rating.tts_script or "",
            thumbnail_path=game_thumb,
            thumbnail_url=game.thumbnail_url,
            features=features,
        )

        # 7. Persist content package
        import json as _json  # noqa: PLC0415
        content = Content(
            game_id=game.id,
            screenshot_path=str(thumb_path) if thumb_path else None,
            thumbnail_a_path=str(thumb_a),
            thumbnail_b_path=str(thumb_b),
            video_path=str(video_path) if video_path else None,
            rating_score=rating.score,
            rating_label=rating.label,
            rating_verdict=rating.verdict,
            rating_breakdown=_json.dumps(rating.breakdown),
            hook_text=rating.tts_script[:120] if rating.tts_script else "",
            tts_script=rating.tts_script,
            description_a=desc.description_a,
            description_b=desc.description_b,
            hashtags=_json.dumps(desc.hashtags),
            predicted_viral_score=predictions["predicted_viral_score"],
            predicted_engagement_score=predictions["predicted_engagement_score"],
            predicted_follow_conv_score=predictions["predicted_follow_conv_score"],
            predicted_novelty_score=predictions["predicted_novelty_score"],
            queue_priority=predictions["queue_priority"],
            status="pending",
        )

        async with get_session() as session:
            session.add(content)
            await session.flush()

            # Mark game as having content generated
            g = await session.get(Game, game.id)
            if g:
                g.content_generated = True

        log.info(
            "pipeline.content_generated",
            game=game.name,
            score=rating.score,
            label=rating.label,
            priority=predictions["queue_priority"],
        )
        return content

    @staticmethod
    def _extract_features(description: str, count: int) -> list[str]:
        """Extract key feature phrases from game description."""
        if not description:
            return []
        sentences = [s.strip() for s in description.replace("\n", ". ").split(".") if len(s.strip()) > 20]
        return sentences[:count]
