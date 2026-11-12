"""Optional local vision helpers for reframing.

Nothing here is required for the studio to run. OpenCV is used when it is
available for face-aware crop placement; without it the renderer falls back to
the centre crop. No model, no cloud call, no network.

Frames are extracted by the bundled ffmpeg at 480px wide, so OpenCV never has to
seek through a long source and detection stays fast on a laptop.
"""

import os
import shutil
import subprocess
import tempfile

try:  # optional on purpose
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - the normal fallback path
    cv2 = None
    np = None

from .config import ffmpeg, ffprobe


def available():
    return cv2 is not None and np is not None


def _even(n):
    return int(n) - (int(n) % 2)


def _probe_size(src):
    try:
        out = subprocess.run(
            [ffprobe(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", src],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


def _detectors():
    if cv2 is None:
        return None, None
    base = getattr(cv2, "data", None)
    haar = getattr(base, "haarcascades", "") if base else ""
    frontal_path = os.path.join(haar, "haarcascade_frontalface_default.xml")
    profile_path = os.path.join(haar, "haarcascade_profileface.xml")
    frontal = cv2.CascadeClassifier(frontal_path) if os.path.isfile(frontal_path) else None
    profile = cv2.CascadeClassifier(profile_path) if os.path.isfile(profile_path) else None
    if frontal is not None and frontal.empty():
        frontal = None
    if profile is not None and profile.empty():
        profile = None
    return frontal, profile


def _frames(src, start, end, count):
    """Extract a few small frames with ffmpeg. Returns [(path, w, h)]."""
    if not src or not os.path.isfile(src):
        return []
    duration = max(0.2, float(end) - float(start))
    rate = max(0.2, min(4.0, count / duration))
    tmp = tempfile.mkdtemp(prefix="cb_faces_")
    pattern = os.path.join(tmp, "f_%02d.jpg")
    cmd = [ffmpeg(), "-v", "error", "-nostdin", "-ss", f"{max(0.0, float(start)):.3f}",
           "-i", src, "-t", f"{duration:.3f}",
           "-vf", f"fps={rate:.3f},scale=480:-2", "-frames:v", str(max(1, count)),
           "-q:v", "4", pattern]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return []
    out = []
    for name in sorted(os.listdir(tmp)):
        path = os.path.join(tmp, name)
        img = cv2.imread(path) if cv2 is not None else None
        if img is not None:
            h, w = img.shape[:2]
            out.append((path, w, h))
    if not out:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def face_crop_x(src, start, end, samples=4, target_ratio=9 / 16):
    """Return a source-pixel x offset for a 9:16 crop that follows faces.

    Returns None when OpenCV is missing, the file cannot be opened, or no face is
    found. A caller must treat None as "use the centre crop".
    """
    if cv2 is None or not src or not os.path.isfile(src):
        return None
    frontal, profile = _detectors()
    if frontal is None and profile is None:
        return None
    src_w, src_h = _probe_size(src)
    if src_w <= 0 or src_h <= 0:
        return None
    frames = _frames(src, start, end, max(2, int(samples or 4)))
    if not frames:
        return None
    xs, weights = [], []
    try:
        for path, fw, fh in frames:
            img = cv2.imread(path)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            boxes = []
            kw = dict(scaleFactor=1.12, minNeighbors=4,
                      minSize=(max(14, fw // 18), max(14, fh // 18)))
            if frontal is not None:
                boxes += [tuple(int(v) for v in b) for b in frontal.detectMultiScale(gray, **kw)]
            if profile is not None:
                boxes += [tuple(int(v) for v in b) for b in profile.detectMultiScale(gray, **kw)]
                flipped = cv2.flip(gray, 1)
                for x, y, w, h in profile.detectMultiScale(flipped, **kw):
                    boxes.append((int(fw - x - w), int(y), int(w), int(h)))
            for x, y, w, h in boxes:
                area = w * h
                if area < fw * fh * 0.003:
                    continue
                xs.append(x + w / 2.0)
                weights.append(area)
        if not xs:
            return None
        total = sum(weights) or 1.0
        centre_scaled = sum(x * w for x, w in zip(xs, weights)) / total
        # Reconstruct the intended 9:16 crop in the scaled frame, then map its
        # left edge back to source pixels.
        fw = frames[0][1]
        fh = frames[0][2]
        crop_w_scaled = min(fw, _even(fh * target_ratio))
        left_scaled = max(0.0, min(fw - crop_w_scaled, centre_scaled - crop_w_scaled / 2.0))
        crop_w_src = min(src_w, _even(src_h * target_ratio))
        left_src = left_scaled * (src_w / float(fw))
        return _even(max(0, min(src_w - crop_w_src, int(round(left_src)))))
    except Exception:
        return None
    finally:
        for path, _w, _h in frames:
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            shutil.rmtree(os.path.dirname(frames[0][0]), ignore_errors=True)
        except Exception:
            pass


def _face_centres(img, frontal, profile):
    """Return [(centre_x_fraction, area_fraction)] for faces in one frame."""
    if cv2 is None or img is None:
        return []
    fh, fw = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    boxes = []
    kw = dict(scaleFactor=1.12, minNeighbors=4,
              minSize=(max(14, fw // 18), max(14, fh // 18)))
    if frontal is not None:
        boxes += [tuple(int(v) for v in b) for b in frontal.detectMultiScale(gray, **kw)]
    if profile is not None:
        boxes += [tuple(int(v) for v in b) for b in profile.detectMultiScale(gray, **kw)]
        flipped = cv2.flip(gray, 1)
        for x, y, w, h in profile.detectMultiScale(flipped, **kw):
            boxes.append((int(fw - x - w), int(y), int(w), int(h)))
    out = []
    for x, y, w, h in boxes:
        area = w * h
        if area < fw * fh * 0.003:
            continue
        out.append(((x + w / 2.0) / max(1.0, fw), area / max(1.0, fw * fh)))
    return out


def focus_path(src, start, end, samples=8):
    """A smooth 9:16 crop path that follows the largest face.

    Returns [(seconds_from_clip_start, centre_x_fraction), ...]. The renderer turns
    this into a per-frame crop expression, so the subject stays in frame instead of
    sitting in a blurred landscape plate. With no face, the path is the centre; the
    result is still a full portrait crop, never a letterboxed landscape frame.
    """
    if cv2 is None or not src or not os.path.isfile(src):
        return []
    frontal, profile = _detectors()
    if frontal is None and profile is None:
        return []
    duration = max(0.2, float(end) - float(start))
    frames = _frames(src, start, end, max(3, int(samples or 8)))
    if not frames:
        return []
    raw = []
    try:
        for i, (path, _fw, _fh) in enumerate(frames):
            img = cv2.imread(path)
            faces = _face_centres(img, frontal, profile)
            if faces:
                # Largest face wins; if two are close, the more central one wins.
                faces.sort(key=lambda f: (-f[1], abs(f[0] - 0.5)))
                raw.append(faces[0][0])
            else:
                raw.append(0.5)
        # Median-of-three removes a one-frame false detection without lagging a pan.
        smooth = []
        for i, x in enumerate(raw):
            window = raw[max(0, i - 1):i + 2]
            smooth.append(sorted(window)[len(window) // 2])
        n = len(smooth)
        return [(round(duration * i / max(1, n - 1), 3), round(x, 4))
                for i, x in enumerate(smooth)]
    except Exception:
        return []
    finally:
        for path, _w, _h in frames:
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            shutil.rmtree(os.path.dirname(frames[0][0]), ignore_errors=True)
        except Exception:
            pass


def _probe_duration(src):
    try:
        out = subprocess.run(
            [ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", src],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        return max(0.0, float(out))
    except Exception:
        return 0.0


def _caption_lines_in_frame(img):
    """Conservative: bright glyphs with a dark edge, several on one centred line,
    in the lower part of the frame. Natural edges rarely produce that pattern."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    top, bottom = int(h * 0.40), int(h * 0.97)
    region = gray[top:bottom]
    if region.size == 0:
        return []
    found = []
    for source in (region, 255 - region):
        bright = source >= 190
        dark = cv2.dilate((source <= 70).astype("uint8"), np.ones((5, 5), "uint8"))
        strokes = (bright & (dark > 0)).astype("uint8")
        count, _, stats, centers = cv2.connectedComponentsWithStats(strokes)
        glyph_mask = np.zeros_like(strokes)
        glyphs = []
        min_glyph, max_glyph = h * 0.008, h * 0.07
        for i in range(1, count):
            x, y, cw, ch, area = stats[i]
            if not (min_glyph <= ch <= max_glyph and cw <= ch * 3 and area >= 6):
                continue
            glyph_mask[y:y + ch, x:x + cw] = 1
            glyphs.append((float(centers[i][0]), float(centers[i][1])))
        if len(glyphs) < 5:
            continue
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(3, int(w * 0.05)), max(3, int(h * 0.006))))
        lines = cv2.morphologyEx(glyph_mask, cv2.MORPH_CLOSE, kernel)
        count, _, stats, _ = cv2.connectedComponentsWithStats(lines)
        for i in range(1, count):
            x, y, cw, ch, _area = stats[i]
            if not (h * 0.015 <= ch <= h * 0.10 and cw >= w * 0.25):
                continue
            if abs((x + cw / 2) - w / 2) > w * 0.15:
                continue
            inside = [gx for gx, gy in glyphs
                      if x <= gx <= x + cw and y <= gy <= y + ch]
            if len(inside) < 6 or (max(inside) - min(inside)) < cw * 0.6:
                continue
            found.append(((top + y) / h, (top + y + ch) / h))
    return found


def caption_band(src, samples=8):
    """Return (top, bottom) fractions of a burned-in caption band, or None.

    Runs only when OpenCV is present. Conservative on purpose: a false positive
    would move the studio's captions away from a clean source for no reason.
    """
    if cv2 is None or not src or not os.path.isfile(src):
        return None
    duration = _probe_duration(src)
    if duration <= 0:
        return None
    frames = _frames(src, 0.0, duration, max(4, int(samples or 8)))
    if not frames:
        return None
    try:
        rows = []
        for path, _w, _h in frames:
            img = cv2.imread(path)
            if img is not None:
                rows.append(_caption_lines_in_frame(img))
        if not rows:
            return None
        lines = [line for row in rows for line in row]
        if not lines:
            return None
        centre = float(np.median([(a + b) / 2 for a, b in lines]))
        hits = [[line for line in row if abs((line[0] + line[1]) / 2 - centre) <= 0.06]
                for row in rows]
        hit_frames = sum(1 for row in hits if row)
        if hit_frames < max(2, int(np.ceil(len(rows) * 0.4))):
            return None
        tops = [line[0] for row in hits for line in row]
        bottoms = [line[1] for row in hits for line in row]
        return round(float(np.percentile(tops, 10)), 3), round(float(np.percentile(bottoms, 90)), 3)
    except Exception:
        return None
    finally:
        for path, _w, _h in frames:
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            shutil.rmtree(os.path.dirname(frames[0][0]), ignore_errors=True)
        except Exception:
            pass
