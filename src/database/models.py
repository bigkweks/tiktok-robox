from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Game(Base):
    """A discovered Roblox game with all its metadata and scoring."""
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Roblox identifiers ────────────────────────────────────────────
    universe_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    place_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    creator_name: Mapped[Optional[str]] = mapped_column(String(256))
    creator_id: Mapped[Optional[str]] = mapped_column(String(64))
    genre: Mapped[Optional[str]] = mapped_column(String(64))

    # ── Assets ────────────────────────────────────────────────────────
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(1024))
    icon_url: Mapped[Optional[str]] = mapped_column(String(1024))
    local_thumbnail_path: Mapped[Optional[str]] = mapped_column(String(512))

    # ── Core metrics ──────────────────────────────────────────────────
    visits: Mapped[int] = mapped_column(Integer, default=0)
    active_players: Mapped[int] = mapped_column(Integer, default=0)
    max_players: Mapped[int] = mapped_column(Integer, default=0)
    favorites: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    dislike_count: Mapped[int] = mapped_column(Integer, default=0)
    like_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Roblox timestamps ─────────────────────────────────────────────
    created_at_roblox: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at_roblox: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # ── Velocity tracking (updated each crawl) ────────────────────────
    visits_24h_ago: Mapped[int] = mapped_column(Integer, default=0)
    players_24h_ago: Mapped[int] = mapped_column(Integer, default=0)
    favorites_24h_ago: Mapped[int] = mapped_column(Integer, default=0)
    visit_velocity: Mapped[float] = mapped_column(Float, default=0.0)
    player_velocity: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Viral scoring ─────────────────────────────────────────────────
    viral_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    growth_velocity_score: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_ratio_score: Mapped[float] = mapped_column(Float, default=0.0)
    novelty_score: Mapped[float] = mapped_column(Float, default=0.0)
    retention_proxy_score: Mapped[float] = mapped_column(Float, default=0.0)
    update_freshness_score: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Discovery metadata ────────────────────────────────────────────
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    crawl_count: Mapped[int] = mapped_column(Integer, default=1)

    # ── Status ────────────────────────────────────────────────────────
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    blacklist_reason: Mapped[Optional[str]] = mapped_column(String(256))
    content_generated: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Relationships ─────────────────────────────────────────────────
    crawl_logs: Mapped[list[CrawlLog]] = relationship("CrawlLog", back_populates="game", cascade="all, delete-orphan")
    content_items: Mapped[list[Content]] = relationship("Content", back_populates="game", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_games_viral_score_blacklisted", "viral_score", "is_blacklisted"),
        Index("ix_games_content_generated", "content_generated", "viral_score"),
    )

    def __repr__(self) -> str:
        return f"<Game {self.universe_id} '{self.name}' score={self.viral_score:.3f}>"


class CrawlLog(Base):
    """Point-in-time snapshot of game metrics for velocity calculations."""
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)

    visits: Mapped[int] = mapped_column(Integer, default=0)
    active_players: Mapped[int] = mapped_column(Integer, default=0)
    favorites: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    dislike_count: Mapped[int] = mapped_column(Integer, default=0)

    game: Mapped[Game] = relationship("Game", back_populates="crawl_logs")

    __table_args__ = (Index("ix_crawl_logs_game_time", "game_id", "crawled_at"),)


class Content(Base):
    """A generated content package ready for TikTok posting."""
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("games.id"), nullable=False)

    # ── Generated assets ──────────────────────────────────────────────
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(512))
    thumbnail_a_path: Mapped[Optional[str]] = mapped_column(String(512))
    thumbnail_b_path: Mapped[Optional[str]] = mapped_column(String(512))
    video_path: Mapped[Optional[str]] = mapped_column(String(512))
    audio_path: Mapped[Optional[str]] = mapped_column(String(512))

    # ── Rating ────────────────────────────────────────────────────────
    rating_score: Mapped[Optional[float]] = mapped_column(Float)
    rating_label: Mapped[Optional[str]] = mapped_column(String(64))
    rating_verdict: Mapped[Optional[str]] = mapped_column(Text)
    rating_breakdown: Mapped[Optional[str]] = mapped_column(Text)  # JSON

    # ── Captions / copy ───────────────────────────────────────────────
    hook_text: Mapped[Optional[str]] = mapped_column(Text)
    carousel_caption: Mapped[Optional[str]] = mapped_column(Text)
    description_a: Mapped[Optional[str]] = mapped_column(Text)
    description_b: Mapped[Optional[str]] = mapped_column(Text)
    hashtags: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    tts_script: Mapped[Optional[str]] = mapped_column(Text)

    # ── Viral predictions ─────────────────────────────────────────────
    predicted_viral_score: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_follow_conv_score: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_novelty_score: Mapped[float] = mapped_column(Float, default=0.0)
    queue_priority: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    # ── Queue / posting status ─────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # pending → approved → scheduled → posted | rejected
    active_variant: Mapped[str] = mapped_column(String(4), default="A")
    scheduled_post_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    tiktok_video_id: Mapped[Optional[str]] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # ── Relationships ─────────────────────────────────────────────────
    game: Mapped[Game] = relationship("Game", back_populates="content_items")
    analytics: Mapped[list[PostAnalytics]] = relationship("PostAnalytics", back_populates="content", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_content_status_priority", "status", "queue_priority"),)

    def __repr__(self) -> str:
        return f"<Content {self.id} game={self.game_id} status={self.status} priority={self.queue_priority:.3f}>"


class PostAnalytics(Base):
    """TikTok performance metrics for a posted video."""
    __tablename__ = "post_analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content.id"), nullable=False)
    tiktok_video_id: Mapped[Optional[str]] = mapped_column(String(128))

    # ── Reach ─────────────────────────────────────────────────────────
    views: Mapped[int] = mapped_column(Integer, default=0)
    unique_viewers: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)

    # ── Engagement ────────────────────────────────────────────────────
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    follows_from_video: Mapped[int] = mapped_column(Integer, default=0)
    profile_visits: Mapped[int] = mapped_column(Integer, default=0)

    # ── Watch metrics ─────────────────────────────────────────────────
    total_watch_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    avg_watch_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    completion_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Derived KPIs ──────────────────────────────────────────────────
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    follow_conversion_rate: Mapped[float] = mapped_column(Float, default=0.0)

    thumbnail_variant: Mapped[str] = mapped_column(String(4), default="A")
    hours_since_post: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    content: Mapped[Content] = relationship("Content", back_populates="analytics")

    __table_args__ = (
        Index("ix_post_analytics_content_id", "content_id"),
        Index("ix_post_analytics_recorded_at", "recorded_at"),
        Index("ix_post_analytics_variant", "thumbnail_variant"),
    )


class CarouselPost(Base):
    """
    A 6-slide photo carousel (the proven viral format).
    Groups 5 rated games into a single TikTok photo carousel post.
    """
    __tablename__ = "carousel_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Series metadata
    edition: Mapped[str] = mapped_column(String(64), default="Friends edition")
    part_number: Mapped[int] = mapped_column(Integer, default=1)

    # Ordered JSON list of game IDs (5 games)
    game_ids: Mapped[str] = mapped_column(Text)  # JSON [id1, id2, ...]

    # Paths to the 6 slide images (JSON list, slide 0 = title)
    slide_paths: Mapped[Optional[str]] = mapped_column(Text)  # JSON list

    # TikTok caption (targets search queries like "roblox games to play")
    caption: Mapped[Optional[str]] = mapped_column(Text)
    hashtags: Mapped[Optional[str]] = mapped_column(Text)  # JSON

    # Queue status
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    scheduled_post_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # ── Mandatory approval (three-reviewer panel) ─────────────────────
    # Only carousels that survive review are ever persisted, so a row's mere
    # existence means it passed — these fields record HOW well it passed.
    review_score: Mapped[Optional[float]] = mapped_column(Float)   # Final Quality Score 0–100
    review_summary: Mapped[Optional[str]] = mapped_column(Text)    # JSON: reviewers + dimensions

    # ── Generated text (persisted for cross-post duplicate detection) ──
    # The cover hook and per-slide captions are stored so future generations can
    # reject near-duplicates of what already shipped (the same followers see
    # consecutive parts, so repetition is the #1 "this is a bot" tell).
    cover_hook: Mapped[Optional[str]] = mapped_column(Text)
    slide_captions: Mapped[Optional[str]] = mapped_column(Text)    # JSON list

    # ── Carousel-centric identity ──────────────────────────────────────
    # A stable per-generation id (distinct from the row id) so analytics and the
    # learning corpus key on the CAROUSEL, not the underlying games.
    generation_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    min_game_rating: Mapped[Optional[float]] = mapped_column(Float)  # lowest score in the batch

    # ── Lifecycle flags (carousel-centric analytics) ───────────────────
    exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class ModelWeights(Base):
    """Learnable scoring weights updated by the analytics feedback loop."""
    __tablename__ = "model_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Discovery weights ─────────────────────────────────────────────
    weight_growth_velocity: Mapped[float] = mapped_column(Float, default=0.30)
    weight_engagement_ratio: Mapped[float] = mapped_column(Float, default=0.20)
    weight_novelty: Mapped[float] = mapped_column(Float, default=0.15)
    weight_retention_proxy: Mapped[float] = mapped_column(Float, default=0.15)
    weight_update_freshness: Mapped[float] = mapped_column(Float, default=0.10)
    weight_cross_platform: Mapped[float] = mapped_column(Float, default=0.10)

    # ── Queue weights ─────────────────────────────────────────────────
    weight_viral_pred: Mapped[float] = mapped_column(Float, default=0.40)
    weight_engagement_pred: Mapped[float] = mapped_column(Float, default=0.30)
    weight_follow_conv_pred: Mapped[float] = mapped_column(Float, default=0.30)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    update_reason: Mapped[Optional[str]] = mapped_column(Text)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
