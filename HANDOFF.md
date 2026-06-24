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
  carousel_quality.py ★ NEW. The "review before presenting" gate. Scores a
                      carousel (hook/curiosity/authenticity/specificity/
                      shareability/follow) + checklist, auto-revises weak pieces.
                      finalize_carousel() is the pipeline entry point; also
                      review_carousel(), score_hook/caption/cta, pick_cover_hook(),
                      pick_cta(), pick_footer_cta(), build_post_caption(), banks
                      COVER_HOOKS / CTA_LINES / FOOTER_CTAS / ENGAGE_LINES.
  rating_engine.py    Claude rates a game → RatingResult(score, label, verdict,
                      tts_script, hook_text, carousel_caption, ...). Prompt has
                      HOOK RULES + CAROUSEL CAPTION VOICE. Prompt was de-seeded so
                      it no longer over-anchors "if ukuk"; stuttering captions are
                      sanitized at the source.
  carousel_generator.py  ★ THE viral format. CarouselGenerator.generate(games,
                      edition, part_number) → 6 slide PNGs. CarouselGame dataclass.
                      EDITIONS list carries (label, theme_emoji, [stickers]).
                      Strips emoji from free-text (name/creator/caption/description)
                      so user/AI emoji can't tofu; "swipe ➡️" uses the Noto color
                      arrow (the plain "→" was tofu in Poppins).
  description_engine.py  TikTok captions + hashtags. Hashtags lead with proven
                      search queries (#robloxgamestoplywithfriends etc).
  video_assembler.py  Secondary 9:16 video (moviepy + gTTS, Ken Burns, captions,
                      animated score count-up). Decorative emoji (👀 🔍 👁️ 👥 ⭐ 💎)
                      now render via draw_mixed (were tofu); feature bullets use
                      the color check ✔️ (U+2714); free-text fields are emoji-stripped.
  thumbnail_generator.py  Video cover variants A/B. Emoji stripped from labels,
                      game name, and hook so they never tofu.
src/scheduler/pipeline.py  Orchestrator (APScheduler). Jobs: discovery (4h),
                      content_factory (4h), carousel_factory (8h),
                      queue_maintenance (12h), analytics_update (24h).
                      run_carousel_factory() batches 5 rated games → CarouselPost,
                      running dedupe_carousel_captions across the 5 captions first.
src/api/dashboard.py  FastAPI. Pages: / , /carousels (review+approve slides +
                      one-step "Save all to Photos"), /queue, /games, /analytics.
                      Endpoints: /pipeline/run-carousel, /analytics/ingest (now
                      validates content_id), /analytics?content_id=N (prefill),
                      /carousel/{id}/download (zip of all slides). build_slides_zip()
                      helper bundles slides.
src/config.py         Settings. channel_name_display / channel_handle_display
                      strip emoji from CHANNEL_NAME/HANDLE before burn-in.
src/analytics/feedback_loop.py  Manual analytics ingest + weight update.
                      ingest_manual() rejects a non-existent content_id (was
                      silently writing orphan rows). get_performance_summary()
                      now also returns avg_follows_per_post.
src/database/models.py  Game, Content (+carousel_caption col), CarouselPost,
                      PostAnalytics, ModelWeights, CrawlLog.
src/database/connection.py  init_db() creates tables + auto-migrates the
                      carousel_caption column for existing DBs (SQLite WAL).
src/api/templates/   base.html (dark theme + .id-chip + imgFallback helper),
                      index.html, carousels.html, queue.html, games.html,
                      analytics.html, content_detail.html.
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
- Pipeline batches carousels every 8h; manual "⚡ Generate Now" button.
- Video + thumbnail pipeline intact (badge-overlap bug fixed).
- **Test suite: 66 passing**. See "Testing" below.

## Session changelog — quality engine + authenticity (latest session)
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
1. **Feedback loop on carousels**: PostAnalytics is wired for videos; extend
   to carousels so the scorer learns which editions/games/captions land.
   Add `/analytics/ingest-carousel` and extend CarouselPost with view/like fields.
2. **Caption A/B**: generate 2 caption variants per carousel and track.
3. **More edition variety / scheduling cadence** (currently 8 editions rotate).
4. **Verify the iPad "Save all to Photos" flow end-to-end on a real device**
   (logic + zip fallback are tested; the share-sheet step is iOS-only and can't
   be exercised in the sandbox).
5. ~~Per-slide download buttons~~ — **DONE** (replaced by one-step save).

## Testing
Run `python -m pytest -q` (49 passing). Test files:
- `tests/test_scoring.py`, `tests/test_discovery.py`, `tests/test_content.py`
  — original suites (scoring, Roblox client/trend detector, rating/captions).
- `tests/test_emoji_rendering.py` — emoji detection/strip/segment, mixed render
  produces real color glyphs, ✔️ vs ✓, video stats/features slides, carousel
  title slide, arrow handling.
- `tests/test_captions.py` — cross-slide dedup, stutter + crutch detection,
  generic-filler blocklist, genre-aware replacement.
- `tests/test_analytics_ingest.py` — ingest rejects missing content_id (no
  orphan rows) and marks valid content posted with correct KPIs.
- `tests/test_dashboard_views.py` — 10K projection branches + analytics prefill
  render (template-level).
- `tests/test_quality.py` — AI-fingerprint + specificity primitives, hook/
  caption/CTA scoring, good-passes/bad-fails review, finalize auto-revises a
  messy batch, hook/CTA/post-caption variety, retention-arc ordering.
- `tests/test_carousel_download.py` — zip bundling (ordering, skips missing) +
  the "Save all to Photos" button render + Web Share wiring.

Sandbox verification pattern: render PNG slides and view them (no real network /
moviepy needed). Templates are validated by parsing all of them and rendering
with mock contexts.

## Conventions
- Develop + push ONLY to `claude/handoff-file-continue-nmksfs`.
- Don't create PRs unless asked.
- Don't put the model ID in commits/code.
- Commits use a `Co-Authored-By: Claude <noreply@anthropic.com>` trailer
  (model name per the active session) plus the session link trailer.
