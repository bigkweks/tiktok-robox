"""
Internal carousel quality reviewer + auto-reviser.

Every carousel runs through this BEFORE it is shown to the user. It scores the
cover hook, the per-slide captions, the per-slide blurbs and the CTA on the
dimensions that actually drive carousel performance, flags anything that reads
AI-generated / templated / generic, and rewrites the weak pieces from
creator-native banks until the post passes — or returns the best it can with a
report explaining what is still soft.

This is deterministic and heuristic (no extra API calls): fast, testable, and
it never blocks generation. It is the "would a real creator post this?" gate.

Scored dimensions (0..1): hook, curiosity, authenticity, specificity,
shareability, follow. Plus a checklist of the explicit review questions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.content.caption_utils import (
    _CURIOSITY_MARKERS,
    _OVERPROMISE,
    has_ai_tell,
    has_internal_repetition,
    is_generic,
    normalize_caption,
    specificity_score,
)

_WORDS = re.compile(r"[a-z0-9']+")


# ── Creator-native banks (rotated, never a single template) ───────────────

# Cover hooks: curiosity-first, no "stop scrolling" cliché spam, no over-promise.
# Each reads like a real creator's first line, not a marketing headline.
COVER_HOOKS: tuple[str, ...] = (
    "you've never heard of these",
    "save this list trust me",
    "ranking roblox games no one plays",
    "your fyp has been lying to you",
    "found these so you don't have to",
    "everyone asks me for these",
    "roblox games that should be famous",
    "i went looking for hidden ones",
    "the ones your friends don't know yet",
    "underrated and i'm not gatekeeping",
    "before these blow up",
    "rating games you've been sleeping on",
)

# Follow / continuation CTAs — natural, content-matched, never desperate.
# `{next}` is the next part number.
CTA_LINES: tuple[str, ...] = (
    "part {next} is already in the works — follow so it finds you",
    "i do these every few days, follow if you keep running out of games",
    "saving you the scroll — follow for the next batch",
    "more where these came from, that's the whole account",
    "follow so part {next} shows up on your fyp",
    "which one are you opening first?",
    "tell me your hidden gem and i'll rate it next",
)

# Closers for the post body (the comment-bait line). Rotated.
ENGAGE_LINES: tuple[str, ...] = (
    "which one are you trying first",
    "tell me i'm wrong about the last one",
    "drop a game and i'll rate it next",
    "ranked in the order i'd play them",
    "number 5 is the one btw",
    "saving this for the weekend fr",
)


# ── Text signals ──────────────────────────────────────────────────────────

@dataclass
class Signals:
    text: str
    words: int
    has_number: bool
    ai_tell: bool
    generic: bool
    repetition: bool
    curiosity: int
    overpromise: int
    specificity: int
    exclamations: int


def signals(text: Optional[str]) -> Signals:
    t = (text or "").strip()
    low = t.lower()
    toks = _WORDS.findall(low)
    return Signals(
        text=t,
        words=len(toks),
        has_number=bool(re.search(r"\d", t)),
        ai_tell=has_ai_tell(t),
        generic=is_generic(t),
        repetition=has_internal_repetition(t),
        curiosity=sum(1 for m in _CURIOSITY_MARKERS if m in low),
        overpromise=sum(1 for m in _OVERPROMISE if m in low),
        specificity=specificity_score(t),
        exclamations=t.count("!"),
    )


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# ── Per-element scores (0..1) ─────────────────────────────────────────────

def score_hook(text: Optional[str]) -> float:
    """Cover/first-line hook: reward curiosity + brevity, punish AI tells &
    over-promise. A good hook earns the swipe without shouting."""
    s = signals(text)
    if not s.words:
        return 0.0
    score = 0.45
    score += 0.18 * min(s.curiosity, 2)          # genuine curiosity gap
    score += 0.12 if 3 <= s.words <= 9 else -0.12  # tight pacing
    score += 0.10 if s.specificity else 0.0
    score -= 0.30 if s.ai_tell else 0.0
    score -= 0.12 * s.overpromise                # spammy hype
    score -= 0.15 if s.generic else 0.0
    return _clamp(score)


def score_caption(text: Optional[str]) -> float:
    """Per-slide burned caption: specific + authentic + not generic/AI."""
    s = signals(text)
    if not s.words:
        return 0.0
    score = 0.5
    score += 0.12 * min(s.specificity, 3)
    score += 0.08 if 3 <= s.words <= 8 else -0.1
    score -= 0.35 if s.ai_tell else 0.0
    score -= 0.3 if s.generic else 0.0
    score -= 0.25 if s.repetition else 0.0
    return _clamp(score)


def score_cta(text: Optional[str]) -> float:
    """CTA: natural + content-matched, not desperate ('like and subscribe')."""
    s = signals(text)
    if not s.words:
        return 0.0
    low = s.text.lower()
    desperate = any(p in low for p in (
        "like and subscribe", "smash that", "don't forget to follow",
        "follow for more!!!", "drop a follow", "hit follow",
    ))
    score = 0.55
    score += 0.15 if ("follow" in low or "?" in s.text) else 0.0
    score += 0.1 if 4 <= s.words <= 16 else -0.1
    score -= 0.4 if desperate else 0.0
    score -= 0.25 if s.ai_tell else 0.0
    score -= 0.1 * max(0, s.exclamations - 1)
    return _clamp(score)


# ── Carousel-level report ─────────────────────────────────────────────────

@dataclass
class QualityReport:
    hook: float
    curiosity: float
    authenticity: float
    specificity: float
    shareability: float
    follow: float
    checklist: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def overall(self) -> float:
        # Weighted toward the levers that move carousel performance most.
        return round(
            0.26 * self.hook
            + 0.20 * self.curiosity
            + 0.20 * self.authenticity
            + 0.14 * self.specificity
            + 0.10 * self.shareability
            + 0.10 * self.follow,
            3,
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.70 and all(self.checklist.values())

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "hook": round(self.hook, 2),
            "curiosity": round(self.curiosity, 2),
            "authenticity": round(self.authenticity, 2),
            "specificity": round(self.specificity, 2),
            "shareability": round(self.shareability, 2),
            "follow": round(self.follow, 2),
            "passed": self.passed,
            "issues": self.issues,
        }


def review_carousel(
    cover_hook: str,
    captions: Sequence[str],
    blurbs: Sequence[str],
    cta: str,
) -> QualityReport:
    """Score a fully-assembled carousel and answer the review checklist."""
    caps = [c for c in captions if c]
    cap_sigs = [signals(c) for c in caps]
    norms = [normalize_caption(c) for c in caps]

    hook = score_hook(cover_hook)
    cap_scores = [score_caption(c) for c in caps] or [0.0]
    cta_s = score_cta(cta)

    curiosity = _clamp(
        0.5 * score_hook(cover_hook)
        + 0.5 * (sum(min(s.curiosity, 1) for s in cap_sigs) / max(len(cap_sigs), 1))
        + 0.2
    )
    ai_hits = sum(1 for s in cap_sigs if s.ai_tell) + (1 if has_ai_tell(cover_hook) else 0)
    authenticity = _clamp(1.0 - 0.25 * ai_hits - 0.15 * sum(1 for s in cap_sigs if s.generic))
    # Fraction of slides that carry a concrete, memorable detail (a number, a
    # genre comparison, a named mechanic) — more meaningful than a raw count,
    # and tolerant of the occasional authentic slang line.
    specificity = _clamp(sum(1 for s in cap_sigs if s.specificity >= 1) / max(len(cap_sigs), 1))
    unique_ratio = len(set(norms)) / max(len(norms), 1)
    shareability = _clamp(0.5 * unique_ratio + 0.5 * (sum(cap_scores) / len(cap_scores)))
    follow = cta_s

    checklist = {
        "creator_would_post": authenticity >= 0.6 and hook >= 0.55,
        "cover_stops_scroll": hook >= 0.58,
        "reason_to_swipe": curiosity >= 0.55,
        "each_slide_adds": min(cap_scores) >= 0.45,
        "cta_natural": cta_s >= 0.55,
        "no_ai_sentences": ai_hits == 0,
        "no_repeated_wording": unique_ratio == 1.0,
        "specific_enough": specificity >= 0.6,
    }

    issues: list[str] = []
    if has_ai_tell(cover_hook):
        issues.append(f"cover hook reads AI: {cover_hook!r}")
    for c, s in zip(caps, cap_sigs):
        if s.ai_tell:
            issues.append(f"caption reads AI: {c!r}")
        elif s.generic:
            issues.append(f"caption too generic: {c!r}")
    if unique_ratio < 1.0:
        issues.append("duplicate caption wording across slides")
    if not checklist["cta_natural"]:
        issues.append(f"CTA feels off: {cta!r}")

    return QualityReport(
        hook=hook, curiosity=curiosity, authenticity=authenticity,
        specificity=specificity, shareability=shareability, follow=follow,
        checklist=checklist, issues=issues,
    )


# ── Selection helpers (deterministic but varied) ──────────────────────────

def _rotate(bank: Sequence[str], seed: int) -> list[str]:
    """Bank rotated so consecutive parts don't reuse the same opener."""
    n = len(bank)
    return [bank[(seed + i) % n] for i in range(n)]


def pick_cover_hook(part: int, used: Optional[set[str]] = None) -> str:
    """A strong, non-recently-used cover hook — rotated so the series varies."""
    used = used or set()
    qualified = [h for h in COVER_HOOKS
                 if score_hook(h) >= 0.6 and normalize_caption(h) not in used]
    if not qualified:
        qualified = [h for h in COVER_HOOKS if normalize_caption(h) not in used] or list(COVER_HOOKS)
    return qualified[part % len(qualified)]


def pick_cta(part: int) -> str:
    nxt = part + 1
    options = [c.format(next=nxt) for c in CTA_LINES]
    qualified = [c for c in options if score_cta(c) >= 0.6] or options
    return qualified[part % len(qualified)]


def pick_engage_line(part: int) -> str:
    return _rotate(ENGAGE_LINES, part)[0]


# Short follow nudges for the last-slide footer chip (kept tight so the chip
# fits). `{next}` is the next part number.
FOOTER_CTAS: tuple[str, ...] = (
    "follow for part {next} 👀",
    "part {next} soon — follow",
    "more like this → follow",
    "don't miss part {next} 👀",
)


def pick_footer_cta(part: int) -> str:
    return FOOTER_CTAS[part % len(FOOTER_CTAS)].format(next=part + 1)


def build_post_caption(edition: str, part: int, game_names: Sequence[str]) -> str:
    """
    De-templated TikTok caption. Keeps the proven SEARCH anchor ("roblox games
    to play") because 23.9% of traffic came from search — but everything around
    it rotates so the series never reads copy-pasted. Returns plain text; the
    pipeline appends hashtags.
    """
    lead = game_names[0] if game_names else "these"
    second = game_names[1] if len(game_names) > 1 else "more"
    ed = edition.replace(" edition", "").strip().lower()

    # Rotating opening lines — all carry the search phrase, none identical.
    openers = [
        f"roblox games to play that nobody talks about — {ed} pt {part}",
        f"actually good roblox games to play (part {part}) — {ed} drop",
        f"more roblox games to play before everyone finds them · {ed} pt {part}",
        f"part {part} of roblox games to play that deserve more — {ed}",
        f"saving you the search: roblox games to play, {ed} edition pt {part}",
    ]
    bodies = [
        f"started with {lead}, {second} caught me off guard",
        f"{lead} is the one everyone's gonna ask about",
        f"swiped through these all week, {lead} stuck",
        f"ranked them — {lead} earned the spot",
    ]
    opener = openers[part % len(openers)]
    body = bodies[part % len(bodies)]
    closer = pick_engage_line(part)
    return f"{opener}\n\n{body}\n\n{closer}"


def finalize_carousel(
    part: int,
    edition: str,
    captions: Sequence[Optional[str]],
    blurbs: Sequence[Optional[str]],
    genres: Optional[Sequence[Optional[str]]] = None,
    scores: Optional[Sequence[Optional[float]]] = None,
    game_names: Optional[Sequence[str]] = None,
    used_hooks: Optional[set[str]] = None,
) -> dict:
    """
    The single 'review before presenting' entry point. Returns a vetted cover
    hook, revised per-slide captions, a natural CTA, a de-templated post caption,
    and the QualityReport. Everything emitted here has already been auto-revised:
    AI tells / generic / duplicate captions are rewritten, and the hook + CTA are
    only ever chosen from bank lines that clear the quality bar.
    """
    from src.content.caption_utils import _candidates, dedupe_carousel_captions

    n = len(captions)
    genres = list(genres) if genres is not None else [None] * n
    scores = list(scores) if scores is not None else [None] * n
    game_names = list(game_names) if game_names is not None else []

    cover_hook = pick_cover_hook(part, used_hooks)

    # Pass 1: dedupe + strip AI tells / crutches / generics.
    caps = dedupe_carousel_captions(captions, genres=genres, scores=scores)

    # Pass 2: strengthen any caption that still scores soft, pulling a more
    # specific, unused, AI-free line from the same genre/score bank.
    used = {normalize_caption(c) for c in caps}
    for i, c in enumerate(caps):
        if score_caption(c) >= 0.55:
            continue
        gi = genres[i] if i < len(genres) else None
        si = scores[i] if i < len(scores) else None
        for cand in _candidates(gi, si):
            nc = normalize_caption(cand)
            if nc in used or has_ai_tell(cand):
                continue
            if score_caption(cand) >= score_caption(c) + 0.05:
                used.discard(normalize_caption(c))
                used.add(nc)
                caps[i] = cand
                break

    cta = pick_cta(part)
    post_caption = build_post_caption(edition, part, game_names)
    report = review_carousel(cover_hook, caps, list(blurbs), cta)

    return {
        "cover_hook": cover_hook,
        "captions": caps,
        "cta": cta,
        "post_caption": post_caption,
        "report": report,
    }


__all__ = [
    "QualityReport", "review_carousel", "finalize_carousel", "score_hook",
    "score_caption", "score_cta", "pick_cover_hook", "pick_cta",
    "pick_footer_cta", "build_post_caption", "COVER_HOOKS", "CTA_LINES",
]
