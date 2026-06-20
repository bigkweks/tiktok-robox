"""
Viral scoring model.

Each sub-score is normalized to [0, 1] before weighting. The final
viral_score is a weighted sum also in [0, 1].

Design principle: weight MOMENTUM over SIZE. A game with 500K visits
growing at 50K/day beats a 500M visit game that's stagnant.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog

from src.config import get_settings
from src.database.models import ModelWeights

log = structlog.get_logger(__name__)


@dataclass
class ScoreBreakdown:
    viral_score: float
    growth_velocity_score: float
    engagement_ratio_score: float
    novelty_score: float
    retention_proxy_score: float
    update_freshness_score: float

    def as_dict(self) -> dict[str, float]:
        return {
            "viral_score": self.viral_score,
            "growth_velocity": self.growth_velocity_score,
            "engagement_ratio": self.engagement_ratio_score,
            "novelty": self.novelty_score,
            "retention_proxy": self.retention_proxy_score,
            "update_freshness": self.update_freshness_score,
        }


class ViralScorer:
    """
    Weighted multi-factor scoring model.

    Factors:
    ─────────────────────────────────────────────────────────────────
    growth_velocity  (0.30): How fast visits/players are increasing NOW.
                              Fast-movers surface before they peak.
    engagement_ratio (0.20): Quality signal. (favorites + likes) / visits.
                              Separates games people love vs just visit.
    novelty          (0.15): Recency × undiscovery. New games with growth
                              create FOMO-driven content.
    retention_proxy  (0.15): Favorites-per-1000-visits. High favorites ↔
                              players keep coming back = replayability.
    update_freshness (0.10): Recent developer updates = active game, more
                              watchable content, algorithm favorability.
    cross_platform   (0.10): Reserved for external buzz signals (Reddit,
                              YouTube). Falls back to visit milestone bonus.
    ─────────────────────────────────────────────────────────────────

    All weights are loaded from ModelWeights table if available, falling
    back to env config (which falls back to hardcoded defaults).
    """

    def __init__(self, weights: Optional[ModelWeights] = None):
        settings = get_settings()
        if weights:
            self.w_growth = weights.weight_growth_velocity
            self.w_engagement = weights.weight_engagement_ratio
            self.w_novelty = weights.weight_novelty
            self.w_retention = weights.weight_retention_proxy
            self.w_freshness = weights.weight_update_freshness
            self.w_cross = weights.weight_cross_platform
        else:
            self.w_growth = settings.WEIGHT_GROWTH_VELOCITY
            self.w_engagement = settings.WEIGHT_ENGAGEMENT_RATIO
            self.w_novelty = settings.WEIGHT_NOVELTY
            self.w_retention = settings.WEIGHT_RETENTION_PROXY
            self.w_freshness = settings.WEIGHT_UPDATE_FRESHNESS
            self.w_cross = settings.WEIGHT_CROSS_PLATFORM

    def score(
        self,
        visits: int,
        active_players: int,
        favorites: int,
        like_count: int,
        dislike_count: int,
        created_at: Optional[datetime],
        updated_at: Optional[datetime],
        visits_24h_ago: int = 0,
        players_24h_ago: int = 0,
    ) -> ScoreBreakdown:
        now = datetime.now(timezone.utc)

        growth = self._growth_velocity_score(visits, active_players, visits_24h_ago, players_24h_ago)
        engagement = self._engagement_ratio_score(visits, favorites, like_count, dislike_count)
        novelty = self._novelty_score(created_at, now)
        retention = self._retention_proxy_score(visits, favorites)
        freshness = self._update_freshness_score(updated_at, now)
        cross = self._cross_platform_score(visits)

        viral = (
            self.w_growth * growth
            + self.w_engagement * engagement
            + self.w_novelty * novelty
            + self.w_retention * retention
            + self.w_freshness * freshness
            + self.w_cross * cross
        )
        viral = max(0.0, min(1.0, viral))

        return ScoreBreakdown(
            viral_score=round(viral, 4),
            growth_velocity_score=round(growth, 4),
            engagement_ratio_score=round(engagement, 4),
            novelty_score=round(novelty, 4),
            retention_proxy_score=round(retention, 4),
            update_freshness_score=round(freshness, 4),
        )

    # ── Sub-score helpers ─────────────────────────────────────────────

    def _growth_velocity_score(
        self,
        visits: int,
        active_players: int,
        visits_24h_ago: int,
        players_24h_ago: int,
    ) -> float:
        """
        Two signals combined:
          1. Visit acceleration: (visits_now - visits_24h) / max(visits_24h, 1)
             → normalized via logistic curve
          2. Active:total player density: active / log10(visits+10)
             → proxy for "on fire right now"
        """
        if visits <= 0:
            return 0.0

        # Signal 1: 24h visit growth rate
        visit_delta = visits - visits_24h_ago
        if visits_24h_ago > 0:
            growth_rate = visit_delta / visits_24h_ago
        else:
            # No history yet — use active/visits ratio as proxy
            growth_rate = active_players / max(visits, 1) * 100

        # Logistic normalization: growth_rate of 0.10 (10% daily) → ~0.73
        sig1 = 1 / (1 + math.exp(-10 * (growth_rate - 0.05)))

        # Signal 2: player density (how "alive" the game is right now)
        # 1000 active players per million visits → score ~0.9
        log_visits = math.log10(max(visits, 1))
        density = active_players / max(log_visits * 1000, 1)
        sig2 = min(1.0, density * 3)

        return 0.6 * sig1 + 0.4 * sig2

    def _engagement_ratio_score(
        self,
        visits: int,
        favorites: int,
        like_count: int,
        dislike_count: int,
    ) -> float:
        """
        Engagement quality = (favorites×5 + likes) / visits
        Favorites weighted 5× because they require deliberate action.
        """
        if visits <= 0:
            return 0.0

        weighted_engagement = (favorites * 5 + like_count) / max(visits, 1)

        # Like ratio quality penalty: if dislike ratio > 30%, penalty applies
        total_votes = like_count + dislike_count
        if total_votes > 0:
            like_ratio = like_count / total_votes
            quality_mult = max(0.3, like_ratio)
        else:
            quality_mult = 0.5  # unknown quality

        raw = weighted_engagement * quality_mult * 1000
        return min(1.0, raw / 10)  # 10 per-1000 visits → score = 1.0

    def _novelty_score(self, created_at: Optional[datetime], now: datetime) -> float:
        """
        New games with growth are TikTok gold: viewers feel like discoverers.
        Score decays from 1.0 over 180 days using exponential decay.
        """
        if created_at is None:
            return 0.3  # unknown age — assume moderate novelty

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        age_days = max(0, (now - created_at).days)
        # τ = 60 days: at 60 days old → score ≈ 0.37
        return math.exp(-age_days / 60)

    def _retention_proxy_score(self, visits: int, favorites: int) -> float:
        """
        Favorites-per-1000-visits is the best public proxy for retention.
        Players only favorite games they plan to return to.
        """
        if visits <= 0:
            return 0.0
        fav_rate = (favorites / visits) * 1000
        # 50 favorites per 1000 visits → score = 1.0
        return min(1.0, fav_rate / 50)

    def _update_freshness_score(self, updated_at: Optional[datetime], now: datetime) -> float:
        """
        Recently updated games signal active development: more content to
        show, less risk of dead servers, TikTok rewards timely content.
        """
        if updated_at is None:
            return 0.2

        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        days_since_update = max(0, (now - updated_at).days)
        # Score = 1.0 if updated today, decays by half every 14 days
        return math.exp(-days_since_update / 14)

    def _cross_platform_score(self, visits: int) -> float:
        """
        Placeholder for Reddit/YouTube buzz data.

        Until external data is integrated, this acts as a visit-milestone
        bonus that rewards games large enough for TikTok viewers to
        recognize but small enough to feel undiscovered:
          - <100K visits → too small for social proof
          - 100K–10M visits → sweet spot (discoverable but not ubiquitous)
          - >100M visits → everyone knows it, lower novelty value
        """
        if visits < 100_000:
            return 0.1
        elif visits < 1_000_000:
            return 0.6
        elif visits < 10_000_000:
            return 1.0
        elif visits < 100_000_000:
            return 0.7
        else:
            return 0.4

    def predict_tiktok_performance(
        self,
        breakdown: ScoreBreakdown,
        rating_score: float,
        game_name: str,
    ) -> dict[str, float]:
        """
        Predict TikTok-specific performance metrics for a content item.
        These are distinct from the game discovery scores — they model
        how a VIDEO about this game will perform.
        """
        # Viral score: watch time drivers
        viral = (
            0.4 * breakdown.novelty_score          # FOMO → shares
            + 0.3 * breakdown.growth_velocity_score  # "before it blows up"
            + 0.2 * breakdown.retention_proxy_score  # good game → viewers trust you
            + 0.1 * (rating_score / 10)             # high/controversial rating = comments
        )

        # Engagement: comment + share drivers
        engagement = (
            0.35 * breakdown.engagement_ratio_score  # proof the game is good
            + 0.25 * breakdown.novelty_score         # discoverers want to share
            + 0.25 * (rating_score / 10)            # rating → debate
            + 0.15 * breakdown.growth_velocity_score # timely content
        )

        # Follow conversion: "this person finds good stuff" signal
        follow_conv = (
            0.40 * breakdown.novelty_score           # hidden gems = follow for more
            + 0.30 * breakdown.retention_proxy_score  # good taste signals
            + 0.30 * breakdown.update_freshness_score # consistent fresh content
        )

        # Novelty (content-level): how fresh will this feel to TikTok viewers
        novelty = breakdown.novelty_score * 0.7 + (1 - breakdown.engagement_ratio_score) * 0.3

        return {
            "predicted_viral_score": min(1.0, viral),
            "predicted_engagement_score": min(1.0, engagement),
            "predicted_follow_conv_score": min(1.0, follow_conv),
            "predicted_novelty_score": min(1.0, novelty),
            "queue_priority": min(1.0, (viral * 0.4 + engagement * 0.3 + follow_conv * 0.3)),
        }
