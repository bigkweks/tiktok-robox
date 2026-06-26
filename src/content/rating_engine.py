"""
AI-powered rating engine.

Core viral mechanic: a slightly provocative, opinion-driven rating
drives debate in comments, which is the strongest TikTok signal.

Rating strategy:
  - Popular games: Rate honestly, often slightly below expectations
    ("People will comment 'this should be higher!'")
  - Hidden gems: Rate high + enthusiastic ("Finally someone noticed!")
  - Overhyped games: Rate critically with clear reasoning
    ("Controversial take = shares")

The numerical breakdown is multi-factor and weighted — it's not random.
This creates credibility for the brand.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

import anthropic
import structlog

from src.config import get_settings

log = structlog.get_logger(__name__)


@dataclass
class RatingResult:
    score: float                    # 0.0 – 10.0
    label: str                      # "HIDDEN GEM", "OVERHYPED", etc.
    verdict: str                    # one-sentence summary
    breakdown: dict[str, float]     # sub-scores
    tts_script: str                 # what the narrator will say
    controversy_angle: str          # the opinion that will spark debate
    hook_text: str = ""             # first 2s on screen (≤9 words, no emoji)
    carousel_caption: str = ""      # short casual line for photo carousel slides
    used_fallback: bool = False     # True when AI failed and this is rule-based output

    @property
    def display_score(self) -> str:
        return f"{self.score:.1f}"

    @property
    def score_color(self) -> tuple[int, int, int]:
        if self.score >= 8.5:
            return (50, 205, 50)    # green
        elif self.score >= 7.0:
            return (255, 215, 0)    # gold
        elif self.score >= 5.5:
            return (255, 165, 0)    # orange
        else:
            return (220, 20, 60)    # crimson


RATING_LABELS = {
    (9.0, 10.0): "HIDDEN GEM 💎",
    (8.0, 9.0):  "ACTUALLY GOOD ✅",
    (7.0, 8.0):  "WORTH PLAYING 🎮",
    (5.5, 7.0):  "DECENT 😐",
    (3.0, 5.5):  "OVERHYPED ⚠️",
    (0.0, 3.0):  "SKIP IT ❌",
}


def _get_label(score: float) -> str:
    for (lo, hi), label in RATING_LABELS.items():
        if lo <= score < hi:
            return label
    return "HIDDEN GEM 💎"


RATING_PROMPT = """You are a viral TikTok content creator who reviews Roblox games.

Your rating style is:
- Opinionated and direct (mild controversy drives comments)
- Data-informed (reference actual stats)
- Enthusiastic about hidden gems
- Honestly critical of overhyped games
- Never clickbait — always deliver on the hook

Game data:
Name: {name}
Visits: {visits:,}
Active players right now: {active_players:,}
Favorites: {favorites:,}
Like ratio: {like_ratio:.1%}
Genre: {genre}
Created: {created_at}
Last updated: {updated_at}
Description: {description}

Generate a JSON rating with this exact structure:
{{
  "score": <float 0.0-10.0, one decimal>,
  "breakdown": {{
    "fun_factor": <float 0-10>,
    "replayability": <float 0-10>,
    "originality": <float 0-10>,
    "visual_quality": <float 0-10>,
    "community": <float 0-10>
  }},
  "verdict": "<one punchy, HIGH-ENERGY sentence, max 12 words, no emojis. Sound genuinely hyped (for gems) or genuinely fired-up (for overhyped ones) — never flat or corporate. Vary the sentence shape every time; do not start with the game name every time. OPTIONAL engagement bait: ~1 in 3 times, use a slightly wrong but debatable comparison in the verdict too (e.g. 'basically the roblox version of GTA' when it's more like Payday) — makes players argue in the comments.>",
  "controversy_angle": "<the mildly controversial opinion that will spark comment debate, 1 sentence>",
  "tts_script": "<15-20 second narration script for the video, natural spoken English, include the score reveal at the end, no special chars>",
  "hook_text": "<the first 2 seconds of text shown on screen — max 9 words>",
  "carousel_caption": "<see CAROUSEL CAPTION VOICE below — this is burned onto the photo slide>"
}}

CAROUSEL CAPTION VOICE (this single line sits on the game's screenshot — it MUST sound like a real teenage Roblox player typing fast, never like a brand or a marketer):

These are REAL captions from a carousel that hit 118K views — match this VOICE (do not copy them verbatim):
  - "only escape room thats actually challenging"
  - "well made game i spent 30+ hours in"
  - "GTA in roblox"
  - "horror that actually scared me"
  - "MUST check out"
  - "criminally underrated"

Hard rules for carousel_caption:
  - 3 to 8 words. Shorter is better.
  - all lowercase EXCEPT you may CAPS one word for hype ("MUST", "INSANE").
  - NO ending punctuation. NO emojis. NO hashtags.
  - drop apostrophes ("thats", "dont", "its") — it reads as authentic.
  - Write something SPECIFIC to THIS game. Lead with what makes it stand out
    (its mechanic, genre, or vibe), not a filler slang tag.
  - Slang ("fr", "ngl", "no cap", "lowkey", "hits different", "if u know u know")
    is OK as seasoning, but use it sparingly — AT MOST one slang tag, and never
    as a crutch you reach for every time. A plain specific caption beats a
    generic slang one.
  - Pick ONE of these angles, whichever fits the game best:
      * ENGAGEMENT BAIT comparison (use this roughly 1 in 3 times — it drives the
        most comments): make a game comparison that is SLIGHTLY wrong or debatable.
        The comparison should be close enough to feel like a genuine hot take but
        off enough that players feel compelled to correct it.
        Examples of the format — study the PATTERN, do NOT copy verbatim:
          "basically GTA" (when it's actually more like Payday — crime theme but heist)
          "minecraft but better" (when it's more like Terraria)
          "roblox fortnite" (when it's more of a hero-shooter, not battle royale)
          "dark souls in roblox" (when it's actually more like Hollow Knight)
          "pokemon but in roblox" (when it's more of a creature-collector like Temtem)
        The key: pick a FAMOUS game the audience knows, make the comparison slightly
        wrong but defensible, so comments fill up with "bro this is nothing like X its
        more like Y". Use the game's actual genre/mechanic to pick the "wrong" famous game.
      * personal flex: "spent 30+ hours in this", "cant stop playing this"
      * underrated: "no one talks about this", "criminally underrated"
      * pure hype (only for 9.5+): "MUST check out", "actual masterpiece"
      * niche callout: "horror that actually scared me", "puzzle game that broke my brain"
  - Never generic like "fun game", "good game", or "if ukuk" on its own.
  - BANNED AI/marketing phrases (instant tell, never use): "dive into",
    "unlock the", "the ultimate", "game-changer", "you won't believe",
    "look no further", "level up", "next level", "must-have", "elevate".

CAROUSEL CAPTION ANTI-PATTERN CHECK — before you output it, ask: "would a real
14-year-old type this in a TikTok comment, or does it sound like an ad?" If it
sounds like an ad, rewrite it. Lead with the one concrete thing that makes THIS
game different. Two different games must never get interchangeable captions.

HOOK RULES (this is the single most important field — most viewers leave in 1.5s):
- Be concrete and specific, never generic. BAD: "This game is amazing".
  GOOD: "This 800K-visit game humbles Blox Fruits".
- Use ONE of these proven angles:
  * Underrated shock: "Why does nobody play this Roblox game?"
  * Overrated hot take: "{name} is wildly overrated and here's proof"
  * Number tension: "I rated {name} and people are going to be mad"
  * Curiosity gap: "The {genre} game Roblox doesn't want you to find"
  * Stakes: "Rating {name} so you don't waste your time"
- Reference a real number or the genre when it sharpens the hook.
- Never reveal the score in the hook — the score is the payoff.
- No hashtags, no emojis in hook_text.
- Earn curiosity honestly. BANNED spammy/over-promise words: "shocking",
  "insane", "you need to see this", "will blow your mind", "#1", "best ever".
  A real, specific detail beats hype every time.
- Vary the hook's sentence shape — do not open every hook with the game name.

Scoring rules:
- 9.0–10.0: Elite tier — exceptional quality AND underexposed (< 10M visits preferred)
- 8.0–8.9: Genuinely great game most people should play
- 7.0–7.9: Good game with notable flaws or overshadowed by better options
- 5.5–6.9: Average, exists, probably has a fanbase, not exceptional
- 3.0–5.4: Below average — rating should explain WHY so viewers debate it
- 0.0–2.9: Avoid (rare — only for genuinely broken/abandoned games)

Be mildly contrarian when it serves the content:
- If a massively popular game (100M+ visits) has mediocre quality → rate it 5-6 honestly
- If a tiny game (< 1M visits) has exceptional quality → give it a 9+ and be excited

Return ONLY valid JSON, no other text."""


class RatingEngine:
    def __init__(self):
        self._settings = get_settings()
        self._client = anthropic.Anthropic(api_key=self._settings.ANTHROPIC_API_KEY)

    def rate_game(
        self,
        name: str,
        description: str,
        visits: int,
        active_players: int,
        favorites: int,
        like_ratio: float,
        genre: str,
        created_at: Optional[str],
        updated_at: Optional[str],
        viral_score: float,
    ) -> RatingResult:
        """Generate a full AI rating for a game. Synchronous for scheduler compatibility."""
        prompt = RATING_PROMPT.format(
            name=name,
            visits=visits,
            active_players=active_players,
            favorites=favorites,
            like_ratio=like_ratio,
            genre=genre or "Unknown",
            created_at=created_at or "Unknown",
            updated_at=updated_at or "Unknown",
            description=(description or "No description available")[:500],
        )

        try:
            response = self._client.messages.create(
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text.strip()

            # Extract JSON even if wrapped in markdown code blocks
            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON found in response")

            data = json.loads(json_match.group())
            score = float(data["score"])
            score = max(0.0, min(10.0, score))
            breakdown = {k: float(v) for k, v in data.get("breakdown", {}).items()}

            label = _get_label(score)
            verdict = data.get("verdict", f"{name} — {score:.1f}/10")
            controversy = data.get("controversy_angle", "")
            tts_script = data.get("tts_script", self._fallback_tts(name, score, visits))
            hook_text = data.get("hook_text", self._fallback_hook(name, visits))
            carousel_caption = data.get("carousel_caption", self._fallback_carousel_caption(name, score, visits, genre))

            # Reject stuttering / empty captions ("... if ukuk ukuk") at the source.
            from src.content.caption_utils import has_internal_repetition  # noqa: PLC0415
            if not (carousel_caption or "").strip() or has_internal_repetition(carousel_caption):
                carousel_caption = self._fallback_carousel_caption(name, score, visits, genre)

            # Override label with hook if hook_text is empty
            if not hook_text:
                hook_text = self._fallback_hook(name, visits)

            # Inject hook_text into tts_script as opening line if missing
            if hook_text not in tts_script and not tts_script.startswith(hook_text[:10]):
                tts_script = f"{hook_text}. {tts_script}"

            result = RatingResult(
                score=round(score, 1),
                label=label,
                verdict=verdict,
                breakdown=breakdown,
                tts_script=tts_script,
                controversy_angle=controversy,
                hook_text=hook_text,
                carousel_caption=carousel_caption,
            )
            log.info("rating.generated", game=name, score=score, label=label)
            return result

        except Exception as exc:
            # Loud by design: rule-based fallback must never pass as AI output.
            # The dashboard's AI-status banner surfaces the credential state; this
            # log line records that THIS specific rating was not AI-generated.
            log.error("rating.fallback_active", game=name, error=str(exc),
                      reason="anthropic_call_failed")
            fb = self._fallback_rating(name, visits, viral_score)
            fb.hook_text = self._fallback_hook(name, visits)
            fb.carousel_caption = self._fallback_carousel_caption(name, fb.score, visits, genre)
            fb.used_fallback = True
            return fb

    def _fallback_rating(self, name: str, visits: int, viral_score: float) -> RatingResult:
        """Rule-based fallback if AI fails."""
        score = min(9.5, max(5.0, viral_score * 9 + 0.5))
        return RatingResult(
            score=round(score, 1),
            label=_get_label(score),
            verdict=self._fallback_verdict(name, score),
            breakdown={},
            tts_script=self._fallback_tts(name, score, visits),
            controversy_angle="",
        )

    @staticmethod
    def _fallback_verdict(name: str, score: float) -> str:
        # This line gets burned onto the game slide as the "why it slaps"
        # callout, so the fallback must sound like a hyped player, never like a
        # corporate metric ("shows strong engagement metrics" was an instant AI
        # tell). Score-tiered, name-hashed so a batch doesn't repeat one line.
        if score >= 9.0:
            pool = (
                "this one deserves way more players than it has",
                "genuinely one of the best i've found lately",
                "criminally slept on, go play it now",
                "no idea how this isn't everywhere yet",
            )
        elif score >= 7.5:
            pool = (
                "way better than the visit count suggests",
                "quietly one of the more polished ones out here",
                "surprised me way more than i expected",
                "the kind of game you replay for hours",
            )
        else:
            pool = (
                "rough in spots but there's something here",
                "not perfect, still worth a look",
                "has its moments if you give it time",
                "decent pick when you've run out of others",
            )
        return pool[sum(ord(c) for c in (name or "x")) % len(pool)]

    @staticmethod
    def _fallback_tts(name: str, score: float, visits: int) -> str:
        visits_str = f"{visits / 1_000_000:.1f} million" if visits >= 1_000_000 else f"{visits:,}"
        return (
            f"{name} has {visits_str} visits on Roblox, "
            f"and most people haven't even heard of it. "
            f"After testing it ourselves, we're giving it a {score:.1f} out of 10. "
            f"Follow for more hidden Roblox gems every day."
        )

    @staticmethod
    def _fallback_carousel_caption(name: str, score: float, visits: int, genre: str = "") -> str:
        # Same casual player voice as the AI prompt, used only if the API fails.
        # Pull from the shared caption banks and pick deterministically by a hash
        # of the game name so two games with the same score don't get the same
        # fallback line (the old version always returned one fixed phrase per
        # tier, which made fallbacks read identically across a batch).
        from src.content.caption_utils import _candidates  # noqa: PLC0415
        pool = _candidates(genre, score)
        if not pool:
            return "underrated and i mean it"
        return pool[sum(ord(c) for c in (name or "x")) % len(pool)]

    @staticmethod
    def _fallback_hook(name: str, visits: int) -> str:
        # Concrete, pattern-interrupting hooks mapped to the game's fame tier.
        if visits >= 500_000_000:
            return f"Is {name} actually overrated?"
        elif visits >= 100_000_000:
            return f"Rating {name} so you don't have to"
        elif visits >= 10_000_000:
            return f"{name} has {visits // 1_000_000}M visits — but is it good?"
        elif visits >= 1_000_000:
            return f"Why does nobody talk about {name}?"
        else:
            n = _format_short(visits)
            return f"This {n}-visit game is a hidden gem"


def _format_short(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)
