"""
Dedicated cover-generation system.

The cover is the most performance-critical slide in the carousel — it
controls stop-scroll rate, initial curiosity, and swipe initiation.
A weak cover kills the carousel before a single game slide is seen.

This module treats cover selection as a scored competition: 10 candidate
concepts are generated for each drop, each scored on the six dimensions
that drive cover performance, weak candidates are eliminated, and the
winner is returned to the renderer.

Scoring dimensions (0.0–1.0):
  curiosity       Information gap — does the viewer NEED to see what's inside?
  clarity         Value obvious in <1 second — no guessing what this is about
  readability     Short and scannable — absorbed without effort
  specificity     Native to Roblox culture / the edition — not genre-generic
  novelty         Avoids overworked patterns and clichés
  authenticity    Sounds like a real Roblox creator, not a brand

Rejection rule: any dimension below REJECT_FLOOR (0.40) eliminates the
concept regardless of its composite. Prevents a one-dimension-strong entry
winning with a fatal weakness in another.

Selection: highest weighted composite among passing candidates wins.
Tie-breaking: edition-specific hook beats base hook.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.content.caption_utils import has_ai_tell, normalize_caption


# Any single dimension below this eliminates the concept.
REJECT_FLOOR: float = 0.40

# Weights for the composite score. Curiosity, Clarity, and Specificity
# dominate — these are the three levers that determine whether a viewer
# stops, understands, and swipes. Authenticity matters for trust;
# Novelty for standing out; Readability for speed-of-absorption.
_WEIGHTS: dict[str, float] = {
    "curiosity": 0.25,
    "clarity": 0.20,
    "specificity": 0.20,
    "authenticity": 0.15,
    "novelty": 0.12,
    "readability": 0.08,
}

# ── Roblox cultural vocabulary (fuels specificity scoring) ────────────────

# Named games the average Roblox player knows — presence in a hook signals
# the creator has genuinely played the platform and knows its culture.
_ROBLOX_GAMES: frozenset[str] = frozenset({
    "doors", "bloxburg", "brookhaven", "adopt me", "blox fruits",
    "pet simulator", "murder mystery", "arsenal", "breaking point",
    "piggy", "tower of hell", "funky friday", "da hood", "bedwars",
    "royale high", "jailbreak", "natural disaster", "flood escape",
    "prison life", "phantom forces",
})

# Roblox-native metric/UI vocabulary — the specific terms players use that
# no outsider (or generic AI) would naturally reach for.
_ROBLOX_METRICS: frozenset[str] = frozenset({
    "visits", "active", "lobby", "lobbies", "gamepass", "robux",
    "front page", "explore page", "search", "obby",
})

# Subculture vocabulary that signals insider membership.
# Short tokens (≤3 chars) use whole-word matching in _score_specificity to
# avoid false substring matches ("op" inside "people", etc.).
_NICHE_VOCAB: frozenset[str] = frozenset({
    "grind", "tryhard", "ranked", "bot lobby", "bot lobbies", "carry", "sweats",
    "fyp", "algorithm", "pvp", "limited", "noob",
})

# ── Curiosity scoring signals ──────────────────────────────────────────────

_INFO_GAP: tuple[str, ...] = (
    "if you've", "only if", "only the", "before they", "before everyone",
    "hiding", "nobody", "no one", "won't show", "been lying",
    "been hiding", "buried", "won't find", "hidden", "secret",
)

_FOMO: tuple[str, ...] = (
    "before they blow", "before everyone", "won't stay hidden",
    "still hidden", "already found", "early",
)

# ── Novelty killers ────────────────────────────────────────────────────────

_OVERUSED: tuple[str, ...] = (
    "stop scrolling", "you won't believe", "you need to see",
    "must play", "must try", "top 5", "best roblox games",
    "hidden gems list", "game changing", "mind blowing",
    "games you need", "underrated games you",
)

# ── Authenticity signals ───────────────────────────────────────────────────

_CREATOR_VOICE: tuple[str, ...] = (
    "i spent", "i found", "i actually", "i've been", "i tested",
    "i played", "i solo", "trust me", "ngl", "fr", "my ",
)

_CORPORATE: tuple[str, ...] = (
    "discover", "explore the", "unlock the", "unleash",
    "experience the", "curated for you",
)


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class CoverScore:
    curiosity: float
    clarity: float
    readability: float
    specificity: float
    novelty: float
    authenticity: float

    @property
    def composite(self) -> float:
        return round(
            _WEIGHTS["curiosity"] * self.curiosity
            + _WEIGHTS["clarity"] * self.clarity
            + _WEIGHTS["readability"] * self.readability
            + _WEIGHTS["specificity"] * self.specificity
            + _WEIGHTS["novelty"] * self.novelty
            + _WEIGHTS["authenticity"] * self.authenticity,
            3,
        )

    @property
    def passes(self) -> bool:
        return all(
            v >= REJECT_FLOOR
            for v in (
                self.curiosity, self.clarity, self.readability,
                self.specificity, self.novelty, self.authenticity,
            )
        )

    def as_dict(self) -> dict:
        return {
            "curiosity": round(self.curiosity, 3),
            "clarity": round(self.clarity, 3),
            "readability": round(self.readability, 3),
            "specificity": round(self.specificity, 3),
            "novelty": round(self.novelty, 3),
            "authenticity": round(self.authenticity, 3),
            "composite": self.composite,
            "passes": self.passes,
        }


@dataclass
class CoverConcept:
    name: str             # archetype label, e.g. "The Qualifier"
    hook: str             # the actual text that goes in the hook slot
    edition: str          # edition this was generated for
    is_edition_specific: bool = False   # True when an edition override was used
    score: Optional[CoverScore] = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "hook": self.hook,
            "edition": self.edition,
            "is_edition_specific": self.is_edition_specific,
            "score": self.score.as_dict() if self.score else None,
        }


# ── The 10 archetype concepts ─────────────────────────────────────────────
#
# Each archetype is a named strategy. The `edition_hooks` override the base
# hook when an edition-specific line is available — these always score higher
# on Specificity because they name a real Roblox cultural reference (a game,
# a mechanic, a community problem) that immediately signals insider knowledge.
#
# Preferred characteristics wired into the archetype set:
#   - Specific: names actual Roblox games or Roblox-native metrics
#   - Native to Roblox culture: uses vocabulary players use, not outsiders
#   - Immediately understandable: no setup or explanation needed
#   - Slightly surprising: subverts expectation or challenges a belief
#   - Visually simple: short enough to render in 1-2 lines at large type
#
# Explicitly avoided:
#   - Generic curiosity ("you won't believe...", "stop scrolling")
#   - Vague claims ("amazing games", "hidden gems you need to play")
#   - Generic listicle titles ("top 5 underrated roblox games")
#   - AI hooks (any phrase from _AI_TELLS in caption_utils.py)

_ARCHETYPES: list[dict] = [
    # 1 ── The Qualifier
    # Gates the audience with a specific cultural reference the target viewer
    # recognises. "If you've already beaten Doors" immediately identifies the
    # viewer (horror-niche Roblox player) and creates tension: what comes next?
    {
        "name": "The Qualifier",
        "base_hook": "for the ones who've already seen the popular list",
        "edition_hooks": {
            "Horror edition": "if you've already beaten doors",
            "Friends edition": "if brookhaven is getting boring",
            "PvP edition": "if you're past the beginner pvp games",
            "Anime edition": "if blox fruits is starting to feel slow",
            "Solo edition": "for when tower of hell gets repetitive",
            "Brainrot edition": "if pet simulator isn't rotting your brain enough",
            "Underrated edition": "if you've played everything on the front page",
            "Hidden Gems": "if you've run out of good games to play",
        },
    },
    # 2 ── The Pattern Break
    # Names a specific Roblox mechanism (search, explore page) and accuses it
    # of hiding something. Creates a clear villain + an information gap.
    {
        "name": "The Pattern Break",
        "base_hook": "roblox search won't show you these",
        "edition_hooks": {
            "Horror edition": "roblox search buried the scary ones",
            "Hidden Gems": "buried under the roblox algorithm",
            "Underrated edition": "the explore page has been lying to you",
            "Friends edition": "roblox keeps serving you the same group games",
        },
    },
    # 3 ── The Niche Gate
    # Opens with a specific community pain point that the target viewer feels
    # every session. Immediately signals the creator understands the niche.
    {
        "name": "The Niche Gate",
        "base_hook": "games that know what they are",
        "edition_hooks": {
            "Horror edition": "horror games that aren't just doors",
            "Friends edition": "group games that aren't brookhaven",
            "PvP edition": "pvp for people who hate bot lobbies",
            "Anime edition": "anime games that aren't blox fruits clones",
            "Solo edition": "solo games with actual content",
            "Brainrot edition": "peak brainrot, curated",
            "Underrated edition": "skipped by the algorithm, found by me",
            "Hidden Gems": "under 1m visits and worth every second",
        },
    },
    # 4 ── The Visit Count
    # Uses Roblox's native metric (visits) to make the underrated argument
    # with specificity. A number is the strongest specificity signal.
    {
        "name": "The Visit Count",
        "base_hook": "50k visits. deserve 50 million.",
        "edition_hooks": {
            "Horror edition": "scarier than doors. 40k visits.",
            "Hidden Gems": "found with under 100k visits each",
            "Underrated edition": "combined visits: less than one viral video",
            "PvP edition": "100k visits. 94% like ratio.",
        },
    },
    # 5 ── The Insider
    # Frames the knowledge as exclusive to a specific subgroup the viewer
    # either belongs to or aspires to be part of.
    {
        "name": "The Insider",
        "base_hook": "only the serious players know these",
        "edition_hooks": {
            "PvP edition": "only the sweats know these exist",
            "Horror edition": "the horror accounts that got it right know these",
            "Anime edition": "the anime grinders found these first",
            "Underrated edition": "the ones the veteran players are playing",
        },
    },
    # 6 ── The Algorithm Accuser
    # Blames a specific platform mechanism, creates a shared adversary, and
    # positions the creator as the workaround.
    {
        "name": "The Algorithm Accuser",
        "base_hook": "your fyp has been hiding these",
        "edition_hooks": {
            "Horror edition": "the horror algorithm only shows you doors",
            "Friends edition": "roblox keeps showing the same five group games",
            "Anime edition": "the anime tab misses the actual good ones",
        },
    },
    # 7 ── The Confession
    # First-person investment signals effort and authenticity. A specific time
    # investment ("3 days") implies the payoff was worth it.
    {
        "name": "The Confession",
        "base_hook": "i spent 3 days finding these",
        "edition_hooks": {
            "Horror edition": "i tested every horror game so you don't have to",
            "Friends edition": "played these with my group before posting",
            "Solo edition": "solo'd all of these to verify they slap",
            "PvP edition": "grinded ranked in all of these first",
        },
    },
    # 8 ── The Anti-Viral
    # Subverts the normal frame (virality = quality). Creates genuine
    # curiosity: what is so good it actively avoided going viral?
    {
        "name": "The Anti-Viral",
        "base_hook": "too good to go viral",
        "edition_hooks": {
            "Horror edition": "too scary for the mainstream algorithm",
            "Hidden Gems": "genuinely good and never trended",
            "Underrated edition": "quality that the algorithm skipped",
        },
    },
    # 9 ── The Hidden Stat
    # Leads with a specific Roblox-native metric to create a concrete
    # underrated claim that's impossible to dismiss as vague.
    {
        "name": "The Hidden Stat",
        "base_hook": "better stats than the front page games",
        "edition_hooks": {
            "Hidden Gems": "buried on page 6 of roblox search",
            "Underrated edition": "100k visits. 95% like ratio. never trended.",
            "PvP edition": "higher skill ceiling than the popular ones",
            "Horror edition": "scarier rating than doors. buried anyway.",
        },
    },
    # 10 ── The Scout Report
    # Stakes the creator's personal credibility — "i actually play these"
    # implies that competitors don't, without saying it explicitly.
    {
        "name": "The Scout Report",
        "base_hook": "i actually play these ones",
        "edition_hooks": {
            "Horror edition": "finished all of these, here's the ranking",
            "Friends edition": "group tested, all approved",
            "PvP edition": "played ranked in all of these first",
            "Anime edition": "grinded all of them before this post",
        },
    },
]


# ── Per-dimension scorers ─────────────────────────────────────────────────

def _score_curiosity(hook: str) -> float:
    low = hook.lower()
    s = 0.45
    # Information gap — the core curiosity mechanism
    gaps = sum(1 for m in _INFO_GAP if m in low)
    s += min(gaps * 0.15, 0.30)
    # FOMO signal
    s += min(sum(1 for m in _FOMO if m in low) * 0.10, 0.15)
    # Conditional framing ("if you've...") creates identity tension
    if low.startswith("if ") or "if you" in low:
        s += 0.10
    # Subversive framing (paradox, accusation) creates curiosity without hype
    subversive = ("too good", "too scary", "been lying", "won't show", "buried")
    if any(sv in low for sv in subversive):
        s += 0.12
    # Penalise generic hooks and AI tells
    s -= sum(1 for p in _OVERUSED if p in low) * 0.20
    if has_ai_tell(hook):
        s -= 0.30
    return max(0.0, min(1.0, s))


def _score_clarity(hook: str) -> float:
    words = hook.split()
    wc = len(words)
    s = 0.50
    # Short = immediately parsed
    if wc <= 5:
        s += 0.20
    elif wc <= 8:
        s += 0.10
    elif wc > 12:
        s -= 0.25
    # Roblox-legible nouns in the hook anchor the value proposition
    anchors = ("games", "roblox", "horror", "pvp", "anime", "friends",
               "visits", "search", "lobby", "obby", "grind")
    if any(a in hook.lower() for a in anchors):
        s += 0.08
    # Long words increase cognitive load
    long_words = sum(1 for w in re.sub(r"[^a-z ]", "", hook.lower()).split() if len(w) > 9)
    s -= long_words * 0.08
    return max(0.0, min(1.0, s))


def _score_readability(hook: str) -> float:
    words = hook.split()
    wc = len(words)
    s = 0.40
    # 3-7 words is the golden zone for a quick-read cover hook
    if 3 <= wc <= 7:
        s += 0.40
    elif wc <= 10:
        s += 0.20
    elif wc > 12:
        s -= 0.20
    # Long words slow scanning
    long_words = sum(1 for w in re.sub(r"[^a-z ]", "", hook.lower()).split() if len(w) > 8)
    s -= long_words * 0.08
    return max(0.0, min(1.0, s))


def _word_match(term: str, text: str) -> bool:
    """Whole-word match for short tokens, substring match for longer ones.
    Prevents short terms like 'pvp' matching as part of 'pvp...' is fine but
    avoids accidental substring hits inside unrelated words."""
    if len(term) <= 3:
        return bool(re.search(r"\b" + re.escape(term) + r"\b", text))
    return term in text


def _score_specificity(hook: str, edition: str = "") -> float:
    low = hook.lower()
    s = 0.30
    # Named Roblox game is the single strongest specificity signal —
    # it proves the creator actually plays the platform
    if any(g in low for g in _ROBLOX_GAMES):
        s += 0.40
    # Roblox-native metrics and vocabulary
    metric_hits = sum(1 for m in _ROBLOX_METRICS if _word_match(m, low))
    s += min(metric_hits * 0.15, 0.30)
    niche_hits = sum(1 for v in _NICHE_VOCAB if _word_match(v, low))
    s += min(niche_hits * 0.10, 0.20)
    # Numbers = concrete claim, not vague assertion
    if re.search(r"\d", hook):
        s += 0.15
    # Hooks with NO specificity markers get a small penalty
    if (not any(g in low for g in _ROBLOX_GAMES)
            and not metric_hits and not niche_hits
            and not re.search(r"\d", hook)):
        s -= 0.08
    return max(0.0, min(1.0, s))


def _score_novelty(hook: str) -> float:
    low = hook.lower()
    s = 0.60
    # Overworked patterns tank novelty
    s -= sum(1 for p in _OVERUSED if p in low) * 0.25
    if has_ai_tell(hook):
        s -= 0.40
    # Subversive / paradoxical framing is structurally novel
    subversions = ("too good", "too scary", "not just", "aren't just",
                   "never trended", "buried", "been lying", "won't show")
    if any(sv in low for sv in subversions):
        s += 0.20
    # Unusual format: Roblox stat + fragment ("50k visits. deserve 50M.")
    if re.search(r"\d+[km]?\s*visits", low):
        s += 0.15
    return max(0.0, min(1.0, s))


def _score_authenticity(hook: str) -> float:
    low = hook.lower()
    s = 0.55
    # First-person voice = real creator, not a marketing team
    creator_hits = sum(1 for m in _CREATOR_VOICE if m in low)
    s += min(creator_hits * 0.12, 0.24)
    # Lowercase / casual grammar signals creator voice
    if hook and hook[0].islower():
        s += 0.06
    # AI-generated language is an immediate disqualifier
    if has_ai_tell(hook):
        s -= 0.45
    # Corporate language kills the creator-made feel
    if any(c in low for c in _CORPORATE):
        s -= 0.25
    # Specific knowledge markers (non-obvious claims about games/platform)
    knowledge = ("actually", "trust me", "i played", "been playing",
                 "beaten", "grinded", "tested", "verified")
    if any(k in low for k in knowledge):
        s += 0.10
    return max(0.0, min(1.0, s))


# ── Scoring entry point ───────────────────────────────────────────────────

def score_concept(hook: str, edition: str = "") -> CoverScore:
    """Score a single hook text on all six cover-performance dimensions."""
    return CoverScore(
        curiosity=_score_curiosity(hook),
        clarity=_score_clarity(hook),
        readability=_score_readability(hook),
        specificity=_score_specificity(hook, edition),
        novelty=_score_novelty(hook),
        authenticity=_score_authenticity(hook),
    )


# ── Concept generation ────────────────────────────────────────────────────

def generate_cover_concepts(edition: str = "", part: int = 1) -> list[CoverConcept]:
    """
    Generate exactly 10 cover concepts — one per archetype — and score each.

    Edition-specific hooks are preferred over the base hook when available:
    they score higher on Specificity by design (naming an actual Roblox game
    or community pain-point is the biggest single lever on creator authenticity).
    `part` is accepted for API compatibility but concepts are scored on content,
    not rotation.
    """
    concepts: list[CoverConcept] = []
    for arch in _ARCHETYPES:
        edition_hook = arch["edition_hooks"].get(edition)
        hook = edition_hook or arch["base_hook"]
        sc = score_concept(hook, edition)
        concepts.append(CoverConcept(
            name=arch["name"],
            hook=hook,
            edition=edition,
            is_edition_specific=bool(edition_hook),
            score=sc,
        ))
    return concepts


# ── Selection ─────────────────────────────────────────────────────────────

def select_cover_concept(
    edition: str = "",
    part: int = 1,
    used_hooks: Optional[set[str]] = None,
) -> CoverConcept:
    """
    Generate 10 cover concepts, reject weak ones, and return the best.

    Rejection rule: any dimension below REJECT_FLOOR (0.40) eliminates the
    concept — prevents a one-dimensionally-strong entry from winning with a
    fatal weakness elsewhere.

    Selection: highest weighted composite score among passing candidates.
    If used_hooks prevents all passing candidates, the constraint is dropped
    (never blocks generation). If no concept passes the REJECT_FLOOR across
    all dimensions, the highest composite is returned with the understanding
    that the base archetypes are designed to pass.
    """
    used = used_hooks or set()
    concepts = generate_cover_concepts(edition, part)

    # 1st choice: passing concepts not in used_hooks
    candidates = [
        c for c in concepts
        if c.score and c.score.passes and normalize_caption(c.hook) not in used
    ]
    if not candidates:
        # 2nd choice: passing concepts regardless of used_hooks
        candidates = [c for c in concepts if c.score and c.score.passes]
    if not candidates:
        # Final fallback: all concepts (shouldn't happen with well-designed archetypes)
        candidates = concepts

    return max(candidates, key=lambda c: c.score.composite if c.score else 0.0)


__all__ = [
    "REJECT_FLOOR",
    "CoverScore",
    "CoverConcept",
    "score_concept",
    "generate_cover_concepts",
    "select_cover_concept",
]
