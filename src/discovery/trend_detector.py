"""
Trend detection layer.

Aggregates games from multiple Roblox discovery sources, scores them,
deduplicates, and persists new/updated games to the database.

Discovery strategy (403-resistant):
  1. Use all SEED_UNIVERSE_IDS ONLY for fetching recommendations — seeds are
     mega-famous games and are explicitly excluded from the content pool so we
     never generate "hidden gem" content about Adopt Me or Blox Fruits.
  2. Fan out recommendations from all 46 seeds in parallel (up to 920 IDs).
  3. Fetch full details + thumbnails for all recommendation IDs.
  4. Try genre-specific game lists as a supplementary source.
  5. Score every game and persist to DB.
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
    SEED_UNIVERSE_IDS,
    RobloxClient,
    RobloxGame,
)
from src.discovery.viral_scorer import ViralScorer

log = structlog.get_logger(__name__)

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

    async def _claude_game_discovery(self, roblox_client: RobloxClient) -> list[str]:
        """Ask Claude for underrated Roblox game names, then resolve them to universe IDs."""
        import json as _json
        import anthropic as _anthropic
        from src.config import get_settings as _cfg

        settings = _cfg()
        if not settings.ANTHROPIC_API_KEY:
            return []

        import random as _random  # noqa: PLC0415
        # Rotate the genre focus each call so repeated discoveries surface fresh games.
        genre_sets = [
            "horror, psychological thriller, survival",
            "obby, parkour, escape room",
            "fighting, pvp, battle royale",
            "roleplay, life sim, social",
            "tycoon, idle, clicker",
            "rpg, anime, fantasy adventure",
            "simulator, sandbox, creative",
            "mystery, puzzle, detective",
        ]
        focus_genres = _random.choice(genre_sets)

        prompt = (
            "You are a Roblox trend spotter for a TikTok channel called 'hidden gems'. "
            "Your picks need to cause a reaction — viewers comment 'HOW did I not know about this?!' "
            "and 'I can't believe this only has X players, it's insane'. "
            "\n\n"
            "Pick exactly 25 Roblox games that ALL meet EVERY criterion below:\n"
            "1. UNDERRATED — not a household name. Not Adopt Me, Blox Fruits, Brookhaven, "
            "Jailbreak, Murder Mystery 2, Tower of Hell, Piggy, Pet Simulator, Arsenal, "
            "Doors, Shindo Life, Anime Fighting Simulator, or any game with 1B+ visits.\n"
            "2. GENUINELY GOOD — high like ratio, polished, players actually enjoy it. "
            "Not half-finished or low-effort.\n"
            "3. ON THE RISE — getting more players lately, recently updated, growing community. "
            "Not a dead game.\n"
            "4. SHOCK FACTOR — has a unique hook or mechanic that makes someone say "
            "'wait, THIS is on Roblox?!'\n"
            "5. TIKTOK-WORTHY — the concept can be explained in one sentence and sounds exciting.\n"
            "\n"
            f"Focus this batch heavily on: {focus_genres}. Mix in a few other genres too.\n"
            "\n"
            "Think of games that real Roblox players love but outsiders haven't heard of. "
            "Be specific and varied — no two games should feel like the same experience.\n"
            "\n"
            'Return ONLY a JSON array of the exact Roblox game names. No explanations, no numbering. '
            'Example: ["Evade", "Fisch", "Type Soul"]'
        )

        loop = asyncio.get_event_loop()
        try:
            def _call_claude():
                c = _anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
                msg = c.messages.create(
                    model=settings.ANTHROPIC_MODEL,
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                )
                return msg.content[0].text.strip()

            raw_text = await loop.run_in_executor(None, _call_claude)
            start = raw_text.index("[")
            end = raw_text.rindex("]") + 1
            names: list[str] = _json.loads(raw_text[start:end])
            log.info("trend_detector.claude_names", count=len(names))
        except Exception as exc:
            log.warning("trend_detector.claude_names_failed", error=str(exc))
            return []

        # Resolve each name to universe IDs via Roblox search (concurrent)
        async def _search_one(name: str) -> list[str]:
            try:
                ids = await roblox_client.omni_search(name)
                return ids[:1]  # top result only — most relevant match for the name
            except Exception:
                return []

        results = await asyncio.gather(*[_search_one(n) for n in names])
        ids: list[str] = []
        seen_local: set[str] = set()
        for batch in results:
            for uid in batch:
                if uid not in seen_local:
                    seen_local.add(uid)
                    ids.append(uid)
        return ids

    async def _crawl_all_sources(self, client: RobloxClient) -> list[RobloxGame]:
        """
        Claude picks game names; Roblox API only resolves and enriches those picks.

        Seed IDs (mega-famous games) are excluded so they never enter the pool.
        """
        excluded: set[str] = set(SEED_UNIVERSE_IDS)

        try:
            candidate_ids = await self._claude_game_discovery(client)
        except Exception as exc:
            log.warning("trend_detector.claude_discovery_failed", error=str(exc))
            candidate_ids = []

        candidate_ids = [uid for uid in candidate_ids if uid not in excluded]
        log.info("trend_detector.candidates_collected", total=len(candidate_ids))

        if not candidate_ids:
            log.error(
                "trend_detector.no_candidates",
                hint="Claude discovery returned no IDs.",
            )
            return []

        games = await client.fetch_games_with_enrichment(candidate_ids)
        log.info("trend_detector.enriched", count=len(games))
        return games

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
        """
        Return the best TikTok CONTENT candidates that haven't had content
        generated yet.

        We do NOT just take the highest raw viral_score — that floods the
        first batch with ubiquitous mega-games (Adopt Me, Brookhaven) that
        flop as "hidden gem" videos. Instead we pull a wider pool by
        viral_score, then re-rank by tiktok_candidacy (which rewards the
        discoverable-but-not-famous sweet spot) and return the top `limit`.
        """
        async with get_session() as session:
            scorer = await self._get_scorer(session)
            result = await session.execute(
                select(Game)
                .where(Game.content_generated == False)  # noqa: E712
                .where(Game.is_blacklisted == False)  # noqa: E712
                .order_by(Game.viral_score.desc())
                .limit(max(limit * 4, 40))
            )
            pool = list(result.scalars().all())

        ranked = sorted(
            pool,
            key=lambda g: scorer.tiktok_candidacy(
                visits=g.visits,
                viral_score=g.viral_score,
                novelty_score=g.novelty_score,
                growth_velocity_score=g.growth_velocity_score,
                retention_proxy_score=g.retention_proxy_score,
            ),
            reverse=True,
        )
        return ranked[:limit]
