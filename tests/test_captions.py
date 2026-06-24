"""
Regression tests for carousel caption repetition safeguards.

Motivating bug: the generator produced the same crutch phrase ("if ukuk") on
slide after slide within a single carousel, and sometimes stuttered it
("dropper if ukuk ukuk").
"""
from __future__ import annotations

from src.content.caption_utils import (
    crutch_tag,
    dedupe_carousel_captions,
    has_internal_repetition,
    normalize_caption,
)


# ── Primitives ───────────────────────────────────────────────────────────

def test_internal_repetition_detection():
    assert has_internal_repetition("minecraft dropper if ukuk ukuk")
    assert has_internal_repetition("good good game")
    assert not has_internal_repetition("minecraft dropper if ukuk")
    assert not has_internal_repetition("well made game honestly")


def test_crutch_tag_detection():
    assert crutch_tag("anime pvp if ukuk") == "if ukuk"
    assert crutch_tag("this one fr") == "fr"
    assert crutch_tag("criminally underrated") is None


# ── Cross-slide dedup ────────────────────────────────────────────────────

def test_repeated_crutch_is_rewritten():
    captions = [
        "minecraft dropper if ukuk",
        "anime pvp if ukuk",
        "horror map if ukuk",
        "tower climb if ukuk",
        "racing game if ukuk",
    ]
    out = dedupe_carousel_captions(captions, scores=[9.6, 8.2, 7.1, 6.0, 9.1])
    # At most one slide may keep the "if ukuk" tag.
    tagged = [c for c in out if crutch_tag(c) == "if ukuk"]
    assert len(tagged) <= 1
    # Every caption is unique within the carousel.
    norms = [normalize_caption(c) for c in out]
    assert len(set(norms)) == len(norms)
    # Output length preserved.
    assert len(out) == len(captions)


def test_exact_duplicates_are_rewritten():
    captions = ["fun game", "fun game", "fun game"]
    out = dedupe_carousel_captions(captions, genres=["horror", "fps", "obby"])
    assert len(set(normalize_caption(c) for c in out)) == 3


def test_stutter_is_replaced():
    out = dedupe_carousel_captions(["dropper if ukuk ukuk"], scores=[8.0])
    assert not has_internal_repetition(out[0])
    assert out[0].strip()


def test_good_distinct_captions_are_preserved():
    captions = [
        "GTA in roblox",
        "horror that actually scared me",
        "criminally underrated",
        "spent 30 hours in this",
        "valorant but roblox",
    ]
    out = dedupe_carousel_captions(captions)
    # None of these collide, so they should pass through untouched.
    assert out == captions


def test_genre_aware_replacement_is_specific():
    captions = ["fun game", "fun game"]
    out = dedupe_carousel_captions(captions, genres=["horror", "puzzle"], scores=[9.0, 9.0])
    # The horror slide should get a horror-flavored line, not a generic one.
    assert "horror" in out[0].lower() or "solo" in out[0].lower() or "unsettling" in out[0].lower()
