"""Draws the Downcast logo: gold chevrons stepping down over a holy-light halo.

Usage: python downcast_logo.py out.png   (needs Pillow)
"""
import math
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, gold_fill, background, sparkle, finish

BG_CENTER = (36, 78, 120)
BG_EDGE = (6, 14, 32)
HALO = (255, 248, 222)
CENTER = (200, 160)


def halo_layer():
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    cx, cy = CENTER
    rays = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(rays)
    for i in range(16):
        a = math.radians(i * 360 / 16)
        spread = math.radians(4)
        reach = 150
        pts = [(cx, cy),
               (cx + reach * math.cos(a - spread), cy + reach * math.sin(a - spread)),
               (cx + reach * math.cos(a + spread), cy + reach * math.sin(a + spread))]
        d.polygon([(s(x), s(y)) for x, y in pts], fill=70)
    d.ellipse([s(cx - 76), s(cy - 76), s(cx + 76), s(cy + 76)], fill=105)
    glow = rays.filter(ImageFilter.GaussianBlur(s(14)))
    layer.paste(HALO + (255,), (0, 0), glow)
    return layer


def chevron(cy, half_width=66, height=42, thick=24):
    """One downward chevron centred at (200, cy), gold with an ink outline."""
    cx = CENTER[0]
    pts = [(cx - half_width, cy - height / 2), (cx, cy + height / 2), (cx + half_width, cy - height / 2),
           (cx + half_width, cy - height / 2 + thick), (cx, cy + height / 2 + thick),
           (cx - half_width, cy - height / 2 + thick)]
    pts = [(s(x), s(y)) for x, y in pts]
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)

    shadow = mask.filter(ImageFilter.GaussianBlur(s(5)))
    layer.paste((0, 0, 0, 140), (s(3), s(6)), shadow)
    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, mask, (s(cy - height / 2), s(cy + height / 2 + thick)))
    layer = Image.alpha_composite(layer, gold)
    ImageDraw.Draw(layer).line(pts + [pts[0]], fill=INK + (255,), width=s(3.5), joint="curve")
    return layer


def faded(layer, opacity):
    r, g, b, a = layer.split()
    a = a.point(lambda v: int(v * opacity))
    return Image.merge("RGBA", (r, g, b, a))


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -40))
    canvas.alpha_composite(halo_layer())
    for cy, opacity in ((96, 0.45), (146, 0.75), (196, 1.0)):
        canvas.alpha_composite(faded(chevron(cy), opacity))
    d = ImageDraw.Draw(canvas)
    sparkle(d, 92, 96, 10, (255, 246, 210, 255))
    sparkle(d, 314, 70, 7, (255, 240, 190, 230))
    sparkle(d, 322, 222, 9, (255, 246, 210, 240))
    finish(canvas, "DOWNCAST", out, title_size=48, tracking=4)


if __name__ == "__main__":
    main(sys.argv[1])
