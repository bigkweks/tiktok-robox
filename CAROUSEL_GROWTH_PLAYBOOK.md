# Carousel Growth Playbook
### Patterns that correlate with high-performing gaming carousels — and how each variant implements them

This document backs the three variant designs (`src/content/carousel_variants.py`).
Every design choice below names **the pattern it implements** and **the
retention or growth mechanism it exploits**. The goal is not "make it pretty" —
it's to copy the structural moves that separate 2M-view gaming carousels from
the 5K-view Roblox-rec norm.

---

## 1. The core gap (why Roblox recs underperform general gaming)

| | Roblox game-rec norm | Top general-gaming carousels |
|---|---|---|
| **Stance** | Discovery ("here are games") | Authority ("I tested / ranked / graded these") |
| **Art** | Raw screenshot + text slapped on | Art is *composed into* an editorial system |
| **Per-slide job** | Show a game | Advance an argument, create a loop |
| **Engagement** | Passive scroll | Save (reference), comment (debate), follow (series) |
| **Result** | 3–20K views, low save rate | 200K–2M, high save + follow rate |

The three variants each import a **proven authority format** and rebuild the
craft to match.

---

## 2. Trends & patterns that correlate with success

These are the recurring, observable patterns in high-performing gaming carousels
(and the reverse-engineered 118.5K-view reference post this project is built on).

### P1 — Authority framing beats discovery framing
Posts that signal the creator *did work* ("23 hours tested", "ranked", "graded")
outperform "check out these games" because they convert the list into **vetted
reference material** worth saving. → **Mechanism: save rate.**

### P2 — Real game art is the trust signal
Carousels where the actual game is *shown* (screenshot/thumbnail) earn instant
credibility; abstract or text-only slides read as low-effort/templated and get
scrolled. → **Mechanism: stop-scroll + dwell time.**
Implemented: **every variant now composites the real Roblox homepage thumbnail
and icon** (`img_to_uri` → renderer). Production passes the live Roblox URL;
the sandbox uses synthesised scenes to prove the layout.

### P3 — The cover IS the search query / the open loop
23.9% of the reference post's traffic came from Search because the title was the
literal query ("roblox games to play"). High performers also open a **curiosity
gap** the swipe resolves. → **Mechanism: search discovery + swipe-through.**

### P4 — Structured per-slide hierarchy increases completion
Slides with a consistent, scannable structure (verdict → score → reason) hold
attention better than a wall of caption. The eye knows where to go in <2s.
→ **Mechanism: swipe-through / completion rate.**

### P5 — Controversy / rankings manufacture comments
Tier lists and letter grades reliably generate "this isn't S tier" replies — the
highest-engagement comment type. A debatable claim on the slide is an explicit
**comment prompt**. → **Mechanism: comment rate → algorithmic reach.**

### P6 — Pattern interrupt beats "nice design"
On a dark, fast feed, an unexpected visual (a clean **cream/white** slide, an
engraved certificate) stops the thumb more reliably than another neon-glow card.
→ **Mechanism: stop-scroll.**

### P7 — Series + progress drive follows and completion
A visible "part N", an unresolved "#1 is coming", and a swipe-progress affordance
all push the viewer to the end and to follow for the next drop.
→ **Mechanism: follow rate + completion.**

### P8 — Save triggers must be explicit
"Keep this list", recommendation stamps, and reference-grade layouts give the
viewer a *reason* to hit save. Saves are weighted heavily by the algorithm and
re-surface the post. → **Mechanism: save rate.**

---

## 3. How each variant implements the patterns

### ① The Scout Report — *reviewer authority* (dark dossier)
- **P1 Authority:** "field-tested dispatch", `Hours in: 23`, "Scout score" — the
  whole frame is a tested reviewer's notebook.
- **P2 Real art:** the in-game capture fills the double-bezel **plate**; the real
  game **icon** is inset on it (authenticity stack).
- **P4 Hierarchy:** entry → score → verdict pull-quote → spec table → field notes.
  A fixed reading path every slide.
- **P7 Progress:** swipe-progress ticks under the plate; "No. 01 / 05".
- **P8 Save:** "Verified gem" colophon + reference-grade layout = keep-it value.

### ② The Tier Drop — *competitive ranking* (full-bleed screenshot)
- **P5 Controversy:** the S/A/B stamp is a debatable claim → comment war by design
  (the format is absent from Roblox TikTok, so novelty compounds the effect).
- **P2 Real art:** the screenshot is the **full-bleed cinematic backdrop**; the
  veil reveals it up top and deepens only where text needs contrast.
- **P6 Pattern interrupt:** the flat brass/sage letterpress stamp (no neon) reads
  premium, not templated.
- **P7 Progress + series:** progress ticks, "Drop 12", "Pick 02 / 05".

### ③ The Grade Report — *academic authority* (cream certificate)
- **P6 Pattern interrupt:** the **cream paper** is the single strongest scroll-stop
  on a dark feed — it doesn't look like anything else in the niche.
- **P5 Controversy:** letter grades + sub-grades (Fun/Value/Original/Social)
  invite "B for social? no way" comments.
- **P2 Real art:** the **filed-exhibit** photo — the real capture framed beside the
  grade like evidence stapled to an assessment.
- **P8 Save:** "Recommended" stamp + certificate format = the highest-save-rate
  variant; people screenshot grade cards to DM friends. → also drives **shares**.
- **P1 Authority:** "official assessment", "examiner's note", "assessed by hand".

---

## 4. Retention & growth mechanics added this pass

| Mechanic | Where | Pattern | Effect |
|---|---|---|---|
| **Real screenshot + icon** | all variants | P2 | trust, dwell, stop-scroll |
| **Swipe-progress ticks** | Scout, Tier | P7 | completion rate |
| **Slide counters** ("01/05") | all | P7 | completion |
| **Debatable claim on-slide** | Tier, Grade | P5 | comments → reach |
| **Pattern-interrupt cover** | Grade (cream) | P6 | stop-scroll |
| **Series markers** ("part N / Drop N") | all | P7 | follows |
| **Recommendation / verified stamp** | Scout, Grade | P8 | saves + shares |
| **Verdict pull-quote / examiner note** | Scout, Grade | P4 | dwell, scannability |

### Recommended next mechanics (not yet built)
1. **Payoff-slide follow loop** — the final game slide should tease the next drop
   ("Part 13 — Friday. Follow so you don't miss #1"), closing the series loop at
   the exact moment intent is highest. *(param hook is ready; wire copy in.)*
2. **Cover swipe-tension** — name the prize the swipe unlocks ("the #1 will start
   an argument") to lift swipe-through from the very first frame.
3. **A/B the three formats** — ship all three to measure which authority frame
   (review vs. rank vs. grade) drives the most saves/follows for *this* audience,
   then bias generation toward the winner (the Performance Learning System and
   genome recorder already support this — feed realised saves/follows into
   `PerformanceStore.update_outcome`).

---

## 5. Production wiring (real art, no placeholder)

`carousel_variants.img_to_uri(src)` accepts a `PIL.Image`, a local path, or a
raw `http(s)` URL and returns a value usable directly in CSS `url(...)`:

- **Codespace / production:** pass the real Roblox homepage thumbnail + icon URL
  (already fetched by `carousel_generator._fetch_thumbnail` / `_fetch_icon`).
  Chromium loads them at render time — no placeholder ever ships.
- **Sandbox:** pass a PIL image (here, `scripts/_demo_scenes.game_scene`), since
  roblox.com is unreachable from this network.

The existing **provenance gate** still applies: if the real thumbnail fails to
load, the render must be rejected (never ship a placeholder as if it were the
real game page).
