"""
Tests for the one-step "save all carousel slides" feature.

The button uses the Web Share API to drop every slide into the iPad Photos app
at once; the /carousel/{id}/download zip is the fallback. These tests cover the
zip bundling and that the share button is wired into the carousels page.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.api.dashboard import build_slides_zip

_TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "api" / "templates"


class _Req:
    def __init__(self, path):
        self.url = type("U", (), {"path": path})()


def test_build_slides_zip_bundles_existing_files_in_order(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"s{i}.png"
        p.write_bytes(b"PNG" + bytes([i]))
        paths.append(str(p))
    # a missing leading path must be skipped without shifting the rest
    paths.insert(0, str(tmp_path / "missing.png"))

    data = build_slides_zip(paths)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert names == ["slide_2.png", "slide_3.png", "slide_4.png"]


def test_build_slides_zip_empty_when_nothing_on_disk(tmp_path):
    assert build_slides_zip([str(tmp_path / "nope.png")]) == b""
    assert build_slides_zip([]) == b""
    assert build_slides_zip(["", None]) == b""  # type: ignore[list-item]


def test_carousels_page_renders_share_button():
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                      autoescape=select_autoescape())
    post = {
        "id": 7, "part_number": 3, "edition": "Anime edition", "status": "approved",
        "caption": "cap", "created_at": __import__("datetime").datetime(2026, 6, 24, 12, 0),
        "posted_at": None, "posted_at_iso": None,
        "slide_paths_list": ["output/carousels/part003/slide_00.png"],
        "slide_urls": ["/output/carousels/part003/slide_00.png",
                       "/output/carousels/part003/slide_01.png"],
        "hashtags_str": "#a #b",
        "review_score": None, "review": None,
        "tiktok_views": None, "tiktok_likes": None, "tiktok_comments": None,
        "tiktok_shares": None, "tiktok_saves": None, "tiktok_follows": None,
        "hours_since_post": None, "analytics_recorded_at": None, "generation_id": None,
    }
    html = env.get_template("carousels.html").render(
        request=_Req("/carousels"),
        carousels=[post],
        settings=type("S", (), {"OUTPUT_DIR": "output"})(),
    )
    assert "saveCarouselToPhotos(this)" in html
    # Export is now one tap: slides + caption together.
    assert "Save 2 slides + caption" in html
    # slide URLs embedded for the share call
    assert "/output/carousels/part003/slide_01.png" in html
    # zip fallback link present
    assert "/carousel/7/download" in html
    # the share helper + Web Share usage are defined on the page
    assert "navigator.share" in html
    assert "navigator.canShare" in html
