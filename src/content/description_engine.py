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

    def caption_a_with_tags(self) -> str:
        return f"{self.description_a}\n\n{self.hashtags_str}"

    def caption_b_with_tags(self) -> str:
        return f"{self.description_b}\n\n{self.hashtags_str}"


HASHTAG_TIERS = {
    "brand": ["#robloxgems", "#robloxrating", "#robloxreview"],
    "niche": ["#robloxfyp", "#robloxgames", "#roblox2024", "#robloxtrending"],
    "broad": ["#fyp", "#foryoupage", "#gaming", "#gamingtiktok"],
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
- End with a call to action
- Natural language, NOT clickbait
- No more than 3 emojis total
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

            cap_a = data.get("caption_a") or self._fallback_a(name, score, label, visits_str)
            cap_b = data.get("caption_b") or self._fallback_b(name, score, visits_str)

        except Exception as exc:
            log.warning("description.ai_failed", game=name, error=str(exc))
            cap_a = self._fallback_a(name, score, label, visits_str)
            cap_b = self._fallback_b(name, score, visits_str)

        hashtags = self._build_hashtags(genre, name)

        return DescriptionResult(
            description_a=cap_a,
            description_b=cap_b,
            hashtags=hashtags,
            hashtags_str=" ".join(hashtags),
        )

    def _build_hashtags(self, genre: Optional[str], name: str) -> list[str]:
        tags: list[str] = []

        # Brand tags always first (build discoverability over time)
        tags.extend(HASHTAG_TIERS["brand"])

        # Genre-specific tags
        genre_lower = (genre or "").lower()
        genre_tags = HASHTAG_TIERS["genre"].get(genre_lower, HASHTAG_TIERS["genre"]["default"])
        tags.extend(genre_tags)

        # Game-specific tag (helps people search the game)
        slug = re.sub(r"[^a-zA-Z0-9]", "", name.lower())
        if len(slug) > 2:
            tags.append(f"#{slug}")

        # Niche tags
        tags.extend(HASHTAG_TIERS["niche"])

        # Broad reach tags (limit these — too many broad tags = lower engagement rate)
        tags.extend(HASHTAG_TIERS["broad"][:2])

        # TikTok has a recommended hashtag count of 3-5 for gaming
        # Use 8-12 total for Roblox gaming niche (data shows this performs best)
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
    def _fallback_a(name: str, score: float, label: str, visits_str: str) -> str:
        if score >= 9.0:
            return (
                f"This Roblox game has {visits_str} visits and most people have never heard of it. "
                f"We played it and gave it a {score}/10 — and we don't hand those out easily. "
                f"Drop a comment with your rating after you try it."
            )
        elif score >= 7.0:
            return (
                f"Gave {name} a {score}/10 and I know people are going to disagree. "
                f"What would YOU rate it? Comment below."
            )
        else:
            return (
                f"{name} has {visits_str} visits but our honest verdict is {score}/10. "
                f"Agree or disagree — let us know."
            )

    @staticmethod
    def _fallback_b(name: str, score: float, visits_str: str) -> str:
        return (
            f"{visits_str} people can't be wrong about {name}... or can they? "
            f"We put it through our rating system and here's what we found. "
            f"Follow for a new Roblox review every day."
        )
