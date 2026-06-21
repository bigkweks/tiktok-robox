# HANDOFF — Roblox TikTok Pipeline

> **New chat? Read this file first, then continue.** It is the complete,
> current state. Everything not in here is noise (old bugs already fixed).

## Goal
Fully automated pipeline that finds underrated Roblox games, AI-rates them,
and produces TikTok content. Target: 10K followers in 30 days.
User is on an **iPad using GitHub Codespaces** — cannot run a real terminal
comfortably, so everything must work via `bash quickstart.sh`.

- **Branch (develop + push here only):** `claude/roblox-tiktok-pipeline-x5t414`
- **Repo:** `bigkweks/tiktok-robox`
- **Run it:** `bash quickstart.sh` (auto-pulls, installs, sets API key, serves
  dashboard at http://localhost:8000)

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
  "minecraft dropper if ukuk", "well made game i spent 30+ hours in",
  "MUST check out". (These are now few-shot anchors in the rating prompt.)

The carousel is the **primary** format. The video pipeline still exists
(video_assembler.py) but is secondary.

## Architecture / key files
```
src/discovery/
  roblox_client.py    Public Roblox API (/v1/games?universeIds=, no auth).
                      SEED_UNIVERSE_IDS = 46 hand-picked games to seed crawl.
  trend_detector.py   Crawl→score→persist. get_top_unprocessed() re-ranks by
                      tiktok_candidacy (rewards the discoverable-not-famous gem).
  viral_scorer.py     Weighted multi-factor scoring + tiktok_candidacy() +
                      predict_tiktok_performance().
src/content/
  fonts.py            SHARED font/emoji loader. Poppins (bundled in
                      assets/fonts) + real Noto Color Emoji. ALL renderers
                      use this. load_font(weight,size) / emoji_image() /
                      paste_emoji().
  rating_engine.py    Claude rates a game → RatingResult(score, label, verdict,
                      tts_script, hook_text, carousel_caption, ...). Prompt has
                      HOOK RULES + CAROUSEL CAPTION VOICE (few-shot anchors).
  carousel_generator.py  ★ THE viral format. CarouselGenerator.generate(games,
                      edition, part_number) → 6 slide PNGs. CarouselGame dataclass.
                      EDITIONS list carries (label, theme_emoji, [stickers]).
  description_engine.py  TikTok captions + hashtags. Hashtags lead with proven
                      search queries (#robloxgamestoplywithfriends etc).
  video_assembler.py  Secondary 9:16 video (moviepy + gTTS, Ken Burns, captions,
                      animated score count-up).
  thumbnail_generator.py  Video cover variants A/B.
src/scheduler/pipeline.py  Orchestrator (APScheduler). Jobs: discovery (4h),
                      content_factory (4h), carousel_factory (8h),
                      queue_maintenance (12h), analytics_update (24h).
                      run_carousel_factory() batches 5 rated games → CarouselPost.
src/api/dashboard.py  FastAPI. Pages: / , /carousels (review+approve slides),
                      /queue, /games, /analytics. Endpoint /pipeline/run-carousel.
src/database/models.py  Game, Content (+carousel_caption col), CarouselPost,
                      PostAnalytics, ModelWeights, CrawlLog.
src/database/connection.py  init_db() creates tables + auto-migrates the
                      carousel_caption column for existing DBs (SQLite WAL).
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

## State: what works now (all pushed)
- Carousel generator produces all 6 slides in <1s, real Poppins + real emoji,
  game art as hero, authentic Roblox-page look. Verified by rendering.
- Rating engine outputs carousel_caption in the viral creator's voice.
- Dashboard /carousels page reviews + approves/rejects carousels.
- Pipeline batches carousels every 8h; manual "⚡ Generate Now" button.
- Video + thumbnail pipeline intact (badge-overlap bug fixed).

## Likely next steps (not yet done — pick up here)
1. **TikTok auto-posting**: nothing actually posts to TikTok yet. Carousels are
   generated + queued + approved in the dashboard, but publishing is manual
   (download slides, post). TikTok Content Posting API (photo carousel) +
   OAuth would close the loop. Config stubs exist (TIKTOK_* in config.py).
2. **More edition variety / scheduling cadence** (currently 8 editions rotate).
3. **Feedback loop on carousels**: PostAnalytics is wired for videos; extend
   to carousels so the scorer learns which editions/games/captions land.
4. **Caption A/B**: generate 2 caption variants per carousel and track.

## Conventions
- Develop + push ONLY to `claude/roblox-tiktok-pipeline-x5t414`.
- Don't create PRs unless asked.
- Don't put the model ID in commits/code.
- Commit trailers used:
  `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`
