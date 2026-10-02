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

from . import (captions, cinema, ffmpeg_tools, hardware, learning, rights, social, stt,
               virality)
from .config import CONFIG

JOBS = {}  # id -> job dict (persisted to jobs.json)
JOBS_FILE = os.path.join(CONFIG["data_dir"], "jobs.json")

DEMO_WORDS = ["watch", "clipblitz", "turn", "this", "test", "video", "into", "vertical",
              "clips", "with", "animated", "captions", "in", "every", "style"]

ENGINES = {
    "prox": {"id": "prox", "name": "ProX v5",
             "note": "story-first cuts, judged and quality-gated"},
    "b2":   {"id": "b2", "name": "B2 Pro X",
             "note": "cuts on shot boundaries, film grade, sound leads the cut"},
    "both": {"id": "both", "name": "Both engines",
             "note": "one analysis pass, both cuts side by side"},
}

# The rights gate. Consent plus information — never detection evasion. The owner
# answers once per job, before the first upload goes out; the answer is stored on the
# job. Nothing here fingerprints, pitches, speeds, mirrors or otherwise tries to
# trick a platform's content matching, and nothing ever will.
RIGHTS = [
    {"id": "own", "label": "It is my own content",
     "note": "You filmed it, or you own the footage and the audio. Clipping your own "
             "long videos into shorts is the primary use case and is always safe."},
    {"id": "licensed", "label": "I have a licence or written permission",
     "note": "The rights holder gave you permission to cut and publish this material. "
             "Keep the agreement where you can find it."},
    {"id": "fair_use", "label": "It is a transformative fair-use edit",
     "note": "You added genuine commentary, reaction, criticism or teaching and you "
             "publish for that purpose. That is a judgement call, and it is yours."},
]
RIGHTS_IDS = {r["id"] for r in RIGHTS}
RIGHTS_NOTE = ("YouTube's Content ID finds unlicensed re-uploads no matter how they are "
               "edited. This studio confirms your rights; it does not and will not try "
               "to evade content matching.")


def _engine_fields(engine):
    """Render fields implied by an engine choice. ProX v5 is this codebase with the
    cinema layer off: no grade, fixed 9:16, no audio lead - the legacy engine exactly."""
    if engine == "prox":
        return {"cinematic_grade": False, "cinematic_grain": False,
                "ratio": "9:16", "audio_lead": 0.0}
    return {"cinematic_grade": True, "cinematic_grain": False,
            "ratio": "9:16", "audio_lead": 0.35}


def _load_jobs():
    try:
        data = json.load(open(JOBS_FILE, encoding="utf-8"))
        for j in data:
            if j.get("status") in ("queued", "running", "posting") and not j.get("rights_hold"):
                j["status"] = "error"
                j["stage"] = "server restarted — re-run this job"
                j["error"] = "Interrupted by a server restart."
            j.setdefault("engine_id", "b2")
            j.setdefault("engine", ENGINES["b2"]["name"])
            j.setdefault("rights_ok", None)
            j.setdefault("rights_pending", False)
            j.setdefault("licence", None)
            j.setdefault("receipt", None)
            if rights.enabled():
                # a job the strict clearance gate is holding across a restart stays
                # answerable: the rights question (or an override) resumes it, and the
                # override record rides in the certificate
                j.setdefault("rights_override", None)
            j.setdefault("source", {"kind": "upload", "label": j.get("name") or ""})
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
            demo=False, framing="blur", top_n=None, engine=None, source=None):
    engine = engine if engine in ENGINES else CONFIG.get("engine_default", "b2")
    if engine not in ENGINES:
        engine = "b2"
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
        "engine_id": engine,
        "engine": ENGINES[engine]["name"],
        # rights gate: None until the owner answers once on the Clips screen
        "rights_ok": None, "rights_pending": False,
        # copyright safety: the licence record and the written edit receipt
        "licence": None, "receipt": None,
        "source": dict(source or {"kind": "upload", "label": name}),
    }
    JOBS[job_id].update(_engine_fields("b2" if engine == "both" else engine))
    save()
    return job_id


def set_rights(job, answer):
    """Store the owner's answer to the rights gate on the job (and log no choice:
    answering the gate is not a taste signal about the cut)."""
    if answer not in RIGHTS_IDS:
        return False
    job["rights_ok"] = answer
    job["rights_at"] = time.time()
    save()
    return True


def resume_autopost(job_id):
    """Run the auto-post a job was holding back for the rights gate. Runs in a
    background thread - a real upload blocks for a while."""
    job_ = JOBS.get(job_id)
    if not job_ or not job_.get("rights_pending") or not rights.cleared(job_):
        return False

    def runner():
        targets = (["youtube"] if social.youtube_connected() else []) + ["tiktok"]
        job_["rights_pending"] = False
        for i in range(len(job_["clips"])):
            _set(job_, stage=f"auto-posting clip {i + 1}/{len(job_['clips'])} -> {', '.join(targets)}")
            social.post_clip(job_, i, targets, on_update=save, wait=True)
            from . import learning
            learning.log("post", job_["clips"][i], job_)
        _set(job_, stage="done", progress=100)

    threading.Thread(target=runner, daemon=True).start()
    return True


def _variant(job, engine):
    """Resolve an engine override for single re-renders; 'both' jobs default to b2."""
    if engine in ("prox", "b2"):
        return engine
    eng = job.get("engine_id", "b2")
    return "b2" if eng == "both" else eng


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


def _waveform(energy, duration, buckets=600):
    """Normalise the ALREADY-MEASURED RMS series into `buckets` values in 0..1 so the
    Transcript timeline can draw the real audio shape. Pure arithmetic on data the
    pipeline already has — no extra ffmpeg pass. Returns [] when the profile is too
    sparse to be honest about, in which case the UI draws nothing."""
    series, mean_db = energy if energy else ([], -30.0)
    if len(series) < 8 or not duration:
        return []
    step = duration / buckets
    sums, counts = [0.0] * buckets, [0] * buckets
    for t, db in series:
        i = min(buckets - 1, max(0, int(t / step)))
        sums[i] += db
        counts[i] += 1
    vals = [sums[i] / counts[i] if counts[i] else mean_db for i in range(buckets)]
    lo, hi = min(vals), max(vals)
    if hi - lo < 6.0:                       # a flat video: show it relative to its own mean
        lo, hi = mean_db - 12.0, mean_db + 3.0
    span = max(1.0, hi - lo)
    return [round(max(0.0, min(1.0, (v - lo) / span)), 3) for v in vals]


def _render_clip(job, src_path, m, base, clips_dir, engine=None):
    """Cut + caption one moment. Returns the clip dict (appended by caller).

    engine=None means the job's own engine; "prox"/"b2" render that specific variant
    (used by the both-engines job and by re-renders from the comparison view)."""
    eng = engine or job.get("engine_id", "b2")
    if eng == "both":
        eng = "b2"
    fields = _engine_fields(eng)
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
    # The transformative-edit layers this render actually applied. Every entry is a real
    # step taken by this render - captions burned into the pixels, a vertical reframe,
    # the film grade, the J-cut - so the badge on the card is a fact, not a claim about
    # the law. (Whether a use is fair is the owner's call, made on the rights gate.)
    layers = []
    if ass_name:
        layers.append("captions burned into the picture")
    layers.append("vertical reframing" + (" with a blur pad" if job.get("framing", "blur") == "blur"
                                          else " to centre crop"))
    if fields["cinematic_grade"]:
        layers.append("film grade (S-curve + vignette)")
    if fields["audio_lead"]:
        layers.append("J-cut (the sound leads the picture)")

    note = ffmpeg_tools.cut_clip(src_path, m["start"], m["end"],
                                 os.path.join(clips_dir, base + ".mp4"), ass_name,
                                 cwd=clips_dir, framing=job.get("framing", "blur"),
                                 grade=fields["cinematic_grade"],
                                 grain=fields["cinematic_grain"],
                                 ratio="9:16" if eng == "prox" else (job.get("ratio") or "9:16"),
                                 audio_lead=fields["audio_lead"])
    return {
        "file": f"/clips/{base}.mp4",
        "ass": f"/clips/{base}.ass" if ass_name else None,
        "note": note if isinstance(note, str) and "skipped" in note else None,
        "title": m.get("title", "Clip"),
        "hook": m.get("hook", ""),
        "reason": m.get("reason", ""),
        "verdict": m.get("verdict", ""),
        "qc": m.get("qc", ""),
        "cinema": m.get("cinema", "") if eng == "b2" else "",
        "ratio": "9:16" if eng == "prox" else (job.get("ratio") or "9:16"),
        "engine": ENGINES[eng]["name"],
        "engine_id": eng,
        "topic": m.get("topic", ""),
        "score": m.get("score", 50),
        "factors": m.get("factors", {}),
        "start": round(m["start"], 1), "end": round(m["end"], 1),
        "duration": round(m["end"] - m["start"], 1),
        "style": job["style"],
        "rank": m.get("rank"),
        "custom": bool(m.get("custom")),
        "transformative": layers,
        "laugh_ending": bool(m.get("laugh_ending")),
        "meta": m.get("meta", {}),
        "post": {},
    }


def process(job_id, src_path):
    job_ = JOBS[job_id]
    eng = job_.get("engine_id", "b2")
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    tmp_dir = os.path.join(CONFIG["data_dir"], "tmp")
    os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        hw = hardware.profile(refresh=True)
        if not hw.get("render_capable"):
            raise RuntimeError(hw.get("reason") or "This device can't render clips.")
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

        # ---- B2 Pro X cinema measurement (skipped entirely for the ProX engine) ----
        # real shot boundaries + per-second on-screen motion, so cuts can land on edits and
        # payoffs can land on the shot that actually carries them
        cinema_marks, motion = None, None
        if eng in ("b2", "both"):
            _set(job_, stage="B2 cinema map: shots + motion", progress=18)
            scene_cache = os.path.join(CONFIG["data_dir"], "cache", f"{job_id}-scenes.json")
            cinema_marks = cinema.load_scene_cache(scene_cache)
            if not cinema_marks:
                cinema_marks = cinema.scene_map(src_path)
                cinema.save_scene_cache(scene_cache, cinema_marks)
            _set(job_, shots=len(cinema_marks))
            motion = cinema.motion_map(src_path, 0.0, duration)
            _set(job_, motion_points=len(motion))

        _set(job_, stage="transcribing", progress=20)
        mode = stt_mode()
        segments = stt.transcribe(wav, mode)
        _set(job_, segments=segments,
             stage=f"transcribed via {mode} ({len(segments)} blocks)", progress=40)

        _set(job_, stage=f"{ENGINES[eng]['name']}: mining + measuring candidates", progress=52)
        # engine selects which learned weight profile scores this run. "both" passes
        # None on purpose: one analysis pass has exactly one ranking, and the two cuts
        # are two renders of it.
        moments, candidates, picker, content_type = virality.rank(
            segments, duration, count=job_.get("top_n") or CONFIG["top_n"],
            energy=energy, laughs=laughs, scenes=scenes,
            cinema_marks=cinema_marks, motion=motion,
            engine=eng if eng in ("prox", "b2") else None)
        _set(job_, mode=f"{mode}+{picker}", content_type=content_type, picker=picker,
             engine=ENGINES[eng]["name"], engine_id=eng,
             shots=len(cinema_marks) if cinema_marks else 0,
             candidates=[{k: c[k] for k in c if k != "meta"} for c in candidates],
             # real measured audio + the mined peak regions, for the Transcript timeline
             waveform=_waveform(energy, duration),
             moments=[{k: m[k] for k in ("start", "end", "heat", "roar", "cuts") if k in m}
                      for m in moments])
        if not moments:
            raise RuntimeError("No clip candidates could be produced from this video.")

        _set(job_, stage="writing titles, descriptions & hashtags", progress=60)
        meta = virality.generate_metadata(moments, segments)
        for i, m in enumerate(moments):
            m["meta"] = meta.get(i, {})

        # both: two variants per moment from ONE analysis pass - the ProX cut is the same
        # edit without the cinema layer (raw_start/raw_end = the pre-cinema window carrying
        # the full non-cinema polish), the B2 cut uses the cinema-snapped bounds; titles,
        # judge verdicts and scores are shared (the judge ran once, on the shared analysis).
        variants = []                      # (moment_index, moment, engine_id, start, end)
        for mi, m in enumerate(moments, start=1):
            if eng in ("prox", "both"):
                variants.append((mi, m, "prox",
                                 m.get("raw_start", m["start"]), m.get("raw_end", m["end"])))
            if eng in ("b2", "both"):
                variants.append((mi, m, "b2", m["start"], m["end"]))

        total = max(len(variants), 1)
        for i, (mi, m, veng, v0, v1) in enumerate(variants):
            _set(job_, stage=f"rendering clip {i + 1}/{total} ({ENGINES[veng]['name']})",
                 progress=64 + int(30 * i / total))
            base = f"{job_id}_{i + 1}"
            clip = _render_clip(job_, src_path, dict(m, start=v0, end=v1), base, clips_dir,
                                engine=veng)
            clip["rank"] = i + 1
            clip["moment"] = mi
            job_["clips"].append(clip)
            save()

        _set(job_, status="done", stage=f"top {len(job_['clips'])} clips ready", progress=96)

        if job_["auto_post"] and job_["clips"]:
            if not rights.cleared(job_):
                # The rights gate. Consent + information, never a bypass: we stop before
                # the first automatic upload and put the question on the Clips screen.
                # Answering it resumes this exact post from resume_autopost().
                _set(job_, rights_pending=True,
                     stage="auto-post paused — confirm your rights on the Clips screen")
            else:
                platforms = ["youtube"] if social.youtube_connected() else []
                assisted = ["tiktok"]  # assisted package is always prepared for TikTok
                targets = platforms + assisted
                for i in range(len(job_["clips"])):
                    _set(job_, status="running", progress=97,
                         stage=f"auto-posting clip {i + 1}/{len(job_['clips'])} → {', '.join(targets)}")
                    social.post_clip(job_, i, targets, on_update=save, wait=True)
                    learning.log("post", job_["clips"][i], job_)

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

        # copyright safety: write the edit receipt now that the clips exist. No source
        # hash here - a receipt is written on every job, and hashing a long video would
        # cost real time; the on-demand receipt (API/CLI) hashes both source and renders.
        try:
            path = rights.write_receipt(job_, hash_source=False)
            if path:
                _set(job_, receipt=path)
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


def render_candidate(job_id, cand_index, style=None, position=None, size_scale=None, engine=None):
    """Render (or re-render) one candidate — a runner-up or a restyle of an existing cut."""
    job_ = JOBS.get(job_id)
    if not job_:
        return None, "unknown job"
    held, why = rights.render_hold(job_)
    if held:
        return None, why
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
        clip = _render_clip(job_, src, cand, base, clips_dir, engine=_variant(job_, engine))
    except Exception as e:
        return None, str(e)[:300]
    clip["rank"] = len(job_["clips"]) + 1
    job_["clips"].append(clip)
    save()
    learning.log("render", clip, job_)
    return clip, None


def render_custom(job_id, start, end, style=None, engine=None):
    """Cut a user-dragged window; it goes through the same honest measurement."""
    job_ = JOBS.get(job_id)
    if not job_:
        return None, "unknown job"
    held, why = rights.render_hold(job_)
    if held:
        return None, why
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
        clip = _render_clip(job_, src, m, base, clips_dir, engine=_variant(job_, engine))
    except Exception as e:
        return None, str(e)[:300]
    clip["rank"] = len(job_["clips"]) + 1
    job_["clips"].append(clip)
    save()
    learning.log("custom", clip, job_)
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
    job_ = JOBS[job_id]
    job_["src"] = src_path
    job_["src_name"] = os.path.basename(src_path)
    job_.pop("rights_hold", None)
    rights.remember_source(job_, path=src_path)      # the registry: where this came from
    held, why = rights.render_hold(job_)
    if held:
        # the strict clearance gate: imported media does not even render until the
        # owner has answered the rights question or recorded an override. Resume
        # happens from resume_render() the moment it is cleared by hand.
        job_.update(status="queued", stage=why, progress=0, rights_hold=True)
        save()
        return job_id
    save()
    threading.Thread(target=process, args=(job_id, src_path), daemon=True).start()
    return job_id


def start_from_url(job_id, url):
    """Download a video from a URL (YouTube via yt-dlp, or a direct media link),
    then run the normal pipeline on it."""
    from . import ingest

    job_ = JOBS[job_id]
    job_.pop("rights_hold", None)
    rights.remember_source(job_, url=url)
    held, why = rights.render_hold(job_)
    if held:
        job_.update(status="queued", stage=why, progress=0, rights_hold=True)
        save()
        return job_id

    def runner():
        job_ = JOBS[job_id]
        try:
            _set(job_, status="running", stage="downloading video from URL", progress=1)
            src = ingest.download(url, os.path.join(CONFIG["data_dir"], "uploads"))
            JOBS[job_id]["src"] = src
            JOBS[job_id]["src_name"] = os.path.basename(src)
            # source awareness: keep the uploader/video id yt-dlp already reported, so
            # the clip card can name the real source and flag a channel that is not the
            # one connected for posting (a reminder to check your rights, not a verdict)
            info = ingest.info_for(src)
            JOBS[job_id]["source"] = {
                "kind": "youtube" if info.get("id") else "url",
                "url": url,
                "video_id": info.get("id") or "",
                "uploader": info.get("uploader") or info.get("channel") or "",
                "channel": info.get("channel") or "",
                "title": info.get("title") or "",
            }
            rights.remember_source(JOBS[job_id], path=src, url=url)
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


def resume_render(job_id):
    """Start a render the strict clearance gate was holding, now cleared by hand.
    Returns True when the render was (re)started."""
    job_ = JOBS.get(job_id)
    if not job_ or not job_.get("rights_hold"):
        return False
    src = job_.get("src")
    if src and os.path.isfile(src):
        job_["rights_hold"] = False
        save()
        start(job_id, src)
        return True
    url = (job_.get("source") or {}).get("url")
    if url:
        job_["rights_hold"] = False
        save()
        start_from_url(job_id, url)
        return True
    _set(job_, rights_hold=False, status="error", stage="failed",
         error="the held source is no longer on disk - re-import it")
    return False


def stt_mode():
    from .config import stt_mode as resolve
    return resolve()
