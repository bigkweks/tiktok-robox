"""Tests for content generation (unit-testable parts only — no API calls)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.content.rating_engine import RatingEngine, RatingResult, _get_label
from src.content.description_engine import DescriptionEngine, HASHTAG_TIERS


# ── Rating label tests ──────────────────────────────────────────────────

def test_rating_labels_correct():
    assert "GEM" in _get_label(9.5)
    assert "GOOD" in _get_label(8.0) or "ACTUALLY" in _get_label(8.0)
    assert "WORTH" in _get_label(7.0) or "PLAYING" in _get_label(7.0)
    assert "HYPED" in _get_label(4.0) or "OVERHYPED" in _get_label(4.0)
    assert "SKIP" in _get_label(1.0)


def test_score_color_by_rating():
    result = RatingResult(score=9.5, label="HIDDEN GEM 💎", verdict="test", breakdown={}, tts_script="", controversy_angle="")
    r, g, b = result.score_color
    assert g > r and g > b  # green dominant for 9.5

    result_low = RatingResult(score=3.0, label="SKIP IT ❌", verdict="test", breakdown={}, tts_script="", controversy_angle="")
    r2, g2, b2 = result_low.score_color
    assert r2 > g2 and r2 > b2  # red dominant for 3.0


def test_fallback_rating_within_bounds():
    engine = RatingEngine.__new__(RatingEngine)
    engine._settings = MagicMock()
    engine._settings.ANTHROPIC_MODEL = "test"

    result = engine._fallback_rating("Test Game", 1_000_000, 0.7)
    assert 0.0 <= result.score <= 10.0
    assert result.label
    assert result.tts_script
    # The fallback verdict is burned onto the game slide, so it must read like a
    # player, not a corporate metric ("shows strong engagement metrics").
    from src.content.caption_utils import has_ai_tell
    assert not has_ai_tell(result.verdict)
    assert "engagement metrics" not in result.verdict.lower()
    # Score-tiered + name-hashed: different games don't all get the same line.
    verdicts = {engine._fallback_rating(n, 1_000_000, 0.7).verdict
                for n in ("Alpha", "Bravo", "Charlie", "Delta")}
    assert len(verdicts) >= 2


# ── Description tests ─────────────────────────────────────────────────

def test_hashtag_count_within_range():
    engine = DescriptionEngine.__new__(DescriptionEngine)
    tags = engine._build_hashtags("horror", "Roblox Horror Game")
    assert 6 <= len(tags) <= 12


def test_hashtag_includes_brand():
    engine = DescriptionEngine.__new__(DescriptionEngine)
    tags = engine._build_hashtags("adventure", "My Adventure")
    tag_str = " ".join(tags)
    # Should always contain a brand hashtag
    assert any(bt in tag_str for bt in HASHTAG_TIERS["brand"])


def test_fallback_captions_not_empty():
    engine = DescriptionEngine.__new__(DescriptionEngine)
    cap_a = engine._fallback_a("Brookhaven", 9.2, "HIDDEN GEM 💎", "500K")
    cap_b = engine._fallback_b("Brookhaven", 9.2, "500K")
    assert len(cap_a) > 30
    assert len(cap_b) > 30


def test_visit_formatting():
    engine = DescriptionEngine.__new__(DescriptionEngine)
    assert engine._format_visits(500_000_000) == "500.0M"
    assert engine._format_visits(1_500_000_000) == "1.5B"
    assert engine._format_visits(50_000) == "50K"
    assert engine._format_visits(999) == "999"
