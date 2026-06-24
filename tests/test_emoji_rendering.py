"""
Regression tests for emoji rendering.

Root cause that motivated these: the video pipeline drew decorative emoji
inline with the Poppins/Liberation text fonts, which have no emoji glyphs, so
they rasterised as tofu boxes (□). Emoji must instead be composited as real
color glyphs, and free-text fields (game names, captions) that carry emoji the
text font cannot draw must be stripped so they never tofu.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from src.content.fonts import (
    contains_emoji,
    draw_mixed,
    load_font,
    measure_mixed,
    strip_emoji,
    _segment,
)


# ── Detection ────────────────────────────────────────────────────────────

def test_detects_pictographic_emoji():
    assert contains_emoji("hidden gems 💎")
    assert contains_emoji("👁️ VISITS")        # base + variation selector
    assert contains_emoji("⚔️ anime pvp")       # U+2694 U+FE0F
    assert contains_emoji("⭐ FAVORITES")
    assert contains_emoji("nice 🔥")


def test_does_not_treat_text_symbols_as_emoji():
    # Arrows and slashes render fine in the text font — must stay text.
    assert not contains_emoji("swipe →")
    assert not contains_emoji("9.5 /10")
    assert not contains_emoji("plain caption no cap")
    assert not contains_emoji("")


def test_strip_emoji_keeps_words_and_arrows():
    assert strip_emoji("👁️ VISITS") == "VISITS"
    assert strip_emoji("hidden gems 💎") == "hidden gems"
    assert strip_emoji("swipe → 💎 go") == "swipe → go"
    assert strip_emoji("🔥🔥 Blox Fruits 🔥") == "Blox Fruits"


def test_segment_round_trips():
    text = "👁️ VISITS ⭐ FAV"
    assert "".join(chunk for _, chunk in _segment(text)) == text


# ── Rendering ────────────────────────────────────────────────────────────

def _emoji_band_is_colorful(img: Image.Image) -> bool:
    """A real color emoji introduces saturated pixels; tofu is monochrome."""
    arr = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    spread = arr.max(axis=2) - arr.min(axis=2)
    # Count pixels with meaningful color (not gray text / dark bg).
    return int((spread > 40).sum()) > 200


def test_draw_mixed_renders_real_color_emoji():
    font = load_font("bold", 60)
    base = Image.new("RGB", (760, 140), (18, 18, 28))
    out = draw_mixed(base, (380, 70), "👁️ VISITS ⭐ 💎", font, (255, 255, 255),
                     anchor="mm", shadow_offset=4)
    assert out.size == base.size
    assert _emoji_band_is_colorful(out)


def test_measure_mixed_accounts_for_emoji_width():
    font = load_font("bold", 60)
    base = Image.new("RGB", (10, 10))
    from PIL import ImageDraw
    d = ImageDraw.Draw(base)
    text_only = measure_mixed(d, "VISITS", font, 56)
    with_emoji = measure_mixed(d, "👁️ VISITS", font, 56)
    assert with_emoji > text_only


def test_video_stats_slide_has_no_tofu():
    from src.content.video_assembler import VideoAssembler
    va = VideoAssembler.__new__(VideoAssembler)
    from src.config import get_settings
    va._settings = get_settings()
    slide = va._slide_stats("🔥 Test Game", 1_500_000, 320, 45_000, None)
    assert _emoji_band_is_colorful(slide)


def test_heavy_check_emoji_actually_renders():
    # The feature bullet uses U+2714 U+FE0F (✔️) because the plain check
    # (U+2713) has no glyph in Noto Color Emoji and would render blank.
    from src.content.fonts import emoji_image
    import numpy as np
    heavy = emoji_image("✔️", 54)
    assert heavy is not None
    assert int((np.asarray(heavy)[..., 3] > 10).sum()) > 200
    assert emoji_image("✓", 54) is None or \
        int((np.asarray(emoji_image("✓", 54))[..., 3] > 10).sum()) == 0


def test_video_features_slide_renders_check_bullets():
    from src.content.video_assembler import VideoAssembler
    from src.config import get_settings
    va = VideoAssembler.__new__(VideoAssembler)
    va._settings = get_settings()
    slide = va._slide_features("G", ["Massive community", "Frequent updates"], None)
    # The color check bullets introduce non-gray pixels.
    assert _emoji_band_is_colorful(slide)


def test_plain_arrow_has_no_glyph_but_color_arrow_does():
    # The carousel "swipe" hint must use ➡️ (U+27A1), not "→" (U+2192) which
    # is tofu in both the text font and Noto.
    from src.content.fonts import emoji_image
    import numpy as np
    assert emoji_image("→", 60) is None or \
        int((np.asarray(emoji_image("→", 60))[..., 3] > 10).sum()) == 0
    color_arrow = emoji_image("➡️", 60)
    assert color_arrow is not None
    assert int((np.asarray(color_arrow)[..., 3] > 10).sum()) > 200


def test_carousel_title_slide_renders_red_wordmark():
    """Minimal cover: clean white, the ROBLOX wordmark is the one red accent."""
    import numpy as np
    from src.content.carousel_generator import CarouselGenerator, EDITIONS, ROBLOX_RED
    from src.config import get_settings
    gen = CarouselGenerator.__new__(CarouselGenerator)
    gen._settings = get_settings()
    slide = gen._make_title_slide(EDITIONS[1], 3, cover_hook="ranking roblox games no one plays")
    arr = np.asarray(slide.convert("RGB")).astype(int)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # Pixels close to Roblox red (the wordmark + rail) must be present & substantial.
    red_mask = (abs(r - ROBLOX_RED[0]) < 40) & (g < 90) & (b < 90)
    assert int(red_mask.sum()) > 2000


def test_cover_value_phrase_folds_niche_into_search_anchor():
    """Each edition's value line keeps the proven 'games to play' search anchor
    while reading niche-specific (not a generic template)."""
    from src.content.carousel_generator import _value_phrase, EDITIONS
    for label, *_ in EDITIONS:
        phrase = _value_phrase(label)
        assert "games to play" in phrase           # SEO anchor preserved everywhere
    assert _value_phrase("Horror edition") == "horror games to play"
    assert _value_phrase("Friends edition") == "games to play with friends"
    assert _value_phrase("Unknown") == "games to play"   # safe default


def test_cover_credibility_and_cta_rotate_and_carry_part():
    """The credibility line is the new trust signal (carries 'part N'); the CTA
    is a natural save line, never the old generic 'swipe to save'. Both rotate."""
    from src.content.carousel_generator import _credibility_line, _cover_cta
    creds = [_credibility_line(p) for p in range(5)]
    assert all(f"part {p}" in creds[p] for p in range(5))   # series marker present
    assert len(set(creds)) >= 4                              # rotates, not one template
    ctas = [_cover_cta(p) for p in range(5)]
    assert all("swipe to save" not in c for c in ctas)
    assert len(set(ctas)) >= 3


def test_game_slide_blurb_callout_renders_color_emoji():
    """The 'why it slaps' callout draws the 🔥 as a real color glyph and fits."""
    from src.content.carousel_generator import CarouselGenerator, CarouselGame
    from src.config import get_settings
    gen = CarouselGenerator.__new__(CarouselGenerator)
    gen._settings = get_settings()
    game = CarouselGame(
        name="Test Horror", creator="Dev", score=9.3,
        carousel_caption="horror that actually scared me", like_ratio=0.92,
        active_players=900, thumbnail_url=None, icon_url=None, genre="horror",
        visits=750_000, description="Find the exit before it finds you.",
        blurb="This is the scariest co-op horror hiding on Roblox right now.",
    )
    slide = gen._make_game_slide(game)
    assert slide.size == (1080, 1920)
    # Callout band (just below the stats row) must carry saturated emoji pixels.
    band = slide.crop((0, 1150, 1080, 1420))
    assert _emoji_band_is_colorful(band)


def test_game_slide_without_blurb_still_renders():
    """No verdict → no callout, description falls back to the full block."""
    from src.content.carousel_generator import CarouselGenerator, CarouselGame
    from src.config import get_settings
    gen = CarouselGenerator.__new__(CarouselGenerator)
    gen._settings = get_settings()
    game = CarouselGame(
        name="No Blurb", creator="Dev", score=7.5,
        carousel_caption="worth a real shot", like_ratio=0.8,
        active_players=120, thumbnail_url=None, icon_url=None, genre="obby",
        visits=300_000, description="A tricky obby with 50 stages.", blurb="",
    )
    slide = gen._make_game_slide(game)
    assert slide.size == (1080, 1920)


def test_game_slide_keeps_name_emoji_but_cleans_description():
    """Minimal redesign: the name keeps its color emoji (authentic), but the
    description is stripped to clean text — no decorative emoji clutter."""
    from src.content.carousel_generator import CarouselGenerator, CarouselGame
    from src.config import get_settings
    gen = CarouselGenerator.__new__(CarouselGenerator)
    gen._settings = get_settings()
    game = CarouselGame(
        name="Sell Lemons 👍", creator="BloxByte Games", score=8.6,
        carousel_caption="sell lemons get rich", like_ratio=0.95,
        active_players=82_300, thumbnail_url=None, icon_url=None, genre="simulator",
        visits=216_000_000,
        description="Sell Lemons 🍋 Make 💵🤑 Unlock unique powers 💪 Make deals 🤝",
        blurb="",  # no callout → description starts right under the stat pills
    )
    slide = gen._make_game_slide(game)
    # Header band still carries the name's color emoji (👍).
    assert _emoji_band_is_colorful(slide.crop((0, 70, 1080, 170)))
    # Description band is now clean text — the decorative emoji were stripped.
    assert not _emoji_band_is_colorful(slide.crop((0, 1230, 1080, 1560)))


def _has_purple(slide) -> bool:
    """True if any strongly-purple pixel (the old brand accent) remains."""
    import numpy as np
    arr = np.asarray(slide.convert("RGB")).astype(int)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # Old purple was ~ (124,111,255)/(90,78,200): high blue, blue clearly > red > green.
    purple = (b > 170) & (r > 80) & (r < 170) & (g < r) & (b - r > 60)
    return int(purple.sum()) > 200


def _has_roblox_red(slide) -> bool:
    import numpy as np
    from src.content.carousel_generator import ROBLOX_RED
    arr = np.asarray(slide.convert("RGB")).astype(int)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    red = (abs(r - ROBLOX_RED[0]) < 45) & (g < 95) & (b < 95)
    return int(red.sum()) > 800


def test_branding_is_roblox_red_not_purple():
    """QC: every slide carries the Roblox-red accent and zero purple."""
    from src.content.carousel_generator import CarouselGenerator, CarouselGame, EDITIONS
    from src.config import get_settings
    gen = CarouselGenerator.__new__(CarouselGenerator)
    gen._settings = get_settings()

    cover = gen._make_title_slide(EDITIONS[2], 5, cover_hook="ranking roblox games no one plays")
    assert _has_roblox_red(cover) and not _has_purple(cover)

    game = CarouselGame(
        name="Backrooms Escape", creator="Liminal Co", score=9.4,
        carousel_caption="horror that actually scared me", like_ratio=0.93,
        active_players=1240, thumbnail_url=None, icon_url=None, genre="horror",
        visits=820_000, description="Find the exit before the entity finds you.",
        blurb="Scariest co-op horror hiding on Roblox right now.",
    )
    last = gen._make_game_slide(game, final_cta="part 6 soon — follow")
    assert _has_roblox_red(last) and not _has_purple(last)
