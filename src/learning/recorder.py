"""
Genome recorder — builds a `CarouselGenome` from an approval run.

Bridges `content_approval.ApprovalResult` (+ the batch context the pipeline
already has) into a fully-classified genome. Kept separate from the pipeline so
it can be unit-tested without a database, and separate from the store so the
store stays a thin persistence layer.
"""
from __future__ import annotations

from typing import Optional, Sequence

from src.learning.components import (
    classify_cta,
    classify_hook,
    detect_ai_signals,
    structure_signature,
)
from src.learning.genome import CarouselGenome, edit_resilience_from_cycles


def _dna_fingerprint(dna) -> dict:
    """A small, stable summary of the DNA blueprint that steered this drop."""
    if dna is None:
        return {"used": False}
    return {
        "used": True,
        "label": getattr(dna, "label", "") or "",
        "is_prior": bool(getattr(dna, "is_prior", False)),
        "overall_confidence": round(float(getattr(dna, "overall_confidence", 0.0) or 0.0), 3),
        "source_count": int(getattr(dna, "source_count", 0) or 0),
    }


def build_genome(
    *,
    part: int,
    edition: str,
    approval,                       # content_approval.ApprovalResult
    genres: Sequence[Optional[str]],
    game_names: Sequence[str],
    blurbs: Optional[Sequence[str]] = None,
    dna=None,
    slide_count: int = 6,
    performance_biased: bool = False,
) -> CarouselGenome:
    """Assemble the genome record for one generated carousel."""
    panel = approval.panel
    dims = panel.dimensions if panel else None

    quality_scores: dict = {}
    authenticity_scores: dict = {}
    if dims is not None:
        d = dims.as_dict()
        quality_scores = {
            "hook": d.get("hook"),
            "curiosity": d.get("curiosity"),
            "authenticity": d.get("authenticity"),
            "readability": d.get("readability"),
            "retention": d.get("retention"),
            "saveability": d.get("saveability"),
            "follow": d.get("follow"),
            "final_score": approval.final_score,
        }
        authenticity_scores = {
            "authenticity": d.get("authenticity"),
            "ai_ratio": d.get("ai_ratio"),
            "culture": d.get("culture"),
            "novelty": d.get("novelty"),
        }

    report = getattr(approval, "report", None)
    fail_reasons = list(getattr(report, "issues", []) or [])

    genres_clean = [g for g in genres if g]
    topic = f"{edition} · {', '.join(genres_clean[:3])}" if genres_clean else edition

    ai_text_pool = [
        approval.cover_hook, approval.cta, *approval.captions, *(blurbs or []),
    ]

    return CarouselGenome(
        part=part,
        edition=edition,
        topic=topic,
        genres=genres_clean,
        game_names=list(game_names),
        hook=approval.cover_hook,
        hook_pattern=classify_hook(approval.cover_hook),
        cover_concept=approval.cover_concept or "unknown",
        slide_count=slide_count,
        structure=structure_signature(slide_count, edition),
        cta=approval.cta,
        cta_pattern=classify_cta(approval.cta),
        dna_profile=_dna_fingerprint(dna),
        generation_settings={
            "cycles": approval.cycles,
            "dna_driven": dna is not None,
            "performance_biased": performance_biased,
            "cover_concept": approval.cover_concept or "",
        },
        quality_scores=quality_scores,
        authenticity_scores=authenticity_scores,
        final_score=approval.final_score,
        approved=approval.approved,
        cycles=approval.cycles,
        hard_failures=list(panel.hard_failures) if panel else [],
        fail_reasons=fail_reasons,
        reviewer_scores={r.name: r.score for r in panel.reviewers} if panel else {},
        ai_signals=detect_ai_signals(ai_text_pool),
        edit_resilience=edit_resilience_from_cycles(approval.approved, approval.cycles),
    )


__all__ = ["build_genome"]
