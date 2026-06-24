"""
Integration tests: the learned performance bias actually steers cover selection,
and the Performance Insights dashboard renders.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.content.cover_generator import (
    PERF_BIAS_CAP,
    generate_cover_concepts,
    select_cover_concept,
)
from src.learning.insights import build_insights

_TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "api" / "templates"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                       autoescape=select_autoescape())


class _Req:
    def __init__(self, path: str):
        self.url = type("U", (), {"path": path})()


# ── Generator bias ──────────────────────────────────────────────────────────

def test_performance_none_matches_unbiased_selection():
    base = select_cover_concept(edition="Horror edition", performance=None)
    again = select_cover_concept(edition="Horror edition", performance={})
    assert base.name == again.name


def test_performance_bias_can_change_the_winner():
    """A strong enough (capped) nudge on a non-default archetype should be able
    to make it win, proving the learned signal feeds back into generation."""
    edition = "Horror edition"
    default = select_cover_concept(edition=edition, performance=None)
    # Find a different passing concept to promote.
    concepts = generate_cover_concepts(edition)
    other = next(c for c in concepts if c.name != default.name and c.score.passes)
    # Boost the other to the cap, throttle the default to the floor.
    bias = {other.name: PERF_BIAS_CAP, default.name: -PERF_BIAS_CAP}
    biased = select_cover_concept(edition=edition, performance=bias)
    assert biased.name == other.name
    assert biased.name != default.name


def test_performance_bias_is_bounded():
    """Even an absurd bias value can't override the scored competition wholesale —
    it's clamped, so a fatally-weak concept still loses."""
    edition = "Horror edition"
    concepts = generate_cover_concepts(edition)
    worst = min(concepts, key=lambda c: c.score.composite)
    biased = select_cover_concept(
        edition=edition, performance={worst.name: 999.0},
    )
    # The clamp keeps the nudge tiny; the worst concept shouldn't win outright
    # over the field on a single capped bonus.
    assert biased.name != worst.name or worst.score.passes


# ── Dashboard render ────────────────────────────────────────────────────────

def test_insights_page_renders_empty_state():
    html = _env().get_template("insights.html").render(
        request=_Req("/insights"),
        ins=build_insights([]),
    )
    assert "Performance Insights" in html
    assert "No drops recorded yet" in html


def test_insights_page_renders_populated():
    from src.learning.genome import CarouselGenome, edit_resilience_from_cycles
    from src.learning.components import structure_signature

    def g(i, cover, final, approved, cycles, hook="stat", cta="save"):
        return CarouselGenome(
            part=i, edition="Horror edition",
            created_at=f"2026-01-01T00:00:{i:02d}",
            hook=f"h{i}", hook_pattern=hook, cover_concept=cover,
            cta="c", cta_pattern=cta, structure=structure_signature(6, "Horror edition"),
            final_score=final, approved=approved, cycles=cycles,
            edit_resilience=edit_resilience_from_cycles(approved, cycles),
            hard_failures=[] if approved else ["generic hook"],
            fail_reasons=[] if approved else ["slide 2 serves no purpose: empty"],
            ai_signals=[] if approved else ["dive into"],
        ).as_dict()

    genomes = [g(i, "The Visit Count", 88, True, 1) for i in range(6)]
    genomes += [g(i, "The Confession", 58, False, 3) for i in range(6, 10)]
    html = _env().get_template("insights.html").render(
        request=_Req("/insights"),
        ins=build_insights(genomes),
    )
    assert "Top hook patterns" in html
    assert "Top cover patterns" in html
    assert "The Visit Count" in html
    assert "Most common failure patterns" in html
    assert "generic hook" in html
    assert "dive into" in html
    assert "Pattern classification" in html
