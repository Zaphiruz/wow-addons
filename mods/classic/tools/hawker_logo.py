"""Draws the Hawker logo: a gold megaphone calling out on a dark arcane badge.

Usage: python hawker_logo.py out.png   (needs Pillow)
"""
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import (W, s, INK, GOLD_LIGHT, GOLD_MID, gold_fill, background, sparkle, finish)

BG_CENTER = (74, 50, 120)
BG_EDGE = (14, 9, 30)


def megaphone_layer():
    """Megaphone drawn horizontally around the layer centre, then tilted."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    cx, cy = W // 2, W // 2

    def P(x, y):
        return (cx + s(x), cy + s(y))

    shape = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(shape)
    cone = [P(-62, -17), P(52, -58), P(52, 58), P(-62, 17)]
    d.polygon(cone, fill=255)
    d.rounded_rectangle([P(-88, -12), P(-58, 12)], radius=s(5), fill=255)       # mouthpiece
    d.polygon([P(-30, 10), P(-38, 56), P(-18, 60), P(-8, 8)], fill=255)          # handle
    d.ellipse([P(40, -58), P(66, 58)], fill=255)                                  # bell rim

    shadow = shape.filter(ImageFilter.GaussianBlur(s(6)))
    shadow_img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    shadow_img.paste((0, 0, 0, 150), (s(5), s(8)), shadow)
    layer = Image.alpha_composite(layer, shadow_img)

    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, shape, (cy - s(60), cy + s(60)))
    layer = Image.alpha_composite(layer, gold)

    d = ImageDraw.Draw(layer)
    ink = INK + (255,)
    lw = s(3.5)
    d.line(cone + [cone[0]], fill=ink, width=lw, joint="curve")
    d.rounded_rectangle([P(-88, -12), P(-58, 12)], radius=s(5), outline=ink, width=lw)
    d.line([P(-30, 10), P(-38, 56), P(-18, 60), P(-8, 8)], fill=ink, width=lw, joint="curve")
    for x, h in ((-30, 29), (8, 43)):                                             # bands
        d.line([P(x, -h), P(x, h)], fill=ink, width=s(3))
    d.ellipse([P(40, -58), P(66, 58)], fill=GOLD_MID + (255,), outline=ink, width=lw)
    d.ellipse([P(46, -48), P(62, 48)], fill=(30, 16, 40, 255), outline=ink, width=s(2))
    d.line([P(-52, -11), P(40, -45)], fill=(255, 248, 210, 200), width=s(3))     # highlight

    for i, r in enumerate((92, 116, 140)):                                        # sound waves
        alpha = 255 - i * 55
        box = [P(-r, -r), P(r, r)]
        d.arc(box, start=-34, end=34, fill=INK + (alpha,), width=s(12 - i * 2))
        d.arc(box, start=-32, end=32, fill=GOLD_LIGHT + (alpha,), width=s(7 - i * 1.5))
    return layer.rotate(14, resample=Image.BICUBIC, center=(cx, cy))


def main(out):
    canvas = background(BG_CENTER, BG_EDGE)
    canvas.alpha_composite(megaphone_layer(), (-s(26), -s(40)))
    d = ImageDraw.Draw(canvas)
    sparkle(d, 72, 92, 11, (255, 246, 200, 255))
    sparkle(d, 102, 60, 6, (255, 236, 160, 220))
    sparkle(d, 336, 252, 8, (255, 236, 160, 220))
    finish(canvas, "HAWKER", out)


if __name__ == "__main__":
    main(sys.argv[1])
