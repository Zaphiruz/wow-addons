"""Draws the Huzzah logo: a raised gold tankard in a burst of light and confetti.

Usage: python huzzah_logo.py out.png   (needs Pillow)
"""
import math
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, GOLD_LIGHT, GOLD_DARK, gold_fill, background, sparkle, finish

BG_CENTER = (150, 40, 44)
BG_EDGE = (36, 6, 10)
FOAM = (250, 246, 232)
FOAM_SHADE = (214, 204, 182)
CONFETTI = [(255, 214, 90), (120, 200, 240), (240, 120, 150), (140, 220, 120), (255, 246, 210)]

CX, CY = 200, 152  # centre of the burst and the tankard


def burst():
    """Soft gold rays behind the tankard."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rays = 16
    for i in range(rays):
        a0 = (i / rays) * 2 * math.pi
        a1 = a0 + math.pi / rays * 0.9
        r = 150
        pts = [(CX, CY), (CX + r * math.cos(a0), CY + r * math.sin(a0)), (CX + r * math.cos(a1), CY + r * math.sin(a1))]
        d.polygon([(s(x), s(y)) for x, y in pts], fill=GOLD_LIGHT + (46,))
    return layer.filter(ImageFilter.GaussianBlur(s(2)))


def tankard():
    """A gold tankard tilted as if raised in a toast, with foam spilling over."""
    size = 400 * 4
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    dm = ImageDraw.Draw(mask)
    # Body and handle, drawn upright around the centre, then rotated.
    body = [s(150), s(110), s(240), s(230)]
    dm.rounded_rectangle(body, radius=s(14), fill=255)
    handle_outer = [s(220), s(130), s(282), s(206)]
    handle_inner = [s(232), s(146), s(266), s(190)]
    handle = Image.new("L", (size, size), 0)
    dh = ImageDraw.Draw(handle)
    dh.rounded_rectangle(handle_outer, radius=s(22), fill=255)
    dh.rounded_rectangle(handle_inner, radius=s(14), fill=0)
    mask = Image.composite(Image.new("L", (size, size), 255), mask, handle)

    shadow = mask.filter(ImageFilter.GaussianBlur(s(6)))
    layer.paste((0, 0, 0, 140), (s(3), s(7)), shadow)
    gold = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gold_fill(gold, mask, (s(110), s(230)))
    layer = Image.alpha_composite(layer, gold)

    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(body, radius=s(14), outline=INK + (255,), width=s(3))
    d.rounded_rectangle(handle_outer, radius=s(22), outline=INK + (255,), width=s(3))
    d.rounded_rectangle(handle_inner, radius=s(14), outline=INK + (255,), width=s(3))
    # Bands and staves.
    for y in (132, 208):
        d.line([(s(152), s(y)), (s(238), s(y))], fill=INK + (255,), width=s(3))
        d.line([(s(152), s(y + 4)), (s(238), s(y + 4))], fill=GOLD_DARK + (200,), width=s(2))
    for x in (172, 195, 218):
        d.line([(s(x), s(138)), (s(x), s(204))], fill=GOLD_DARK + (170,), width=s(2))
    # Foam: a row of bubbles over the rim, one drip down the side.
    for i, (x, y, r) in enumerate([(152, 108, 14), (172, 100, 17), (195, 98, 18), (218, 101, 16), (238, 108, 13)]):
        d.ellipse([s(x - r), s(y - r), s(x + r), s(y + r)], fill=FOAM + (255,), outline=INK + (255,), width=s(2.5))
    d.rounded_rectangle([s(146), s(104), s(160), s(150)], radius=s(7), fill=FOAM + (255,), outline=INK + (255,), width=s(2.5))
    for x, y, r in [(178, 104, 5), (205, 102, 4), (226, 106, 4)]:
        d.ellipse([s(x - r), s(y - r), s(x + r), s(y + r)], fill=FOAM_SHADE + (255,))
    return layer.rotate(-14, resample=Image.BICUBIC, center=(s(205), s(170)))


def confetti():
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    bits = [(88, 76, 20), (120, 52, -30), (300, 60, 35), (322, 120, -15), (72, 168, 50), (330, 196, 10),
            (104, 232, -40), (290, 244, 25), (150, 40, 60), (258, 36, -20), (60, 120, 5), (344, 156, -45)]
    for i, (x, y, angle) in enumerate(bits):
        color = CONFETTI[i % len(CONFETTI)]
        piece = Image.new("RGBA", (s(24), s(24)), (0, 0, 0, 0))
        ImageDraw.Draw(piece).rectangle([s(4), s(8), s(20), s(15)], fill=color + (255,), outline=INK + (255,), width=s(1.5))
        piece = piece.rotate(angle, resample=Image.BICUBIC, expand=False)
        layer.alpha_composite(piece, (s(x - 12), s(y - 12)))
    return layer


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -30))
    canvas.alpha_composite(burst())
    canvas.alpha_composite(confetti())
    canvas.alpha_composite(tankard())
    d = ImageDraw.Draw(canvas)
    sparkle(d, 92, 112, 9, (255, 246, 210, 255))
    sparkle(d, 314, 88, 8, (255, 240, 190, 240))
    sparkle(d, 300, 222, 6, (255, 246, 210, 230))
    finish(canvas, "HUZZAH", out, title_size=58, tracking=6)


if __name__ == "__main__":
    main(sys.argv[1])
