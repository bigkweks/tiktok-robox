"""
Phase 4 workflow tests — no auto-approval; export gated on human approval.

  - a pending_review carousel shows Approve / Regenerate and HIDES export
  - an approved carousel shows the export ("Save … slides") action
  - the AI-status banner element is present on every page (base.html)
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "api" / "templates"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                       autoescape=select_autoescape())


class _Req:
    def __init__(self, path: str = "/carousels"):
        self.url = type("U", (), {"path": path})()


class _Settings:
    OUTPUT_DIR = "output"


def _post(status: str) -> dict:
    return {
        "id": 1, "part_number": 3, "edition": "Hidden Gems", "status": status,
        "caption": "actually good roblox games to play", "created_at": datetime(2026, 6, 25, 12, 0),
        "slide_paths_list": ["output/carousels/p/slide_00.png"],
        "slide_urls": ["/output/carousels/p/slide_00.png"],
        "hashtags_str": "#roblox #robloxgames",
        "review_score": 84.0,
        "review": {"reviewers": [{"name": "Growth Strategist", "score": 80}]},
    }


def _render(status: str) -> str:
    tmpl = _env().get_template("carousels.html")
    return tmpl.render(request=_Req(), carousels=[_post(status)], settings=_Settings())


def test_pending_review_shows_approve_and_hides_export():
    html = _render("pending_review")
    assert "Approve" in html
    assert "Regenerate" in html
    assert "awaiting your approval" in html
    # The export button (saveCarouselToPhotos) must NOT be available pre-approval.
    assert "saveCarouselToPhotos(this)" not in html
    assert "to unlock saving" in html


def test_approved_shows_export_action():
    html = _render("approved")
    assert "saveCarouselToPhotos(this)" in html   # export unlocked
    assert "Mark as posted" in html


def test_ai_status_banner_present_on_every_page():
    # base.html (inherited by all pages) must carry the credential banner + poll.
    tmpl = _env().get_template("base.html")
    html = tmpl.render(request=_Req("/"))
    assert 'id="ai-status-banner"' in html
    assert "refreshAiStatus" in html
