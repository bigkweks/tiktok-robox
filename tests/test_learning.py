"""
Tests for the Performance Learning System.

Covers the whole loop: component classification → genome record → corpus store →
ranking metrics (success confidence / effectiveness / diversity / novelty) →
anti-convergence bias → evaluation buckets → insights payload → generator bias →
the recorder bridge from a real approval run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.learning import PerformanceStore, build_genome
from src.learning.components import (
    classify_cta,
    classify_hook,
    detect_ai_signals,
    structure_signature,
)
from src.learning.genome import CarouselGenome, edit_resilience_from_cycles
from src.learning import evaluation, insights, ranking


# ── Fixtures ────────────────────────────────────────────────────────────────

def _genome(i, cover, *, hook="stat", cta="save", final=86.0,
            approved=True, cycles=1, edition="Horror edition",
            hard_failures=None, fail_reasons=None, ai_signals=None,
            created="2026-01-01") -> CarouselGenome:
    return CarouselGenome(
        part=i,
        edition=edition,
        created_at=f"{created}T00:00:{i:02d}",
        hook=f"hook {i}",
        hook_pattern=hook,
        cover_concept=cover,
        cta="cta line",
        cta_pattern=cta,
        structure=structure_signature(6, edition),
        final_score=final,
        approved=approved,
        cycles=cycles,
        edit_resilience=edit_resilience_from_cycles(approved, cycles),
        hard_failures=hard_failures or ([] if approved else ["generic hook"]),
        fail_reasons=fail_reasons or ([] if approved else ["slide 2 serves no purpose: empty"]),
        ai_signals=ai_signals or ([] if approved else ["dive into"]),
        reviewer_scores={"Growth Strategist": final},
    )


# ── Component classification ────────────────────────────────────────────────

def test_classify_hook_families():
    assert classify_hook("if you've already beaten doors") == "qualifier"
    assert classify_hook("50k visits. deserve 50 million.") == "stat"
    assert classify_hook("i spent 3 days finding these") == "confession"
    assert classify_hook("your fyp has been hiding these") == "accusation"
    assert classify_hook("too good to go viral") == "paradox"
    assert classify_hook("only the serious players know these") == "insider"
    # No signal at all → curiosity fallback.
    assert classify_hook("games that know what they are") == "curiosity"
    assert classify_hook("") == "curiosity"


def test_classify_cta_families():
    assert classify_cta("save these for later") == "save"
    assert classify_cta("which one are you opening first?") == "question"
    assert classify_cta("part 5 soon — follow") == "follow"
    assert classify_cta("here's the list") == "engage"


def test_structure_signature():
    assert structure_signature(6, "Horror edition") == "6-slide/horror"
    assert structure_signature(6, "Friends edition") == "6-slide/friends"
    assert structure_signature(5, None) == "5-slide/generic"


def test_detect_ai_signals():
    sigs = detect_ai_signals(["dive into this", "totally fine", "the ultimate guide"])
    assert "dive into" in sigs and "the ultimate" in sigs
    assert detect_ai_signals(["a clean human caption", None]) == []


# ── Genome ──────────────────────────────────────────────────────────────────

def test_edit_resilience_decays_with_cycles():
    assert edit_resilience_from_cycles(True, 1) == 1.0
    assert edit_resilience_from_cycles(True, 2) == 0.6
    assert edit_resilience_from_cycles(True, 3) == 0.3
    assert edit_resilience_from_cycles(False, 1) == 0.0


def test_genome_roundtrip():
    g = _genome(1, "The Visit Count")
    g2 = CarouselGenome.from_dict(g.as_dict())
    assert g2.cover_concept == "The Visit Count"
    assert g2.hook_pattern == "stat"
    assert g2.component("cover") == "The Visit Count"
    assert g2.component("hook") == "stat"
    assert g2.component("cta") == "save"


# ── Ranking ─────────────────────────────────────────────────────────────────

def test_effectiveness_blends_score_and_resilience():
    strong = ranking.effectiveness(_genome(1, "x", final=90, approved=True, cycles=1).as_dict())
    weak = ranking.effectiveness(_genome(2, "x", final=60, approved=False, cycles=3).as_dict())
    assert strong > weak
    assert 0.0 <= weak <= strong <= 1.0


def test_effectiveness_realised_outcomes_dominate():
    d = _genome(1, "x", final=90).as_dict()
    d["outcomes"] = {"performance_index": 0.1, "samples": 5}
    # A poor realised outcome pulls effectiveness well below the proxy.
    assert ranking.effectiveness(d) < 0.7


def test_wilson_confidence_grows_with_evidence():
    one = ranking._wilson_lower_bound(1, 1)
    twenty = ranking._wilson_lower_bound(20, 20)
    assert twenty > one  # same 100% rate, but far more evidence


def test_is_success_requires_quality_and_survival():
    assert ranking.is_success(_genome(1, "x", final=85, approved=True, cycles=1).as_dict())
    assert not ranking.is_success(_genome(2, "x", final=85, approved=True, cycles=3).as_dict())
    assert not ranking.is_success(_genome(3, "x", final=60, approved=False, cycles=3).as_dict())


def test_component_stats_metrics():
    genomes = [_genome(i, "The Insider", final=86, approved=True, cycles=1) for i in range(6)]
    stats = ranking.component_stats([g.as_dict() for g in genomes], "cover")
    s = stats["The Insider"]
    assert s.n == 6
    assert s.historical_effectiveness > 0.6
    assert s.success_confidence > 0.0
    # The only component → it has the whole recent share, so it's overused.
    assert s.selection_share == 1.0
    assert s.diversity_score == pytest.approx(0.0)


def test_bias_is_capped_and_empty_at_cold_start():
    assert ranking.component_bias([], "cover") == {}
    genomes = [_genome(i, c).as_dict() for i, c in enumerate(
        ["The Insider", "The Confession", "The Scout Report", "The Visit Count"])]
    for b in ranking.component_bias(genomes, "cover").values():
        assert -ranking.BIAS_CAP <= b <= ranking.BIAS_CAP


def test_anti_convergence_throttles_dominant_even_when_best():
    # The Insider is the strongest AND the most-used → must be forced negative so
    # it can't take over every drop. A fresh strong alternative must beat it.
    genomes = [_genome(i, "The Insider", final=92, approved=True, cycles=1) for i in range(8)]
    genomes += [_genome(8, "The Scout Report", final=84, approved=True, cycles=1)]
    genomes += [_genome(i, "The Confession", final=58, approved=False, cycles=3)
                for i in range(9, 13)]
    ds = [g.as_dict() for g in genomes]
    bias = ranking.component_bias(ds, "cover")
    assert bias["The Insider"] == -ranking.BIAS_CAP        # dominant → throttled
    assert bias["The Scout Report"] > bias["The Insider"]  # fresh winner preferred


# ── Evaluation ──────────────────────────────────────────────────────────────

def test_classification_buckets():
    genomes = [_genome(i, "The Insider", final=88, approved=True, cycles=1) for i in range(8)]
    genomes += [_genome(i, "The Confession", final=55, approved=False, cycles=3)
                for i in range(8, 14)]
    genomes += [_genome(14, "The Scout Report", final=85, approved=True, cycles=1)]
    ds = [g.as_dict() for g in genomes]
    buckets = evaluation.category_patterns(ds, "cover")
    strong = {d["name"] for d in buckets["strong"]}
    weak = {d["name"] for d in buckets["weak"]}
    overused = {d["name"] for d in buckets["overused"]}
    emerging = {d["name"] for d in buckets["emerging"]}
    assert "The Insider" in strong
    assert "The Confession" in weak
    assert "The Insider" in overused          # strong but dominating
    assert "The Scout Report" in emerging     # fresh + performing, small sample


def test_selection_frequency_and_survival_rate():
    genomes = [_genome(i, "The Insider", approved=True, cycles=1) for i in range(3)]
    genomes += [_genome(i, "The Confession", approved=False, cycles=3) for i in range(3, 5)]
    ds = [g.as_dict() for g in genomes]
    freq = evaluation.selection_frequency(ds, "cover")
    assert freq[0] == ("The Insider", 3)
    # 3 of 5 survived editing with minimal changes (approved on cycle 1).
    assert evaluation.survival_rate(ds) == pytest.approx(0.6)


# ── Insights ────────────────────────────────────────────────────────────────

def test_insights_payload_shape():
    genomes = [_genome(i, "The Insider", approved=True, cycles=1) for i in range(6)]
    genomes += [_genome(i, "The Confession", approved=False, cycles=3,
                        hard_failures=["generic hook"],
                        fail_reasons=["slide 3 serves no purpose: empty"],
                        ai_signals=["dive into"]) for i in range(6, 10)]
    ds = [g.as_dict() for g in genomes]
    data = insights.build_insights(ds)
    assert data["summary"]["total_generated"] == 10
    assert data["summary"]["approved"] == 6
    assert data["top_covers"][0]["name"] == "The Insider"
    assert {f["name"] for f in data["failure_patterns"]} == {"generic hook"}
    assert {a["name"] for a in data["ai_signals"]} == {"dive into"}
    # Slide-indexed reasons collapse to one stable category.
    assert data["quality_fail_reasons"][0]["name"] == "slide serves no purpose"
    assert data["quality_fail_reasons"][0]["count"] == 4


def test_improvement_trend_detects_getting_smarter():
    # Older drops weak, newer drops strong → improving.
    older = [_genome(i, "x", final=55, approved=False, cycles=3, created="2026-01-01")
             for i in range(4)]
    newer = [_genome(i, "x", final=90, approved=True, cycles=1, created="2026-06-01")
             for i in range(4, 8)]
    ds = [g.as_dict() for g in older + newer]
    trend = insights.improvement_trend(ds)
    assert trend["available"] and trend["improving"]
    assert trend["recent"] > trend["older"]


def test_improvement_trend_needs_minimum_sample():
    ds = [_genome(i, "x").as_dict() for i in range(3)]
    assert insights.improvement_trend(ds)["available"] is False


# ── Store ───────────────────────────────────────────────────────────────────

def test_store_record_list_count(tmp_path: Path):
    store = PerformanceStore(root=tmp_path)
    assert store.count() == 0
    gid = store.record(_genome(1, "The Visit Count"))
    store.record(_genome(2, "The Insider"))
    assert store.count() == 2
    dicts = store.list_dicts()
    assert {d["cover_concept"] for d in dicts} == {"The Visit Count", "The Insider"}
    assert any(d["id"] == gid for d in dicts)


def test_store_update_outcome(tmp_path: Path):
    store = PerformanceStore(root=tmp_path)
    gid = store.record(_genome(1, "x", final=90))
    assert store.update_outcome(gid, {"performance_index": 0.2, "samples": 3})
    assert not store.update_outcome("nonexistent", {})
    d = next(d for d in store.list_dicts() if d["id"] == gid)
    assert d["outcomes"]["performance_index"] == 0.2


def test_store_tolerates_corrupt_corpus(tmp_path: Path):
    store = PerformanceStore(root=tmp_path)
    store._ensure()
    store.path.write_text("{ not json")
    assert store.list_dicts() == []
    # Still recordable after corruption.
    store.record(_genome(1, "x"))
    assert store.count() == 1


def test_store_component_bias_and_insights(tmp_path: Path):
    store = PerformanceStore(root=tmp_path)
    for i in range(6):
        store.record(_genome(i, "The Insider", approved=True, cycles=1))
    bias = store.component_bias("cover")
    assert "The Insider" in bias
    assert store.insights()["summary"]["total_generated"] == 6


# ── Recorder bridge (real approval run) ─────────────────────────────────────

def test_build_genome_from_real_approval():
    from src.content.content_approval import ContentApprovalSystem
    approval = ContentApprovalSystem().approve(
        part=3,
        edition="Horror edition",
        captions=[
            "horror that actually scared me",
            "60 hours deep no regrets",
            "the puzzle design is unreal",
            "co-op horror done right",
            "genuinely terrifying solo",
        ],
        blurbs=["", "", "", "", ""],
        genres=["Horror", "Horror", "Puzzle", "Horror", "Horror"],
        scores=[88, 85, 82, 80, 90],
        game_names=["A", "B", "C", "D", "E"],
    )
    g = build_genome(
        part=3,
        edition="Horror edition",
        approval=approval,
        genres=["Horror", "Horror", "Puzzle", "Horror", "Horror"],
        game_names=["A", "B", "C", "D", "E"],
        blurbs=["", "", "", "", ""],
        performance_biased=False,
    )
    assert g.part == 3
    assert g.edition == "Horror edition"
    assert g.slide_count == 6
    assert g.cover_concept  # an archetype was chosen
    assert g.hook_pattern  # classified
    assert g.cta_pattern
    assert g.structure == "6-slide/horror"
    assert "Horror" in g.topic
    assert g.final_score == approval.final_score
    assert g.edit_resilience == edit_resilience_from_cycles(approval.approved, approval.cycles)
    # The genome must carry the quality + authenticity score blocks.
    assert "final_score" in g.quality_scores
    assert "ai_ratio" in g.authenticity_scores
    # Round-trips cleanly for persistence.
    assert CarouselGenome.from_dict(g.as_dict()).cover_concept == g.cover_concept
