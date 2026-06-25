# Silent Quality-Degradation Audit

> **Question asked:** Where does the application quietly produce lower-quality
> content while appearing successful — fallbacks masking failures, placeholders
> replacing real content, AI failures becoming generic content, exports/uploads
> succeeding with degraded/incomplete data, quality gates being bypassed, or
> retries returning low-quality results?

**Scope:** all of `src/` (discovery → rating → carousel → approval → export).
**Date:** 2026-06-25 · **Branch:** `claude/handoff-file-continue-nmksfs`

> **Remediation status (updated):** **C1, H1, H2, M2, and M3 are now fixed**
> (see commits on this branch). M1 is substantially mitigated as a side-effect of
> C1 (fallback content can no longer reach the panel). The Low items (L2–L4) are
> triaged as **accepted residual risk** — they degrade robustness/telemetry, not
> shipped content. The per-issue sections below describe the original finding;
> the summary table at the bottom carries the current status.

This codebase already has a strong remediation layer (the launch-readiness
session): a placeholder-hero gate, an export validator, a rating floor, a
three-reviewer panel, cross-post dedup, and an AI-status banner. Those gates are
real and they work for the cases they cover. This audit looks specifically for
the seams **between** those gates — the places where degraded content still
slips through *appearing successful*.

The headline finding: **the system gates the things it can see in the rendered
PNG (placeholder hero, blank frame, wrong dimensions), but it does not gate the
provenance of the words and ratings.** When the AI silently fails, rule-based
output is persisted indistinguishably from real AI output and sails through
every downstream gate, because every downstream gate is itself rule-based.

---

## CRITICAL

### C1 — AI-failure ratings are persisted and shipped indistinguishably from real AI output

**Where:** `src/content/rating_engine.py:265-275` sets `RatingResult.used_fallback = True`
on any Anthropic failure. `src/scheduler/pipeline.py:741-763`
(`_generate_content_for_game`) persists the `Content` row **without** that flag —
`Content` (`src/database/models.py:108`) has **no `used_fallback` column**.
`run_carousel_factory` (`pipeline.py:188-202`) selects games purely on
`rating_score >= MIN_CAROUSEL_RATING`. Grep confirms `used_fallback` is **read
nowhere** in the codebase — it is a dead flag.

The fallback rating is a deterministic name-hash lookup
(`_fallback_rating`, `rating_engine.py:277-287`):
`score = min(9.5, max(5.0, viral_score*9+0.5))`. With `MIN_CAROUSEL_RATING = 7.4`,
any game with `viral_score ≥ 0.77` (common — discovery already filters at 0.45)
gets a fallback score **above the floor** and becomes carousel-eligible. The
verdict, hook, and caption are all canned bank lines.

- **User impact:** The product's core promise — *"AI rates underrated Roblox
  games"* — silently becomes a hash function picking from a fixed phrase bank.
  Every "rating," "verdict," and "why it slaps" callout is fabricated, not
  reasoned. The user posts it believing it's AI-curated.
- **Likelihood:** **High.** This fires on *every* transient failure: a single
  rate-limit (429), a timeout, a network blip, an expired key, or a malformed
  response — per game. A valid key that hits one 429 mid-batch produces fallback
  content with **no banner at all** (the banner reflects key validity, not the
  per-call outcome).
- **Trust impact:** **Severe.** This is the exact failure mode `ai_status.py`'s
  own docstring warns about ("a product that *looks* like it is working while
  silently producing non-AI output… they blame 'weak AI'"), but the mitigation
  stops at a global banner and never reaches the per-item record. A creator
  building a brand on "honest AI ratings" is unknowingly shipping fabricated
  ratings.
- **Recommended fix:**
  1. Add `used_fallback: bool` (and ideally `fallback_reason`) to the `Content`
     model + auto-migration; persist `rating.used_fallback` in
     `_generate_content_for_game`.
  2. In `run_carousel_factory`, **exclude** `used_fallback` content from carousel
     selection (or hard-block the batch if any member is fallback), mirroring the
     existing rating-floor gate.
  3. Surface a per-carousel "contains fallback content" marker in the review UI
     so a human never approves fabricated ratings unknowingly.
  4. Optionally: re-rate fallback rows on the next run once the key/network
     recovers, rather than letting them persist permanently.

---

## HIGH

### H1 — Game-page icon silently falls back to a synthetic letter avatar, and it is NOT gated

**Where:** `src/content/carousel_generator.py:718-731` (`_fetch_icon`). When the
real Roblox icon URL fails to load, it draws a colored rounded square with the
game's first letter. Unlike the hero thumbnail (`_make_game_slide:591-604`,
which calls `report.record_hero(..., ok=False)`), the icon path records
**nothing**. `RenderReport.ok` (`carousel_generator.py:172-175`) only counts
placeholder *heroes*, so a slide with a real hero but a fake letter-icon passes
every gate and ships.

- **User impact:** The whole point of the format (per HANDOFF: "look like a
  genuine Roblox game page → instant trust") is undermined by a generic
  letter-tile sitting where the real game icon should be. It reads as
  "auto-generated," the precise tell the format exists to avoid.
- **Likelihood:** **Medium-High.** Icons come from a different Roblox CDN
  endpoint than thumbnails and can fail independently — especially under the same
  rate-limiting that the hero gate was built to catch. The hero can load while
  the icon doesn't.
- **Trust impact:** **High.** A viewer who clicks expecting the real game sees a
  mismatch between the authentic hero art and a fake icon — the carousel looks
  faked, eroding the authenticity that drives the 23.9% search trust.
- **Recommended fix:** Record icon failures in `RenderReport`
  (e.g. `record_icon(ok=False)`), and either include them in `report.ok` or
  surface them as a soft warning the reviewer sees. At minimum, the export
  validator should sample the icon region the way it samples the hero band.

### H2 — Content-DNA "extraction" silently returns a generic prior but reports `status: "extracted"`

**Where:** `src/content/content_dna.py:540-562`. If the vision call fails (no
key, network, unparseable response) or no readable images are supplied,
`extract()` returns `seed_prior_profile()` — a hand-written generic baseline.
The dashboard endpoint `/dna/extract`
(`src/api/dashboard.py:478-513`) then responds with
`{"status": "extracted", ...}` regardless. The `is_prior` flag is included in the
payload, but the top-line status claims success either way.

- **User impact:** The user uploads screenshots of a *proven winning* carousel
  expecting Claude vision to learn *why it worked*. On silent failure they get a
  generic baseline that learned nothing from their upload — yet it's saved as a
  profile and folded into the consolidated blueprint that steers all future
  generation. The "learning" feature silently learns nothing.
- **Likelihood:** **Medium.** Vision calls are heavier than text calls (larger
  payloads, stricter limits) and this is exactly the kind of call that fails on a
  rate-limit or a slightly-off JSON response (`_parse` returns no patterns →
  raises → prior).
- **Trust impact:** **High.** A core differentiator ("upload winners → extract
  DNA → generate better") quietly becomes a no-op while telling the user it
  succeeded. The user believes the system is getting smarter from their data when
  it isn't.
- **Recommended fix:** Have `/dna/extract` return `status: "fell_back_to_prior"`
  (or `status: "extracted"` only when `is_prior is False`), and make `dna.html`
  visibly flag prior-vs-extracted profiles. Do not silently merge a failed
  extraction's prior into the consolidated blueprint as if it were real signal.

---

## MEDIUM

### M1 — The three-reviewer approval panel is fully rule-based and cannot detect fabricated/fallback content

**Where:** `src/content/review_panel.py` + `src/content/content_approval.py`.
The panel scores text heuristics (hook strength, AI-tells, specificity, CTA) and
even **swaps captions from the same banks** the fallback uses
(`content_approval.py:71-105`, `_revise_captions`). Nothing in the panel verifies
that the rating/verdict/caption originated from the AI rather than the
deterministic fallback.

- **User impact:** Fallback content (see C1) can pass the panel and be presented
  as "survived a 3-reviewer approval panel with a Final Quality Score of 84,"
  overstating the assurance. The score measures *phrasing*, not *truth* or
  *provenance*.
- **Likelihood:** **Medium** (conditional on C1 firing, which is High).
- **Trust impact:** **Medium-High.** "Passed review" is a trust signal the UI
  leans on heavily; for fallback content that signal is hollow.
- **Recommended fix:** Feed `used_fallback` into the panel as a **hard failure**
  (`detect_hard_failures`, `review_panel.py:224`). Reframe the panel's claim as
  "editorial polish," not "quality assurance," in the UI copy.

### M2 — Creator name silently falls back to "Roblox", mislabeling authorship

**Where:** `src/content/carousel_generator.py:582` —
`(game.creator or "Roblox")`. When `creator_name` is missing, the slide
attributes the game to "Roblox" itself, which is usually false.

- **User impact:** The slide states a wrong fact (creator) on a format whose
  entire value is *authenticity*. A knowledgeable viewer spots it instantly.
- **Likelihood:** **Low-Medium** — `creator_name` is nullable
  (`models.py:29`) and discovery can leave it empty.
- **Trust impact:** **Medium.** Wrong on-image facts read as "bot content."
- **Recommended fix:** If the creator is unknown, omit the line rather than
  asserting "Roblox," or record it as a soft slide-quality warning.

### M3 — Video captions fall back to canned templates with only a log warning

**Where:** `src/content/description_engine.py:140-143`. On AI failure the
TikTok caption silently becomes a fixed template (`_fallback_a/_fallback_b`).
`DescriptionResult` has no `used_fallback` flag; only a `log.warning` records it.
The carousel path uses `generate_local()` (rule-based by design, fine), but when
`GENERATE_VIDEOS=True` the *video* caption silently degrades.

- **User impact:** When videos are enabled, posted captions are generic
  templates presented as AI-written.
- **Likelihood:** **Low** today (videos off by default), rises if videos are
  turned on.
- **Trust impact:** **Medium** (only on the video path).
- **Recommended fix:** Mirror the C1 fix — flag `used_fallback` on
  `DescriptionResult` and surface it; don't let template captions pass as AI
  output when videos are on.

---

## LOW

### L1 — Icon/thumbnail fetch retries exhaust silently to `None`
`carousel_generator.py:203-219` retries twice then logs a single warning and
returns `None` → placeholder. The hero case is caught by the gate; the **icon**
case is not (see H1). Residual risk beyond H1 is low.
**Fix:** covered by H1.

### L2 — Learning/DNA/perf loads swallow all exceptions to silent cold-start
`pipeline.py:277-292, 309-327` wrap DNA, performance-bias, and genome recording
in broad `try/except` that only `log.warning`. Generation correctly continues,
but the "system is getting smarter" claim can be silently false (the corpus may
never be written).
**Fix:** acceptable for robustness; consider a dashboard health indicator showing
whether the learning corpus is actually being written.

### L3 — Edition mismatch falls back to "Hidden Gems" with a warning
`pipeline.py:255-259`. `edition_for_games` is supposed to prevent this, so it's a
defensive default; a genre/cover mismatch would be a quieter quality dip than the
gate it replaced. **Low.**

### L4 — Blank/placeholder export checks are heuristic and could miss edge cases
`export_validator.py:45-67` samples 24×24 / 20×20 thumbnails with fixed color
thresholds. A corrupt-but-not-grey render, or a hero that partially loaded, could
pass. Residual after the existing gates is small.
**Fix:** consider a perceptual/entropy check on the hero band in addition to the
flat-grey test.

---

## Summary table

| ID | Severity | Issue | Status |
|----|----------|-------|--------|
| C1 | Critical | AI-failure ratings persist & ship as if AI-generated (`used_fallback` was a dead flag) | **✅ Fixed** — column persisted, selection + defensive gate, "why" surfaced, UI markers, test |
| H1 | High | Synthetic letter-avatar icon not recorded or gated | **✅ Fixed** — icon provenance in `RenderReport`, blocks when a real icon URL fails to load, tests |
| H2 | High | DNA extraction silently returns generic prior, reports "extracted" | **✅ Fixed** — failed extraction reported as `no_signal`, prior never persisted/merged, UI warning, tests |
| M1 | Medium | Rule-based panel can't detect fabricated/fallback content | **Mitigated** by C1 (fallback can't reach the panel); optional hard-failure still open |
| M2 | Medium | Creator silently falls back to "Roblox" | **✅ Fixed** — unknown creator renders "Roblox creator", never falsely credits Roblox itself |
| M3 | Medium | Video captions silently fall back to templates | **✅ Fixed** — `DescriptionResult.used_fallback` flagged + logged loudly; test |
| L1 | Low | Icon fetch retries exhaust silently | Closed via H1 |
| L2 | Low | Learning/DNA loads swallow exceptions to cold-start | Accepted — robustness/telemetry only, never ships content; logged |
| L3 | Low | Edition mismatch → "Hidden Gems" default | Accepted — "Hidden Gems" is a genre-neutral edition, so the fallback can't mislabel the games |
| L4 | Low | Export blank/placeholder checks are heuristic | Accepted — backs the authoritative render-time `RenderReport` gate; residual risk small |

## The one-line takeaway
The visual gates (placeholder hero, dimensions, blank frame) are solid. The
**provenance gates are missing**: when the AI silently degrades to rule-based
output, that fabricated content is persisted with no marker (C1) and then
validated by gates that are themselves rule-based (M1), so it ships looking
fully successful. Closing C1 (persist + honor `used_fallback`) is the highest-
leverage fix and unblocks M1.
