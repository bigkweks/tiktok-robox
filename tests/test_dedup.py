"""
Cross-post duplicate / near-duplicate detection tests.

Repetition across posts is the #1 "this is a bot" tell (the same followers see
consecutive parts). These cover exact, near, and unrelated cases plus the batch
and historical gates.
"""
from __future__ import annotations

from src.content.dedup import (
    DEFAULT_THRESHOLD,
    dedupe_batch,
    is_near_duplicate,
    most_similar,
    normalize,
    similarity,
)


def test_normalize_strips_punctuation_and_case():
    assert normalize("You've NEVER heard of these!!") == "you ve never heard of these"


def test_identical_strings_are_max_similar():
    assert similarity("criminally underrated", "criminally underrated") == 1.0


def test_apostrophe_and_case_variants_are_near_duplicates():
    # "thats" vs "that's", caps differences — a real near-duplicate.
    assert similarity("horror that actually scared me",
                      "Horror that's actually scared me") >= DEFAULT_THRESHOLD


def test_unrelated_strings_are_low_similarity():
    assert similarity("GTA in roblox", "criminally underrated puzzle game") < 0.5


def test_is_near_duplicate_against_history():
    history = ["you've never heard of these", "save this list trust me"]
    assert is_near_duplicate("youve never heard of these", history) is True
    assert is_near_duplicate("ranked games no one plays", history) is False


def test_empty_candidate_is_never_a_duplicate():
    assert is_near_duplicate("", ["anything"]) is False
    assert is_near_duplicate("   ", ["anything"]) is False


def test_dedupe_batch_flags_later_duplicates_only():
    lines = [
        "criminally underrated",
        "GTA in roblox",
        "criminally underrated",   # dup of index 0
        "horror that scared me",
    ]
    assert dedupe_batch(lines) == [2]


def test_most_similar_returns_best_match():
    match, score = most_similar(
        "horror that actually scared me",
        ["GTA in roblox", "horror that scared me", "puzzle game"],
    )
    assert match == "horror that scared me"
    assert score >= 0.7


def test_token_reorder_still_similar():
    # Same content words, reordered — token Jaccard catches it even though the
    # character sequence differs.
    assert similarity("ranked games no one plays",
                      "no one plays ranked games") >= 0.95
