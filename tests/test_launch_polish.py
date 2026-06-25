"""
Tests for the launch-polish fixes:
  - DescriptionEngine.generate_local builds captions WITHOUT an API call
  - base.html ships responsive breakpoints + collapsible nav labels
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "api" / "templates"


def test_generate_local_needs_no_api_call(monkeypatch):
    # If the local path touched the Anthropic client, this would blow up.
    from src.content.description_engine import DescriptionEngine

    eng = DescriptionEngine.__new__(DescriptionEngine)
    from src.config import get_settings
    eng._settings = get_settings()

    def _boom(*a, **k):
        raise AssertionError("generate_local must not call the Anthropic API")

    eng._client = type("C", (), {"messages": type("M", (), {"create": _boom})()})()
    res = eng.generate_local(name="Doomspire", score=8.4, label="WORTH PLAYING 🎮",
                             visits=900_000, genre="adventure")
    assert res.description_a and res.description_b
    assert res.hashtags        # local hashtags still built
    # Intentional local copy is NOT a degradation — never flagged as fallback.
    assert res.used_fallback is False


def test_description_ai_failure_flags_fallback(monkeypatch):
    """Audit M3: when the AI caption call fails, the rule-based captions must be
    flagged so degraded video copy is never mistaken for AI output."""
    from src.content.description_engine import DescriptionEngine
    from src.config import get_settings

    eng = DescriptionEngine.__new__(DescriptionEngine)
    eng._settings = get_settings()

    def _boom(*a, **k):
        raise RuntimeError("anthropic down")

    eng._client = type("C", (), {"messages": type("M", (), {"create": _boom})()})()
    res = eng.generate(name="Doomspire", score=8.4, label="WORTH PLAYING 🎮",
                       verdict="solid", visits=900_000, genre="adventure",
                       hook_text="is it good?", controversy_angle="")
    assert res.description_a and res.description_b
    assert res.used_fallback is True


def test_base_html_has_responsive_breakpoints():
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                      autoescape=select_autoescape())
    html = env.get_template("base.html").render(
        request=type("R", (), {"url": type("U", (), {"path": "/"})()})())
    assert "@media (max-width: 1024px)" in html
    assert "@media (max-width: 768px)" in html
    assert "nav-text" in html          # labels are collapsible on phones
    assert 'name="viewport"' in html
