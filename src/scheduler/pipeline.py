"""
Pipeline orchestrator.

Wires all components together and runs them on schedule via APScheduler.

Schedule:
  Every 4h  → discovery run (crawl Roblox, score, update DB)
  Every 4h  → content factory (generate content for top unprocessed games)
  Every 12h → queue reprioritize + schedule posts
  Every 24h → analytics weight update
  Startup   → immediate discovery run if queue < 20 items
"""
from __future__ import annotations

import asyncio
import functools
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from src.analytics.feedback_loop import FeedbackLoop
from src.capture.screenshot_engine import ScreenshotEngine
from src.config import get_settings
from src.content.carousel_generator import CarouselGame, CarouselGenerator
from src.content.description_engine import DescriptionEngine
from src.content.rating_engine import RatingEngine
from src.content.thumbnail_generator import ThumbnailGenerator
from src.content.video_assembler import VideoAssembler
from src.database.connection import get_session, init_db
from src.database.models import CarouselPost, Content, Game
from src.discovery.trend_detector import TrendDetector
from src.queue.content_queue import ContentQueue

log = structlog.get_logger(__name__)


class Pipeline:
    def __init__(self):
        self._settings = get_settings()
        self._scheduler = AsyncIOScheduler()
        self._detector = TrendDetector()
        self._queue = ContentQueue()
        self._feedback = FeedbackLoop()
        self._rating = RatingEngine()
        self._description = DescriptionEngine()
        self._thumbgen = ThumbnailGenerator()
        self._video = VideoAssembler()
        self._carousel = CarouselGenerator()
        self._running = False
        self._carousel_part_counter = 1
        self._warming = False   # a background warm-up (discover→rate→build) is in flight

    async def start(self) -> None:
        await init_db()
        self._settings.ensure_dirs()

        self._scheduler.add_job(
            self.run_discovery,
            "interval",
            hours=self._settings.DISCOVERY_INTERVAL_HOURS,
            id="discovery",
            name="Roblox Discovery Crawl",
            misfire_grace_time=300,
        )
        self._scheduler.add_job(
            self.run_content_factory,
            "interval",
            hours=self._settings.DISCOVERY_INTERVAL_HOURS,
            id="content_factory",
            name="Content Generation Factory",
            misfire_grace_time=300,
        )
        self._scheduler.add_job(
            self.run_queue_maintenance,
            "interval",
            hours=12,
            id="queue_maintenance",
            name="Queue Reprioritization",
        )
        self._scheduler.add_job(
            self.run_analytics_update,
            "interval",
            hours=24,
            id="analytics_update",
            name="Analytics Weight Update",
        )
        self._scheduler.add_job(
            self.run_carousel_factory,
            "interval",
            hours=8,
            id="carousel_factory",
            name="Carousel Batch Generator",
            misfire_grace_time=300,
        )

        self._scheduler.start()
        self._running = True
        log.info("pipeline.started")

        # Kick off background tasks if queue is thin — no sleep, both fire immediately
        queue_size = await self._queue.queue_size()
        if queue_size < 20:
            log.info("pipeline.startup_discovery", queue_size=queue_size)
            asyncio.create_task(self.run_discovery())
            asyncio.create_task(self.run_content_factory())

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        self._running = False
        log.info("pipeline.stopped")

    # ── Job handlers ──────────────────────────────────────────────────

    async def run_discovery(self) -> dict:
        log.info("pipeline.discovery.start")
        try:
            stats = await self._detector.run_discovery()
            log.info("pipeline.discovery.complete", **stats)
            return stats
        except Exception as exc:
            log.error("pipeline.discovery.failed", error=str(exc))
            return {"error": str(exc)}

    async def run_content_factory(self, batch_size: int = 10) -> dict:
        """
        Generate content packages for the top unprocessed games.
        Each game gets: screenshots, thumbnail A+B, AI rating, captions, video.
        """
        log.info("pipeline.content_factory.start")
        games = await self._detector.get_top_unprocessed(limit=batch_size)
        if not games:
            log.info("pipeline.content_factory.no_games")
            return {"processed": 0}

        processed = 0
        for game in games:
            try:
                await self._generate_content_for_game(game)
                processed += 1
            except Exception as exc:
                log.error(
                    "pipeline.content_factory.game_failed",
                    game=game.name,
                    universe_id=game.universe_id,
                    error=str(exc),
                )

        log.info("pipeline.content_factory.complete", processed=processed, total=len(games))
        return {"processed": processed, "attempted": len(games)}

    async def run_queue_maintenance(self) -> None:
        await self._queue.reprioritize()
        scheduled = await self._queue.schedule_posts(days_ahead=14)
        log.info("pipeline.queue_maintenance.complete", newly_scheduled=scheduled)

    async def run_analytics_update(self) -> None:
        result = await self._feedback.run_weight_update()
        if result:
            log.info("pipeline.analytics_update.weights_updated")
        else:
            log.info("pipeline.analytics_update.no_update")

    async def run_carousel_factory(self) -> dict:
        """
        Batch 5 rated games into one photo carousel — the proven viral format.
        Picks games that already have ratings (content_generated=True) and
        haven't been included in a carousel yet, then generates all 6 slides.
        """
        import json as _json
        log.info("pipeline.carousel_factory.start")

        # Pull 5 approved/rated content items not yet in a carousel
        async with get_session() as session:
            # Get game IDs already used in carousels
            from sqlalchemy import select as sa_select, text as sa_text  # noqa: PLC0415
            used_result = await session.execute(sa_select(CarouselPost.game_ids))
            used_ids: set[int] = set()
            for row in used_result.scalars().all():
                try:
                    used_ids.update(_json.loads(row))
                except Exception:
                    pass

            # Fetch top-rated content not yet carouselled.
            # PRE-GENERATION RATING GATE: only games at/above the quality floor
            # (MIN_CAROUSEL_RATING) are even eligible — one weak game makes the
            # whole carousel read as filler.
            min_rating = self._settings.MIN_CAROUSEL_RATING
            # PROVENANCE GATE: exclude rule-based fallback content (AI call failed)
            # so a fabricated rating/caption never ships as if it were AI-curated
            # (audit C1). `used_fallback` is False/NULL for genuine AI output.
            result = await session.execute(
                sa_select(Content, Game)
                .join(Game, Content.game_id == Game.id)
                .where(Content.status.in_(["pending", "approved"]))
                .where(Content.rating_score.isnot(None))
                .where(Content.rating_score >= min_rating)
                .where(Content.carousel_caption.isnot(None))
                .where(Content.used_fallback.isnot(True))
                .order_by(Content.queue_priority.desc())
                .limit(80)
            )
            # Dedupe so the same game can never appear twice in one carousel.
            # Two ways a duplicate slips in: (a) a game has >1 Content row, so the
            # join yields it more than once; (b) clones/re-uploads share an
            # identical name under different universe IDs and read as the "same
            # game" to a viewer. Guard against both — by game id and by name.
            candidates = []
            seen_game_ids: set[int] = set()
            seen_names: set[str] = set()
            for c, g in result:
                if g.id in used_ids or g.id in seen_game_ids:
                    continue
                name_key = (g.name or "").strip().lower()
                if name_key and name_key in seen_names:
                    continue
                seen_game_ids.add(g.id)
                if name_key:
                    seen_names.add(name_key)
                candidates.append((c, g))

        if len(candidates) < 5:
            # If the library is thin because AI ratings fell back to rule-based
            # output (and were therefore excluded by the provenance gate), say so
            # — otherwise "not enough games" looks like a discovery problem when
            # the real cause is a missing/invalid key or a rate-limit (C1).
            async with get_session() as session:
                from sqlalchemy import func as sa_func  # noqa: PLC0415
                fallback_count = await session.scalar(
                    sa_select(sa_func.count(Content.id))
                    .where(Content.used_fallback.is_(True))
                    .where(Content.rating_score >= min_rating)
                ) or 0
            log.info("pipeline.carousel_factory.not_enough_games",
                     count=len(candidates), excluded_fallback=fallback_count)
            result: dict = {"carousels": 0, "eligible": len(candidates)}
            if fallback_count:
                result["reason"] = "fallback_content"
                result["message"] = (
                    f"{fallback_count} rated game(s) were excluded because their "
                    f"ratings are rule-based fallback (the AI call failed — check "
                    f"the API-key banner). Fix the key so real AI ratings can be "
                    f"generated, then try again.")
            return result

        # Sequence the 5 games for a RETENTION ARC instead of a flat
        # highest-first ranking (predictable = scrollable). Open strong, dip,
        # build back, and save the single best game for the last slide so
        # finishing the carousel feels rewarded — which lifts completion rate.
        batch = self._retention_order(candidates[:5], key=lambda cg: cg[0].rating_score or 0.0)

        # DEFENSIVE RATING GATE (pre-approval): even though the query filtered by
        # rating, never let a below-floor game reach generation — fail safe.
        min_rating = self._settings.MIN_CAROUSEL_RATING
        batch_scores = [c.rating_score or 0.0 for c, g in batch]
        below = [(g.name, c.rating_score) for c, g in batch
                 if (c.rating_score or 0.0) < min_rating]
        if below:
            log.error("pipeline.carousel_factory.below_rating_floor",
                      min_rating=min_rating, below=below)
            return {"carousels": 0, "rejected": True, "reason": "below_rating_floor",
                    "message": (f"Some selected games are below the {min_rating} "
                                f"rating floor ({below}). Not building a carousel.")}

        # DEFENSIVE PROVENANCE GATE (pre-approval): the selection query already
        # excludes fallback content, but never let a rule-based rating reach
        # generation — a fabricated rating must never ship as if AI-curated (C1).
        fallback_games = [g.name for c, g in batch if getattr(c, "used_fallback", False)]
        if fallback_games:
            log.error("pipeline.carousel_factory.fallback_in_batch",
                      games=fallback_games)
            return {"carousels": 0, "rejected": True, "reason": "fallback_content",
                    "message": (f"Some selected games have rule-based (non-AI) "
                                f"ratings ({fallback_games}) because the AI call "
                                f"failed. Not building a carousel until real AI "
                                f"ratings are available.")}

        # GENRE-AWARE EDITION (replaces the blind counter rotation): pick an
        # edition that actually fits the batch's genres, so a themed cover never
        # lies about the games underneath it.
        from src.content.edition_match import (  # noqa: PLC0415
            edition_for_games, validate_edition_match,
        )
        batch_genres = [g.genre for c, g in batch]
        part = self._carousel_part_counter
        edition = edition_for_games(batch_genres, part)
        ed_ok, ed_reason = validate_edition_match(edition, batch_genres)
        if not ed_ok:
            # Should not happen (edition_for_games only returns a fitting edition),
            # but if it ever does, fall back to a safe neutral edition.
            log.warning("pipeline.carousel_factory.edition_mismatch", reason=ed_reason)
            edition = "Hidden Gems"
        self._carousel_part_counter += 1

        # HISTORICAL DEDUP: load the cover hooks + captions of recently shipped
        # carousels so the approval gate never reuses a hook/caption the same
        # followers already saw (the #1 "this is a bot" tell).
        used_hooks_hist, used_caps_hist = await self._recent_text_history(limit=25)

        # ── MANDATORY approval gate (runs BEFORE we render or persist) ──
        # A carousel is not complete until it survives the three-reviewer panel.
        # The approval system runs Generate→Critique→Revise→Re-score→Critique→
        # Finalize (max 3 cycles); we ship ONLY what it approves. The user never
        # sees a first draft. Generation is steered by the extracted Content DNA.
        from src.content.carousel_quality import (  # noqa: PLC0415
            build_carousel_hashtags, pick_footer_cta,
        )
        from src.content.content_approval import ContentApprovalSystem  # noqa: PLC0415
        dna_profile = None
        try:
            from src.content.dna_store import DNAStore  # noqa: PLC0415
            dna_profile = DNAStore().get_consolidated()
        except Exception as exc:
            log.warning("pipeline.carousel_factory.dna_load_failed", error=str(exc))

        # ── Performance Learning System: bias generation toward the cover
        # archetypes that have historically performed (anti-convergence built in).
        perf_store = None
        cover_bias: dict = {}
        try:
            from src.learning import PerformanceStore  # noqa: PLC0415
            perf_store = PerformanceStore()
            cover_bias = perf_store.component_bias("cover")
        except Exception as exc:
            log.warning("pipeline.carousel_factory.perf_load_failed", error=str(exc))

        approval = ContentApprovalSystem().approve(
            part=part,
            edition=edition,
            captions=[c.carousel_caption or "" for c, g in batch],
            blurbs=[c.rating_verdict or "" for c, g in batch],
            genres=[g.genre for c, g in batch],
            scores=[c.rating_score for c, g in batch],
            game_names=[g.name for c, g in batch],
            dna=dna_profile,
            performance=cover_bias or None,
            used_hooks=used_hooks_hist,   # don't reuse a hook history already saw
        )

        # ── Record this carousel's genome (approved OR rejected) into the
        # learning corpus so the system keeps getting smarter over time.
        if perf_store is not None:
            try:
                from src.learning import build_genome  # noqa: PLC0415
                genome = build_genome(
                    part=part,
                    edition=edition,
                    approval=approval,
                    genres=[g.genre for c, g in batch],
                    game_names=[g.name for c, g in batch],
                    blurbs=[c.rating_verdict or "" for c, g in batch],
                    dna=dna_profile,
                    performance_biased=bool(cover_bias),
                )
                perf_store.record(genome)
                log.info("pipeline.carousel_factory.genome_recorded",
                         part=part, genome_id=genome.id, approved=approval.approved,
                         hook_pattern=genome.hook_pattern, cover=genome.cover_concept)
            except Exception as exc:
                log.warning("pipeline.carousel_factory.genome_failed", error=str(exc))
        # Log every review cycle (the critique trail).
        for entry in approval.trail:
            log.info("pipeline.carousel_factory.review_cycle", part=part, **entry)

        report = approval.report
        plan = approval.plan
        if plan is not None:
            log.info("pipeline.carousel_factory.plan", part=part,
                     audience=plan.brief.who, purposeful=plan.purposeful,
                     purposes=[s.purpose for s in plan.slides],
                     dead_slides=plan.dead_slides)

        # ── The gate: if it didn't survive review, it does NOT ship. ──
        if not approval.approved:
            log.warning("pipeline.carousel_factory.rejected", part=part,
                        final_score=approval.final_score,
                        cycles=approval.cycles,
                        hard_failures=approval.panel.hard_failures,
                        reviewers={r.name: r.score for r in approval.panel.reviewers})
            # Roll back the part counter so the rejected part number is reused by
            # the next attempt — we don't burn a "Part N" on content nobody sees.
            self._carousel_part_counter -= 1
            return {"carousels": 0, "rejected": True, "part": part,
                    "final_score": approval.final_score,
                    "hard_failures": approval.panel.hard_failures}

        # ── NEAR-DUPLICATE GATE (vs shipped history) ──────────────────
        # The panel guarantees intra-carousel variety; this guards across posts.
        # If the approved cover hook or any caption is a near-duplicate of a
        # recently shipped one, reject so the retry produces something fresh.
        from src.content.dedup import is_near_duplicate  # noqa: PLC0415
        dup_reason = None
        if is_near_duplicate(approval.cover_hook, used_hooks_hist):
            dup_reason = f"cover hook too similar to a recent post: '{approval.cover_hook}'"
        else:
            for cap in approval.captions:
                if is_near_duplicate(cap, used_caps_hist):
                    dup_reason = f"caption too similar to a recent post: '{cap}'"
                    break
        if dup_reason:
            log.warning("pipeline.carousel_factory.near_duplicate", part=part,
                        reason=dup_reason)
            self._carousel_part_counter -= 1
            return {"carousels": 0, "rejected": True, "part": part,
                    "reason": "near_duplicate", "message": dup_reason}

        log.info("pipeline.carousel_factory.approved", part=part,
                 final_score=approval.final_score, cycles=approval.cycles,
                 reviewers={r.name: r.score for r in approval.panel.reviewers})

        deduped_captions = approval.captions
        cover_hook = approval.cover_hook
        footer_cta = pick_footer_cta(part)

        carousel_games = [
            CarouselGame(
                name=g.name,
                creator=g.creator_name or "",
                score=c.rating_score,
                carousel_caption=deduped_captions[idx],
                like_ratio=g.like_ratio,
                active_players=g.active_players,
                thumbnail_url=g.thumbnail_url,
                icon_url=g.icon_url,
                genre=g.genre,
                visits=g.visits,
                description=g.description or "",
                blurb=c.rating_verdict or "",
            )
            for idx, (c, g) in enumerate(batch)
        ]

        slug = f"part{part:03d}"
        loop = asyncio.get_event_loop()
        render = await loop.run_in_executor(
            None,
            functools.partial(
                self._carousel.generate,
                games=carousel_games,
                edition=edition,
                part_number=part,
                slug=slug,
                cover_hook=cover_hook,
                final_cta=footer_cta,
            ),
        )

        # ── FAIL-SAFE IMAGE GATE (runs AFTER render, BEFORE persist) ──
        # The text passed the three-reviewer panel, but the carousel is only
        # shippable if every game slide loaded the REAL Roblox hero thumbnail.
        # If any slide fell back to a grey placeholder (Roblox rate-limit / CDN
        # timeout / dead thumbnail URL), we DO NOT persist it. A carousel that is
        # never persisted is never approved and never exportable. We roll back the
        # part counter so the next attempt reuses this Part N, and report a clear
        # reason so run_create_carousel can retry / tell the user.
        if not render.ok:
            log.error("pipeline.carousel_factory.placeholder_rejected", part=part,
                      placeholder_count=render.placeholder_count,
                      game_slides=render.game_slide_count,
                      failed_games=render.failed_games,
                      failed_icons=render.failed_icon_games)
            self._carousel_part_counter -= 1
            return {"carousels": 0, "rejected": True, "part": part,
                    "reason": "placeholder_thumbnails",
                    "message": render.failure_reason,
                    "placeholder_count": render.placeholder_count,
                    "failed_games": render.failed_games,
                    "failed_icons": render.failed_icon_games}

        slide_paths = render.slides

        # ── EXPORT VALIDATION GATE (safe-zone / dimensions / integrity) ──
        # The render loaded real thumbnails; this confirms every slide is a valid
        # 1080×1920 frame, not blank/corrupt, before we ever persist it.
        from src.content.export_validator import validate_carousel_export  # noqa: PLC0415
        export_check = validate_carousel_export([str(p) for p in slide_paths])
        if not export_check.ok:
            log.error("pipeline.carousel_factory.export_invalid", part=part,
                      reasons=export_check.reasons)
            self._carousel_part_counter -= 1
            return {"carousels": 0, "rejected": True, "part": part,
                    "reason": "export_invalid",
                    "message": "Render failed validation: " + "; ".join(export_check.reasons)}

        # De-templated TikTok caption (keeps the proven search anchor) + CTA.
        caption = f"{approval.post_caption}\n\n{approval.cta}"
        # Per-post hashtags: proven search anchors pinned, the rest rotated by
        # part + matched to the edition so no two drops post the identical wall
        # (an automation tell that TikTok can suppress as repetitive).
        hashtags = build_carousel_hashtags(
            part, edition, game_names=[g.name for c, g in batch],
        )

        import uuid as _uuid  # noqa: PLC0415
        generation_id = _uuid.uuid4().hex[:12]

        async with get_session() as session:
            post = CarouselPost(
                edition=edition,
                part_number=part,
                game_ids=_json.dumps([g.id for _, g in batch]),
                slide_paths=_json.dumps([str(p) for p in slide_paths]),
                caption=caption,
                hashtags=_json.dumps(hashtags),
                # It passed the automated panel + image gate, but the HUMAN makes
                # the call to publish. It lands in review, never auto-approved.
                status="pending_review",
                review_score=approval.final_score,
                review_summary=_json.dumps(approval.panel.as_dict()),
                cover_hook=cover_hook,
                slide_captions=_json.dumps(list(deduped_captions)),
                generation_id=generation_id,
                min_game_rating=min(batch_scores) if batch_scores else None,
            )
            session.add(post)

        log.info("pipeline.carousel_factory.complete", part=part, edition=edition,
                 slides=len(slide_paths), final_score=approval.final_score,
                 cycles=approval.cycles, generation_id=generation_id,
                 games=[g.name for g in carousel_games])
        return {"carousels": 1, "part": part, "edition": edition,
                "generation_id": generation_id,
                "final_score": approval.final_score, "approved": False,
                "status": "pending_review", "cycles": approval.cycles}

    async def run_create_carousel(self) -> dict:
        """
        ONE action → a carousel. Does whatever prerequisite work is needed so the
        user never has to orchestrate discovery → rating → generation by hand.

        Fast path: if enough rated games already exist, build (and review) a
        carousel right now. Otherwise kick the whole chain (discover if the
        library is thin, then rate, then build) in the background and tell the
        user it's warming up — a carousel will be ready shortly.
        """
        def _created(r: dict) -> dict:
            # A carousel was generated and is waiting in review (NOT auto-approved).
            # `status` is forced to 'created' so it isn't shadowed by the inner
            # 'pending_review'; the JS routes the user to the in-app review page.
            return {**r, "status": "created", "review_required": True,
                    "carousel_status": "pending_review"}

        result = await self.run_carousel_factory()
        if result.get("carousels"):
            return _created(result)

        # It tried but the draft was rejected — one quick retry. A retry helps
        # both rejection causes: the panel (different ordering / cover hooks often
        # clears the bar) AND a transient placeholder failure (re-fetching the
        # Roblox thumbnails often succeeds on the second pass).
        if result.get("rejected"):
            retry = await self.run_carousel_factory()
            if retry.get("carousels"):
                return _created(retry)
            # If the failure is missing game art (Roblox CDN / rate-limit), say so
            # explicitly — it's a network condition, not a quality problem, and the
            # honest message keeps the user from thinking the AI is broken.
            if retry.get("reason") == "placeholder_thumbnails" or \
               result.get("reason") == "placeholder_thumbnails":
                return {"status": "image_error",
                        "reason": "placeholder_thumbnails",
                        "message": retry.get("message") or result.get("message")
                        or "Couldn't load the real Roblox game images (network or "
                           "Roblox rate-limit). Nothing was posted. Try again shortly."}
            return {"status": "retry",
                    "message": "A draft didn't pass review — tap again in a moment."}

        # Not enough rated games. Start the prerequisite chain in the background
        # (it's minutes of crawling + AI rating) and report that it's warming up.
        if not self._warming:
            self._warming = True
            asyncio.create_task(self._warmup_for_carousel())
        return {"status": "warming_up",
                "message": "Finding and rating games — a carousel will be ready in a few minutes."}

    async def _warmup_for_carousel(self) -> None:
        """Background: ensure there are rated games, then build a carousel."""
        try:
            from sqlalchemy import func, select as sa_select  # noqa: PLC0415
            async with get_session() as session:
                total_games = await session.scalar(sa_select(func.count(Game.id))) or 0
            if total_games < 50:
                await self.run_discovery()
            await self.run_content_factory()
            await self.run_carousel_factory()
        except Exception as exc:
            log.error("pipeline.warmup_failed", error=str(exc))
        finally:
            self._warming = False

    async def _recent_text_history(self, limit: int = 25) -> tuple[list[str], list[str]]:
        """Load the cover hooks and slide captions of recently created carousels
        for cross-post duplicate detection. Returns (hooks, captions)."""
        import json as _json  # noqa: PLC0415
        from sqlalchemy import select as sa_select  # noqa: PLC0415
        hooks: list[str] = []
        caps: list[str] = []
        try:
            async with get_session() as session:
                rows = await session.execute(
                    sa_select(CarouselPost.cover_hook, CarouselPost.slide_captions)
                    .order_by(CarouselPost.created_at.desc())
                    .limit(limit)
                )
                for hook, slide_caps in rows:
                    if hook:
                        hooks.append(hook)
                    if slide_caps:
                        try:
                            caps.extend([c for c in _json.loads(slide_caps) if c])
                        except Exception:
                            pass
        except Exception as exc:  # history is best-effort; never block generation
            log.warning("pipeline.carousel_factory.history_load_failed", error=str(exc))
        return hooks, caps

    @staticmethod
    def _retention_order(items: list, key) -> list:
        """
        Reorder a batch for a curiosity arc: strong opener, a dip in the middle
        for contrast, and the single best item LAST (completion payoff). Avoids
        the predictable monotonic high→low ordering that reads as templated.
        """
        if len(items) <= 2:
            return list(items)
        ranked = sorted(items, key=key, reverse=True)
        best = ranked[0]
        rest = ranked[1:]
        # rest[0] is the 2nd best → strong opener; then alternate weak/strong so
        # scores zig-zag instead of descending; best is appended at the end.
        opener = rest[0]
        middle = rest[1:]
        zig: list = []
        lo, hi = len(middle) - 1, 0
        take_low = True
        while hi <= lo:
            if take_low:
                zig.append(middle[lo]); lo -= 1
            else:
                zig.append(middle[hi]); hi += 1
            take_low = not take_low
        return [opener, *zig, best]

    # ── Content generation ────────────────────────────────────────────

    async def _generate_content_for_game(self, game: Game) -> Content:
        log.info("pipeline.generating", game=game.name, universe_id=game.universe_id)
        loop = asyncio.get_event_loop()

        # 1. Download visual assets
        async with ScreenshotEngine() as screenshot:
            assets = await screenshot.capture_game_assets(
                universe_id=game.universe_id,
                thumbnail_url=game.thumbnail_url,
                icon_url=game.icon_url,
            )

        thumb_path = assets.get("thumbnail")
        game_thumb = Path(thumb_path) if thumb_path else None

        # 2. AI rating — sync Claude SDK call, run in thread to avoid blocking event loop
        rating = await loop.run_in_executor(
            None,
            functools.partial(
                self._rating.rate_game,
                name=game.name,
                description=game.description or "",
                visits=game.visits,
                active_players=game.active_players,
                favorites=game.favorites,
                like_ratio=game.like_ratio,
                genre=game.genre or "",
                created_at=str(game.created_at_roblox) if game.created_at_roblox else None,
                updated_at=str(game.updated_at_roblox) if game.updated_at_roblox else None,
                viral_score=game.viral_score,
            ),
        )

        # Steps 3 & 4 both depend only on the rating and are independent of each
        # other, so run them CONCURRENTLY instead of serially (was two awaited
        # executor calls back-to-back). Captions + thumbnails overlap.
        #
        # The TikTok *video* captions (description_a/b) cost a SECOND Claude call
        # per game. The carousel — the primary product — never uses them, so when
        # videos are off we build them locally (rule-based) and save that call.
        if self._settings.GENERATE_VIDEOS:
            desc_fut = loop.run_in_executor(
                None,
                functools.partial(
                    self._description.generate,
                    name=game.name,
                    score=rating.score,
                    label=rating.label,
                    verdict=rating.verdict,
                    visits=game.visits,
                    genre=game.genre,
                    hook_text=rating.hook_text,
                    controversy_angle=rating.controversy_angle,
                ),
            )
        else:
            desc_fut = loop.run_in_executor(
                None,
                functools.partial(
                    self._description.generate_local,
                    name=game.name,
                    score=rating.score,
                    label=rating.label,
                    visits=game.visits,
                    genre=game.genre,
                ),
            )
        thumb_fut = loop.run_in_executor(
            None,
            functools.partial(
                self._thumbgen.generate_both,
                game_name=game.name,
                universe_id=game.universe_id,
                score=rating.score,
                label=rating.label,
                hook_text=rating.hook_text,
                thumbnail_path=game_thumb,
                thumbnail_url=game.thumbnail_url,
            ),
        )
        desc, (thumb_a, thumb_b) = await asyncio.gather(desc_fut, thumb_fut)

        # 5. TikTok performance predictions
        from src.discovery.viral_scorer import ViralScorer, ScoreBreakdown  # noqa: PLC0415
        async with get_session() as session:
            from sqlalchemy import select as sa_select  # noqa: PLC0415
            from src.database.models import ModelWeights  # noqa: PLC0415
            weights = await session.scalar(
                sa_select(ModelWeights).order_by(ModelWeights.updated_at.desc()).limit(1)
            )
        scorer = ViralScorer(weights=weights)
        breakdown = ScoreBreakdown(
            viral_score=game.viral_score,
            growth_velocity_score=game.growth_velocity_score,
            engagement_ratio_score=game.engagement_ratio_score,
            novelty_score=game.novelty_score,
            retention_proxy_score=game.retention_proxy_score,
            update_freshness_score=game.update_freshness_score,
        )
        predictions = scorer.predict_tiktok_performance(breakdown, rating.score, game.name)

        # 6. Video assembly — the single most expensive step (moviepy + ffmpeg +
        # gTTS). The carousel is the primary product and doesn't use the video, so
        # this is SKIPPED unless GENERATE_VIDEOS is enabled. This is the biggest
        # speed-up on the carousel warm-up path (no per-game video render).
        video_path = None
        if self._settings.GENERATE_VIDEOS:
            features = self._extract_features(game.description or "", 3)
            video_path = await loop.run_in_executor(
                None,
                functools.partial(
                    self._video.assemble,
                    universe_id=game.universe_id,
                    game_name=game.name,
                    score=rating.score,
                    label=rating.label,
                    verdict=rating.verdict,
                    hook_text=rating.hook_text,
                    visits=game.visits,
                    active_players=game.active_players,
                    favorites=game.favorites,
                    tts_script=rating.tts_script or "",
                    thumbnail_path=game_thumb,
                    thumbnail_url=game.thumbnail_url,
                    features=features,
                ),
            )

        # 7. Persist content package
        import json as _json  # noqa: PLC0415
        content = Content(
            game_id=game.id,
            screenshot_path=str(thumb_path) if thumb_path else None,
            thumbnail_a_path=str(thumb_a),
            thumbnail_b_path=str(thumb_b),
            video_path=str(video_path) if video_path else None,
            rating_score=rating.score,
            rating_label=rating.label,
            rating_verdict=rating.verdict,
            rating_breakdown=_json.dumps(rating.breakdown),
            # Record provenance: if the AI call failed, this is rule-based output.
            # The carousel selection gate excludes it so fabricated ratings never
            # ship as if AI-curated (audit C1).
            used_fallback=bool(getattr(rating, "used_fallback", False)),
            hook_text=rating.hook_text,
            carousel_caption=rating.carousel_caption,
            tts_script=rating.tts_script,
            description_a=desc.description_a,
            description_b=desc.description_b,
            hashtags=_json.dumps(desc.hashtags),
            predicted_viral_score=predictions["predicted_viral_score"],
            predicted_engagement_score=predictions["predicted_engagement_score"],
            predicted_follow_conv_score=predictions["predicted_follow_conv_score"],
            predicted_novelty_score=predictions["predicted_novelty_score"],
            queue_priority=predictions["queue_priority"],
            status="pending",
        )

        async with get_session() as session:
            session.add(content)
            await session.flush()
            g = await session.get(Game, game.id)
            if g:
                g.content_generated = True

        log.info(
            "pipeline.content_generated",
            game=game.name,
            score=rating.score,
            label=rating.label,
            priority=predictions["queue_priority"],
        )
        return content

    @staticmethod
    def _extract_features(description: str, count: int) -> list[str]:
        if not description:
            return []
        sentences = [s.strip() for s in description.replace("\n", ". ").split(".") if len(s.strip()) > 20]
        return sentences[:count]
