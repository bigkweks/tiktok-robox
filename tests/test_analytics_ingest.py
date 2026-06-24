"""
Regression tests for analytics ingestion validation.

Motivating bug: ingest_manual accepted any content_id and wrote a PostAnalytics
row even when no such Content existed. That orphan row is excluded from every
join, so the user's logged metrics silently vanished. Ingestion must reject a
non-existent content_id instead.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analytics.feedback_loop import FeedbackLoop


class _FakeSessionCtx:
    """Minimal async context manager standing in for get_session()."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _session(get_return):
    session = MagicMock()
    session.get = AsyncMock(return_value=get_return)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_ingest_rejects_missing_content():
    fb = FeedbackLoop()
    session = _session(get_return=None)  # content lookup returns nothing
    with patch("src.analytics.feedback_loop.get_session",
               return_value=_FakeSessionCtx(session)):
        with pytest.raises(ValueError):
            await fb.ingest_manual(
                content_id=999999, views=1000, likes=10, comments=2, shares=1,
                saves=1, follows=5, profile_visits=0, avg_watch_time_s=10.0,
                video_duration_s=20.0,
            )
    # No orphan analytics row may be written when the content does not exist.
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_accepts_existing_content_and_marks_posted():
    fb = FeedbackLoop()
    content = MagicMock()
    content.status = "approved"
    session = _session(get_return=content)
    with patch("src.analytics.feedback_loop.get_session",
               return_value=_FakeSessionCtx(session)):
        record = await fb.ingest_manual(
            content_id=1, views=1000, likes=50, comments=5, shares=10, saves=8,
            follows=20, profile_visits=3, avg_watch_time_s=12.0,
            video_duration_s=20.0, thumbnail_variant="B",
        )
    session.add.assert_called_once()
    assert content.status == "posted"
    # Derived KPIs computed correctly.
    assert record.follow_conversion_rate == pytest.approx(20 / 1000)
    assert record.completion_rate == pytest.approx(12.0 / 20.0)
    assert record.thumbnail_variant == "B"
