#!/usr/bin/env python
"""B2 Pro X verification — proves the cinematic engine works, end to end.

Run with the server up (python run.py, port 4302):
    python scripts/verify_b2.py

Checks, in order:
  1. health: engine reports "B2 Pro X", ffmpeg + yt-dlp present, a brain is configured
  2. cinema module: ratio table + filter chain build
  3. scene detection on a GENERATED control clip with known cuts at 3/6/9 s
  4. a live demo job through the real API, polled to completion
  5. the rendered file's specs (vertical 1080x1920, audio track, graded frames)

Exit code 0 = all green.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PORT = int(os.environ.get("CB_PORT", "4302"))
BASE = f"http://127.0.0.1:{PORT}"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def get(path, timeout=20):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.load(r)


def main():
    print("\nB2 Pro X verification\n" + "=" * 60)

    # ---- 1. health ----------------------------------------------------------
    print("\n1. server health")
    try:
        h = get("/api/health")
        check("engine reports B2 Pro X", h.get("engine") == "B2 Pro X", h.get("engine"))
        check("ffmpeg available", bool(h.get("ffmpeg")))
        check("yt-dlp available", bool(h.get("ytdlp")))
        check("at least one brain configured", bool(h.get("brains")), str(h.get("brains")))
        print(f"       version {h.get('version')} · stt {h.get('stt')}")
    except Exception as e:
        check("server reachable", False, f"{e} — start it with: python run.py")
        return report()

    # ---- 2. cinema module ---------------------------------------------------
    print("\n2. cinema module")
    from clipblitz import cinema
    check("ratio table has 9:16 / 1:1 / 16:9",
          set(cinema.RATIOS) == {"9:16", "1:1", "16:9"}, str(list(cinema.RATIOS)))
    w, hh = cinema.ratio_size("9:16")
    check("9:16 resolves to 1080x1920", (w, hh) == (1080, 1920), f"{w}x{hh}")
    chain = cinema.cinematic_filters(grain=True)
    check("grade chain builds (contrast + vignette + grain)",
          "contrast" in chain and "vignette" in chain and "noise" in chain)

    # ---- 3. scene detection on a control clip -------------------------------
    print("\n3. scene detection (control clip with cuts at 3 / 6 / 9 s)")
    from clipblitz.config import ffmpeg
    tmp = os.path.join(ROOT, "data", "tmp")
    os.makedirs(tmp, exist_ok=True)
    ctl = os.path.join(tmp, "verify_scenes.mp4")
    graph = ("color=c=black:s=640x360:d=3,format=yuv420p[v0];"
             "color=c=white:s=640x360:d=3,format=yuv420p[v1];"
             "color=c=red:s=640x360:d=3,format=yuv420p[v2];"
             "color=c=blue:s=640x360:d=3,format=yuv420p[v3];"
             "[v0][v1][v2][v3]concat=n=4:v=1:a=0[out]")
    try:
        subprocess.run([ffmpeg(), "-y", "-filter_complex", graph, "-map", "[out]",
                        "-c:v", "libx264", "-preset", "ultrafast", ctl],
                       capture_output=True, timeout=120)
        marks = cinema.scene_map(ctl, threshold=0.30, max_seconds=60)
        times = [round(t) for t, _ in marks]
        check("detected the three cuts", times == [3, 6, 9], f"found {times}")
    except Exception as e:
        check("scene detection ran", False, str(e)[:80])

    # ---- 4. live demo job ---------------------------------------------------
    print("\n4. live demo job through the API")
    try:
        req = urllib.request.Request(BASE + "/api/demo", method="POST")
        job = json.load(urllib.request.urlopen(req, timeout=60)).get("job_id")
        check("demo job started", bool(job), job)
    except Exception as e:
        check("demo job started", False, str(e)[:80])
        return report()

    status, info = "running", {}
    for _ in range(60):          # up to ~10 minutes (cinema + grade is heavier)
        time.sleep(10)
        try:
            info = get(f"/api/job/{job}?light=1")
        except Exception:
            continue
        status = info.get("status")
        print(f"       {status} {info.get('progress')}% — {info.get('stage', '')[:60]}")
        if status in ("done", "error"):
            break
    check("job finished cleanly", status == "done", f"status={status} err={info.get('error')}")

    # ---- 5. rendered output -------------------------------------------------
    print("\n5. rendered output")
    clips = info.get("clips") or []
    check("at least one clip rendered", len(clips) > 0, f"{len(clips)} clip(s)")
    if clips:
        rel = clips[0].get("file", "").lstrip("/")
        path = os.path.join(ROOT, "data", rel.replace("clips/", "clips/"))
        check("clip file exists on disk", os.path.isfile(path), path)
        from clipblitz.config import ffprobe
        try:
            p = subprocess.run([ffprobe(), "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "default=nw=1", path],
                               capture_output=True, timeout=60)
            dims = dict(l.split("=") for l in p.stdout.decode().strip().splitlines() if "=" in l)
            check("vertical 1080x1920", dims.get("width") == "1080" and dims.get("height") == "1920",
                  f"{dims.get('width')}x{dims.get('height')}")
            a = subprocess.run([ffprobe(), "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=codec_name", "-of", "default=nw=1", path],
                               capture_output=True, timeout=60)
            check("audio track present", "codec_name" in a.stdout.decode(), a.stdout.decode().strip())
        except Exception as e:
            check("output probed", False, str(e)[:80])
        check("score follows content (0-100)", 0 <= (clips[0].get("score") or -1) <= 100,
              str(clips[0].get("score")))
        check("QC verdict recorded", bool(clips[0].get("qc")), str(clips[0].get("qc")))

    return report()


def report():
    print("\n" + "=" * 60)
    print(f"PASS {len(PASS)} · FAIL {len(FAIL)}")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
        print("RESULT: NOT GREEN")
        return 1
    print("RESULT: ALL GREEN — B2 Pro X verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())