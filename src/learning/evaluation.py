"""
Evaluation framework.

Turns the raw component statistics (`ranking.component_stats`) into the four
qualitative judgements the brief asks for, per category:

  STRONG     enough evidence (n ≥ MIN_SAMPLE) AND high effectiveness AND
             real win-rate confidence — a pattern worth leaning into.
  WEAK       enough evidence but low effectiveness — a pattern to retire.
  OVERUSED   recent selection share over the dominance threshold — a
             convergence risk, even if it's also strong.
  EMERGING   recent, still-small sample but already out-performing — a promising
             pattern to give more airtime before it's proven.

A component can carry more than one label (e.g. STRONG *and* OVERUSED — a winner
that's starting to take over). It also tallies which components are *selected*
most often (hooks / covers / structures / CTAs) and which outputs survive editing
with minimal changes — the selection-frequency and edit-survival signals the
brief calls for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.learning.components import CATEGORIES
from src.learning.ranking import (
    DOMINANCE_SHARE,
    MIN_SAMPLE,
    ComponentStat,
    component_stats,
)

STRONG_EFFECTIVENESS: float = 0.62
WEAK_EFFECTIVENESS: float = 0.45
STRONG_CONFIDENCE: float = 0.30
EMERGING_EFFECTIVENESS: float = 0.62
# A genome "survives editing with minimal changes" when its edit-resilience is
# high (approved on an early cycle — see genome.edit_resilience_from_cycles).
SURVIVAL_RESILIENCE: float = 0.6


@dataclass
class PatternVerdict:
    name: str
    stat: ComponentStat
    labels: list[str]   # any of: strong / weak / overused / emerging

    def as_dict(self) -> dict:
        return {**self.stat.as_dict(), "labels": self.labels}


def classify_component(stat: ComponentStat) -> list[str]:
    labels: list[str] = []
    enough = stat.n >= MIN_SAMPLE
    if enough and stat.historical_effectiveness >= STRONG_EFFECTIVENESS \
            and stat.success_confidence >= STRONG_CONFIDENCE:
        labels.append("strong")
    if enough and stat.historical_effectiveness < WEAK_EFFECTIVENESS:
        labels.append("weak")
    if stat.selection_share > DOMINANCE_SHARE:
        labels.append("overused")
    # Emerging: not yet proven (small sample) but already performing AND in
    # active recent use — a pattern on the way up.
    if (not enough) and stat.recent_n >= 1 \
            and stat.historical_effectiveness >= EMERGING_EFFECTIVENESS:
        labels.append("emerging")
    return labels


def evaluate_category(
    genomes: Sequence[dict], category: str,
) -> dict[str, PatternVerdict]:
    stats = component_stats(genomes, category)
    return {
        name: PatternVerdict(name=name, stat=s, labels=classify_component(s))
        for name, s in stats.items()
    }


def selection_frequency(genomes: Sequence[dict], category: str) -> list[tuple[str, int]]:
    """Which components are selected most often, most-frequent first."""
    counts: dict[str, int] = {}
    for g in genomes:
        name = {
            "hook": g.get("hook_pattern", ""),
            "cover": g.get("cover_concept", ""),
            "structure": g.get("structure", ""),
            "cta": g.get("cta_pattern", ""),
        }.get(category, "")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)


def survival_rate(genomes: Sequence[dict]) -> float:
    """Fraction of generated carousels that survived review/editing with minimal
    changes (high edit-resilience). The brief's 'survive editing with minimal
    changes' signal at the corpus level."""
    if not genomes:
        return 0.0
    survived = sum(
        1 for g in genomes if (g.get("edit_resilience") or 0.0) >= SURVIVAL_RESILIENCE
    )
    return survived / len(genomes)


def category_patterns(genomes: Sequence[dict], category: str) -> dict[str, list[dict]]:
    """The strong / weak / overused / emerging buckets for one category."""
    verdicts = evaluate_category(genomes, category)
    buckets: dict[str, list[dict]] = {
        "strong": [], "weak": [], "overused": [], "emerging": [],
    }
    for v in verdicts.values():
        for label in v.labels:
            buckets[label].append(v.as_dict())
    # Most-effective first within each bucket.
    for label in buckets:
        buckets[label].sort(
            key=lambda d: d["historical_effectiveness"], reverse=True,
        )
    return buckets


def evaluate_all(genomes: Sequence[dict]) -> dict[str, dict]:
    """Full evaluation across every category."""
    return {
        cat: {
            "selection_frequency": selection_frequency(genomes, cat),
            "patterns": category_patterns(genomes, cat),
        }
        for cat in CATEGORIES
    }


__all__ = [
    "STRONG_EFFECTIVENESS",
    "WEAK_EFFECTIVENESS",
    "SURVIVAL_RESILIENCE",
    "PatternVerdict",
    "classify_component",
    "evaluate_category",
    "selection_frequency",
    "survival_rate",
    "category_patterns",
    "evaluate_all",
]
