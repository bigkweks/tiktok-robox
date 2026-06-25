"""
TikTok caption + hashtag generator.

Generates multiple caption variants (A/B test) optimized for:
  - First line as hook (TikTok shows only the first line in feed)
  - Saves (caption adds value beyond the video)
  - Comments (asks a question or makes a statement viewers react to)
  - Follow (creates expectation for more content)
  - Discoverability (strategic hashtag mix)
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
class DescriptionResult:
    description_a: str      # Primary caption (curiosity-driven)
    description_b: str      # Secondary caption (social proof angle)
    hashtags: list[str]     # Combined hashtag strategy
    hashtags_str: str       # Space-separated for display
    used_fallback: bool = False  # True when AI failed and captions are rule-based

    def caption_a_with_tags(self) -> str:
        return f"{self.description_a}\n\n{self.hashtags_str}"

    def caption_b_with_tags(self) -> str:
        return f"{self.description_b}\n\n{self.hashtags_str}"


HASHTAG_TIERS = {
    # These match the EXACT search queries that drove 23.9% search traffic
    # on the proven viral post: "roblox games", "roblox games to play",
    # "roblox games to play with friends", "fun roblox games with friends"
    "brand": ["#robloxgems", "#robloxrating", "#robloxreview"],
    "search": ["#robloxgames", "#robloxgamestoplywithfriends", "#funrobloxgames"],
    "niche": ["#robloxfyp", "#roblox", "#robloxtrending"],
    "broad": ["#fyp", "#gaming"],
    "genre": {
        "horror": ["#robloxhorror", "#horrorRoblox"],
        "adventure": ["#robloxadventure"],
        "roleplay": ["#robloxrp", "#robloxroleplay"],
        "simulator": ["#robloxsimulator"],
        "obby": ["#robloxobby"],
        "default": ["#robloxgaming"],
    },
}

DESCRIPTION_PROMPT = """You are a TikTok content strategist specializing in gaming content.

Create two caption variants for a TikTok video reviewing this Roblox game.

Game: {name}
Rating: {score}/10 ({label})
Verdict: {verdict}
Visits: {visits_str}
Genre: {genre}
Hook used: {hook_text}
Controversy angle: {controversy}

Requirements for BOTH captions:
- First line is the hook (shows in feed before "see more")
- 2-4 sentences max
- Curiosity-driven or social proof
- End with a call to action that demands a reply ("which one are you playing first?",
  "rate it 1-10 in the comments", "tag who you'd play this with")
- Natural, HIGH-ENERGY teenage-creator voice — genuinely excited, never flat,
  never corporate, never clickbait
- Use 2-3 emojis, placed where they punch (not all clumped at the end)
- Every caption must feel different from the last — vary the opening words,
  sentence rhythm, and the call to action. Do NOT start both variants the same way.
- BANNED AI/marketing tells (instant giveaway, never use): "dive into",
  "look no further", "the ultimate", "unlock", "game-changer", "elevate",
  "without further ado", "in today's", "you won't believe", "level up".
- Self-check before output: if a line sounds like brand copy or a press
  release, rewrite it in the voice of a real player texting a friend.
- Must make viewers want to comment their opinion

Variant A: curiosity/mystery angle (builds tension around the rating)
Variant B: social proof angle (references the visits/stats to create FOMO)

Return JSON only:
{{
  "caption_a": "<caption text, no hashtags>",
  "caption_b": "<caption text, no hashtags>"
}}"""


class DescriptionEngine:
    def __init__(self):
        self._settings = get_settings()
        self._client = anthropic.Anthropic(api_key=self._settings.ANTHROPIC_API_KEY)

    def generate(
        self,
        name: str,
        score: float,
        label: str,
        verdict: str,
        visits: int,
        genre: Optional[str],
        hook_text: str,
        controversy_angle: str,
    ) -> DescriptionResult:
        visits_str = self._format_visits(visits)

        try:
            prompt = DESCRIPTION_PROMPT.format(
                name=name,
                score=score,
                label=label,
                verdict=verdict,
                visits_str=visits_str,
                genre=genre or "Unknown",
                hook_text=hook_text,
                controversy=controversy_angle or "N/A",
            )

            response = self._client.messages.create(
                model=self._settings.ANTHROPIC_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(json_match.group()) if json_match else {}

            # If either caption is missing from the AI response we fall back for
            # it — flag that so degraded copy is never mistaken for AI output (M3).
            used_fallback = not (data.get("caption_a") and data.get("caption_b"))
            cap_a = data.get("caption_a") or self._fallback_a(name, score, label, visits_str)
            cap_b = data.get("caption_b") or self._fallback_b(name, score, visits_str)

        except Exception as exc:
            log.warning("description.ai_failed", game=name, error=str(exc))
            cap_a = self._fallback_a(name, score, label, visits_str)
            cap_b = self._fallback_b(name, score, visits_str)
            used_fallback = True

        hashtags = self._build_hashtags(genre, name)

        return DescriptionResult(
            description_a=cap_a,
            description_b=cap_b,
            hashtags=hashtags,
            hashtags_str=" ".join(hashtags),
            used_fallback=used_fallback,
        )

    def generate_local(
        self,
        name: str,
        score: float,
        label: str,
        visits: int,
        genre: Optional[str],
    ) -> DescriptionResult:
        """Build TikTok video captions WITHOUT an API call, using the same
        rule-based fallbacks the AI path falls back to. Used on the carousel-only
        path (videos off) so we don't spend a second Claude call per game on
        captions the carousel never uses."""
        visits_str = self._format_visits(visits)
        hashtags = self._build_hashtags(genre, name)
        return DescriptionResult(
            description_a=self._fallback_a(name, score, label, visits_str),
            description_b=self._fallback_b(name, score, visits_str),
            hashtags=hashtags,
            hashtags_str=" ".join(hashtags),
        )

    def _build_hashtags(self, genre: Optional[str], name: str) -> list[str]:
        tags: list[str] = []

        # Search-optimised order: match proven queries first
        tags.extend(HASHTAG_TIERS["search"])   # drives Search traffic (23.9% proven)
        tags.extend(HASHTAG_TIERS["brand"])

        # Genre-specific tags
        genre_lower = (genre or "").lower()
        genre_tags = HASHTAG_TIERS["genre"].get(genre_lower, HASHTAG_TIERS["genre"]["default"])
        tags.extend(genre_tags)

        # Game-specific tag (helps people search the game)
        slug = re.sub(r"[^a-zA-Z0-9]", "", name.lower())
        if len(slug) > 2:
            tags.append(f"#{slug}")

        # Niche + broad
        tags.extend(HASHTAG_TIERS["niche"])
        tags.extend(HASHTAG_TIERS["broad"])

        return tags[:12]

    @staticmethod
    def _format_visits(visits: int) -> str:
        if visits >= 1_000_000_000:
            return f"{visits / 1_000_000_000:.1f}B"
        elif visits >= 1_000_000:
            return f"{visits / 1_000_000:.1f}M"
        elif visits >= 1_000:
            return f"{visits / 1_000:.0f}K"
        return str(visits)

    @staticmethod
    def _pick(name: str, options: list[str]) -> str:
        """Deterministic but game-varied choice so fallbacks don't repeat."""
        return options[sum(ord(c) for c in (name or "x")) % len(options)]

    @classmethod
    def _fallback_a(cls, name: str, score: float, label: str, visits_str: str) -> str:
        if score >= 9.0:
            return cls._pick(name, [
                f"okay this {visits_str}-visit game is a straight up HIDDEN GEM 💎 "
                f"we gave it a {score}/10 and we do not hand those out. "
                f"go play it then tell me i was wrong 👇",
                f"why is NOBODY talking about this Roblox game?? 😭 {score}/10, no notes. "
                f"save this so you actually remember to play it. which one first?",
                f"found your next obsession and it only has {visits_str} visits 👀 "
                f"hard {score}/10 from us. rate it yourself in the comments 🔥",
            ])
        elif score >= 7.0:
            return cls._pick(name, [
                f"gave {name} a {score}/10 and i KNOW some of you are gonna fight me on it 😅 "
                f"what would you rate it? comment below ⬇️",
                f"is {name} actually worth it? we said {score}/10 👀 "
                f"agree? disagree? settle it in the comments.",
                f"{name} surprised me ngl — solid {score}/10. "
                f"tag who you'd drag into this one 🎮",
            ])
        else:
            return cls._pick(name, [
                f"hot take: {name} is overhyped 🫣 we gave it an honest {score}/10. "
                f"come argue with me in the comments ⬇️",
                f"{visits_str} visits but is it actually good? our verdict: {score}/10. "
                f"am i tripping? let me know 👇",
            ])

    @classmethod
    def _fallback_b(cls, name: str, score: float, visits_str: str) -> str:
        return cls._pick(name, [
            f"{visits_str} people can't be wrong about {name}... or can they? 🤔 "
            f"we ran it through our rating system and the result shocked us. "
            f"follow for a new Roblox gem every single day 🔥",
            f"everyone sleeps on {name} and i don't get it 😤 {visits_str} visits and climbing. "
            f"save it, play it, then thank me later. follow for daily Roblox picks 💎",
            f"POV: you just found the Roblox game your whole friend group needed 🫶 "
            f"{name} — {visits_str} visits. tag the squad and follow for more 🎮",
        ])
