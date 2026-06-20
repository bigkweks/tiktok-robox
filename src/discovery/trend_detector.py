"""
Trend detection layer.

Aggregates games from multiple Roblox discovery sources, scores them,
deduplicates, and persists new/updated games to the database.
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
    SORT_TOKENS,
    RobloxClient,
    RobloxGame,
)
from src.discovery.viral_scorer import ViralScorer

log = structlog.get_logger(__name__)

# Discovery strategy: which sort×genre combos to crawl.
# "trending × horror" finds fast-growing horror games, etc.
DISCOVERY_PLAN: list[tuple[str, str]] = [
    ("trending", "all"),
    ("trending", "horror"),
    ("trending", "adventure"),
    ("trending", "roleplay"),
    ("new", "all"),
    ("new", "adventure"),
    ("new", "horror"),
    ("popular", "all"),
    ("top_rated", "all"),
    ("updated", "all"),
]

# Keywords that signal high TikTok content potential
VIRAL_KEYWORDS: list[str] = [
    "obby",
    "horror",
    "escape",
    "murder mystery",
    "adopt me",
    "tycoon",
    "piggy",
    "brookhaven",
    "blox fruits",
    "parkour",
    "survival",
    "roleplay",
    "simulator",
    "tower of hell",
    "ragdoll",
    "liminal",
]

MAX_GAMES_PER_RUN = 500


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
        """Parallel crawl of all discovery sources."""
        tasks = []
        for sort_name, genre_name in DISCOVERY_PLAN:
            sort_token = SORT_TOKENS.get(sort_name, sort_name)
            genre_id = GENRE_IDS.get(genre_name, 0)
            tasks.append(
                client.fetch_games_with_enrichment(
                    sort_tokens=[sort_token],
                    genre_ids=[genre_id],
                    max_per_sort=80,
                )
            )

        # Keyword searches (sequential to avoid hammering)
        for kw in VIRAL_KEYWORDS[:6]:
            tasks.append(self._keyword_search_task(client, kw))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen: set[str] = set()
        games: list[RobloxGame] = []
        for result in results:
            if isinstance(result, Exception):
                log.error("trend_detector.source_failed", error=str(result))
                continue
            for game in result:
                if game.universe_id not in seen:
                    seen.add(game.universe_id)
                    games.append(game)

        log.info("trend_detector.crawled", total=len(games))
        # Cap to avoid processing too many
        return games[:MAX_GAMES_PER_RUN]

    async def _keyword_search_task(self, client: RobloxClient, keyword: str) -> list[RobloxGame]:
        try:
            raw = await client.get_games_by_keyword(keyword, max_rows=30)
            uids = [str(g.get("universeId", g.get("id", ""))) for g in raw if g.get("universeId") or g.get("id")]
            if not uids:
                return []
            details = await client.get_game_details_bulk(uids)
            thumbnails = await client.get_thumbnails(uids)
            icons = await client.get_icons(uids)
            games = []
            details_map = {str(d.get("id", "")): d for d in details}
            for g in raw:
                uid = str(g.get("universeId", g.get("id", "")))
                merged = {**g, **details_map.get(uid, {})}
                game = client._parse_game(merged)
                if game:
                    game.thumbnail_url = thumbnails.get(uid)
                    game.icon_url = icons.get(uid)
                    games.append(game)
            return games
        except Exception as exc:
            log.warning("trend_detector.keyword_failed", keyword=keyword, error=str(exc))
            return []

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
                    # Update velocity metrics
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
