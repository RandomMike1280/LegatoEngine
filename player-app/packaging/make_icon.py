"""Draws the player's icon: piano keys under an orange play button.

    uv run python player-app/packaging/make_icon.py

Writes icon.png (also the window icon), icon.icns for the Mac app and icon.ico for Windows.
"""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
S = 2048  # drawn at twice the size, then scaled down for smooth edges


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # the rounded square of the macOS icon grid: 824 of 1024, centred
    margin, radius = S * 100 // 1024, S * 185 // 1024
    box = (margin, margin, S - margin, S - margin)
    background = Image.new("RGBA", (S, S))
    top, bottom = (46, 49, 61), (21, 22, 27)
    for y in range(S):
        f = y / S
        ImageDraw.Draw(background).line([(0, y), (S, y)], fill=tuple(round(a + (b - a) * f) for a, b in zip(top, bottom)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    img.paste(background, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # six white keys, C to A, with their four black keys
    left, right = margin + S * 70 // 1024, S - margin - S * 70 // 1024
    keys_top, keys_bottom = S * 560 // 1024, S - margin - S * 70 // 1024
    gap = S * 10 // 1024
    white = (right - left - 5 * gap) / 6
    for i in range(6):
        x = left + i * (white + gap)
        d.rounded_rectangle((x, keys_top, x + white, keys_bottom), S * 22 // 1024, fill=(244, 244, 246))
    black_w, black_h = white * 0.58, (keys_bottom - keys_top) * 0.6
    for after in (0, 1, 3, 4):
        cx = left + (after + 1) * (white + gap) - gap / 2
        d.rounded_rectangle((cx - black_w / 2, keys_top - 2, cx + black_w / 2, keys_top + black_h),
                            S * 16 // 1024, fill=(22, 23, 27))

    # the play button
    cx, cy, r = S / 2, S * 345 // 1024, S * 150 // 1024
    tri = [(cx - r * 0.62, cy - r), (cx - r * 0.62, cy + r), (cx + r * 1.0, cy)]
    d.polygon(tri, fill=(240, 140, 58))
    return img.resize((1024, 1024), Image.LANCZOS)


def main() -> None:
    icon = draw()
    icon.save(HERE / "icon.png")
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)
    # Windows shows icons edge to edge, so crop away the Mac grid's empty margin
    inner = icon.crop((90, 90, 934, 934))
    inner.save(HERE / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote icon.png, icon.icns and icon.ico")


if __name__ == "__main__":
    main()
