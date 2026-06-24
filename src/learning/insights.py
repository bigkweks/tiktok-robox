"""
Performance insights — the dashboard payload.

Aggregates the whole genome corpus into the panels the Performance Insights
Dashboard shows:

  * Top-performing hook / cover / CTA patterns
  * Most common failure patterns (hard failures that auto-rejected drafts)
  * Most common AI signals detected
  * Most common reasons outputs fail quality review
  * A 'getting smarter over time' trend — is recent output better than older?

Everything here is a pure function of a list of genome dicts, so it is fast and
fully testable offline.
"""
from __future__ import annotations

from collections import Counter
from typing import Sequence

from src.learning.evaluation import (
    category_patterns,
    selection_frequency,
    survival_rate,
)
from src.learning.ranking import MIN_SAMPLE, component_stats, effectiveness

# How many genomes are needed before the trend line is meaningful.
_TREND_MIN: int = 6


def _top_patterns(genomes: Sequence[dict], category: str, limit: int = 5) -> list[dict]:
    """Highest-effectiveness components in a category, evidence-weighted.

    Components with enough samples to trust rank above lucky one-offs; within a
    confidence tier, higher effectiveness wins.
    """
    stats = component_stats(genomes, category)
    ranked = sorted(
        stats.values(),
        key=lambda s: (
            s.n >= MIN_SAMPLE,
            round(s.historical_effectiveness * s.success_confidence, 4),
            s.historical_effectiveness,
        ),
        reverse=True,
    )
    return [s.as_dict() for s in ranked[:limit]]


def _counter_list(items: Sequence[str], limit: int = 8) -> list[dict]:
    counts = Counter(i for i in items if i)
    return [{"name": name, "count": n} for name, n in counts.most_common(limit)]


def failure_patterns(genomes: Sequence[dict], limit: int = 8) -> list[dict]:
    """Most common hard failures that auto-rejected drafts (across all genomes,
    approved or not — an approved carousel can still have logged a hard failure
    in an earlier cycle of its trail; here we read the final recorded set)."""
    flat: list[str] = []
    for g in genomes:
        flat.extend(g.get("hard_failures", []))
    return _counter_list(flat, limit)


def ai_signal_frequency(genomes: Sequence[dict], limit: int = 8) -> list[dict]:
    flat: list[str] = []
    for g in genomes:
        flat.extend(g.get("ai_signals", []))
    return _counter_list(flat, limit)


def quality_fail_reasons(genomes: Sequence[dict], limit: int = 8) -> list[dict]:
    """Most common reasons the quality review flagged a draft (the QualityReport
    issues — finer-grained than the hard-failure buckets)."""
    flat: list[str] = []
    for g in genomes:
        flat.extend(_normalise_reason(r) for r in g.get("fail_reasons", []))
    return _counter_list(flat, limit)


def _normalise_reason(reason: str) -> str:
    """Collapse slide-indexed messages ('slide 2 serves no purpose: …') to a
    stable category so they tally together instead of fragmenting."""
    low = (reason or "").lower()
    if "serves no purpose" in low or "dead slide" in low:
        return "slide serves no purpose"
    # Drop a leading 'slide N ' prefix so per-slide variants merge.
    import re
    return re.sub(r"^slide\s+\d+\s+", "slide ", low).strip()


def improvement_trend(genomes: Sequence[dict]) -> dict:
    """Is the system getting smarter? Compare mean effectiveness of the older
    half of the corpus to the newer half.

    This is the success-criterion metric: a positive delta means a creator
    generating carousels later receives better output than one generating
    earlier — the whole point of the learning system.
    """
    if len(genomes) < _TREND_MIN:
        return {"available": False, "older": 0.0, "recent": 0.0, "delta": 0.0,
                "improving": False, "n": len(genomes)}
    ordered = sorted(genomes, key=lambda g: g.get("created_at", ""))
    mid = len(ordered) // 2
    older = ordered[:mid]
    recent = ordered[mid:]
    older_mean = sum(effectiveness(g) for g in older) / len(older)
    recent_mean = sum(effectiveness(g) for g in recent) / len(recent)
    delta = recent_mean - older_mean
    return {
        "available": True,
        "older": round(older_mean, 3),
        "recent": round(recent_mean, 3),
        "delta": round(delta, 3),
        "improving": delta > 0.005,
        "n": len(genomes),
    }


def summary(genomes: Sequence[dict]) -> dict:
    n = len(genomes)
    approved = sum(1 for g in genomes if g.get("approved"))
    avg_final = (sum((g.get("final_score") or 0.0) for g in genomes) / n) if n else 0.0
    avg_eff = (sum(effectiveness(g) for g in genomes) / n) if n else 0.0
    return {
        "total_generated": n,
        "approved": approved,
        "rejected": n - approved,
        "approval_rate": round(approved / n, 3) if n else 0.0,
        "avg_final_score": round(avg_final, 1),
        "avg_effectiveness": round(avg_eff, 3),
        "survival_rate": round(survival_rate(genomes), 3),
    }


def build_insights(genomes: Sequence[dict]) -> dict:
    """The complete Performance Insights payload for the dashboard."""
    return {
        "summary": summary(genomes),
        "trend": improvement_trend(genomes),
        "top_hooks": _top_patterns(genomes, "hook"),
        "top_covers": _top_patterns(genomes, "cover"),
        "top_ctas": _top_patterns(genomes, "cta"),
        "failure_patterns": failure_patterns(genomes),
        "ai_signals": ai_signal_frequency(genomes),
        "quality_fail_reasons": quality_fail_reasons(genomes),
        "selection_frequency": {
            "hook": selection_frequency(genomes, "hook"),
            "cover": selection_frequency(genomes, "cover"),
            "cta": selection_frequency(genomes, "cta"),
        },
        "patterns": {
            "hook": category_patterns(genomes, "hook"),
            "cover": category_patterns(genomes, "cover"),
            "cta": category_patterns(genomes, "cta"),
        },
    }


__all__ = [
    "build_insights",
    "summary",
    "improvement_trend",
    "failure_patterns",
    "ai_signal_frequency",
    "quality_fail_reasons",
]
