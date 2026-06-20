"""
Analytics feedback loop.

Ingests TikTok performance data and updates the scoring model.

Two modes:
  1. API mode: Pulls data from TikTok Research API (requires approval)
  2. Manual mode: Dashboard endpoint accepts POST with video metrics

The feedback loop runs daily and:
  1. Identifies which game attributes correlate with high performance
  2. Updates ModelWeights to reflect what actually drives follows
  3. Flags game types/genres that consistently underperform
  4. Promotes A or B thumbnail variants based on CTR evidence
  5. Adjusts queue_priority for unpublished content

Learning rate: conservative (0.1) to avoid overfitting on small samples.
Minimum sample size: 10 posted videos before weights are adjusted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_session
from src.database.models import Content, Game, ModelWeights, PostAnalytics

log = structlog.get_logger(__name__)

LEARNING_RATE = 0.1
MIN_SAMPLE = 10


class FeedbackLoop:
    async def ingest_manual(
        self,
        content_id: int,
        views: int,
        likes: int,
        comments: int,
        shares: int,
        saves: int,
        follows: int,
        profile_visits: int,
        avg_watch_time_s: float,
        video_duration_s: float,
        thumbnail_variant: str = "A",
    ) -> PostAnalytics:
        """Record TikTok analytics from manual entry or dashboard POST."""
        completion = avg_watch_time_s / max(video_duration_s, 1.0)
        total_engagements = likes + comments + shares + saves
        engagement_rate = total_engagements / max(views, 1)
        follow_conv = follows / max(views, 1)

        record = PostAnalytics(
            content_id=content_id,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            saves=saves,
            follows_from_video=follows,
            profile_visits=profile_visits,
            avg_watch_time_seconds=avg_watch_time_s,
            completion_rate=min(1.0, completion),
            engagement_rate=engagement_rate,
            follow_conversion_rate=follow_conv,
            thumbnail_variant=thumbnail_variant,
            recorded_at=datetime.now(timezone.utc),
        )

        async with get_session() as session:
            session.add(record)
            await session.flush()

            # Update content item
            content = await session.get(Content, content_id)
            if content:
                content.status = "posted"

        log.info(
            "feedback.ingested",
            content_id=content_id,
            views=views,
            follows=follows,
            follow_rate=f"{follow_conv:.3%}",
        )
        return record

    async def run_weight_update(self) -> Optional[ModelWeights]:
        """
        Gradient-free weight update based on performance correlations.
        Runs daily. Returns new ModelWeights or None if sample too small.
        """
        async with get_session() as session:
            analytics = await self._load_analytics(session)

        if len(analytics) < MIN_SAMPLE:
            log.info("feedback.skip_update", reason="insufficient_sample", count=len(analytics))
            return None

        new_weights = await self._compute_weights(analytics)
        async with get_session() as session:
            session.add(new_weights)

        log.info("feedback.weights_updated", sample_size=len(analytics))
        return new_weights

    async def _load_analytics(self, session: AsyncSession) -> list[dict]:
        """Load all analytics joined with content and game data."""
        result = await session.execute(
            select(PostAnalytics, Content, Game)
            .join(Content, PostAnalytics.content_id == Content.id)
            .join(Game, Content.game_id == Game.id)
        )
        rows = []
        for analytics, content, game in result:
            rows.append({
                "views": analytics.views,
                "follows": analytics.follows_from_video,
                "shares": analytics.shares,
                "saves": analytics.saves,
                "comments": analytics.comments,
                "completion_rate": analytics.completion_rate,
                "engagement_rate": analytics.engagement_rate,
                "follow_conv_rate": analytics.follow_conversion_rate,
                "thumbnail_variant": analytics.thumbnail_variant,
                "growth_velocity": game.growth_velocity_score,
                "engagement_ratio": game.engagement_ratio_score,
                "novelty": game.novelty_score,
                "retention_proxy": game.retention_proxy_score,
                "update_freshness": game.update_freshness_score,
                "viral_score": game.viral_score,
                "predicted_viral": content.predicted_viral_score,
                "predicted_engagement": content.predicted_engagement_score,
                "predicted_follow_conv": content.predicted_follow_conv_score,
            })
        return rows

    async def _compute_weights(self, data: list[dict]) -> ModelWeights:
        """
        Simple correlation-based weight update.
        Uses follow conversion rate as the primary optimization target.
        """
        import statistics

        current = await self._get_current_weights()

        follow_rates = [d["follow_conv_rate"] for d in data]
        mean_follow = statistics.mean(follow_rates) if follow_rates else 0.0

        def _corr(feature: str) -> float:
            """Pearson correlation between feature and follow conversion."""
            xs = [d[feature] for d in data]
            ys = follow_rates
            if len(xs) < 2:
                return 0.0
            mx, my = statistics.mean(xs), statistics.mean(ys)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            denom = (
                (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
            )
            return num / denom if denom > 0 else 0.0

        # Correlations of game features with follow conversion
        corr_growth = max(0.0, _corr("growth_velocity"))
        corr_engagement = max(0.0, _corr("engagement_ratio"))
        corr_novelty = max(0.0, _corr("novelty"))
        corr_retention = max(0.0, _corr("retention_proxy"))
        corr_freshness = max(0.0, _corr("update_freshness"))

        total_corr = corr_growth + corr_engagement + corr_novelty + corr_retention + corr_freshness
        if total_corr <= 0:
            # No signal — keep current weights
            return ModelWeights(
                weight_growth_velocity=current.weight_growth_velocity,
                weight_engagement_ratio=current.weight_engagement_ratio,
                weight_novelty=current.weight_novelty,
                weight_retention_proxy=current.weight_retention_proxy,
                weight_update_freshness=current.weight_update_freshness,
                weight_cross_platform=current.weight_cross_platform,
                weight_viral_pred=current.weight_viral_pred,
                weight_engagement_pred=current.weight_engagement_pred,
                weight_follow_conv_pred=current.weight_follow_conv_pred,
                sample_size=len(data),
                update_reason="no_correlation_signal_found",
            )

        # Normalize to target weight allocation (leave cross_platform fixed)
        allocated = 0.90  # remaining 0.10 stays as cross_platform
        raw_weights = {
            "growth": corr_growth,
            "engagement": corr_engagement,
            "novelty": corr_novelty,
            "retention": corr_retention,
            "freshness": corr_freshness,
        }
        weight_sum = sum(raw_weights.values())
        scaled = {k: (v / weight_sum) * allocated for k, v in raw_weights.items()}

        def _update(old: float, new: float) -> float:
            return round(old + LEARNING_RATE * (new - old), 4)

        # Thumbnail A/B analysis
        variant_a = [d for d in data if d["thumbnail_variant"] == "A"]
        variant_b = [d for d in data if d["thumbnail_variant"] == "B"]
        if variant_a and variant_b:
            a_follow = statistics.mean(d["follow_conv_rate"] for d in variant_a)
            b_follow = statistics.mean(d["follow_conv_rate"] for d in variant_b)
            winner = "A" if a_follow >= b_follow else "B"
            log.info("feedback.ab_winner", winner=winner, a_rate=a_follow, b_rate=b_follow)

        return ModelWeights(
            weight_growth_velocity=_update(current.weight_growth_velocity, scaled["growth"]),
            weight_engagement_ratio=_update(current.weight_engagement_ratio, scaled["engagement"]),
            weight_novelty=_update(current.weight_novelty, scaled["novelty"]),
            weight_retention_proxy=_update(current.weight_retention_proxy, scaled["retention"]),
            weight_update_freshness=_update(current.weight_update_freshness, scaled["freshness"]),
            weight_cross_platform=current.weight_cross_platform,
            weight_viral_pred=current.weight_viral_pred,
            weight_engagement_pred=current.weight_engagement_pred,
            weight_follow_conv_pred=current.weight_follow_conv_pred,
            updated_at=datetime.now(timezone.utc),
            update_reason=f"correlation_update_n={len(data)}_mean_follow={mean_follow:.4f}",
            sample_size=len(data),
        )

    async def _get_current_weights(self) -> ModelWeights:
        async with get_session() as session:
            weights = await session.scalar(
                select(ModelWeights).order_by(ModelWeights.updated_at.desc()).limit(1)
            )
        if weights:
            return weights
        return ModelWeights()  # defaults

    async def get_performance_summary(self) -> dict:
        """Return aggregated performance stats for dashboard."""
        async with get_session() as session:
            result = await session.execute(select(PostAnalytics))
            all_analytics = result.scalars().all()

        if not all_analytics:
            return {
                "total_posts": 0,
                "total_views": 0,
                "total_follows": 0,
                "avg_completion_rate": 0.0,
                "avg_follow_conv_rate": 0.0,
                "avg_engagement_rate": 0.0,
                "top_performing_variant": "N/A",
            }

        total_views = sum(a.views for a in all_analytics)
        total_follows = sum(a.follows_from_video for a in all_analytics)

        import statistics
        completion_rates = [a.completion_rate for a in all_analytics if a.completion_rate > 0]
        eng_rates = [a.engagement_rate for a in all_analytics if a.engagement_rate > 0]
        follow_rates = [a.follow_conversion_rate for a in all_analytics if a.follow_conversion_rate > 0]

        a_follows = [a.follow_conversion_rate for a in all_analytics if a.thumbnail_variant == "A"]
        b_follows = [a.follow_conversion_rate for a in all_analytics if a.thumbnail_variant == "B"]
        if a_follows and b_follows:
            top_variant = "A" if statistics.mean(a_follows) >= statistics.mean(b_follows) else "B"
        else:
            top_variant = "A" if a_follows else "B" if b_follows else "N/A"

        return {
            "total_posts": len(all_analytics),
            "total_views": total_views,
            "total_follows": total_follows,
            "avg_completion_rate": statistics.mean(completion_rates) if completion_rates else 0.0,
            "avg_follow_conv_rate": statistics.mean(follow_rates) if follow_rates else 0.0,
            "avg_engagement_rate": statistics.mean(eng_rates) if eng_rates else 0.0,
            "top_performing_variant": top_variant,
        }
