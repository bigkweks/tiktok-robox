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
import json
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
from src.content.gazette_generator import GazetteCarouselGenerator
from src.integrations.buffer_client import BufferClient, BufferError
from src.content.description_engine import DescriptionEngine
from src.content.rating_engine import RatingEngine
from src.content.thumbnail_generator import ThumbnailGenerator
from src.content.video_assembler import VideoAssembler
from src.database.connection import get_session, init_db
from src.database.models import Account, CarouselPost, Content, Game
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
        # Choose carousel renderer based on CAROUSEL_STYLE setting.
        # "gazette"  → newspaper cover + Gazette review columns (Direction 1+2).
        # "classic"  → original Roblox-style photo carousel.
        if self._settings.CAROUSEL_STYLE == "gazette":
            self._carousel = GazetteCarouselGenerator()
            log.info("pipeline.carousel_style", style="gazette")
        else:
            self._carousel = CarouselGenerator()
            log.info("pipeline.carousel_style", style="classic")
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

        # Multi-account posting: register 3 daily cron jobs per active account.
        # Each account posts to a different Buffer/TikTok profile. Accounts are
        # managed via the /accounts dashboard page.
        await self._seed_default_account_if_needed()
        await self._register_all_account_jobs()

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

    async def run_content_factory(self, batch_size: int = 5) -> dict:
        """
        Generate content packages for the top unprocessed games.
        Each game gets: screenshots, thumbnail A+B, AI rating, captions, video.
        """
        log.info("pipeline.content_factory.start")
        games = await self._detector.get_top_unprocessed(limit=batch_size)
        if not games:
            log.info("pipeline.content_factory.no_games")
            return {"processed": 0}

        sem = asyncio.Semaphore(5)

        async def _process(game: Game) -> None:
            async with sem:
                await self._generate_content_for_game(game)

        results = await asyncio.gather(*[_process(g) for g in games], return_exceptions=True)
        processed = sum(1 for r in results if not isinstance(r, Exception))
        for game, result in zip(games, results):
            if isinstance(result, Exception):
                log.error(
                    "pipeline.content_factory.game_failed",
                    game=game.name,
                    universe_id=game.universe_id,
                    error=str(result),
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

    # ── Multi-account helpers ─────────────────────────────────────────

    async def _seed_default_account_if_needed(self) -> None:
        """
        On first startup, if no accounts exist and .env has a Buffer profile ID,
        create a default Account from the legacy env-var settings so existing
        single-account users get zero-downtime migration.
        """
        if not self._settings.BUFFER_EMAIL:
            return
        if not self._settings.BUFFER_TIKTOK_PROFILE_ID:
            return
        async with get_session() as session:
            from sqlalchemy import func as _func  # noqa: PLC0415
            count = await session.scalar(select(_func.count(Account.id))) or 0
            if count > 0:
                return
            account = Account(
                slug="default",
                display_name=self._settings.CHANNEL_NAME or "Default",
                channel_name=self._settings.CHANNEL_NAME,
                channel_handle=self._settings.CHANNEL_HANDLE,
                brand_primary_color=self._settings.BRAND_PRIMARY_COLOR,
                brand_secondary_color=self._settings.BRAND_SECONDARY_COLOR,
                brand_accent_color=self._settings.BRAND_ACCENT_COLOR,
                carousel_style=self._settings.CAROUSEL_STYLE,
                buffer_tiktok_profile_id=self._settings.BUFFER_TIKTOK_PROFILE_ID,
                post_hour_1_utc=self._settings.MORNING_RUN_UTC_HOUR,
                post_hour_2_utc=self._settings.DEFAULT_POST_HOUR_2_UTC,
                post_hour_3_utc=self._settings.DEFAULT_POST_HOUR_3_UTC,
                is_active=True,
            )
            session.add(account)
        log.info("pipeline.default_account_seeded",
                 profile_id=self._settings.BUFFER_TIKTOK_PROFILE_ID)

    async def _register_all_account_jobs(self) -> None:
        """Register posting cron jobs for every active account with Buffer credentials."""
        if not self._settings.BUFFER_EMAIL:
            log.info("pipeline.accounts_disabled", reason="BUFFER_EMAIL not set")
            return
        async with get_session() as session:
            rows = await session.execute(
                select(Account).where(Account.is_active == True)  # noqa: E712
            )
            accounts = list(rows.scalars().all())
        n = 0
        for account in accounts:
            if account.buffer_tiktok_profile_id:
                self._register_account_jobs(account)
                n += 1
        log.info("pipeline.account_jobs_registered", accounts=n)

    def _register_account_jobs(self, account: Account) -> None:
        """Register 3 daily cron jobs for a single account (replace_existing=True)."""
        for slot, hour in enumerate([
            account.post_hour_1_utc,
            account.post_hour_2_utc,
            account.post_hour_3_utc,
        ], 1):
            self._scheduler.add_job(
                functools.partial(self.run_account_post, account.id),
                "cron",
                hour=hour,
                minute=0,
                id=f"account_{account.id}_slot_{slot}",
                name=f"{account.slug} slot {slot} ({hour:02d}:00 UTC)",
                misfire_grace_time=600,
                replace_existing=True,
            )
        log.info("pipeline.account_registered", slug=account.slug,
                 hours=[account.post_hour_1_utc, account.post_hour_2_utc,
                        account.post_hour_3_utc])

    def _deregister_account_jobs(self, account_id: int) -> None:
        """Remove all 3 posting cron jobs for a deactivated account."""
        for slot in (1, 2, 3):
            job_id = f"account_{account_id}_slot_{slot}"
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
        log.info("pipeline.account_deregistered", account_id=account_id)

    async def run_account_post(self, account_id: int) -> dict:
        """
        Scheduled job: generate one carousel for `account_id` and queue it in Buffer.

        Fired 3× per day per account (at each of the account's posting hours).
        The carousel generation, approval, and image gates are identical to the
        manual create-carousel flow — only the Buffer profile ID differs.
        """
        log.info("pipeline.account_post.start", account_id=account_id)

        async with get_session() as session:
            account = await session.get(Account, account_id)
            if not account or not account.is_active:
                log.warning("pipeline.account_post.skipped",
                            account_id=account_id, reason="inactive or not found")
                return {"status": "skipped", "account_id": account_id}
            # Detach from session so we can use the account object outside
            session.expunge(account)

        # 1. Generate + approve a carousel scoped to this account.
        factory_result = await self.run_carousel_factory(account=account)

        if not factory_result.get("carousels"):
            reason = factory_result.get("reason", "unknown")
            log.warning("pipeline.account_post.generation_failed",
                        account_id=account_id, reason=reason)
            # One retry — a first-pass rejection is often just a stale hook
            factory_result = await self.run_carousel_factory(account=account)

        if not factory_result.get("carousels"):
            reason = factory_result.get("reason", "unknown")
            log.warning("pipeline.account_post.failed_after_retry",
                        account_id=account_id, reason=reason)
            return {"status": "failed", "account_id": account_id,
                    "reason": reason, **factory_result}

        # 2. Retrieve the slide paths from the persisted CarouselPost row.
        gen_id = factory_result.get("generation_id", "")
        async with get_session() as session:
            from sqlalchemy import select as _sel  # noqa: PLC0415
            post_row = await session.scalar(
                _sel(CarouselPost)
                .where(CarouselPost.generation_id == gen_id)
                .limit(1)
            )
            if post_row is None:
                log.error("pipeline.account_post.post_not_found", gen_id=gen_id)
                return {"status": "failed", "reason": "post_record_not_found"}
            slide_paths_raw = _safe_json_load(post_row.slide_paths) if isinstance(
                post_row.slide_paths, str
            ) else (post_row.slide_paths or [])
            slide_paths = [Path(p) for p in slide_paths_raw] if isinstance(
                slide_paths_raw, list
            ) else []
            caption = post_row.caption or ""
            hashtags_raw = post_row.hashtags or "[]"
            hashtags = json.loads(hashtags_raw) if isinstance(hashtags_raw, str) else hashtags_raw

        if not slide_paths:
            log.error("pipeline.account_post.no_slides", gen_id=gen_id)
            return {"status": "failed", "reason": "no_slide_paths"}

        # 3. Upload to Buffer using this account's TikTok profile.
        buffer_result = await asyncio.get_event_loop().run_in_executor(
            None,
            functools.partial(
                self._upload_to_buffer,
                account=account,
                slide_paths=slide_paths,
                caption=caption,
                hashtags=hashtags if isinstance(hashtags, list) else [],
            ),
        )

        overall = {
            "status": "success" if buffer_result.get("queued") else "partial",
            "account_id": account_id,
            "account_slug": account.slug,
            "part": factory_result.get("part"),
            "slides": len(slide_paths),
            "generation_id": gen_id,
            "final_score": factory_result.get("final_score"),
            **buffer_result,
        }
        log.info("pipeline.account_post.complete", **overall)
        return overall

    def _upload_to_buffer(
        self,
        account: Account,
        slide_paths: list[Path],
        caption: str,
        hashtags: list[str],
    ) -> dict:
        """
        Sync helper: upload a carousel to Buffer via the web interface.
        Called in an executor so the async event loop is never blocked.
        """
        email = self._settings.BUFFER_EMAIL
        password = self._settings.BUFFER_PASSWORD
        profile_id = account.buffer_tiktok_profile_id

        if not email or not password or not profile_id:
            log.warning("pipeline.buffer_upload_skipped",
                        account=account.slug, reason="credentials not configured")
            return {"queued": False, "buffer_updates": 0,
                    "error": "BUFFER_EMAIL / BUFFER_PASSWORD / profile ID not configured"}
        try:
            client = BufferClient(email, password)
            result = client.queue_gazette_carousel(
                profile_id=profile_id,
                slide_paths=slide_paths,
                caption=caption,
                hashtags=hashtags,
            )
            log.info("pipeline.buffer_upload_ok",
                     account=account.slug, profile_id=profile_id)
            return {"queued": True, "buffer_updates": result.get("updates", 1), "error": None}
        except BufferError as exc:
            log.error("pipeline.buffer_upload_failed",
                      account=account.slug, error=str(exc))
            return {"queued": False, "buffer_updates": 0, "error": str(exc)}
        except Exception as exc:
            log.error("pipeline.buffer_upload_unexpected",
                      account=account.slug, error=str(exc))
            return {"queued": False, "buffer_updates": 0, "error": str(exc)}

    async def run_carousel_factory(self, account: Optional[Account] = None) -> dict:
        """
        Batch 5 rated games into one photo carousel — the proven viral format.
        Picks games that already have ratings (content_generated=True) and
        haven't been included in a carousel yet, then generates all 6 slides.
        """
        import json as _json
        account_id = account.id if account else None
        log.info("pipeline.carousel_factory.start", account_id=account_id)

        # Pull 5 approved/rated content items not yet in a carousel
        async with get_session() as session:
            # Build a cooldown set: exclude games that appeared in a carousel
            # fewer than 50 unique other games ago (so no game repeats within
            # the next 50 unique featured games after its last use).
            # Scoped to this account so cross-account repeats don't count.
            from sqlalchemy import select as sa_select  # noqa: PLC0415
            cooldown_q = sa_select(CarouselPost.game_ids).order_by(
                CarouselPost.created_at.asc()
            )
            if account_id is not None:
                cooldown_q = cooldown_q.where(CarouselPost.account_id == account_id)
            hist_result = await session.execute(cooldown_q)
            ordered_appearances: list[int] = []
            for (row,) in hist_result:
                try:
                    ordered_appearances.extend(_json.loads(row))
                except Exception:
                    pass

            # For each game, find the index of its last appearance and count
            # how many unique games appeared after it.
            last_idx: dict[int, int] = {}
            for i, gid in enumerate(ordered_appearances):
                last_idx[gid] = i

            used_ids: set[int] = set()
            for gid, idx in last_idx.items():
                unique_after = len(set(ordered_appearances[idx + 1:]))
                if unique_after < 50:
                    used_ids.add(gid)

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
        # Part counter: per-account (from Account.part_counter) or global fallback
        if account is not None:
            part = account.part_counter
        else:
            part = self._carousel_part_counter
        edition = edition_for_games(batch_genres, part)
        ed_ok, ed_reason = validate_edition_match(edition, batch_genres)
        if not ed_ok:
            # Should not happen (edition_for_games only returns a fitting edition),
            # but if it ever does, fall back to a safe neutral edition.
            log.warning("pipeline.carousel_factory.edition_mismatch", reason=ed_reason)
            edition = "Hidden Gems"
        if account is None:
            self._carousel_part_counter += 1

        # HISTORICAL DEDUP: load per-account cover hooks + captions so each
        # channel's followers never see repeated hooks. Scoped to account_id.
        used_hooks_hist, used_caps_hist = await self._recent_text_history(
            limit=25, account_id=account_id
        )

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
            # Roll back the part counter (no part burned on rejected content).
            if account is None:
                self._carousel_part_counter -= 1
            return {"carousels": 0, "rejected": True, "part": part,
                    "final_score": approval.final_score,
                    "hard_failures": approval.panel.hard_failures}

        # ── NEAR-DUPLICATE GATE (vs shipped history) ──────────────────
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
            if account is None:
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
                # Pass AI sub-scores so GazetteCarouselGenerator can derive the
                # four Gazette letter sub-grades (Fun / Value / Original / Social).
                # Keys: fun_factor, replayability, originality, visual_quality,
                #       community — all 0–10 floats from RatingEngine.
                breakdown=_safe_json_load(c.rating_breakdown),
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
            if account is None:
                self._carousel_part_counter -= 1
            return {"carousels": 0, "rejected": True, "part": part,
                    "reason": "placeholder_thumbnails",
                    "message": render.failure_reason,
                    "placeholder_count": render.placeholder_count,
                    "failed_games": render.failed_games,
                    "failed_icons": render.failed_icon_games}

        slide_paths = render.slides

        # ── EXPORT VALIDATION GATE (safe-zone / dimensions / integrity) ──
        from src.content.export_validator import validate_carousel_export  # noqa: PLC0415
        export_check = validate_carousel_export([str(p) for p in slide_paths])
        if not export_check.ok:
            log.error("pipeline.carousel_factory.export_invalid", part=part,
                      reasons=export_check.reasons)
            if account is None:
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

        from datetime import timezone as _tz  # noqa: PLC0415
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
                account_id=account_id,
            )
            session.add(post)
            # Track carousel usage on each featured game so the 50-game cooldown
            # query has fresh data on the next run_carousel_factory call.
            now_utc = datetime.now(_tz.utc)
            for _, g in batch:
                game_row = await session.get(Game, g.id)
                if game_row:
                    game_row.times_carouseled = (game_row.times_carouseled or 0) + 1
                    game_row.last_carouseled_at = now_utc
            # Increment per-account part counter atomically in DB
            if account_id is not None:
                acc_row = await session.get(Account, account_id)
                if acc_row:
                    acc_row.part_counter = part + 1

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

    async def _recent_text_history(
        self, limit: int = 25, account_id: Optional[int] = None
    ) -> tuple[list[str], list[str]]:
        """Load per-account cover hooks and slide captions for dedup detection."""
        import json as _json  # noqa: PLC0415
        from sqlalchemy import select as sa_select  # noqa: PLC0415
        hooks: list[str] = []
        caps: list[str] = []
        try:
            async with get_session() as session:
                q = (
                    sa_select(CarouselPost.cover_hook, CarouselPost.slide_captions)
                    .order_by(CarouselPost.created_at.desc())
                    .limit(limit)
                )
                if account_id is not None:
                    q = q.where(CarouselPost.account_id == account_id)
                rows = await session.execute(q)
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
        # Guard against double-processing when two factory runs overlap (e.g.
        # startup task + scheduled job both pick up the same game before either
        # sets content_generated=True).
        async with get_session() as session:
            from sqlalchemy import select as _sa_select  # noqa: PLC0415
            already = await session.scalar(
                _sa_select(Content.id).where(Content.game_id == game.id).limit(1)
            )
            if already:
                log.info("pipeline.generating.skipped_duplicate", game=game.name)
                return await session.get(Content, already)

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

        # If the AI caption call failed on the video path, the captions are
        # rule-based — surface it loudly so degraded video copy is never mistaken
        # for AI output (audit M3). (generate_local on the carousel path is
        # intentional rule-based copy, not a failure, and is not flagged.)
        if self._settings.GENERATE_VIDEOS and getattr(desc, "used_fallback", False):
            log.warning("pipeline.description_fallback_active", game=game.name,
                        reason="anthropic_call_failed")

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


def _safe_json_load(raw: str | None) -> dict:
    """Parse a JSON string into a dict; return {} on any failure."""
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}
