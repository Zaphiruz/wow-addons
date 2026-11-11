"""Draws the Storied logo: a gold sword with a parchment scroll wound around its blade.

Usage: python storied_logo.py out.png   (needs Pillow)
"""
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, GOLD_DARK, gold_fill, background, sparkle, finish

BG_CENTER = (52, 70, 120)
BG_EDGE = (10, 12, 30)
PARCHMENT = (238, 224, 186)
PARCHMENT_SHADE = (196, 174, 128)
STEEL_LINE = (255, 246, 210)

CX = 200  # the sword's centre line


def sword_layer():
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    mask = Image.new("L", (W, W), 0)
    dm = ImageDraw.Draw(mask)
    blade = [(CX - 18, 196), (CX - 18, 70), (CX, 34), (CX + 18, 70), (CX + 18, 196)]
    guard = [CX - 66, 196, CX + 66, 214]
    grip = [CX - 10, 214, CX + 10, 258]
    pommel = [CX - 17, 254, CX + 17, 284]
    dm.polygon([(s(x), s(y)) for x, y in blade], fill=255)
    dm.rounded_rectangle([s(v) for v in guard], radius=s(8), fill=255)
    dm.rectangle([s(v) for v in grip], fill=255)
    dm.ellipse([s(v) for v in pommel], fill=255)

    shadow = mask.filter(ImageFilter.GaussianBlur(s(6)))
    layer.paste((0, 0, 0, 150), (s(3), s(7)), shadow)
    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, mask, (s(34), s(284)))
    layer = Image.alpha_composite(layer, gold)

    d = ImageDraw.Draw(layer)
    d.polygon([(s(x), s(y)) for x, y in blade], outline=INK + (255,), width=s(3))
    d.line([(s(CX), s(48)), (s(CX), s(192))], fill=STEEL_LINE + (200,), width=s(2.5))  # fuller
    d.rounded_rectangle([s(v) for v in guard], radius=s(8), outline=INK + (255,), width=s(3))
    d.rectangle([s(v) for v in grip], outline=INK + (255,), width=s(3))
    for y in range(220, 256, 8):  # wrapped grip
        d.line([(s(CX - 10), s(y)), (s(CX + 10), s(y + 5))], fill=GOLD_DARK + (230,), width=s(2))
    d.ellipse([s(v) for v in pommel], outline=INK + (255,), width=s(3))
    return layer


def scroll_layer():
    """A parchment band across the blade, curling off to each side."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    top, bottom = 112, 150
    # Rolled ends behind the band.
    for x0, x1 in ((88, 120), (280, 312)):
        d.rounded_rectangle([s(x0), s(top + 6), s(x1), s(bottom + 10)], radius=s(10),
                            fill=PARCHMENT_SHADE + (255,), outline=INK + (255,), width=s(2.5))
    # The band, tilted a little like a ribbon.
    band = [(104, top - 2), (296, top + 6), (296, bottom + 6), (104, bottom - 2)]
    d.polygon([(s(x), s(y)) for x, y in band], fill=PARCHMENT + (255,))
    d.polygon([(s(x), s(y)) for x, y in band], outline=INK + (255,), width=s(3))
    # Lines of writing.
    for i, (x0, x1) in enumerate([(122, 270), (122, 236), (122, 258)]):
        y = top + 10 + i * 10
        d.line([(s(x0), s(y + (x0 - 104) / 24)), (s(x1), s(y + (x1 - 104) / 24))],
               fill=(110, 82, 50, 255), width=s(2.5))
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 110), (s(2), s(5)), layer.split()[3].filter(ImageFilter.GaussianBlur(s(4))))
    return Image.alpha_composite(shadow, layer)


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -40))
    canvas.alpha_composite(sword_layer())
    canvas.alpha_composite(scroll_layer())
    d = ImageDraw.Draw(canvas)
    sparkle(d, 98, 70, 10, (255, 246, 210, 255))
    sparkle(d, 306, 84, 8, (255, 240, 190, 240))
    sparkle(d, 300, 236, 7, (255, 246, 210, 230))
    finish(canvas, "STORIED", out, title_size=56, tracking=5)


if __name__ == "__main__":
    main(sys.argv[1])
