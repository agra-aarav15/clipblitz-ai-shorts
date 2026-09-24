"""Mean-luminance probe for the V3 headless capture.

Healthy ClipBlitz captures sit in the 26-30 band (bright monochrome glass on a
#050505 void). The historic stuck-dim regression measured ~13, because half the
page was frozen at opacity:0. Anything below ~22 means something is invisible.

Usage: python scripts/lum.py _shots/studio_1440.png
"""
import sys

from PIL import Image


def main(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()

    total = 0
    bright = 0            # pixels clearly above the void floor
    dead_rows = 0         # rows that are pure void top-to-bottom (a blank band)
    for y in range(h):
        row_sum = 0
        for x in range(w):
            r, g, b = px[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            row_sum += lum
            total += lum
            if lum > 40:
                bright += 1
        if row_sum // w < 8:
            dead_rows += 1

    n = w * h
    mean = total / n
    print(f"file            {path}")
    print(f"size            {w}x{h}")
    print(f"mean luminance  {mean:.2f}   (healthy 26-30, historic dim ~13)")
    print(f"bright pixels   {bright} ({100.0 * bright / n:.2f}% of frame)")
    print(f"void rows       {dead_rows} of {h} ({100.0 * dead_rows / h:.1f}%)")
    if mean < 22:
        print("VERDICT         FAIL - page is too dim, something is stuck invisible")
        return 1
    if bright / n < 0.02:
        print("VERDICT         FAIL - almost nothing is lit")
        return 1
    print("VERDICT         PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "_shots/studio_1440.png"))
