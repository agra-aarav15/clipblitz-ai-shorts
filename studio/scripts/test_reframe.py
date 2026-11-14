"""Portrait reframe tests - stdlib + bundled ffmpeg, no network.

Run from the studio root:   python scripts/test_reframe.py

The old default was a blurred landscape plate. These tests lock down the new
focus crop: a full-height 9:16 crop, a per-frame subject path, and a real rendered
file that is 1080x1920 rather than a landscape frame with bars.
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz import ffmpeg_tools as F  # noqa: E402
from clipblitz import vision  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def test_expression():
    path = [(0.0, 0.30), (2.0, 0.50), (4.0, 0.70)]
    expr = F._focus_x_expr(path)
    check("reframe: a focus path becomes a per-frame expression",
          bool(expr) and "if(lt(t" in expr and "iw*0.3000" in expr, (expr or "")[:80])
    check("reframe: the expression is clamped to the source",
          "max(0" in expr and "min(iw-ih*9/16" in expr)
    check("reframe: no path falls back to the centre",
          F._focus_x_expr([]) is None)


def test_filtergraph():
    simple = F._filtergraph("focus", None, 10.0,
                            focus_path=[(0.0, 0.4), (5.0, 0.6)])[1]
    check("reframe: focus is a full-height 9:16 crop",
          "crop=w=min(iw" in simple and "ih*9/16" in simple, simple[:90])
    check("reframe: focus does not use a blur plate",
          "boxblur" not in simple)
    check("reframe: focus scales to 1080x1920",
          "scale=1080:1920" in simple)
    blur = F._filtergraph("blur", None, 10.0)[0]
    check("reframe: blur remains available as an explicit option",
          bool(blur) and "boxblur" in blur)
    auto = F._filtergraph("auto", None, 10.0,
                          focus_path=[(0.0, 0.3), (5.0, 0.7)])[1]
    check("reframe: auto framing follows a supplied focus path",
          "if(lt(t" in auto, auto[:90])
    tall = F._filtergraph("crop", None, 10.0)[1]
    check("reframe: fixed crop is guarded for tall sources",
          "min(iw" in tall and "min(ih" in tall, tall[:90])


def test_active_area():
    """A source with black side bars must report the real picture rectangle; a
    full-frame source must not. The focus crop is clamped inside that rectangle so
    the rendered portrait never contains the source's bar."""
    padded = os.path.join(tempfile.gettempdir(), "cb_reframe_padded.mp4")
    plain = os.path.join(tempfile.gettempdir(), "cb_reframe_plain.mp4")
    out = os.path.join(tempfile.gettempdir(), "cb_reframe_padded_out.mp4")
    try:
        F.run([F.ffmpeg(), "-y", "-v", "error",
               "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=2:r=30",
               "-f", "lavfi", "-i", "testsrc2=size=960x720:rate=30:duration=2",
               "-filter_complex", "[0][1]overlay=160:0", "-shortest",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", padded], timeout=60)
        area = F.detect_active_area(padded)
        check("reframe: a pillarboxed source reports its active picture area",
              bool(area) and abs(area[0] - 0.125) < 0.01
              and abs(area[2] - 0.875) < 0.01, str(area))
        F.run([F.ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
               "-i", "testsrc2=size=1280x720:rate=30:duration=2",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", plain], timeout=60)
        check("reframe: a full-frame source reports no bars",
              F.detect_active_area(plain) is None)
        expr = F._filtergraph("focus", None, 2.0, focus_path=[(0.0, 0.02)],
                              active=area)[1]
        check("reframe: the focus expression is clamped inside the active area",
              "iw*0.1250" in expr and "iw*0.8750" in expr, expr[:100])
        # Render with the subject pushed to the left edge: the clamp must keep the
        # output out of the black bar, so the leftmost 8px column is picture, not bar.
        F.cut_clip(padded, 0.0, 1.0, out, framing="focus",
                   focus_path=[(0.0, 0.02), (1.0, 0.02)], active=area,
                   grade=False, vignette=False)
        stat = subprocess.run(
            [F.ffmpeg(), "-v", "error", "-i", out, "-frames:v", "1",
             "-vf", "crop=8:1920:0:0,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
             "-f", "null", "-"], capture_output=True, text=True, timeout=60)
        yavg = [float(m) for m in re.findall(
            r"lavfi\.signalstats\.YAVG=([\d.]+)", stat.stdout + stat.stderr)]
        check("reframe: a clamped crop does not include the source's black bar",
              bool(yavg) and max(yavg) > 20.0, str(yavg[:3]))
    except Exception as e:
        check("reframe: a pillarboxed source is measured and clamped", False, str(e))
    finally:
        for p in (padded, plain, out):
            try:
                os.remove(p)
            except OSError:
                pass


def test_subject_centre():
    try:
        import cv2
        import numpy as np
        img = np.zeros((720, 1280, 3), dtype="uint8")
        cv2.rectangle(img, (900, 150), (1200, 650), (255, 255, 255), -1)
        centre = vision._subject_centre(img)
        check("reframe: a faceless side subject is not centre-cropped out",
              centre > 0.55, str(centre))
    except Exception as e:
        check("reframe: a faceless side subject is not centre-cropped out", False, str(e))


def test_focus_path_fallback():
    # A source with no detectable face must still return a centre path, not [].
    src = os.path.join(tempfile.gettempdir(), "cb_reframe_blank.mp4")
    try:
        F.run([F.ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
               "-i", "color=c=black:s=1280x720:d=2", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", src], timeout=60)
        path = vision.focus_path(src, 0.0, 2.0, samples=3)
        check("reframe: a faceless landscape source gets a centre path",
              bool(path) and all(abs(x - 0.5) < 0.01 for _t, x in path), str(path))
    except Exception as e:
        check("reframe: a faceless landscape source gets a centre path", False, str(e))
    finally:
        try:
            os.remove(src)
        except OSError:
            pass


def test_tall_render():
    src = os.path.join(tempfile.gettempdir(), "cb_reframe_tall.mp4")
    out = os.path.join(tempfile.gettempdir(), "cb_reframe_tall_out.mp4")
    try:
        F.run([F.ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
               "-i", "testsrc2=size=1080x2400:rate=30:duration=1",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
               "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", src], timeout=60)
        F.cut_clip(src, 0.0, 1.0, out, framing="crop", grade=False, vignette=False)
        probe = subprocess.run(
            [F.ffprobe(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
            capture_output=True, text=True, timeout=30).stdout.strip()
        check("reframe: a tall source renders with fixed crop", probe == "1080,1920", probe)
    except Exception as e:
        check("reframe: a tall source renders with fixed crop", False, str(e))
    finally:
        for p in (src, out):
            try:
                os.remove(p)
            except OSError:
                pass


def test_real_render():
    src = os.path.join(tempfile.gettempdir(), "cb_reframe_landscape.mp4")
    out = os.path.join(tempfile.gettempdir(), "cb_reframe_portrait.mp4")
    try:
        F.run([F.ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
               "-i", "testsrc2=size=1280x720:rate=30:duration=2",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
               "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", src], timeout=60)
        F.cut_clip(src, 0.0, 2.0, out, framing="focus",
                   focus_path=[(0.0, 0.35), (1.0, 0.5), (2.0, 0.65)],
                   grade=False, vignette=False)
        probe = subprocess.run(
            [F.ffprobe(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
            capture_output=True, text=True, timeout=30).stdout.strip()
        check("reframe: a landscape source renders a real 1080x1920 file",
              probe == "1080,1920", probe)
    except Exception as e:
        check("reframe: a landscape source renders a real 1080x1920 file", False, str(e))
    finally:
        for p in (src, out):
            try:
                os.remove(p)
            except OSError:
                pass


def main():
    test_expression()
    test_filtergraph()
    test_active_area()
    test_subject_centre()
    test_focus_path_fallback()
    test_tall_render()
    test_real_render()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
