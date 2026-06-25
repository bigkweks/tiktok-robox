"""
Export validation tests — no carousel may export with wrong dimensions, blank /
corrupt slides, missing files, or a placeholder hero.
"""
from __future__ import annotations

from PIL import Image

from src.content.carousel_generator import CarouselGame, CarouselGenerator
from src.content.export_validator import EXPORT_H, EXPORT_W, validate_carousel_export


def _game(name="Real Game"):
    return CarouselGame(
        name=name, creator="Dev", score=8.4, carousel_caption="actually fun",
        like_ratio=0.9, active_players=600, thumbnail_url="http://x/t.png",
        icon_url=None, genre="adventure", visits=900_000,
        description="A real game.", blurb="worth a look",
    )


def _render(tmp_path, monkeypatch, *, thumbs_ok=True, slug="v"):
    if thumbs_ok:
        monkeypatch.setattr(CarouselGenerator, "_fetch_thumbnail",
                            lambda self, url: Image.new("RGB", (1280, 720), (20, 110, 200)))
    else:
        monkeypatch.setattr(CarouselGenerator, "_fetch_thumbnail",
                            lambda self, url: None)
    gen = CarouselGenerator()
    report = gen.generate([_game(f"G{i}") for i in range(5)],
                          output_dir=tmp_path / slug, slug=slug)
    return [str(p) for p in report.slides]


def test_valid_carousel_passes(tmp_path, monkeypatch):
    paths = _render(tmp_path, monkeypatch, thumbs_ok=True)
    v = validate_carousel_export(paths)
    assert v.ok is True
    assert v.checked == 6
    assert v.reasons == []


def test_placeholder_hero_fails_validation(tmp_path, monkeypatch):
    paths = _render(tmp_path, monkeypatch, thumbs_ok=False, slug="ph")
    v = validate_carousel_export(paths)
    assert v.ok is False
    assert any("placeholder" in r for r in v.reasons)


def test_wrong_dimensions_fail(tmp_path):
    p = tmp_path / "bad.png"
    Image.new("RGB", (800, 800), (10, 10, 10)).save(p)
    v = validate_carousel_export([str(p)], check_placeholder=False)
    assert v.ok is False
    assert any("dimensions" in r for r in v.reasons)


def test_correct_dimensions_constant():
    assert (EXPORT_W, EXPORT_H) == (1080, 1920)


def test_missing_file_fails(tmp_path):
    v = validate_carousel_export([str(tmp_path / "nope.png")])
    assert v.ok is False
    assert any("missing" in r for r in v.reasons)


def test_blank_slide_fails(tmp_path):
    p = tmp_path / "blank.png"
    Image.new("RGB", (EXPORT_W, EXPORT_H), (12, 12, 12)).save(p)
    v = validate_carousel_export([str(p)], check_placeholder=False)
    assert v.ok is False
    assert any("blank" in r for r in v.reasons)


def test_empty_list_fails():
    v = validate_carousel_export([])
    assert v.ok is False


def test_corrupt_image_fails(tmp_path):
    p = tmp_path / "corrupt.png"
    p.write_bytes(b"not a real png")
    v = validate_carousel_export([str(p)])
    assert v.ok is False
    assert any("corrupt" in r or "unreadable" in r for r in v.reasons)
