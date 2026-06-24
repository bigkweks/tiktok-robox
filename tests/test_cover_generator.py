"""
Tests for the dedicated cover-generation system.

Covers: concept generation count, scoring dimension ranges, rejection
logic, selection mechanics, edition-specific hook preference, Roblox
cultural specificity, no-AI-tell guarantee, and the full select path.
"""
from __future__ import annotations

from src.content.caption_utils import has_ai_tell
from src.content.cover_generator import (
    REJECT_FLOOR,
    CoverConcept,
    CoverScore,
    generate_cover_concepts,
    score_concept,
    select_cover_concept,
)


# ── Basic shape ───────────────────────────────────────────────────────────

def test_generates_exactly_10_concepts():
    concepts = generate_cover_concepts("Horror edition")
    assert len(concepts) == 10


def test_each_concept_has_a_score():
    for c in generate_cover_concepts("Friends edition"):
        assert c.score is not None
        assert isinstance(c.score, CoverScore)


def test_all_six_dimensions_in_range():
    for c in generate_cover_concepts("PvP edition"):
        s = c.score
        for dim in (s.curiosity, s.clarity, s.readability,
                    s.specificity, s.novelty, s.authenticity):
            assert 0.0 <= dim <= 1.0, f"{c.name}: dimension out of range"


def test_composite_matches_weighted_sum():
    c = generate_cover_concepts("Horror edition")[0]
    s = c.score
    expected = round(
        0.25 * s.curiosity + 0.20 * s.clarity + 0.08 * s.readability
        + 0.20 * s.specificity + 0.12 * s.novelty + 0.15 * s.authenticity,
        3,
    )
    assert abs(s.composite - expected) < 1e-9


# ── Scoring quality ───────────────────────────────────────────────────────

def test_edition_specific_hook_scores_higher_on_specificity():
    horror_concepts = generate_cover_concepts("Horror edition")
    qualifier = next(c for c in horror_concepts if c.name == "The Qualifier")
    # Edition-specific: "if you've already beaten doors" names an actual game
    assert qualifier.is_edition_specific
    assert qualifier.score.specificity > 0.60, (
        f"Expected specificity > 0.60, got {qualifier.score.specificity}"
    )


def test_visit_count_concept_has_high_specificity():
    # The Visit Count archetype uses numbers + Roblox-native metric "visits"
    for edition in ("Horror edition", "Hidden Gems", ""):
        concepts = generate_cover_concepts(edition)
        vc = next(c for c in concepts if c.name == "The Visit Count")
        assert vc.score.specificity >= 0.50, (
            f"Edition {edition!r}: Visit Count specificity {vc.score.specificity}"
        )


def test_niche_gate_scores_high_for_its_edition():
    concepts = generate_cover_concepts("PvP edition")
    ng = next(c for c in concepts if c.name == "The Niche Gate")
    # "pvp for people who hate bot lobbies" — names community pain + niche vocab
    assert ng.score.specificity >= 0.55
    assert ng.score.authenticity >= 0.50


def test_horror_qualifier_names_doors():
    concepts = generate_cover_concepts("Horror edition")
    qualifier = next(c for c in concepts if c.name == "The Qualifier")
    assert "doors" in qualifier.hook.lower()


def test_no_concept_contains_ai_tell():
    for edition in ("Horror edition", "Friends edition", "PvP edition", ""):
        for c in generate_cover_concepts(edition):
            assert not has_ai_tell(c.hook), (
                f"AI tell found in {c.name!r} hook: {c.hook!r}"
            )


# ── REJECT_FLOOR mechanics ────────────────────────────────────────────────

def test_bad_hook_fails_reject_floor():
    # An AI-tell hook should fail on multiple dimensions
    bad = score_concept("dive into the ultimate roblox hidden gems experience")
    # Authenticity and novelty should tank
    assert not bad.passes


def test_good_hook_passes_reject_floor():
    # "if you've already beaten doors" — specific, curious, creator-native
    good = score_concept("if you've already beaten doors", "Horror edition")
    assert good.passes, f"Expected passing score, got: {good.as_dict()}"


# ── Selection mechanics ───────────────────────────────────────────────────

def test_select_returns_cover_concept():
    result = select_cover_concept("Horror edition", part=1)
    assert isinstance(result, CoverConcept)
    assert result.hook
    assert result.score is not None


def test_select_returns_highest_composite_among_passing():
    edition = "Hidden Gems"
    concepts = generate_cover_concepts(edition)
    passing = [c for c in concepts if c.score and c.score.passes]
    best = max(passing, key=lambda c: c.score.composite)
    selected = select_cover_concept(edition, part=1)
    assert abs(selected.score.composite - best.score.composite) < 1e-9


def test_select_skips_used_hooks():
    edition = "Friends edition"
    first = select_cover_concept(edition, part=1)
    used = {first.hook.strip().lower()}
    second = select_cover_concept(edition, part=1, used_hooks=used)
    assert second.hook.strip().lower() != first.hook.strip().lower()


def test_select_works_without_edition():
    # Should fall back gracefully to base hooks and still return a valid concept
    result = select_cover_concept("", part=1)
    assert isinstance(result, CoverConcept)
    assert result.score is not None


def test_select_works_for_all_editions():
    for edition in (
        "Horror edition", "Friends edition", "Hidden Gems",
        "Solo edition", "Anime edition", "PvP edition",
        "Underrated edition", "Brainrot edition",
    ):
        result = select_cover_concept(edition, part=1)
        assert result.hook, f"Empty hook for edition {edition!r}"
        assert result.score.composite > 0.0


# ── as_dict serialisation ─────────────────────────────────────────────────

def test_concept_as_dict_has_required_keys():
    c = generate_cover_concepts("Horror edition")[0]
    d = c.as_dict()
    for key in ("name", "hook", "edition", "is_edition_specific", "score"):
        assert key in d, f"Missing key: {key}"
    for dim in ("curiosity", "clarity", "readability",
                "specificity", "novelty", "authenticity", "composite", "passes"):
        assert dim in d["score"], f"Missing score key: {dim}"


def test_reject_floor_constant_is_sensible():
    assert 0.30 <= REJECT_FLOOR <= 0.60, "REJECT_FLOOR should be a reasonable threshold"
