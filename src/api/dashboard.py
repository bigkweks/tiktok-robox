"""
FastAPI dashboard.

Provides:
  - Content queue review & approval UI
  - Manual analytics entry
  - Discovery stats
  - Pipeline health monitoring
  - Analytics performance charts
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware

from src.logging_config import configure_logging as _configure_logging
_configure_logging()

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import desc, select

from src.analytics.feedback_loop import FeedbackLoop
from src.config import get_settings
from src.database.connection import get_session, init_db
from src.database.models import CarouselPost, Content, CrawlLog, Game, PostAnalytics
from src.queue.content_queue import ContentQueue
from src.scheduler.pipeline import Pipeline

log = structlog.get_logger(__name__)

app = FastAPI(title="TikTok Robox Dashboard", version="1.0.0")
app.add_middleware(GZipMiddleware, minimum_size=500)

_settings = get_settings()
_queue = ContentQueue()
_feedback = FeedbackLoop()
_pipeline: Optional[Pipeline] = None

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

output_dir = Path(_settings.OUTPUT_DIR)
if output_dir.exists():
    app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")


@app.on_event("startup")
async def startup():
    global _pipeline
    await init_db()
    _settings.ensure_dirs()
    _pipeline = Pipeline()
    await _pipeline.start()
    log.info("dashboard.started")


@app.on_event("shutdown")
async def shutdown():
    if _pipeline:
        await _pipeline.stop()


# ── Pages ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Run both stat queries concurrently
    stats, perf = await asyncio.gather(
        _queue.get_dashboard_stats(),
        _feedback.get_performance_summary(),
    )
    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "perf": perf,
        "now": datetime.utcnow(),
    })


@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request, status: str = "pending"):
    async with get_session() as session:
        result = await session.execute(
            select(Content, Game)
            .join(Game, Content.game_id == Game.id)
            .where(Content.status == status)
            .order_by(Content.queue_priority.desc())
            .limit(50)
        )
        items = [(c, g) for c, g in result]

    return templates.TemplateResponse("queue.html", {
        "request": request,
        "items": items,
        "status": status,
        "statuses": ["pending", "approved", "posted", "rejected"],
    })


@app.get("/games", response_class=HTMLResponse)
async def games_page(request: Request, sort: str = "viral_score"):
    async with get_session() as session:
        sort_col = getattr(Game, sort, Game.viral_score)
        result = await session.execute(
            select(Game)
            .where(Game.is_blacklisted == False)  # noqa: E712
            .order_by(desc(sort_col))
            .limit(100)
        )
        games = result.scalars().all()

    return templates.TemplateResponse("games.html", {
        "request": request,
        "games": games,
        "sort": sort,
    })


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, content_id: Optional[int] = None):
    perf = await _feedback.get_performance_summary()
    async with get_session() as session:
        result = await session.execute(
            select(PostAnalytics, Content, Game)
            .join(Content, PostAnalytics.content_id == Content.id)
            .join(Game, Content.game_id == Game.id)
            .order_by(PostAnalytics.recorded_at.desc())
            .limit(50)
        )
        recent = [(a, c, g) for a, c, g in result]

        # Optional deep-link target: prefill the form for a specific post and
        # show which game it is, so the Content ID is never guessed.
        prefill_game = None
        if content_id is not None:
            prefill_game = await session.scalar(
                select(Game.name)
                .join(Content, Content.game_id == Game.id)
                .where(Content.id == content_id)
            )

    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "perf": perf,
        "recent": recent,
        "prefill_content_id": content_id,
        "prefill_game": prefill_game,
    })


@app.get("/content/{content_id}", response_class=HTMLResponse)
async def content_detail(request: Request, content_id: int):
    # Single joined query instead of two separate gets
    async with get_session() as session:
        result = await session.execute(
            select(Content, Game)
            .join(Game, Content.game_id == Game.id)
            .where(Content.id == content_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(404, "Content not found")
        content, game = row

    hashtags: list = []
    if content.hashtags:
        try:
            hashtags = json.loads(content.hashtags)
        except Exception:
            pass

    breakdown: dict = {}
    if content.rating_breakdown:
        try:
            breakdown = json.loads(content.rating_breakdown)
        except Exception:
            pass

    return templates.TemplateResponse("content_detail.html", {
        "request": request,
        "content": content,
        "game": game,
        "hashtags": hashtags,
        "breakdown": breakdown,
        "caption_a": f"{content.description_a}\n\n{' '.join(hashtags)}" if hashtags else content.description_a,
        "caption_b": f"{content.description_b}\n\n{' '.join(hashtags)}" if hashtags else content.description_b,
    })


# ── Actions ───────────────────────────────────────────────────────────

@app.post("/content/{content_id}/approve")
async def approve_content(content_id: int):
    await _queue.approve_item(content_id)
    return {"status": "approved", "content_id": content_id}


@app.post("/content/{content_id}/reject")
async def reject_content(content_id: int):
    await _queue.reject_item(content_id)
    return {"status": "rejected", "content_id": content_id}


@app.post("/content/{content_id}/mark-posted")
async def mark_posted(content_id: int, tiktok_id: str = Form(default="")):
    await _queue.mark_posted(content_id, tiktok_video_id=tiktok_id or None)
    return {"status": "posted", "content_id": content_id}


@app.post("/pipeline/run-discovery")
async def trigger_discovery():
    if _pipeline:
        stats = await _pipeline.run_discovery()
        return {"status": "complete", "job": "discovery", **stats}
    return {"status": "error", "message": "Pipeline not initialized"}


@app.post("/pipeline/run-content")
async def trigger_content(background_tasks: BackgroundTasks):
    if _pipeline:
        background_tasks.add_task(_pipeline.run_content_factory)
        return {"status": "started", "job": "content_factory"}
    return {"status": "error", "message": "Pipeline not initialized"}


@app.post("/pipeline/run-carousel")
async def trigger_carousel(background_tasks: BackgroundTasks):
    if _pipeline:
        result = await _pipeline.run_carousel_factory()
        return result
    return {"status": "error", "message": "Pipeline not initialized"}


# ── Carousel pages ────────────────────────────────────────────────────

@app.get("/carousels", response_class=HTMLResponse)
async def carousels_page(request: Request):
    async with get_session() as session:
        result = await session.execute(
            select(CarouselPost).order_by(CarouselPost.created_at.desc()).limit(20)
        )
        posts = result.scalars().all()

    # Attach helper properties for template
    enriched = []
    for p in posts:
        slide_paths_list = []
        try:
            slide_paths_list = json.loads(p.slide_paths or "[]")
        except Exception:
            pass
        hashtags_list = []
        try:
            hashtags_list = json.loads(p.hashtags or "[]")
        except Exception:
            pass
        # Public URLs (served via the /output mount) for the one-step save.
        prefix = _settings.OUTPUT_DIR.rstrip("/") + "/"
        slide_urls = [
            "/output/" + (sp[len(prefix):] if sp.startswith(prefix) else sp)
            for sp in slide_paths_list if sp
        ]
        enriched.append({
            "id": p.id,
            "edition": p.edition,
            "part_number": p.part_number,
            "status": p.status,
            "caption": p.caption,
            "created_at": p.created_at,
            "slide_paths_list": slide_paths_list,
            "slide_urls": slide_urls,
            "hashtags_str": " ".join(hashtags_list),
        })

    return templates.TemplateResponse("carousels.html", {
        "request": request,
        "carousels": enriched,
        "settings": _settings,
    })


@app.post("/carousel/{carousel_id}/approve")
async def approve_carousel(carousel_id: int):
    async with get_session() as session:
        post = await session.get(CarouselPost, carousel_id)
        if post:
            post.status = "approved"
    return {"status": "approved"}


@app.post("/carousel/{carousel_id}/reject")
async def reject_carousel(carousel_id: int):
    async with get_session() as session:
        post = await session.get(CarouselPost, carousel_id)
        if post:
            post.status = "rejected"
    return {"status": "rejected"}


@app.post("/carousel/{carousel_id}/mark-posted")
async def mark_carousel_posted(carousel_id: int):
    """Mark a carousel as posted after you've uploaded it to TikTok yourself."""
    from datetime import timezone
    async with get_session() as session:
        post = await session.get(CarouselPost, carousel_id)
        if not post:
            raise HTTPException(404, "Carousel not found")
        post.status = "posted"
        post.posted_at = datetime.now(timezone.utc)
    return {"status": "posted", "carousel_id": carousel_id}


def build_slides_zip(slide_paths: list[str]) -> bytes:
    """Zip the slide image files that exist on disk, ordered slide_1, slide_2…

    Returns empty bytes if nothing on disk could be added.
    """
    import io
    import zipfile

    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, sp in enumerate(slide_paths):
            if not sp:
                continue
            path = Path(sp)
            if path.exists():
                zf.write(str(path), arcname=f"slide_{i + 1}{path.suffix or '.png'}")
                added += 1
    return buf.getvalue() if added else b""


@app.get("/carousel/{carousel_id}/download")
async def download_carousel_zip(carousel_id: int):
    """
    Bundle every slide of a carousel into a single .zip.

    This is the fallback path for the one-step save: browsers that support the
    Web Share API drop all slides straight into Photos, but desktop / older
    browsers grab this zip instead of downloading each slide by hand.
    """
    async with get_session() as session:
        post = await session.get(CarouselPost, carousel_id)
        if not post:
            raise HTTPException(404, "Carousel not found")
        try:
            slide_paths = json.loads(post.slide_paths or "[]")
        except Exception:
            slide_paths = []
        part = post.part_number

    if not slide_paths:
        raise HTTPException(404, "This carousel has no slides yet")

    data = build_slides_zip(slide_paths)
    if not data:
        raise HTTPException(404, "Slide image files are missing on disk")

    filename = f"roblox_carousel_part{part:03d}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Analytics ingestion ───────────────────────────────────────────────

class AnalyticsPayload(BaseModel):
    content_id: int
    views: int
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    follows: int = 0
    profile_visits: int = 0
    avg_watch_time_s: float = 0.0
    video_duration_s: float = 21.5
    thumbnail_variant: str = "A"


@app.post("/analytics/ingest")
async def ingest_analytics(payload: AnalyticsPayload):
    try:
        record = await _feedback.ingest_manual(
            content_id=payload.content_id,
            views=payload.views,
            likes=payload.likes,
            comments=payload.comments,
            shares=payload.shares,
            saves=payload.saves,
            follows=payload.follows,
            profile_visits=payload.profile_visits,
            avg_watch_time_s=payload.avg_watch_time_s,
            video_duration_s=payload.video_duration_s,
            thumbnail_variant=payload.thumbnail_variant,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"status": "recorded", "analytics_id": record.id}


# ── API endpoints ─────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    stats, perf = await asyncio.gather(
        _queue.get_dashboard_stats(),
        _feedback.get_performance_summary(),
    )
    return {**stats, **perf}


@app.get("/api/queue")
async def api_queue(limit: int = 20):
    async with get_session() as session:
        result = await session.execute(
            select(Content, Game)
            .join(Game, Content.game_id == Game.id)
            .where(Content.status == "approved")
            .order_by(Content.queue_priority.desc())
            .limit(limit)
        )
        return [
            {
                "content_id": c.id,
                "game_name": g.name,
                "rating": c.rating_score,
                "label": c.rating_label,
                "priority": c.queue_priority,
                "scheduled": c.scheduled_post_time.isoformat() if c.scheduled_post_time else None,
                "thumbnail_a": f"/output/thumbnails/{g.universe_id}/variant_a.png",
                "thumbnail_b": f"/output/thumbnails/{g.universe_id}/variant_b.png",
                "video": f"/output/videos/{g.universe_id}.mp4" if c.video_path else None,
                "caption_a": c.description_a,
                "caption_b": c.description_b,
            }
            for c, g in result
        ]


@app.get("/api/games/top")
async def api_top_games(limit: int = 20):
    async with get_session() as session:
        result = await session.execute(
            select(Game)
            .where(Game.is_blacklisted == False)  # noqa: E712
            .order_by(Game.viral_score.desc())
            .limit(limit)
        )
        games = result.scalars().all()
        return [
            {
                "universe_id": g.universe_id,
                "name": g.name,
                "url": g.url,
                "visits": g.visits,
                "active_players": g.active_players,
                "viral_score": g.viral_score,
                "genre": g.genre,
                "thumbnail_url": g.thumbnail_url,
                "content_generated": g.content_generated,
            }
            for g in games
        ]


@app.get("/output/thumbnails/{universe_id}/{filename}")
async def serve_thumbnail(universe_id: str, filename: str):
    path = Path(_settings.OUTPUT_DIR, "thumbnails", universe_id, filename)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(str(path))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "pipeline_running": _pipeline._running if _pipeline else False,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Game deletion ──────────────────────────────────────────────────────

@app.delete("/game/{game_id}")
async def delete_game(game_id: int):
    """Permanently delete a game and all its content / crawl history from the DB."""
    async with get_session() as session:
        game = await session.get(Game, game_id)
        if not game:
            raise HTTPException(404, "Game not found")
        name = game.name
        await session.delete(game)  # cascades to Content (→ PostAnalytics) + CrawlLog
    log.info("dashboard.game_deleted", game_id=game_id, name=name)
    return {"status": "deleted", "game_id": game_id, "name": name}


@app.post("/api/games/clear-all")
async def clear_all_games():
    """Permanently delete ALL games, content, crawl logs, and carousel posts."""
    from sqlalchemy import text
    async with get_session() as session:
        from sqlalchemy import func, select as sa_select
        game_count = await session.scalar(sa_select(func.count(Game.id))) or 0
        # Delete in FK-dependency order (SQLite may not enforce FKs)
        await session.execute(text("DELETE FROM post_analytics"))
        await session.execute(text("DELETE FROM content"))
        await session.execute(text("DELETE FROM crawl_logs"))
        await session.execute(text("DELETE FROM carousel_posts"))
        await session.execute(text("DELETE FROM games"))
    log.info("dashboard.all_games_cleared", count=game_count)
    return {"status": "cleared", "deleted": game_count}
