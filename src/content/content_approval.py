"""
Mandatory content-approval system.

A generated carousel is not "done" when it is generated — it is done only when
it survives review. This module runs the explicit revision cycle:

    Generate → Critique → Revise → Re-score → Critique again → Finalize

up to a maximum of 3 cycles, gating on the three-reviewer panel
(`review_panel.evaluate_panel`). The user is NEVER shown the first draft — the
pipeline persists a carousel only when `approved` is True, so only content that
passes the panel (clears the Final Quality Score bar, every reviewer's floor,
and zero hard failures) is ever surfaced.

If three cycles can't produce an approved carousel, nothing is shipped. The
objective is not more content — it is fewer, significantly stronger carousels.

Deterministic (no extra API calls): each cycle re-runs `finalize_carousel`
(generate + internal revision) and, between cycles, applies an explicit revise
step — it rotates away from a rejected cover hook and swaps the weakest caption
for a stronger, unused bank line — so every cycle is a genuine improvement, not
a re-roll of the same output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import structlog

from src.content.caption_utils import (
    _candidates,
    has_ai_tell,
    normalize_caption,
)
from src.content.carousel_quality import finalize_carousel, score_caption
from src.content.review_panel import PanelResult, evaluate_panel

log = structlog.get_logger(__name__)

MAX_CYCLES: int = 3


@dataclass
class ApprovalResult:
    approved: bool
    final_score: float
    cycles: int
    panel: PanelResult
    # The surviving (or best-attempted) content.
    cover_hook: str
    captions: list[str]
    cta: str
    post_caption: str
    cover_concept: str = ""
    report: object = None          # carousel_quality.QualityReport
    plan: object = None            # creator_brief.CarouselPlan
    trail: list[dict] = field(default_factory=list)   # per-cycle critique record

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "final_score": self.final_score,
            "cycles": self.cycles,
            "cover_concept": self.cover_concept,
            "panel": self.panel.as_dict() if self.panel else None,
            "trail": self.trail,
        }


def _revise_captions(
    captions: Sequence[str],
    genres: Sequence[Optional[str]],
    scores: Sequence[Optional[float]],
    used: set[str],
) -> list[str]:
    """Explicit revise step: replace the single weakest caption (or any that
    reads AI) with the strongest unused bank alternative. Guarantees the next
    cycle's input differs, so re-scoring reflects a real change."""
    caps = list(captions)
    if not caps:
        return caps

    # Target: the weakest caption, or the first AI-tell caption if one exists.
    target = None
    ai_idx = next((i for i, c in enumerate(caps) if has_ai_tell(c)), None)
    if ai_idx is not None:
        target = ai_idx
    else:
        target = min(range(len(caps)), key=lambda i: score_caption(caps[i]))

    gi = genres[target] if target < len(genres) else None
    si = scores[target] if target < len(scores) else None
    best_alt, best_score = None, score_caption(caps[target])
    for cand in _candidates(gi, si):
        n = normalize_caption(cand)
        if n in used or has_ai_tell(cand):
            continue
        s = score_caption(cand)
        if s > best_score:
            best_alt, best_score = cand, s
    if best_alt is not None:
        used.add(normalize_caption(best_alt))
        caps[target] = best_alt
    return caps


class ContentApprovalSystem:
    """Runs the mandatory Generate→Critique→Revise→Re-score→Critique→Finalize
    cycle and returns only what survives review."""

    def approve(
        self,
        part: int,
        edition: str,
        captions: Sequence[Optional[str]],
        blurbs: Sequence[Optional[str]],
        genres: Optional[Sequence[Optional[str]]] = None,
        scores: Optional[Sequence[Optional[float]]] = None,
        game_names: Optional[Sequence[str]] = None,
        dna=None,
        used_hooks: Optional[set[str]] = None,
        max_cycles: int = MAX_CYCLES,
    ) -> ApprovalResult:
        n = len(captions)
        genres_list = list(genres) if genres is not None else [None] * n
        scores_list = list(scores) if scores is not None else [None] * n
        used_hooks = set(used_hooks or set())
        used_caps: set[str] = set()

        current_caps: list[str] = [c or "" for c in captions]
        trail: list[dict] = []
        best: Optional[ApprovalResult] = None

        for cycle in range(1, max(1, max_cycles) + 1):
            # ── Generate (cycle 1) / Re-score the revised input (later cycles) ──
            final = finalize_carousel(
                part=part,
                edition=edition,
                captions=current_caps,
                blurbs=list(blurbs),
                genres=genres_list,
                scores=scores_list,
                game_names=game_names,
                used_hooks=used_hooks,
                dna=dna,
            )

            # ── Critique ──
            panel = evaluate_panel(
                final["cover_hook"], final["captions"], list(blurbs),
                final["cta"], plan=final.get("plan"),
            )

            result = ApprovalResult(
                approved=panel.approved,
                final_score=panel.final_score,
                cycles=cycle,
                panel=panel,
                cover_hook=final["cover_hook"],
                captions=list(final["captions"]),
                cta=final["cta"],
                post_caption=final["post_caption"],
                cover_concept=final.get("cover_concept", ""),
                report=final.get("report"),
                plan=final.get("plan"),
            )
            trail.append({
                "cycle": cycle,
                "action": "generate" if cycle == 1 else "revise",
                "final_score": panel.final_score,
                "min_reviewer": panel.min_reviewer,
                "reviewers": {r.name: r.score for r in panel.reviewers},
                "hard_failures": panel.hard_failures,
                "approved": panel.approved,
            })

            # Track the strongest attempt so we always know the best we built.
            if best is None or panel.final_score > best.final_score:
                best = result

            if panel.approved:
                result.trail = trail
                log.info("content_approval.approved", part=part, cycle=cycle,
                         final_score=panel.final_score,
                         reviewers={r.name: r.score for r in panel.reviewers})
                return result

            # ── Revise for the next cycle: don't reuse a rejected cover hook,
            # and swap the weakest caption for a stronger unused line. ──
            used_hooks.add(normalize_caption(final["cover_hook"]))
            used_caps.update(normalize_caption(c) for c in final["captions"])
            current_caps = _revise_captions(
                final["captions"], genres_list, scores_list, used_caps,
            )
            log.info("content_approval.revising", part=part, cycle=cycle,
                     final_score=panel.final_score,
                     hard_failures=panel.hard_failures)

        # Three cycles, still not approved → nothing ships. Return the best we
        # built so the caller can log WHY it was rejected.
        assert best is not None
        best.trail = trail
        best.cycles = max_cycles
        log.warning("content_approval.rejected", part=part,
                    final_score=best.final_score,
                    hard_failures=best.panel.hard_failures,
                    reviewers={r.name: r.score for r in best.panel.reviewers})
        return best


__all__ = ["ContentApprovalSystem", "ApprovalResult", "MAX_CYCLES"]
