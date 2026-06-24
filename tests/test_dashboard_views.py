"""
Tests for dashboard view logic that is computed in templates:

  - the 10K-follower projection now uses real follows-per-post, not an
    assumed views-per-video constant;
  - the analytics page prefills + confirms the Content ID when deep-linked
    from a posted content card.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "api" / "templates"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                       autoescape=select_autoescape())


class _Req:
    def __init__(self, path: str):
        self.url = type("U", (), {"path": path})()


def _perf(**over):
    base = dict(
        total_posts=0, total_views=0, total_follows=0,
        avg_completion_rate=0.0, avg_follow_conv_rate=0.0,
        avg_engagement_rate=0.0, avg_follows_per_post=0.0,
        top_performing_variant="A",
    )
    base.update(over)
    return base


def _stats(**over):
    base = dict(total_games=0, queue_size=0, pending=0, posted=0,
                total_views=0, top_game="—")
    base.update(over)
    return base


def test_goal_projection_uses_per_post_follows():
    # 200 follows over 10 posts => 20 follows/post => (10000-200)/20 = 490 videos.
    html = _env().get_template("index.html").render(
        request=_Req("/"),
        stats=_stats(),
        perf=_perf(total_posts=10, total_follows=200, avg_follows_per_post=20.0),
        now=datetime(2026, 6, 24, 12, 0),
    )
    assert "490 more videos" in html


def test_goal_projection_handles_posts_without_follows():
    html = _env().get_template("index.html").render(
        request=_Req("/"),
        stats=_stats(),
        perf=_perf(total_posts=5, total_follows=0, avg_follows_per_post=0.0),
        now=datetime(2026, 6, 24, 12, 0),
    )
    assert "No follows logged yet" in html
    # Must not divide by zero / emit a bogus huge number.
    assert "more videos" not in html


def test_goal_projection_before_first_post():
    html = _env().get_template("index.html").render(
        request=_Req("/"),
        stats=_stats(),
        perf=_perf(total_posts=0),
        now=datetime(2026, 6, 24, 12, 0),
    )
    assert "Post first video to project timeline" in html


def test_analytics_prefill_confirms_game_and_value():
    html = _env().get_template("analytics.html").render(
        request=_Req("/analytics"),
        perf=_perf(),
        recent=[],
        prefill_content_id=42,
        prefill_game="Brookhaven RP",
    )
    assert 'value="42"' in html
    assert "Brookhaven RP" in html
    assert "Content #42" in html
    # focus script only emitted when prefilled
    assert "scrollIntoView" in html


def test_analytics_without_prefill_shows_help_not_script():
    html = _env().get_template("analytics.html").render(
        request=_Req("/analytics"),
        perf=_perf(),
        recent=[],
        prefill_content_id=None,
        prefill_game=None,
    )
    assert "Content Queue" in html      # the help text
    assert "scrollIntoView" not in html  # no auto-focus without a target
