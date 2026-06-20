"""
Content queue manager.

Maintains a prioritized queue of 100+ future posts. Priority is computed
as a weighted combination of viral predictions, refreshed on each scoring
update. The queue auto-fills when it drops below a threshold.

Posting schedule: TARGET_DAILY_POSTS posts per day, spread across optimal
TikTok posting windows (6am, 12pm, 7pm in the account's target timezone).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select

from src.database.connection import get_session
from src.database.models import Content, Game, ModelWeights

log = structlog.get_logger(__name__)

# Optimal posting times (hour in 24h, local time)
# Based on Roblox audience demographics (primarily 13-24) and general TikTok data
POSTING_HOURS = [6, 12, 19]  # 6am, 12pm, 7pm


class ContentQueue:
    async def queue_size(self) -> int:
        async with get_session() as session:
            result = await session.scalar(
                select(func.count(Content.id)).where(Content.status == "approved")
            )
            return result or 0

    async def pending_size(self) -> int:
        async with get_session() as session:
            result = await session.scalar(
                select(func.count(Content.id)).where(Content.status == "pending")
            )
            return result or 0

    async def get_next_items(self, limit: int = 10) -> list[Content]:
        """Return top-priority approved items not yet scheduled."""
        async with get_session() as session:
            result = await session.execute(
                select(Content)
                .where(Content.status == "approved")
                .where(Content.scheduled_post_time == None)  # noqa: E711
                .order_by(Content.queue_priority.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def schedule_posts(self, days_ahead: int = 14) -> int:
        """
        Assign scheduled_post_time to approved items.
        Spreads posts across POSTING_HOURS over the next days_ahead days.
        Returns the number of posts scheduled.
        """
        items = await self.get_next_items(limit=days_ahead * len(POSTING_HOURS))
        if not items:
            return 0

        now = datetime.now(timezone.utc)
        # Find the next posting slot
        next_slot = self._next_post_slot(now)
        scheduled = 0

        async with get_session() as session:
            for item in items:
                fresh = await session.get(Content, item.id)
                if fresh and fresh.scheduled_post_time is None:
                    fresh.scheduled_post_time = next_slot
                    next_slot = self._advance_slot(next_slot)
                    scheduled += 1

        log.info("queue.scheduled", count=scheduled)
        return scheduled

    async def mark_posted(self, content_id: int, tiktok_video_id: Optional[str] = None) -> None:
        async with get_session() as session:
            item = await session.get(Content, content_id)
            if item:
                item.status = "posted"
                item.posted_at = datetime.now(timezone.utc)
                if tiktok_video_id:
                    item.tiktok_video_id = tiktok_video_id

    async def approve_item(self, content_id: int) -> None:
        async with get_session() as session:
            item = await session.get(Content, content_id)
            if item:
                item.status = "approved"

    async def reject_item(self, content_id: int, reason: str = "") -> None:
        async with get_session() as session:
            item = await session.get(Content, content_id)
            if item:
                item.status = "rejected"

    async def reprioritize(self) -> None:
        """Recompute queue_priority for all pending/approved items using current model weights."""
        async with get_session() as session:
            weights = await session.scalar(
                select(ModelWeights).order_by(ModelWeights.updated_at.desc()).limit(1)
            )
            w_viral = weights.weight_viral_pred if weights else 0.40
            w_engage = weights.weight_engagement_pred if weights else 0.30
            w_follow = weights.weight_follow_conv_pred if weights else 0.30

            result = await session.execute(
                select(Content).where(Content.status.in_(["pending", "approved"]))
            )
            items = result.scalars().all()
            for item in items:
                item.queue_priority = (
                    w_viral * item.predicted_viral_score
                    + w_engage * item.predicted_engagement_score
                    + w_follow * item.predicted_follow_conv_score
                )

        log.info("queue.reprioritized", count=len(items))

    async def get_due_for_posting(self) -> list[Content]:
        """Return items whose scheduled_post_time has passed."""
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            result = await session.execute(
                select(Content)
                .where(Content.status == "approved")
                .where(Content.scheduled_post_time <= now)
                .order_by(Content.scheduled_post_time.asc())
            )
            return list(result.scalars().all())

    async def get_dashboard_stats(self) -> dict:
        async with get_session() as session:
            total_games = await session.scalar(select(func.count(Game.id)))
            total_content = await session.scalar(select(func.count(Content.id)))
            approved = await session.scalar(
                select(func.count(Content.id)).where(Content.status == "approved")
            )
            posted = await session.scalar(
                select(func.count(Content.id)).where(Content.status == "posted")
            )
            pending = await session.scalar(
                select(func.count(Content.id)).where(Content.status == "pending")
            )
            top_game = await session.scalar(
                select(Game.name).order_by(Game.viral_score.desc()).limit(1)
            )
            return {
                "total_games": total_games or 0,
                "total_content": total_content or 0,
                "queue_size": approved or 0,
                "posted": posted or 0,
                "pending": pending or 0,
                "top_game": top_game or "N/A",
            }

    @staticmethod
    def _next_post_slot(after: datetime) -> datetime:
        for hour in POSTING_HOURS:
            candidate = after.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > after:
                return candidate
        # All today's slots passed — first slot tomorrow
        tomorrow = after + timedelta(days=1)
        return tomorrow.replace(hour=POSTING_HOURS[0], minute=0, second=0, microsecond=0)

    @staticmethod
    def _advance_slot(slot: datetime) -> datetime:
        hour_idx = next((i for i, h in enumerate(POSTING_HOURS) if h == slot.hour), None)
        if hour_idx is not None and hour_idx + 1 < len(POSTING_HOURS):
            return slot.replace(hour=POSTING_HOURS[hour_idx + 1])
        return (slot + timedelta(days=1)).replace(hour=POSTING_HOURS[0])
