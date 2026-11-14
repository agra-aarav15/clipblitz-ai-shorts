"""Real-media verification - run ARGON end to end on a local video.

This is the local-media counterpart to the offline suites. It uses the real
pipeline (ffmpeg, speech-to-text, editor, judge, render) and writes a JSON report
with wall time per stage and per clip.

    python scripts/verify_media.py --video "data/uploads/tv.mp4" --label tv
    python scripts/verify_media.py --video a.mp4 --video b.mp4 --label-set bench

It never publishes anything and never touches the owner's jobs: pass --data to a
throwaway directory and every artifact is written there. It requires provider keys
(or a local server) for the editor/judge; without them it still runs the measured
path and says so honestly.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)


def _probe(path):
    from clipblitz.config import ffprobe
    args = [ffprobe(), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-show_entries", "format=duration,size", "-of", "json", path]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    audio = subprocess.run(
        [ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name", "-of", "json", path],
        capture_output=True, text=True, timeout=60)
    try:
        has_audio = bool((json.loads(audio.stdout or "{}").get("streams") or []))
    except ValueError:
        has_audio = False
    try:
        num, den = (stream.get("r_frame_rate") or "0/1").split("/")
        fps = round(float(num) / float(den), 3) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    try:
        duration = round(float(fmt.get("duration") or 0.0), 2)
        size = round(float(fmt.get("size") or 0) / 1048576.0, 1)
    except (TypeError, ValueError):
        duration, size = 0.0, 0.0
    return {"width": stream.get("width"), "height": stream.get("height"),
            "fps": fps, "duration": duration, "size_mb": size, "audio": has_audio}


def _stage(job):
    return job.get("stage") or ""


def _judge_payload(c, segments):
    """The same payload argon._judge_batch sends, rebuilt from the stored clip.
    Used only by the model cross-check."""
    from clipblitz import argon
    from clipblitz import virality as V
    c = c or {}
    stats = c.get("text_stats") or {}
    return {
        "index": 0, "title": (c.get("title") or "")[:100],
        "duration": round(float(c.get("duration") or 0.0), 1),
        "anchor": c.get("anchor_kind") or "",
        "verbatim": V._text_in(segments, c["start"], c["end"], argon.MAX_SPEAK_CHARS),
        "measured": {
            "hook_speed": c.get("hook_speed", 0.0),
            "energy": (c.get("measured") or {}).get("energy", 0.0),
            "laughter": (c.get("measured") or {}).get("laughter", 0.0),
            "tail_laugh": (c.get("measured") or {}).get("tail_laugh", 0.0),
            "event": (c.get("measured") or {}).get("event", 0.0),
            "words_per_second": stats.get("wps", 0.0),
            "starts_clean": stats.get("starts_clean", True),
            "ends_on_sentence": stats.get("ends_final", True),
            "shot_cuts_inside": stats.get("scenes", 0),
            "context_dependency": stats.get("context_dependency", 0.0),
            "list_incomplete": stats.get("list_incomplete", 0.0),
            "boundary": stats.get("boundary", 0.0),
            "opening": stats.get("opening", 0.0),
            "opening_issue": stats.get("opening_issue", ""),
        },
    }


def _crosscheck(job, providers):
    """Ask each named provider the ARGON judge question on the SAME exact clip.
    This is how the model layer is verified, not inferred from the pool's answer."""
    import json as _json
    from clipblitz import argon, brains
    by_name = {b["name"]: b for b in brains.brains()}
    clips = [c for c in (job.get("clips") or []) if c.get("start") is not None]
    segments = job.get("segments") or []
    out = []
    for c in clips:
        row = {"clip": f"{c.get('start')}-{c.get('end')}s", "models": {}}
        payload = [_judge_payload(c, segments)]
        prompt = argon.ARGON_JUDGE_PROMPT.format(
            clips=_json.dumps(payload, ensure_ascii=False))
        for name in providers:
            brain = by_name.get(name)
            if brain is None:
                row["models"][name] = {"error": "not configured"}
                continue
            try:
                text = brains._call_one(brain, {
                    "model": brain.get("model"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.15}, timeout=120)
                data = argon._parse_json(text)
                j = (data.get("judgements") or [{}])[0]
                row["models"][name] = {
                    "label": argon._clean_emotion_label(j.get("emotion_label")),
                    "hook": argon._num(j, "hook"),
                    "payoff": argon._num(j, "payoff"),
                    "coherence": argon._num(j, "coherence"),
                    "retention_3s": argon._num(j, "retention_3s"),
                    "retention_end": argon._num(j, "retention_end"),
                    "alone": bool(j.get("alone", True)),
                    "ends_abrupt": bool(j.get("ends_abrupt", False)),
                    "flags": argon._clean_flags(j.get("flags")),
                    "verdict": str(j.get("verdict") or "")[:160],
                }
            except Exception as e:
                row["models"][name] = {"error": f"{type(e).__name__}: {str(e)[:140]}"}
        out.append(row)
    return out


def run_one(video, label, data_dir, top_n, style, engine="argon", crosscheck=None):
    os.environ["CB_DATA"] = data_dir
    from clipblitz.config import CONFIG
    CONFIG["data_dir"] = data_dir
    from clipblitz import pipeline, argon, brains

    calls = {"count": 0, "by_provider": {}, "failures": []}
    raw = brains._call_one_raw

    def counted(brain, payload, timeout=180, model_override=None):
        try:
            out = raw(brain, payload, timeout=timeout, model_override=model_override)
            calls["count"] += 1
            calls["by_provider"][brain["name"]] = calls["by_provider"].get(brain["name"], 0) + 1
            return out
        except Exception as e:
            calls["failures"].append(f"{brain['name']}: {type(e).__name__}: {str(e)[:120]}")
            raise

    timeline = []
    real_set = pipeline._set
    t0 = time.time()

    def timed_set(job, **kw):
        stage = kw.get("stage")
        if stage and (not timeline or timeline[-1][1] != stage):
            timeline.append((round(time.time() - t0, 2), stage))
        return real_set(job, **kw)

    brains._call_one_raw = counted
    cache_before = {
        "scenes": bool(pipeline._source_cache_path(video, "scenes")
                       and os.path.isfile(pipeline._source_cache_path(video, "scenes"))),
        "active": bool(pipeline._source_cache_path(video, "active")
                       and os.path.isfile(pipeline._source_cache_path(video, "active"))),
    }
    pipeline._set = timed_set
    try:
        job_id = pipeline.new_job(label, style=style, top_n=top_n, engine=engine,
                                  framing="focus", demo=False,
                                  source={"kind": "file", "label": os.path.basename(video)})
        job = pipeline.JOBS[job_id]
        pipeline.process(job_id, os.path.abspath(video))
    finally:
        pipeline._set = real_set
        brains._call_one_raw = raw
    wall = round(time.time() - t0, 2)

    clips = []
    for c in job.get("clips") or []:
        path = os.path.join(data_dir, (c.get("file") or "").lstrip("/\\"))
        info = _probe(path) if os.path.isfile(path) else {}
        clips.append({
            "file": c.get("file"), "title": c.get("title"),
            "start": c.get("start"), "end": c.get("end"),
            "duration": c.get("duration"), "score": c.get("score"),
            "tier": c.get("tier"), "qc": c.get("qc"),
            "emotion": c.get("emotion_label"),
            "flags": c.get("flags") or [],
            "gate": c.get("gate"),
            "verified_trace": argon.verify_score(c),
            "hook_speed": c.get("hook_speed"),
            "tail": c.get("tail"),
            "verdict": c.get("verdict"), "reason": c.get("reason"),
            "render": info,
        })
    dead = [c for c in (job.get("candidates") or [])
            if (c.get("gate") or {}).get("passed") is False]
    models = _crosscheck(job, crosscheck) if crosscheck else []
    return {
        "label": label, "video": os.path.abspath(video), "job": job_id,
        "model_crosscheck": models,
        "status": job.get("status"), "error": job.get("error"),
        "empty_reason": job.get("empty_reason"),
        "wall_s": wall,
        "duration_s": job.get("duration"),
        "mode": job.get("mode"), "content_type": job.get("content_type"),
        "candidates": len(job.get("candidates") or []),
        "candidates_failed_gate": len(dead),
        "clips": clips,
        "timeline": timeline,
        "provider_calls": calls,
        "cache_before": cache_before,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", action="append", required=True,
                    help="local video path (repeatable)")
    ap.add_argument("--label", action="append", default=[],
                    help="label per video (default: file stem)")
    ap.add_argument("--data", default=os.path.join(STUDIO, "data", "verify-media"),
                    help="throwaway data directory")
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--style", default="wordpop")
    ap.add_argument("--crosscheck", default="",
                    help="comma-separated provider names to re-judge the exact clips")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    args.data = os.path.abspath(args.data)
    os.makedirs(args.data, exist_ok=True)
    labels = list(args.label)
    providers = [p.strip() for p in args.crosscheck.split(",") if p.strip()]
    results = []
    for i, video in enumerate(args.video):
        label = labels[i] if i < len(labels) else os.path.splitext(
            os.path.basename(video))[0]
        print(f"\n=== {label}: {video}", flush=True)
        r = run_one(video, label, args.data, args.top_n, args.style,
                    crosscheck=providers)
        results.append(r)
        print(f"  {r['status']}  wall {r['wall_s']}s  dur {r['duration_s']}s  "
              f"candidates {r['candidates']} (gate-failed {r['candidates_failed_gate']})  "
              f"clips {len(r['clips'])}  mode {r['mode']}  type {r['content_type']}", flush=True)
        if r.get("error"):
            print(f"  error: {r['error']}", flush=True)
        if r.get("empty_reason"):
            print(f"  empty: {r['empty_reason']}", flush=True)
        for c in r["clips"]:
            print(f"  clip {c['start']}-{c['end']}s score {c['score']} {c['tier']} "
                  f"{c['qc']} {c['emotion']} render {c['render'].get('width')}x"
                  f"{c['render'].get('height')} {c['render'].get('duration')}s "
                  f"audio={c['render'].get('audio')} trace={c['verified_trace']}",
                  flush=True)
            print(f"    {c['title']!r} | {(c['verdict'] or '')[:110]}", flush=True)
        for row in r.get("model_crosscheck") or []:
            print(f"  model check {row['clip']}:", flush=True)
            for name, m in row["models"].items():
                if m.get("error"):
                    print(f"    {name}: {m['error']}", flush=True)
                else:
                    print(f"    {name}: {m['label']} hook {m['hook']} payoff {m['payoff']} "
                          f"coh {m['coherence']} r3 {m['retention_3s']} "
                          f"end {m['retention_end']} flags {m['flags']} | "
                          f"{m['verdict'][:80]}", flush=True)
        print(f"  stages: " + " -> ".join(f"{t}s {s}" for t, s in r["timeline"]), flush=True)
        print(f"  cache before: {r['cache_before']}", flush=True)
        print(f"  provider calls: {r['provider_calls']['count']} "
              f"{r['provider_calls']['by_provider']}", flush=True)
        for f in r["provider_calls"]["failures"][:6]:
            print(f"    provider note: {f}", flush=True)

    report = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": results}
    out = args.json or os.path.join(args.data, "verify-report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
