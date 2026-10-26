"""Shared drawing for addon logos: a rounded gold-bordered badge with a gold wordmark.

Everything is drawn at 4x (S) on a W x W canvas and scaled to SIZE when saved.
Coordinates passed to these helpers are in final 400px units.
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageChops

SIZE = 400
S = 4
W = SIZE * S
FONT = r"C:\Windows\Fonts\palab.ttf"

GOLD_LIGHT = (255, 236, 160)
GOLD_MID = (226, 178, 74)
GOLD_DARK = (150, 100, 30)
INK = (40, 22, 8)
GOLD_STOPS = [(0, GOLD_LIGHT), (0.45, GOLD_MID), (1, GOLD_DARK)]


def s(v):
    return int(round(v * S))


def vertical_gradient(w, h, stops):
    """stops: list of (position 0..1, rgb)."""
    img = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                k = (t - p0) / (p1 - p0) if p1 > p0 else 0
                img.putpixel((0, y), tuple(int(a + (b - a) * k) for a, b in zip(c0, c1)))
                break
    return img.resize((w, h), Image.BICUBIC)


def gold_fill(canvas, mask, box=None):
    """Paste a gold gradient through mask; the gradient spans box (top, bottom) in canvas px."""
    top, bottom = box or (0, canvas.height)
    grad = vertical_gradient(canvas.width, max(1, bottom - top), GOLD_STOPS)
    full = Image.new("RGB", canvas.size, GOLD_DARK)
    full.paste(GOLD_LIGHT, (0, 0, canvas.width, max(0, top)))
    full.paste(grad, (0, top))
    canvas.paste(full, (0, 0), mask)


def background(center, edge, shift=(-10, -25)):
    grad = Image.radial_gradient("L").resize((W, W), Image.BICUBIC)
    grad = ImageChops.offset(grad, s(shift[0]), s(shift[1]))
    return ImageOps.colorize(grad, black=center, white=edge).convert("RGBA")


def sparkle(d, x, y, r, color):
    pts = [(x, y - r), (x + r * 0.22, y - r * 0.22), (x + r, y), (x + r * 0.22, y + r * 0.22),
           (x, y + r), (x - r * 0.22, y + r * 0.22), (x - r, y), (x - r * 0.22, y - r * 0.22)]
    d.polygon([(s(px), s(py)) for px, py in pts], fill=color)


def wordmark(canvas, text, y_center, size, tracking):
    """Gold letters with a dark outline and soft shadow, centred horizontally. canvas is RGB."""
    font = ImageFont.truetype(FONT, s(size))
    widths = [font.getbbox(ch)[2] - font.getbbox(ch)[0] for ch in text]
    total = sum(widths) + s(tracking) * (len(text) - 1)
    x = (W - total) // 2
    top = font.getbbox("H")[1]
    height = font.getbbox("H")[3] - top
    y = s(y_center) - top - height // 2

    mask = Image.new("L", (W, W), 0)
    stroke = Image.new("L", (W, W), 0)
    dm, ds = ImageDraw.Draw(mask), ImageDraw.Draw(stroke)
    cx = x
    for ch, w in zip(text, widths):
        off = font.getbbox(ch)[0]
        dm.text((cx - off, y), ch, font=font, fill=255)
        ds.text((cx - off, y), ch, font=font, fill=255, stroke_width=s(3))
        cx += w + s(tracking)

    shadow = stroke.filter(ImageFilter.GaussianBlur(s(4)))
    canvas.paste((0, 0, 0), (s(2), s(4)), shadow)
    canvas.paste(INK, (0, 0), stroke)
    gold_fill(canvas, mask, (y + top, y + top + height))


def border(canvas):
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([s(10), s(10), W - s(10), W - s(10)], radius=s(44), outline=INK + (255,), width=s(9))
    d.rounded_rectangle([s(12), s(12), W - s(12), W - s(12)], radius=s(42), outline=GOLD_MID + (255,), width=s(5))
    d.rounded_rectangle([s(19), s(19), W - s(19), W - s(19)], radius=s(36), outline=GOLD_DARK + (180,), width=s(1.5))


def finish(canvas, title, out, title_y=322, title_size=60, tracking=6):
    """Add the wordmark and border, round the corners, scale down and save."""
    rgb = canvas.convert("RGB")
    wordmark(rgb, title, title_y, title_size, tracking)
    canvas = rgb.convert("RGBA")
    border(canvas)
    corners = Image.new("L", (W, W), 0)
    ImageDraw.Draw(corners).rounded_rectangle([s(6), s(6), W - s(6), W - s(6)], radius=s(48), fill=255)
    canvas.putalpha(corners)
    canvas.resize((SIZE, SIZE), Image.LANCZOS).save(out, optimize=True)
    print("wrote", out)
