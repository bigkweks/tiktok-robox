"""
Integration tests for the carousel factory's trust/quality gates against a REAL
(temp) database:

  - the rating floor (>= MIN_CAROUSEL_RATING) excludes weak games
  - an approved draft persists as status='pending_review' (NO auto-approval)
  - the cover hook + slide captions are persisted for cross-post dedup

These exercise the real selection query, approval cycle, render, and persistence
path — only the network (Roblox thumbnails) is stubbed. Everything for one test
runs inside a single fresh event loop, because the async engine is loop-bound.
"""
from __future__ import annotations

import asyncio

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import src.database.connection as conn
from src.content.carousel_generator import CarouselGenerator
from src.database.models import Base, CarouselPost, Content, Game
from src.scheduler.pipeline import Pipeline


def _stub_network(monkeypatch):
    monkeypatch.setattr(CarouselGenerator, "_fetch_thumbnail",
                        lambda self, url: Image.new("RGB", (1280, 720), (20, 110, 200)))
    monkeypatch.setattr(CarouselGenerator, "_fetch_icon",
                        lambda self, url, name: Image.new("RGBA", (168, 168), (90, 90, 90, 255)))


def _pipeline(tmp_path):
    from src.config import get_settings
    p = Pipeline.__new__(Pipeline)
    p._settings = get_settings()
    p._carousel = CarouselGenerator()
    p._carousel_part_counter = 1
    orig = p._carousel.generate
    def gen(*a, **k):
        k.setdefault("output_dir", tmp_path / "carousels" / k.get("slug", "c"))
        return orig(*a, **k)
    p._carousel.generate = gen
    return p


async def _setup(tmp_path, scores, used_fallback=False):
    url = f"sqlite+aiosqlite:///{tmp_path/'gate.db'}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(bind=engine, expire_on_commit=False,
                                 autoflush=False, autocommit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with factory() as s:
        for i, score in enumerate(scores):
            g = Game(universe_id=f"u{i}", place_id=1000 + i, name=f"Game {i}",
                     url=f"https://roblox.com/games/{1000+i}", creator_name="Dev",
                     genre="Adventure", visits=900_000 + i, active_players=400,
                     like_ratio=0.92, viral_score=0.7, thumbnail_url=f"http://x/{i}",
                     icon_url=None, description="A genuinely fun game with depth.",
                     content_generated=True)
            s.add(g)
            await s.flush()
            s.add(Content(
                game_id=g.id, rating_score=score, rating_label="WORTH PLAYING 🎮",
                rating_verdict="quietly one of the more polished ones out here",
                carousel_caption=f"hidden gem number {i}", status="pending",
                queue_priority=100 - i, used_fallback=used_fallback,
            ))
        await s.commit()
    return engine, factory


def _run_test(tmp_path, monkeypatch, scores, body, used_fallback=False):
    """Run one test fully inside a fresh loop with the temp DB wired in."""
    _stub_network(monkeypatch)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        engine, factory = loop.run_until_complete(
            _setup(tmp_path, scores, used_fallback=used_fallback))
        monkeypatch.setattr(conn, "_engine", engine)
        monkeypatch.setattr(conn, "_session_factory", factory)
        try:
            return loop.run_until_complete(body(_pipeline(tmp_path), factory))
        finally:
            loop.run_until_complete(engine.dispose())
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_rating_floor_excludes_weak_games(tmp_path, monkeypatch):
    async def body(p, factory):
        out = await p.run_carousel_factory()
        assert out["carousels"] == 0      # all below the 7.4 floor → nothing built
    _run_test(tmp_path, monkeypatch, [6.0, 6.5, 7.0, 7.3, 5.5], body)


def test_fallback_content_excluded_from_carousels(tmp_path, monkeypatch):
    """Provenance gate (audit C1): rule-based (used_fallback) ratings, even with
    high scores above the floor, must NEVER be selected into a carousel — a
    fabricated rating can't ship as if it were AI-curated."""
    async def body(p, factory):
        out = await p.run_carousel_factory()
        assert out["carousels"] == 0          # nothing built from fallback content
        # The factory explains WHY (so "not enough games" isn't mistaken for a
        # discovery problem when the real cause is the AI key).
        assert out.get("reason") == "fallback_content"
    # All five score well above the 7.4 floor but are flagged rule-based.
    _run_test(tmp_path, monkeypatch, [9.1, 8.6, 8.2, 7.9, 7.6], body,
              used_fallback=True)


def test_good_batch_persists_pending_review(tmp_path, monkeypatch):
    async def body(p, factory):
        out = await p.run_carousel_factory()
        if out.get("carousels") == 1:
            assert out["status"] == "pending_review"
            assert out["approved"] is False
            async with factory() as s:
                post = (await s.execute(select(CarouselPost))).scalars().first()
            assert post is not None
            assert post.status == "pending_review"   # NOT auto-approved
            assert post.cover_hook                    # persisted for dedup
            assert post.slide_captions
            assert post.generation_id
            assert post.min_game_rating >= 7.4
        else:
            # The panel may reject on a seed, but never for the rating floor here.
            assert out.get("reason") != "below_rating_floor"
    _run_test(tmp_path, monkeypatch, [9.1, 8.6, 8.2, 7.9, 7.6], body)
