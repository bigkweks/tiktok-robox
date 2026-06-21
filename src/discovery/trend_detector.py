"""
Trend detection layer.

Aggregates games from multiple Roblox discovery sources, scores them,
deduplicates, and persists new/updated games to the database.

Discovery strategy (403-resistant):
  1. Fetch details for all SEED_UNIVERSE_IDS via the fully-public /v1/games endpoint
  2. Expand by fetching recommendations from a rotating subset of seeds
  3. Score every game and persist to DB
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_session
from src.database.models import CrawlLog, Game, ModelWeights
from src.discovery.roblox_client import (
    GENRE_IDS,
    SEED_UNIVERSE_IDS,
    RobloxClient,
    RobloxGame,
)
from src.discovery.viral_scorer import ViralScorer

log = structlog.get_logger(__name__)

MAX_GAMES_PER_RUN = 500

# How many seed games to fan out for recommendations each run
RECOMMENDATION_SEEDS = 10


class TrendDetector:
    def __init__(self):
        self._scorer: Optional[ViralScorer] = None

    async def _get_scorer(self, session: AsyncSession) -> ViralScorer:
        if self._scorer is None:
            weights = await session.scalar(
                select(ModelWeights).order_by(ModelWeights.updated_at.desc()).limit(1)
            )
            self._scorer = ViralScorer(weights=weights)
        return self._scorer

    async def run_discovery(self) -> dict[str, int]:
        """
        Full discovery pipeline: crawl → score → persist.
        Returns summary stats.
        """
        async with RobloxClient() as client:
            raw_games = await self._crawl_all_sources(client)

        async with get_session() as session:
            scorer = await self._get_scorer(session)
            stats = await self._process_games(session, raw_games, scorer)

        log.info("trend_detector.run_complete", **stats)
        return stats

    async def _crawl_all_sources(self, client: RobloxClient) -> list[RobloxGame]:
        """
        Seed-based discovery using only public Roblox endpoints.
        """
        seen: set[str] = set()
        games: list[RobloxGame] = []

        # Step 1: fetch all seed games (public endpoint, always works)
        log.info("trend_detector.fetching_seeds", count=len(SEED_UNIVERSE_IDS))
        seed_games = await client.fetch_games_with_enrichment(SEED_UNIVERSE_IDS)
        for g in seed_games:
            if g.universe_id not in seen:
                seen.add(g.universe_id)
                games.append(g)
        log.info("trend_detector.seeds_fetched", count=len(games))

        # Step 2: expand via recommendations from a rotating subset of seeds
        recommendation_seeds = SEED_UNIVERSE_IDS[:RECOMMENDATION_SEEDS]
        rec_tasks = [
            client.get_recommendations(uid, max_rows=20)
            for uid in recommendation_seeds
        ]
        rec_results = await asyncio.gather(*rec_tasks, return_exceptions=True)

        extra_ids: list[str] = []
        for result in rec_results:
            if isinstance(result, Exception):
                log.warning("trend_detector.rec_failed", error=str(result))
                continue
            for uid in result:
                if uid and uid not in seen:
                    seen.add(uid)
                    extra_ids.append(uid)

        if extra_ids:
            log.info("trend_detector.fetching_recommendations", count=len(extra_ids))
            rec_games = await client.fetch_games_with_enrichment(extra_ids)
            games.extend(rec_games)
            log.info("trend_detector.recommendations_fetched", total=len(games))

        # Step 3: optionally try the authenticated games/list endpoint (may 403)
        sort_ids = await client.try_get_sort_tokens()
        if sort_ids:
            log.info("trend_detector.sort_tokens_available", count=len(sort_ids))
            for token in sort_ids[:3]:
                uids = await client.try_games_list(sort_token=token, max_rows=80)
                new_uids = [u for u in uids if u not in seen]
                if new_uids:
                    extra = await client.fetch_games_with_enrichment(new_uids)
                    for g in extra:
                        if g.universe_id not in seen:
                            seen.add(g.universe_id)
                            games.append(g)

        log.info("trend_detector.crawled", total=len(games))
        return games[:MAX_GAMES_PER_RUN]

    async def _process_games(
        self,
        session: AsyncSession,
        games: list[RobloxGame],
        scorer: ViralScorer,
    ) -> dict[str, int]:
        new_count = updated_count = skipped_count = 0
        now = datetime.now(timezone.utc)

        for raw_game in games:
            try:
                existing = await session.scalar(
                    select(Game).where(Game.universe_id == raw_game.universe_id)
                )

                if existing:
                    existing.visits_24h_ago = existing.visits
                    existing.players_24h_ago = existing.active_players
                    existing.favorites_24h_ago = existing.favorites

                    existing.visits = raw_game.visits
                    existing.active_players = raw_game.active_players
                    existing.favorites = raw_game.favorites
                    existing.like_count = raw_game.like_count
                    existing.dislike_count = raw_game.dislike_count
                    existing.like_ratio = raw_game.like_ratio
                    existing.updated_at_roblox = raw_game.updated_at
                    existing.last_crawled_at = now
                    existing.crawl_count += 1

                    if raw_game.thumbnail_url:
                        existing.thumbnail_url = raw_game.thumbnail_url
                    if raw_game.icon_url:
                        existing.icon_url = raw_game.icon_url

                    breakdown = scorer.score(
                        visits=raw_game.visits,
                        active_players=raw_game.active_players,
                        favorites=raw_game.favorites,
                        like_count=raw_game.like_count,
                        dislike_count=raw_game.dislike_count,
                        created_at=raw_game.created_at,
                        updated_at=raw_game.updated_at,
                        visits_24h_ago=existing.visits_24h_ago,
                        players_24h_ago=existing.players_24h_ago,
                    )
                    existing.viral_score = breakdown.viral_score
                    existing.growth_velocity_score = breakdown.growth_velocity_score
                    existing.engagement_ratio_score = breakdown.engagement_ratio_score
                    existing.novelty_score = breakdown.novelty_score
                    existing.retention_proxy_score = breakdown.retention_proxy_score
                    existing.update_freshness_score = breakdown.update_freshness_score

                    session.add(
                        CrawlLog(
                            game_id=existing.id,
                            crawled_at=now,
                            visits=raw_game.visits,
                            active_players=raw_game.active_players,
                            favorites=raw_game.favorites,
                            like_count=raw_game.like_count,
                            dislike_count=raw_game.dislike_count,
                        )
                    )
                    updated_count += 1

                else:
                    breakdown = scorer.score(
                        visits=raw_game.visits,
                        active_players=raw_game.active_players,
                        favorites=raw_game.favorites,
                        like_count=raw_game.like_count,
                        dislike_count=raw_game.dislike_count,
                        created_at=raw_game.created_at,
                        updated_at=raw_game.updated_at,
                    )

                    game = Game(
                        universe_id=raw_game.universe_id,
                        place_id=raw_game.place_id,
                        name=raw_game.name,
                        url=raw_game.url,
                        description=raw_game.description,
                        creator_name=raw_game.creator_name,
                        creator_id=raw_game.creator_id,
                        genre=raw_game.genre,
                        thumbnail_url=raw_game.thumbnail_url,
                        icon_url=raw_game.icon_url,
                        visits=raw_game.visits,
                        active_players=raw_game.active_players,
                        max_players=raw_game.max_players,
                        favorites=raw_game.favorites,
                        like_count=raw_game.like_count,
                        dislike_count=raw_game.dislike_count,
                        like_ratio=raw_game.like_ratio,
                        created_at_roblox=raw_game.created_at,
                        updated_at_roblox=raw_game.updated_at,
                        last_crawled_at=now,
                        viral_score=breakdown.viral_score,
                        growth_velocity_score=breakdown.growth_velocity_score,
                        engagement_ratio_score=breakdown.engagement_ratio_score,
                        novelty_score=breakdown.novelty_score,
                        retention_proxy_score=breakdown.retention_proxy_score,
                        update_freshness_score=breakdown.update_freshness_score,
                    )
                    session.add(game)
                    await session.flush()

                    session.add(
                        CrawlLog(
                            game_id=game.id,
                            crawled_at=now,
                            visits=raw_game.visits,
                            active_players=raw_game.active_players,
                            favorites=raw_game.favorites,
                            like_count=raw_game.like_count,
                            dislike_count=raw_game.dislike_count,
                        )
                    )
                    new_count += 1

            except Exception as exc:
                log.error(
                    "trend_detector.process_game_failed",
                    universe_id=raw_game.universe_id,
                    name=raw_game.name,
                    error=str(exc),
                )
                skipped_count += 1

        return {"new": new_count, "updated": updated_count, "skipped": skipped_count}

    async def get_top_unprocessed(self, limit: int = 20) -> list[Game]:
        """Return top-scored games that haven't had content generated yet."""
        async with get_session() as session:
            result = await session.execute(
                select(Game)
                .where(Game.content_generated == False)  # noqa: E712
                .where(Game.is_blacklisted == False)  # noqa: E712
                .order_by(Game.viral_score.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
