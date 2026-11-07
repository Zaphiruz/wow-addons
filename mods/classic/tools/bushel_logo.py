"""Draws the Bushel logo: a gold woven basket holding herbs and a lump of ore.

Usage: python bushel_logo.py out.png   (needs Pillow)
"""
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, GOLD_DARK, gold_fill, background, sparkle, finish

BG_CENTER = (120, 84, 38)
BG_EDGE = (28, 16, 6)

# The basket, in final 400px units.
RIM_Y, BASE_Y = 160, 272
TOP_L, TOP_R = 104, 296
BOT_L, BOT_R = 132, 268
RIM_H = 26

LEAF_DARK = (46, 96, 40)
LEAF_LIGHT = (128, 190, 92)
ORE = [(90, 98, 112), (150, 160, 176), (206, 214, 226)]


def body_points():
    return [(TOP_L, RIM_Y), (TOP_R, RIM_Y), (BOT_R, BASE_Y - 10), (BOT_R - 14, BASE_Y),
            (BOT_L + 14, BASE_Y), (BOT_L, BASE_Y - 10)]


def basket_layer():
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).polygon([(s(x), s(y)) for x, y in body_points()], fill=255)

    shadow = mask.filter(ImageFilter.GaussianBlur(s(6)))
    layer.paste((0, 0, 0, 130), (s(3), s(7)), shadow)
    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, mask, (s(RIM_Y), s(BASE_Y)))
    layer = Image.alpha_composite(layer, gold)

    # Weave: horizontal bands and staggered stakes, clipped to the body.
    weave = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(weave)
    rows = 5
    for i in range(1, rows):
        y = RIM_Y + (BASE_Y - RIM_Y) * i / rows
        d.line([(s(80), s(y)), (s(320), s(y))], fill=INK + (230,), width=s(2.5))
    for i in range(rows):
        y0 = RIM_Y + (BASE_Y - RIM_Y) * i / rows
        y1 = RIM_Y + (BASE_Y - RIM_Y) * (i + 1) / rows
        t = (y0 + y1) / 2
        k = (t - RIM_Y) / (BASE_Y - RIM_Y)
        left = TOP_L + (BOT_L - TOP_L) * k
        right = TOP_R + (BOT_R - TOP_R) * k
        step = (right - left) / 8
        for j in range(9):
            x = left + step * (j + (0.5 if i % 2 else 0))
            d.line([(s(x), s(y0 + 3)), (s(x), s(y1 - 3))], fill=GOLD_DARK + (220,), width=s(2))
    clip = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    clip.paste(weave, (0, 0), mask)
    layer = Image.alpha_composite(layer, clip)

    d = ImageDraw.Draw(layer)
    d.polygon([(s(x), s(y)) for x, y in body_points()], outline=INK + (255,), width=s(3))
    return layer


def rim_layer():
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    mask = Image.new("L", (W, W), 0)
    box = [s(TOP_L - 10), s(RIM_Y - RIM_H / 2), s(TOP_R + 10), s(RIM_Y + RIM_H / 2)]
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=s(RIM_H / 2), fill=255)
    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, mask, (box[1], box[3]))
    layer = Image.alpha_composite(layer, gold)
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(box, radius=s(RIM_H / 2), outline=INK + (255,), width=s(3))
    for x in range(TOP_L + 6, TOP_R, 16):  # twisted rim
        d.line([(s(x), s(RIM_Y - RIM_H / 2 + 4)), (s(x + 8), s(RIM_Y + RIM_H / 2 - 4))],
               fill=GOLD_DARK + (230,), width=s(2))
    return layer


def leaf(d, base, tip, width):
    """A leaf from base to tip, bulging `width` to each side, with a midrib."""
    (bx, by), (tx, ty) = base, tip
    nx, ny = -(ty - by), (tx - bx)
    n = (nx * nx + ny * ny) ** 0.5
    nx, ny = nx / n * width, ny / n * width
    pts = []
    for i in range(13):
        t = i / 12
        w = 4 * t * (1 - t)
        pts.append((bx + (tx - bx) * t + nx * w, by + (ty - by) * t + ny * w))
    for i in range(12, -1, -1):
        t = i / 12
        w = 4 * t * (1 - t)
        pts.append((bx + (tx - bx) * t - nx * w, by + (ty - by) * t - ny * w))
    d.polygon([(s(x), s(y)) for x, y in pts], fill=LEAF_LIGHT + (255,), outline=INK + (255,), width=s(2.5))
    d.line([(s(bx), s(by)), (s(tx), s(ty))], fill=LEAF_DARK + (255,), width=s(2))


def contents_layer():
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Herb sprig on the left.
    d.line([(s(160), s(160)), (s(150), s(92))], fill=LEAF_DARK + (255,), width=s(4))
    leaf(d, (156, 150), (112, 104), 15)
    leaf(d, (154, 132), (136, 70), 13)
    leaf(d, (152, 124), (190, 80), 14)
    leaf(d, (158, 158), (204, 124), 13)
    # A faceted lump of ore on the right.
    out = [(214, 152), (222, 116), (250, 96), (284, 106), (294, 140), (276, 156)]
    d.polygon([(s(x), s(y)) for x, y in out], fill=ORE[1] + (255,))
    d.polygon([(s(x), s(y)) for x, y in [(222, 116), (250, 96), (284, 106), (252, 122)]], fill=ORE[2] + (255,))
    d.polygon([(s(x), s(y)) for x, y in [(252, 122), (284, 106), (294, 140), (276, 156), (246, 150)]], fill=ORE[0] + (255,))
    d.polygon([(s(x), s(y)) for x, y in out], outline=INK + (255,), width=s(3))
    d.line([(s(222), s(116)), (s(252), s(122)), (s(284), s(106))], fill=INK + (255,), width=s(2))
    d.line([(s(252), s(122)), (s(246), s(150))], fill=INK + (255,), width=s(2))
    # A glint of copper in the ore.
    d.ellipse([s(258), s(130), s(270), s(140)], fill=(232, 150, 80, 255), outline=INK + (255,), width=s(1.5))
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 110), (s(2), s(5)), layer.split()[3].filter(ImageFilter.GaussianBlur(s(4))))
    return Image.alpha_composite(shadow, layer)


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -30))
    canvas.alpha_composite(contents_layer())
    canvas.alpha_composite(basket_layer())
    canvas.alpha_composite(rim_layer())
    d = ImageDraw.Draw(canvas)
    sparkle(d, 314, 72, 10, (255, 246, 210, 255))
    sparkle(d, 84, 186, 7, (255, 240, 190, 230))
    sparkle(d, 322, 214, 8, (255, 246, 210, 240))
    finish(canvas, "BUSHEL", out, title_size=58, tracking=6)


if __name__ == "__main__":
    main(sys.argv[1])
