"""
Generation-component taxonomy.

The Performance Learning System learns at the level of *components* — the
reusable building blocks every carousel is assembled from. A component is one
named choice in a category:

    CATEGORY     COMPONENT (the thing we learn about)
    ──────────   ───────────────────────────────────────────────────────────
    hook         the cover hook's *family* (qualifier / stat / confession …)
    cover        the cover concept *archetype* ("The Visit Count", …)
    structure    the carousel structure signature (slide count + edition)
    cta          the closing CTA's *family* (save / question / follow …)

Classifying the hook and CTA into families (rather than keying on the literal
text) is deliberate: it lets the system learn that "first-person confession
hooks convert" even when the exact wording is new — including AI-generated
wording the cover banks never contained. The classifiers are deterministic
keyword buckets so the whole module is testable offline.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from src.content.caption_utils import _AI_TELLS

CATEGORIES: tuple[str, ...] = ("hook", "cover", "structure", "cta")

# ── Hook families ───────────────────────────────────────────────────────────
# Ordered: the first family whose signals fire wins, so the more specific /
# higher-signal families are checked before the generic fallback.

_HOOK_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    # First-person investment ("i spent 3 days", "i tested every horror game").
    ("confession", (
        "i spent", "i tested", "i found", "i played", "i solo", "i grinded",
        "i actually", "i've been", "i finished", "played these", "grinded",
        "solo'd", "tested every",
    )),
    # A concrete Roblox-native number / metric (the strongest specificity lever).
    ("stat", (
        "visits", "like ratio", "% like", "active", "front page", "page 6",
        "better stats",
    )),
    # Blames a platform mechanism (algorithm / search / fyp) for hiding value.
    ("accusation", (
        "algorithm", "fyp", "search won't", "search buried", "explore page",
        "won't show", "been lying", "keeps showing", "keeps serving", "buried",
        "hiding", "hidden by",
    )),
    # Gates the audience by a shared reference ("if you've already beaten doors").
    ("qualifier", (
        "if you've", "if you", "for the ones", "for when", "already beaten",
        "already played", "already seen", "getting boring", "past the",
        "run out of",
    )),
    # Subverts virality = quality ("too good to go viral", "never trended").
    ("paradox", (
        "too good", "too scary", "never trended", "not just", "aren't just",
        "isn't just", "deserve", "skipped by",
    )),
    # Frames knowledge as insider-only ("only the sweats know these").
    ("insider", (
        "only the", "know these", "the serious", "the veterans", "the sweats",
        "found first", "found these first", "got it right",
    )),
]

# CTA families, same ordering principle.
_CTA_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("follow", ("follow", "part ", "next drop", "more coming", "more soon",
                "don't miss the next", "tap follow")),
    ("save", ("save", "keep this", "you'll want", "bookmark", "for later",
              "screenshot")),
    ("question", ("which one", "what's your", "what would", "agree?", "?")),
]

_HOOK_FALLBACK = "curiosity"
_CTA_FALLBACK = "engage"


def _matches(text: str, signals: Iterable[str]) -> bool:
    low = text.lower()
    for s in signals:
        if s == "?":
            if low.strip().endswith("?"):
                return True
        elif s in low:
            return True
    return False


def classify_hook(hook: str | None) -> str:
    """Map a cover hook to its strategy family. Generalises beyond the literal
    bank wording so the learner recognises the *pattern*, not the phrase."""
    if not hook or not hook.strip():
        return _HOOK_FALLBACK
    # A bare number that isn't tied to a metric still reads as a "stat" hook.
    for name, signals in _HOOK_FAMILIES:
        if _matches(hook, signals):
            return name
    if re.search(r"\d", hook):
        return "stat"
    return _HOOK_FALLBACK


def classify_cta(cta: str | None) -> str:
    """Map a closing CTA to its family (save / question / follow / engage)."""
    if not cta or not cta.strip():
        return _CTA_FALLBACK
    for name, signals in _CTA_FAMILIES:
        if _matches(cta, signals):
            return name
    return _CTA_FALLBACK


def structure_signature(slide_count: int, edition: str | None = None) -> str:
    """A coarse structure descriptor. Slide count is the dominant structural
    lever (the proven format is 6 = cover + 5 games); the edition family adds a
    second axis so 'horror 6-slide' and 'friends 6-slide' are distinguishable
    structures without exploding the space."""
    edition_key = (edition or "").split()[0].lower() if edition else "generic"
    return f"{int(slide_count)}-slide/{edition_key}"


def detect_ai_signals(texts: Sequence[str | None]) -> list[str]:
    """Return the distinct AI-tell phrases present across the given texts.

    Drives the dashboard's 'most common AI signals detected' panel. Uses the
    same `_AI_TELLS` vocabulary the quality gate rejects on, so the dashboard
    reports exactly what the gate is catching."""
    found: list[str] = []
    for t in texts:
        if not t:
            continue
        low = t.lower()
        for tell in _AI_TELLS:
            if tell in low and tell not in found:
                found.append(tell)
    return found


def component_label(category: str, name: str) -> str:
    """Human-readable label for a component in the dashboard."""
    if category == "hook":
        return f"{name} hook"
    if category == "cta":
        return f"{name} CTA"
    if category == "structure":
        return name
    return name  # cover archetype names are already display-ready


__all__ = [
    "CATEGORIES",
    "classify_hook",
    "classify_cta",
    "structure_signature",
    "detect_ai_signals",
    "component_label",
]
