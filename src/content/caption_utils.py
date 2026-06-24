"""
Carousel caption safeguards.

Two failure modes this guards against:

  1. Within one caption: stutters like "minecraft dropper if ukuk ukuk".
  2. Across one carousel: the model leaning on the same slang crutch for every
     slide ("X if ukuk", "Y if ukuk", "Z if ukuk"), or repeating the same line.

`dedupe_carousel_captions` takes the per-slide captions for a single carousel
and rewrites any duplicate / crutch-repeating / stuttering line with a varied,
game-appropriate alternative, so no two slides in a post read the same way.
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

# Slang tags the model tends to over-use. We allow a tag once per carousel; a
# second slide reaching for the same one gets rewritten.
_SLANG_TAGS = (
    "if ukuk",
    "if u know u know",
    "if you know you know",
    "iykyk",
    "no cap",
    "fr fr",
    "fr",
    "ngl",
    "lowkey",
    "hits different",
)

_WORD_RE = re.compile(r"[a-z0-9]+")

# Generic filler the caption voice explicitly forbids. Treated as unacceptable
# so even the first occurrence gets rewritten to something specific.
_GENERIC_BANNED = frozenset({
    "fun game", "good game", "great game", "nice game", "cool game",
    "amazing game", "best game", "fun roblox game", "good roblox game",
    "play this", "check this out", "must play", "so fun", "very fun",
})

# Game-appropriate alternatives, ordered most-specific first. Kept in the same
# lowercase player voice as the prompt. No emojis, no trailing punctuation.
_GENRE_LINES: dict[str, tuple[str, ...]] = {
    "horror": ("horror that actually scared me", "do not play this solo",
               "genuinely unsettling one", "made me jump for real", "scariest one on roblox"),
    "adventure": ("adventure that hooked me fast", "open world done right",
                  "actually worth exploring", "got lost for hours in this", "the map is HUGE"),
    "rpg": ("rpg with real depth", "grind that feels rewarding",
            "surprisingly deep progression", "the build variety is crazy", "60 hours deep no regrets"),
    "fighting": ("combat that actually feels good", "movement is so clean",
                 "pvp that takes skill", "the combos are buttery", "skill ceiling is insane"),
    "fps": ("gunplay hits different", "valorant but roblox",
            "sweat lobby in the best way", "the aim feels SO clean", "cracked shooter on roblox"),
    "simulator": ("sim that respects your time", "weirdly addictive loop",
                  "one more run every time", "numbers go brrr", "cant stop the grind"),
    "obby": ("obby that actually challenged me", "rage bait done right",
             "harder than it looks", "almost broke my phone", "the hardest obby ive beat"),
    "roleplay": ("roleplay that feels alive", "best rp town ive found",
                 "immersion is unreal", "the community makes it", "got way too invested"),
    "tycoon": ("tycoon you cant put down", "satisfying build up",
               "numbers go up perfectly", "the empire grind is real", "one more upgrade fr"),
    "puzzle": ("puzzle game that broke my brain", "actually makes you think",
               "clever level design", "had me genuinely stuck", "so satisfying to solve"),
    "tower defense": ("td that actually got hard", "the late waves are brutal",
                      "strategy that rewards you", "best td on roblox imo"),
    "racing": ("the drift physics are unreal", "actual racing not luck",
               "got way too competitive", "smoother than it has any right to be"),
    "survival": ("the tension never lets up", "survival that stresses you out",
                 "every run feels different", "barely made it out alive"),
    "story": ("the story actually hit", "did NOT expect that ending",
              "more story than most full games", "got me emotional ngl"),
    "anime": ("for the anime fans fr", "the abilities go crazy",
              "peak anime energy", "every character slaps"),
    "clicker": ("dangerously addictive clicker", "the progression is so smooth",
                "lost track of time clicking", "one more prestige i swear"),
}

_SCORE_LINES: tuple[tuple[float, tuple[str, ...]], ...] = (
    (9.5, ("MUST check this out", "actual masterpiece", "instant favorite",
           "this is a TOP tier one", "drop everything and play this")),
    (9.0, ("no one talks about this", "criminally underrated", "hidden gem for real",
           "how is this not viral", "best one i found this month")),
    (8.0, ("well made game honestly", "way better than expected", "spent hours in this",
           "this deserves way more players", "genuinely impressed by this")),
    (7.0, ("lowkey pretty solid", "better than it looks", "worth a real shot",
           "surprised me ngl", "give this one a chance")),
    (5.5, ("decent if youre into it", "fine for a quick session", "has its moments",
           "okay but could be more", "playable but rough edges")),
    (0.0, ("overhyped imo", "not worth the hype", "skip unless youre bored",
           "expected way more", "all hype no substance")),
)

_NEUTRAL_LINES: tuple[str, ...] = (
    "stumbled on this and stayed",
    "underrated and i mean it",
    "this one surprised me",
    "way more fun than expected",
    "cant believe its free",
    "been playing this nonstop",
    "why is no one playing this",
    "found a gem fr",
    "sleeper hit of the year",
    "instantly added to favorites",
    "this got me off tiktok",
    "wish i found this sooner",
)


def normalize_caption(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def has_internal_repetition(text: Optional[str]) -> bool:
    """Immediate duplicate-word stutters, e.g. 'if ukuk ukuk' or 'game game'."""
    words = _WORD_RE.findall((text or "").lower())
    return any(a == b for a, b in zip(words, words[1:]))


def is_generic(text: Optional[str]) -> bool:
    """True for forbidden filler captions like 'fun game' / 'good game'."""
    return normalize_caption(text) in _GENERIC_BANNED


def crutch_tag(text: Optional[str]) -> Optional[str]:
    """The trailing slang tag a caption leans on, if any."""
    t = normalize_caption(text)
    if not t:
        return None
    for tag in _SLANG_TAGS:
        if t == tag or t.endswith(" " + tag):
            return tag
    return None


def _candidates(genre: Optional[str], score: Optional[float]) -> list[str]:
    """Ordered alternative captions for a game, most-specific first."""
    out: list[str] = []
    g = (genre or "").lower()
    for key, lines in _GENRE_LINES.items():
        if key in g:
            out.extend(lines)
            break
    if score is not None:
        for threshold, lines in _SCORE_LINES:
            if score >= threshold:
                out.extend(lines)
                break
    out.extend(_NEUTRAL_LINES)
    return out


def dedupe_carousel_captions(
    captions: Sequence[Optional[str]],
    genres: Optional[Sequence[Optional[str]]] = None,
    scores: Optional[Sequence[Optional[float]]] = None,
) -> list[str]:
    """
    Return captions for one carousel with duplicates, repeated slang crutches,
    and word stutters rewritten to varied, game-appropriate alternatives.

    Order and length are preserved (1:1 with the input).
    """
    n = len(captions)
    genres = list(genres) if genres is not None else [None] * n
    scores = list(scores) if scores is not None else [None] * n

    used_norms: set[str] = set()
    used_tags: set[str] = set()
    result: list[str] = []

    for i in range(n):
        original = (captions[i] or "").strip()
        genre = genres[i] if i < len(genres) else None
        score = scores[i] if i < len(scores) else None

        def _acceptable(text: str) -> bool:
            norm = normalize_caption(text)
            if not norm or norm in used_norms:
                return False
            if norm in _GENERIC_BANNED:
                return False
            if has_internal_repetition(text):
                return False
            tag = crutch_tag(text)
            if tag and tag in used_tags:
                return False
            return True

        chosen = original if _acceptable(original) else None
        if chosen is None:
            for cand in _candidates(genre, score):
                if _acceptable(cand):
                    chosen = cand
                    break
        if chosen is None:
            # Exhausted the bank (unlikely): fall back to a unique numbered line.
            base = next(iter(_NEUTRAL_LINES))
            k = 2
            chosen = base
            while normalize_caption(chosen) in used_norms:
                chosen = f"{base} {k}"
                k += 1

        used_norms.add(normalize_caption(chosen))
        tag = crutch_tag(chosen)
        if tag:
            used_tags.add(tag)
        result.append(chosen)

    return result
