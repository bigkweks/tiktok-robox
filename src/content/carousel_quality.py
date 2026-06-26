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
shareability, follow, readability, saveability, novelty.
Plus a checklist of explicit review questions.

`finalize_carousel` runs up to max_attempts=3 passes, escalating the caption-
replacement threshold and rotating the hook on each retry, driving toward the
top-1% quality bar (`top1pct_passed`).
"""
from __future__ import annotations

import re
from collections import Counter
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
# Each reads like a real creator's first line, not a marketing headline. These are
# the generic fallback bank; edition-specific niche hooks (below) are preferred
# because niche-specific language is the single strongest authenticity signal.
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

# ── Niche-specific cover hooks (keyed by edition label) ────────────────────
# Niche language is what makes a cover read creator-made instead of templated —
# a real horror-niche creator opens with horror words, not a generic line. The
# renderer puts this in the small top slot above the dominant ROBLOX wordmark.
# Kept short (the cover slot is small) and curiosity-first, never clickbait.
EDITION_HOOKS: dict[str, tuple[str, ...]] = {
    "Horror edition": (
        "hidden horror gems",
        "if you've already played doors",
        "horror nobody's found yet",
        "too scary to go viral",
    ),
    "Friends edition": (
        "the group-chat games",
        "send this to your squad",
        "no one's put you onto these",
    ),
    "Hidden Gems": (
        "buried under the algorithm",
        "the ones that should be famous",
        "you've never heard of these",
    ),
    "Solo edition": (
        "for when you're playing alone",
        "no friends required",
        "single-player roblox actually exists",
    ),
    "Anime edition": (
        "anime games that aren't mid",
        "before the algorithm finds them",
        "worth the grind, i checked",
    ),
    "PvP edition": (
        "where the sweats actually hide",
        "pvp that takes real skill",
        "ranked players only know these",
    ),
    "Underrated edition": (
        "criminally underrated",
        "i'm not gatekeeping these",
        "skipped by literally everyone",
    ),
    "Brainrot edition": (
        "peak brainrot, no notes",
        "turn your brain off for these",
        "unserious but undefeated",
    ),
}

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


def score_readability(captions: Sequence[str]) -> float:
    """Slide-by-slide readability: each caption scannable in under 2 seconds.

    Rewards short word-counts (3–8 words) and varied openers so the batch
    doesn't feel copy-pasted. Punishes walls of text (>10 words).
    """
    caps = [c for c in captions if c]
    if not caps:
        return 0.0
    sigs = [signals(c) for c in caps]
    in_range = sum(1 for s in sigs if 3 <= s.words <= 8) / len(sigs)
    overlong = sum(1 for s in sigs if s.words > 10) / len(sigs)
    first_words = []
    for c in caps:
        stripped = c.strip()
        first_words.append(stripped.split()[0].lower() if stripped else "")
    variety = len(set(w for w in first_words if w)) / max(len(first_words), 1)
    return _clamp(0.40 * in_range + 0.30 * (1.0 - overlong) + 0.30 * variety)


def score_saveability(captions: Sequence[str]) -> float:
    """List-reference value: specific enough that a viewer saves it to return.

    A carousel gets saved when it functions as a curated, referenceable list —
    concrete game details (specificity) and varied caption angles (one isn't
    just a rewording of another) are the two strongest signals.
    """
    caps = [c for c in captions if c]
    if not caps:
        return 0.0
    sigs = [signals(c) for c in caps]
    avg_spec = sum(s.specificity for s in sigs) / len(sigs)
    # Varied angles: proxy by distinct 4-char prefixes (different sentence shapes)
    prefixes = {c.strip().lower()[:4] for c in caps if c.strip()}
    angle_variety = len(prefixes) / max(len(caps), 1)
    length_bonus = 0.08 if len(caps) >= 5 else 0.0
    return _clamp(0.50 * min(avg_spec / 2.0, 1.0) + 0.42 * angle_variety + length_bonus)


_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "in", "on", "of",
    "to", "is", "it", "i", "this", "that", "its", "you",
    # Domain words that inherently repeat in a Roblox game-recommendation carousel
    # and don't signal copy-repetition:
    "game", "games", "roblox", "play", "plays", "playing", "played",
    "players", "fun", "good", "great", "like", "get", "has", "for", "with",
})


def score_novelty(captions: Sequence[str], cover_hook: str = "") -> float:
    """Cross-slide freshness: no crutch words overused, no structural monotony.

    Penalises any meaningful word that appears 3+ times across the batch (a
    sign the copy is leaning on a crutch) and structural monotony where more
    than one slide uses the exact same "X in/but roblox" pattern.
    """
    all_text = [c for c in captions if c]
    if cover_hook:
        all_text = [cover_hook] + all_text
    if not all_text:
        return 0.0
    word_counts: Counter = Counter()
    for text in all_text:
        word_counts.update(
            w for w in _WORDS.findall(text.lower())
            if w not in _STOPWORDS and len(w) > 2
        )
    crutch_count = sum(1 for c in word_counts.values() if c >= 3)
    caps_only = [c for c in captions if c]
    roblox_comp = sum(
        1 for c in caps_only if re.search(r"\b(in|but)\s+roblox\b", c.lower())
    )
    mono_penalty = max(0.0, (roblox_comp - 1) / max(len(caps_only), 1))
    return _clamp(1.0 - 0.15 * crutch_count - 0.30 * mono_penalty)


# ── Carousel-level report ─────────────────────────────────────────────────

@dataclass
class QualityReport:
    hook: float
    curiosity: float
    authenticity: float
    specificity: float
    shareability: float
    follow: float
    readability: float = 0.0
    saveability: float = 0.0
    novelty: float = 0.0
    checklist: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def overall(self) -> float:
        # Weighted toward the levers that move carousel performance most.
        return round(
            0.22 * self.hook
            + 0.18 * self.curiosity
            + 0.18 * self.authenticity
            + 0.12 * self.specificity
            + 0.08 * self.shareability
            + 0.08 * self.follow
            + 0.06 * self.readability
            + 0.05 * self.saveability
            + 0.03 * self.novelty,
            3,
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.70 and all(self.checklist.values())

    @property
    def top1pct_passed(self) -> bool:
        """Top-1% Roblox TikTok standard — stricter than the minimum pass bar.

        Requires: overall ≥ 0.80, every checklist item True, hook strong
        enough to stop a scroll (≥ 0.65), and zero AI fingerprints (≥ 0.75
        authenticity). A carousel that clears this would rank alongside the
        best-performing accounts in the niche.
        """
        return (
            self.overall >= 0.80
            and all(self.checklist.values())
            and self.hook >= 0.65
            and self.authenticity >= 0.75
        )

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "hook": round(self.hook, 2),
            "curiosity": round(self.curiosity, 2),
            "authenticity": round(self.authenticity, 2),
            "specificity": round(self.specificity, 2),
            "shareability": round(self.shareability, 2),
            "follow": round(self.follow, 2),
            "readability": round(self.readability, 2),
            "saveability": round(self.saveability, 2),
            "novelty": round(self.novelty, 2),
            "passed": self.passed,
            "top1pct_passed": self.top1pct_passed,
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
    readability = score_readability(caps)
    saveability = score_saveability(caps)
    novelty = score_novelty(caps, cover_hook)

    checklist = {
        "creator_would_post": authenticity >= 0.6 and hook >= 0.55,
        "cover_stops_scroll": hook >= 0.58,
        "reason_to_swipe": curiosity >= 0.55,
        "each_slide_adds": min(cap_scores) >= 0.45,
        "cta_natural": cta_s >= 0.55,
        "no_ai_sentences": ai_hits == 0,
        "no_repeated_wording": unique_ratio == 1.0,
        "specific_enough": specificity >= 0.6,
        "readable_slides": readability >= 0.55,
        "saveworthy": saveability >= 0.50,
        "novel_language": novelty >= 0.60,
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
    if not checklist["readable_slides"]:
        issues.append(f"readability low ({readability:.2f}): captions may be too long or repetitive")
    if not checklist["saveworthy"]:
        issues.append(f"saveability low ({saveability:.2f}): captions lack concrete specificity")
    if not checklist["novel_language"]:
        issues.append(f"novelty low ({novelty:.2f}): crutch words or structural monotony detected")

    return QualityReport(
        hook=hook, curiosity=curiosity, authenticity=authenticity,
        specificity=specificity, shareability=shareability, follow=follow,
        readability=readability, saveability=saveability, novelty=novelty,
        checklist=checklist, issues=issues,
    )


# ── Selection helpers (deterministic but varied) ──────────────────────────

def _rotate(bank: Sequence[str], seed: int) -> list[str]:
    """Bank rotated so consecutive parts don't reuse the same opener."""
    n = len(bank)
    return [bank[(seed + i) % n] for i in range(n)]


def pick_cover_hook(part: int, used: Optional[set[str]] = None,
                    edition: Optional[str] = None) -> str:
    """A strong, non-recently-used cover hook — rotated so the series varies.

    When an `edition` is given we prefer its niche-specific bank: niche language
    ("hidden horror gems") reads far more creator-made than a generic line and
    is the biggest lever on the "does this feel AI?" check. Falls back to the
    generic bank if the edition has no niche hooks or they're all used.
    """
    used = used or set()
    niche = list(EDITION_HOOKS.get(edition or "", ()))
    # Niche hooks first (filtered for AI tells), then the vetted generic bank.
    niche_ok = [h for h in niche
                if not has_ai_tell(h) and normalize_caption(h) not in used]
    if niche_ok:
        return niche_ok[part % len(niche_ok)]
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


# ── Hashtags ───────────────────────────────────────────────────────────────
# A bot reuses the EXACT same hashtag wall on every upload; a real creator's
# tags drift post to post. Identical tag sets are both a template tell to a
# human AND a repetitive-content signal TikTok can suppress. So: pin the proven
# search anchors (they drove 23.9% of the reference post's traffic) on every
# drop, then rotate the rest by part and match the edition's niche — every post
# gets a distinct, on-topic set without losing the SEO that works.

# Always present — the exact search queries the proven post ranked for.
_HASHTAG_ANCHORS: tuple[str, ...] = ("#robloxgames", "#robloxgamestoplywithfriends")

# Rotated tail pool — varied by part so no two consecutive drops match.
_HASHTAG_POOL: tuple[str, ...] = (
    "#roblox", "#robloxfyp", "#robloxgamestoplay", "#robloxhiddengems",
    "#robloxgems", "#robloxtrending", "#robloxtok", "#robloxrecommendations",
    "#fyp", "#gaming",
)

# Edition → niche tag(s), so the set reads on-topic for the drop.
_EDITION_TAGS: dict[str, tuple[str, ...]] = {
    "Horror edition": ("#robloxhorror", "#robloxhorrorgames"),
    "Friends edition": ("#robloxwithfriends",),
    "Hidden Gems": ("#robloxhiddengems",),
    "Solo edition": ("#robloxsolo",),
    "Anime edition": ("#robloxanime",),
    "PvP edition": ("#robloxpvp",),
    "Underrated edition": ("#underratedroblox",),
    "Brainrot edition": ("#robloxbrainrot",),
}


def build_carousel_hashtags(
    part: int,
    edition: str,
    game_names: Optional[Sequence[str]] = None,
    limit: int = 9,
) -> list[str]:
    """A per-post hashtag set that keeps the proven search anchors but rotates
    everything else, so the series never posts the identical wall twice."""
    tags: list[str] = list(_HASHTAG_ANCHORS)
    tags.extend(_EDITION_TAGS.get(edition, ()))

    # A game-specific tag drawn from the lead game — varies naturally per drop
    # and helps people searching that exact game find the post.
    if game_names:
        slug = re.sub(r"[^a-z0-9]", "", (game_names[0] or "").lower())
        if len(slug) > 2:
            tags.append(f"#{slug}")

    # Rotate the tail pool by part so consecutive posts don't repeat.
    rotated = [_HASHTAG_POOL[(part + i) % len(_HASHTAG_POOL)]
               for i in range(len(_HASHTAG_POOL))]
    for t in rotated:
        if len(tags) >= limit:
            break
        if t not in tags:
            tags.append(t)

    # De-dup, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:limit]


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
    max_attempts: int = 3,
    dna=None,
    performance: Optional[dict] = None,
) -> dict:
    """
    The single 'review before presenting' entry point. Returns a vetted cover
    hook, revised per-slide captions, a natural CTA, a de-templated post caption,
    the QualityReport, the slide-purpose plan, and the number of attempts taken.

    Before scoring, the audience for the edition is inferred and every slide is
    assigned an explicit purpose (`plan_carousel`). A slide whose content serves
    no purpose — empty, generic, or AI — is a "dead slide" the loop must fix, not
    ship. Runs up to `max_attempts` passes, escalating the caption-replacement
    threshold (0.55 → 0.60 → 0.65) and rotating to a stronger hook on each retry.
    Targets `top1pct_passed` AND a fully purposeful plan. If that bar can't be
    cleared it accepts anything that passes the minimum quality gate — and always
    returns the best version it built, never an un-revised draft.

    When `dna` (a ContentDNAProfile extracted from proven carousels) is supplied,
    the cover hook is chosen by what those winners actually did, not a generic
    heuristic — generation is driven by the extracted DNA.
    """
    from src.content.caption_utils import _candidates, dedupe_carousel_captions
    from src.content.creator_brief import plan_carousel

    n = len(captions)
    genres_list = list(genres) if genres is not None else [None] * n
    scores_list = list(scores) if scores is not None else [None] * n
    game_names_list = list(game_names) if game_names is not None else []

    # Translate the extracted DNA (if any) into concrete generation directives
    # that steer cover selection toward the proven patterns.
    directives = None
    if dna is not None:
        from src.content.dna_directives import derive_directives
        directives = derive_directives(dna)

    from src.content.cover_generator import select_cover_concept
    _concept = select_cover_concept(
        edition=edition, part=part, used_hooks=used_hooks, dna=directives,
        performance=performance,
    )
    cover_hook = _concept.hook
    cta = pick_cta(part)
    # Working copy; improvements carry forward across attempts.
    current_caps: list[str] = [c or "" for c in captions]
    report: Optional[QualityReport] = None
    plan = None
    attempts_taken = 0

    for attempt in range(max(1, max_attempts)):
        attempts_taken = attempt + 1

        # Pass 1: dedupe + strip AI tells / crutches / generics.
        caps = dedupe_carousel_captions(current_caps, genres=genres_list, scores=scores_list)

        # Pass 2: strengthen captions below the escalating threshold.
        # Each attempt raises the bar so near-miss captions get replaced too.
        replace_threshold = 0.55 + attempt * 0.05   # 0.55 → 0.60 → 0.65
        used = {normalize_caption(c) for c in caps}
        for i, c in enumerate(caps):
            if score_caption(c) >= replace_threshold:
                continue
            gi = genres_list[i] if i < len(genres_list) else None
            si = scores_list[i] if i < len(scores_list) else None
            for cand in _candidates(gi, si):
                nc = normalize_caption(cand)
                if nc in used or has_ai_tell(cand):
                    continue
                if score_caption(cand) > score_caption(c):
                    used.discard(normalize_caption(c))
                    used.add(nc)
                    caps[i] = cand
                    break

        # On retry attempts, swap to a stronger hook when the current one is soft.
        if attempt > 0 and score_hook(cover_hook) < 0.65:
            alt = pick_cover_hook(part + attempt, used_hooks, edition=edition)
            if score_hook(alt) > score_hook(cover_hook):
                cover_hook = alt

        report = review_carousel(cover_hook, caps, list(blurbs), cta)
        plan = plan_carousel(edition, cover_hook, caps, list(blurbs), cta)
        # A slide that serves no purpose is a generation failure, not a soft
        # score — surface it so the post is never shipped with dead weight.
        for idx in plan.dead_slides:
            slide = plan.slides[idx] if idx < len(plan.slides) else None
            if slide and slide.note:
                report.issues.append(f"slide {idx} serves no purpose: {slide.note}")
        current_caps = caps   # carry improvements to the next attempt

        # Stop early once we've hit the top-1% bar AND every slide has a job;
        # always stop on the last attempt.
        if (report.top1pct_passed and plan.purposeful) or attempt == max_attempts - 1:
            break

    post_caption = build_post_caption(edition, part, game_names_list)

    return {
        "cover_hook": cover_hook,
        "captions": current_caps,
        "cta": cta,
        "post_caption": post_caption,
        "report": report,
        "plan": plan,
        "attempts": attempts_taken,
        "dna_directives": directives.as_dict() if directives is not None else None,
        "cover_concept": _concept.name,
    }


__all__ = [
    "QualityReport", "review_carousel", "finalize_carousel",
    "score_hook", "score_caption", "score_cta",
    "score_readability", "score_saveability", "score_novelty",
    "pick_cover_hook", "pick_cta", "pick_footer_cta",
    "build_post_caption", "build_carousel_hashtags",
    "COVER_HOOKS", "CTA_LINES", "EDITION_HOOKS",
]
