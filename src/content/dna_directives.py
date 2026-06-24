"""
DNA → generation bridge.

This is the payoff of the whole Content DNA system: instead of generating from
a generic prompt, generation reads the *extracted* DNA and is steered by it.

`derive_directives(profile)` converts a ContentDNAProfile into a small, concrete
`GenerationDirectives` object the cover generator and quality gate can act on —
which hook qualities to favour, how tight to keep the copy, whether a save/follow
trigger is required. Each directive is gated by the confidence of the pattern it
came from, so a low-confidence DNA nudges generation gently while a corroborated,
high-confidence DNA steers it firmly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.content.content_dna import WEAK_CONFIDENCE, ContentDNAProfile


@dataclass
class GenerationDirectives:
    """Concrete, DNA-derived levers for generation. `weight` (0..1) scales how
    strongly they're applied — it tracks the DNA's confidence."""
    active: bool = False
    weight: float = 0.0
    prefer_curiosity_gap: bool = False
    prefer_specificity: bool = False
    prefer_first_person: bool = False
    max_hook_words: int = 9
    require_save_trigger: bool = False
    require_follow_trigger: bool = False
    hook_keywords: tuple[str, ...] = field(default_factory=tuple)
    source_label: str = ""

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "weight": round(self.weight, 3),
            "prefer_curiosity_gap": self.prefer_curiosity_gap,
            "prefer_specificity": self.prefer_specificity,
            "prefer_first_person": self.prefer_first_person,
            "max_hook_words": self.max_hook_words,
            "require_save_trigger": self.require_save_trigger,
            "require_follow_trigger": self.require_follow_trigger,
            "hook_keywords": list(self.hook_keywords),
            "source_label": self.source_label,
        }


# Tokens worth carrying into hook selection when the DNA's hook drivers mention
# them — intersected against the observation text so we only forward signal.
_HOOK_SIGNAL_WORDS: frozenset[str] = frozenset({
    "search", "niche", "specific", "number", "visits", "curiosity",
    "gap", "qualifier", "credibility", "trust", "fomo", "vetted",
})

_SPECIFICITY_MARKERS = ("specif", "number", "named", "search", "niche", "stat", "visit")
_FIRST_PERSON_MARKERS = ("first-person", "first person", "creator", "i play", "personal", "confession")


def _has(text: str, markers) -> bool:
    low = (text or "").lower()
    return any(m in low for m in markers)


def derive_directives(profile: ContentDNAProfile) -> GenerationDirectives:
    """Translate a DNA profile into concrete generation levers."""
    if profile is None:
        return GenerationDirectives()

    patterns = profile.patterns
    hook_conf = profile.hook_formula.confidence
    cta_conf = profile.cta_formula.confidence

    def conf(dim: str) -> float:
        p = patterns.get(dim)
        return p.confidence if p else 0.0

    def obs(dim: str) -> str:
        p = patterns.get(dim)
        return p.observation if p else ""

    prefer_curiosity = conf("curiosity_mechanisms") >= WEAK_CONFIDENCE
    prefer_specificity = (
        _has(obs("hook_structure"), _SPECIFICITY_MARKERS)
        or _has(obs("information_hierarchy"), _SPECIFICITY_MARKERS)
    ) and conf("hook_structure") >= WEAK_CONFIDENCE
    prefer_first_person = _has(obs("emotional_triggers") + " " + obs("hook_structure"),
                               _FIRST_PERSON_MARKERS)

    # Reading-pace observation often states an explicit word target ("3-8 words").
    max_words = 9
    pace = obs("reading_pace")
    nums = [int(n) for n in re.findall(r"\d+", pace) if int(n) <= 20]
    if nums:
        max_words = max(5, max(nums))

    require_save = conf("save_triggers") >= WEAK_CONFIDENCE
    require_follow = conf("follow_triggers") >= WEAK_CONFIDENCE

    # Forward only the signal words the hook drivers actually mention.
    hook_text = " ".join(d.observation for d in profile.hook_formula.drivers).lower()
    keywords = tuple(sorted(w for w in _HOOK_SIGNAL_WORDS if w in hook_text))

    weight = round(max(hook_conf, cta_conf), 3)
    active = weight >= WEAK_CONFIDENCE

    return GenerationDirectives(
        active=active,
        weight=weight,
        prefer_curiosity_gap=prefer_curiosity,
        prefer_specificity=prefer_specificity,
        prefer_first_person=prefer_first_person,
        max_hook_words=max_words,
        require_save_trigger=require_save,
        require_follow_trigger=require_follow,
        hook_keywords=keywords,
        source_label=profile.label,
    )


__all__ = ["GenerationDirectives", "derive_directives"]
