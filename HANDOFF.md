# HANDOFF — Roblox TikTok Pipeline

> **New chat? Read this file first, then continue.** It is the complete,
> current state. Everything not in here is noise (old bugs already fixed).
> This file is the merge of the original handoff plus the stabilization &
> polish session — nothing has been dropped.

## Goal
Fully automated pipeline that finds underrated Roblox games, AI-rates them,
and produces TikTok content. Target: 10K followers in 30 days.
User is on an **iPad using GitHub Codespaces** — cannot run a real terminal
comfortably, so everything must work via `bash quickstart.sh`.

- **Branch (develop + push here only):** `claude/handoff-file-continue-nmksfs`
- **Repo:** `bigkweks/tiktok-robox`
- **Run it:** `bash quickstart.sh` (auto-pulls, installs, sets API key, serves
  dashboard at http://localhost:8000)
- **After pulling new work:** the uvicorn server runs with `reload=False`, so
  templates/code changes only show up **after a server restart**. Pull, then
  restart (`python main.py serve`) and hard-refresh the browser.

## THE CORE STRATEGY (most important thing)
We reverse-engineered a real TikTok that hit **118.5K views** (user sent 9
screenshots of its analytics). The winning format is a **6-slide photo
carousel**, NOT a single video:

- **Slide 0 = title card:** white background (pattern-interrupts the dark feed),
  big Poppins type "actually good ROBLOX games to play | part N | {edition}",
  two real expressive emoji stickers.
- **Slides 1-5 = game slides:** look like a genuine Roblox game page —
  rounded icon + name + creator + maturity badge header, the game's **real
  Roblox homepage thumbnail** as the hero, score + casual caption burned into
  the bottom (TikTok-classic white text + dark stroke), authentic stats row
  (👍 like% · 👥 active · 🔔 Notify · ⭐ Fav), real description filling the
  lower card, visit-count footer.

**Why it worked (from the analytics):**
- 23.9% of traffic came from **Search** ("roblox games to play",
  "roblox games to play with friends") → the title IS the search query.
- "Part N" + edition forces follows for the next drop.
- Game slides look authentic → instant trust, zero "produced" feel.
- Captions sound like a real teenage player, never a brand:
  "only escape room thats actually challenging", "GTA in roblox",
  "well made game i spent 30+ hours in", "MUST check out". (These are few-shot
  anchors in the rating prompt — see the caption safeguards note below.)

The carousel is the **primary** format. The video pipeline still exists
(video_assembler.py) but is secondary.

## Architecture / key files
```
src/discovery/
  roblox_client.py    Public Roblox API (/v1/games?universeIds=, no auth).
                      SEED_UNIVERSE_IDS = hand-picked games to seed crawl.
                      Discovery rebuilt on explore-api (primary) + search-api
                      (secondary). Bulk details sub-chunks on HTTP 400 and
                      SKIPS the `filters` sortId (it returns category IDs, not
                      universe IDs, which poisoned whole batches). Chunk size 50.
  trend_detector.py   Crawl→score→persist. get_top_unprocessed() re-ranks by
                      tiktok_candidacy (rewards the discoverable-not-famous gem).
                      Keyword searches run SEQUENTIALLY with a 1.5s sleep between
                      each (parallel gather tripped Roblox 429 rate limits).
  viral_scorer.py     Weighted multi-factor scoring + tiktok_candidacy() +
                      predict_tiktok_performance().
src/content/
  fonts.py            SHARED font/emoji loader. Poppins (bundled in
                      assets/fonts) + real Noto Color Emoji. ALL renderers use
                      this. load_font(weight,size) / emoji_image() / paste_emoji().
                      ALSO the mixed text+emoji renderer (added this session):
                      draw_mixed() draws a string that contains emoji by
                      splitting it into text runs (drawn with the font) and
                      emoji runs (composited as real Noto color glyphs).
                      contains_emoji() / strip_emoji() / measure_mixed() /
                      EMOJI_PATTERN. Arrows like "→" are deliberately NOT treated
                      as emoji.
  caption_utils.py    ★ Carousel caption safeguards. dedupe_carousel_captions()
                      rewrites duplicate / slang-crutch / stuttering / AI-tell
                      captions so no two slides read the same. has_internal_repetition(),
                      crutch_tag(), is_generic(), normalize_caption(),
                      has_ai_tell(), specificity_score(), _AI_TELLS,
                      _CURIOSITY_MARKERS, _OVERPROMISE.
  carousel_quality.py ★ Quality gate + auto-reviser. Scores 9 dimensions:
                      hook, curiosity, authenticity, specificity, shareability,
                      follow, readability, saveability, novelty. QualityReport
                      has passed (≥0.70) and top1pct_passed (≥0.80, hook≥0.65,
                      authenticity≥0.75). finalize_carousel(..., dna=) runs up to
                      3 passes, escalating caption-replacement threshold; the cover
                      hook comes from cover_generator.select_cover_concept (steered
                      by the extracted DNA when supplied). Returns dna_directives +
                      cover_concept. Targets top1pct_passed + a purposeful plan.
                      Also: review_carousel(), score_hook/caption/cta/readability/
                      saveability/novelty, pick_cover_hook() (edition-aware niche
                      hooks), pick_cta(), pick_footer_cta(), build_post_caption(),
                      build_carousel_hashtags(), banks COVER_HOOKS / CTA_LINES /
                      FOOTER_CTAS / ENGAGE_LINES / EDITION_HOOKS.
  review_panel.py   ★ NEW. Three-reviewer approval panel. evaluate_panel() →
                      PanelResult: 3 personas (Growth Strategist / Successful
                      Roblox Creator / Skeptical Viewer) each 0–100, a weighted
                      Final Quality Score (7 dims, FINAL_WEIGHTS), and
                      detect_hard_failures(). compute_dimensions(). APPROVE bars
                      (score≥80, every reviewer≥70, zero hard failures).
  content_approval.py ★ NEW. ContentApprovalSystem.approve() runs the mandatory
                      cycle Generate→Critique→Revise→Re-score→Critique→Finalize
                      (max 3). Returns ApprovalResult (approved, final_score,
                      panel, surviving content, per-cycle trail). Only approved
                      content is ever shown.
  content_dna.py    ★ NEW. Content DNA Extraction System. ContentDNAExtractor
                      sends carousel screenshots to Claude vision (injectable
                      vision_fn → testable offline) and extracts 14 DIMENSIONS as
                      Pattern(observation/confidence/evidence). synthesize_profile
                      builds the 5 Formulas (FORMULA_COMPOSITION). SINGLE_SOURCE_CAP
                      =0.65. merge_profiles = the learning step (corroboration
                      raises confidence). seed_prior_profile = offline baseline.
                      ContentDNAProfile.as_dict/from_dict.
  dna_store.py      ★ NEW. JSON corpus under output/content_dna/. DNAStore
                      save_screenshots/save_profile/list_profiles/
                      rebuild_consolidated/get_consolidated. Consolidated blueprint
                      is what generation reads. save_profile REFUSES priors and
                      rebuild_consolidated EXCLUDES priors (audit H2 — a failed
                      extraction must never pollute the blueprint).
  dna_directives.py ★ NEW. DNA → generation bridge. derive_directives(profile) →
                      GenerationDirectives (prefer_curiosity_gap/specificity/
                      first_person, max_hook_words, require_save/follow_trigger,
                      hook_keywords, weight). Consumed by cover_generator.
  cover_generator.py ★ Dedicated cover-generation system. 10 archetype
                      concepts (The Qualifier, The Pattern Break, The Niche Gate,
                      The Visit Count, The Insider, The Algorithm Accuser, The
                      Confession, The Anti-Viral, The Hidden Stat, The Scout
                      Report) scored on 6 dimensions (curiosity/clarity/
                      specificity/authenticity/novelty/readability). REJECT_FLOOR
                      = 0.40 eliminates any concept with a fatal weakness.
                      select_cover_concept(edition, part, used_hooks) returns the
                      scored winner. finalize_carousel() calls this instead of
                      pick_cover_hook(). CoverConcept / CoverScore dataclasses.
  creator_brief.py  ★ Creator-decision layer. EDITION_BRIEFS answers the
                      7 audience-inference questions per niche (who, why_care,
                      knows, believes, surprise, save_trigger, follow_trigger)
                      in niche-specific language. plan_carousel() assigns every
                      slide an explicit purpose (stop_scrolling, create_curiosity,
                      build_credibility, deliver_value, challenge_assumptions,
                      reveal_information, trigger_saving, trigger_sharing,
                      trigger_following). Dead slides (empty/generic/AI content)
                      flagged in report.issues. brief_for(edition) → AudienceBrief.
  rating_engine.py    Claude rates a game → RatingResult(score, label, verdict,
                      tts_script, hook_text, carousel_caption, used_fallback).
                      Prompt has HOOK RULES + CAROUSEL CAPTION VOICE. Prompt was
                      de-seeded so it no longer over-anchors "if ukuk"; stuttering
                      captions are sanitized at the source. used_fallback=True on
                      any AI failure → now PERSISTED on Content + excluded from
                      carousel selection (audit C1 — fallback never ships as AI).
  carousel_generator.py  ★ THE viral format. CarouselGenerator.generate(games,
                      edition, part_number) → RenderReport (6 slide PNGs + hero AND
                      icon provenance). CarouselGame dataclass. EDITIONS list carries
                      (label, theme_emoji, [stickers]). Strips emoji from free-text
                      so user/AI emoji can't tofu; "swipe ➡️" uses the Noto color
                      arrow. RenderReport.ok gates persistence: blocks on any
                      placeholder hero OR an icon that had a real URL but failed to
                      load (audit H1); a genuinely-absent icon URL doesn't block.
                      Unknown creator renders "Roblox creator", never "Roblox" (M2).
  description_engine.py  TikTok captions + hashtags. Hashtags lead with proven
                      search queries (#robloxgamestoplywithfriends etc).
                      generate_local() builds captions WITHOUT an API call (used
                      on the carousel path when GENERATE_VIDEOS is off).
                      DescriptionResult.used_fallback flags rule-based captions on
                      the AI path (audit M3); generate_local stays False (it's
                      intentional local copy, not a failure).
  ai_status.py      ★ NEW. AI credential validator. check_api_key(probe=) →
                      AIStatus distinguishing missing/malformed/invalid/
                      rate_limited/unreachable/valid (+ fallback_active). Injectable
                      probe (token-free models.list) so it's testable offline.
                      Used at startup, dashboard (/api/ai-status), onboarding.
  dedup.py          ★ NEW. Cross-post duplicate detection. similarity() (token
                      Jaccard + difflib ratio), is_near_duplicate(), dedupe_batch(),
                      most_similar(), normalize(). Stops the same hook/caption
                      shipping to the same followers across parts.
  edition_match.py  ★ NEW. Genre↔edition. edition_for_games() derives the edition
                      from the batch's genres (was a blind counter rotation);
                      validate_edition_match() rejects a themed cover that doesn't
                      fit the games. GENRE_EDITIONS / NEUTRAL_EDITIONS / MIN_GENRE_MATCH.
  export_validator.py ★ NEW. validate_carousel_export() — pre-persist + pre-export
                      gate: exact 1080×1920, not blank, not corrupt/missing, no
                      placeholder hero. ExportValidation(ok, reasons).
  pil_compat.py     ★ NEW. ensure_resampling() restores Image.ANTIALIAS etc. for
                      moviepy 1.0.3 on Pillow 10+ (called before the moviepy import).
  video_assembler.py  Secondary 9:16 video (moviepy + gTTS, Ken Burns, captions,
                      animated score count-up). Gated behind GENERATE_VIDEOS
                      (default off — carousel is primary). Decorative emoji render
                      via draw_mixed; free-text fields are emoji-stripped.
  thumbnail_generator.py  Video cover variants A/B. Emoji stripped from labels,
                      game name, and hook so they never tofu.
src/learning/        ★ NEW. Performance Learning System (JSON corpus under
                      output/performance/). components.py (classify_hook/cta,
                      structure_signature, detect_ai_signals → strategy families).
                      genome.py (CarouselGenome — the feedback-architecture record:
                      topic/hook/cover/slides/cta/DNA/settings/quality+authenticity
                      scores/outcome; edit_resilience_from_cycles). ranking.py
                      (effectiveness, Wilson success_confidence, diversity, novelty,
                      component_stats, capped anti-convergence component_bias;
                      BIAS_CAP, DOMINANCE_SHARE). evaluation.py (strong/weak/
                      overused/emerging, selection_frequency, survival_rate).
                      insights.py (build_insights + improvement_trend).
                      performance_store.py (PerformanceStore: record/list/count/
                      update_outcome/component_bias/insights). recorder.py
                      (build_genome bridges an ApprovalResult → a classified genome).
src/scheduler/pipeline.py  Orchestrator (APScheduler). Jobs: discovery (4h),
                      content_factory (4h), carousel_factory (8h),
                      queue_maintenance (12h), analytics_update (24h).
                      run_carousel_factory() batches 5 rated games, loads the
                      consolidated Content DNA, runs the MANDATORY ContentApprovalSystem
                      and persists a CarouselPost (status=approved, +review_score
                      /review_summary) ONLY if it passes review. run_create_carousel()
                      = the one-action orchestrator (build now / retry / warm up
                      via _warmup_for_carousel).
src/api/dashboard.py  FastAPI. Pages: / , /carousels (shows the review panel +
                      one-tap "Save N slides + caption"), /queue, /games, /analytics,
                      /dna (upload winners → 5 formulas + 14 patterns + confidence).
                      Endpoints: /pipeline/create-carousel (the one-action CTA),
                      /pipeline/run-carousel, /dna/extract (POST screenshots),
                      /api/dna/consolidated, /analytics/ingest (validates
                      content_id), /analytics?content_id=N (prefill),
                      /carousel/{id}/download (zip of all slides). build_slides_zip()
                      helper bundles slides.
src/config.py         Settings. channel_name_display / channel_handle_display
                      strip emoji from CHANNEL_NAME/HANDLE before burn-in.
src/analytics/feedback_loop.py  Manual analytics ingest + weight update.
                      ingest_manual() rejects a non-existent content_id (was
                      silently writing orphan rows). get_performance_summary()
                      now also returns avg_follows_per_post.
src/database/models.py  Game, Content (+carousel_caption, +used_fallback cols),
                      CarouselPost (+review_score / review_summary), PostAnalytics,
                      ModelWeights, CrawlLog.
src/database/connection.py  init_db() creates tables + auto-migrates
                      content.carousel_caption, content.used_fallback, and
                      carousel_posts.review_score / review_summary for existing DBs
                      (SQLite WAL).
src/api/templates/   Premium dark theme (no template tells). base.html holds the
                      design system: .metric/.kv/.workflow-steps/.count-pill/
                      .action-hint/.review-panel + shared createCarousel(). index,
                      carousels (review panel + one-tap export + Create CTA), queue,
                      games, analytics, content_detail, dna.
```

## Environment constraints (important)
- **This Claude sandbox cannot reach roblox.com or tiktok.com** (network
  allowlist). The **Codespace can**. So: real game thumbnails/icons only load
  when the user runs it in their Codespace. In the sandbox we test layout with
  placeholder images.
- moviepy/ffmpeg may be absent in the sandbox; PIL/numpy always work, so we
  verify image slides by rendering PNGs and viewing them.
- Anthropic API key lives in `.env` (ANTHROPIC_API_KEY). Model: `claude-sonnet-4-6`.
- `tiktok_robox.db` is local-only (untracked); quickstart.sh handles it.
- **Noto Color Emoji** must be present (`/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf`)
  for emoji to render; it is on the Codespace image. fonts.py falls back gracefully.

## State: what works now (all pushed)
- **Discovery works** — rebuilt on explore-api + search-api; proven finding
  ~340 hidden-gem games (750K–16M visit range) in the Codespace.
- Carousel generator produces all 6 slides in <1s, real Poppins + real emoji,
  game art as hero, authentic Roblox-page look. Verified by rendering.
- Rating engine outputs carousel_caption in the viral creator's voice; the
  carousel pipeline de-dupes captions so a post never repeats the same phrase.
- **Emoji render correctly everywhere** (carousels, video, thumbnails) — no
  more tofu boxes. Verified by rendering slides and inspecting them.
- Dashboard is a polished dark theme. /carousels reviews + approves/rejects,
  **one-step "Save all 6 slides to Photos"** (Web Share → iPad Photos, zip
  fallback), copy caption, **Mark as Posted**.
- Content lineage is explicit: Content #N / Carousel #N chips on cards + detail,
  status + posted state shown, analytics deep-links from each posted item.
- Analytics ingest validates the Content ID; the 10K-goal projection uses real
  follows-per-post.
- Pipeline batches carousels every 8h; one-click **"Create a carousel"** does the
  whole chain (discover → rate → build → review) from any state.
- Video + thumbnail pipeline intact (badge-overlap bug fixed).
- **Every carousel passes a mandatory 3-reviewer approval panel** before it's
  persisted — the user never sees a first draft, only survivors (shown with their
  Final Quality Score + the three reviewer scores).
- **Dashboard is a premium, restrained creator tool** (no template tells — no
  gradient hero, no emoji labels, no rainbow borders, one accent, clean hierarchy).
- **Test suite: 236 passing**. See "Testing" below.
- **Performance Learning System**: every generated carousel (approved or
  rejected) is recorded as a genome; components are ranked (success confidence /
  effectiveness / diversity / novelty), classified (strong/weak/overused/
  emerging), and a capped anti-convergence bias steers cover selection toward
  proven archetypes without letting one template dominate. Dashboard `/insights`.
- **Content DNA system**: upload screenshots of a proven carousel → Claude vision
  extracts WHY it worked across 14 dimensions into 5 reusable formulas with
  confidence scores; consolidated DNA drives cover generation. Dashboard `/dna`.

## Session changelog — Silent-Degradation Audit + Provenance Gates (latest)
Brief: audit the whole codebase for every place it silently produces
lower-quality content while *appearing* successful, write a severity-ranked
report, then fix it. The product must never quietly ship degraded content as if
it were the real thing. Full report lives in `AUDIT_SILENT_DEGRADATION.md` (10
findings, Critical→Low). **236 tests passing.**

The framing that drove the fixes: the prior remediation gated everything visible
in the rendered PNG (placeholder hero, dimensions, blank frame) but **nothing
gated provenance** — when the AI silently failed, rule-based output was persisted
indistinguishable from real AI output and sailed through downstream gates that
are themselves rule-based. These changes close that seam.

- **Provenance gate for AI-failure ratings — the Critical fix (`models.py`,
  `connection.py`, `pipeline.py`, `rating_engine.py`).** `RatingResult.used_fallback`
  was a DEAD flag — set on every Anthropic failure but read nowhere, never
  persisted. A deterministic name-hash fallback rating (which can score above the
  7.4 floor) flowed into approved carousels indistinguishable from real AI output;
  the only signal was a global key-state banner that misses transient
  429s/timeouts on a valid key. Fix: new `Content.used_fallback` column (+ SQLite
  auto-migration), the pipeline persists `rating.used_fallback`, and
  `run_carousel_factory` **excludes fallback content** from selection
  (`.where(Content.used_fallback.isnot(True))`) plus a defensive pre-approval
  batch check (mirrors the rating-floor gate). "Not enough games" now explains
  when AI fallback is the cause (so it's not mistaken for a discovery problem).
  UI: rule-based warning banner on content detail + a "rule-based" chip on the
  queue list. Test: high-scoring fallback content is excluded with
  `reason=fallback_content`.
- **Icon provenance gate (`carousel_generator.py`).** The header icon silently
  fell back to a synthetic letter-tile that was never recorded or gated, so a fake
  icon shipped beside a real hero while `RenderReport.ok` stayed True. `_fetch_icon`
  now returns the REAL icon or None; `_synthetic_icon` is separate; `RenderReport`
  records icon outcomes via `record_icon(ok=, had_url=)`. An icon that had a real
  URL but failed to load (transient/retryable) is a **blocking** failure like a
  placeholder hero; a genuinely-absent URL is recorded (`missing_icon_games`) but
  does NOT block (a retry could never produce it). `failure_reason` + pipeline log
  cover icons. Tests: URL-but-failed blocks; no-URL doesn't.
- **DNA "extraction" no longer fakes success (`dashboard.py`, `dna_store.py`,
  `dna.html`).** A failed vision call returned a generic prior, but `/dna/extract`
  reported `status:"extracted"` AND persisted the prior into the corpus, polluting
  the consolidated blueprint that steers all generation. Fix: a prior result is
  reported as `status:"no_signal"` with a clear message and is **never saved**;
  `DNAStore.save_profile` refuses priors; `rebuild_consolidated` excludes priors
  from the merge (also drops any legacy prior already on disk). The DNA page shows
  the failure as a warning instead of fake success. Tests: store refuses a prior;
  consolidated ignores a legacy prior.
- **No fabricated creator (`carousel_generator.py`).** The game slide credited an
  unknown creator to "Roblox" (the company) — a false on-image fact on a format
  whose whole value is authenticity. Unknown creators now render "Roblox creator",
  never falsely crediting Roblox itself.
- **Flagged caption fallback (`description_engine.py`, `pipeline.py`).**
  `DescriptionResult.used_fallback` is now set on the AI path when captions fall
  back to templates (NOT on `generate_local`, which is intentional local copy);
  the pipeline logs it loudly when videos are on, so degraded video copy is never
  mistaken for AI output. Test covers both.
- **Low items L2–L4 triaged as accepted residual risk** in the report (learning/
  DNA loads swallow to cold-start; edition→neutral "Hidden Gems" default; heuristic
  export checks) — they degrade robustness/telemetry, not shipped content.
- **Tests added/changed (all green):** `test_carousel_gates_integration.py`
  (fallback excluded from carousels), `test_thumbnail_gate.py` (icon-failure
  blocks / missing-icon doesn't), `test_dna_store.py` (store refuses prior,
  consolidated excludes legacy prior), `test_launch_polish.py` (description
  used_fallback flag). **230 → 236 passing.**

## Session changelog — Launch-Readiness Remediation (prior)
Brief: make the product trustworthy + launch-ready — fix every place degraded
content can appear successful, kill cross-post duplicates, enforce a rating
floor, match cover genre to games, remove auto-approval, validate exports, and
speed up generation. Trust beats convenience. **228 tests passing.**

**PHASE 1 — Trust & reliability (the launch blockers).**
- **Placeholder-thumbnail gate (P0-A).** `carousel_generator.generate()` now
  returns a `RenderReport` (successful/failed/placeholder counts + failed game
  names + `ok`/`failure_reason`). `_make_game_slide(report=)` records whether the
  REAL Roblox hero loaded. The pipeline REFUSES to persist a render whose report
  isn't ok (rolls back the part number, returns `rejected reason=placeholder_
  thumbnails` with a clear message); `run_create_carousel` surfaces it as
  `image_error`. A grey-box carousel can no longer be approved/exported/published.
- **API-key validation (P0-B).** New `src/content/ai_status.py` —
  `check_api_key(probe=)` distinguishes missing / malformed / invalid(revoked) /
  rate_limited / unreachable / valid, with an injectable probe (`models.list`,
  token-free) so it's testable offline. Validated at **startup** (dashboard),
  **on the dashboard** (`GET /api/ai-status` + a loud banner in base.html that
  polls and offers Re-check), and **onboarding** (`scripts/check_api_key.py`,
  called by quickstart.sh step 5b). `RatingResult.used_fallback` flags rule-based
  output and `rating.fallback_active` logs loudly — fallback is never mistaken
  for AI.

**PHASE 2 — Content quality (root causes, not symptoms).**
- **Rating floor `MIN_CAROUSEL_RATING=7.4`** enforced at SELECTION (SQL filter)
  AND as a defensive pre-approval check — a single below-floor game blocks the
  carousel.
- **Cross-post duplicate detection** — new `src/content/dedup.py` (normalized
  token-Jaccard + difflib ratio, `similarity` / `is_near_duplicate` /
  `dedupe_batch`). The pipeline loads cover hooks + captions of the last 25
  carousels (`_recent_text_history`), feeds them into the approval as
  `used_hooks`, and **rejects** an approved cover/caption that's a near-duplicate
  of history (`reason=near_duplicate`). Root cause fixed: dedup was previously
  per-run only, so the same followers saw repeated lines across parts.
- **Genre/edition match** — new `src/content/edition_match.py`. Edition is now
  DERIVED from the batch's genres (`edition_for_games`, was a blind counter
  rotation) and VALIDATED (`validate_edition_match`) so a "Horror edition" cover
  can't sit on non-horror games.

**PHASE 3 — Visual & export correctness.**
- **Export validation layer** — new `src/content/export_validator.py`
  (`validate_carousel_export`): exact 1080×1920 dims, not blank, not
  corrupt/missing, no placeholder hero. Wired pre-persist (pipeline) AND
  pre-export (`/download` → 409 with reasons).
- **PIL.Image.ANTIALIAS fix** — `src/content/pil_compat.py` `ensure_resampling()`
  restores the legacy resampling constants moviepy 1.0.3 needs on Pillow 10+
  (called before the moviepy import in video_assembler) — fixes the
  "module 'PIL.Image' has no attribute 'ANTIALIAS'" video crash.

**PHASE 4 — Workflow + analytics.**
- **No auto-approval.** Carousels persist as `status="pending_review"` (was
  auto-`approved`). Dashboard shows explicit **Approve / Reject / Regenerate**
  (`/carousel/{id}/regenerate` added); export + mark-posted are **gated** behind
  approval (server-side 409 + UI gating). Generate → Review → Approve → Publish,
  all in-app.
- **Carousel-centric identity.** New `CarouselPost` columns (auto-migrated):
  `cover_hook`, `slide_captions`, `generation_id`, `min_game_rating`,
  `exported_at`.

**PHASE 5 — Performance (measured, not guessed).**
- Profiled locally: carousel render ≈760ms, approval ≈4ms, export validation
  ≈154ms — local compute is NOT the bottleneck; per-game AI calls + the video
  render are (seconds each, network/ffmpeg).
- **`GENERATE_VIDEOS=False` by default** — the expensive per-game moviepy/ffmpeg/
  gTTS video is skipped on the (primary) carousel path; flip on only to post
  videos. Biggest warm-up speed-up.
- Caption + thumbnail generation (independent, both depend only on the rating)
  now run **concurrently** via `asyncio.gather` instead of serial executor awaits.

**Tests added (all green):** `test_thumbnail_gate.py`, `test_ai_status.py`,
`test_pil_compat.py`, `test_dedup.py`, `test_edition_match.py`,
`test_export_validator.py`, `test_workflow_gates.py`,
`test_carousel_gates_integration.py` (real temp-DB: rating floor + pending_review
persistence). **178 → 230 passing.**

**Launch polish (this session, all fixed):**
- **Responsive dashboard** — base.html now has `@media` breakpoints (1024/768/
  480px): the 7-link nav scrolls horizontally then collapses to icon-only
  (`.nav-text` spans hidden) on phones; page header stacks; tap targets ≥40px.
- **One Claude call per game on the carousel path** — `DescriptionEngine.
  generate_local()` builds the video captions rule-based (no API) and the
  pipeline uses it whenever `GENERATE_VIDEOS` is off, halving per-game API spend.
- **Lifespan migration** — `@app.on_event` startup/shutdown replaced with a
  FastAPI `lifespan` context manager (deprecation warnings gone).

**Remaining (documented, not blocking):** caption/hook banks could still be
expanded for even more variety (dedup already prevents cross-post repeats);
destructive endpoints are unauthenticated + bound to 0.0.0.0 (Codespaces ports
are private by default). Neither gates launch.

## Session changelog — Performance Learning System (prior)
Brief: build a feedback architecture so the platform continuously improves
generation quality from outcomes — learn which generated outputs consistently
produce the highest-quality content, rank every generation component, and feed
that back into generation while preventing convergence on one template.

- **New `src/learning/` package — the closed learning loop.** For *every*
  generated carousel (approved OR rejected) a `CarouselGenome`
  (`genome.py`) is recorded with the full feedback architecture the brief
  specified: Topic, Hook (+ classified family), Cover structure (the archetype),
  Slide count (+ structure signature), CTA style (+ family), Content DNA profile
  fingerprint that steered it, Generation settings (cycles / dna-driven /
  perf-biased), Quality scores (the 7 weighted dims + final score) and
  Authenticity scores (authenticity / ai_ratio / culture / novelty), plus the
  review outcome (approved, hard failures, quality-review fail reasons, reviewer
  scores, AI signals detected) and a slot for *realised* saves/follows the
  analytics loop can patch in later.
- **Component taxonomy (`components.py`).** The system learns at the level of
  reusable building blocks. `classify_hook` / `classify_cta` bucket the literal
  text into strategy *families* (qualifier / stat / confession / accusation /
  paradox / insider / curiosity; save / question / follow / engage) so the
  learner recognises the *pattern*, not the phrase — and so it generalises to
  AI-generated wording the banks never contained. `structure_signature` keys on
  slide-count + edition; `detect_ai_signals` reuses the gate's `_AI_TELLS` vocab.
- **Ranking system (`ranking.py`).** Per component: `success_confidence` (a
  Wilson lower bound on its win-rate — grows with evidence, so one good drop is a
  guess and twenty is a law), `historical_effectiveness` (final score + edit-
  resilience, with realised outcomes dominating once known), `diversity_score`
  (1 − recent share) and `novelty_score`. These combine into a deliberately
  *small*, capped (`±BIAS_CAP=0.06`) additive `component_bias` the generator
  consults. **Anti-convergence is structural, not hoped-for:** the bias is
  centred on the category mean (so better-than-average → positive, worse →
  negative — it actually *prefers* winners, doesn't just discourage), and any
  component whose recent selection share exceeds `DOMINANCE_SHARE=0.40` is forced
  to a negative bias regardless of how well it performs. Verified: the single
  strongest cover archetype, once overused, is throttled below a fresh emerging
  alternative.
- **Evaluation framework (`evaluation.py`).** Classifies every component as
  **strong / weak / overused / emerging** (a component can be both strong *and*
  overused — a winner starting to take over), tallies selection frequency
  (which hooks/covers/structures/CTAs are picked most), and computes the corpus
  `survival_rate` (share that survived review/editing with minimal changes —
  proxied by edit-resilience: approved on cycle 1 = survived intact).
- **Insights (`insights.py`) + `PerformanceStore` (`performance_store.py`).**
  JSON-backed corpus under `output/performance/` (same rationale as the DNA
  corpus: append-mostly, human-inspectable, no migration; `update_outcome`
  patches realised performance in place). `build_insights` produces the dashboard
  payload incl. an `improvement_trend` (older-half vs recent-half mean
  effectiveness) — the literal success-criterion metric that a creator generating
  carousels later gets better output than one generating earlier.
- **Wired into generation + pipeline.** `cover_generator.select_cover_concept`,
  `carousel_quality.finalize_carousel` and `content_approval.approve` take an
  optional `performance` map (clamped to `PERF_BIAS_CAP` in the selector,
  defence-in-depth). `pipeline.run_carousel_factory` loads the cover bias from
  the store, passes it to the approval system, and records the genome (both
  outcomes) — all in `try/except` so learning can never break generation. Cold
  start = empty bias = unchanged behaviour.
- **Performance Insights dashboard (`/insights` + `insights.html` + nav link).**
  Shows summary metrics, the getting-smarter trend, top hook/cover/CTA patterns
  (effectiveness bars + confidence + share + overused flag), most common failure
  patterns, most common AI signals detected, why outputs fail quality review, and
  the strong/weak/overused/emerging classification per category. `/api/insights`
  exposes the raw payload.
- **Tests +28** (`test_learning.py` 21, `test_learning_integration.py` 7):
  hook/CTA/structure classification + AI-signal detection, genome round-trip +
  edit-resilience decay, effectiveness (proxy + realised-dominates), Wilson
  confidence growing with evidence, is-success gate, component stats, capped/
  cold-start bias, **anti-convergence throttles the dominant pattern even when
  it's best**, strong/weak/overused/emerging buckets, selection frequency +
  survival rate, insights payload shape, improvement-trend detection, store
  record/list/update-outcome/corrupt-tolerance, the recorder bridge from a real
  approval run, generator bias changes the winner (and is bounded / no-op when
  empty), and the insights page renders empty + populated. **Full suite: 178 passing.**

## Session changelog — approval gate + premium UI + one-tap workflow (prior)
Brief: three goals in one session — (1) transform the dashboard to feel trusted,
professional, premium (not a template); (2) make content approval MANDATORY via
three independent reviewer personas with a revision cycle, so only the strongest
carousels ship; (3) collapse the create→export→publish workflow to the minimum
number of actions so the app feels effortless.

- **Mandatory three-reviewer approval gate (`review_panel.py` + `content_approval.py`,
  new).** A carousel is no longer complete when generated — only when it survives
  review. `review_panel.evaluate_panel` runs three independent personas, each
  scoring 0–100 through its own lens: **Growth Strategist** (stop-scroll /
  retention / saves / follows), **Successful Roblox Creator** (would I post /
  authentic / on-culture / original), **Skeptical Viewer** (seen before / feels AI
  / worth attention / keep swiping) — they're different weightings of shared
  signals so they genuinely disagree. A single **Final Quality Score** (0–100) is
  computed from the seven specified weights (Hook 20 · Curiosity 15 · Authenticity
  20 · Readability 15 · Retention 15 · Saveability 10 · Follow 5; Retention is
  derived from weakest-slide hold + novelty + slide-purpose + opener). `detect_hard_failures`
  auto-rejects on repetitive phrasing, generic hook, AI wording, weak CTA, or a
  low-value/purposeless/removable slide (read from the `creator_brief` plan).
  `ContentApprovalSystem.approve` runs the cycle Generate→Critique→Revise→Re-score→
  Critique→Finalize (max 3); between cycles it rotates away from a rejected cover
  hook and swaps the weakest caption for a stronger unused bank line, so each pass
  improves. Approval needs score ≥80 AND every reviewer ≥70 AND zero hard failures.
- **Pipeline enforces the gate (`pipeline.py`).** `run_carousel_factory` now calls
  the approval system and persists a `CarouselPost` ONLY when approved (rejected
  drafts are never written, and the Part number is rolled back for reuse). The
  surviving carousel records `review_score` + `review_summary` (new `CarouselPost`
  columns + SQLite auto-migration). Since the AI panel already vetted quality,
  carousels persist as `status="approved"` — the redundant human Approve click is
  gone.
- **One-action workflow (`pipeline.run_create_carousel` + `POST /pipeline/create-carousel`).**
  Time-to-first-generation went from 4 clicks across 2 pages (Run discovery →
  Generate content → switch page → Generate now, dead-ending at "not enough games")
  to ONE button: it builds immediately when games are ready, retries once if the
  panel rejects a draft, or warms up the discover→rate→build chain in the
  background (`_warmup_for_carousel`) and reports it's on the way. Dashboard +
  Carousels both lead with a single "Create a carousel" CTA (shared `createCarousel`
  in base.html); the carousels empty state is that one button.
- **One-tap export.** "Save N slides + caption" now copies the caption to the
  clipboard AND opens the iPad share sheet in a single tap (was two separate taps),
  so the caption is ready to paste the moment the slides save. Mark-as-posted sits
  right beside it in the natural sequence. Removed the jarring `prompt()` modal for
  an optional TikTok Video ID on mark-posted (queue + content detail) → direct tap.
- **Premium UI redesign (all templates + `base.html`).** Audited every screen
  through five lenses and stripped the template tells: the red gradient marketing
  hero, emoji on every stat label (🎮✅⏳🚀❤️👀), rainbow colored card borders, a
  decorative icon on every card header (incl. a 🤖 robot on "AI Rating"), and the
  gold accent fighting the Roblox red on every number (page-level `var(--accent)`
  usage is now 0). Fixed a real trust bug: the dashboard "Last run" line actually
  showed page-load time — removed. New shared components: `.metric`, `.kv`,
  `.workflow-steps`, `.count-pill`, `.action-hint`, `.review-panel`. Voice unified
  to plain confident sentence case; loading states use a spinner. Also fixed a
  duplicate `discoverBtn` id in the cold-start dashboard.
- **Tests +21** (`test_review_panel.py` 16, `test_workflow.py` 6 incl. orchestrator
  build/retry/warm-up/no-double-warm, `test_carousel_download` updated for the
  combined export button). **Full suite: 150 passing.**

## Session changelog — Content DNA Extraction System (prior)
Brief: the platform's purpose is not to generate carousels but to identify *why*
previously successful carousels performed well and replicate those underlying
patterns — when screenshots are uploaded, extract the DNA (hook structure,
curiosity mechanisms, information hierarchy, slide progression, emotional
triggers, retention loops, swipe/save/follow triggers, CTA patterns, reading
pace, typography, visual hierarchy, content density) into a structured blueprint
of 5 formulas (Hook / Slide / Retention / CTA / Visual), with a confidence score
on every pattern, and drive future generation from the extracted DNA instead of a
generic prompt. Learn "why did this work?", not "what does this look like?".

- **Core extractor (`src/content/content_dna.py`, new).** `ContentDNAExtractor`
  sends uploaded carousel screenshots to Claude (vision) and parses a structured
  per-dimension extraction: each of the 14 `DIMENSIONS` becomes a `Pattern`
  (observation = the MECHANISM/why, never the literal copy; plus `confidence` and
  `evidence`). `synthesize_profile` assembles the 14 patterns into the five
  `Formula`s via `FORMULA_COMPOSITION` (a formula's confidence is the mean of its
  driver confidences, softened when drivers are missing). A single carousel can
  never make us certain — `SINGLE_SOURCE_CAP = 0.65` caps every single-source
  pattern. The Claude call is injected (`vision_fn`) so the whole module is
  testable offline; if no key / the call fails / no images, it returns a clearly
  labelled low-confidence PRIOR profile (`seed_prior_profile`, seeded from the
  reverse-engineered 118.5K-view reference post) so the system always works.
- **Learning step (`merge_profiles`).** Consolidates many analysed carousels into
  one blueprint: a dimension reported by more winners gets higher confidence via
  `_corroborate` (merged = avg + (1-avg)·(k-1)/k, capped 0.98), so a pattern seen
  once is a guess and a pattern seen across five winners becomes a reliable law.
  The most-confident observation is kept as the canonical phrasing; `is_prior`
  only stays true if every source was a prior.
- **Persistence corpus (`src/content/dna_store.py`, new).** `DNAStore` saves each
  extracted profile + its screenshots as JSON under `output/content_dna/` and
  rebuilds a `_consolidated.json` blueprint on every save (the one generation
  reads). JSON-file-backed (not a DB table) on purpose: small, append-only,
  human-inspectable, and no SQLite migration. `get_consolidated()` falls back to
  the seeded prior when nothing's been uploaded.
- **DNA → generation bridge (`src/content/dna_directives.py`, new).**
  `derive_directives(profile)` turns a DNA profile into concrete
  `GenerationDirectives` (prefer_curiosity_gap / prefer_specificity /
  prefer_first_person, max_hook_words read from the observed reading-pace number,
  require_save/follow_trigger, hook signal keywords) — each gated by the DNA's
  confidence, with a `weight` that scales how hard it steers.
- **Wired into cover generation.** `cover_generator.select_cover_concept(...,
  dna=)` adds a confidence-scaled `_dna_bonus` so the winning archetype is the one
  the proven carousels actually used (verified: a high-specificity DNA makes "The
  Visit Count" — "scarier than doors. 40k visits." — win for Horror).
  `carousel_quality.finalize_carousel(..., dna=)` derives directives and threads
  them in, returning `dna_directives` + `cover_concept` in its result.
  `pipeline.run_carousel_factory` loads the consolidated DNA via `DNAStore` and
  passes it to `finalize_carousel`, logging `carousel_factory.dna_driven`.
- **Dashboard (`/dna`).** New page (`dna.html`) + DNA nav link: upload a winner's
  screenshots, see the 5 formulas with confidence bars, the 14-pattern table, and
  every extracted profile. Routes: `GET /dna`, `POST /dna/extract` (saves
  screenshots, runs extraction off the event loop, persists + reconsolidates),
  `GET /api/dna/consolidated`.
- **Tests +25** (`test_content_dna.py` 15, `test_dna_store.py` 8 incl. the
  directives→cover-selection bridge, `test_dna_dashboard.py` 2). Cover: all
  dimensions extracted, single-source cap, five-formula synthesis, prior/
  failed-vision/malformed-JSON/partial-pattern fallbacks, corroboration raises
  confidence past the cap, most-confident observation kept, prior ignored when a
  real profile exists, serialisation round-trip, store save/list/consolidate +
  screenshot save, directive derivation + reading-pace word cap, DNA steers cover
  selection, dna.html renders prior + extracted states. **Full suite: 129 passing.**

## Session changelog — dedicated cover-generation system (prior)
Brief: treat the cover (Slide 0) as its own scored competition rather than a
random hook rotation — generate 10 distinct concept archetypes per drop, score
each on six dimensions that drive stop-scroll performance, reject weak candidates,
and return the highest-composite winner to the renderer. The cover controls
stop-scroll rate, initial curiosity, and swipe initiation; a weak cover kills
the carousel before a single game slide is seen.

- **New `src/content/cover_generator.py` — dedicated cover-concept engine.**
  Defines 10 named archetype concepts (`The Qualifier`, `The Pattern Break`,
  `The Niche Gate`, `The Visit Count`, `The Insider`, `The Algorithm Accuser`,
  `The Confession`, `The Anti-Viral`, `The Hidden Stat`, `The Scout Report`),
  each with a base hook and edition-specific overrides (e.g. Horror edition
  Qualifier = "if you've already beaten doors" — naming a real Roblox game is
  the single strongest lever on specificity and authenticity).
  Six scoring dimensions with explicit weights: `curiosity` (0.25), `clarity`
  (0.20), `specificity` (0.20), `authenticity` (0.15), `novelty` (0.12),
  `readability` (0.08). `REJECT_FLOOR = 0.40`: any dimension below this
  eliminates the concept regardless of composite — prevents a one-dimension-
  strong entry winning with a fatal weakness elsewhere. `select_cover_concept()`
  returns the highest composite among passing candidates; falls back to
  ignoring `used_hooks` or all concepts if needed (never blocks generation).
  Scoring uses whole-word matching for short niche vocab (≤3 chars) to prevent
  false substring matches (e.g. "op" inside "people").
- **`carousel_quality.finalize_carousel` now calls `select_cover_concept()`.**
  Replaces the old `pick_cover_hook()` call so every carousel drop gets the
  scored winner for that edition, not a rotation-position from a flat list.
- **Tests: 18 new cases in `tests/test_cover_generator.py`.** Covers: exactly
  10 concepts generated, all dimensions in [0,1], composite matches weighted
  sum, edition-specific hook scores higher on specificity, Visit Count has
  specificity via Roblox metric "visits", Niche Gate names the community pain,
  Horror Qualifier names "doors", no concept contains an AI tell, bad hooks
  fail REJECT_FLOOR, good hook passes, selection returns highest composite,
  used-hook skipping, all 8 editions return valid concepts, `as_dict` shape.
  **Full suite: 104 passing.**

## Session changelog — creator-decision model + top-1% quality gate (prior)
Brief 1 (quality): treat every carousel as competing against the top 1% of
Roblox TikTok accounts — score Hook, Curiosity, Readability, Saveability,
Shareability, Follow conversion, Authenticity, Novelty; reject below threshold;
auto-regenerate weak slides until the bar is met.
Brief 2 (creator decisions): stop *generating carousels*, start *generating
creator decisions* — before building, infer the audience (who's scrolling, why
they care, what they know/believe, what surprises them, what makes them
save/follow); give every slide an explicit purpose; remove any slide that
serves none. The post should feel like a creator talking to an audience.

- **8-dimension quality system (`carousel_quality.py`).** Added three scorers to
  the existing six: `score_readability` (each caption scannable <2s — short,
  varied openers, no walls of text), `score_saveability` (list-reference value —
  concrete specificity + varied angles across the 5 slides), `score_novelty`
  (no crutch word used 3+ times across the batch, no structural monotony like
  every slide being "X in roblox"). `QualityReport` now carries all nine
  dimensions with re-balanced weights and a `top1pct_passed` property — the elite
  bar: overall ≥ 0.80 AND every checklist item AND hook ≥ 0.65 AND authenticity
  ≥ 0.75. Three new checklist items (`readable_slides`, `saveworthy`,
  `novel_language`) with their own issue messages.
- **Auto-regeneration loop (`finalize_carousel`).** Now runs up to 3 passes,
  escalating the caption-replacement threshold (0.55 → 0.60 → 0.65) and rotating
  to a stronger cover hook on each retry, exiting early once the top-1% bar AND a
  fully purposeful plan are both met. Always returns the best version it built
  (never an un-revised draft) plus an `attempts` count. Pipeline logs elite vs
  soft quality and the attempt count.
- **Creator-decision layer (`creator_brief.py`, new).** `EDITION_BRIEFS` encodes
  a real `AudienceBrief` per niche — the seven inference questions answered in
  niche-specific language (a horror fan who's *already beaten Doors*, believes
  *they've played everything scary*, would be surprised by *under-the-radar
  horror that lands a real scare*). `plan_carousel()` assigns every slide an
  explicit purpose from a fixed vocabulary (`stop_scrolling`, `create_curiosity`,
  `build_credibility`, `deliver_value`, `challenge_assumptions`,
  `reveal_information`, `trigger_saving`, `trigger_sharing`, `trigger_following`):
  cover stops the scroll, slide 1 builds credibility, the middle reveals, the
  standout slide challenges the "good = popular" belief, the closer triggers save
  + follow. A slide whose content serves no purpose (empty / generic / AI) is a
  **dead slide** — surfaced in `report.issues` so the regeneration loop replaces
  it rather than shipping dead weight. `finalize_carousel` emits the `plan`; the
  pipeline logs the inferred audience + the per-slide purpose sequence as the
  "why each slide ships" record.
- **Tests:** `test_creator_brief.py` (8) covers audience inference, fallback,
  niche-distinctness, purpose assignment, dead-slide flagging, serialisation, and
  finalize-emits-purposeful-plan. `test_quality.py` extended (+7) for the three
  new scorers, the elite bar, `as_dict` shape, attempt count, and empty-caption
  recovery. **Full suite: 86 passing.**

## Session changelog — app-wide authenticity audit (prior)
Brief: audit the whole app for patterns that read "AI/template-generated" and
fix the ones that genuinely hurt perceived authenticity, so the whole thing
feels like a real Roblox creator built it (not a SaaS startup). Two surfaces:
the content the tool PRODUCES (audience-facing) and the tool ITSELF (dashboard).

- **Identical hashtag wall every post → rotated.** The carousel pipeline pinned
  the SAME 8 hashtags on every drop. A fixed tag wall is both a human-readable
  template tell and a repetitive-content signal TikTok can suppress — and it
  caps reach. New `carousel_quality.build_carousel_hashtags(part, edition,
  game_names)`: keeps the two proven SEARCH anchors (`#robloxgames`,
  `#robloxgamestoplywithfriends`) on every post, then rotates a tail pool by
  part and adds the edition's niche tag + a lead-game slug tag, so every drop
  gets a distinct, on-topic set without losing the SEO. Wired into
  `pipeline.run_carousel_factory` (the hardcoded list is gone). Test asserts
  anchors-on-every-post + all sets distinct + niche tag present + no dupes.
- **Dashboard de-SaaS'd into a creator's first-person voice.** The tool read
  like a corporate product: brand "💎 RoboxPipeline — TikTok Automation", hero
  "💎 Roblox Hidden-Gem Factory 🚀 / Find underrated games → AI-rate them → drop
  scroll-stopping TikTok carousels", arrow-chain instructions, "in database"
  dev-speak. Arrow-chain value props, noun-stacked product names and "X Factory
  🚀" taglines are the fingerprint of AI-generated landing copy. Rewrote the
  brand → **"the gemvault"**, the hero into first person ("finding the roblox
  games before they blow up / i dig up the underrated ones, rate them honestly,
  and turn the best 5 into a carousel…"), the empty-state + "Top Game" + games
  subtitle into a creator's own words, and removed the prose arrow-chains. CTA
  "Review Carousels" → "review today's drop".
- **Deliberately KEPT (not tells):** the game slide's repeated structure (icon /
  name / thumb / score / pills / description) is *authentic* — it mimics a real
  Roblox game page, which is the whole point; identical-by-design ≠ templated.
  The 🔥 "hot pick" marker on each callout is a consistent creator brand signal,
  not a repetition tell. Stat-label emoji on the dashboard were left (they add
  personality; the SaaS *voice* was the real problem, now fixed).
- **Corporate fallback verdict → creator voice.** `rating_engine._fallback_rating`
  burned `"{name} shows strong engagement metrics."` as the verdict — and the
  verdict becomes the 🔥 "why it slaps" callout on the game slide, so an AI-call
  failure put a corporate metric line straight in front of the audience. New
  `_fallback_verdict(name, score)`: score-tiered, name-hashed, hyped-player voice
  ("criminally slept on, go play it now"). Tested: no AI tell, varies by game.

### Complete surface-by-surface audit (what was reviewed, not just what changed)
Every audience- and creator-facing surface was read end to end. Findings:
- **Cover slide** — fixed in the prior redesign (asymmetric, niche hook,
  credibility, natural CTA).
- **Carousel hashtags** — FIXED (rotation, above).
- **Rating fallback verdict** — FIXED (above).
- **Dashboard brand + hero + empty states** — FIXED (creator voice, above).
- **`caption_utils` genre/score/neutral banks** — reviewed, KEPT. Already
  specific, lowercase, varied teen-creator lines ("horror that actually scared
  me", "60 hours deep no regrets"); de-dup guarantees no repeat within a post.
  Not generic — no change earns its place.
- **`rating_engine` + `description_engine` prompts** — reviewed, KEPT. Both
  already carry explicit BANNED-AI-phrase lists, the "would a real 14-yo type
  this?" self-check, and sentence-shape variation rules. The AI-path fallbacks
  (`_fallback_a/_b`, `_fallback_tts/_hook`) are already in player voice.
- **Game-slide structure** — reviewed, KEPT (intentionally mirrors a real Roblox
  game page; identical-by-design ≠ templated).
- **Channel branding (`config.CHANNEL_NAME/HANDLE`)** — reviewed, KEPT. Generic
  placeholders ("RobloxGems") but env-overridable — that's the creator's real
  handle to set, not ours to invent.
- **Thumbnail "Follow @handle for more" CTA (video path)** — reviewed, KEPT.
  Generic-looking, but a "follow for more" cover label is standard real-creator
  practice, not an AI tell.
- **Remaining templates (queue / analytics / content_detail)** — reviewed,
  KEPT. Plain functional UI labels ("Content Queue", "Log Analytics for a
  Video"); a real creator's own tool has utilitarian labels too. Slang-ifying
  every label would be a forced change, not an authenticity gain.
- **Known lower-priority follow-up:** the secondary VIDEO path
  (`description_engine._build_hashtags`) still builds a near-identical tag set
  per genre — same tell as the carousel wall was, but video is secondary; rotate
  it the same way (reuse `build_carousel_hashtags`’s approach) if/when video is
  prioritised.
- Tests: **71 passing** (+1 hashtag rotation; fallback-verdict assertions folded
  into the existing rating test). Templates still render (`test_dashboard_views`).

## Session changelog — performance-first cover redesign (prior)
Brief: stop making the cover *prettier* — optimise it for stop-scroll, swipe-
through, saves and follows while staying minimal/premium and creator-made. The
old cover was a dead-centred, perfectly symmetrical "actually good ROBLOX games
to play" block floating in whitespace with a generic "swipe to save" CTA and
zero credibility signal — it read like a Canva/AI template. Rebuilt
`_make_title_slide` end to end.

- **Composition is now LEFT-ALIGNED + asymmetric off a Roblox-red rail.** A thick
  red vertical rail (`rail_x=100`, `rail_w=16`) brackets the keyword block. The
  structural (not decorative) use of brand red is what kills the symmetry, adds
  energy, and makes it read creator-made. Everything keys off `text_x` to the
  right of the rail. White canvas, black text, red as the only accent (unchanged
  palette + the no-purple QC test still holds).
- **4-tier hierarchy, eye travels top→down** (matches the brief's spec):
  1. small **niche curiosity hook** (strong dark type, not faint grey),
  2. **dominant ROBLOX** (auto-fit to width, the one red accent, ~250px),
  3. **edition-aware value/search line** (`_value_phrase`) that folds the niche
     INTO the proven search anchor — "horror games to play", "games to play with
     friends", etc. (every edition still contains "games to play" for SEO),
  4. small **credibility line** (`_credibility_line`) — the trust signal the old
     cover lacked: "part N · ranked, not random / i actually play these / vetted,
     not just viral …" (pairs the proven part-marker with a curation proof).
  Then a natural **CTA** ("save these for later" / "you'll want this list later"
  + red arrow) replacing the generic "swipe to save".
- **Niche-specific hooks** (`carousel_quality.EDITION_HOOKS`, keyed by edition):
  horror gets "hidden horror gems", "if you've already played doors", "too scary
  to go viral"…; every edition has its own niche bank. `pick_cover_hook(part,
  used, edition=)` now prefers the niche bank (the single biggest "does this feel
  AI?" lever) and falls back to the generic `COVER_HOOKS` — back-compatible: the
  no-edition call still works. `finalize_carousel` passes the edition through.
- **CTA pulled out of the occluded zone.** In-feed, TikTok overlays the caption/
  username/action rail across the lower ~25% of the image, so the old bottom CTA
  would be hidden. The whole hook→CTA unit is now seated at ~46% height (upper-
  middle clear zone), which also removes the dead lower gap — higher info density
  without clutter, exactly what the brief asked.
- **Decision: no raster visual on the cover.** The brief invited testing a small
  screenshot/blurred frame; rejected because (a) the cover has no single game to
  show, (b) the sandbox can't fetch art and a stock image would read templated/
  AI. The typographic asymmetry + red rail is the stronger, more authentic
  scroll-stopper. Documented so it isn't re-litigated.
- Verified by rendering covers across editions (horror/friends/anime/hidden
  gems) at full + feed-thumbnail scale, plus a full 6-slide `generate()` smoke.
- Tests +3 (now **70 passing**): niche hooks are edition-specific (and generic
  fallback still works); value phrase folds niche into the search anchor for
  every edition; credibility + CTA rotate and never reuse "swipe to save".

## Session changelog — cover spacing finalization (prior)
Incremental user-approved spacing tweaks to the cover slide after the minimal
redesign landed.

- **Block position** tuned to `block_top = 625` — the anchor for the ROBLOX
  wordmark. Moved the whole title block up from 715 in six approved increments.
- **Equal glyph-box whitespace around ROBLOX.** Measured the exact glyph boxes
  of "actually good" and "games to play" using Pillow `textbbox()`, then computed
  `ag_y` (the "actually good" baseline) so the gap between the bottom of the "g"
  in "actually good" and the top of "R" in ROBLOX equals the gap between the
  bottom of "X" in ROBLOX and the top of "g" in "games to play" — both 45 px.
- **Adaptive hook font** on cover: long curiosity hooks (e.g. "the ones your
  friends don't know yet") shrink from 38 px down in 2 px steps until the text
  fits within `W − 80 − kpad×2` pixels so nothing clips on any hook from the
  quality bank.
- Commits: `9031695` (breathe), `7048ec5` (tuck), `9c7500e` (even spacing).

## Session changelog — minimal Roblox-red redesign (prior)
Brief: clean, premium, minimal carousel with Roblox red as the ONLY accent.

- **Cover slide rebuilt as minimal/premium.** Removed the dark top "header bar"
  pill, the big purple ROBLOX box, all 4 scattered emoji stickers, and the dark
  edition pill. New clean hierarchy on white: curiosity hook (quiet grey) →
  "actually good ROBLOX games to play" with **ROBLOX in Roblox red** (the one
  accent) → "part N · edition" → a "swipe to save" CTA with a **drawn red
  triangle** (no emoji, no tofu). Generous whitespace; zero clutter.
- **Roblox red everywhere, used sparingly.** New `ROBLOX_RED = (226,35,26)`
  constant. Verdict callout rail and the last-slide follow chip recolored
  purple → red (thin rail / soft chip, not a fill). Fallback letter-icon palette
  de-purpled. Dashboard brand recolored purple → red too (base.html `--brand`,
  hero gradient, all `rgba(124,111,255,*)`, `#a78bfa`, 💜→❤️) — nav kept.
- **Emoji discipline (≤2 per slide, never decorative).** Game-slide description
  is now **clean text** (color emoji stripped — was a 🍋💵🤑 wall); name keeps its
  one authentic emoji, callout keeps 🔥 → ≤2. Stat-row glyphs are flat grey UI,
  not counted. Cover uses zero emoji.
- **Text safety.** New `_wrap_to_width()` greedy pixel-width word-wrap (cover
  hook + description + callout) so nothing clips or crosses the safe margin;
  hero font auto-shrinks if "ROBLOX" would exceed the margins. `SAFE=90` cover
  margin; game-slide content unified to one 48px left edge.
- **QC test** (`test_branding_is_roblox_red_not_purple`) asserts every slide has
  the red accent and **zero purple pixels**. Title-slide + description tests
  updated for the new minimal design.

## Session changelog — quality engine + authenticity (prior session)
Goal: make carousels read like a top human creator, not an AI template.
Added an internal quality gate that reviews + auto-revises every post first.

- **★ NEW `src/content/carousel_quality.py` — the review-before-presenting gate.**
  Deterministic, heuristic (no extra API calls). Scores a carousel 0..1 on
  hook / curiosity / authenticity / specificity / shareability / follow, runs
  the explicit review checklist ("would a creator post this?", "does the cover
  stop the scroll?", "any AI sentence?", "any repeated wording?", "specific
  enough?"), and **auto-revises** weak pieces before anything is shown:
  - `finalize_carousel(...)` — single entry point. Dedupes + de-AI-tells the
    captions, strengthens soft ones from genre/score banks, picks a vetted
    curiosity-first **cover hook** and a natural **CTA**, builds a de-templated
    **post caption**, and returns the `QualityReport`.
  - Banks (rotated, never one template): `COVER_HOOKS`, `CTA_LINES`,
    `FOOTER_CTAS`, `ENGAGE_LINES`. `build_post_caption` keeps the proven SEARCH
    anchor ("roblox games to play") but rotates everything around it.
  - Scorers: `score_hook/score_caption/score_cta`, `review_carousel`.
- **AI-fingerprint detection in `caption_utils`.** `_AI_TELLS` ("dive into",
  "unlock the", "the ultimate", "game-changer", "you won't believe"…),
  `has_ai_tell()`, `specificity_score()` (numbers / genre comparison / named
  mechanic), `_CURIOSITY_MARKERS`, `_OVERPROMISE`. `dedupe_carousel_captions`
  now rejects AI tells too. Slang ("fr", "ngl") is NOT treated as a tell.
- **Retention-arc sequencing** (`Pipeline._retention_order`). Slides no longer
  run highest→lowest (predictable = scrollable). Open strong, dip for contrast,
  **save the single best game for the LAST slide** (completion payoff).
- **Last-slide follow CTA.** The final game slide renders a soft brand chip
  ("part N+1 soon — follow") next to the visits footer — natural, not desperate.
  `CarouselGenerator.generate(..., cover_hook=, final_cta=)` threads both;
  `_make_title_slide(cover_hook=)` (adaptive font so long hooks fit);
  `_make_game_slide(final_cta=)`.
- **Prompts hardened** (rating + description engines): explicit BANNED AI/
  marketing phrase lists, an anti-pattern self-check ("would a real 14-yo type
  this or does it sound like an ad?"), and sentence-shape variation rules.
- **Pipeline wiring**: `run_carousel_factory` orders the batch, calls
  `finalize_carousel`, logs the `QualityReport` (`pipeline.carousel_factory
  .quality`), warns when a post is still soft, and passes the vetted hook/CTA
  into the renderer. The old `_build_carousel_caption` template is removed.
- **Before → after** (same broken batch): overall quality **0.27 → 0.89**;
  captions "fun game / dive into this / fun game" → genre-specific lines; cover
  "stop scrolling 🛑" → "the ones your friends don't know yet"; CTA "follow for
  more!!!" → "which one are you opening first?".
- Tests +12 (`tests/test_quality.py`): fingerprint + specificity, element
  scores, good-passes / bad-fails review, finalize cleans a messy batch, hook/
  CTA/post-caption variety, retention order saves best for last.

## Session changelog — Roblox-fidelity game slide (prior session)
Goal: make the carousel game slide look like a real Roblox game page.
Driven by two reference screenshots the user sent (Sell Lemons page).

- **Stat row rebuilt to match Roblox exactly** (the "like / active / notify /
  favorite" control bar). Was a centered 4-column row of color emoji framed by
  hairlines; now a **left-aligned row of light-grey rounded pills** with **flat
  monochrome glyphs** (Roblox uses grey icons, not playful color emoji). The
  like pill shows **👍 % 👎** together; then **👥 82.3K active**, **🔔 Notify**,
  **⭐**. Helpers: `_mono_icon` (recolors a Noto emoji silhouette to one grey),
  `_draw_stat_pills`, `_active_label` ("82.3K active" style), `_emoji_px`.
- **Color emoji kept in the game name + description** (was stripped). The real
  Roblox name "Sell Lemons 👍" and emoji-rich descriptions (🍋 💵 🤑 …) now render
  via `draw_mixed`, matching the live page. Name still fits/truncates (measured
  with `measure_mixed`).
- **Maturity is now plain grey text** ("Maturity: Minimal") under the creator,
  like Roblox — dropped the colored pill.
- **No Events section** (user asked not to include it) — slide never had one.
- Font: Roblox's "Builder Sans" isn't available in the sandbox (only Poppins +
  DejaVu); kept Poppins. If we want a closer face we'd have to bundle one.
- Test +1: name + description retain real color emoji on the game slide.

## Session changelog — engagement blitz (prior session)
Focused on watch-time / follow-rate maximisation + a real duplicate bug.
All on `claude/handoff-file-continue-nmksfs`.

1. **Duplicate game in carousel — FIXED.** `run_carousel_factory` joined
   Content×Game and took the top 5 rows, but a game can have >1 Content row
   (concurrent "Generate Content" runs both pick it before `content_generated`
   flips) and clones/re-uploads share a name under different universe IDs — so
   the same game could appear twice in one carousel. The batch now dedupes by
   **game id AND normalized name** (and still excludes games used in prior
   carousels). `universe_id` is already `unique` so the DB itself can't hold
   universe-level dupes.
2. **Carousel title slide rebuilt as a scroll-stopper** (`_make_title_slide`).
   Off-white pattern-interrupt kept, but now: a bold rotating **kicker pill**
   ("you NEED to save these", "stop scrolling 🛑", "no one is talking about
   these"…), a **brand-purple highlight box behind "ROBLOX"** (the biggest pop
   on a white feed), "part N · N games" subline, **4 scattered tilted emoji
   stickers** (was 2) drawn from richer per-edition sticker sets, and a bottom
   **"swipe ➡️ save the list 👇" CTA** (real Noto color glyphs, never tofu).
   `EDITIONS` now carries 4 stickers each; new `TITLE_KICKERS` list.
3. **Captions/descriptions diversified + energised.**
   - `caption_utils`: genre bank expanded (+tower defense, racing, survival,
     story, anime, clicker; 5 lines each) and score/neutral banks grown, so a
     5-slide carousel never reads samey.
   - `rating_engine._fallback_carousel_caption` now pulls from the shared banks
     and picks by a **hash of the game name** (was one fixed phrase per score
     tier → identical across a batch). Verdict prompt demands high energy +
     varied sentence shape.
   - `description_engine`: prompt rewritten for high-energy teenage-creator
     voice, reply-bait CTAs, varied openings; fallbacks A/B are now multi-option
     hash-picked and emoji-punchy (were one static line each).
4. **Dashboard homepage made eye-catching.** New gradient **hero banner**
   ("💎 Roblox Hidden-Gem Factory 🚀" + Review Carousels CTA) and emoji on every
   stat label (🎮 ✅ ⏳ 🚀 💜 👀).
5. **Game slides now hyped AND authentic.** Each game slide renders a punchy
   **"🔥 why it slaps" accent callout** (an AI pull-quote) above the real Roblox
   description. Reuses the already-generated `Content.rating_verdict` (no new DB
   column / migration); `CarouselGame.blurb` carries it, threaded in
   `run_carousel_factory`. The real description stays beneath (trimmed to 3 lines
   when a callout is present) so the slide keeps its authentic game-page look.
   Renderer wraps the blurb to ≤3 lines, grows the card to fit, and clears the
   visits footer. No blurb → no callout, full description block as before.
6. **Tests +4**: fallback-caption variety across games, new-genre captions
   resolve to specific (non-generic) lines, blurb callout draws a real color 🔥
   and fits, and the no-blurb path still renders.

## Session changelog — stabilization & polish (prior session)
Five reported problems + a bug sweep + follow-up polish + the iPad save feature.
All committed to `claude/handoff-file-continue-nmksfs`.

1. **Emoji tofu (□) fixed.** Root cause: `video_assembler.py` drew decorative
   emoji inline with the Poppins/Liberation text fonts (no emoji glyphs), so
   they rasterised as tofu. The carousel was already correct (it composites Noto
   color glyphs via `paste_emoji`). Fix:
   - Added `draw_mixed` + `contains_emoji` / `strip_emoji` to `fonts.py`.
   - Routed every video emoji line (👀 🔍 👁️ 👥 ⭐ 💎) through `draw_mixed`.
   - Feature bullets: `✓` (U+2713, blank in Noto) → `✔️` (U+2714, real color).
   - Carousel "swipe →" (U+2192, tofu in Poppins) → "swipe ➡️" (U+27A1, color).
   - Stripped emoji from free-text burned with the text font: game names,
     captions, creator, description, verdict, hook, and CHANNEL_NAME/HANDLE
     (via `config.channel_name_display` / `channel_handle_display`).

2. **Repeated "if ukuk" captions fixed.** Two causes: the rating prompt seeded
   "if ukuk" **twice** (model over-anchored), and captions were generated
   per-game with no cross-slide dedup, so a 5-game carousel could stack the same
   phrase. Fix:
   - De-seeded + diversified the prompt; added an explicit anti-crutch rule.
   - New `caption_utils.dedupe_carousel_captions()` rewrites duplicate /
     crutch-repeating / stuttering / generic captions to varied, genre+score
     appropriate lines (only one slang tag allowed per carousel). Wired into
     `pipeline.run_carousel_factory`.
   - Per-game stutters sanitized in `rating_engine`.

3. **Content ID workflow clarified + ingest hardened.** `ingest_manual` used to
   accept any `content_id` and write an orphan `PostAnalytics` row that vanished
   from every join (silent data loss). Fix: validate the content exists → 400
   with a clear message. UI: `Content #N` / `Carousel #N` id-chips on queue
   cards, carousels, and the post-package page, with status + posted state; the
   analytics form's Content ID field is explained + validated client+server side.

4. **Analytics deep-link.** "Log Analytics" buttons on posted content (queue
   footer + content detail) open `/analytics?content_id=N`, which prefills and
   confirms the Content ID with the game name and focuses the first metric — no
   manual ID entry.

5. **10K projection math.** Replaced the assumed-views-per-video estimate with
   real `avg_follows_per_post` (total_follows / total_posts) from the
   performance summary, with clean empty/zero states.

6. **Bug sweep.** Broken-image fallback (`imgFallback` in base.html swaps a
   broken thumbnail for an inline "no image" placeholder) + alt text on
   thumbnails; analytics watch-time/duration field hints.

7. **★ One-step "Save all slides to Photos" (iPad).** Previously you saved each
   of the 6 slides by hand. New per-carousel button uses the **Web Share API**
   (`navigator.share({files})`) so iPadOS shows a single "Save N Images" action
   that drops every slide into Photos at once. Fallback: `/carousel/{id}/download`
   streams all slides as one ordered `.zip` (desktop / browsers without file
   share). Needs HTTPS on iOS — the Codespaces forwarded URL is HTTPS, so it
   works there; plain-http LAN falls back to the zip.

## Posting is MANUAL by design (auto-upload removed)
We removed the automatic TikTok uploader. Automated **public** posting is not
achievable for this single-creator setup:
- TikTok's Content Posting API only allows **public** posts from apps that have
  passed TikTok's **audit**. Until audited, every post is forced to `SELF_ONLY`
  (visible only to the creator) and the account must be private at post time.
- Even in the best case it needs an OAuth + PKCE flow and a token-refresh job
  (access tokens expire in ~24h in sandbox), none of which existed — so the
  old "auto-post every 30 min" job would have died within a day.

So the flow is: generate → review → approve → **you** save the 6 slides (now
one tap via "Save all to Photos"), copy the caption, upload the photo carousel
to TikTok, then click **Mark as Posted**. This matches how the video pipeline
already worked.

**Removed earlier:** `src/content/tiktok_poster.py`, the `run_auto_poster`
pipeline job, the `/carousel/{id}/post` + `/setup` + `/privacy` + `/terms` +
`/app-icon.png` dashboard routes, the setup/privacy/terms templates, all
`TIKTOK_*` posting settings, `scripts/generate_app_icon.py`, and the
Netlify/Cloudflare/`docs/` static site + TikTok domain-verification files (these
existed only to get the posting app audited).

## Likely next steps (not yet done — pick up here)
> ✅ **Resolved in the launch-readiness session:** placeholder-thumbnail gate,
> API-key validation (startup/dashboard/onboarding), cross-post duplicate
> rejection, rating≥7.4 floor, genre↔edition match + validation, export
> safe-zone/dimension validation, ANTIALIAS fix, removal of auto-approval
> (manual Approve/Reject/Regenerate), carousel-centric `CarouselPost` columns
> (`generation_id`/`cover_hook`/`slide_captions`/`min_game_rating`/`exported_at`),
> `GENERATE_VIDEOS=False` + concurrent description/thumbnail + one-AI-call path,
> responsive dashboard, lifespan migration.
>
> ✅ **Resolved in the silent-degradation audit session** (see
> `AUDIT_SILENT_DEGRADATION.md`): provenance gate so AI-fallback ratings can't
> ship as if AI-curated (`Content.used_fallback` persisted + excluded from
> carousel selection + UI markers); icon provenance gate (fake letter-tile where
> a real icon URL failed now blocks); DNA extraction reports `no_signal` and
> never persists/merges a failed-extraction prior; unknown creator no longer
> falsely credited to "Roblox"; `DescriptionResult.used_fallback` flagged on the
> video path. Open residual (accepted, low): learning/DNA loads swallow to
> cold-start, edition→neutral default, heuristic export checks. Optional follow-up:
> make `used_fallback` a hard-failure inside the review panel too (M1).

1. **Feedback loop on carousels — PARTIALLY DONE.** The Performance Learning
   System now records a genome per carousel and learns from review-stage signals
   (quality scores, edit-resilience, approval). `CarouselPost` now carries a
   `generation_id` to link analytics. Still missing is *realised* TikTok
   analytics for carousels: add `/analytics/ingest-carousel`, extend
   `CarouselPost` with view/like/save/follow fields, and call
   `PerformanceStore.update_outcome(genome_id, {performance_index, samples})` so
   `ranking.effectiveness` lets measured performance dominate the proxy. (Store
   the genome_id on the CarouselPost to link them.)
2. **Caption A/B**: generate 2 caption variants per carousel and track which
   caption voice (genre-specific vs. score-tier vs. neutral) drives more saves.
3. ~~Expose quality/plan in dashboard~~ — **DONE** (the /carousels review panel
   now shows the Final Quality Score + the three reviewer scores). Could still add
   the inferred audience + per-slide purpose sequence to that panel.
4. **AudienceBrief → rating prompt injection**: feed `brief.surprise` and
   `brief.save_trigger` into the `RATING_PROMPT` so Claude's `carousel_caption`
   already writes toward what makes *this* audience save, not a generic voice.
5. **More edition variety / scheduling cadence** (currently 8 editions rotate).
6. **Verify the iPad "Save all to Photos" flow end-to-end on a real device**
   (logic + zip fallback are tested; the share-sheet step is iOS-only and can't
   be exercised in the sandbox).
7. ~~Per-slide download buttons~~ — **DONE** (replaced by one-step save).
8. **DNA → caption/blurb generation**: the extracted DNA currently steers the
   COVER (via `select_cover_concept`). Extend it to the per-slide captions and the
   "why it slaps" blurb — feed `Hook/Slide/Retention/CTA` formula observations
   into the `RATING_PROMPT` and `dedupe_carousel_captions` so the whole carousel,
   not just the cover, is generated from the proven DNA.
9. **Real-device DNA extraction**: the vision call is mocked in tests; run it
   once in the Codespace with a real Anthropic key against actual winner
   screenshots to confirm the prompt yields clean per-dimension JSON, then tune
   `_EXTRACTION_PROMPT` if any dimension comes back weak.
10. **DNA-weighted analytics loop**: once carousel analytics exist (item 1), feed
    realised saves/follows back to re-weight which extracted patterns matter most
    (raise/lower per-dimension confidence by measured performance, not just
    corroboration count). The Performance Learning System's `update_outcome` hook
    is the natural place to wire this — realised performance already dominates the
    effectiveness proxy once `outcomes.performance_index` is set.
11. **Extend the performance bias beyond the cover.** The learned bias currently
    steers cover-archetype selection. Extend it to hook family, CTA family and
    structure (the genome already records and ranks all of them) by threading the
    relevant `component_bias(category)` into caption/CTA selection — same capped,
    anti-convergence mechanism.
12. **Add the inferred audience + per-slide purpose to the /carousels panel** (the
    one leftover from next-step 3) and surface a per-carousel genome link on
    `/insights` for drill-down.

## Testing
Run `python -m pytest -q` (**230 passing**). Test files:
- `tests/test_scoring.py`, `tests/test_discovery.py`, `tests/test_content.py`
  — original suites (scoring, Roblox client/trend detector, rating/captions).
  `test_content.py` extended: fallback verdict no AI tell, score-tiered variety.
- `tests/test_emoji_rendering.py` — emoji detection/strip/segment, mixed render
  produces real color glyphs, ✔️ vs ✓, video stats/features slides, carousel
  title slide, arrow handling. Extended: cover value phrase, cover credibility/CTA.
- `tests/test_captions.py` — cross-slide dedup, stutter + crutch detection,
  generic-filler blocklist, genre-aware replacement.
- `tests/test_analytics_ingest.py` — ingest rejects missing content_id (no
  orphan rows) and marks valid content posted with correct KPIs.
- `tests/test_dashboard_views.py` — 10K projection branches + analytics prefill
  render (template-level).
- `tests/test_quality.py` — AI-fingerprint + specificity primitives, hook/
  caption/CTA scoring, good-passes/bad-fails review, finalize auto-revises a
  messy batch, hook/CTA/post-caption variety, retention-arc ordering, niche-
  specific edition hooks, hashtag rotation. Extended: 3 new scorer functions
  (readability/saveability/novelty), top-1% bar, `as_dict` shape, attempt count,
  empty-caption recovery.
- `tests/test_carousel_download.py` — zip bundling (ordering, skips missing) +
  the "Save all to Photos" button render + Web Share wiring.
- `tests/test_creator_brief.py` — every edition has a full 7-question brief,
  unknown/None falls back cleanly, briefs are niche-distinct, purpose assignment
  covers all slide roles, dead slides flagged with reasons, serialisation,
  finalize emits a purposeful plan.
- `tests/test_cover_generator.py` — 10 concepts generated, all dimensions in
  [0,1], composite formula verified, edition-specific hooks score higher on
  specificity, Horror Qualifier names "doors", no AI tells, REJECT_FLOOR
  mechanics, selection returns highest composite, used-hook skipping, all 8
  editions return valid concepts, as_dict shape.
- `tests/test_content_dna.py` (**new**) — extract returns all 14 dimensions,
  single-source confidence cap, 5-formula synthesis (drivers stay within their
  composition), no-images/failed-vision/malformed-JSON → prior, partial patterns
  keep only observed, formula confidence softened by missing drivers,
  corroboration raises confidence past the cap, most-confident observation kept,
  prior ignored when a real profile exists, profile round-trip, prior is labelled
  + sub-cap.
- `tests/test_dna_store.py` (**new**) — store save/list, consolidated starts as
  prior then merges after saves, screenshot save, directive inactive-for-prior /
  active-for-confident, reading-pace sets max words, DNA directives steer cover
  selection (and dna=None matches the base call).
- `tests/test_dna_dashboard.py` (**new**) — dna.html renders the 5 formulas + all
  14 dimensions in the prior state and the extracted-profiles state.
- `tests/test_review_panel.py` (**new**) — three named independent reviewers,
  the 7 FINAL_WEIGHTS match spec + sum to 1, final-score range, each hard-failure
  condition trips, strong carousel has none, weak carousel rejected, panel as_dict
  shape, and the approval cycle runs / terminates ≤3 / keeps the best / records the
  per-cycle trail.
- `tests/test_learning.py` (**new**) — hook/CTA/structure classification + AI-
  signal detection, genome round-trip + edit-resilience decay, effectiveness
  (proxy + realised-dominates), Wilson confidence growing with evidence, is-success
  gate, component stats, capped/cold-start bias, anti-convergence throttles the
  dominant pattern even when best, strong/weak/overused/emerging buckets, selection
  frequency + survival rate, insights payload shape, improvement-trend detection +
  min-sample, store record/list/update-outcome/corrupt-tolerance, and the recorder
  bridge from a real approval run.
- `tests/test_learning_integration.py` (**new**) — the performance bias is a no-op
  when empty (matches unbiased selection), can change the winning cover archetype,
  and is bounded (an absurd bias can't override the scored competition); the
  `/insights` page renders both the empty and populated states.
- `tests/test_workflow.py` (**new**) — the one-action orchestrator builds
  immediately when ready, retries once on panel rejection, reports retry when both
  drafts fail, warms up when games are scarce, and never double-warms.
- `tests/test_thumbnail_gate.py` (**new**) — RenderReport counts for all/one/all
  thumbnails failing, rate-limit + CDN-timeout → None, and the placeholder gate.
- `tests/test_ai_status.py` (**new**) — valid/invalid/empty/malformed/rate-limited/
  timeout credential states with an injected probe; default-probe SDK mapping.
- `tests/test_dedup.py` (**new**) — normalize/similarity/is_near_duplicate/
  dedupe_batch (exact, near, reordered, unrelated).
- `tests/test_edition_match.py` (**new**) — edition derived from genres, neutral
  fallback + rotation, validate rejects/accepts genre-specific editions.
- `tests/test_export_validator.py` (**new**) — valid passes; placeholder hero,
  wrong dims, blank, missing, corrupt, empty all fail.
- `tests/test_pil_compat.py` (**new**) — ANTIALIAS restored + idempotent + a real
  resize with the legacy constant.
- `tests/test_workflow_gates.py` (**new**) — pending_review hides export + shows
  Approve/Regenerate, approved unlocks export, AI banner on every page.
- `tests/test_carousel_gates_integration.py` (**new**) — real temp-DB: rating
  floor excludes weak games; a good batch persists status=pending_review with
  cover_hook/slide_captions/generation_id/min_game_rating.
- `tests/test_launch_polish.py` (**new**) — generate_local makes no API call;
  base.html ships responsive @media breakpoints + collapsible nav labels.

Sandbox verification pattern: render PNG slides and view them (no real network /
moviepy needed). Templates are validated by parsing all of them and rendering
with mock contexts.

## Conventions
- Develop + push ONLY to `claude/handoff-file-continue-nmksfs`.
- Don't create PRs unless asked.
- Don't put the model ID in commits/code.
- Commits use a `Co-Authored-By: Claude <noreply@anthropic.com>` trailer
  (model name per the active session) plus the session link trailer.
- **`/handoff` skill**: at the end of any session run `/handoff`. The skill
  at `.claude/skills/handoff/SKILL.md` documents what changed, merges the
  new changelog entry into `HANDOFF.md`, and commits + pushes. This keeps the
  file current so the next session never starts cold.
