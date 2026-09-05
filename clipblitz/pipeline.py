"""The v4 pipeline: video in → transcript → audio-energy profile → ProX top-3
→ styled captioned verticals → AI metadata → optional automatic social posting.

Jobs are persisted to data/jobs.json so a refresh (or server restart) never
orphans clips. Every candidate and clip carries its factor breakdown.
"""

import json
import os
import re
import threading
import time
import uuid

from . import captions, ffmpeg_tools, social, stt, virality
from .config import CONFIG

JOBS = {}  # id -> job dict (persisted to jobs.json)
JOBS_FILE = os.path.join(CONFIG["data_dir"], "jobs.json")

DEMO_WORDS = ["watch", "clipblitz", "turn", "this", "test", "video", "into", "vertical",
              "clips", "with", "animated", "captions", "in", "every", "style"]


def _load_jobs():
    try:
        data = json.load(open(JOBS_FILE, encoding="utf-8"))
        for j in data:
            if j.get("status") in ("queued", "running", "posting"):
                j["status"] = "error"
                j["stage"] = "server restarted — re-run this job"
                j["error"] = "Interrupted by a server restart."
            JOBS[j["id"]] = j
    except (OSError, ValueError):
        pass


def save():
    try:
        os.makedirs(CONFIG["data_dir"], exist_ok=True)
        tmp = JOBS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(JOBS.values())[-40:], f)  # keep the last 40 jobs
        os.replace(tmp, JOBS_FILE)
    except OSError:
        pass


_load_jobs()


def new_job(name, style=None, position="bottom", size_scale=1.0, auto_post=False, privacy=None,
            demo=False, framing="blur", top_n=None):
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {
        "id": job_id, "name": name, "status": "queued", "stage": "waiting",
        "progress": 0, "clips": [], "candidates": [], "segments": [],
        "error": None, "mode": None, "content_type": None, "picker": None,
        "created": time.time(), "demo": bool(demo), "framing": framing or "blur",
        "style": style or captions.DEFAULT_STYLE,
        "position": position, "size_scale": float(size_scale or 1.0),
        "auto_post": bool(auto_post), "privacy": privacy or CONFIG["privacy"],
        "top_n": int(top_n) if top_n else CONFIG["top_n"],
    }
    save()
    return job_id


def _set(job, **kw):
    job.update(kw)
    save()


def job(job_id):
    return JOBS.get(job_id)


def _words_for_window(segments, w0, w1):
    """Flatten Whisper word timings inside the window; distribute evenly as fallback."""
    words = []
    for s in segments:
        for w in s.get("words", []):
            if w["end"] > w0 and w["start"] < w1:
                words.append({"word": w["word"], "start": w["start"], "end": w["end"]})
    if words:
        return words
    text_words = []
    for s in segments:
        if s.get("text") and s["end"] > w0 and s["start"] < w1:
            text_words.extend(s["text"].split())
    if not text_words:
        return []
    span = w1 - w0
    step = span / max(len(text_words), 1)
    return [{"word": w, "start": w0 + i * step, "end": w0 + (i + 1) * step}
            for i, w in enumerate(text_words)]


def _render_clip(job, src_path, m, base, clips_dir):
    """Cut + caption one moment. Returns the clip dict (appended by caller)."""
    words = _words_for_window(job["segments"], m["start"], m["end"])
    if not words and job.get("demo"):
        span = max(1.0, m["end"] - m["start"])
        step = span / len(DEMO_WORDS)
        words = [{"word": w, "start": m["start"] + i * step, "end": m["start"] + (i + 1) * step}
                 for i, w in enumerate(DEMO_WORDS)]
    ass_name = None
    if words:
        ass_path = os.path.join(clips_dir, base + ".ass")
        captions.build_ass(words, (m["start"], m["end"]),
                           job["style"], job["size_scale"], job["position"], ass_path)
        ass_name = base + ".ass"  # relative → ffmpeg runs with cwd=clips_dir (path-safe)
    note = ffmpeg_tools.cut_clip(src_path, m["start"], m["end"],
                                 os.path.join(clips_dir, base + ".mp4"), ass_name,
                                 cwd=clips_dir, framing=job.get("framing", "blur"))
    return {
        "file": f"/clips/{base}.mp4",
        "ass": f"/clips/{base}.ass" if ass_name else None,
        "note": note if isinstance(note, str) and "skipped" in note else None,
        "title": m.get("title", "Clip"),
        "hook": m.get("hook", ""),
        "reason": m.get("reason", ""),
        "verdict": m.get("verdict", ""),
        "qc": m.get("qc", ""),
        "topic": m.get("topic", ""),
        "score": m.get("score", 50),
        "factors": m.get("factors", {}),
        "start": round(m["start"], 1), "end": round(m["end"], 1),
        "duration": round(m["end"] - m["start"], 1),
        "style": job["style"],
        "rank": m.get("rank"),
        "custom": bool(m.get("custom")),
        "meta": m.get("meta", {}),
        "post": {},
    }


def process(job_id, src_path):
    job_ = JOBS[job_id]
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    tmp_dir = os.path.join(CONFIG["data_dir"], "tmp")
    os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        _set(job_, status="running", stage="probing video", progress=4)
        duration = ffmpeg_tools.duration_of(src_path)  # fails with a clear message if unreadable
        _set(job_, duration=duration)

        _set(job_, stage="extracting audio", progress=8)
        wav = os.path.join(tmp_dir, f"{job_id}.wav")
        ffmpeg_tools.extract_audio(src_path, wav)

        _set(job_, stage="reading the audio's energy profile", progress=12)
        energy = ffmpeg_tools.loudness_profile(wav)
        _set(job_, stage="detecting audience laughter (acoustic)", progress=14)
        laughs = ffmpeg_tools.laughter_regions(wav)
        _set(job_, laughs=len(laughs))
        _set(job_, stage="finding the peak moments (audio + camera cuts)", progress=17)
        scenes = ffmpeg_tools.scene_cuts(src_path)
        _set(job_, scenes=len(scenes))

        _set(job_, stage="transcribing", progress=20)
        mode = stt_mode()
        segments = stt.transcribe(wav, mode)
        _set(job_, segments=segments,
             stage=f"transcribed via {mode} ({len(segments)} blocks)", progress=40)

        _set(job_, stage=f"ProX engine: mining + measuring candidates", progress=52)
        moments, candidates, picker, content_type = virality.rank(
            segments, duration, count=job_.get("top_n") or CONFIG["top_n"],
            energy=energy, laughs=laughs, scenes=scenes)
        _set(job_, mode=f"{mode}+{picker}", content_type=content_type, picker=picker,
             candidates=[{k: c[k] for k in c if k != "meta"} for c in candidates])
        if not moments:
            raise RuntimeError("No clip candidates could be produced from this video.")

        _set(job_, stage="writing titles, descriptions & hashtags", progress=60)
        meta = virality.generate_metadata(moments, segments)
        for i, m in enumerate(moments):
            m["meta"] = meta.get(i, {})

        total = max(len(moments), 1)
        for i, m in enumerate(moments):
            _set(job_, stage=f"rendering clip {i + 1}/{total} ({job_['style']} captions, 9:16)",
                 progress=64 + int(30 * i / total))
            base = f"{job_id}_{i + 1}"
            clip = _render_clip(job_, src_path, m, base, clips_dir)
            clip["rank"] = i + 1
            job_["clips"].append(clip)
            save()

        _set(job_, status="done", stage=f"top {len(job_['clips'])} clips ready", progress=96)

        if job_["auto_post"] and job_["clips"]:
            platforms = ["youtube"] if social.youtube_connected() else []
            assisted = ["tiktok"]  # assisted package is always prepared for TikTok
            targets = platforms + assisted
            for i in range(len(job_["clips"])):
                _set(job_, status="running", progress=97,
                     stage=f"auto-posting clip {i + 1}/{len(job_['clips'])} → {', '.join(targets)}")
                social.post_clip(job_, i, targets, on_update=save, wait=True)

        # QC re-check: if the judge was rate-limited during the run, cool down and retry
        # — verdicts/scores refresh without re-rendering (windows never change here).
        if virality.has_brain() and any(c.get("qc") != "verified" for c in job_["clips"]):
            _set(job_, status="running", progress=98, stage="QC judge re-check (rate-limit cooldown)")
            time.sleep(40)
            try:
                ok = virality.rejudge(job_["clips"], segments, job_.get("content_type") or "other")
                save()
                if ok:
                    _set(job_, stage=f"QC judge verified {ok}/{len(job_['clips'])} clips")
            except Exception:
                pass

        _set(job_, status="done", stage="done", progress=100)
    except Exception as e:
        import traceback
        tb = traceback.format_exc().strip().splitlines()
        _set(job_, status="error", error=f"{e} || {' <- '.join(tb[-4:-1])}"[:900], stage="failed")
    finally:
        junk = os.path.join(CONFIG["data_dir"], "tmp", f"{job_id}.wav")
        if os.path.exists(junk):
            os.remove(junk)


def render_candidate(job_id, cand_index, style=None, position=None, size_scale=None):
    """Render (or re-render) one candidate — a runner-up or a restyle of an existing cut."""
    job_ = JOBS.get(job_id)
    if not job_:
        return None, "unknown job"
    cands = job_.get("candidates") or []
    if not isinstance(cand_index, int) or not 0 <= cand_index < len(cands):
        return None, "unknown candidate"
    src = job_.get("src") or _find_source(job_id)
    if not src or not os.path.isfile(src):
        return None, "source video no longer on disk — re-upload to re-render"
    if style:
        job_["style"] = style
    if position:
        job_["position"] = position
    if size_scale:
        job_["size_scale"] = float(size_scale)
    cand = dict(cands[cand_index])
    cand["custom"] = cand.get("custom", False)
    cand["rank"] = len(job_["clips"]) + 1
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    base = f"{job_id}_{len(job_['clips']) + 1}_{int(time.time()) % 10000}"
    try:
        clip = _render_clip(job_, src, cand, base, clips_dir)
    except Exception as e:
        return None, str(e)[:300]
    clip["rank"] = len(job_["clips"]) + 1
    job_["clips"].append(clip)
    save()
    return clip, None


def render_custom(job_id, start, end, style=None):
    """Cut a user-dragged window; it goes through the same honest measurement."""
    job_ = JOBS.get(job_id)
    if not job_:
        return None, "unknown job"
    try:
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        return None, "bad start/end"
    duration = job_.get("duration") or 0
    if duration and end > duration:
        end = duration
    if not (0 <= start < end) or end - start < 3:
        return None, "window must be at least 3 seconds"
    if end - start > 120:
        end = start + 120
    if style:
        job_["style"] = style
    m = virality.rank_single(job_.get("segments") or [], duration or end + 1,
                             None, start, end)
    m["custom"] = True
    m["title"] = f"Custom cut {m['start']:.0f}-{m['end']:.0f}s"
    m["meta"] = virality.fallback_metadata([m])[0]
    m["rank"] = len(job_["clips"]) + 1
    src = job_.get("src") or _find_source(job_id)
    if not src or not os.path.isfile(src):
        return None, "source video no longer on disk — re-upload to re-render"
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    base = f"{job_id}_custom_{int(time.time()) % 100000}"
    try:
        clip = _render_clip(job_, src, m, base, clips_dir)
    except Exception as e:
        return None, str(e)[:300]
    clip["rank"] = len(job_["clips"]) + 1
    job_["clips"].append(clip)
    save()
    return clip, None


def _find_source(job_id):
    """Locate the most likely source file for a persisted job after a restart."""
    up_dir = os.path.join(CONFIG["data_dir"], "uploads")
    if not os.path.isdir(up_dir):
        return None
    candidates = [os.path.join(up_dir, f) for f in os.listdir(up_dir)]
    video = [p for p in candidates if p.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"))]
    return max(video, key=os.path.getmtime) if video else None


def start(job_id, src_path):
    JOBS[job_id]["src"] = src_path
    JOBS[job_id]["src_name"] = os.path.basename(src_path)
    save()
    threading.Thread(target=process, args=(job_id, src_path), daemon=True).start()
    return job_id


def start_from_url(job_id, url):
    """Download a video from a URL (YouTube via yt-dlp, or a direct media link),
    then run the normal pipeline on it."""
    from . import ingest

    def runner():
        job_ = JOBS[job_id]
        try:
            _set(job_, status="running", stage="downloading video from URL", progress=1)
            src = ingest.download(url, os.path.join(CONFIG["data_dir"], "uploads"))
            JOBS[job_id]["src"] = src
            JOBS[job_id]["src_name"] = os.path.basename(src)
            base = os.path.splitext(os.path.basename(src))[0]
            pretty = re.sub(r"^yt_[A-Za-z0-9_-]+_\d+_", "", base)  # strip yt_<id>_<ts>_ prefix
            if len(pretty) > 3 and re.fullmatch(r"[A-Za-z0-9_-]{11}", JOBS[job_id].get("name") or ""):
                JOBS[job_id]["name"] = pretty  # URL-slug name -> real video title
            save()
            process(job_id, src)
        except Exception as e:
            _set(job_, status="error", error=str(e)[:400], stage="download failed")

    threading.Thread(target=runner, daemon=True).start()
    return job_id


def stt_mode():
    from .config import stt_mode as resolve
    return resolve()
