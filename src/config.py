from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── AI ──────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = Field(default="", description="Required for content generation")
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./tiktok_robox.db"

    # ── Pipeline ─────────────────────────────────────────────────────────
    DISCOVERY_INTERVAL_HOURS: int = 4
    MAX_QUEUE_SIZE: int = 150
    TARGET_DAILY_POSTS: int = 3
    MIN_VIRAL_SCORE: float = 0.45

    # ── Content generation ───────────────────────────────────────────────
    THUMBNAIL_VARIANTS: int = 2
    VIDEO_FPS: int = 30
    VIDEO_WIDTH: int = 1080
    VIDEO_HEIGHT: int = 1920
    TTS_PROVIDER: Literal["gtts", "elevenlabs"] = "gtts"
    ELEVENLABS_API_KEY: str = ""

    # ── Branding ─────────────────────────────────────────────────────────
    CHANNEL_NAME: str = "RobloxGems"
    CHANNEL_HANDLE: str = "@robloxgems"
    BRAND_PRIMARY_COLOR: str = "#6C63FF"
    BRAND_SECONDARY_COLOR: str = "#FF6584"
    BRAND_ACCENT_COLOR: str = "#FFD700"

    # ── Scoring weights ───────────────────────────────────────────────────
    WEIGHT_GROWTH_VELOCITY: float = 0.30
    WEIGHT_ENGAGEMENT_RATIO: float = 0.20
    WEIGHT_NOVELTY: float = 0.15
    WEIGHT_RETENTION_PROXY: float = 0.15
    WEIGHT_UPDATE_FRESHNESS: float = 0.10
    WEIGHT_CROSS_PLATFORM: float = 0.10

    # ── Paths ─────────────────────────────────────────────────────────────
    OUTPUT_DIR: str = "output"
    ASSETS_DIR: str = "assets"

    # ── Dashboard ─────────────────────────────────────────────────────────
    DASHBOARD_HOST: str = "0.0.0.0"
    DASHBOARD_PORT: int = 8000
    DASHBOARD_SECRET_KEY: str = "change-this-in-production"

    @field_validator("WEIGHT_GROWTH_VELOCITY", "WEIGHT_ENGAGEMENT_RATIO",
                     "WEIGHT_NOVELTY", "WEIGHT_RETENTION_PROXY",
                     "WEIGHT_UPDATE_FRESHNESS", "WEIGHT_CROSS_PLATFORM")
    @classmethod
    def validate_weight(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Weights must be between 0.0 and 1.0")
        return v

    def ensure_dirs(self) -> None:
        for subdir in ["thumbnails", "videos", "screenshots", "audio"]:
            Path(self.OUTPUT_DIR, subdir).mkdir(parents=True, exist_ok=True)
        Path(self.ASSETS_DIR, "fonts").mkdir(parents=True, exist_ok=True)
        Path(self.ASSETS_DIR, "branding").mkdir(parents=True, exist_ok=True)

    def hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        h = hex_color.lstrip("#")
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    @property
    def brand_primary_rgb(self) -> tuple[int, int, int]:
        return self.hex_to_rgb(self.BRAND_PRIMARY_COLOR)

    @property
    def brand_secondary_rgb(self) -> tuple[int, int, int]:
        return self.hex_to_rgb(self.BRAND_SECONDARY_COLOR)

    @property
    def brand_accent_rgb(self) -> tuple[int, int, int]:
        return self.hex_to_rgb(self.BRAND_ACCENT_COLOR)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
