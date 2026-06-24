"""
Template-level test for the Content DNA dashboard page — it must render the
five formulas, the 14-dimension table, and the prior/extracted state without a
live server or DB.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.content.content_dna import DIMENSIONS, seed_prior_profile, synthesize_profile
from src.content.content_dna import Pattern

_TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "api" / "templates"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                       autoescape=select_autoescape())


class _Req:
    def __init__(self, path: str):
        self.url = type("U", (), {"path": path})()


def test_dna_page_renders_prior():
    consolidated = seed_prior_profile()
    html = _env().get_template("dna.html").render(
        request=_Req("/dna"),
        consolidated=consolidated.as_dict(),
        profiles=[],
        dimensions=list(DIMENSIONS),
    )
    assert "Content DNA" in html
    assert "Hook Formula" in html
    assert "Slide Formula" in html
    assert "Retention Formula" in html
    assert "CTA Formula" in html
    assert "Visual Formula" in html
    assert "prior" in html.lower()
    # All 14 dimensions surfaced in the detail table.
    for dim in DIMENSIONS:
        assert dim in html


def test_dna_page_renders_extracted_profiles():
    patterns = {dim: Pattern(dim, f"why {dim}", 0.7, sample_count=3) for dim in DIMENSIONS}
    consolidated = synthesize_profile(patterns, source_count=3, label="Consolidated DNA")
    profile = synthesize_profile(patterns, source_count=1, label="horror pt4")
    html = _env().get_template("dna.html").render(
        request=_Req("/dna"),
        consolidated=consolidated.as_dict(),
        profiles=[profile.as_dict()],
        dimensions=list(DIMENSIONS),
    )
    assert "horror pt4" in html
    assert "source(s)" in html  # the consolidated source-count badge
