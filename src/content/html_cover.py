"""
HTML → Playwright cover renderer for 1080×1920 TikTok carousel covers.

Dramatically better than PIL:
  - Real Poppins with CSS letter-spacing, line-height, and text-shadow
  - Smooth CSS gradients and atmospheric glow effects
  - CSS Roblox noob character (div-based, pixel-perfect blocky shapes)
  - JS-driven hook auto-sizing after fonts are confirmed loaded
"""
from __future__ import annotations

import base64
import html as _html
import io
import tempfile
from pathlib import Path

from PIL import Image

FONT_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

_WEIGHTS = {
    "black": (900, "Poppins-Black.ttf"),
    "extrabold": (800, "Poppins-ExtraBold.ttf"),
    "semibold": (600, "Poppins-SemiBold.ttf"),
    "medium": (500, "Poppins-Medium.ttf"),
}


def _font_faces() -> str:
    parts = []
    for name, (w, fname) in _WEIGHTS.items():
        b64 = base64.b64encode((FONT_DIR / fname).read_bytes()).decode()
        uri = f"data:font/truetype;base64,{b64}"
        parts.append(
            f"@font-face{{font-family:'Poppins';font-weight:{w};"
            f"src:url('{uri}')format('truetype');}}"
        )
    return "\n".join(parts)


def _stars(n: int = 30) -> str:
    import random
    rng = random.Random(42)
    divs = []
    for _ in range(n):
        x = rng.randint(20, 1060)
        y = rng.randint(30, 1050)
        s = rng.choice([2, 2, 3, 3, 4, 5])
        op = round(rng.uniform(0.25, 0.75), 2)
        divs.append(
            f'<div style="position:absolute;left:{x}px;top:{y}px;'
            f'width:{s}px;height:{s}px;background:#fff;'
            f'border-radius:50%;opacity:{op}"></div>'
        )
    return "".join(divs)


def _noob() -> str:
    """
    Classic Roblox noob character built from CSS divs.
    Container: 380×580px. No border-radius — Roblox is all squares.

    Layout (top of container = 0):
      Head:       left=90  top=0    200×200
      Eye L:      left=115 top=65   38×42
      Eye R:      left=227 top=65   38×42
      Mouth:      left=130 top=150  120×14
      Neck:       left=155 top=200  70×18
      Torso:      left=100 top=218  180×160
      Arm L:      left=38  top=218  62×140
      Arm R:      left=280 top=218  62×140
      Hand L:     left=38  top=358  62×38
      Hand R:     left=280 top=358  62×38
      Leg L:      left=100 top=378  80×150
      Leg R:      left=200 top=378  80×150  (20px gap between legs)
      Shoe L:     left=90  top=528  100×42
      Shoe R:     left=190 top=528  100×42
    Total height: 570px
    """
    YL = "#F5C518"   # yellow skin/head
    SH = "#1A8FE3"   # blue shirt
    PN = "#278B45"   # green pants
    BK = "#0A0A0A"   # black shoes/eyes

    def d(l, t, w, h, c, extra=""):
        return (
            f'<div style="position:absolute;left:{l}px;top:{t}px;'
            f'width:{w}px;height:{h}px;background:{c};{extra}"></div>'
        )

    return (
        '<div class="noob">'
        + d(90, 0, 200, 200, YL)          # head
        + d(115, 65, 38, 42, BK)          # eye L
        + d(227, 65, 38, 42, BK)          # eye R
        + d(130, 150, 120, 14, BK)        # mouth
        + d(155, 200, 70, 18, YL)         # neck
        + d(100, 218, 180, 160, SH)       # torso
        + d(38, 218, 62, 140, SH)         # arm L
        + d(280, 218, 62, 140, SH)        # arm R
        + d(38, 358, 62, 38, YL)          # hand L
        + d(280, 358, 62, 38, YL)         # hand R
        + d(100, 378, 80, 150, PN)        # leg L
        + d(200, 378, 80, 150, PN)        # leg R
        + d(90, 528, 100, 42, BK)         # shoe L
        + d(190, 528, 100, 42, BK)        # shoe R
        + "</div>"
    )


def make_cover_html(
    hook: str,
    value: str,
    cred: str,
    cta: str,
    part_number: int,
) -> str:
    font_faces = _font_faces()
    stars = _stars()
    noob_html = _noob()

    h = _html.escape
    part_label = f"part {part_number}"
    cta_arrow = f"→ {h(cta)}"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{font_faces}

*{{margin:0;padding:0;box-sizing:border-box;}}

body{{
    width:1080px;height:1920px;overflow:hidden;
    font-family:'Poppins',sans-serif;background:#08081c;
    position:relative;
}}

/* Multi-layer atmospheric background */
.bg{{
    position:absolute;inset:0;
    background:
        radial-gradient(ellipse 800px 600px at 50% 38%,rgba(226,35,26,.16) 0%,transparent 70%),
        radial-gradient(ellipse 500px 900px at 80% 100%,rgba(30,10,60,.7) 0%,transparent 65%),
        linear-gradient(172deg,#0c0c28 0%,#140830 48%,#1e0820 100%);
}}

/* Subtle scanline texture */
.bg::after{{
    content:'';position:absolute;inset:0;
    background:repeating-linear-gradient(
        to bottom,transparent 0px,transparent 3px,
        rgba(0,0,0,.07) 3px,rgba(0,0,0,.07) 4px
    );
    pointer-events:none;
}}

/* Character area glow (behind noob) */
.char-glow{{
    position:absolute;left:50%;transform:translateX(-50%);
    top:1050px;width:700px;height:900px;
    background:radial-gradient(ellipse at 50% 30%,rgba(226,35,26,.10) 0%,transparent 60%);
    pointer-events:none;
}}

/* Roblox noob — centered, peeking from bottom */
.noob{{
    position:absolute;top:1195px;left:50%;
    transform:translateX(-50%);
    width:380px;height:580px;
    filter:drop-shadow(0 0 24px rgba(226,35,26,.22))
           drop-shadow(0 30px 40px rgba(0,0,0,.65));
}}

/* Character ground shadow ellipse */
.noob-shadow{{
    position:absolute;top:1755px;left:50%;transform:translateX(-50%);
    width:280px;height:24px;
    background:rgba(0,0,0,.55);border-radius:50%;
    filter:blur(14px);
}}

/* Part badge — top-right, red outline */
.badge{{
    position:absolute;top:90px;right:90px;
    border:3px solid #e2231a;border-radius:10px;
    padding:14px 28px;
    color:#e2231a;font-size:46px;font-weight:600;line-height:1;
    background:rgba(8,8,28,.65);letter-spacing:.5px;
}}

/* Main text block */
.block{{
    position:absolute;left:90px;right:90px;top:240px;
    display:flex;flex-direction:column;align-items:center;
}}

#hook-text{{
    font-size:160px;font-weight:900;color:#fff;
    line-height:1.0;letter-spacing:-4px;text-align:center;
    text-shadow:0 0 80px rgba(226,35,26,.55),0 0 30px rgba(226,35,26,.3);
    word-break:break-word;max-width:900px;
    margin-bottom:58px;
}}

.sep{{
    width:900px;height:3px;background:#e2231a;
    margin-bottom:52px;
    box-shadow:0 0 14px rgba(226,35,26,.65);
}}

.value{{
    font-size:74px;font-weight:800;
    color:rgba(255,255,255,.9);
    text-align:center;line-height:1.1;letter-spacing:-1px;
    max-width:900px;margin-bottom:46px;
}}

.brand{{
    font-size:102px;font-weight:900;color:#e2231a;
    text-align:center;letter-spacing:3px;
    text-shadow:0 0 44px rgba(226,35,26,.45);
    margin-bottom:52px;
}}

.cred{{
    font-size:44px;font-weight:600;
    color:rgba(255,255,255,.46);
    text-align:center;letter-spacing:.3px;margin-bottom:40px;
}}

.cta{{
    font-size:40px;font-weight:500;
    color:rgba(255,255,255,.30);
    text-align:center;letter-spacing:.5px;
}}
</style>
</head>
<body>

<div class="bg"></div>
{stars}
<div class="char-glow"></div>
<div class="noob-shadow"></div>
{noob_html}
<div class="badge">{part_label}</div>

<div class="block">
    <div id="hook-text">{h(hook)}</div>
    <div class="sep"></div>
    <div class="value" id="value-text">{h(value)}</div>
    <div class="brand">ROBLOX</div>
    <div class="cred">{h(cred)}</div>
    <div class="cta">{cta_arrow}</div>
</div>

</body>
</html>"""


def render_cover(html_src: str) -> Image.Image:
    """Render an HTML cover at 1080×1920 and return a PIL RGB image."""
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

            # Wait for all @font-face fonts to be decoded and ready.
            # Base64 fonts are synchronous to parse but async to activate — this
            # ensures the browser has measured glyphs with the real Poppins metrics
            # before we run the auto-sizer.
            page.evaluate("async () => { await document.fonts.ready; }")

            # Auto-size hook (160→80px) and value phrase (74→48px) to 2 lines max.
            page.evaluate("""() => {
                function fit(id, start, min, lhRatio) {
                    const el = document.getElementById(id);
                    if (!el) return;
                    let sz = start;
                    el.style.fontSize = sz + 'px';
                    for (let i = 0; i < 40 && sz > min; i++) {
                        const lines = Math.round(el.scrollHeight / (sz * lhRatio));
                        if (lines <= 2) break;
                        sz -= 4;
                        el.style.fontSize = sz + 'px';
                    }
                }
                fit('hook-text', 160, 80, 1.0);
                fit('value-text', 74, 48, 1.1);
            }""")

            png_bytes = page.screenshot(type="png", full_page=False)
            browser.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return Image.open(io.BytesIO(png_bytes)).convert("RGB")
