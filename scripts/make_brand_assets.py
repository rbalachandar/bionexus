#!/usr/bin/env python3
"""Derive the BioNexus logo asset family from the canonical banner.

Single source of truth: assets/logo/bionexus-banner.png (dark card,
matrix-grid icon, "bionexus." wordmark). Everything else is generated:

  bionexus-mark.png           icon only, transparent (light surfaces)
  bionexus-mark-tile.png      icon on its navy tile (as in the banner)
  bionexus-wordmark.png       title only, ink recolor (light surfaces)
  bionexus-wordmark-onDark.png title only, original white/coral
  bionexus-lockup.png         icon + title, light-surface recolor
  bionexus-lockup-onDark.png  icon + title, original colors
  favicon.png                 icon centered on a navy rounded square

Usage: python scripts/make_brand_assets.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "assets" / "logo"
BANNER = LOGO / "bionexus-banner.png"

NAVY = (0x0d, 0x11, 0x17)
CARD = (0x19, 0x1e, 0x26)
INK = (0x2a, 0x28, 0x23)


def diff(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def is_text(p):
    r, g, b = p[:3]
    return (r > 140 and g > 140 and b > 140) or (r > 150 and r - b > 60)


def cut_alpha(region, bg=CARD, tol=28):
    """Region crop -> RGBA with the card background removed."""
    out = Image.new("RGBA", region.size)
    for y in range(region.size[1]):
        for x in range(region.size[0]):
            p = region.getpixel((x, y))
            out.putpixel((x, y), (*p[:3], 0 if diff(p[:3], bg) < tol else 255))
    return out


def recolor_ink(rgba):
    """White pixels -> ink; coral and everything else unchanged."""
    out = rgba.copy()
    px = out.load()
    for y in range(out.size[1]):
        for x in range(out.size[0]):
            r, g, b, a = px[x, y]
            if a and r > 140 and g > 140 and b > 140:
                px[x, y] = (*INK, a)
    return out


def main():
    im = Image.open(BANNER).convert("RGB")
    w, h = im.size
    bg = im.getpixel((540, 60))

    # --- locate icon and title blocks by strong-pixel bounding boxes
    def bbox(x_range, pred):
        xs, ys = [], []
        for x in x_range:
            for y in range(10, h - 10, 2):
                if pred(im.getpixel((x, y))):
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys))

    is_white = lambda p: p[0] > 140 and p[1] > 140 and p[2] > 140
    strong = lambda p: diff(p, bg) > 55 and not is_white(p)

    def solid_bbox(x_range, min_votes=3):
        # column/row votes: ignore isolated specks (dot grid, AA fringes)
        cols, rows = {}, {}
        for x in x_range:
            for y in range(10, h - 10):
                if strong(im.getpixel((x, y))):
                    cols[x] = cols.get(x, 0) + 1
                    rows[y] = rows.get(y, 0) + 1
        cx = [x for x, n in cols.items() if n >= min_votes]
        cy = [y for y, n in rows.items() if n >= min_votes]
        return (min(cx), min(cy), max(cx), max(cy))

    ibox = solid_bbox(range(20, 430))
    tbox = solid_bbox(range(ibox[2] + 30, w - 20), min_votes=2)

    # the icon sits on its own darker panel — use the LOCAL background
    icon_bg = im.getpixel((max(ibox[0] - 6, 0), max(ibox[1] - 6, 0)))
    pad = 8
    icon = cut_alpha(im.crop((ibox[0] - pad, ibox[1] - pad,
                              ibox[2] + pad, ibox[3] + pad)),
                     bg=icon_bg, tol=20)

    # title = first contiguous text band; subtitle sits after a big gap
    rows = sorted({y for x in range(tbox[0], tbox[2], 2)
                   for y in range(10, h - 10, 2) if is_text(im.getpixel((x, y)))})
    t_end = rows[-1]
    for a, b in zip(rows, rows[1:]):
        if b - a > 15:                 # first real break = title/subtitle
            t_end = a
            break
    word_box = (tbox[0] - 2, tbox[1] - 4, tbox[2] + 6, t_end + 6)
    # keep only real text pixels (kills the dot-grid noise)
    word = Image.new("RGBA", (word_box[2] - word_box[0],
                              word_box[3] - word_box[1]))
    for y in range(word.size[1]):
        for x in range(word.size[0]):
            p = im.getpixel((word_box[0] + x, word_box[1] + y))
            if is_text(p):
                word.putpixel((x, y), (*p, 255))

    # --- write the family.
    # NOTE: bionexus-mark.png and bionexus-wordmark.png are hand-cropped
    # from the banner (operator-provided, keep the white path on the navy
    # panel) — this script never overwrites them; it only generates the
    # derived variants below.
    word.save(LOGO / "bionexus-wordmark-onDark.png")

    def lockup(light):
        gap = 36
        wl = recolor_ink(word) if light else word
        canvas = Image.new("RGBA", (icon.size[0] + gap + wl.size[0],
                                    max(icon.size[1], wl.size[1])))
        ico = recolor_ink(icon) if light else icon
        canvas.alpha_composite(ico, (0, (canvas.size[1] - icon.size[1]) // 2))
        canvas.alpha_composite(wl, (icon.size[0] + gap,
                                    (canvas.size[1] - wl.size[1]) // 2))
        return canvas

    lockup(light=True).save(LOGO / "bionexus-lockup.png")
    lockup(light=False).save(LOGO / "bionexus-lockup-onDark.png")

    # tile: icon centered on its navy card (as it appears in the banner)
    tile = Image.new("RGBA", (icon.size[0] + 28, icon.size[1] + 28), (*CARD, 255))
    tile.alpha_composite(icon, (14, 14))
    tile.save(LOGO / "bionexus-mark-tile.png")

    # favicon: icon on a navy rounded square
    side = max(icon.size) + 28
    fav = Image.new("RGBA", (side, side), (*NAVY, 255))
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1),
                                           radius=side // 5, fill=255)
    fav.putalpha(mask)
    fav.alpha_composite(icon, ((side - icon.size[0]) // 2,
                               (side - icon.size[1]) // 2))
    fav.resize((64, 64), Image.LANCZOS).save(LOGO / "favicon.png")

    print("generated:", ", ".join(sorted(p.name for p in LOGO.glob("*.png"))))


if __name__ == "__main__":
    main()
