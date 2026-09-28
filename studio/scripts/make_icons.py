"""Generate every brand asset the studio ships, with nothing but the standard library.

One mark, every surface. The geometry is the same 48-unit space as the inline SVG
`#i-mark` in web/index.html: a rounded plate holding a bolt.

    web/icons/icon-512.png, icon-192.png     PWA install + browser
    web/icons/apple-touch-icon.png           iOS home screen (opaque, 180)
    assets/logo.png                          the mark alone, for the READMEs
    assets/ClipBlitzStudio.ico               Windows EXE + shortcut icon, 7 frames
    android/res/mipmap-*/ic_launcher.png     Android launcher, 48..192
    android/res/mipmap-*/ic_launcher_round.png
    android/res/drawable-*/ic_launcher_foreground.png   adaptive icon foreground
    android/res/mipmap-anydpi-v26/ic_launcher.xml       adaptive icon wiring
    android/res/values/ic_launcher_background.xml

The renderer box-downsamples a 4x supersampled raster, so edges are antialiased and the
image a decoder reads is exactly the image the header promises. PNG chunks and the ICO
container (BMP frames, 32bpp + AND mask) are written by hand.

    python scripts/make_icons.py            rewrite every asset
    python scripts/make_icons.py --check    decode what is on disk and diff it against a
                                            fresh render; exits 1 on any difference
"""

import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The mark, in the SVG's 48-unit space.
BOLT = [(27.2, 9.5), (14.5, 27.4), (22.6, 27.4), (20.2, 38.5), (33.5, 20.6), (25.3, 20.6)]
BOLT_BOX = (14.5, 9.5, 33.5, 38.5)
PLATE_LO, PLATE_HI, PLATE_R = 0.035, 0.965, 0.27

INK = (5, 5, 5, 255)
PAPER = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)

SUPERSAMPLE = 4        # 16 samples per pixel
FG_SCALE = 0.66        # adaptive foreground: the bolt inside the 72dp safe zone

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
MIPMAPS = (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192))
FOREGROUNDS = (("mdpi", 108), ("hdpi", 162), ("xhdpi", 216), ("xxhdpi", 288), ("xxxhdpi", 432))


# ----------------------------------------------------------------- geometry

def scaled_bolt(size, scale):
    """The bolt polygon, centred in a square canvas and optionally shrunk."""
    cx = (BOLT_BOX[0] + BOLT_BOX[2]) / 2.0
    cy = (BOLT_BOX[1] + BOLT_BOX[3]) / 2.0
    u = size / 48.0
    return [((x - cx) * scale * u + size / 2.0,
             (y - cy) * scale * u + size / 2.0) for x, y in BOLT]


def bolt_inside(x, y, pts):
    """Ray casting: odd crossings on the left means inside."""
    n, inside, j = len(pts), False, len(pts) - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def plate_inside(x, y, size):
    """The rounded plate: a rectangle with the four corners rounded off."""
    lo, hi = size * PLATE_LO, size * PLATE_HI
    if not (lo <= x <= hi and lo <= y <= hi):
        return False
    r = size * PLATE_R
    cx = min(max(x, lo + r), hi - r)
    cy = min(max(y, lo + r), hi - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def circle_inside(x, y, size):
    c = size / 2.0
    r = size / 2.0
    return (x - c) ** 2 + (y - c) ** 2 <= r * r


def sampler(kind, size, scale=1.0):
    """Return f(x, y) -> RGBA for one pixel-sized shape at sub-pixel coordinates."""
    bolt = scaled_bolt(size, scale if kind == "bolt" else 1.0)
    bx0, by0, bx1, by1 = (min(p[0] for p in bolt), min(p[1] for p in bolt),
                          max(p[0] for p in bolt), max(p[1] for p in bolt))

    if kind == "bolt":
        def bolt_only(x, y):
            if bx0 <= x <= bx1 and by0 <= y <= by1 and bolt_inside(x, y, bolt):
                return PAPER
            return CLEAR
        return bolt_only

    def mark(x, y):
        if bx0 <= x <= bx1 and by0 <= y <= by1 and bolt_inside(x, y, bolt):
            return PAPER
        if not plate_inside(x, y, size):
            return CLEAR
        if kind == "round" and not circle_inside(x, y, size):
            return CLEAR
        return INK

    return mark


# ----------------------------------------------------------------- raster

def render(size, kind="plate", scale=1.0, flatten=None):
    """Box-downsample the mark into `size` RGBA rows.

    `flatten` fills the transparent page with that colour instead of leaving alpha —
    iOS ignores alpha on home-screen icons, so it gets an opaque raster.
    """
    shape = sampler(kind, size, scale)
    area = SUPERSAMPLE * SUPERSAMPLE
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            ar = ag = ab = aa = 0
            y0, x0 = py * SUPERSAMPLE, px * SUPERSAMPLE
            for sy in range(y0, y0 + SUPERSAMPLE):
                y = (sy + 0.5) / SUPERSAMPLE
                for sx in range(x0, x0 + SUPERSAMPLE):
                    r, g, b, a = shape((sx + 0.5) / SUPERSAMPLE, y)
                    if a:
                        ar += r * a
                        ag += g * a
                        ab += b * a
                        aa += a
            if aa == 0:
                row += b"\x00\x00\x00\x00" if flatten is None else bytes(flatten)
                continue
            # every sample is opaque, so averaging is exact
            r_out, g_out, b_out = ar // aa, ag // aa, ab // aa
            a_out = (aa // 255 * 255 + area // 2) // area
            if flatten is not None:
                f = a_out / 255.0
                r_out = int(round(r_out * f + flatten[0] * (1 - f)))
                g_out = int(round(g_out * f + flatten[1] * (1 - f)))
                b_out = int(round(b_out * f + flatten[2] * (1 - f)))
                a_out = 255
            row += bytes((r_out, g_out, b_out, a_out))
        rows.append(bytes(row))
    return rows


# ----------------------------------------------------------------- encoders

def png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_bytes(size, rows):
    """8-bit RGBA, one IDAT, filter 0 on every scanline."""
    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(raw, 9))
            + png_chunk(b"IEND", b""))


def read_png_rgba(path):
    """Decode a PNG this script wrote: returns (size, [rows of RGBA bytes]).

    Deliberately strict — a file whose scanlines do not add up to the header is
    reported rather than half-read, which is what an oversized IDAT would hide.
    """
    blob = open(path, "rb").read()
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    off, idat = 8, b""
    width = height = ctype = None
    while off < len(blob):
        ln = struct.unpack(">I", blob[off:off + 4])[0]
        tag = blob[off + 4:off + 8]
        data = blob[off + 8:off + 8 + ln]
        if tag == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", data[:10])
            if (width, height, depth, ctype) != (width, height, 8, 6):
                raise ValueError("expected 8-bit RGBA, got depth=%s ctype=%s" % (depth, ctype))
        elif tag == b"IDAT":
            idat += data
        off += 12 + ln
    raw = zlib.decompress(idat)
    stride = 1 + width * 4
    if len(raw) != stride * height:
        raise ValueError("IDAT holds %d bytes, header implies %d" % (len(raw), stride * height))
    if any(raw[y * stride] != 0 for y in range(height)):
        raise ValueError("unsupported scanline filter")
    return width, [raw[y * stride + 1:(y + 1) * stride] for y in range(height)]


def bmp_frame(size, rows):
    """One ICO frame: a 32bpp bottom-up DIB plus the 1bpp AND mask Windows expects."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        row = rows[y]
        for x in range(size):
            r, g, b, a = row[x * 4:x * 4 + 4]
            xor += bytes((b, g, r, a))
    mask_stride = ((size + 31) // 32) * 4
    mask = bytearray()
    for y in range(size - 1, -1, -1):
        row = rows[y]
        bits = bytearray(mask_stride)
        for x in range(size):
            if row[x * 4 + 3] < 128:
                bits[x >> 3] |= 0x80 >> (x & 7)
        mask += bits
    return header + bytes(xor) + bytes(mask)


def ico_bytes(frames):
    out = struct.pack("<HHH", 0, 1, len(frames))
    entries, blob, offset = b"", b"", 6 + 16 * len(frames)
    for size, dib in frames:
        side = 0 if size >= 256 else size          # 256 is written as 0
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(dib), offset)
        blob += dib
        offset += len(dib)
    return out + entries + blob


def read_ico_frames(path):
    """Decode the frames of an ICO this script wrote: {size: [RGBA rows]}."""
    blob = open(path, "rb").read()
    reserved, kind, count = struct.unpack("<HHH", blob[:6])
    if (reserved, kind) != (0, 1):
        raise ValueError("not an icon container")
    frames = {}
    for i in range(count):
        w, h, _c, _r, _p, bpp, length, offset = struct.unpack(
            "<BBBBHHII", blob[6 + 16 * i:22 + 16 * i])
        size = w or 256
        dib = blob[offset:offset + length]
        if struct.unpack("<I", dib[:4])[0] != 40:
            raise ValueError("frame %d is not a BITMAPINFOHEADER" % size)
        xor = dib[40:40 + size * size * 4]
        if len(xor) != size * size * 4:
            raise ValueError("frame %d is short" % size)
        rows = []
        for y in range(size):                      # stored bottom-up
            src = (size - 1 - y) * size * 4
            row = bytearray()
            for x in range(size):
                b, g, r, a = xor[src + x * 4:src + x * 4 + 4]
                row += bytes((r, g, b, a))
            rows.append(bytes(row))
        frames[size] = rows
        if bpp != 32:
            raise ValueError("frame %d is %d bpp" % (size, bpp))
    return frames


# ----------------------------------------------------------------- outputs

ADAPTIVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
</adaptive-icon>
"""

BACKGROUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">#050505</color>
</resources>
"""


def plan():
    """Every asset we ship: (path relative to the studio, size, kind, scale, opaque)."""
    out = [
        ("web/icons/icon-512.png", 512, "plate", 1.0, None),
        ("web/icons/icon-192.png", 192, "plate", 1.0, None),
        ("web/icons/apple-touch-icon.png", 180, "plate", 1.0, (5, 5, 5, 255)),
        ("assets/logo.png", 512, "plate", 1.0, None),
    ]
    for density, size in MIPMAPS:
        out.append(("android/res/mipmap-%s/ic_launcher.png" % density, size, "plate", 1.0, None))
        out.append(("android/res/mipmap-%s/ic_launcher_round.png" % density, size, "round", 1.0, None))
    for density, size in FOREGROUNDS:
        out.append(("android/res/drawable-%s/ic_launcher_foreground.png" % density,
                    size, "bolt", FG_SCALE, None))
    return out


def expected(path, size, kind, scale, flatten):
    return render(size, kind, scale, flatten)


def write_all():
    made = 0
    for rel, size, kind, scale, flatten in plan():
        rows = expected(rel, size, kind, scale, flatten)
        path = os.path.join(ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(png_bytes(size, rows))
        print("  %-56s %4dpx  %7d bytes" % (rel, size, os.path.getsize(path)))
        made += 1

    ico = ico_bytes([(size, bmp_frame(size, render(size, "plate"))) for size in ICO_SIZES])
    ico_path = os.path.join(ROOT, "assets", "ClipBlitzStudio.ico")
    os.makedirs(os.path.dirname(ico_path), exist_ok=True)
    with open(ico_path, "wb") as f:
        f.write(ico)
    print("  %-56s %4s    %7d bytes (%d frames)"
          % ("assets/ClipBlitzStudio.ico", "ico", len(ico), len(ICO_SIZES)))
    made += 1

    for rel, body in (("android/res/mipmap-anydpi-v26/ic_launcher.xml", ADAPTIVE_XML),
                      ("android/res/mipmap-anydpi-v26/ic_launcher_round.xml", ADAPTIVE_XML),
                      ("android/res/values/ic_launcher_background.xml", BACKGROUND_XML)):
        path = os.path.join(ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print("  %-56s %4s    %7d bytes" % (rel, "xml", os.path.getsize(path)))
        made += 1
    return made


def check():
    """Diff the assets on disk against a fresh render. Any drift is a failure."""
    problems = []
    for rel, size, kind, scale, flatten in plan():
        path = os.path.join(ROOT, *rel.split("/"))
        want = expected(rel, size, kind, scale, flatten)
        if not os.path.exists(path):
            problems.append("%s is missing" % rel)
            continue
        try:
            got_size, got = read_png_rgba(path)
        except Exception as exc:
            problems.append("%s is unreadable: %s" % (rel, exc))
            continue
        if got_size != size:
            problems.append("%s is %dpx, expected %dpx" % (rel, got_size, size))
            continue
        if got != want:
            diff = sum(1 for y in range(size) for x in range(size)
                       if got[y][x * 4:x * 4 + 4] != want[y][x * 4:x * 4 + 4])
            problems.append("%s differs from a fresh render (%d of %d pixels)"
                            % (rel, diff, size * size))

    ico_path = os.path.join(ROOT, "assets", "ClipBlitzStudio.ico")
    if not os.path.exists(ico_path):
        problems.append("assets/ClipBlitzStudio.ico is missing")
    else:
        try:
            frames = read_ico_frames(ico_path)
        except Exception as exc:
            problems.append("assets/ClipBlitzStudio.ico is unreadable: %s" % exc)
            frames = {}
        for size in ICO_SIZES:
            if size not in frames:
                problems.append("assets/ClipBlitzStudio.ico has no %dpx frame" % size)
            elif frames[size] != render(size, "plate"):
                problems.append("assets/ClipBlitzStudio.ico %dpx frame differs" % size)

    for rel, want in (("android/res/mipmap-anydpi-v26/ic_launcher.xml", ADAPTIVE_XML),
                      ("android/res/mipmap-anydpi-v26/ic_launcher_round.xml", ADAPTIVE_XML),
                      ("android/res/values/ic_launcher_background.xml", BACKGROUND_XML)):
        path = os.path.join(ROOT, *rel.split("/"))
        if not os.path.exists(path):
            problems.append("%s is missing" % rel)
        elif open(path, encoding="utf-8").read().replace("\r\n", "\n") != want:
            problems.append("%s differs" % rel)

    if problems:
        print("brand assets are stale or damaged:")
        for p in problems:
            print("  - %s" % p)
        return 1
    print("brand assets match a fresh render (%d images + the .ico + 3 resource files)"
          % len(plan()))
    return 0


def main(argv):
    if "--check" in argv:
        return check()
    print("rendering brand assets into %s" % ROOT)
    made = write_all()
    print("wrote %d files" % made)
    return check()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
