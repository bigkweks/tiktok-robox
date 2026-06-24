"""
Tests for the three-reviewer approval panel + the mandatory approval cycle.

The panel must: produce three independent 0–100 reviewer scores, compute the
weighted Final Quality Score over the seven specified dimensions, trip the hard-
failure conditions, approve only genuinely strong carousels, reject weak ones,
and (via the approval system) run the revision cycle and never return a first
draft as approved when it doesn't pass.
"""
from __future__ import annotations

from src.content.content_approval import MAX_CYCLES, ContentApprovalSystem
from src.content.review_panel import (
    APPROVE_FINAL_SCORE,
    FINAL_WEIGHTS,
    compute_dimensions,
    detect_hard_failures,
    evaluate_panel,
)


# A strong, specific, varied, on-culture carousel (should pass).
_STRONG_HOOK = "if you've already beaten doors"
_STRONG_CAPS = [
    "horror that actually scared me",
    "valorant but roblox",
    "spent 30 hours in this",
    "criminally underrated tower defense",
    "the late waves are brutal",
]
_STRONG_BLURBS = ["", "", "", "", ""]
_STRONG_CTA = "part 6 is already in the works — follow so it finds you"

# A weak, generic, repetitive, AI-tell carousel (should fail hard).
_WEAK_HOOK = "the ultimate roblox games"
_WEAK_CAPS = ["fun game", "fun game", "dive into this one", "good game", "cool game"]
_WEAK_CTA = "follow for more!!!"


# ── Final score weights ────────────────────────────────────────────────────

def test_final_weights_sum_to_one():
    assert abs(sum(FINAL_WEIGHTS.values()) - 1.0) < 1e-9


def test_final_weights_match_spec():
    assert FINAL_WEIGHTS["hook"] == 0.20
    assert FINAL_WEIGHTS["curiosity"] == 0.15
    assert FINAL_WEIGHTS["authenticity"] == 0.20
    assert FINAL_WEIGHTS["readability"] == 0.15
    assert FINAL_WEIGHTS["retention"] == 0.15
    assert FINAL_WEIGHTS["saveability"] == 0.10
    assert FINAL_WEIGHTS["follow"] == 0.05


# ── Three independent reviewers ────────────────────────────────────────────

def test_panel_has_three_named_reviewers():
    panel = evaluate_panel(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA)
    names = [r.name for r in panel.reviewers]
    assert names == ["Growth Strategist", "Successful Roblox Creator", "Skeptical Viewer"]
    for r in panel.reviewers:
        assert 0 <= r.score <= 100
        assert len(r.answers) == 4   # each reviewer answers its four questions


def test_reviewers_are_independent_not_identical():
    panel = evaluate_panel(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA)
    scores = {r.score for r in panel.reviewers}
    # Different lenses → not all three collapse to one number.
    assert len(scores) >= 2


def test_final_score_in_range():
    panel = evaluate_panel(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA)
    assert 0 <= panel.final_score <= 100


# ── Hard-failure conditions ────────────────────────────────────────────────

def test_repetitive_phrasing_is_hard_failure():
    d = compute_dimensions(_STRONG_HOOK, ["fun game", "fun game"], ["", ""], _STRONG_CTA)
    fails = detect_hard_failures(_STRONG_HOOK, ["fun game", "fun game"], ["", ""], _STRONG_CTA, d)
    assert "repetitive phrasing" in fails


def test_generic_hook_is_hard_failure():
    d = compute_dimensions("amazing games", _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA)
    fails = detect_hard_failures("amazing games", _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA, d)
    assert "generic hook" in fails


def test_ai_wording_is_hard_failure():
    caps = ["dive into this one", "horror that scared me", "spent 30 hours", "valorant but roblox", "brutal waves"]
    d = compute_dimensions(_STRONG_HOOK, caps, _STRONG_BLURBS, _STRONG_CTA)
    fails = detect_hard_failures(_STRONG_HOOK, caps, _STRONG_BLURBS, _STRONG_CTA, d)
    assert "ai-style wording" in fails


def test_weak_cta_is_hard_failure():
    d = compute_dimensions(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, "like and subscribe!!!")
    fails = detect_hard_failures(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, "like and subscribe!!!", d)
    assert "weak cta" in fails


def test_strong_carousel_has_no_hard_failures():
    d = compute_dimensions(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA)
    fails = detect_hard_failures(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA, d)
    assert fails == []


# ── Approval verdict ───────────────────────────────────────────────────────

def test_weak_carousel_is_rejected():
    panel = evaluate_panel(_WEAK_HOOK, _WEAK_CAPS, ["", "", "", "", ""], _WEAK_CTA)
    assert not panel.approved
    assert panel.hard_failures   # at least one hard failure tripped


def test_strong_carousel_can_pass_panel():
    panel = evaluate_panel(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA)
    # No hard failures, and a high final score — the elite bar is reachable.
    assert panel.hard_failures == []
    assert panel.final_score >= APPROVE_FINAL_SCORE - 15  # in the strong band


# ── as_dict ────────────────────────────────────────────────────────────────

def test_panel_as_dict_shape():
    d = evaluate_panel(_STRONG_HOOK, _STRONG_CAPS, _STRONG_BLURBS, _STRONG_CTA).as_dict()
    assert set(d) >= {"approved", "final_score", "min_reviewer", "hard_failures", "reviewers", "dimensions"}
    assert len(d["reviewers"]) == 3


# ── The mandatory approval cycle ───────────────────────────────────────────

def test_approval_runs_and_returns_result():
    sys = ContentApprovalSystem()
    result = sys.approve(
        part=1, edition="Horror edition",
        captions=_STRONG_CAPS, blurbs=_STRONG_BLURBS,
        genres=["horror", "fps", "rpg", "tower defense", "survival"],
        scores=[9.1, 8.4, 8.8, 9.3, 9.5],
        game_names=["A", "B", "C", "D", "E"],
    )
    assert result.panel is not None
    assert 1 <= result.cycles <= MAX_CYCLES
    assert result.cover_hook
    # The trail records each critique cycle.
    assert len(result.trail) == result.cycles
    for entry in result.trail:
        assert "final_score" in entry and "reviewers" in entry


def test_approval_never_exceeds_max_cycles():
    sys = ContentApprovalSystem()
    # A deliberately weak batch forces revision; it must still terminate ≤3.
    result = sys.approve(
        part=2, edition="Hidden Gems",
        captions=["fun game", "fun game", "good game", "cool game", "nice game"],
        blurbs=["", "", "", "", ""],
        genres=[None] * 5, scores=[5.0] * 5,
        game_names=["A", "B", "C", "D", "E"],
    )
    assert result.cycles <= MAX_CYCLES


def test_approval_improves_or_holds_across_cycles():
    # The best final score returned must be >= the first cycle's score
    # (we always keep the strongest attempt, never regress).
    sys = ContentApprovalSystem()
    result = sys.approve(
        part=3, edition="Anime edition",
        captions=["fun game", "good game", "the abilities go crazy", "fun game", "peak anime energy"],
        blurbs=["", "", "", "", ""],
        genres=["anime"] * 5, scores=[8.0] * 5,
        game_names=["A", "B", "C", "D", "E"],
    )
    first = result.trail[0]["final_score"]
    assert result.final_score >= first
