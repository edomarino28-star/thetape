"""Generate the app icon.

The mark is the product's own thesis: three stacked delay bars, short-green to
long-red, on a dark ledger ground. It carries meaning at 256px and still reads
as a distinct silhouette at 16px, which a literal chart or dollar sign does not.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

GROUND = (13, 20, 24, 255)      # --ink, the dark ledger plane
RULE = (61, 74, 84, 255)
BARS = [
    ((12, 163, 12, 255), 0.22),   # fresh   - insiders, 2 days
    ((235, 160, 0, 255), 0.58),   # warning - congress, 45 days
    ((208, 59, 59, 255), 0.94),   # stale   - funds, 135 days
]


def draw(size):
    """Render one square frame at `size` px."""
    s = size * 4                                  # supersample, then downscale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=GROUND)

    pad = s * 0.17
    usable = s - pad * 2
    bar_h = usable * 0.185
    gap = (usable - bar_h * 3) / 2
    radius = max(1, int(bar_h * 0.34))

    for i, (color, frac) in enumerate(BARS):
        y0 = pad + i * (bar_h + gap)
        y1 = y0 + bar_h
        # recessive track, so a short bar still reads as "short of something"
        d.rounded_rectangle([pad, y0, pad + usable, y1], radius=radius, fill=RULE)
        w = max(bar_h, usable * frac)
        d.rounded_rectangle([pad, y0, pad + w, y1], radius=radius, fill=color)

    return img.resize((size, size), Image.LANCZOS)


def build(path=None):
    path = path or os.path.join(HERE, "paper-trail.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw(n) for n in sizes]
    frames[-1].save(path, format="ICO",
                    sizes=[(n, n) for n in sizes], append_images=frames[:-1])
    return path


if __name__ == "__main__":
    print(build())
