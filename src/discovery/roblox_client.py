"""
Async Roblox API client.

Discovery strategy (403-resistant):
  1. Try /v1/games/sorts to get real sort tokens, then /v1/games/list
  2. If that 403s, use the recommendations API seeded from known game IDs
  3. The public /v1/games?universeIds= endpoint ALWAYS works without auth
     — use it for all detail fetching

We never crash on 403: every fetch has a graceful fallback.
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
    retry=retry_if_exception_type((httpx.TimeoutException,)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=False,
)

ROBLOX_GAMES_BASE = "https://games.roblox.com/v1"
ROBLOX_THUMBS_BASE = "https://thumbnails.roblox.com/v1"

# Well-known Roblox universe IDs covering all major genres.
# The /v1/games?universeIds= endpoint is fully public — no auth needed.
# Add more IDs here anytime to expand discovery coverage.
SEED_UNIVERSE_IDS: list[str] = [
    "2753915549",   # Blox Fruits
    "920587237",    # Adopt Me!
    "606849621",    # Jailbreak
    "142823291",    # Murder Mystery 2
    "1962086868",   # Tower of Hell
    "4852038898",   # Piggy
    "735030788",    # Royale High
    "286090429",    # Arsenal
    "151784841",    # MeepCity
    "287826790",    # Natural Disaster Survival
    "292439477",    # Phantom Forces
    "3260590327",   # Tower Defense Simulator
    "6284583030",   # Pet Simulator X
    "6872265039",   # BedWars
    "537413528",    # Build a Boat for Treasure
    "6516141723",   # Doors
    "7533892901",   # The Mimic
    "5309581300",   # Shindo Life
    "3805446438",   # Ninja Legends
    "4924922222",   # Brookhaven RP
    "4812045819",   # Islands (Skyblock)
    "3628400479",   # Anime Fighting Simulator X
    "391149966",    # Dragon Ball Z Final Stand
    "2788229376",   # Wisteria
    "1537690962",   # Super Golf
    "1271834323",   # Prison Life
    "155615604",    # Speed Run 4
    "301549746",    # The Mad Murderer
    "3233893879",   # My Hero Mania
    "6017479568",   # The Strongest Battlegrounds
    "3085732897",   # Anime Dungeon Fighters
    "7414549597",   # Type Soul
    "5632482380",   # Fisch
    "10449761463",  # Dress to Impress
    "4198700559",   # Rainbow Friends
    "8737899170",   # Pet Simulator 99
    "7915867861",   # Da Hood
    "6213347060",   # Break In 2
    "5936735687",   # Ability Wars
    "6456724523",   # Funky Friday
    "2670031726",   # Untitled Boxing Game
    "4372463300",   # Project Slayers
    "9969477681",   # Evade
    "3254287817",   # Survive the Killer
    "4792038890",   # Bee Swarm Simulator
    "189707",       # Escape Room (classic)
]

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
    "fps": 17,
    "rpg": 18,
    "sports": 19,
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
            # Browser-like headers — reduces 403s on some endpoints
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.roblox.com/",
                "Origin": "https://www.roblox.com",
            },
            follow_redirects=True,
        )

    async def __aenter__(self) -> RobloxClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()

    async def _get(self, url: str, **params: Any) -> Any:
        """GET with retry on timeouts, returns None on 403/404."""
        try:
            resp = await self._client.get(url, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "10"))
                log.warning("roblox.rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after)
                resp = await self._client.get(url, params=params)
            if resp.status_code in (403, 401):
                log.debug("roblox.auth_required", url=url, status=resp.status_code)
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            log.warning("roblox.timeout", url=url)
            return None
        except httpx.HTTPStatusError as exc:
            log.warning("roblox.http_error", url=url, status=exc.response.status_code)
            return None
        except Exception as exc:
            log.warning("roblox.request_failed", url=url, error=str(exc))
            return None

    async def get_game_details_bulk(self, universe_ids: list[str]) -> list[dict[str, Any]]:
        """
        Fetch detailed game data for up to 100 universe IDs at once.
        This endpoint is fully public — no auth required.
        """
        if not universe_ids:
            return []
        # Deduplicate
        unique_ids = list(dict.fromkeys(universe_ids))
        chunks = [unique_ids[i: i + 100] for i in range(0, len(unique_ids), 100)]
        results = []
        for chunk in chunks:
            data = await self._get(
                f"{ROBLOX_GAMES_BASE}/games",
                universeIds=",".join(chunk),
            )
            if data:
                results.extend(data.get("data", []))
        return results

    async def get_votes(self, universe_id: str) -> dict[str, int]:
        """Get upvotes and downvotes. Public endpoint."""
        data = await self._get(f"{ROBLOX_GAMES_BASE}/games/{universe_id}/votes")
        if not data:
            return {"like_count": 0, "dislike_count": 0}
        return {
            "like_count": data.get("upVotes", 0),
            "dislike_count": data.get("downVotes", 0),
        }

    async def get_thumbnails(self, universe_ids: list[str]) -> dict[str, str]:
        """Return {universe_id: thumbnail_url}. Public endpoint."""
        if not universe_ids:
            return {}
        result: dict[str, str] = {}
        chunks = [universe_ids[i: i + 50] for i in range(0, len(universe_ids), 50)]
        for chunk in chunks:
            data = await self._get(
                f"{ROBLOX_THUMBS_BASE}/games/multiget/thumbnails",
                universeIds=",".join(chunk),
                countPerUniverse=1,
                defaults="true",
                size="768x432",
                format="Png",
                isCircular="false",
            )
            if not data:
                continue
            for item in data.get("data", []):
                uid = str(item.get("universeId", ""))
                thumbnails = item.get("thumbnails", [])
                if thumbnails and thumbnails[0].get("imageUrl"):
                    result[uid] = thumbnails[0]["imageUrl"]
        return result

    async def get_icons(self, universe_ids: list[str]) -> dict[str, str]:
        """Return {universe_id: icon_url}. Public endpoint."""
        if not universe_ids:
            return {}
        result: dict[str, str] = {}
        chunks = [universe_ids[i: i + 100] for i in range(0, len(universe_ids), 100)]
        for chunk in chunks:
            data = await self._get(
                f"{ROBLOX_THUMBS_BASE}/games/icons",
                universeIds=",".join(chunk),
                returnPolicy="PlaceHolder",
                size="512x512",
                format="Png",
                isCircular="false",
            )
            if not data:
                continue
            for item in data.get("data", []):
                uid = str(item.get("universeId", ""))
                if item.get("imageUrl"):
                    result[uid] = item["imageUrl"]
        return result

    async def get_recommendations(self, universe_id: str, max_rows: int = 30) -> list[str]:
        """
        Get recommended game universe IDs based on a seed game.
        Used to discover new games beyond the seed list.
        """
        data = await self._get(
            f"{ROBLOX_GAMES_BASE}/games/recommendations/game/{universe_id}",
            maxRows=max_rows,
        )
        if not data:
            return []
        games = data.get("games", [])
        return [str(g.get("universeId", g.get("id", ""))) for g in games if g.get("universeId") or g.get("id")]

    async def try_games_list(self, sort_token: str = "", genre_id: int = 0, max_rows: int = 100) -> list[str]:
        """
        Attempt the authenticated games/list endpoint.
        Returns universe IDs if it works, empty list if 403.
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
        if not data:
            return []
        games = data.get("games", [])
        return [str(g.get("universeId", g.get("id", ""))) for g in games if g.get("universeId") or g.get("id")]

    async def try_get_sort_tokens(self) -> list[str]:
        """Try to get real sort tokens. Returns empty list if auth required."""
        data = await self._get(f"{ROBLOX_GAMES_BASE}/games/sorts")
        if not data:
            return []
        sorts = data.get("sorts", [])
        return [s.get("token", "") for s in sorts if s.get("token")]

    def _parse_game(self, raw: dict[str, Any]) -> Optional[RobloxGame]:
        try:
            uid = str(raw.get("id", raw.get("universeId", "")))
            if not uid or uid == "0":
                return None

            place_id = str(raw.get("rootPlaceId", raw.get("placeId", uid)))
            votes = raw.get("voteData", {})
            up = int(votes.get("upVotes", raw.get("upVotes", 0)))
            down = int(votes.get("downVotes", raw.get("downVotes", 0)))
            total = up + down
            like_ratio = (up / total) if total > 0 else 0.0

            def _dt(s: Any) -> Optional[datetime]:
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
                name=raw.get("name", "Unknown"),
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
                created_at=_dt(raw.get("created")),
                updated_at=_dt(raw.get("updated")),
                url=f"https://www.roblox.com/games/{place_id}",
                raw=raw,
            )
        except Exception as exc:
            log.debug("roblox.parse_failed", error=str(exc))
            return None

    async def fetch_games_with_enrichment(
        self,
        universe_ids: list[str],
    ) -> list[RobloxGame]:
        """
        Given a list of universe IDs, fetch full details + thumbnails.
        The underlying endpoints are all public — no auth required.
        """
        if not universe_ids:
            return []

        details_raw = await self.get_game_details_bulk(universe_ids)
        if not details_raw:
            return []

        fetched_ids = [str(d.get("id", "")) for d in details_raw]
        thumbnails = await self.get_thumbnails(fetched_ids)
        icons = await self.get_icons(fetched_ids)

        games: list[RobloxGame] = []
        for raw in details_raw:
            game = self._parse_game(raw)
            if game is None:
                continue
            game.thumbnail_url = thumbnails.get(game.universe_id)
            game.icon_url = icons.get(game.universe_id)
            games.append(game)

        return games
