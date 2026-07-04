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
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
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
from src.database.models import Account, CarouselPost, Content, CrawlLog, Game, PostAnalytics
from src.queue.content_queue import ContentQueue
from src.scheduler.pipeline import Pipeline

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    global _pipeline
    await init_db()
    _settings.ensure_dirs()
    # Validate the AI credentials up front so a bad key surfaces immediately
    # instead of silently degrading every rating into fallback mode.
    try:
        status = await _refresh_ai_status()
        if not status.get("ok"):
            log.error("dashboard.ai_key_check_failed", **status)
    except Exception as exc:  # never let a check failure block startup
        log.warning("dashboard.ai_key_check_error", error=str(exc))
    _pipeline = Pipeline()
    await _pipeline.start()
    log.info("dashboard.started")
    try:
        yield
    finally:
        # ── shutdown ──
        if _pipeline:
            await _pipeline.stop()


app = FastAPI(title="TikTok Robox Dashboard", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)

_settings = get_settings()
_queue = ContentQueue()
_feedback = FeedbackLoop()
_pipeline: Optional[Pipeline] = None

# Cached AI credential state, refreshed at startup and on demand. None until the
# first check runs. The dashboard surfaces this so a missing/invalid/expired key
# can never silently downgrade users into fallback mode without them knowing.
_ai_status: Optional[dict] = None


async def _refresh_ai_status() -> dict:
    """Probe the Anthropic key off the event loop and cache the result."""
    global _ai_status
    from src.content.ai_status import check_api_key  # noqa: PLC0415
    status = await asyncio.get_event_loop().run_in_executor(None, check_api_key)
    _ai_status = status.as_dict()
    return _ai_status

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

output_dir = Path(_settings.OUTPUT_DIR)
if output_dir.exists():
    app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Pages ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Run both stat queries concurrently
    stats, perf = await asyncio.gather(
        _queue.get_dashboard_stats(),
        _feedback.get_performance_summary(),
    )
    return templates.TemplateResponse(request, "index.html", {
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

    return templates.TemplateResponse(request, "queue.html", {
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

    return templates.TemplateResponse(request, "games.html", {
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

    return templates.TemplateResponse(request, "analytics.html", {
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

    return templates.TemplateResponse(request, "content_detail.html", {
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


@app.post("/pipeline/create-carousel")
async def create_carousel():
    """One action → a carousel. Builds now if possible, otherwise warms up the
    discover→rate→build chain in the background. The single primary CTA."""
    if _pipeline:
        return await _pipeline.run_create_carousel()
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
        review = None
        if getattr(p, "review_summary", None):
            try:
                review = json.loads(p.review_summary)
            except Exception:
                review = None
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
            "review_score": getattr(p, "review_score", None),
            "review": review,
        })

    return templates.TemplateResponse(request, "carousels.html", {
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


@app.post("/carousel/{carousel_id}/regenerate")
async def regenerate_carousel(carousel_id: int):
    """Reject this draft and build a fresh one. Explicit creator action — part of
    the Generate → Review → Approve/Reject/Regenerate workflow."""
    async with get_session() as session:
        post = await session.get(CarouselPost, carousel_id)
        if not post:
            raise HTTPException(404, "Carousel not found")
        post.status = "rejected"
    if _pipeline:
        result = await _pipeline.run_create_carousel()
        return {"status": "regenerating", "result": result}
    return {"status": "error", "message": "Pipeline not initialized"}


@app.post("/carousel/{carousel_id}/mark-posted")
async def mark_carousel_posted(carousel_id: int):
    """Mark a carousel as posted after you've uploaded it to TikTok yourself."""
    from datetime import timezone
    async with get_session() as session:
        post = await session.get(CarouselPost, carousel_id)
        if not post:
            raise HTTPException(404, "Carousel not found")
        # Can't mark something posted that was never approved — that would skip
        # the mandatory human review step.
        if post.status not in ("approved", "posted"):
            raise HTTPException(
                409, f"Approve this carousel before marking it posted "
                f"(it's currently '{post.status}').")
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
        # EXPORT GATE: a carousel is only exportable once a human has approved it
        # (or it's already posted). This enforces Generate → Review → Approve →
        # Publish — you cannot export something still pending review or rejected.
        if post.status not in ("approved", "posted"):
            raise HTTPException(
                409,
                f"This carousel is '{post.status}', not approved. Review and "
                f"approve it before exporting.",
            )
        try:
            slide_paths = json.loads(post.slide_paths or "[]")
        except Exception:
            slide_paths = []
        part = post.part_number

    if not slide_paths:
        raise HTTPException(404, "This carousel has no slides yet")

    # PRE-EXPORT SAFE-ZONE / INTEGRITY GATE: never hand the user a broken export
    # (wrong dimensions, blank/corrupt slide, or a placeholder hero).
    from src.content.export_validator import validate_carousel_export  # noqa: PLC0415
    validation = validate_carousel_export(slide_paths)
    if not validation.ok:
        raise HTTPException(
            409, "This carousel failed export validation: "
            + "; ".join(validation.reasons))

    data = build_slides_zip(slide_paths)
    if not data:
        raise HTTPException(404, "Slide image files are missing on disk")

    filename = f"roblox_carousel_part{part:03d}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Content DNA ────────────────────────────────────────────────────────

@app.get("/dna", response_class=HTMLResponse)
async def dna_page(request: Request):
    """View the extracted Content DNA — the blueprint of *why* proven carousels
    worked — plus every per-upload profile feeding it."""
    from src.content.content_dna import DIMENSIONS
    from src.content.dna_store import DNAStore
    store = DNAStore()
    consolidated = store.get_consolidated()
    profiles = store.list_profiles()
    return templates.TemplateResponse(request, "dna.html", {
        "consolidated": consolidated.as_dict(),
        "profiles": [p.as_dict() for p in profiles],
        "dimensions": list(DIMENSIONS),
    })


@app.post("/dna/extract")
async def dna_extract(files: list[UploadFile] = File(...), label: str = Form(default="")):
    """Upload screenshots of a successful carousel → extract its Content DNA.

    Saves the screenshots, runs the vision extractor, persists the profile, and
    rebuilds the consolidated blueprint that future generation reads from.
    """
    from src.content.content_dna import ContentDNAExtractor
    from src.content.dna_store import DNAStore

    payloads: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if data:
            payloads.append((f.filename or "slide.png", data))
    if not payloads:
        return JSONResponse(status_code=400, content={"error": "no files uploaded"})

    store = DNAStore()
    saved_paths = store.save_screenshots(payloads)

    # Vision extraction can hit the network — run it off the event loop.
    extractor = ContentDNAExtractor()
    profile = await asyncio.get_event_loop().run_in_executor(
        None, extractor.extract, saved_paths, label,
    )

    # H2: the extractor returns a generic PRIOR when the vision call fails (no key,
    # network error, or no usable patterns). That is NOT a successful extraction —
    # nothing was learned from the upload. Do NOT persist it (it would pollute the
    # consolidated blueprint and look like success) and tell the user plainly.
    if profile.is_prior:
        log.warning("dna.extract_no_signal", slides=len(saved_paths),
                    notes=profile.notes)
        return {
            "status": "no_signal",
            "is_prior": True,
            "slides": len(saved_paths),
            "overall_confidence": profile.overall_confidence,
            "message": (
                "Couldn't extract DNA from these screenshots — the AI vision step "
                "returned no usable patterns (check the API-key banner up top). "
                "Nothing was added to your blueprint. Fix the key and try again."
            ),
            "notes": profile.notes,
        }

    pid = store.save_profile(profile)
    return {
        "status": "extracted",
        "profile_id": pid,
        "slides": len(saved_paths),
        "overall_confidence": profile.overall_confidence,
        "is_prior": False,
        "profile": profile.as_dict(),
    }


@app.get("/api/dna/consolidated")
async def api_dna_consolidated():
    """The active consolidated DNA blueprint generation reads from."""
    from src.content.dna_store import DNAStore
    return DNAStore().get_consolidated().as_dict()


# ── Performance Insights ───────────────────────────────────────────────

@app.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request):
    """The Performance Insights dashboard — what the system has learned about
    which generation choices produce the highest-quality content."""
    from src.learning import PerformanceStore
    data = PerformanceStore().insights()
    return templates.TemplateResponse(request, "insights.html", {
        "ins": data,
    })


@app.get("/api/insights")
async def api_insights():
    """The raw Performance Insights payload (JSON)."""
    from src.learning import PerformanceStore
    return PerformanceStore().insights()


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
        "ai": _ai_status or {"state": "unchecked", "ok": False},
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/ai-status")
async def api_ai_status(recheck: bool = False):
    """Current Anthropic credential state. The dashboard polls this to render a
    visible banner whenever the key is missing/invalid/rate-limited so users are
    never silently downgraded into fallback mode without knowing.

    Pass ?recheck=1 to re-probe after fixing the key (no restart needed)."""
    global _ai_status
    if recheck or _ai_status is None:
        return await _refresh_ai_status()
    return _ai_status


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


# ── Account management ─────────────────────────────────────────────────────────

class AccountCreateRequest(BaseModel):
    slug: str
    display_name: str
    channel_name: str = "RobloxGems"
    channel_handle: str = "@robloxgems"
    brand_primary_color: str = "#6C63FF"
    brand_secondary_color: str = "#FF6584"
    brand_accent_color: str = "#FFD700"
    carousel_style: str = "gazette"
    buffer_tiktok_profile_id: str = ""
    post_hour_1_utc: int = 7
    post_hour_2_utc: int = 12
    post_hour_3_utc: int = 17


@app.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request):
    async with get_session() as session:
        from sqlalchemy import func as _func, select as _sel
        rows = await session.execute(
            _sel(Account).order_by(Account.created_at.asc())
        )
        accounts = list(rows.scalars().all())

        # Post counts per account
        counts_q = await session.execute(
            _sel(CarouselPost.account_id, _func.count(CarouselPost.id))
            .group_by(CarouselPost.account_id)
        )
        post_counts = {row[0]: row[1] for row in counts_q}

    return templates.TemplateResponse(request, "accounts.html", {
        "accounts": accounts,
        "post_counts": post_counts,
        "default_hours": [
            _settings.DEFAULT_POST_HOUR_1_UTC,
            _settings.DEFAULT_POST_HOUR_2_UTC,
            _settings.DEFAULT_POST_HOUR_3_UTC,
        ],
        "buffer_configured": bool(_settings.BUFFER_EMAIL and _settings.BUFFER_PASSWORD),
    })


@app.post("/accounts")
async def create_account(req: AccountCreateRequest):
    """Create a new account and register its posting jobs."""
    slug = req.slug.strip().lower().replace(" ", "-")
    async with get_session() as session:
        from sqlalchemy import select as _sel
        existing = await session.scalar(
            _sel(Account).where(Account.slug == slug).limit(1)
        )
        if existing:
            raise HTTPException(400, f"Account slug '{slug}' already exists")
        account = Account(
            slug=slug,
            display_name=req.display_name.strip(),
            channel_name=req.channel_name.strip(),
            channel_handle=req.channel_handle.strip(),
            brand_primary_color=req.brand_primary_color,
            brand_secondary_color=req.brand_secondary_color,
            brand_accent_color=req.brand_accent_color,
            carousel_style=req.carousel_style,
            buffer_tiktok_profile_id=req.buffer_tiktok_profile_id.strip(),
            post_hour_1_utc=req.post_hour_1_utc,
            post_hour_2_utc=req.post_hour_2_utc,
            post_hour_3_utc=req.post_hour_3_utc,
        )
        session.add(account)
        await session.flush()
        account_id = account.id
        # Detach before session closes so we can pass it to the pipeline
        import copy as _copy
        account_copy = _copy.copy(account)
        session.expunge(account)

    if _pipeline and req.buffer_tiktok_profile_id:
        _pipeline._register_account_jobs(account_copy)

    log.info("dashboard.account_created", slug=slug, account_id=account_id)
    return {"status": "created", "account_id": account_id, "slug": slug}


@app.post("/accounts/{account_id}/deactivate")
async def deactivate_account(account_id: int):
    """Deactivate an account and remove its scheduled posting jobs."""
    async with get_session() as session:
        account = await session.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        account.is_active = False
        slug = account.slug

    if _pipeline:
        _pipeline._deregister_account_jobs(account_id)

    log.info("dashboard.account_deactivated", account_id=account_id, slug=slug)
    return {"status": "deactivated", "account_id": account_id}


@app.post("/accounts/{account_id}/activate")
async def activate_account(account_id: int):
    """Re-activate a deactivated account and re-register its posting jobs."""
    async with get_session() as session:
        account = await session.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        account.is_active = True
        import copy as _copy
        account_copy = _copy.copy(account)
        session.expunge(account)

    if _pipeline and account_copy.buffer_tiktok_profile_id:
        _pipeline._register_account_jobs(account_copy)

    log.info("dashboard.account_activated", account_id=account_id)
    return {"status": "activated", "account_id": account_id}


@app.post("/accounts/{account_id}/update")
async def update_account(account_id: int, req: AccountCreateRequest):
    """Update account settings and re-register posting jobs with new hours."""
    async with get_session() as session:
        account = await session.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        account.display_name = req.display_name.strip()
        account.channel_name = req.channel_name.strip()
        account.channel_handle = req.channel_handle.strip()
        account.brand_primary_color = req.brand_primary_color
        account.brand_secondary_color = req.brand_secondary_color
        account.brand_accent_color = req.brand_accent_color
        account.carousel_style = req.carousel_style
        account.buffer_tiktok_profile_id = req.buffer_tiktok_profile_id.strip()
        account.post_hour_1_utc = req.post_hour_1_utc
        account.post_hour_2_utc = req.post_hour_2_utc
        account.post_hour_3_utc = req.post_hour_3_utc
        import copy as _copy
        account_copy = _copy.copy(account)
        session.expunge(account)

    # Re-register jobs with updated hours
    if _pipeline and account_copy.is_active and account_copy.buffer_tiktok_profile_id:
        _pipeline._register_account_jobs(account_copy)

    log.info("dashboard.account_updated", account_id=account_id)
    return {"status": "updated", "account_id": account_id}


@app.post("/accounts/{account_id}/test-buffer")
async def test_buffer_account(account_id: int):
    """Verify that Buffer credentials are valid by doing a headless test login."""
    if not _settings.BUFFER_EMAIL or not _settings.BUFFER_PASSWORD:
        return {"ok": False, "error": "BUFFER_EMAIL and BUFFER_PASSWORD not set in .env"}
    async with get_session() as session:
        account = await session.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Account not found")
        profile_id = account.buffer_tiktok_profile_id

    if not profile_id:
        return {"ok": False, "error": "No channel handle set for this account"}

    import asyncio as _asyncio
    from src.integrations.buffer_client import BufferClient, BufferError
    def _check():
        try:
            client = BufferClient(_settings.BUFFER_EMAIL, _settings.BUFFER_PASSWORD)
            result = client.test_login()
            if result["ok"]:
                channels = result.get("channels", [])
                handle = profile_id.lstrip("@").lower()
                matched = any(handle in ch.lower() for ch in channels)
                return {
                    "ok": True,
                    "service": "TikTok",
                    "username": profile_id,
                    "channel_found": matched,
                    "channels_visible": channels,
                }
            return {"ok": False, "error": result.get("error", "Login failed")}
        except BufferError as e:
            return {"ok": False, "error": str(e)}
    return await _asyncio.get_event_loop().run_in_executor(None, _check)
