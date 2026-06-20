"""
Async Roblox API client.

All public endpoints — no authentication required. We use exponential
backoff via tenacity so transient 429s / 5xx never crash the pipeline.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger(__name__)

_RETRY = dict(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)

ROBLOX_GAMES_BASE = "https://games.roblox.com/v1"
ROBLOX_THUMBS_BASE = "https://thumbnails.roblox.com/v1"
ROBLOX_ECONOMY_BASE = "https://economy.roblox.com/v1"

# Sort tokens discovered from Roblox web app
SORT_TOKENS: dict[str, str] = {
    "popular": "PopularSort",
    "trending": "TrendingSort",
    "top_rated": "TopRatedSort",
    "new": "NewSort",
    "updated": "RecentlyUpdatedSort",
    "featured": "FeaturedSort",
}

GENRE_IDS: dict[str, int] = {
    "all": 0,
    "adventure": 1,
    "tutorial": 2,
    "fighting": 4,
    "roleplay": 5,
    "building": 6,
    "horror": 8,
    "town_and_city": 9,
    "military": 11,
    "comedy": 12,
    "medieval": 13,
    "sci_fi": 14,
    "naval": 15,
    "fps": 17,
    "rpg": 18,
    "sports": 19,
    "ninja": 20,
    "unknown": 21,
}


@dataclass
class RobloxGame:
    universe_id: str
    place_id: str
    name: str
    description: str
    creator_name: str
    creator_id: str
    genre: str
    visits: int
    active_players: int
    max_players: int
    favorites: int
    like_count: int
    dislike_count: int
    like_ratio: float
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    url: str
    thumbnail_url: Optional[str] = None
    icon_url: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


class RobloxClient:
    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TikTokRobox/1.0)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    async def __aenter__(self) -> RobloxClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()

    @retry(**_RETRY)
    async def _get(self, url: str, **params: Any) -> Any:
        resp = await self._client.get(url, params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "10"))
            log.warning("roblox.rate_limited", retry_after=retry_after)
            await asyncio.sleep(retry_after)
            resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_game_sorts(self) -> list[dict[str, Any]]:
        """Fetch available game sort categories from Roblox."""
        data = await self._get(f"{ROBLOX_GAMES_BASE}/games/sorts")
        return data.get("sorts", [])

    async def get_games_by_sort(
        self,
        sort_token: str,
        genre_id: int = 0,
        max_rows: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Retrieve game listings by sort. Returns raw game dicts from the
        Roblox games/list endpoint.
        """
        data = await self._get(
            f"{ROBLOX_GAMES_BASE}/games/list",
            **{
                "model.sortToken": sort_token,
                "model.genreFilter": genre_id,
                "model.maxRows": max_rows,
                "model.startRows": 0,
            },
        )
        return data.get("games", [])

    async def get_games_by_keyword(self, keyword: str, max_rows: int = 50) -> list[dict[str, Any]]:
        data = await self._get(
            f"{ROBLOX_GAMES_BASE}/games/list",
            **{
                "model.keyword": keyword,
                "model.maxRows": max_rows,
                "model.startRows": 0,
            },
        )
        return data.get("games", [])

    async def get_game_details_bulk(self, universe_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch detailed game data for up to 100 universe IDs at once."""
        if not universe_ids:
            return []
        chunks = [universe_ids[i : i + 100] for i in range(0, len(universe_ids), 100)]
        results = []
        for chunk in chunks:
            data = await self._get(
                f"{ROBLOX_GAMES_BASE}/games",
                universeIds=",".join(chunk),
            )
            results.extend(data.get("data", []))
        return results

    async def get_votes(self, universe_id: str) -> dict[str, int]:
        """Get upvotes and downvotes for a game."""
        try:
            data = await self._get(f"{ROBLOX_GAMES_BASE}/games/{universe_id}/votes")
            return {
                "like_count": data.get("upVotes", 0),
                "dislike_count": data.get("downVotes", 0),
            }
        except Exception as exc:
            log.warning("roblox.votes_failed", universe_id=universe_id, error=str(exc))
            return {"like_count": 0, "dislike_count": 0}

    async def get_thumbnails(self, universe_ids: list[str]) -> dict[str, str]:
        """Return {universe_id: thumbnail_url} for the given IDs."""
        if not universe_ids:
            return {}
        chunks = [universe_ids[i : i + 50] for i in range(0, len(universe_ids), 50)]
        result: dict[str, str] = {}
        for chunk in chunks:
            try:
                data = await self._get(
                    f"{ROBLOX_THUMBS_BASE}/games/multiget/thumbnails",
                    universeIds=",".join(chunk),
                    countPerUniverse=1,
                    defaults="true",
                    size="768x432",
                    format="Png",
                    isCircular="false",
                )
                for item in data.get("data", []):
                    uid = str(item.get("universeId", ""))
                    thumbnails = item.get("thumbnails", [])
                    if thumbnails:
                        result[uid] = thumbnails[0].get("imageUrl", "")
            except Exception as exc:
                log.warning("roblox.thumbnails_failed", error=str(exc))
        return result

    async def get_icons(self, universe_ids: list[str]) -> dict[str, str]:
        """Return {universe_id: icon_url}."""
        if not universe_ids:
            return {}
        chunks = [universe_ids[i : i + 100] for i in range(0, len(universe_ids), 100)]
        result: dict[str, str] = {}
        for chunk in chunks:
            try:
                data = await self._get(
                    f"{ROBLOX_THUMBS_BASE}/games/icons",
                    universeIds=",".join(chunk),
                    returnPolicy="PlaceHolder",
                    size="512x512",
                    format="Png",
                    isCircular="false",
                )
                for item in data.get("data", []):
                    uid = str(item.get("universeId", ""))
                    result[uid] = item.get("imageUrl", "")
            except Exception as exc:
                log.warning("roblox.icons_failed", error=str(exc))
        return result

    def _parse_game(self, raw: dict[str, Any]) -> Optional[RobloxGame]:
        try:
            uid = str(raw.get("universeId", raw.get("id", "")))
            if not uid:
                return None

            place_id = str(raw.get("rootPlaceId", raw.get("placeId", uid)))
            name = raw.get("name", "Unknown")
            votes = raw.get("voteData", {})
            up = int(votes.get("upVotes", raw.get("upVotes", 0)))
            down = int(votes.get("downVotes", raw.get("downVotes", 0)))
            total = up + down
            like_ratio = (up / total) if total > 0 else 0.0

            created_raw = raw.get("created")
            updated_raw = raw.get("updated")

            def _parse_dt(s: Any) -> Optional[datetime]:
                if not s:
                    return None
                try:
                    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
                except ValueError:
                    return None

            creator = raw.get("creator", {})

            return RobloxGame(
                universe_id=uid,
                place_id=place_id,
                name=name,
                description=raw.get("description", "") or "",
                creator_name=creator.get("name", raw.get("creatorName", "")),
                creator_id=str(creator.get("id", raw.get("creatorId", ""))),
                genre=raw.get("genre", ""),
                visits=int(raw.get("visits", 0)),
                active_players=int(raw.get("playing", 0)),
                max_players=int(raw.get("maxPlayers", 0)),
                favorites=int(raw.get("favoritedCount", raw.get("favorites", 0))),
                like_count=up,
                dislike_count=down,
                like_ratio=like_ratio,
                created_at=_parse_dt(created_raw),
                updated_at=_parse_dt(updated_raw),
                url=f"https://www.roblox.com/games/{place_id}",
                raw=raw,
            )
        except Exception as exc:
            log.warning("roblox.parse_failed", error=str(exc), raw=str(raw)[:200])
            return None

    async def fetch_games_with_enrichment(
        self,
        sort_tokens: list[str],
        genre_ids: list[int] | None = None,
        max_per_sort: int = 100,
    ) -> list[RobloxGame]:
        """
        High-level call: fetch multiple sort categories, deduplicate,
        enrich with votes + thumbnails, return parsed RobloxGame list.
        """
        if genre_ids is None:
            genre_ids = [0]

        seen: set[str] = set()
        raw_games: list[dict[str, Any]] = []

        for sort_token in sort_tokens:
            for genre_id in genre_ids:
                try:
                    games = await self.get_games_by_sort(sort_token, genre_id, max_per_sort)
                    for g in games:
                        uid = str(g.get("universeId", g.get("id", "")))
                        if uid and uid not in seen:
                            seen.add(uid)
                            raw_games.append(g)
                    await asyncio.sleep(0.5)  # be polite to Roblox servers
                except Exception as exc:
                    log.error("roblox.fetch_sort_failed", sort=sort_token, genre=genre_id, error=str(exc))

        if not raw_games:
            return []

        universe_ids = [str(g.get("universeId", g.get("id", ""))) for g in raw_games]

        # Enrich with full details (includes voteData, favoritedCount, etc.)
        details_raw = await self.get_game_details_bulk(universe_ids)
        details_map = {str(d["id"]): d for d in details_raw}

        # Merge raw game data with full details
        merged: list[dict[str, Any]] = []
        for g in raw_games:
            uid = str(g.get("universeId", g.get("id", "")))
            detail = details_map.get(uid, {})
            merged.append({**g, **detail})

        thumbnails = await self.get_thumbnails(universe_ids)
        icons = await self.get_icons(universe_ids)

        games_out: list[RobloxGame] = []
        for raw in merged:
            game = self._parse_game(raw)
            if game is None:
                continue
            game.thumbnail_url = thumbnails.get(game.universe_id)
            game.icon_url = icons.get(game.universe_id)
            games_out.append(game)

        log.info("roblox.fetch_complete", total=len(games_out))
        return games_out
