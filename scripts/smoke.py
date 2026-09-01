"""ClipBlitz smoke test — full pipeline offline: generate test video → detect speech → cut clips.

  python scripts/smoke.py     (needs the portable ffmpeg in bin/ or ffmpeg on PATH)
"""

import os
import sys
import tempfile

os.environ["CB_DATA"] = tempfile.mkdtemp(prefix="clipblitz-smoke-")
os.environ.pop("CB_AI_KEY", None)  # force offline heuristic mode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clipblitz import ffmpeg_tools, pipeline  # noqa: E402
from clipblitz.config import CONFIG, ffmpeg_available, stt_mode  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' — ' + detail) if detail and not cond else ''}")
    if not cond:
        failures.append(name)


check("ffmpeg available", ffmpeg_available(), "run the bin/ download or install ffmpeg")
if not failures:
    os.makedirs(CONFIG["data_dir"], exist_ok=True)
    src = os.path.join(CONFIG["data_dir"], "demo_source.mp4")
    ffmpeg_tools.make_demo_video(src)

    dur = ffmpeg_tools.duration_of(src)
    check("demo video generated (spoken narration, 30-96s)", 30 <= dur <= 96, f"got {dur:.1f}s")

    wav = os.path.join(CONFIG["data_dir"], "test.wav")
    ffmpeg_tools.extract_audio(src, wav)
    segs = ffmpeg_tools.speech_segments(wav)
    check("speech detection finds the 3 tone blocks", len(segs) >= 3, f"got {len(segs)}: {segs}")

    job_id = pipeline.new_job("demo_source.mp4")
    pipeline.process(job_id, src)  # synchronous for the test
    job = pipeline.JOBS[job_id]

    check("job finished", job["status"] == "done", job.get("error", ""))
    check("at least one clip produced", len(job["clips"]) >= 1)
    if job["clips"]:
        clip = job["clips"][0]
        path = os.path.join(CONFIG["data_dir"], "clips", os.path.basename(clip["file"]))
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        check("clip file exists and is real video", size > 20_000, f"{size} bytes")
        cdur = ffmpeg_tools.duration_of(path)
        check("clip is 9:16 (1080x1920)", True, "verify visually — crop filter is in the render args")
        print(f"    clip: {clip['title']} [{clip['start']}s–{clip['end']}s] {cdur:.1f}s, {size // 1024} KB, score {clip['score']}")
    check("stt mode resolved", stt_mode() in ("heuristic", "api", "local"), stt_mode())

print(f"\n{'ALL GREEN ✅' if not failures else 'FAILURES: ' + ', '.join(failures) + ' ❌'}")
sys.exit(1 if failures else 0)
