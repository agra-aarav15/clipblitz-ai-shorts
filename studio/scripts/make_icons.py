"""Generate the studio's PNG icons with nothing but the standard library.

Draws the brand mark (dark rounded square + white bolt, matching the inline SVG
`#i-mark`) by ray-casting the polygon at 4x supersampling, then encodes PNG chunks
by hand (zlib + struct). Outputs:
    web/icons/icon-512.png
    web/icons/icon-192.png
    web/icons/apple-touch-icon.png   (180x180, opaque — iOS home screen)
"""
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "icons")

BOLT = [(27.2, 9.5), (14.5, 27.4), (22.6, 27.4), (20.2, 38.5), (33.5, 20.6), (25.3, 20.6)]


def inside_rounded_square(x, y, size, radius_frac=0.27):
    r = size * radius_frac
    lo, hi = size * 0.035, size * 0.965          # the mark keeps a small margin
    if not (lo <= x <= hi and lo <= y <= hi):
        return False
    cx = min(max(x, lo + r), hi - r)
    cy = min(max(y, lo + r), hi - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r or (lo + r <= x <= hi - r or lo + r <= y <= hi - r)


def inside_bolt(x, y, size):
    """Ray casting against the scaled bolt polygon."""
    pts = [(px * size / 48.0, py * size / 48.0) for px, py in BOLT]
    n, inside = len(pts), False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def render(size):
    S = 4
    n = size * S
    rows = []
    for py in range(n):
        row = bytearray()
        row.append(0)                              # PNG filter: none
        y = (py + 0.5) / S
        for px in range(n):
            x = (px + 0.5) / S
            if inside_bolt(x, y, size):
                row += bytes((255, 255, 255, 255))
            elif inside_rounded_square(x, y, size):
                row += bytes((5, 5, 5, 255))       # the void itself
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))
    return b"".join(rows)


def png(width, height, raw):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, size, opaque in (("icon-512.png", 512, False),
                               ("icon-192.png", 192, False),
                               ("apple-touch-icon.png", 180, True)):
        raw = render(size)
        if opaque:                                  # iOS: no alpha — flatten onto the void
            flat = bytearray()
            for py in range(size):
                row = raw[py * (1 + size * 4):(py + 1) * (1 + size * 4)]
                flat.append(0)
                for px in range(size):
                    r, g, b, a = row[1 + px * 4:5 + px * 4]
                    if a == 0:
                        flat += bytes((5, 5, 5, 255))
                    else:
                        flat += bytes((r, g, b, 255))
            raw = bytes(flat)
        path = os.path.join(OUT, name)
        with open(path, "wb") as f:
            f.write(png(size, size, raw))
        print(f"{name}: {os.path.getsize(path)} bytes")


if __name__ == "__main__":
    main()
