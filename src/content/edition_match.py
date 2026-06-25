"""
Edition ↔ genre matching and validation.

ROOT CAUSE this fixes: the pipeline chose the carousel edition by a blind
counter rotation (``EDITIONS[part % len]``) with no regard for the genres of the
5 games actually selected. That let a "Horror edition" cover sit on top of five
non-horror games — an obvious authenticity break that screams "templated".

Two responsibilities:
  - ``edition_for_games`` — CHOOSE an edition that fits the batch's genres
    (a genre-specific edition only when the genre is actually present; otherwise
    a genre-neutral edition, rotated for variety).
  - ``validate_edition_match`` — GATE: reject a carousel whose genre-specific
    edition does not match the games (the cover would lie about the content).
"""
from __future__ import annotations

from typing import Optional, Sequence

# Genre-specific editions REQUIRE matching games. The value is the set of
# substrings (matched case-insensitively against the Roblox genre string) that
# qualify a game for that edition.
GENRE_EDITIONS: dict[str, frozenset[str]] = {
    "Horror edition": frozenset({"horror", "scary", "survival horror"}),
    "Anime edition": frozenset({"anime", "manga"}),
    "PvP edition": frozenset({"pvp", "fighting", "fps", "shooter", "battle", "combat"}),
}

# Genre-neutral editions can frame almost any batch of hidden gems. Rotated for
# variety when no genre-specific edition clearly fits.
NEUTRAL_EDITIONS: tuple[str, ...] = (
    "Hidden Gems",
    "Underrated edition",
    "Friends edition",
    "Solo edition",
)

# How much of the batch must match a genre-specific edition for it to be valid.
# 2 of 5 games is enough to make a themed cover honest.
MIN_GENRE_MATCH = 2


def _genre_matches(genre: Optional[str], keywords: frozenset[str]) -> bool:
    g = (genre or "").lower()
    return any(k in g for k in keywords)


def count_genre_matches(edition: str, genres: Sequence[Optional[str]]) -> int:
    kws = GENRE_EDITIONS.get(edition)
    if not kws:
        return 0
    return sum(1 for g in genres if _genre_matches(g, kws))


def is_genre_specific(edition: str) -> bool:
    return edition in GENRE_EDITIONS


def edition_for_games(genres: Sequence[Optional[str]], part: int) -> str:
    """Pick the edition that best fits the batch.

    A genre-specific edition wins only when ≥ MIN_GENRE_MATCH games match it
    (strongest match first). Otherwise fall back to a neutral edition, rotated by
    ``part`` so the series still varies.
    """
    best_edition, best_count = None, 0
    for edition in GENRE_EDITIONS:
        c = count_genre_matches(edition, genres)
        if c >= MIN_GENRE_MATCH and c > best_count:
            best_edition, best_count = edition, c
    if best_edition:
        return best_edition
    return NEUTRAL_EDITIONS[part % len(NEUTRAL_EDITIONS)]


def validate_edition_match(
    edition: str, genres: Sequence[Optional[str]]
) -> tuple[bool, str]:
    """Gate a chosen edition against the batch.

    Genre-neutral editions always pass. A genre-specific edition passes only if
    enough games match; otherwise it's rejected with a clear reason so the cover
    never lies about the content.
    """
    if not is_genre_specific(edition):
        return True, ""
    matches = count_genre_matches(edition, genres)
    if matches >= MIN_GENRE_MATCH:
        return True, ""
    return False, (
        f"'{edition}' requires at least {MIN_GENRE_MATCH} matching games but only "
        f"{matches} of {len(genres)} fit that genre — the cover would misrepresent "
        f"the games. Choose a genre-neutral edition or a batch that matches."
    )


__all__ = [
    "GENRE_EDITIONS", "NEUTRAL_EDITIONS", "MIN_GENRE_MATCH",
    "count_genre_matches", "is_genre_specific", "edition_for_games",
    "validate_edition_match",
]
