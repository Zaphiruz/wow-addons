"""Draws the Hopscotch logo: a gold hopscotch grid with dotted hop arcs.

Usage: python hopscotch_logo.py out.png   (needs Pillow)
"""
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, GOLD_LIGHT, gold_fill, background, sparkle, finish

BG_CENTER = (58, 112, 64)
BG_EDGE = (8, 26, 14)
CELL = 50
GAP = 4
# Grid cells as centres, bottom to top: single, pair, single, pair.
ROWS = [(258, [200]), (204, [173, 227]), (150, [200]), (96, [173, 227])]


def grid_layer():
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    mask = Image.new("L", (W, W), 0)
    inner = Image.new("L", (W, W), 0)
    dm, di = ImageDraw.Draw(mask), ImageDraw.Draw(inner)
    half = (CELL - GAP) / 2
    for cy, xs in ROWS:
        for cx in xs:
            box = [s(cx - half), s(cy - half), s(cx + half), s(cy + half)]
            dm.rounded_rectangle(box, radius=s(5), fill=255)
            di.rounded_rectangle([b + (s(6) if i < 2 else -s(6)) for i, b in enumerate(box)], radius=s(3), fill=255)
    frame = Image.composite(Image.new("L", (W, W), 0), mask, inner)

    shadow = mask.filter(ImageFilter.GaussianBlur(s(5)))
    layer.paste((0, 0, 0, 120), (s(3), s(6)), shadow)
    layer.paste((14, 40, 20, 200), (0, 0), inner)
    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, frame, (s(70), s(285)))
    layer = Image.alpha_composite(layer, gold)
    d = ImageDraw.Draw(layer)
    for cy, xs in ROWS:
        for cx in xs:
            d.rounded_rectangle([s(cx - half), s(cy - half), s(cx + half), s(cy + half)],
                                radius=s(5), outline=INK + (255,), width=s(2.5))
    return layer


def hop_dots():
    """A dotted bouncing trail up the right of the grid: one arc per hop."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x_base, bulge = 270, 34
    ys = [cy for cy, _ in ROWS]
    for y0, y1 in zip(ys, ys[1:]):
        for i in range(0, 8):
            t = i / 8
            x = x_base + bulge * 4 * t * (1 - t)
            y = y0 + (y1 - y0) * t
            r = 4 if i == 0 else 3
            d.ellipse([s(x - r), s(y - r), s(x + r), s(y + r)], fill=GOLD_LIGHT + (240,), outline=INK + (255,), width=s(1))
    x, y = x_base, ys[-1]
    d.ellipse([s(x - 4), s(y - 4), s(x + 4), s(y + 4)], fill=GOLD_LIGHT + (240,), outline=INK + (255,), width=s(1))
    return layer


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -30))
    canvas.alpha_composite(grid_layer())
    canvas.alpha_composite(hop_dots())
    d = ImageDraw.Draw(canvas)
    sparkle(d, 300, 70, 10, (255, 246, 210, 255))
    sparkle(d, 96, 120, 7, (255, 240, 190, 230))
    sparkle(d, 112, 236, 8, (255, 246, 210, 240))
    finish(canvas, "HOPSCOTCH", out, title_size=46, tracking=3)


if __name__ == "__main__":
    main(sys.argv[1])
