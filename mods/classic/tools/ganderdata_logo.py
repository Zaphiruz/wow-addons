"""Draws the GanderData logo: Gander's goose and magnifying glass, over an open book of notes.

Usage: python ganderdata_logo.py out.png   (needs Pillow)
"""
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, GOLD_LIGHT, GOLD_DARK, background, sparkle, finish
import gander_logo

BG_CENTER = (58, 84, 122)
BG_EDGE = (10, 18, 36)
PAGE = (246, 238, 214)
PAGE_SHADE = (214, 200, 166)
RULE = (150, 128, 92)


def book():
    """An open book at the bottom left, with ruled lines for its entries."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ink = INK + (255,)
    spine = (112, 262)
    left = [(26, 214), (112, 226), spine, (26, 250)]
    right = [(112, 226), (198, 214), (198, 250), spine]
    cover = [(20, 220), (112, 234), (204, 220), (204, 258), (112, 272), (20, 258)]
    shadow = Image.new("L", (W, W), 0)
    ImageDraw.Draw(shadow).polygon([(s(x), s(y)) for x, y in cover], fill=255)
    layer.paste((0, 0, 0, 150), (s(3), s(7)), shadow.filter(ImageFilter.GaussianBlur(s(6))))
    d.polygon([(s(x), s(y)) for x, y in cover], fill=GOLD_DARK + (255,), outline=ink)
    d.line([(s(x), s(y)) for x, y in cover + cover[:1]], fill=ink, width=s(3))
    for page, tone in ((left, PAGE), (right, PAGE_SHADE)):
        d.polygon([(s(x), s(y)) for x, y in page], fill=tone + (255,))
        d.line([(s(x), s(y)) for x, y in page + page[:1]], fill=ink, width=s(3))
    for i in range(3):  # ruled lines, following the slope of each page
        y = 226 + i * 8
        d.line([(s(36), s(y)), (s(102), s(y + 9))], fill=RULE + (255,), width=s(2))
        d.line([(s(122), s(y + 9)), (s(188), s(y))], fill=RULE + (255,), width=s(2))
    return layer


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -30))
    canvas.alpha_composite(gander_logo.glass())
    canvas.alpha_composite(gander_logo.goose())
    canvas.alpha_composite(gander_logo.shine())
    canvas.alpha_composite(gander_logo.frame())
    canvas.alpha_composite(book())
    d = ImageDraw.Draw(canvas)
    sparkle(d, 72, 70, 9, GOLD_LIGHT + (255,))
    sparkle(d, 330, 74, 7, (255, 246, 210, 235))
    finish(canvas, "GANDERDATA", out, title_size=40, tracking=3)


if __name__ == "__main__":
    main(sys.argv[1])
