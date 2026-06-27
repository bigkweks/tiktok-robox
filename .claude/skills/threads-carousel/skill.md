# threads-carousel

Converts text posts into visual carousel slides optimised for social platforms.
Source: https://github.com/itchernetski/threads-carousel-claude-skill

## What it does
- 12 slide types (hook, body, stat, comparison, checklist, emoji-illus, hero-number…)
- 6 format presets: Threads/Instagram 1080×1350, LinkedIn 1080×1080, TikTok/Stories 1080×1920, wide 1920×1080
- 880 style combinations: 5 fonts × 8 color surfaces × 10 accents × 8 bg decorations
- Live preview server on port 3333 (Next.js 15 + React 19 + Tailwind)
- PNG and PDF export

## Invocation
/threads-carousel <text or @file.md> [--slides N] [--format tiktok] [--font condensed] [--color dark] [--accent red]

## Slide types
hook · body · stat · comparison · checklist · emoji-illus · hero-number · quote · timeline · table · code · closing

## Format presets
| preset | size | platform |
|---|---|---|
| portrait | 1080×1350 | Threads / Instagram |
| square | 1080×1080 | LinkedIn |
| tiktok | 1080×1920 | TikTok / Stories |
| wide | 1920×1080 | YouTube / Slides |

## Design axes (independent, composable)
- **Font**: minimal-geo · humanist · mono · condensed · slab
- **Surface**: dark · white · gradient · neon · warm · cool · paper · code
- **Accent**: yellow · red · teal · coral · purple · blue · green · orange · pink · white
- **Bg deco**: none · dots · grid · ruled · noise · gradient-glow · halftone · torn

## Install (requires Node.js, local only)
```
git clone https://github.com/itchernetski/threads-carousel-claude-skill ~/.claude/skills/threads-carousel
cd ~/.claude/skills/threads-carousel/template && npm install
```

## Notes
- Requires a running local dev server — not available in remote/cloud sessions.
- In cloud sessions: use PIL-based carousel_generator.py instead for image output.
