"""
Pillow compatibility shim.

moviepy 1.0.3 (and other older libs) reference the legacy resampling constants
``Image.ANTIALIAS`` / ``Image.BICUBIC`` / ``Image.BILINEAR`` / ``Image.NEAREST``,
which Pillow REMOVED in 10.0 (they live under ``Image.Resampling`` now). On a
modern Pillow this raises:

    AttributeError: module 'PIL.Image' has no attribute 'ANTIALIAS'

…which crashes video resizing mid-render. Rather than pin an ancient Pillow, we
re-attach the old names to the modern enum values. Call ``ensure_resampling()``
before importing/using any library that still expects them.
"""
from __future__ import annotations

from PIL import Image

# (legacy attribute, modern Resampling member)
_ALIASES = (
    ("ANTIALIAS", "LANCZOS"),
    ("LANCZOS", "LANCZOS"),
    ("BICUBIC", "BICUBIC"),
    ("BILINEAR", "BILINEAR"),
    ("NEAREST", "NEAREST"),
    ("HAMMING", "HAMMING"),
    ("BOX", "BOX"),
)


def ensure_resampling() -> None:
    """Idempotently restore legacy ``Image.<FILTER>`` constants on modern Pillow."""
    resampling = getattr(Image, "Resampling", None)
    for legacy, modern in _ALIASES:
        if hasattr(Image, legacy):
            continue
        value = None
        if resampling is not None and hasattr(resampling, modern):
            value = getattr(resampling, modern)
        elif hasattr(Image, modern):
            value = getattr(Image, modern)
        if value is not None:
            setattr(Image, legacy, value)


__all__ = ["ensure_resampling"]
