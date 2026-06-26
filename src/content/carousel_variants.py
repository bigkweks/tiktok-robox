"""
carousel_variants.py — Three editorial carousel systems (anti-slop rebuild).

COMPETITIVE ANALYSIS: Roblox vs. General Gaming TikTok
──────────────────────────────────────────────────────
Roblox game-rec channels run a DISCOVERY architecture ("here are games"):
raw screenshot + text overlay, no authority, no editorial point of view.
Top general-gaming carousels (200K–2M views) run an AUTHORITY architecture —
the creator TESTED, RANKED, or GRADED. That reframing turns a list into
reference material people save, screenshot, and argue with.

THE DESIGN PROBLEM (v1 → v2)
────────────────────────────
v1 imported the right *formats* but rendered them in AI-slop visual language:
neon-glow badges, saturated radial gradients, dead-centre symmetry, and
Poppins (a default Google font). This v2 keeps the formats but rebuilds the
craft to read editorial, not generated:
  · Type: Fraunces (high-contrast serif) + Space Grotesk + Bricolage Grotesque,
    replacing Poppins. The single biggest anti-slop lever.
  · Zero glows. Depth comes from grain, hairlines, and nested bezels.
  · Muted, art-directed palettes (brass / sage / ember / cream), not pure RGB.
  · Asymmetric editorial composition with intentional whitespace rhythm.
  · Film-grain overlay on every slide for a physical, printed feel.

Three formats, three art directions:
  ① THE SCOUT REPORT  → dark dossier · reviewer authority   (Fraunces + Grotesk)
  ② THE TIER DROP     → black stage · flat stamped tiers     (Bricolage + Grotesk)
  ③ THE GRADE REPORT  → cream paper · academic certificate   (Fraunces serif)
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import io
import tempfile
from pathlib import Path

from PIL import Image

PREMIUM_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts" / "premium"
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# family name → (weight, filename)
_FONTS = {
    ("Fraunces", 400): "Fraunces-400.woff2",
    ("Fraunces", 600): "Fraunces-600.woff2",
    ("Fraunces", 700): "Fraunces-700.woff2",
    ("Fraunces", 900): "Fraunces-900.woff2",
    ("Space Grotesk", 500): "SpaceGrotesk-500.woff2",
    ("Space Grotesk", 700): "SpaceGrotesk-700.woff2",
    ("Bricolage Grotesque", 700): "Bricolage-700.woff2",
    ("Bricolage Grotesque", 800): "Bricolage-800.woff2",
}


def _font_faces() -> str:
    parts = []
    for (family, weight), fname in _FONTS.items():
        path = PREMIUM_DIR / fname
        if not path.exists():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode()
        uri = f"data:font/woff2;base64,{b64}"
        parts.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};"
            f"font-style:normal;font-display:block;"
            f"src:url('{uri}')format('woff2');}}"
        )
    return "\n".join(parts)


# Film-grain overlay (fixed, pointer-events-none). A physical printed-paper
# texture that flattens the "rendered" feel. Light vs dark variant by opacity.
def _grain(opacity: float = 0.05) -> str:
    svg = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "viewBox='0 0 320 320'%3E%3Cfilter id='n'%3E%3CfeTurbulence "
        "type='fractalNoise' baseFrequency='0.82' numOctaves='3' "
        "stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' "
        "height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"
    )
    return (
        f'<div style="position:absolute;inset:0;pointer-events:none;z-index:60;'
        f'opacity:{opacity};mix-blend-mode:overlay;'
        f'background-image:url(\"{svg}\");background-size:320px 320px"></div>'
    )


def _accent_for(name: str) -> str:
    """A muted, art-directed accent hex unique to a game (never neon)."""
    palette = [
        "#B5512F",  # terracotta
        "#5E7A52",  # moss
        "#3E6B7A",  # slate teal
        "#8A6D3B",  # bronze
        "#7A4A52",  # dusty plum
        "#46685B",  # pine
        "#9A5B3F",  # clay
        "#5A6478",  # blue-grey
    ]
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    return palette[h % len(palette)]


def _muted_field(name: str) -> tuple[str, str]:
    """Two deep, desaturated tones for an art panel — no saturated gradients."""
    fields = [
        ("#1d1518", "#3a2630"),  # oxblood
        ("#14191a", "#243838"),  # deep teal
        ("#1a1714", "#352a1f"),  # umber
        ("#161a18", "#27352c"),  # forest
        ("#181620", "#2c2740"),  # ink violet
        ("#1a1618", "#332430"),  # mulberry
    ]
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    return fields[h % len(fields)]


def img_to_uri(src) -> str:
    """
    Turn a PIL.Image, a file path, or a raw http(s) URL into a value usable
    directly in CSS `url(...)`.

    - PIL.Image / Path / local file  → embedded base64 data URI (works offline)
    - http(s) string                  → returned as-is (Chromium fetches it; in
      the Codespace this is the REAL Roblox homepage thumbnail / icon)

    This is the seam that lets the SAME renderer take a real Roblox screenshot in
    production and a local raster in the sandbox.
    """
    if src is None:
        return ""
    if isinstance(src, str):
        if src.startswith(("http://", "https://", "data:")):
            return src
        src = Image.open(src)
    if isinstance(src, Image.Image):
        buf = io.BytesIO()
        src.convert("RGB").save(buf, format="JPEG", quality=88)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    raise TypeError(f"unsupported art source: {type(src)}")


def _render_html(html_src: str) -> Image.Image:
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


# ═════════════════════════════════════════════════════════════════════════════
# VARIANT 1 — THE SCOUT REPORT  ·  dark dossier, reviewer authority
#
# Art direction: a printed review-magazine spread on warm charcoal stock.
# Fraunces serif carries the verdict as an editorial pull-quote; Space Grotesk
# handles data with technical precision. The score is set as type, not a glowing
# medal. Authority signal nobody in Roblox TikTok uses: "tested, then judged".
# ═════════════════════════════════════════════════════════════════════════════

_SCOUT_BASE = """
*{margin:0;padding:0;box-sizing:border-box;}
:root{
    --ink:#F3EDE2; --ink-soft:rgba(243,237,226,.55); --ink-faint:rgba(243,237,226,.30);
    --paper:#15120F; --line:rgba(243,237,226,.12);
}
body{
    width:1080px;height:1920px;overflow:hidden;position:relative;
    background:
        radial-gradient(120% 80% at 50% -10%, #1c1813 0%, #15120F 55%),
        #15120F;
    color:var(--ink);
    font-family:'Space Grotesk',sans-serif;
    -webkit-font-smoothing:antialiased;
}
.eyebrow{
    font-family:'Space Grotesk';font-weight:500;
    font-size:25px;letter-spacing:.42em;text-transform:uppercase;
    color:var(--ink-faint);
}
.rule{height:1px;background:var(--line);width:100%;}
"""

_SCOUT_CSS = _SCOUT_BASE + """
/* Masthead */
.masthead{
    position:absolute;top:0;left:0;right:0;
    padding:64px 96px 30px;
    display:flex;justify-content:space-between;align-items:baseline;
    border-bottom:1px solid var(--line);
}
.mast-title{
    font-family:'Fraunces';font-weight:900;font-size:34px;
    letter-spacing:.01em;color:var(--ink);
}
.mast-title em{font-style:italic;font-weight:400;color:var(--ink-soft);}
.mast-meta{font-size:24px;letter-spacing:.28em;color:var(--ink-faint);text-transform:uppercase;}

/* Art plate — real in-game capture, double-bezel, no glow */
.plate-shell{
    position:absolute;top:150px;left:96px;right:96px;height:430px;
    padding:10px;border-radius:26px;
    background:rgba(243,237,226,.04);
    border:1px solid var(--line);
}
.plate{
    width:100%;height:100%;border-radius:18px;overflow:hidden;position:relative;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.06);
}
.plate-art{position:absolute;inset:0;background-size:cover;background-position:center;}
.plate-fade{
    position:absolute;inset:0;
    background:linear-gradient(180deg,rgba(10,8,6,.05) 0%,transparent 32%,rgba(10,8,6,.62) 100%);
}
.plate-tag{
    position:absolute;left:30px;bottom:26px;
    font-family:'Space Grotesk';font-weight:500;font-size:23px;
    letter-spacing:.3em;text-transform:uppercase;color:rgba(255,255,255,.78);
}
/* Real Roblox game icon, inset on the capture */
.plate-icon{
    position:absolute;right:26px;bottom:24px;width:104px;height:104px;
    border-radius:22px;background-size:cover;background-position:center;
    box-shadow:0 6px 22px rgba(0,0,0,.5),inset 0 0 0 1px rgba(255,255,255,.25);
}
/* Swipe-progress ticks (retention affordance) */
.progress{
    position:absolute;top:592px;left:96px;right:96px;
    display:flex;gap:10px;align-items:center;
}
.tick{height:4px;border-radius:2px;background:rgba(243,237,226,.16);flex:1;}
.tick.on{background:#B5512F;}

/* Headline row: serif name + scored numeral */
.head{
    position:absolute;top:640px;left:96px;right:96px;
    display:flex;justify-content:space-between;align-items:flex-end;gap:40px;
}
.name-block{flex:1;}
.kicker{
    font-size:24px;letter-spacing:.3em;text-transform:uppercase;
    color:var(--ink-faint);margin-bottom:18px;
}
.game-name{
    font-family:'Fraunces';font-weight:900;font-size:84px;line-height:.96;
    letter-spacing:-.015em;color:var(--ink);
}
.game-name em{font-style:italic;font-weight:400;}
.creator{
    font-family:'Space Grotesk';font-weight:500;font-size:30px;
    color:var(--ink-soft);margin-top:18px;letter-spacing:.01em;
}
.score-stack{text-align:right;flex-shrink:0;padding-bottom:6px;}
.score-num{
    font-family:'Fraunces';font-weight:900;font-size:128px;line-height:.82;
    letter-spacing:-.03em;color:var(--ink);
}
.score-out{
    font-family:'Space Grotesk';font-weight:500;font-size:30px;
    color:var(--ink-faint);letter-spacing:.05em;margin-top:6px;
}
.score-cap{
    font-size:22px;letter-spacing:.34em;text-transform:uppercase;
    color:#C46A4E;margin-top:10px;
}

/* Verdict — editorial pull-quote */
.verdict{
    position:absolute;top:900px;left:96px;right:96px;
    padding-left:34px;border-left:2px solid #B5512F;
}
.verdict-text{
    font-family:'Fraunces';font-weight:400;font-style:italic;
    font-size:54px;line-height:1.28;color:var(--ink);
    letter-spacing:-.005em;
}

/* Spec table — not pill-blobs, an editorial data row */
.specs{
    position:absolute;top:1190px;left:96px;right:96px;
    display:flex;border-top:1px solid var(--line);border-bottom:1px solid var(--line);
}
.spec{
    flex:1;padding:36px 0 32px;
    border-right:1px solid var(--line);
}
.spec:last-child{border-right:none;padding-left:0;}
.spec{padding-left:34px;}
.spec:first-child{padding-left:0;}
.spec-key{
    font-size:23px;letter-spacing:.26em;text-transform:uppercase;
    color:var(--ink-faint);margin-bottom:16px;
}
.spec-val{
    font-family:'Fraunces';font-weight:700;font-size:62px;line-height:1;
    color:var(--ink);
}

/* Field notes */
.notes{
    position:absolute;top:1430px;left:96px;right:96px;
}
.notes-label{
    font-size:24px;letter-spacing:.3em;text-transform:uppercase;
    color:#C46A4E;margin-bottom:26px;
}
.note{
    display:flex;gap:24px;align-items:flex-start;margin-bottom:24px;
    font-family:'Fraunces';font-weight:400;font-size:40px;line-height:1.34;
    color:var(--ink-soft);
}
.note-idx{
    font-family:'Space Grotesk';font-weight:700;font-size:26px;
    color:#B5512F;line-height:1.8;flex-shrink:0;letter-spacing:.05em;
}

/* Colophon footer */
.colophon{
    position:absolute;bottom:0;left:0;right:0;
    padding:40px 96px 56px;
    display:flex;justify-content:space-between;align-items:center;
    border-top:1px solid var(--line);
}
.colo-left{font-size:25px;letter-spacing:.04em;color:var(--ink-faint);}
.colo-right{
    font-family:'Space Grotesk';font-weight:700;font-size:25px;
    letter-spacing:.2em;text-transform:uppercase;color:var(--ink-soft);
}
"""

_SCOUT_COVER_CSS = _SCOUT_BASE + """
.frame{position:absolute;inset:54px;border:1px solid var(--line);border-radius:8px;pointer-events:none;}
.mast{
    position:absolute;top:118px;left:118px;right:118px;
    display:flex;justify-content:space-between;align-items:baseline;
}
.mast em{font-style:italic;}
.issue{
    font-family:'Space Grotesk';font-weight:500;font-size:24px;
    letter-spacing:.3em;text-transform:uppercase;color:var(--ink-faint);
}
.center{
    position:absolute;top:330px;left:118px;right:118px;
    display:flex;flex-direction:column;
}
.over{
    font-size:26px;letter-spacing:.4em;text-transform:uppercase;
    color:#C46A4E;margin-bottom:46px;
    display:flex;align-items:center;gap:26px;
}
.over::before{content:'';width:72px;height:1px;background:#B5512F;}
.hook{
    font-family:'Fraunces';font-weight:900;font-size:142px;line-height:.94;
    letter-spacing:-.03em;color:var(--ink);margin-bottom:8px;
}
.hook em{font-style:italic;font-weight:400;color:var(--ink-soft);}
.sub{
    font-family:'Fraunces';font-weight:400;font-style:italic;
    font-size:50px;line-height:1.3;color:var(--ink-soft);
    margin-top:40px;max-width:840px;
}
/* Contact sheet — previews the five field captures inside */
.strip-label{
    position:absolute;top:1300px;left:118px;
    font-family:'Space Grotesk';font-weight:500;font-size:23px;
    letter-spacing:.3em;text-transform:uppercase;color:var(--ink-faint);
}
.strip{
    position:absolute;top:1346px;left:118px;right:118px;
    display:flex;gap:14px;
}
.cap{
    flex:1;height:212px;border-radius:10px;position:relative;overflow:hidden;
    background-size:cover;background-position:center;
    border:1px solid var(--line);box-shadow:inset 0 1px 0 rgba(255,255,255,.06);
}
.cap-fade{position:absolute;inset:0;background:linear-gradient(transparent 45%,rgba(8,6,5,.7));}
.cap-n{position:absolute;left:12px;bottom:9px;font-family:'Space Grotesk';font-weight:700;font-size:21px;color:rgba(255,255,255,.92);letter-spacing:.05em;}
.foot{
    position:absolute;bottom:120px;left:118px;right:118px;
    display:flex;justify-content:space-between;align-items:center;
    padding-top:36px;border-top:1px solid var(--line);
}
.foot-l{font-size:25px;letter-spacing:.3em;text-transform:uppercase;color:var(--ink-faint);}
.foot-r{font-family:'Fraunces';font-weight:700;font-size:30px;color:var(--ink);letter-spacing:.02em;}
"""


class ScoutReportVariant:
    """VARIANT 1 — THE SCOUT REPORT (editorial dark dossier)."""

    def cover_html(self, hook_main: str, hook_em: str, sub: str, part: int,
                   arts=None) -> str:
        ff = _font_faces()
        h = _html.escape
        arts = arts or []
        if arts:
            caps = "".join(
                f'<div class="cap" style="background-image:url(\'{img_to_uri(a)}\');">'
                f'<div class="cap-fade"></div><div class="cap-n">{i+1:02d}</div></div>'
                for i, a in enumerate(arts[:5])
            )
            strip = (
                '<div class="strip-label">This issue · five field captures</div>'
                f'<div class="strip">{caps}</div>'
            )
        else:
            strip = ""
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_SCOUT_COVER_CSS}</style></head><body>
<div class="frame"></div>
<div class="mast">
  <div class="mast-title" style="font-family:'Fraunces';font-weight:900;font-size:34px;">
    The Gemvault <em>Scout</em></div>
  <div class="issue">Issue {part:02d}</div>
</div>
<div class="center">
  <div class="over">Field-tested dispatch</div>
  <div class="hook">{h(hook_main)}<br><em>{h(hook_em)}</em></div>
  <div class="sub">{h(sub)}</div>
</div>
{strip}
<div class="foot">
  <span class="foot-l">Five entries · independently played</span>
  <span class="foot-r">No. {part:02d}</span>
</div>
{_grain(0.055)}
</body></html>"""

    def game_slide_html(
        self, name: str, name_em: str, creator: str, score: float, verdict: str,
        hours: int, active_label: str, like_pct: int, visits_label: str,
        note1: str, note2: str, part: int, index: int,
        art=None, icon=None, total: int = 5,
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        # Real in-game capture fills the plate; gradient only if art is absent.
        art_uri = img_to_uri(art)
        if art_uri:
            plate_bg = f"background-image:url('{art_uri}');"
        else:
            d, m = _muted_field(name)
            plate_bg = f"background:radial-gradient(130% 100% at 28% 18%, {m} 0%, {d} 62%);"
        icon_uri = img_to_uri(icon)
        icon_html = (
            f'<div class="plate-icon" style="background-image:url(\'{icon_uri}\');"></div>'
            if icon_uri else ""
        )
        ticks = "".join(
            f'<div class="tick{" on" if i < index else ""}"></div>'
            for i in range(total)
        )
        name_html = h(name) + (f' <em>{h(name_em)}</em>' if name_em else "")
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_SCOUT_CSS}</style></head><body>
<div class="masthead">
  <div class="mast-title">The Gemvault <em>Scout</em></div>
  <div class="mast-meta">No. {index:02d} / {total:02d} · Issue {part:02d}</div>
</div>
<div class="plate-shell"><div class="plate">
  <div class="plate-art" style="{plate_bg}"></div>
  <div class="plate-fade"></div>
  <div class="plate-tag">In-game capture · {index:02d}</div>
  {icon_html}
</div></div>
<div class="progress">{ticks}</div>
<div class="head">
  <div class="name-block">
    <div class="kicker">The entry</div>
    <div class="game-name">{name_html}</div>
    <div class="creator">built by {h(creator)}</div>
  </div>
  <div class="score-stack">
    <div class="score-num">{score:.1f}</div>
    <div class="score-out">out of 10</div>
    <div class="score-cap">Scout score</div>
  </div>
</div>
<div class="verdict"><div class="verdict-text">“{h(verdict)}”</div></div>
<div class="specs">
  <div class="spec"><div class="spec-key">Hours in</div><div class="spec-val">{hours}</div></div>
  <div class="spec"><div class="spec-key">Playing now</div><div class="spec-val">{h(active_label)}</div></div>
  <div class="spec"><div class="spec-key">Rated up</div><div class="spec-val">{like_pct}%</div></div>
</div>
<div class="notes">
  <div class="notes-label">Field notes</div>
  <div class="note"><span class="note-idx">01</span><span>{h(note1)}</span></div>
  <div class="note"><span class="note-idx">02</span><span>{h(note2)}</span></div>
</div>
<div class="colophon">
  <span class="colo-left">{h(visits_label)} lifetime visits</span>
  <span class="colo-right">Verified gem</span>
</div>
{_grain(0.05)}
</body></html>"""


# ═════════════════════════════════════════════════════════════════════════════
# VARIANT 2 — THE TIER DROP  ·  black stage, flat stamped tiers
#
# Art direction: a gallery wall, not a slot machine. The tier is a FLAT
# letterpress stamp — solid muted brass / sage / slate, sharp edges, no glow.
# Bricolage Grotesque gives the game name a confident, characterful weight.
# This format (tier debate) is absent from Roblox TikTok; the comment war it
# starts is the whole point.
# ═════════════════════════════════════════════════════════════════════════════

_TIER_TONES = {
    "S": ("#C9A24B", "#0d0c09"),   # brass on near-black
    "A": ("#7E9B6B", "#0a0c0a"),   # sage
    "B": ("#6E8AA0", "#090b0d"),   # slate
    "C": ("#B07A52", "#0d0a08"),   # clay
}

_TIER_BASE = """
*{margin:0;padding:0;box-sizing:border-box;}
body{
    width:1080px;height:1920px;overflow:hidden;position:relative;
    background:#0A0A0C;color:#F4F1EA;
    font-family:'Space Grotesk',sans-serif;-webkit-font-smoothing:antialiased;
}
.vign{position:absolute;inset:0;background:radial-gradient(120% 90% at 50% 38%,transparent 40%,rgba(0,0,0,.7) 100%);pointer-events:none;}
"""

_TIER_CSS = _TIER_BASE + """
.art{position:absolute;inset:0;}
.art-grad{position:absolute;inset:0;background-size:cover;background-position:center;}
/* Veil reveals the real screenshot up top, deepens to solid for text legibility */
.art-veil{
    position:absolute;inset:0;
    background:linear-gradient(180deg,
        rgba(10,10,12,.12) 0%,rgba(10,10,12,.22) 16%,
        rgba(10,10,12,.58) 40%,rgba(10,10,12,.86) 68%,#0A0A0C 92%);
}
/* A faint brand wash so the screenshot never looks accidental */
.art-tint{position:absolute;inset:0;mix-blend-mode:soft-light;
    background:linear-gradient(180deg,rgba(201,162,75,.10),transparent 40%);}
/* Swipe-progress ticks */
.progress{position:absolute;top:148px;left:96px;right:96px;display:flex;gap:10px;}
.tick{height:4px;border-radius:2px;background:rgba(244,241,234,.18);flex:1;}
.tick.on{background:#C9A24B;}
.chip{
    position:absolute;top:80px;left:96px;
    font-family:'Space Grotesk';font-weight:500;font-size:25px;
    letter-spacing:.34em;text-transform:uppercase;color:rgba(244,241,234,.45);
}
.chip-r{
    position:absolute;top:80px;right:96px;
    font-family:'Space Grotesk';font-weight:500;font-size:25px;
    letter-spacing:.34em;text-transform:uppercase;color:rgba(244,241,234,.45);
}
.stage{
    position:absolute;top:300px;left:96px;right:96px;
    display:flex;flex-direction:column;align-items:flex-start;
}
/* Flat stamped tier block — no glow, sharp letterpress */
.stamp{
    width:300px;height:300px;border-radius:28px;
    display:flex;align-items:center;justify-content:center;
    position:relative;margin-bottom:64px;
    box-shadow:inset 0 0 0 2px rgba(255,255,255,.14), inset 0 2px 0 rgba(255,255,255,.12);
}
.stamp-letter{
    font-family:'Fraunces';font-weight:900;font-size:210px;line-height:1;
    letter-spacing:-.04em;color:#0A0A0C;
}
.stamp-plus{
    position:absolute;top:30px;right:34px;
    font-family:'Fraunces';font-weight:900;font-size:74px;color:rgba(10,10,12,.7);line-height:1;
}
.stamp-tier{
    position:absolute;bottom:-14px;left:50%;transform:translateX(-50%);
    background:#0A0A0C;padding:0 18px;
    font-family:'Space Grotesk';font-weight:700;font-size:25px;
    letter-spacing:.4em;text-transform:uppercase;color:rgba(244,241,234,.6);
}
.tier-name{
    font-family:'Bricolage Grotesque';font-weight:800;
    font-size:118px;line-height:.92;letter-spacing:-.025em;color:#F4F1EA;
    text-shadow:0 2px 50px rgba(0,0,0,.7);margin-bottom:54px;max-width:880px;
}
.divider{display:flex;align-items:center;gap:24px;margin-bottom:42px;}
.divider-line{width:88px;height:2px;}
.divider-label{
    font-family:'Space Grotesk';font-weight:700;font-size:26px;
    letter-spacing:.32em;text-transform:uppercase;
}
.why{
    font-family:'Fraunces';font-weight:400;font-style:italic;
    font-size:62px;line-height:1.26;color:rgba(244,241,234,.92);
    letter-spacing:-.01em;max-width:900px;
}
.foot{
    position:absolute;bottom:78px;left:96px;right:96px;
    display:flex;justify-content:space-between;align-items:center;
    padding-top:38px;border-top:1px solid rgba(244,241,234,.12);
}
.foot span{font-family:'Space Grotesk';font-weight:500;font-size:30px;color:rgba(244,241,234,.42);letter-spacing:.02em;}
"""

_TIER_COVER_CSS = _TIER_BASE + """
.glow{position:absolute;top:42%;left:50%;transform:translate(-50%,-58%);width:1000px;height:1000px;
    background:radial-gradient(ellipse,rgba(201,162,75,.08) 0%,transparent 62%);pointer-events:none;}
.issue{position:absolute;top:88px;right:96px;font-weight:500;font-size:25px;letter-spacing:.34em;text-transform:uppercase;color:rgba(244,241,234,.4);}
.brand{position:absolute;top:88px;left:96px;font-family:'Fraunces';font-weight:900;font-size:32px;color:rgba(244,241,234,.7);}
.brand em{font-style:italic;font-weight:400;}
.mid{position:absolute;top:40px;left:0;right:0;height:1240px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 96px;}
.label{font-family:'Space Grotesk';font-weight:700;font-size:30px;letter-spacing:.5em;text-transform:uppercase;color:#C9A24B;margin-bottom:30px;padding-left:.5em;}
.big{
    font-family:'Fraunces';font-weight:900;font-size:470px;line-height:.78;
    letter-spacing:-.05em;color:#C9A24B;margin-bottom:26px;
}
.wordmark{font-family:'Bricolage Grotesque';font-weight:800;font-size:100px;letter-spacing:-.02em;color:#F4F1EA;line-height:1;margin-bottom:18px;}
.tagline{font-family:'Fraunces';font-weight:400;font-style:italic;font-size:44px;color:rgba(244,241,234,.55);text-align:center;max-width:760px;line-height:1.3;}
/* Filmstrip — the five contenders, dealt like cards */
.film-label{position:absolute;top:1330px;left:0;right:0;text-align:center;font-family:'Space Grotesk';font-weight:700;font-size:24px;letter-spacing:.4em;text-transform:uppercase;color:rgba(244,241,234,.4);}
.film{position:absolute;top:1390px;left:0;right:0;display:flex;justify-content:center;align-items:center;gap:8px;}
.film-card{
    width:158px;height:206px;border-radius:14px;background-size:cover;background-position:center;
    border:1px solid rgba(255,255,255,.16);
    box-shadow:0 14px 34px rgba(0,0,0,.6);position:relative;
}
.film-card:nth-child(1){transform:rotate(-6deg) translateY(10px);}
.film-card:nth-child(2){transform:rotate(-3deg);}
.film-card:nth-child(3){transform:rotate(0deg) translateY(-8px);z-index:2;}
.film-card:nth-child(4){transform:rotate(3deg);}
.film-card:nth-child(5){transform:rotate(6deg) translateY(10px);}
.foot{position:absolute;bottom:96px;left:0;right:0;text-align:center;font-family:'Space Grotesk';font-weight:500;font-size:26px;letter-spacing:.3em;text-transform:uppercase;color:rgba(244,241,234,.32);}
"""


class TierDropVariant:
    """VARIANT 2 — THE TIER DROP (flat stamped tiers, no neon)."""

    def cover_html(self, tagline: str, part: int, arts=None) -> str:
        ff = _font_faces()
        h = _html.escape
        arts = arts or []
        if arts:
            cards = "".join(
                f'<div class="film-card" style="background-image:url(\'{img_to_uri(a)}\');"></div>'
                for a in arts[:5]
            )
            film = f'<div class="film-label">inside this drop</div><div class="film">{cards}</div>'
        else:
            film = ""
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_TIER_COVER_CSS}</style></head><body>
<div class="glow"></div>
<div class="brand">The Gemvault <em>Ranked</em></div>
<div class="issue">Drop {part:02d}</div>
<div class="mid">
  <div class="label">S — Tier Only</div>
  <div class="big">S</div>
  <div class="wordmark">ROBLOX</div>
  <div class="tagline">{h(tagline)}</div>
</div>
{film}
<div class="vign"></div>
<div class="foot">five games · ranked, not random</div>
{_grain(0.05)}
</body></html>"""

    def game_slide_html(
        self, name: str, creator: str, tier: str, why: str,
        visits_label: str, active_label: str, part: int, index: int,
        art=None, total: int = 5,
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        base_tier = tier.rstrip("+")
        tone, _ = _TIER_TONES.get(base_tier, _TIER_TONES["A"])
        # Real screenshot fills the whole frame behind the veil.
        art_uri = img_to_uri(art)
        if art_uri:
            art_bg = f"background-image:url('{art_uri}');"
        else:
            d, m = _muted_field(name)
            art_bg = f"background:radial-gradient(120% 90% at 30% 22%, {m} 0%, {d} 58%);"
        ticks = "".join(
            f'<div class="tick{" on" if i < index else ""}"></div>'
            for i in range(total)
        )
        plus = '<div class="stamp-plus">+</div>' if "+" in tier else ""
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_TIER_CSS}</style></head><body>
<div class="art">
  <div class="art-grad" style="{art_bg}"></div>
  <div class="art-tint"></div>
  <div class="art-veil"></div>
</div>
<div class="chip">Pick {index:02d} / {total:02d}</div>
<div class="chip-r">Drop {part:02d}</div>
<div class="progress">{ticks}</div>
<div class="stage">
  <div class="stamp" style="background:{tone};">
    <div class="stamp-letter">{h(base_tier)}</div>
    {plus}
    <div class="stamp-tier">Tier</div>
  </div>
  <div class="tier-name">{h(name)}</div>
  <div class="divider">
    <div class="divider-line" style="background:{tone};"></div>
    <div class="divider-label" style="color:{tone};">Why {h(tier)}</div>
  </div>
  <div class="why">“{h(why)}”</div>
</div>
<div class="foot">
  <span>{h(visits_label)} visits</span>
  <span>by {h(creator)}</span>
  <span>{h(active_label)} now</span>
</div>
<div class="vign"></div>
{_grain(0.05)}
</body></html>"""


# ═════════════════════════════════════════════════════════════════════════════
# VARIANT 3 — THE GRADE REPORT  ·  cream paper, academic certificate
#
# Art direction: an engraved assessment certificate on warm letterpress stock.
# Fraunces serif throughout sells the academic authority; the cream paper is a
# hard pattern-interrupt on TikTok's dark feed (the strongest scroll-stopper).
# Highest save-rate format — people screenshot grade cards to friends.
# ═════════════════════════════════════════════════════════════════════════════

_GRADE_INK = {
    "S":  "#A6332B", "A+": "#3F6B43", "A": "#3F6B43",
    "B+": "#3E6378", "B": "#3E6378", "C": "#9A6326",
}

_GRADE_BASE = """
*{margin:0;padding:0;box-sizing:border-box;}
:root{
    --paper:#F4EEE2; --ink:#1C1813; --ink-soft:#6B6357; --ink-faint:#A39A8B;
    --line:#D8CFBE; --ember:#A6332B;
}
body{
    width:1080px;height:1920px;overflow:hidden;position:relative;
    background:var(--paper);color:var(--ink);
    font-family:'Space Grotesk',sans-serif;-webkit-font-smoothing:antialiased;
}
.deckle{position:absolute;inset:34px;border:2px solid var(--ink);border-radius:4px;pointer-events:none;}
.deckle2{position:absolute;inset:44px;border:1px solid var(--line);border-radius:2px;pointer-events:none;}
"""

_GRADE_CSS = _GRADE_BASE + """
.head{
    position:absolute;top:84px;left:96px;right:96px;
    display:flex;justify-content:space-between;align-items:baseline;
    padding-bottom:30px;border-bottom:1px solid var(--line);
}
.seal{font-family:'Fraunces';font-weight:900;font-size:30px;letter-spacing:.02em;}
.seal em{font-style:italic;font-weight:400;color:var(--ink-soft);}
.head-meta{font-weight:500;font-size:24px;letter-spacing:.28em;text-transform:uppercase;color:var(--ink-faint);}

.subject{position:absolute;top:212px;left:96px;right:96px;}
.subject-label{font-weight:500;font-size:24px;letter-spacing:.34em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:20px;}
.game-name{font-family:'Fraunces';font-weight:900;font-size:88px;line-height:.98;letter-spacing:-.02em;color:var(--ink);}
.creator{font-family:'Fraunces';font-weight:400;font-style:italic;font-size:38px;color:var(--ink-soft);margin-top:18px;}

/* Grade + Exhibit card — the grade letter beside the real in-game capture */
.exhibit{
    position:absolute;top:500px;left:96px;right:96px;height:408px;
    border:2px solid var(--ink);border-radius:14px;overflow:hidden;
    display:flex;background:#fff;
}
.ex-grade{
    width:42%;flex-shrink:0;
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    border-right:2px solid var(--ink);padding:18px;
}
.med-top{font-weight:500;font-size:22px;letter-spacing:.34em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:2px;text-align:center;}
.grade{
    font-family:'Fraunces';font-weight:900;font-size:208px;line-height:.82;
    letter-spacing:-.04em;
}
.med-rule{width:96px;height:2px;background:var(--ink);margin:12px auto 12px;}
.med-bottom{font-weight:700;font-size:21px;letter-spacing:.26em;text-transform:uppercase;color:var(--ink-soft);text-align:center;}
.ex-photo{flex:1;position:relative;background-size:cover;background-position:center;background-color:#1a1714;}
.ex-cap{
    position:absolute;left:0;right:0;bottom:0;
    background:linear-gradient(transparent,rgba(18,15,12,.82));
    color:#F4EEE2;padding:42px 24px 20px;
    font-family:'Space Grotesk';font-weight:500;font-size:21px;
    letter-spacing:.22em;text-transform:uppercase;
}

/* Sub-grade ledger */
.ledger{
    position:absolute;top:952px;left:96px;right:96px;
    border-top:1.5px solid var(--ink);border-bottom:1.5px solid var(--ink);
    display:flex;
}
.lcol{flex:1;padding:28px 0 26px;text-align:center;border-right:1px solid var(--line);}
.lcol:last-child{border-right:none;}
.lkey{font-weight:500;font-size:23px;letter-spacing:.22em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:14px;}
.lval{font-family:'Fraunces';font-weight:900;font-size:60px;line-height:1;}

/* Assessment */
.assess{position:absolute;top:1156px;left:96px;right:96px;}
.assess-label{font-weight:500;font-size:24px;letter-spacing:.34em;text-transform:uppercase;color:var(--ember);margin-bottom:22px;}
.assess-text{font-family:'Fraunces';font-weight:400;font-size:48px;line-height:1.38;color:var(--ink);}

/* Verdict stamp row */
.stamp-row{
    position:absolute;top:1556px;left:96px;right:96px;
    display:flex;justify-content:space-between;align-items:center;gap:30px;
}
.verdict-stamp{
    display:inline-flex;align-items:baseline;gap:16px;flex-shrink:0;
    border:2.5px solid var(--ember);border-radius:6px;padding:18px 34px;
    transform:rotate(-2deg);
}
.verdict-stamp .vs-lead{font-family:'Space Grotesk';font-weight:700;font-size:22px;letter-spacing:.2em;text-transform:uppercase;color:var(--ink-faint);}
.verdict-stamp .vs-main{font-family:'Fraunces';font-weight:900;font-size:40px;letter-spacing:.02em;color:var(--ember);text-transform:uppercase;}
.visits{font-family:'Fraunces';font-weight:400;font-style:italic;font-size:32px;color:var(--ink-faint);text-align:right;line-height:1.25;flex-shrink:0;}

.foot{
    position:absolute;bottom:78px;left:96px;right:96px;
    display:flex;justify-content:space-between;align-items:center;
    padding-top:30px;border-top:1px solid var(--line);
}
.foot span{font-weight:500;font-size:24px;letter-spacing:.2em;text-transform:uppercase;color:var(--ink-faint);}
.foot .sig{font-family:'Fraunces';font-weight:700;font-style:italic;font-size:30px;letter-spacing:0;text-transform:none;color:var(--ink-soft);}
"""

_GRADE_COVER_CSS = _GRADE_BASE + """
.seal-mark{
    position:absolute;top:120px;left:50%;transform:translateX(-50%);
    width:184px;height:184px;border-radius:50%;
    border:2px solid var(--ember);display:flex;align-items:center;justify-content:center;
}
.seal-mark span{font-family:'Fraunces';font-weight:900;font-size:30px;color:var(--ember);text-align:center;line-height:1.05;letter-spacing:.02em;}
.center{position:absolute;top:346px;left:0;right:0;display:flex;flex-direction:column;align-items:center;padding:0 110px;text-align:center;}
.over{font-weight:500;font-size:26px;letter-spacing:.46em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:28px;padding-left:.46em;}
.l1{font-family:'Fraunces';font-weight:400;font-style:italic;font-size:62px;color:var(--ink-soft);line-height:1;margin-bottom:6px;}
.l2{font-family:'Fraunces';font-weight:900;font-size:168px;line-height:.9;letter-spacing:-.03em;color:var(--ink);margin-bottom:10px;}
.l3{font-family:'Fraunces';font-weight:400;font-style:italic;font-size:58px;color:var(--ember);line-height:1;}
.rule{width:340px;height:1.5px;background:var(--ink);margin:46px 0 40px;}
.sub{font-family:'Fraunces';font-weight:400;font-size:43px;line-height:1.36;color:var(--ink-soft);max-width:760px;}
/* Specimens on file — captures clipped to the certificate, each with its grade */
.spec-label{position:absolute;top:1372px;left:0;right:0;text-align:center;font-weight:500;font-size:23px;letter-spacing:.34em;text-transform:uppercase;color:var(--ink-faint);}
.specimens{position:absolute;top:1420px;left:96px;right:96px;display:flex;gap:14px;}
.spec{flex:1;height:202px;border:2px solid var(--ink);border-radius:8px;position:relative;overflow:hidden;background-size:cover;background-position:center;background-color:#1a1714;}
.spec-tag{position:absolute;bottom:0;left:0;background:var(--paper);border-top:2px solid var(--ink);border-right:2px solid var(--ink);border-radius:0 8px 0 6px;padding:3px 14px;font-family:'Fraunces';font-weight:900;font-size:30px;line-height:1.1;}
.foot{position:absolute;bottom:110px;left:0;right:0;text-align:center;font-weight:500;font-size:25px;letter-spacing:.34em;text-transform:uppercase;color:var(--ink-faint);}
"""

# ── Newspaper front-page cover (the committed direction) ─────────────────────
_NEWS_COVER_CSS = _GRADE_BASE + """
.page{position:absolute;inset:0;padding:74px 92px 56px;display:flex;flex-direction:column;}
.topline{
    display:flex;justify-content:space-between;align-items:center;
    font-weight:500;font-size:21px;letter-spacing:.26em;text-transform:uppercase;
    color:var(--ink-soft);margin-bottom:14px;
}
.rule-d{border-top:4px solid var(--ink);border-bottom:1px solid var(--ink);height:5px;}
.masthead{
    text-align:center;font-family:'Fraunces';font-weight:900;
    font-size:74px;line-height:1;letter-spacing:-1px;color:var(--ink);
    margin:18px 0 16px;white-space:nowrap;
}
.dateline{
    display:flex;justify-content:space-between;align-items:center;
    padding:14px 4px;border-top:1px solid var(--ink);border-bottom:1px solid var(--ink);
    font-weight:500;font-size:22px;letter-spacing:.18em;text-transform:uppercase;color:var(--ink-soft);
}
.dateline .stars{color:var(--ember);letter-spacing:.34em;font-size:24px;}
.kicker{
    text-align:center;font-weight:700;font-size:24px;letter-spacing:.4em;
    text-transform:uppercase;color:var(--ember);margin-top:34px;
}
.headline{
    text-align:center;font-family:'Fraunces';font-weight:900;
    font-size:96px;line-height:.97;letter-spacing:-3px;color:var(--ink);
    margin-top:16px;
}
.deck{
    text-align:center;font-family:'Fraunces';font-weight:400;font-style:italic;
    font-size:40px;line-height:1.28;color:var(--ink-soft);
    margin:24px auto 0;max-width:840px;
    padding-bottom:26px;border-bottom:1px solid var(--line);
}
/* Hero photo — fills remaining height, printed-newspaper duotone */
.photo-shell{
    flex:1;min-height:0;display:flex;flex-direction:column;
    margin-top:30px;
    border:2px solid var(--ink);padding:12px;background:#fff;
}
.photo-wrap{flex:1;min-height:0;position:relative;overflow:hidden;}
.photo{
    position:absolute;inset:0;background-size:cover;background-position:center 40%;
    filter:grayscale(.66) contrast(1.14) sepia(.42) brightness(.98);
}
.halftone{
    position:absolute;inset:0;mix-blend-mode:multiply;opacity:.22;
    background-image:radial-gradient(circle, rgba(20,15,10,.9) 0.7px, transparent 1.4px);
    background-size:5px 5px;
}
.photo-edge{position:absolute;inset:0;box-shadow:inset 0 0 0 1px rgba(20,15,10,.25);}
.photo-cap{
    display:flex;justify-content:space-between;align-items:baseline;
    margin-top:12px;font-weight:500;font-size:21px;letter-spacing:.04em;
    color:var(--ink-soft);
}
.photo-cap .em{font-family:'Fraunces';font-style:italic;font-weight:400;font-size:24px;color:var(--ink);}
.teaser{
    margin-top:26px;padding-top:22px;border-top:4px double var(--ink);
    text-align:center;font-family:'Fraunces';font-weight:900;font-size:38px;
    letter-spacing:.01em;color:var(--ink);
}
.teaser .ar{color:var(--ember);}
"""


class GradeReportVariant:
    """VARIANT 3 — THE GRADE REPORT (cream academic certificate)."""

    def newspaper_cover_html(
        self, headline: str, deck: str, caption: str, part: int,
        hero=None, masthead: str = "The Gemvault Gazette",
        kicker: str = "The Roblox Desk · Exclusive",
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        hero_uri = img_to_uri(hero)
        photo_bg = f"background-image:url('{hero_uri}');" if hero_uri else ""
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_NEWS_COVER_CSS}</style></head><body>
<div class="deckle"></div><div class="deckle2"></div>
<div class="page">
  <div class="topline">
    <span>Vol. {part:02d}</span>
    <span>Roblox Edition · Est. 2024</span>
    <span>Independent &amp; Unbought</span>
  </div>
  <div class="rule-d"></div>
  <div class="masthead">{h(masthead)}</div>
  <div class="dateline">
    <span>Friday Edition · No. {part:02d}</span>
    <span class="stars">★★★★★</span>
    <span>Price: one follow</span>
  </div>
  <div class="kicker">{h(kicker)}</div>
  <div class="headline">{h(headline)}</div>
  <div class="deck">{h(deck)}</div>
  <div class="photo-shell">
    <div class="photo-wrap">
      <div class="photo" style="{photo_bg}"></div>
      <div class="halftone"></div>
      <div class="photo-edge"></div>
    </div>
    <div class="photo-cap">
      <span>{h(caption)}</span>
      <span class="em">graded inside ▸</span>
    </div>
  </div>
  <div class="teaser">Full grades &amp; verdicts inside <span class="ar">▸▸</span> swipe</div>
</div>
{_grain(0.05)}
</body></html>"""

    def cover_html(self, l1: str, l3: str, sub: str, part: int,
                   arts=None, tags=None) -> str:
        ff = _font_faces()
        h = _html.escape
        arts = arts or []
        tags = tags or ["S", "A+", "A", "B", "A"]
        if arts:
            specs = ""
            for i, a in enumerate(arts[:5]):
                tag = tags[i] if i < len(tags) else "A"
                ink = _GRADE_INK.get(tag, "#1C1813")
                specs += (
                    f'<div class="spec" style="background-image:url(\'{img_to_uri(a)}\');">'
                    f'<div class="spec-tag" style="color:{ink};">{h(tag)}</div></div>'
                )
            specimens = (
                '<div class="spec-label">Specimens on file · grades inside</div>'
                f'<div class="specimens">{specs}</div>'
            )
        else:
            specimens = ""
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_GRADE_COVER_CSS}</style></head><body>
<div class="deckle"></div><div class="deckle2"></div>
<div class="seal-mark"><span>GEM<br>VAULT</span></div>
<div class="center">
  <div class="over">Official assessment · No. {part:02d}</div>
  <div class="l1">{h(l1)}</div>
  <div class="l2">ROBLOX</div>
  <div class="l3">{h(l3)}</div>
  <div class="rule"></div>
  <div class="sub">{h(sub)}</div>
</div>
{specimens}
<div class="foot">independently graded · part {part:02d}</div>
{_grain(0.045)}
</body></html>"""

    def game_slide_html(
        self, name: str, creator: str, overall: str, subgrades: dict[str, str],
        assessment: str, visits_label: str, recommended: bool, part: int, index: int,
        art=None,
    ) -> str:
        ff = _font_faces()
        h = _html.escape
        ink = _GRADE_INK.get(overall, "#A6332B")
        art_uri = img_to_uri(art)
        photo_bg = f"background-image:url('{art_uri}');" if art_uri else ""

        def sg_ink(g: str) -> str:
            return _GRADE_INK.get(g, "#1C1813")

        ledger = ""
        for k, v in subgrades.items():
            ledger += (
                f'<div class="lcol"><div class="lkey">{h(k)}</div>'
                f'<div class="lval" style="color:{sg_ink(v)};">{h(v)}</div></div>'
            )

        if recommended:
            stamp = (
                '<div class="verdict-stamp">'
                '<span class="vs-lead">Verdict</span>'
                '<span class="vs-main">Recommended</span></div>'
            )
        else:
            stamp = (
                '<div class="verdict-stamp" style="border-color:#6B6357;">'
                '<span class="vs-lead">Verdict</span>'
                '<span class="vs-main" style="color:#6B6357;">Pass For Now</span></div>'
            )

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{ff}\n{_GRADE_CSS}</style></head><body>
<div class="deckle"></div><div class="deckle2"></div>
<div class="head">
  <div class="seal">Grade <em>Report</em></div>
  <div class="head-meta">Entry {index:02d} · No. {part:02d}</div>
</div>
<div class="subject">
  <div class="subject-label">Subject under review</div>
  <div class="game-name">{h(name)}</div>
  <div class="creator">developed by {h(creator)}</div>
</div>
<div class="exhibit">
  <div class="ex-grade">
    <div class="med-top">Overall</div>
    <div class="grade" style="color:{ink};">{h(overall)}</div>
    <div class="med-rule" style="background:{ink};"></div>
    <div class="med-bottom">Final grade</div>
  </div>
  <div class="ex-photo" style="{photo_bg}">
    <div class="ex-cap">Exhibit {index:02d} · in-game capture</div>
  </div>
</div>
<div class="ledger">{ledger}</div>
<div class="assess">
  <div class="assess-label">Examiner's note</div>
  <div class="assess-text">“{h(assessment)}”</div>
</div>
<div class="stamp-row">
  {stamp}
  <span class="visits">{h(visits_label)}<br>visits on record</span>
</div>
<div class="foot">
  <span>@gemvault</span>
  <span class="sig">— assessed by hand</span>
  <span>No. {part:02d}</span>
</div>
{_grain(0.045)}
</body></html>"""
