"""
Component ranking + the anti-convergence generation bias.

For every generation component the system computes four numbers:

  success_confidence       A Wilson lower bound on the component's "win rate"
                           (share of its uses that were high-quality AND survived
                           editing). Grows with evidence: one good carousel is a
                           guess, twenty is a law — so confidence rises with n,
                           never just the raw average.
  historical_effectiveness Mean realised/proxy performance of carousels built
                           with this component (final score + edit-resilience,
                           blended with realised saves/follows once known).
  diversity_score          How much picking this component would *preserve
                           variation* (1 − its recent selection share). High when
                           the component is under-used, low when it dominates.
  novelty_score            How fresh the component is — rewards rarely/recently
                           used components so emerging winners get airtime.

These combine into a single, deliberately *small* additive `bias` the generator
adds to a component's intrinsic score. The bias gradually steers generation
toward higher-performing structures **while preventing convergence**:

  * It is clamped to ±`BIAS_CAP` (a nudge, never an override) so a proven
    component can't swamp the intrinsic quality competition.
  * Any component whose recent selection share exceeds `DOMINANCE_SHARE` is
    forced to a *negative* bias regardless of how well it performs — so no single
    successful template is ever allowed to dominate every drop. Variation,
    originality and authenticity are preserved structurally, not by hope.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

# Minimum uses before a component's averages are trusted as "strong/weak".
MIN_SAMPLE: int = 5

# A component used in more than this share of recent drops is "overused" — the
# convergence guard kicks in and its bias goes negative.
DOMINANCE_SHARE: float = 0.40

# How many of the most-recent genomes define "recent" for share/novelty.
RECENT_WINDOW: int = 24

# The generation bias is a nudge, never an override.
BIAS_CAP: float = 0.06

# Blend weights for the bias (prefer-proven vs. explore-new vs. avoid-repetition).
_W_EFFECTIVENESS: float = 0.7
_W_NOVELTY: float = 0.4
_W_REPETITION: float = 0.6

# A carousel "succeeds" when it both cleared the quality bar and survived review
# with minimal rework — i.e. it's the kind of output we want more of.
_SUCCESS_FINAL: float = 80.0
_SUCCESS_RESILIENCE: float = 0.6


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def effectiveness(g: dict) -> float:
    """Proxy effectiveness of a single genome in [0,1].

    Blends the panel's Final Quality Score with how intact the draft survived
    editing. Once the analytics loop attaches *realised* outcomes (a 0..1
    `performance_index` from saves/follows), they dominate — measured beats
    predicted.
    """
    base = _clamp((g.get("final_score") or 0.0) / 100.0)
    resilience = _clamp(g.get("edit_resilience") or 0.0)
    proxy = 0.6 * base + 0.4 * resilience

    outcomes = g.get("outcomes") or {}
    idx = outcomes.get("performance_index")
    if idx is not None and (outcomes.get("samples") or 0) > 0:
        return _clamp(0.5 * proxy + 0.5 * _clamp(float(idx)))
    return proxy


def is_success(g: dict) -> bool:
    return (
        bool(g.get("approved"))
        and (g.get("final_score") or 0.0) >= _SUCCESS_FINAL
        and (g.get("edit_resilience") or 0.0) >= _SUCCESS_RESILIENCE
    )


def _wilson_lower_bound(successes: int, n: int, z: float = 1.64) -> float:
    """Wilson score lower bound (≈90% one-sided). 0 when n == 0.

    This is why confidence *grows with evidence*: a 1/1 success rate yields a
    far lower bound than 18/20, even though both have a raw mean of ≥0.9.
    """
    if n <= 0:
        return 0.0
    phat = successes / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return _clamp((centre - margin) / denom)


@dataclass
class ComponentStat:
    category: str
    name: str
    n: int                      # total uses
    recent_n: int               # uses within the recent window
    selection_share: float      # recent share (0..1) — the repetition signal
    success_confidence: float   # Wilson lower bound on win-rate
    historical_effectiveness: float
    diversity_score: float
    novelty_score: float
    bias: float                 # the capped, anti-convergence generation nudge
    approval_rate: float
    avg_final_score: float

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "name": self.name,
            "n": self.n,
            "recent_n": self.recent_n,
            "selection_share": round(self.selection_share, 3),
            "success_confidence": round(self.success_confidence, 3),
            "historical_effectiveness": round(self.historical_effectiveness, 3),
            "diversity_score": round(self.diversity_score, 3),
            "novelty_score": round(self.novelty_score, 3),
            "bias": round(self.bias, 4),
            "approval_rate": round(self.approval_rate, 3),
            "avg_final_score": round(self.avg_final_score, 1),
            "overused": self.selection_share > DOMINANCE_SHARE,
        }


def _recent(genomes: Sequence[dict], window: int = RECENT_WINDOW) -> list[dict]:
    """The most-recent `window` genomes (input is assumed newest-first or is
    sorted by created_at descending here defensively)."""
    ordered = sorted(genomes, key=lambda g: g.get("created_at", ""), reverse=True)
    return ordered[:window]


def component_stats(
    genomes: Sequence[dict], category: str, window: int = RECENT_WINDOW,
) -> dict[str, ComponentStat]:
    """Compute the full ranking statistics for every component in a category."""
    members: dict[str, list[dict]] = {}
    for g in genomes:
        name = _component_of(g, category)
        if not name:
            continue
        members.setdefault(name, []).append(g)

    recent = _recent(genomes, window)
    recent_total = len(recent)
    recent_counts: dict[str, int] = {}
    for g in recent:
        name = _component_of(g, category)
        if name:
            recent_counts[name] = recent_counts.get(name, 0) + 1

    # ── Pass 1: per-component metrics + a raw 'desirability' score. ──
    raw: dict[str, dict] = {}
    for name, gs in members.items():
        n = len(gs)
        effs = [effectiveness(g) for g in gs]
        hist_eff = sum(effs) / n if n else 0.0
        successes = sum(1 for g in gs if is_success(g))
        conf = _wilson_lower_bound(successes, n)
        recent_n = recent_counts.get(name, 0)
        share = (recent_n / recent_total) if recent_total else 0.0
        diversity = _clamp(1.0 - share)
        # Novelty rewards rarely-recently-used components (emerging > entrenched).
        novelty = 1.0 / (1.0 + recent_n)
        approvals = sum(1 for g in gs if g.get("approved"))
        approval_rate = approvals / n if n else 0.0
        avg_final = sum((g.get("final_score") or 0.0) for g in gs) / n if n else 0.0
        # Prefer proven (effectiveness × confidence), explore the new (novelty),
        # avoid repetition (share).
        desire = (
            _W_EFFECTIVENESS * hist_eff * conf
            + _W_NOVELTY * novelty
            - _W_REPETITION * share
        )
        raw[name] = dict(
            n=n, recent_n=recent_n, share=share, conf=conf, hist_eff=hist_eff,
            diversity=diversity, novelty=novelty, approval_rate=approval_rate,
            avg_final=avg_final, desire=desire,
        )

    # ── Pass 2: center desirability on the category mean so the bias is
    # *relative* — above-average components get a positive nudge, below-average
    # a negative one. This is what makes the generator gradually PREFER the
    # better structures, instead of every bias collapsing the same direction.
    mean_desire = (
        sum(r["desire"] for r in raw.values()) / len(raw) if raw else 0.0
    )

    stats: dict[str, ComponentStat] = {}
    for name, r in raw.items():
        bias = _bias_from_desire(r["desire"], mean_desire, r["share"])
        stats[name] = ComponentStat(
            category=category,
            name=name,
            n=r["n"],
            recent_n=r["recent_n"],
            selection_share=r["share"],
            success_confidence=r["conf"],
            historical_effectiveness=r["hist_eff"],
            diversity_score=r["diversity"],
            novelty_score=r["novelty"],
            bias=bias,
            approval_rate=r["approval_rate"],
            avg_final_score=r["avg_final"],
        )
    return stats


def _bias_from_desire(desire: float, mean_desire: float, share: float) -> float:
    """The capped, anti-convergence nudge for one component.

    Centered on the category mean so it spreads above/below zero. A dominating
    component is forced negative regardless of performance — the hard structural
    guarantee that one successful template can never take over every generation.
    """
    if share > DOMINANCE_SHARE:
        return -BIAS_CAP
    return max(-BIAS_CAP, min(BIAS_CAP, desire - mean_desire))


def component_bias(
    genomes: Sequence[dict], category: str, window: int = RECENT_WINDOW,
) -> dict[str, float]:
    """The map a generator consults: component name → additive score nudge.

    Empty when there's no history yet (cold start → pure intrinsic scoring, no
    bias). Capped and anti-convergent by construction.
    """
    if not genomes:
        return {}
    return {name: s.bias for name, s in component_stats(genomes, category, window).items()}


def _component_of(g: dict, category: str) -> str:
    return {
        "hook": g.get("hook_pattern", ""),
        "cover": g.get("cover_concept", ""),
        "structure": g.get("structure", ""),
        "cta": g.get("cta_pattern", ""),
    }.get(category, "")


__all__ = [
    "MIN_SAMPLE",
    "DOMINANCE_SHARE",
    "RECENT_WINDOW",
    "BIAS_CAP",
    "ComponentStat",
    "effectiveness",
    "is_success",
    "component_stats",
    "component_bias",
]
