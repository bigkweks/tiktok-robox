"""
Tests for the carousel quality reviewer + auto-revision gate.

The gate must: catch AI fingerprints, reward specific/curiosity-driven copy,
pass genuinely good carousels, fail templated/generic ones, and always emit
auto-revised (AI-free, unique, vetted) hooks/captions/CTAs.
"""
from __future__ import annotations

from src.content.caption_utils import has_ai_tell, specificity_score
from src.content.carousel_quality import (
    build_post_caption,
    finalize_carousel,
    pick_cover_hook,
    pick_cta,
    review_carousel,
    score_caption,
    score_cta,
    score_hook,
)


# ── Fingerprint + specificity primitives ─────────────────────────────────

def test_ai_tells_detected_but_slang_spared():
    assert has_ai_tell("dive into the ultimate experience")
    assert has_ai_tell("unlock the secrets of this game")
    assert not has_ai_tell("horror that actually scared me")
    assert not has_ai_tell("valorant but roblox fr")   # slang is authentic, not a tell


def test_specificity_rewards_concrete_detail():
    assert specificity_score("spent 30 hours in this") >= 2      # number
    assert specificity_score("valorant but roblox") >= 1         # comparison
    assert specificity_score("horror that actually scared me") >= 1  # named vibe
    assert specificity_score("fun game") == 0


# ── Element scores ───────────────────────────────────────────────────────

def test_hook_scoring_prefers_curiosity_over_hype():
    assert score_hook("you've never heard of these") > score_hook("the most INSANE games ever")
    assert score_hook("dive into the ultimate roblox list") < 0.4   # AI tell tanks it


def test_caption_scoring_punishes_generic_and_ai():
    assert score_caption("horror that actually scared me") > 0.6
    assert score_caption("fun game") < 0.4
    assert score_caption("dive into this one") < 0.4


def test_cta_scoring_punishes_desperation():
    assert score_cta("part 6 is already in the works — follow so it finds you") > 0.6
    assert score_cta("like and subscribe for more!!!") < 0.4


# ── Carousel-level review ────────────────────────────────────────────────

def test_good_carousel_passes_review():
    rep = review_carousel(
        "you've never heard of these",
        ["horror that actually scared me", "valorant but roblox",
         "spent 30 hours in this", "puzzle that broke my brain", "the story actually hit"],
        ["b1", "b2", "b3", "b4", "b5"],
        "part 6 is already in the works — follow so it finds you",
    )
    assert rep.passed
    assert rep.overall >= 0.72
    assert rep.checklist["no_ai_sentences"]
    assert rep.checklist["no_repeated_wording"]


def test_bad_carousel_fails_and_reports_issues():
    rep = review_carousel(
        "dive into the ultimate roblox experience",
        ["fun game", "good game", "unlock the secrets", "dive in", "fun game"],
        ["", "", "", "", ""],
        "like and subscribe for more!!!",
    )
    assert not rep.passed
    assert not rep.checklist["no_ai_sentences"]
    assert not rep.checklist["no_repeated_wording"]
    assert any("AI" in i for i in rep.issues)


# ── Auto-revision ────────────────────────────────────────────────────────

def test_finalize_cleans_a_messy_batch():
    out = finalize_carousel(
        part=5, edition="Hidden Gems",
        captions=["dive into this game", "fun game", "good game", "this one if ukuk", "fun game"],
        blurbs=["b"] * 5,
        genres=["horror", "racing", "fps", "puzzle", "story"],
        scores=[9.4, 8.1, 7.5, 9.0, 6.2],
        game_names=["A", "B", "C", "D", "E"],
    )
    caps = out["captions"]
    # No AI tells survive, captions are unique, and the post now passes.
    assert not any(has_ai_tell(c) for c in caps)
    assert len(set(c.lower() for c in caps)) == len(caps)
    assert not has_ai_tell(out["cover_hook"])
    assert out["report"].passed


# ── De-templating / variety ──────────────────────────────────────────────

def test_cover_hooks_vary_and_are_clean():
    picks = [pick_cover_hook(p) for p in range(6)]
    assert len(set(picks)) >= 4                  # not the same hook every part
    assert all(not has_ai_tell(h) for h in picks)


def test_cover_hooks_are_niche_specific_per_edition():
    """An edition gets niche-specific hooks (the key authenticity signal), and
    a generic call still works (back-compat for the bank)."""
    from src.content.carousel_quality import EDITION_HOOKS

    horror = {pick_cover_hook(p, edition="Horror edition") for p in range(4)}
    # Every horror pick comes from the horror niche bank — not the generic one.
    assert horror and horror <= set(EDITION_HOOKS["Horror edition"])
    # A different niche yields different language.
    pvp = pick_cover_hook(0, edition="PvP edition")
    assert pvp in EDITION_HOOKS["PvP edition"]
    # No edition / unknown edition falls back to the generic bank cleanly.
    assert isinstance(pick_cover_hook(0), str)
    assert isinstance(pick_cover_hook(0, edition="Nonexistent"), str)


def test_ctas_vary_across_parts():
    picks = [pick_cta(p) for p in range(5)]
    assert len(set(picks)) >= 3


def test_carousel_hashtags_pin_anchors_but_rotate():
    """Every post keeps the proven search anchors, but the full set differs drop
    to drop (an identical hashtag wall is an automation tell TikTok suppresses)
    and reads on-topic for the edition."""
    from src.content.carousel_quality import build_carousel_hashtags
    eds = ["Horror edition", "Friends edition", "Hidden Gems", "Anime edition", "Solo edition"]
    sets = [tuple(build_carousel_hashtags(p, eds[p], game_names=["Backrooms Escape"]))
            for p in range(5)]
    # Proven search anchors are on every post…
    assert all("#robloxgames" in s and "#robloxgamestoplywithfriends" in s for s in sets)
    # …but no two consecutive drops post the identical wall.
    assert len(set(sets)) == len(sets)
    # Edition niche tag shows up (on-topic, not generic).
    assert "#robloxhorror" in sets[0]
    assert "#robloxanime" in sets[3]
    # No duplicates within a single post.
    for s in sets:
        assert len(s) == len(set(s))


def test_post_caption_keeps_search_anchor_but_varies():
    caps = [build_post_caption("Hidden Gems", p, ["Sell Lemons", "Drift Kings"]) for p in range(5)]
    # The proven search phrase is always present (23.9% of traffic was search)…
    assert all("roblox games to play" in c.lower() for c in caps)
    # …but the surrounding copy rotates, so the series never reads copy-pasted.
    assert len(set(caps)) >= 4


# ── Retention-arc sequencing ─────────────────────────────────────────────

def test_retention_order_saves_best_for_last():
    from src.scheduler.pipeline import Pipeline
    items = [("A", 9.5), ("B", 8.0), ("C", 7.0), ("D", 6.0), ("E", 9.1)]
    out = Pipeline._retention_order(items, key=lambda x: x[1])
    assert sorted(out) == sorted(items)           # a permutation, nothing lost
    assert out[-1][1] == 9.5                       # single best game is last (payoff)
    scores = [s for _, s in out]
    assert scores != sorted(scores, reverse=True)  # not a predictable descending list
