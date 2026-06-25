"""
Edition ↔ genre matching tests.

Root cause being guarded: the edition (and thus the cover theme) used to be a
blind counter rotation, so a "Horror edition" cover could sit on five non-horror
games. The cover must match the games underneath it.
"""
from __future__ import annotations

from src.content.edition_match import (
    MIN_GENRE_MATCH,
    count_genre_matches,
    edition_for_games,
    is_genre_specific,
    validate_edition_match,
)


def test_horror_edition_chosen_when_enough_horror_games():
    genres = ["Horror", "horror survival", "Adventure", "Horror", "RPG"]
    assert edition_for_games(genres, part=3) == "Horror edition"


def test_neutral_edition_when_no_genre_dominates():
    genres = ["Adventure", "Simulator", "Tycoon", "Obby", "RPG"]
    ed = edition_for_games(genres, part=1)
    assert not is_genre_specific(ed)        # falls back to a neutral edition


def test_neutral_edition_rotates_by_part():
    genres = ["Adventure", "Simulator", "Tycoon", "Obby", "RPG"]
    a = edition_for_games(genres, part=1)
    b = edition_for_games(genres, part=2)
    assert a != b                            # variety across drops


def test_single_horror_game_is_not_enough():
    genres = ["Horror", "Adventure", "Simulator", "Obby", "RPG"]
    # Only 1 horror game (< MIN_GENRE_MATCH) → must not pick Horror edition.
    assert edition_for_games(genres, part=0) != "Horror edition"


def test_validate_rejects_mismatched_genre_edition():
    genres = ["Adventure", "Simulator", "Tycoon", "Obby", "RPG"]
    ok, reason = validate_edition_match("Horror edition", genres)
    assert ok is False
    assert "Horror edition" in reason


def test_validate_passes_matching_genre_edition():
    genres = ["Horror", "horror", "Adventure", "Obby", "RPG"]
    ok, reason = validate_edition_match("Horror edition", genres)
    assert ok is True
    assert reason == ""


def test_validate_always_passes_neutral_edition():
    genres = ["Horror", "Anime", "PvP", "Adventure", "RPG"]
    ok, _ = validate_edition_match("Hidden Gems", genres)
    assert ok is True


def test_pvp_matches_fighting_and_shooter():
    genres = ["Fighting", "FPS shooter", "Adventure", "Battle", "RPG"]
    assert count_genre_matches("PvP edition", genres) >= MIN_GENRE_MATCH
    assert edition_for_games(genres, part=0) == "PvP edition"


def test_none_genres_do_not_crash():
    genres = [None, None, None, None, None]
    ed = edition_for_games(genres, part=0)
    assert not is_genre_specific(ed)
    ok, _ = validate_edition_match("Anime edition", genres)
    assert ok is False
