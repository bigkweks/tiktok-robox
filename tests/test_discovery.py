"""Tests for the Roblox API client (mocked HTTP) and trend detector."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discovery.roblox_client import RobloxClient, RobloxGame


MOCK_GAME_RAW = {
    "id": "12345",
    "universeId": "12345",
    "rootPlaceId": "67890",
    "name": "Test Game",
    "description": "A test Roblox game for unit testing",
    "creator": {"name": "TestCreator", "id": "111"},
    "genre": "Adventure",
    "visits": 5_000_000,
    "playing": 1500,
    "maxPlayers": 20,
    "favoritedCount": 200_000,
    "voteData": {"upVotes": 45000, "downVotes": 3000},
    "created": "2023-01-15T00:00:00Z",
    "updated": "2024-06-01T00:00:00Z",
}


def test_parse_game_valid():
    client = RobloxClient.__new__(RobloxClient)
    game = client._parse_game(MOCK_GAME_RAW)
    assert game is not None
    assert game.universe_id == "12345"
    assert game.name == "Test Game"
    assert game.visits == 5_000_000
    assert game.active_players == 1500
    assert game.favorites == 200_000
    assert game.like_count == 45000
    assert game.dislike_count == 3000
    assert abs(game.like_ratio - 0.9375) < 0.001
    assert "roblox.com/games/67890" in game.url


def test_parse_game_missing_universe_id():
    client = RobloxClient.__new__(RobloxClient)
    result = client._parse_game({"name": "Broken"})
    assert result is None


def test_parse_game_zero_votes():
    client = RobloxClient.__new__(RobloxClient)
    raw = {**MOCK_GAME_RAW, "voteData": {"upVotes": 0, "downVotes": 0}}
    game = client._parse_game(raw)
    assert game is not None
    assert game.like_ratio == 0.0


def test_parse_game_handles_malformed_date():
    client = RobloxClient.__new__(RobloxClient)
    raw = {**MOCK_GAME_RAW, "created": "not-a-date", "updated": None}
    game = client._parse_game(raw)
    assert game is not None
    assert game.created_at is None
    assert game.updated_at is None


def test_collect_universe_ids_nested_shapes():
    """The recursive ID collector must find universeIds no matter how the
    explore/search API nests them — this is what keeps discovery resilient to
    Roblox changing its response shape."""
    # Shape A: explore-api get-sorts (games inline under each sort)
    explore = {
        "sorts": [
            {"sortId": "popular", "games": [{"universeId": 111}, {"universeId": 222}]},
            {"sortId": "up-and-coming", "games": [{"universeId": "333"}]},
        ]
    }
    ids: set[str] = set()
    RobloxClient._collect_universe_ids(explore, ids)
    assert ids == {"111", "222", "333"}

    # Shape B: search-api (deeply nested contents, plus a universeIds list)
    search = {
        "searchResults": [
            {"contents": [{"universeId": 444}, {"universeId": 555}]},
            {"recommendationList": {"universeIds": [666, "777"]}},
        ]
    }
    ids2: set[str] = set()
    RobloxClient._collect_universe_ids(search, ids2)
    assert ids2 == {"444", "555", "666", "777"}

    # Non-numeric / junk values are ignored
    ids3: set[str] = set()
    RobloxClient._collect_universe_ids({"universeId": "abc", "other": 1}, ids3)
    assert ids3 == set()


@pytest.mark.asyncio
async def test_enrichment_merges_bulk_votes():
    """fetch_games_with_enrichment must overlay bulk votes onto games, because
    the /v1/games details endpoint omits votes (otherwise like_ratio is always 0)."""
    client = RobloxClient.__new__(RobloxClient)
    # details endpoint returns a game with NO vote data
    details = {**MOCK_GAME_RAW, "voteData": {}}
    client.get_game_details_bulk = AsyncMock(return_value=[details])
    client.get_thumbnails = AsyncMock(return_value={})
    client.get_icons = AsyncMock(return_value={})
    client.get_votes_bulk = AsyncMock(return_value={"12345": (90, 10)})

    games = await client.fetch_games_with_enrichment(["12345"])
    assert len(games) == 1
    assert games[0].like_count == 90
    assert games[0].dislike_count == 10
    assert abs(games[0].like_ratio - 0.9) < 0.001


def test_roblox_game_url_format():
    game = RobloxGame(
        universe_id="999",
        place_id="12345",
        name="Test",
        description="",
        creator_name="dev",
        creator_id="1",
        genre="Adventure",
        visits=100,
        active_players=10,
        max_players=20,
        favorites=5,
        like_count=10,
        dislike_count=1,
        like_ratio=0.9,
        created_at=None,
        updated_at=None,
        url="https://www.roblox.com/games/12345",
    )
    assert "12345" in game.url
