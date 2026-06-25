"""Regression test — modern Pillow must expose legacy resampling constants after
the compat shim runs, so moviepy 1.0.3 video rendering doesn't crash with
"module 'PIL.Image' has no attribute 'ANTIALIAS'"."""
from __future__ import annotations

from PIL import Image

from src.content.pil_compat import ensure_resampling


def test_ensure_resampling_restores_antialias(monkeypatch):
    # Simulate Pillow 10+ where the legacy names are gone.
    for name in ("ANTIALIAS", "BICUBIC", "BILINEAR", "NEAREST"):
        monkeypatch.delattr(Image, name, raising=False)
    ensure_resampling()
    assert hasattr(Image, "ANTIALIAS")
    assert Image.ANTIALIAS == Image.Resampling.LANCZOS
    assert Image.BICUBIC == Image.Resampling.BICUBIC


def test_ensure_resampling_is_idempotent():
    ensure_resampling()
    ensure_resampling()
    assert hasattr(Image, "ANTIALIAS")


def test_resize_with_legacy_constant_works(monkeypatch):
    monkeypatch.delattr(Image, "ANTIALIAS", raising=False)
    ensure_resampling()
    img = Image.new("RGB", (100, 100), (10, 20, 30))
    out = img.resize((50, 50), Image.ANTIALIAS)  # the exact call moviepy makes
    assert out.size == (50, 50)
