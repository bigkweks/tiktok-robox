"""
carousel_variants.py — Three alternative carousel visual systems.

COMPETITIVE ANALYSIS: Roblox vs. General Gaming TikTok

The Gap
───────
Roblox game recommendation channels treat their carousel as a **discovery list**:
  raw screenshot → text overlay → "you need this game". No authority signals.
  Typical result: 3–15K views, low save rate, almost no comments.

Top general gaming channels (indie-game curators, console gem-hunters, PC hidden
gem accounts that hit 200K–2M views per carousel) treat every slide as
**editorial content**:
  1. They position as EXPERTS who tested, not mere discoverers.
  2. Every slide has a structured information hierarchy (verdict, score, reason).
  3. The format itself creates ENGAGEMENT LOOPS (tier lists → debate comments,
     grade cards → save + screenshot to share the grade, review cards → "do you
     agree?" replies).

Three proven general-gaming formats — imported into Roblox:
  ① THE SCOUT REPORT   → reviewer-authority (test + verdict + score)
  ② THE TIER DROP      → competitive ranking (S/A/B tier → debate comments)
  ③ THE GRADE REPORT   → academic authority (A+/B/S grades → screenshot saves)
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import io
import math
import tempfile
from pathlib import Path

from PIL import Image

FONT_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

_FONT_WEIGHTS = {
    "black":     (900, "Poppins-Black.ttf"),
    "extrabold": (800, "Poppins-ExtraBold.ttf"),
    "bold":      (700, "Poppins-Bold.ttf"),
    "semibold":  (600, "Poppins-SemiBold.ttf"),
    "medium":    (500, "Poppins-Medium.ttf"),
    "regular":   (400, "Poppins-Regular.ttf"),
}


def _font_faces() -> str:
    parts = []
    for name, (w, fname) in _FONT_WEIGHTS.items():
        path = FONT_DIR / fname
        if not path.exists():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode()
        uri = f"data:font/truetype;base64,{b64}"
        parts.append(
            f"@font-face{{font-family:'Poppins';font-weight:{w};"
            f"src:url('{uri}')format('truetype');}}"
        )
    return "\n".join(parts)


def _game_palette(name: str) -> tuple[str, str]:
    """Return two CSS hex colors (dark + mid) unique to the game name."""
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    hue = h % 360
    palettes = [
        ("#1a0a3e", "#6b21a8"),   # purple
        ("#0a2e1a", "#15803d"),   # forest green
        ("#1a0a0a", "#b91c1c"),   # deep red
        ("#0a1a3e", "#1d4ed8"),   # royal blue
        ("#1a150a", "#b45309"),   # amber
        ("#0a1a2e", "#0e7490"),   # teal
        ("#1a0a2e", "#7c3aed"),   # violet
        ("#0e1a0a", "#4d7c0f"),   # olive
    ]
    return palettes[hue % len(palettes)]


def _render_html(html_src: str) -> Image.Image:
    """Render an HTML string at 1080×1920 and return a PIL RGB image."""
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(html_src)
        tmp_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=CHROMIUM,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1080, "height": 1920})
            page.goto(f"file://{tmp_path}", wait_until="domcontentloaded")
            page.evaluate("async () => { await document.fonts.ready; }")
            png_bytes = page.screenshot(type="png", full_page=False)
            browser.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return Image.open(io.BytesIO(png_bytes)).convert("RGB")


# ─────────────────────────────────────────────────────────────────────────────
# VARIANT 1 — THE SCOUT REPORT
#
# Imports: Gaming-reviewer authority aesthetic (Skill Up, Dunkey, NakeyJakey
# style adapted for short-form). The creator is a TESTED EXPERT, not a curator.
# Hook: "I played 47+ hours so you don't have to"
# Engagement driver: High save rate — people keep reviewer picks for later.
# What's missing in Roblox TikTok: nobody positions as a tested reviewer.
# ─────────────────────────────────────────────────────────────────────────────

_SCOUT_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}

body{
    width:1080px;height:1920px;overflow:hidden;
    font-family:'Poppins',sans-serif;
    background:#09091C;
    position:relative;
}

/* ── Subtle noise texture overlay ─────────────────────────────────── */
body::after{
    content:'";
    position:absolute;inset:0;pointer-events:none;
    background:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    opacity:0.5;
}

/* ── Grid lines (very subtle) ──────────────────────────────────────── */
.grid{
    position:absolute;inset:0;pointer-events:none;
    background-image:
        linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
    background-size:120px 120px;
}

/* ── Header bar ────────────────────────────────────────────────────── */
.header{
    position:relative;z-index:10;
    padding:36px 80px;
    display:flex;justify-content:space-between;align-items:center;
    border-bottom:1px solid rgba(255,255,255,.07);
}
.scout-wordmark{
    font-size:30px;font-weight:600;letter-spacing:5px;
    color:#E2231A;text-transform:uppercase;
}
.issue-chip{
    font-size:28px;font-weight:500;
    color:rgba(255,255,255,.25);letter-spacing:2px;
}

/* ── Game art panel ────────────────────────────────────────────────── */
.art-panel{
    position:relative;
    height:540px;overflow:hidden;
}
.art-bg{
    position:absolute;inset:0;
}
.art-overlay{
    position:absolute;inset:0;
    background:linear-gradient(
        160deg,
        rgba(9,9,28,.1) 0%,
        rgba(9,9,28,.5) 60%,
        rgba(9,9,28,.92) 100%
    );
}

/* Score badge — overlaid on art, bottom-right */
.score-badge{
    position:absolute;bottom:44px;right:80px;
    width:176px;height:176px;border-radius:50%;
    background:linear-gradient(145deg,#FFB300,#FF8C00);
    box-shadow:0 0 48px rgba(255,179,0,.55), 0 0 90px rgba(255,179,0,.2);
    display:flex;flex-direction:column;
    align-items:center;justify-content:center;
    z-index:5;
}
.score-num{
    font-size:72px;font-weight:900;color:#09091C;line-height:1;
    letter-spacing:-2px;
}
.score-label{
    font-size:20px;font-weight:700;color:rgba(9,9,28,.6);
    letter-spacing:2px;text-transform:uppercase;margin-top:4px;
}

/* ── Content body ──────────────────────────────────────────────────── */
.body{padding:52px 80px 0;}

.game-name{
    font-size:76px;font-weight:900;color:#fff;
    line-height:1.0;letter-spacing:-3px;
    margin-bottom:14px;
}
.creator{
    font-size:36px;font-weight:500;
    color:rgba(255,255,255,.35);
    margin-bottom:46px;
    letter-spacing:.5px;
}

/* Verdict card */
.verdict-card{
    border-left:6px solid #E2231A;
    background:rgba(255,255,255,.04);
    border-radius:0 18px 18px 0;
    padding:34px 44px;
    margin-bottom:44px;
}
.verdict-label{
    font-size:24px;font-weight:700;color:#E2231A;
    letter-spacing:4px;text-transform:uppercase;
    margin-bottom:14px;
}
.verdict-text{
    font-size:46px;font-weight:600;color:#fff;
    line-height:1.3;font-style:italic;
}

/* Stat pills */
.stats{display:flex;gap:18px;margin-bottom:46px;}
.pill{
    flex:1;background:rgba(255,255,255,.05);
    border:1px solid rgba(255,255,255,.08);
    border-radius:18px;padding:28px 20px;text-align:center;
}
.pill-val{
    font-size:50px;font-weight:900;color:#fff;line-height:1;
}
.pill-key{
    font-size:23px;font-weight:600;
    color:rgba(255,255,255,.35);
    letter-spacing:2px;text-transform:uppercase;margin-top:10px;
}

/* Why it works */
.why-header{
    font-size:24px;font-weight:700;color:#E2231A;
    letter-spacing:4px;text-transform:uppercase;
    margin-bottom:20px;
}
.why-item{
    font-size:40px;font-weight:500;color:rgba(255,255,255,.72);
    line-height:1.35;padding:10px 0;
    display:flex;gap:20px;align-items:flex-start;
}
.dot{color:#E2231A;font-weight:900;flex-shrink:0;}

/* Footer */
.footer{
    position:absolute;bottom:0;left:0;right:0;
    padding:32px 80px;
    border-top:1px solid rgba(255,255,255,.07);
    display:flex;justify-content:space-between;align-items:center;
}
.foot-left{font-size:34px;font-weight:500;color:rgba(255,255,255,.28);}
.foot-right{
    font-size:28px;font-weight:600;color:#4CAF50;
    letter-spacing:1px;
}
"""

_SCOUT_COVER_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{
    width:1080px;height:1920px;overflow:hidden;
    font-family:'Poppins',sans-serif;
    background:#09091C;position:relative;
}
.grid{
    position:absolute;inset:0;pointer-events:none;
    background-image:
        linear-gradient(rgba(255,255,255,.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.03) 1px, transparent 1px);
    background-size:100px 100px;
}
/* Diagonal red slash accent */
.slash{
    position:absolute;top:-200px;right:-100px;
    width:600px;height:600px;
    background:linear-gradient(135deg,rgba(226,35,26,.12),transparent);
    transform:rotate(15deg);pointer-events:none;
}
.badge{
    position:absolute;top:90px;right:90px;
    border:3px solid rgba(226,35,26,.6);border-radius:12px;
    padding:16px 34px;
    color:#E2231A;font-size:42px;font-weight:600;
    background:rgba(9,9,28,.8);letter-spacing:1px;
}
.block{
    position:absolute;top:0;bottom:0;left:0;right:0;
    display:flex;flex-direction:column;
    justify-content:center;align-items:flex-start;
    padding:0 90px;
}
.eyebrow{
    font-size:30px;font-weight:700;color:#E2231A;
    letter-spacing:6px;text-transform:uppercase;
    margin-bottom:36px;
    display:flex;align-items:center;gap:18px;
}
.eyebrow-line{
    width:60px;height:3px;background:#E2231A;flex-shrink:0;
}
.hook{
    font-size:128px;font-weight:900;color:#fff;
    line-height:.95;letter-spacing:-5px;
    text-shadow:0 0 80px rgba(226,35,26,.3);
    margin-bottom:60px;
    max-width:900px;
}
.sep{
    width:100%;max-width:900px;height:3px;
    background:linear-gradient(90deg,#E2231A,rgba(226,35,26,.1));
    margin-bottom:52px;
}
.value{
    font-size:64px;font-weight:800;color:rgba(255,255,255,.85);
    line-height:1.2;letter-spacing:-1px;max-width:900px;
    margin-bottom:36px;
}
.meta{
    font-size:36px;font-weight:500;color:rgba(255,255,255,.28);
    letter-spacing:2px;
}
/* Bottom glow strip */
.glow-strip{
    position:absolute;bottom:0;left:0;right:0;height:6px;
    background:linear-gradient(90deg,#E2231A,rgba(226,35,26,.3),transparent);
}
"""


class ScoutReportVariant:
    """
    VARIANT 1 — THE SCOUT REPORT

    Authority signal: "I tested this personally"
    Target engagement: High save rate (reviewer picks = reference material)
    Missing in Roblox TikTok: The reviewer persona. Roblox channels curate,
    they don't review. The word "tested" alone changes how a viewer treats the list.
    """

    def cover_html(
        self,
        hook: str,
        value: str,
        part: int,
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_SCOUT_COVER_CSS}</style></head><body>
<div class="grid"></div>
<div class="slash"></div>
<div class="badge">part {part}</div>
<div class="block">
  <div class="eyebrow"><div class="eyebrow-line"></div>GEMVAULT SCOUT REPORT</div>
  <div class="hook">{h(hook)}</div>
  <div class="sep"></div>
  <div class="value">{h(value)}</div>
  <div class="meta">5 tested picks · part {part} · all underrated</div>
</div>
<div class="glow-strip"></div>
</body></html>"""

    def game_slide_html(
        self,
        name: str,
        creator: str,
        score: float,
        verdict: str,
        hours_tested: int,
        active: int,
        like_pct: int,
        visits_m: float,
        why1: str,
        why2: str,
        part: int,
        index: int,
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        dark, mid = _game_palette(name)
        art_grad = f"linear-gradient(135deg,{dark} 0%,{mid} 40%,{dark} 100%)"
        score_str = f"{score:.1f}"
        active_str = f"{active}K" if active < 1000 else f"{active/1000:.1f}M"
        visits_str = f"{visits_m:.1f}M"
        like_str = f"{like_pct}%"

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_SCOUT_CSS}</style></head><body>
<div class="grid"></div>
<div class="header">
  <span class="scout-wordmark">⚡ Scout Report</span>
  <span class="issue-chip">#{index} of 5 · part {part}</span>
</div>
<div class="art-panel">
  <div class="art-bg" style="background:{art_grad};"></div>
  <div class="art-overlay"></div>
  <div class="score-badge">
    <div class="score-num">{h(score_str)}</div>
    <div class="score-label">Scout</div>
  </div>
</div>
<div class="body">
  <div class="game-name">{h(name)}</div>
  <div class="creator">by {h(creator)}</div>
  <div class="verdict-card">
    <div class="verdict-label">Verdict</div>
    <div class="verdict-text">"{h(verdict)}"</div>
  </div>
  <div class="stats">
    <div class="pill">
      <div class="pill-val">{hours_tested}h</div>
      <div class="pill-key">Tested</div>
    </div>
    <div class="pill">
      <div class="pill-val">{h(active_str)}</div>
      <div class="pill-key">Active</div>
    </div>
    <div class="pill">
      <div class="pill-val">{h(like_str)}</div>
      <div class="pill-key">Liked</div>
    </div>
  </div>
  <div class="why-header">Why it works</div>
  <div class="why-item"><span class="dot">›</span>{h(why1)}</div>
  <div class="why-item"><span class="dot">›</span>{h(why2)}</div>
</div>
<div class="footer">
  <span class="foot-left">{h(visits_str)} visits</span>
  <span class="foot-right">{h(like_str)} liked</span>
</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# VARIANT 2 — THE TIER DROP
#
# Imports: Tier-list culture — dominant in gaming TikTok (Smash Bros, FPS,
# RPG tier lists routinely hit 500K–5M views). The tier badge is the hero visual.
# Hook: "S-tier Roblox games you're sleeping on"
# Engagement driver: Tier lists ALWAYS generate "I disagree" comments, which
# is the single highest-engagement comment type. The format is built for debate.
# What's missing in Roblox TikTok: Nobody has done real tier-format carousels.
# ─────────────────────────────────────────────────────────────────────────────

_TIER_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{
    width:1080px;height:1920px;overflow:hidden;
    font-family:'Poppins',sans-serif;
    background:#050508;position:relative;
}

/* Full-bleed atmospheric game art */
.art-full{position:absolute;inset:0;z-index:0;}
.art-full .art-bg{position:absolute;inset:0;}
.dark-overlay{
    position:absolute;inset:0;
    background:linear-gradient(
        to bottom,
        rgba(5,5,8,.45) 0%,
        rgba(5,5,8,.55) 35%,
        rgba(5,5,8,.80) 65%,
        rgba(5,5,8,.97) 100%
    );
}
.vignette{
    position:absolute;inset:0;
    background:radial-gradient(ellipse 100% 80% at 50% 50%,transparent 40%,rgba(0,0,0,.75) 100%);
}

/* Content stack */
.content{
    position:absolute;inset:0;z-index:10;
    display:flex;flex-direction:column;
    align-items:center;
    padding:70px 80px 0;
}

/* Top chip */
.top-chip{
    align-self:flex-start;
    background:rgba(226,35,26,.15);
    border:1px solid rgba(226,35,26,.3);
    border-radius:100px;
    padding:14px 36px;
    font-size:28px;font-weight:600;color:rgba(226,35,26,.9);
    letter-spacing:3px;text-transform:uppercase;
    margin-bottom:80px;
}

/* The tier badge — the HERO */
.tier-badge{
    width:320px;height:320px;border-radius:40px;
    background:linear-gradient(145deg,#FFD600,#FF8C00);
    box-shadow:
        0 0 100px rgba(255,200,0,.8),
        0 0 200px rgba(255,150,0,.4),
        0 0 340px rgba(255,100,0,.2);
    display:flex;flex-direction:column;
    align-items:center;justify-content:center;
    border:2px solid rgba(255,255,255,.2);
    margin-bottom:50px;
}
.tier-letter{
    font-size:190px;font-weight:900;color:#050508;
    line-height:.8;letter-spacing:-8px;
}
.tier-label{
    font-size:32px;font-weight:700;color:rgba(5,5,8,.5);
    letter-spacing:5px;text-transform:uppercase;margin-top:6px;
}
.tier-a-badge{
    background:linear-gradient(145deg,#B9F2C7,#2E7D32);
    box-shadow:
        0 0 80px rgba(76,175,80,.75),
        0 0 160px rgba(46,125,50,.35),
        0 0 280px rgba(30,100,30,.15);
}
.tier-a-letter{color:#F8F8F8;}

/* Game name — full width, massive */
.game-name{
    font-size:100px;font-weight:900;color:#fff;
    line-height:.92;letter-spacing:-4px;
    text-align:center;
    text-shadow:0 2px 40px rgba(0,0,0,.9),0 0 80px rgba(0,0,0,.6);
    margin-bottom:50px;
    max-width:920px;
}

/* Thin separator */
.sep{
    width:100%;max-width:920px;height:2px;
    background:linear-gradient(90deg,transparent,#E2231A 20%,rgba(226,35,26,.4) 80%,transparent);
    margin-bottom:46px;
}

/* Why tier section */
.why-label{
    font-size:28px;font-weight:700;color:#E2231A;
    letter-spacing:4px;text-transform:uppercase;
    margin-bottom:18px;
    align-self:flex-start;
}
.why-text{
    font-size:52px;font-weight:600;color:rgba(255,255,255,.88);
    line-height:1.3;font-style:italic;
    align-self:flex-start;
}

/* Footer */
.footer{
    position:absolute;bottom:0;left:0;right:0;
    padding:50px 80px;
    display:flex;justify-content:space-between;align-items:center;
}
.foot-stat{font-size:36px;font-weight:500;color:rgba(255,255,255,.3);}
"""

_TIER_COVER_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{
    width:1080px;height:1920px;overflow:hidden;
    font-family:'Poppins',sans-serif;
    background:#050508;position:relative;
}
/* Background atmosphere */
.bg-glow{
    position:absolute;
    top:50%;left:50%;transform:translate(-50%,-55%);
    width:1200px;height:1200px;
    background:radial-gradient(ellipse,rgba(226,35,26,.10) 0%,transparent 65%);
    pointer-events:none;
}
.bg-glow-2{
    position:absolute;bottom:-300px;left:50%;transform:translateX(-50%);
    width:1400px;height:800px;
    background:radial-gradient(ellipse,rgba(255,120,0,.06) 0%,transparent 60%);
}
.badge{
    position:absolute;top:90px;right:90px;
    border:3px solid rgba(226,35,26,.5);border-radius:12px;
    padding:16px 34px;
    color:rgba(226,35,26,.8);font-size:42px;font-weight:600;
    background:rgba(5,5,8,.9);
}

/* Center stack */
.center{
    position:absolute;inset:0;
    display:flex;flex-direction:column;
    align-items:center;justify-content:center;
    padding:0 80px;
}
.tier-word{
    font-size:34px;font-weight:700;color:rgba(255,179,0,.7);
    letter-spacing:12px;text-transform:uppercase;
    margin-bottom:28px;
}
.big-s{
    font-size:480px;font-weight:900;color:#fff;
    line-height:.8;letter-spacing:-20px;
    text-shadow:
        0 0 80px rgba(255,179,0,.9),
        0 0 160px rgba(255,179,0,.5),
        0 0 300px rgba(255,100,0,.25);
    margin-bottom:20px;
}
.roblox-line{
    font-size:88px;font-weight:900;color:rgba(255,255,255,.9);
    letter-spacing:6px;text-align:center;
    margin-bottom:30px;
}
.games-label{
    font-size:48px;font-weight:800;color:rgba(255,255,255,.6);
    letter-spacing:3px;text-transform:uppercase;
    margin-bottom:70px;
}
.sub{
    font-size:40px;font-weight:500;color:rgba(255,255,255,.25);
    text-align:center;font-style:italic;
}
.bottom-bar{
    position:absolute;bottom:0;left:0;right:0;height:5px;
    background:linear-gradient(90deg,transparent,#E2231A 30%,#FFB300 70%,transparent);
}
"""


class TierDropVariant:
    """
    VARIANT 2 — THE TIER DROP

    Authority signal: Ranking position (S > A > B) is an immediate value signal.
    Target engagement: Comments ("this is not S tier wtf"), shares to friends
    ("bro why does this not have S tier"), saves (to use as reference).
    Missing in Roblox TikTok: The tier-format carousel simply doesn't exist.
    Even a basic execution would dominate by novelty alone.
    """

    def cover_html(self, hook: str, part: int) -> str:
        ff = _font_faces()
        h = _html.escape
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_TIER_COVER_CSS}</style></head><body>
<div class="bg-glow"></div>
<div class="bg-glow-2"></div>
<div class="badge">part {part}</div>
<div class="center">
  <div class="tier-word">S · tier</div>
  <div class="big-s">S</div>
  <div class="roblox-line">ROBLOX</div>
  <div class="games-label">Games</div>
  <div class="sub">"{h(hook)}"</div>
</div>
<div class="bottom-bar"></div>
</body></html>"""

    def game_slide_html(
        self,
        name: str,
        creator: str,
        tier: str,
        why: str,
        visits_m: float,
        active: int,
        part: int,
        index: int,
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        dark, mid = _game_palette(name)
        art_grad = f"linear-gradient(135deg,{dark} 0%,{mid} 50%,{dark} 100%)"
        active_str = f"{active}K" if active < 1000 else f"{active/1000:.1f}M"
        visits_str = f"{visits_m:.1f}M"

        tier_cls = "" if tier == "S" else " tier-a-badge"
        tier_letter = tier.rstrip("+")  # show S or A not S+

        letter_cls = " tier-a-letter" if tier != "S" else ""

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_TIER_CSS}</style></head><body>
<div class="art-full">
  <div class="art-bg" style="background:{art_grad};"></div>
  <div class="dark-overlay"></div>
  <div class="vignette"></div>
</div>
<div class="content">
  <div class="top-chip">pick {index} of 5 · part {part}</div>
  <div class="tier-badge{tier_cls}">
    <div class="tier-letter{letter_cls}">{h(tier_letter)}</div>
    <div class="tier-label">Tier</div>
  </div>
  <div class="game-name">{h(name)}</div>
  <div class="sep"></div>
  <div class="why-label">Why {h(tier)} tier</div>
  <div class="why-text">"{h(why)}"</div>
</div>
<div class="footer">
  <span class="foot-stat">{h(visits_str)} visits</span>
  <span class="foot-stat">{h(active_str)} active now</span>
</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# VARIANT 3 — THE GRADE REPORT
#
# Imports: The "grading games" format (popular with gaming streamers who assign
# letter grades to games) — but made visual as a report card carousel. The
# clean white aesthetic creates a PATTERN INTERRUPT on TikTok's dark feed.
# The academic authority signals create instant credibility.
# Hook: "giving roblox games REAL grades / nobody asked but here we are"
# Engagement driver: Highest save rate of all three variants. People screenshot
# grade cards to share to Discord, DM to friends, post on Reddit.
# What's missing in Roblox TikTok: Clean, white, editorial design language.
# ─────────────────────────────────────────────────────────────────────────────

_GRADER_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{
    width:1080px;height:1920px;overflow:hidden;
    font-family:'Poppins',sans-serif;
    background:#F8F7F4;position:relative;
    border:6px solid #111;
}

/* Header */
.header{
    background:#111;
    padding:36px 80px;
    display:flex;justify-content:space-between;align-items:center;
}
.report-wordmark{
    font-size:30px;font-weight:700;letter-spacing:4px;
    color:#fff;text-transform:uppercase;
}
.part-num{
    font-size:30px;font-weight:500;
    color:rgba(255,255,255,.4);
}

/* Game identity section */
.game-section{
    padding:56px 80px 0;
    border-bottom:2px solid #E5E3DE;
    padding-bottom:48px;
}
.game-name{
    font-size:74px;font-weight:900;color:#111;
    line-height:1.0;letter-spacing:-3px;
    margin-bottom:12px;
}
.creator{
    font-size:36px;font-weight:500;color:#888;
    margin-bottom:0;
}

/* The grade card */
.grade-card{
    margin:52px 80px;
    background:#fff;
    border:3px solid #111;
    border-radius:24px;
    padding:52px;
    position:relative;
}
.grade-top-label{
    font-size:26px;font-weight:700;letter-spacing:5px;
    color:#888;text-transform:uppercase;text-align:center;
    margin-bottom:20px;
}
.grade-big{
    font-size:300px;font-weight:900;color:#E2231A;
    line-height:.85;letter-spacing:-12px;
    text-align:center;
    text-shadow:4px 6px 0px rgba(226,35,26,.15);
}
.grade-a{color:#2E7D32;}
.grade-b{color:#1565C0;}
.grade-c{color:#E65100;}

.grade-underline{
    width:120px;height:4px;background:#E2231A;
    margin:20px auto 32px;
    border-radius:2px;
}
.grade-s-underline{background:#E2231A;}
.grade-a-underline{background:#2E7D32;}

.overall-label{
    font-size:24px;font-weight:700;letter-spacing:5px;
    color:#aaa;text-transform:uppercase;text-align:center;
}

/* Sub-grades row */
.subgrades{
    display:flex;margin:0 80px;
    border:2px solid #E5E3DE;border-radius:18px;overflow:hidden;
    margin-bottom:48px;
}
.subgrade{
    flex:1;padding:30px 10px;text-align:center;
    border-right:2px solid #E5E3DE;
}
.subgrade:last-child{border-right:none;}
.sg-key{
    font-size:24px;font-weight:700;letter-spacing:2px;
    color:#999;text-transform:uppercase;margin-bottom:12px;
}
.sg-val{
    font-size:52px;font-weight:900;color:#E2231A;
    line-height:1;
}
.sg-a{color:#2E7D32;}
.sg-b{color:#1565C0;}

/* Assessment */
.assessment-section{
    padding:0 80px;margin-bottom:48px;
}
.assess-label{
    font-size:26px;font-weight:700;letter-spacing:5px;
    color:#999;text-transform:uppercase;
    border-bottom:2px solid #E5E3DE;
    padding-bottom:18px;margin-bottom:24px;
}
.assess-text{
    font-size:44px;font-weight:500;color:#333;
    line-height:1.4;
}

/* Recommendation stamp */
.stamp-row{
    padding:0 80px;
    display:flex;justify-content:space-between;align-items:center;
    margin-bottom:48px;
}
.stamp{
    display:inline-flex;align-items:center;gap:18px;
    border:4px solid #2E7D32;border-radius:16px;
    padding:22px 44px;
}
.stamp-text{
    font-size:40px;font-weight:800;color:#2E7D32;
    letter-spacing:2px;text-transform:uppercase;
}
.stamp-icon{font-size:44px;}
.visit-count{
    font-size:36px;font-weight:500;color:#bbb;
}

/* Footer */
.footer{
    position:absolute;bottom:0;left:0;right:0;
    background:#111;padding:28px 80px;
    display:flex;justify-content:space-between;align-items:center;
}
.foot-handle{
    font-size:30px;font-weight:600;color:rgba(255,255,255,.5);
    letter-spacing:1px;
}
.foot-right{
    font-size:28px;font-weight:500;color:rgba(255,255,255,.25);
}
"""

_GRADER_COVER_CSS = """
*{margin:0;padding:0;box-sizing:border-box;}
body{
    width:1080px;height:1920px;overflow:hidden;
    font-family:'Poppins',sans-serif;
    background:#F8F7F4;position:relative;
    border:8px solid #111;
}
/* Red stamp decoration */
.stamp-decor{
    position:absolute;top:110px;left:80px;
    width:200px;height:200px;border-radius:50%;
    border:6px solid #E2231A;
    display:flex;align-items:center;justify-content:center;
    transform:rotate(-15deg);
}
.stamp-text{
    font-size:26px;font-weight:900;color:#E2231A;
    text-align:center;letter-spacing:2px;text-transform:uppercase;
    line-height:1.2;
}
.badge{
    position:absolute;top:90px;right:80px;
    border:3px solid #111;border-radius:12px;
    padding:16px 34px;
    color:#111;font-size:42px;font-weight:600;
    background:#F8F7F4;
}
/* Main content */
.block{
    position:absolute;inset:0;
    display:flex;flex-direction:column;
    align-items:center;justify-content:center;
    padding:0 80px;
    text-align:center;
}
.official{
    font-size:28px;font-weight:700;letter-spacing:8px;
    color:#bbb;text-transform:uppercase;margin-bottom:16px;
}
.title-line1{
    font-size:72px;font-weight:900;color:#111;
    letter-spacing:-2px;line-height:1;margin-bottom:8px;
}
.title-line2{
    font-size:160px;font-weight:900;color:#E2231A;
    letter-spacing:-8px;line-height:.85;
    text-shadow:3px 5px 0px rgba(226,35,26,.12);
    margin-bottom:8px;
}
.title-line3{
    font-size:72px;font-weight:900;color:#111;
    letter-spacing:-2px;line-height:1;margin-bottom:50px;
}
.sep{
    width:400px;height:4px;background:#111;
    margin-bottom:42px;
}
.subtitle{
    font-size:38px;font-weight:500;color:#999;
    font-style:italic;max-width:800px;
    margin-bottom:50px;
}
.meta{
    font-size:30px;font-weight:600;color:#ccc;
    letter-spacing:3px;text-transform:uppercase;
}
/* Watermark grade grid — lower decorative */
.grade-watermark{
    position:absolute;bottom:120px;left:0;right:0;
    display:flex;justify-content:center;gap:40px;
    opacity:.07;pointer-events:none;
    flex-wrap:wrap;padding:0 80px;
}
.wm-grade{
    font-size:200px;font-weight:900;color:#111;
    line-height:.85;letter-spacing:-8px;
}
/* Bottom decorative line */
.bottom-line{
    position:absolute;bottom:0;left:0;right:0;height:8px;
    background:#E2231A;
}
"""


class GradeReportVariant:
    """
    VARIANT 3 — THE GRADE REPORT

    Authority signal: Academic grading is universally understood, instantly
    legible, and triggers strong opinions ("B? really?").
    Target engagement: HIGHEST save rate — people screenshot A/S grade cards
    to send to friends. The white design also stands out massively on TikTok's
    dark feed (pattern interrupt beats stop-scroll hooks).
    Missing in Roblox TikTok: Clean, white, structured editorial design.
    The format is proven in general gaming (game streamers who grade games get
    massive engagement) but has never been done as a Roblox carousel.
    """

    def cover_html(
        self,
        hook: str,
        part: int,
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_GRADER_COVER_CSS}</style></head><body>
<div class="stamp-decor"><div class="stamp-text">GRADE<br>REPORT</div></div>
<div class="badge">part {part}</div>
<div class="block">
  <div class="official">Official assessment</div>
  <div class="title-line1">Roblox Game</div>
  <div class="title-line2">GRADES</div>
  <div class="title-line3">Part {part}</div>
  <div class="sep"></div>
  <div class="subtitle">"{h(hook)}"</div>
  <div class="meta">independently assessed · gemvault</div>
</div>
<div class="grade-watermark">
  <span class="wm-grade">S</span>
  <span class="wm-grade">A+</span>
  <span class="wm-grade">B</span>
</div>
<div class="bottom-line"></div>
</body></html>"""

    def game_slide_html(
        self,
        name: str,
        creator: str,
        overall_grade: str,
        subgrades: dict[str, str],
        assessment: str,
        visits_m: float,
        recommended: bool,
        part: int,
        index: int,
    ) -> str:
        ff = _font_faces()
        h = _html.escape

        grade_class = {
            "S": "", "A+": " grade-a", "A": " grade-a",
            "B+": " grade-b", "B": " grade-b",
            "C": " grade-c",
        }.get(overall_grade, "")
        underline_class = "grade-a-underline" if "A" in overall_grade else "grade-s-underline"

        def sg_cls(g: str) -> str:
            if g in ("S", "A+", "A"):
                return ""
            if g in ("B+", "B"):
                return " sg-a"
            return " sg-b"

        sg_html = ""
        for key, val in subgrades.items():
            sg_html += (
                f'<div class="subgrade">'
                f'<div class="sg-key">{h(key)}</div>'
                f'<div class="sg-val{sg_cls(val)}">{h(val)}</div>'
                f'</div>'
            )

        stamp_html = (
            '<div class="stamp">'
            '<span class="stamp-icon">✓</span>'
            '<span class="stamp-text">Recommended</span>'
            '</div>'
            if recommended else
            '<div class="stamp" style="border-color:#b71c1c;">'
            '<span class="stamp-text" style="color:#b71c1c;">Skip It</span>'
            '</div>'
        )

        visits_str = f"{visits_m:.1f}M visits"

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_GRADER_CSS}</style></head><body>
<div class="header">
  <span class="report-wordmark">Grade Report</span>
  <span class="part-num">pick {index} · part {part}</span>
</div>
<div class="game-section">
  <div class="game-name">{h(name)}</div>
  <div class="creator">by {h(creator)}</div>
</div>
<div class="grade-card">
  <div class="grade-top-label">Overall Grade</div>
  <div class="grade-big{grade_class}">{h(overall_grade)}</div>
  <div class="grade-underline {underline_class}"></div>
  <div class="overall-label">Final Grade</div>
</div>
<div class="subgrades">{sg_html}</div>
<div class="assessment-section">
  <div class="assess-label">Assessment</div>
  <div class="assess-text">"{h(assessment)}"</div>
</div>
<div class="stamp-row">
  {stamp_html}
  <span class="visit-count">{h(visits_str)}</span>
</div>
<div class="footer">
  <span class="foot-handle">@gemvault</span>
  <span class="foot-right">part {part} of ?</span>
</div>
</body></html>"""
