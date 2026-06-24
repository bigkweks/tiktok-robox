"""
The carousel genome — the feedback architecture's atomic record.

For *every* generated carousel (whether it survived review or not) we store a
`CarouselGenome`: the full set of decisions that produced it plus how it scored.
This is the raw material the evaluation framework, the ranking system, and the
insights dashboard all read from. A row's components are pre-classified at write
time (see `components.py`) so analysis never has to re-derive them.

Stored fields map directly onto the brief:
    Topic                → topic / genres / game_names
    Hook                 → hook (+ hook_pattern family)
    Cover structure      → cover_concept (the archetype)
    Slide count          → slide_count (+ structure signature)
    CTA style            → cta (+ cta_pattern family)
    Content DNA profile  → dna_profile (the blueprint fingerprint that steered it)
    Generation settings  → generation_settings (attempts, cycles, dna/perf driven)
    Quality scores       → quality_scores (the 7 weighted dims + final score)
    Authenticity scores  → authenticity_scores (authenticity / ai_ratio / culture / novelty)

Plus the review outcome (approved, hard failures, fail reasons, reviewer scores,
AI signals detected) and a slot for *realised* outcomes (saves/follows) that the
analytics loop can fill in later via `PerformanceStore.update_outcome`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def edit_resilience_from_cycles(approved: bool, cycles: int) -> float:
    """Proxy for 'survives editing with minimal changes'.

    Fewer revision cycles ⇒ the first draft needed less rework ⇒ it survived
    editing more intact. Approved on cycle 1 is the gold standard (1.0); each
    extra cycle the panel forced means the draft was reworked more, so the score
    decays. A rejected carousel survived no editing (0.0). When real
    human-edit-distance data arrives it can override this estimate.
    """
    if not approved:
        return 0.0
    return {1: 1.0, 2: 0.6, 3: 0.3}.get(max(1, int(cycles)), 0.3)


@dataclass
class CarouselGenome:
    # ── Identity ──────────────────────────────────────────────────────────
    part: int
    edition: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=_now_iso)

    # ── Topic ─────────────────────────────────────────────────────────────
    topic: str = ""
    genres: list[str] = field(default_factory=list)
    game_names: list[str] = field(default_factory=list)

    # ── Components ────────────────────────────────────────────────────────
    hook: str = ""
    hook_pattern: str = ""          # classified hook family
    cover_concept: str = ""         # cover structure archetype
    slide_count: int = 6
    structure: str = ""             # structure signature
    cta: str = ""
    cta_pattern: str = ""           # classified cta family

    # ── Content DNA fingerprint that steered generation ───────────────────
    dna_profile: dict = field(default_factory=dict)

    # ── Generation settings ───────────────────────────────────────────────
    generation_settings: dict = field(default_factory=dict)

    # ── Scores ────────────────────────────────────────────────────────────
    quality_scores: dict = field(default_factory=dict)
    authenticity_scores: dict = field(default_factory=dict)
    final_score: float = 0.0

    # ── Review outcome ────────────────────────────────────────────────────
    approved: bool = False
    cycles: int = 1
    hard_failures: list[str] = field(default_factory=list)
    fail_reasons: list[str] = field(default_factory=list)
    reviewer_scores: dict = field(default_factory=dict)
    ai_signals: list[str] = field(default_factory=list)
    edit_resilience: float = 0.0

    # ── Realised performance (filled in later by the analytics loop) ──────
    outcomes: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "part": self.part,
            "edition": self.edition,
            "topic": self.topic,
            "genres": list(self.genres),
            "game_names": list(self.game_names),
            "hook": self.hook,
            "hook_pattern": self.hook_pattern,
            "cover_concept": self.cover_concept,
            "slide_count": self.slide_count,
            "structure": self.structure,
            "cta": self.cta,
            "cta_pattern": self.cta_pattern,
            "dna_profile": self.dna_profile,
            "generation_settings": self.generation_settings,
            "quality_scores": self.quality_scores,
            "authenticity_scores": self.authenticity_scores,
            "final_score": round(self.final_score, 2),
            "approved": self.approved,
            "cycles": self.cycles,
            "hard_failures": list(self.hard_failures),
            "fail_reasons": list(self.fail_reasons),
            "reviewer_scores": self.reviewer_scores,
            "ai_signals": list(self.ai_signals),
            "edit_resilience": round(self.edit_resilience, 3),
            "outcomes": self.outcomes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CarouselGenome":
        return cls(
            part=d.get("part", 0),
            edition=d.get("edition", ""),
            id=d.get("id", uuid.uuid4().hex[:12]),
            created_at=d.get("created_at", _now_iso()),
            topic=d.get("topic", ""),
            genres=list(d.get("genres", [])),
            game_names=list(d.get("game_names", [])),
            hook=d.get("hook", ""),
            hook_pattern=d.get("hook_pattern", ""),
            cover_concept=d.get("cover_concept", ""),
            slide_count=d.get("slide_count", 6),
            structure=d.get("structure", ""),
            cta=d.get("cta", ""),
            cta_pattern=d.get("cta_pattern", ""),
            dna_profile=d.get("dna_profile", {}) or {},
            generation_settings=d.get("generation_settings", {}) or {},
            quality_scores=d.get("quality_scores", {}) or {},
            authenticity_scores=d.get("authenticity_scores", {}) or {},
            final_score=d.get("final_score", 0.0),
            approved=d.get("approved", False),
            cycles=d.get("cycles", 1),
            hard_failures=list(d.get("hard_failures", [])),
            fail_reasons=list(d.get("fail_reasons", [])),
            reviewer_scores=d.get("reviewer_scores", {}) or {},
            ai_signals=list(d.get("ai_signals", [])),
            edit_resilience=d.get("edit_resilience", 0.0),
            outcomes=d.get("outcomes"),
        )

    def component(self, category: str) -> str:
        """The component name this genome contributes to a learning category."""
        return {
            "hook": self.hook_pattern,
            "cover": self.cover_concept,
            "structure": self.structure,
            "cta": self.cta_pattern,
        }.get(category, "")


__all__ = ["CarouselGenome", "edit_resilience_from_cycles"]
