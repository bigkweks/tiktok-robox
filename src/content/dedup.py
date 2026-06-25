"""
Cross-post duplicate & near-duplicate detection.

The whole growth strategy is "Part N forces follows", which means the SAME
followers see consecutive drops. So repetition is the single most damaging
"this is a bot" tell — and the old pipeline only de-duplicated WITHIN one
carousel, never against what already shipped.

This module provides text normalization + a similarity score and a single
``is_near_duplicate`` gate, used to reject a cover hook / caption / CTA that is
too close to anything in recent history (or to another line in the same batch).

Similarity blends two cheap, complementary signals:
  - token Jaccard      — catches reworded-but-same-words lines
  - difflib ratio      — catches char-level near-misses (typo/apostrophe variants)
The max of the two is used, so EITHER kind of closeness trips the gate.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

# Default: 0.82 flags clear near-duplicates while leaving genuinely distinct
# lines alone. Exposed so callers can tune per surface (hooks vs captions).
DEFAULT_THRESHOLD = 0.82

_WORD = re.compile(r"[a-z0-9]+")
# Filler words that shouldn't make two lines look "different" or "same".
_STOP = frozenset({"the", "a", "an", "to", "of", "and", "for", "in", "on", "is",
                   "this", "that", "these", "those", "you", "your", "i", "it"})


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/apostrophes, collapse whitespace."""
    return " ".join(_WORD.findall((text or "").lower()))


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def token_jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def similarity(a: str, b: str) -> float:
    """0.0 (unrelated) → 1.0 (identical). Max of token-Jaccard and char-ratio."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return max(token_jaccard(a, b), SequenceMatcher(None, na, nb).ratio())


def is_near_duplicate(
    candidate: str,
    history: Iterable[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    """True if ``candidate`` is at/above ``threshold`` similarity to any item in
    ``history`` (exact or near). Empty candidates never count as duplicates."""
    if not (candidate or "").strip():
        return False
    return any(similarity(candidate, h) >= threshold for h in history if h)


def most_similar(candidate: str, history: Iterable[str]) -> tuple[str, float]:
    """Return the (history_item, score) most similar to candidate (or ('',0))."""
    best, best_s = "", 0.0
    for h in history:
        if not h:
            continue
        s = similarity(candidate, h)
        if s > best_s:
            best, best_s = h, s
    return best, best_s


def dedupe_batch(lines: list[str], threshold: float = DEFAULT_THRESHOLD) -> list[int]:
    """Return the indices of lines that are near-duplicates of an EARLIER line in
    the same batch (so a caller can flag/replace them). The first occurrence is
    always kept."""
    dupes: list[int] = []
    for i, line in enumerate(lines):
        if is_near_duplicate(line, lines[:i], threshold):
            dupes.append(i)
    return dupes


__all__ = [
    "DEFAULT_THRESHOLD", "normalize", "token_jaccard", "similarity",
    "is_near_duplicate", "most_similar", "dedupe_batch",
]
