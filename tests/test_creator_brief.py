"""
Tests for the creator-brief + slide-purpose planner.

The planner must: infer a real (never empty) audience per edition, assign every
slide an explicit purpose from the fixed vocabulary, and correctly flag slides
whose content serves no purpose (empty / generic / AI) as dead slides so the
regeneration loop fixes them rather than shipping dead weight.
"""
from __future__ import annotations

from src.content.creator_brief import (
    EDITION_BRIEFS,
    PURPOSES,
    AudienceBrief,
    brief_for,
    plan_carousel,
)
from src.content.carousel_quality import finalize_carousel


# ── Audience inference ─────────────────────────────────────────────────────

def test_every_known_edition_has_a_full_brief():
    for edition, brief in EDITION_BRIEFS.items():
        assert isinstance(brief, AudienceBrief)
        # Every one of the seven questions is answered with real text.
        for field_val in (brief.who, brief.why_care, brief.knows, brief.believes,
                          brief.surprise, brief.save_trigger, brief.follow_trigger):
            assert isinstance(field_val, str) and len(field_val) > 10


def test_brief_for_unknown_edition_falls_back_not_empty():
    b = brief_for("Nonexistent edition")
    assert isinstance(b, AudienceBrief)
    assert b.who and b.surprise and b.follow_trigger
    # None / empty also resolves cleanly.
    assert brief_for(None).who


def test_briefs_are_niche_specific_not_interchangeable():
    horror = brief_for("Horror edition")
    friends = brief_for("Friends edition")
    # Different audiences → different inferred knowledge / beliefs.
    assert horror.knows != friends.knows
    assert horror.believes != friends.believes
    assert "scare" in horror.surprise.lower() or "horror" in horror.surprise.lower()


# ── Slide purpose assignment ───────────────────────────────────────────────

def test_plan_assigns_a_valid_purpose_to_every_slide():
    plan = plan_carousel(
        "Hidden Gems",
        "you've never heard of these",
        ["horror that actually scared me", "valorant but roblox",
         "spent 30 hours in this", "puzzle that broke my brain", "the story actually hit"],
        ["b1", "b2", "b3", "b4", "b5"],
        "part 6 is already in the works — follow so it finds you",
    )
    # cover + 5 game slides = 6 planned slides
    assert len(plan.slides) == 6
    assert all(s.purpose in PURPOSES for s in plan.slides)
    # Cover's job is to stop the scroll.
    assert plan.slides[0].role == "cover"
    assert plan.slides[0].purpose == "stop_scrolling"
    # The last slide is the payoff: it carries follow + save triggers.
    last = plan.slides[-1]
    assert last.role == "closer"
    assert "trigger_following" in last.secondary
    assert "trigger_saving" in last.secondary


def test_good_carousel_is_fully_purposeful():
    plan = plan_carousel(
        "Horror edition",
        "hidden horror gems",
        ["horror that actually scared me", "do not play this solo",
         "made me jump for real", "the entity AI is brutal", "scariest one on roblox"],
        ["b"] * 5,
        "part 4 soon — follow",
    )
    assert plan.purposeful
    assert plan.dead_slides == []


def test_dead_slides_flagged_for_empty_generic_and_ai():
    plan = plan_carousel(
        "Hidden Gems",
        "dive into the ultimate roblox experience",   # AI tell → dead cover
        ["fun game",                                   # generic → dead
         "horror that actually scared me",             # real → alive
         "",                                           # empty → dead
         "dive into this one",                         # AI → dead
         "spent 30 hours in this"],                    # real → alive
        ["b"] * 5,
        "follow",
    )
    assert not plan.purposeful
    # cover(0) + slides 1,3,4 are dead (indices in the plan are slide indices)
    assert 0 in plan.dead_slides      # AI cover
    assert 1 in plan.dead_slides      # 'fun game'
    assert 3 in plan.dead_slides      # empty
    assert 4 in plan.dead_slides      # 'dive into this one'
    # The two real captions survive.
    assert 2 not in plan.dead_slides
    assert 5 not in plan.dead_slides
    # Each dead slide carries a human-readable reason.
    for idx in plan.dead_slides:
        assert plan.slides[idx].note


def test_plan_as_dict_is_serialisable():
    plan = plan_carousel(
        "Anime edition", "anime games that aren't mid",
        ["the abilities go crazy", "peak anime energy", "every character slaps",
         "the grind is worth it", "for the anime fans fr"],
        ["b"] * 5, "follow for part 2",
    )
    d = plan.as_dict()
    assert d["brief"] == "Anime edition"
    assert d["purposeful"] is True
    assert len(d["slides"]) == 6
    assert all("purpose" in s for s in d["slides"])


# ── Integration: finalize emits a purposeful plan ──────────────────────────

def test_finalize_emits_a_purposeful_plan():
    out = finalize_carousel(
        part=4, edition="Horror edition",
        captions=["dive into this game", "fun game", "good game", "this if ukuk", "fun game"],
        blurbs=["b"] * 5,
        genres=["horror", "horror", "horror", "horror", "horror"],
        scores=[9.4, 8.1, 7.5, 9.0, 6.2],
        game_names=["A", "B", "C", "D", "E"],
    )
    plan = out["plan"]
    assert plan is not None
    # After auto-revision, the shipped carousel has no dead slides.
    assert plan.purposeful
    assert plan.dead_slides == []
    # The plan knows who it's talking to.
    assert "horror" in plan.brief.who.lower() or "horror" in plan.brief.knows.lower()
