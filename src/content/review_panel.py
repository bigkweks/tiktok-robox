"""
Three-reviewer content approval panel.

A generated carousel is NOT complete until it survives review. Every carousel
is judged by three independent reviewer personas, each scoring 0–100 through
its own lens:

  1. Growth Strategist     — will this stop the scroll, retain, earn saves + follows?
  2. Successful Roblox Creator — would I actually post this? authentic? on-culture? original?
  3. Skeptical Viewer      — seen it before? feels AI? worth attention? keep swiping?

The three are deliberately different weightings of the same underlying signals,
so they function as genuinely independent evaluations rather than one score
reported three times.

Alongside the personas, a single **Final Quality Score** (0–100) is computed
from seven weighted dimensions:

  Hook 20% · Curiosity 15% · Authenticity 20% · Readability 15%
  Retention 15% · Saveability 10% · Follow Conversion 5%

And a set of **hard-failure conditions** auto-reject a carousel regardless of
score (repetitive phrasing, generic hook, AI wording, weak CTA, a low-value /
purposeless / removable slide). A carousel is APPROVED only when it clears the
score bar AND every reviewer's floor AND has zero hard failures.

Deterministic and heuristic (no extra API calls): reuses the scoring primitives
in `carousel_quality` and `caption_utils`, and the slide-purpose plan from
`creator_brief`, so the whole panel is fast and fully testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.content.caption_utils import (
    crutch_tag,
    has_ai_tell,
    has_internal_repetition,
    is_generic,
    normalize_caption,
    specificity_score,
)
from src.content.carousel_quality import (
    review_carousel,
    score_caption,
    score_cta,
    score_hook,
    score_novelty,
)

# ── Bars ───────────────────────────────────────────────────────────────────

# A carousel must clear ALL of these to be approved. Set strict on purpose —
# the objective is fewer, significantly stronger carousels.
APPROVE_FINAL_SCORE: float = 68.0      # weighted Final Quality Score (0–100)
APPROVE_REVIEWER_FLOOR: float = 60.0   # every reviewer must reach this

# Seven-dimension weights for the Final Quality Score (sum = 1.0).
FINAL_WEIGHTS: dict[str, float] = {
    "hook": 0.20,
    "curiosity": 0.15,
    "authenticity": 0.20,
    "readability": 0.15,
    "retention": 0.15,
    "saveability": 0.10,
    "follow": 0.05,
}


def _clamp100(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)


# ── Dimension scores (0..1) ────────────────────────────────────────────────

@dataclass
class Dimensions:
    """The seven weighted dimensions, each 0..1, plus the helper signals the
    reviewers and hard-failure checks read from."""
    hook: float
    curiosity: float
    authenticity: float
    readability: float
    retention: float
    saveability: float
    follow: float
    # supporting signals
    novelty: float
    specificity_frac: float
    ai_ratio: float
    culture: float

    def final_score(self) -> float:
        s = sum(FINAL_WEIGHTS[k] * getattr(self, k) for k in FINAL_WEIGHTS)
        return _clamp100(s * 100)

    def as_dict(self) -> dict:
        return {k: round(getattr(self, k), 3) for k in (
            "hook", "curiosity", "authenticity", "readability", "retention",
            "saveability", "follow", "novelty", "specificity_frac", "ai_ratio",
            "culture",
        )}


def compute_dimensions(
    cover_hook: str,
    captions: Sequence[str],
    blurbs: Sequence[str],
    cta: str,
    plan=None,
) -> Dimensions:
    caps = [c for c in captions if c]
    report = review_carousel(cover_hook, caps, list(blurbs), cta)

    cap_scores = [score_caption(c) for c in caps] or [0.0]
    novelty = score_novelty(caps, cover_hook)

    # Retention is a derived dimension: the weakest slide still has to hold the
    # swipe (min caption), the batch must not be monotonous (novelty), no slide
    # may be dead weight (purpose plan), and the opener must pull (hook).
    dead_ratio = 0.0
    if plan is not None and caps:
        dead_ratio = len(plan.dead_slides) / max(len(caps), 1)
    retention = max(0.0, min(1.0,
        0.35 * min(cap_scores)
        + 0.25 * novelty
        + 0.25 * (1.0 - dead_ratio)
        + 0.15 * report.hook
    ))

    # Supporting signals.
    all_texts = [cover_hook, cta, *caps, *[b for b in blurbs if b]]
    ai_hits = sum(1 for t in all_texts if has_ai_tell(t))
    ai_ratio = ai_hits / max(len(all_texts), 1)
    spec_frac = (sum(1 for c in caps if specificity_score(c) >= 1) / len(caps)) if caps else 0.0
    culture = max(0.0, min(1.0,
        0.5 * report.authenticity + 0.3 * spec_frac + 0.2 * (1.0 - ai_ratio)
    ))

    return Dimensions(
        hook=report.hook,
        curiosity=report.curiosity,
        authenticity=report.authenticity,
        readability=report.readability,
        retention=retention,
        saveability=report.saveability,
        follow=report.follow,
        novelty=novelty,
        specificity_frac=spec_frac,
        ai_ratio=ai_ratio,
        culture=culture,
    )


# ── Reviewer verdicts ──────────────────────────────────────────────────────

@dataclass
class ReviewerVerdict:
    name: str
    score: float                       # 0–100
    answers: dict[str, float]          # each sub-question, 0–100
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "answers": {k: round(v, 1) for k, v in self.answers.items()},
            "notes": self.notes,
        }


def _growth_strategist(d: Dimensions) -> ReviewerVerdict:
    answers = {
        "stops_scrolling": _clamp100(d.hook * 100),
        "increases_retention": _clamp100(d.retention * 100),
        "increases_saves": _clamp100(d.saveability * 100),
        "increases_follows": _clamp100(d.follow * 100),
    }
    score = _clamp100(sum(answers.values()) / len(answers))
    notes = []
    if answers["stops_scrolling"] < 60:
        notes.append("cover unlikely to stop the scroll")
    if answers["increases_retention"] < 60:
        notes.append("retention arc is weak — a slide may not earn the swipe")
    return ReviewerVerdict("Growth Strategist", score, answers, notes)


def _roblox_creator(d: Dimensions) -> ReviewerVerdict:
    answers = {
        "would_post": _clamp100((0.6 * d.authenticity + 0.4 * d.hook) * 100),
        "authentic": _clamp100(d.authenticity * 100),
        "matches_culture": _clamp100(d.culture * 100),
        "feels_original": _clamp100(d.novelty * 100),
    }
    score = _clamp100(sum(answers.values()) / len(answers))
    notes = []
    if answers["authentic"] < 70:
        notes.append("reads produced, not like a real player")
    if answers["feels_original"] < 60:
        notes.append("too close to a format that's already everywhere")
    return ReviewerVerdict("Successful Roblox Creator", score, answers, notes)


def _skeptical_viewer(d: Dimensions) -> ReviewerVerdict:
    answers = {
        "feels_fresh": _clamp100(d.novelty * 100),               # "have I seen this?"
        "not_ai": _clamp100((1.0 - d.ai_ratio) * 100),           # "feels AI-generated?"
        "worth_attention": _clamp100((0.5 * d.specificity_frac + 0.5 * d.curiosity) * 100),
        "keep_swiping": _clamp100((0.5 * d.hook + 0.5 * d.retention) * 100),
    }
    score = _clamp100(sum(answers.values()) / len(answers))
    notes = []
    if answers["not_ai"] < 75:
        notes.append("smells AI-generated")
    if answers["worth_attention"] < 60:
        notes.append("nothing concrete enough to be worth stopping for")
    return ReviewerVerdict("Skeptical Viewer", score, answers, notes)


# ── Hard-failure detection ─────────────────────────────────────────────────

def detect_hard_failures(
    cover_hook: str,
    captions: Sequence[str],
    blurbs: Sequence[str],
    cta: str,
    d: Dimensions,
    plan=None,
) -> list[str]:
    """Conditions that auto-reject a carousel regardless of its score."""
    caps = [c for c in captions if c]
    failures: list[str] = []

    # Repetitive phrasing: actual stutters and duplicate lines only. The novelty
    # dimension (d.novelty) is influenced by domain vocabulary ("game", "roblox")
    # that legitimately repeats in this content type — those words are stopwords in
    # score_novelty. Hard-fail only on structural repetition (same normalized caption
    # twice, same slang crutch twice, internal stutter), not on novelty score alone.
    norms = [normalize_caption(c) for c in caps]
    tags = [t for t in (crutch_tag(c) for c in caps) if t]
    if (any(has_internal_repetition(c) for c in caps)
            or len(set(norms)) < len(norms)
            or len(tags) != len(set(tags))):
        failures.append("repetitive phrasing")

    # Generic hook.
    if is_generic(cover_hook) or score_hook(cover_hook) < 0.45:
        failures.append("generic hook")

    # AI-style wording in audience-facing copy only (hook, captions, CTA).
    # Blurbs are Claude's internal game analysis rendered as "why it slaps" callouts
    # and may contain analytical language — don't gate the whole carousel on them.
    if any(has_ai_tell(t) for t in [cover_hook, cta, *caps]):
        failures.append("ai-style wording")

    # Weak CTA.
    if score_cta(cta) < 0.40:
        failures.append("weak cta")

    # Low-value slide: only if more than one caption scores below floor, or a
    # plan explicitly marks slides as purposeless. One weak slide can be replaced.
    if plan is not None and plan.dead_slides:
        failures.append("low-value slide (serves no purpose)")
    elif sum(1 for c in caps if score_caption(c) < 0.35) > 1:
        failures.append("low-value slides (multiple captions too weak)")

    return failures


# ── Panel result ───────────────────────────────────────────────────────────

@dataclass
class PanelResult:
    reviewers: list[ReviewerVerdict]
    dimensions: Dimensions
    final_score: float                 # 0–100, the weighted Final Quality Score
    hard_failures: list[str]
    approved: bool

    @property
    def min_reviewer(self) -> float:
        return min((r.score for r in self.reviewers), default=0.0)

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "final_score": self.final_score,
            "min_reviewer": self.min_reviewer,
            "hard_failures": self.hard_failures,
            "reviewers": [r.as_dict() for r in self.reviewers],
            "dimensions": self.dimensions.as_dict(),
        }


def evaluate_panel(
    cover_hook: str,
    captions: Sequence[str],
    blurbs: Sequence[str],
    cta: str,
    plan=None,
) -> PanelResult:
    """Run all three reviewers + compute the Final Quality Score + hard failures."""
    d = compute_dimensions(cover_hook, captions, blurbs, cta, plan=plan)
    reviewers = [_growth_strategist(d), _roblox_creator(d), _skeptical_viewer(d)]
    final_score = d.final_score()
    failures = detect_hard_failures(cover_hook, captions, blurbs, cta, d, plan=plan)

    approved = (
        not failures
        and final_score >= APPROVE_FINAL_SCORE
        and all(r.score >= APPROVE_REVIEWER_FLOOR for r in reviewers)
    )
    return PanelResult(
        reviewers=reviewers,
        dimensions=d,
        final_score=final_score,
        hard_failures=failures,
        approved=approved,
    )


__all__ = [
    "APPROVE_FINAL_SCORE",
    "APPROVE_REVIEWER_FLOOR",
    "FINAL_WEIGHTS",
    "Dimensions",
    "ReviewerVerdict",
    "PanelResult",
    "compute_dimensions",
    "detect_hard_failures",
    "evaluate_panel",
]
