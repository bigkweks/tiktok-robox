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
  "verdict": "<one punchy sentence, max 12 words, no emojis>",
  "controversy_angle": "<the mildly controversial opinion that will spark comment debate, 1 sentence>",
  "tts_script": "<15-20 second narration script for the video, natural spoken English, include the score reveal at the end, no special chars>",
  "hook_text": "<the first 2 seconds of text shown on screen — must create instant curiosity, max 10 words>"
}}

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
            )
            log.info("rating.generated", game=name, score=score, label=label)
            return result

        except Exception as exc:
            log.error("rating.failed", game=name, error=str(exc))
            return self._fallback_rating(name, visits, viral_score)

    def _fallback_rating(self, name: str, visits: int, viral_score: float) -> RatingResult:
        """Rule-based fallback if AI fails."""
        score = min(9.5, max(5.0, viral_score * 9 + 0.5))
        return RatingResult(
            score=round(score, 1),
            label=_get_label(score),
            verdict=f"{name} shows strong engagement metrics.",
            breakdown={},
            tts_script=self._fallback_tts(name, score, visits),
            controversy_angle="",
        )

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
    def _fallback_hook(name: str, visits: int) -> str:
        if visits > 100_000_000:
            return f"Is {name} actually worth your time?"
        elif visits > 10_000_000:
            return f"{name} has {visits // 1_000_000}M visits — here's why"
        else:
            return f"Nobody talks about this Roblox game..."
