"""Generate a 512×512 app icon for the TikTok Developer Portal."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("assets/app_icon_1024.png")


def main() -> None:
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background: brand purple with a slightly darker centre-fill
    draw.rounded_rectangle([0, 0, size, size], radius=160, fill="#6C63FF")
    draw.rounded_rectangle([40, 40, size - 40, size - 40], radius=136, fill="#5a52d5")

    # Diamond gem shape (centred)
    cx, cy = size // 2, size // 2 - 60
    gem_w, gem_h = 400, 360
    top    = (cx, cy - gem_h // 2)
    left   = (cx - gem_w // 2, cy + 40)
    right  = (cx + gem_w // 2, cy + 40)
    bottom = (cx, cy + gem_h // 2 + 20)
    tl     = (cx - gem_w // 4, cy - gem_h // 2 + 60)
    tr     = (cx + gem_w // 4, cy - gem_h // 2 + 60)

    gem_poly = [top, tr, right, bottom, left, tl]
    draw.polygon(gem_poly, fill="white")

    # Inner highlight triangle
    inner = [(cx, cy - gem_h // 2 + 20), tr, tl]
    draw.polygon(inner, fill="#d0ccff")

    # "RG" text below gem
    font_path = Path("assets/fonts/Poppins-ExtraBold.ttf")
    if font_path.exists():
        font = ImageFont.truetype(str(font_path), 200)
    else:
        font = ImageFont.load_default()

    text = "RG"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = cy + gem_h // 2 + 40 - bbox[1]
    draw.text((tx, ty), text, font=font, fill="white")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(OUT), "PNG")
    print(f"App icon saved → {OUT}")


if __name__ == "__main__":
    main()
