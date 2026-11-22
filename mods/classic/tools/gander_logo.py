"""Draws the Gander logo: a goose taking a good look through a gold magnifying glass.

Usage: python gander_logo.py out.png   (needs Pillow)
"""
import sys
from PIL import Image, ImageDraw, ImageFilter

from badge import W, s, INK, GOLD_LIGHT, gold_fill, background, sparkle, finish

BG_CENTER = (44, 110, 104)
BG_EDGE = (8, 30, 34)
GLASS_TOP = (196, 232, 236)
GLASS_BOTTOM = (120, 178, 190)
FEATHER = (250, 248, 240)
FEATHER_SHADE = (212, 208, 196)
BEAK = (240, 150, 50)
BEAK_SHADE = (196, 108, 30)

CX, CY, R = 186, 150, 84  # the lens


def lens_mask(radius):
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).ellipse([s(CX - radius), s(CY - radius), s(CX + radius), s(CY + radius)], fill=255)
    return mask


def glass():
    """The pale glass of the lens, lighter at the top."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    fill = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(fill)
    top, bottom = s(CY - R), s(CY + R)
    for y in range(top, bottom):
        t = (y - top) / (bottom - top)
        color = tuple(int(a + (b - a) * t) for a, b in zip(GLASS_TOP, GLASS_BOTTOM))
        d.line([(0, y), (W, y)], fill=color + (255,))
    layer.paste(fill, (0, 0), lens_mask(R))
    return layer


def goose():
    """A white goose's head and neck, looking right, seen through the lens."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ink = INK + (255,)
    # Neck: a curve of overlapping circles from below the lens up to the head.
    points = [(150, 250, 30), (152, 228, 28), (157, 206, 26), (164, 186, 25), (172, 168, 24), (180, 152, 24)]
    neck = []
    for (x0, y0, r0), (x1, y1, r1) in zip(points, points[1:]):
        for i in range(8):
            t = i / 8
            neck.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, r0 + (r1 - r0) * t))
    neck.append(points[-1])
    for x, y, r in neck:
        d.ellipse([s(x - r - 3), s(y - r - 3), s(x + r + 3), s(y + r + 3)], fill=ink)
    # Beak, behind the head.
    beak = [(212, 124), (262, 140), (214, 154)]
    d.polygon([(s(x), s(y)) for x, y in beak], fill=BEAK + (255,), outline=ink)
    d.line([(s(212), s(124)), (s(262), s(140)), (s(214), s(154)), (s(212), s(124))], fill=ink, width=s(3))
    d.line([(s(216), s(140)), (s(258), s(140))], fill=BEAK_SHADE + (255,), width=s(2.5))
    # Head outline, then the white of neck and head over the outlines.
    d.ellipse([s(158), s(104), s(226), s(166)], fill=ink)
    for x, y, r in neck:
        d.ellipse([s(x - r), s(y - r), s(x + r), s(y + r)], fill=FEATHER + (255,))
    d.ellipse([s(161), s(107), s(223), s(163)], fill=FEATHER + (255,))
    # Shading down the back of the neck.
    for x, y, r in neck:
        d.ellipse([s(x - r), s(y - r * 0.6), s(x - r * 0.45), s(y + r * 0.6)], fill=FEATHER_SHADE + (255,))
    # Eye, with a glint: wide open, taking a good look.
    d.ellipse([s(196), s(122), s(212), s(138)], fill=ink)
    d.ellipse([s(200), s(124), s(206), s(130)], fill=(255, 255, 255, 255))
    clipped = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    clipped.paste(layer, (0, 0), lens_mask(R - 2))
    return clipped


def frame():
    """The gold rim and handle of the magnifying glass."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    mask = Image.new("L", (W, W), 0)
    dm = ImageDraw.Draw(mask)
    dm.ellipse([s(CX - R - 12), s(CY - R - 12), s(CX + R + 12), s(CY + R + 12)], fill=255)
    dm.ellipse([s(CX - R), s(CY - R), s(CX + R), s(CY + R)], fill=0)
    # Handle towards the lower right.
    handle = Image.new("L", (W, W), 0)
    dh = ImageDraw.Draw(handle)
    dh.rounded_rectangle([s(CX + R + 2), s(CY - 13), s(CX + R + 96), s(CY + 13)], radius=s(11), fill=255)
    handle = handle.rotate(-42, resample=Image.BICUBIC, center=(s(CX), s(CY)))
    outline = Image.new("L", (W, W), 0)
    outline.paste(255, (0, 0), mask)
    outline.paste(255, (0, 0), handle)

    shadow = outline.filter(ImageFilter.GaussianBlur(s(6)))
    layer.paste((0, 0, 0, 150), (s(3), s(7)), shadow)
    edge = outline.filter(ImageFilter.MaxFilter(2 * s(3) + 1))
    hole = lens_mask(R - 3)
    edge.paste(0, (0, 0), hole)
    layer.paste(INK + (255,), (0, 0), edge)
    gold = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    gold_fill(gold, outline, (s(CY - R - 12), s(CY + R + 60)))
    return Image.alpha_composite(layer, gold)


def shine():
    """A soft highlight across the top left of the glass."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.arc([s(CX - R + 12), s(CY - R + 12), s(CX + R - 12), s(CY + R - 12)], 196, 262, fill=(255, 255, 255, 190), width=s(7))
    return layer.filter(ImageFilter.GaussianBlur(s(1.5)))


def main(out):
    canvas = background(BG_CENTER, BG_EDGE, shift=(0, -30))
    canvas.alpha_composite(glass())
    canvas.alpha_composite(goose())
    canvas.alpha_composite(shine())
    canvas.alpha_composite(frame())
    d = ImageDraw.Draw(canvas)
    sparkle(d, 72, 70, 9, GOLD_LIGHT + (255,))
    sparkle(d, 330, 74, 7, (255, 246, 210, 235))
    sparkle(d, 66, 236, 6, (255, 246, 210, 225))
    finish(canvas, "GANDER", out, title_size=58, tracking=6)


if __name__ == "__main__":
    main(sys.argv[1])
