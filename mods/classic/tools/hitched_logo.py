"""Draws the Hitched logo: two linked gold wedding rings under a heart.

Usage: python hitched_logo.py out.png   (needs Pillow)
"""
import math
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, gold_fill, background, sparkle, finish

BG_CENTER = (176, 62, 104)
BG_EDGE = (48, 10, 34)
HEART = (255, 128, 160)
HEART_LIGHT = (255, 214, 226)

CY = 176            # the rings' centre line
LEFT, RIGHT = 158, 242
R, THICK = 64, 17   # outer radius and band width


def ring(cx, shadowed=True):
    """One gold band with a dark outline and a soft shadow."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    outer = [s(cx - R), s(CY - R), s(cx + R), s(CY + R)]
    inner = [s(cx - R + THICK), s(CY - R + THICK), s(cx + R - THICK), s(CY + R - THICK)]
    mask = Image.new("L", (W, W), 0)
    dm = ImageDraw.Draw(mask)
    dm.ellipse(outer, fill=255)
    dm.ellipse(inner, fill=0)

    if shadowed:
        shadow = mask.filter(ImageFilter.GaussianBlur(s(6)))
        layer.paste((0, 0, 0, 150), (s(3), s(7)), shadow)
    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, mask, (s(CY - R), s(CY + R)))
    layer = Image.alpha_composite(layer, gold)

    d = ImageDraw.Draw(layer)
    d.ellipse(outer, outline=INK + (255,), width=s(3))
    d.ellipse(inner, outline=INK + (255,), width=s(3))
    # A highlight along the top of the band.
    d.arc([s(cx - R + 7), s(CY - R + 7), s(cx + R - 7), s(CY + R - 7)], 200, 300, fill=(255, 250, 220, 220), width=s(3))
    return layer


def rings():
    """The right ring lies over the left one at the top and under it at the bottom, so they link."""
    left, right = ring(LEFT), ring(RIGHT)
    layer = Image.alpha_composite(left, right)
    box = (s(170), s(CY + 8), s(232), s(CY + R + 14))  # around the lower crossing
    patch = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    patch.paste(ring(LEFT, shadowed=False).crop(box), box[:2])  # the band alone, without its shadow
    return Image.alpha_composite(layer, patch)


def heart(cx, cy, size):
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    pts = []
    for i in range(120):
        t = i / 120 * 2 * math.pi
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((s(cx + x * size), s(cy - y * size)))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    shadow = mask.filter(ImageFilter.GaussianBlur(s(5)))
    layer.paste((0, 0, 0, 140), (s(2), s(5)), shadow)
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=HEART + (255,))
    d.line(pts + pts[:1], fill=INK + (255,), width=s(3), joint="curve")
    d.ellipse([s(cx - 13 * size), s(cy - 11 * size), s(cx - 6 * size), s(cy - 5 * size)], fill=HEART_LIGHT + (230,))
    return layer


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -30))
    canvas.alpha_composite(rings())
    canvas.alpha_composite(heart(200, 72, 1.5))
    d = ImageDraw.Draw(canvas)
    sparkle(d, 86, 96, 9, (255, 246, 210, 255))
    sparkle(d, 318, 84, 8, (255, 240, 190, 240))
    sparkle(d, 332, 226, 6, (255, 246, 210, 230))
    sparkle(d, 70, 232, 6, (255, 240, 190, 230))
    finish(canvas, "HITCHED", out, title_size=56, tracking=5)


if __name__ == "__main__":
    main(sys.argv[1])
