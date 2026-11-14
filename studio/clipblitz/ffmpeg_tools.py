"""ffmpeg wrappers: probing, audio extraction, speech detection, 9:16 cutting, demo video."""

import json
import math
import os
import re
import subprocess
from collections import Counter

from .config import ffmpeg, ffprobe
from . import cinema


def run(args, timeout=900, cwd=None):
    try:
        proc = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                              errors="replace",  # tool output can carry any byte (smart quotes etc.)
                              timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired as e:
        tail = (e.stderr or "")
        if isinstance(tail, bytes):
            tail = tail.decode("utf-8", "replace")
        raise RuntimeError(
            f"ffmpeg timed out after {timeout}s while encoding this clip. "
            f"The source is long or runs at a high frame rate; try a shorter clip. "
            f"{tail[-300:]}") from None
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-500:]}")
    return proc


def available():
    try:
        run([ffmpeg(), "-version"], timeout=20)
        return True
    except Exception:
        return False


def duration_of(path):
    out = run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]).stdout
    try:
        return float(json.loads(out)["format"]["duration"])
    except (KeyError, ValueError):
        raise RuntimeError(
            "This file can't be read as a video. If it's a download, it's probably "
            "incomplete (the MP4 index is missing) — re-download it and try again."
        )


def is_readable(path):
    try:
        duration_of(path)
        return True
    except Exception:
        return False


def extract_audio(video, wav):
    run([ffmpeg(), "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav], timeout=600)


def speech_segments(wav):
    """Detect speech blocks by inverting silence detection (works fully offline)."""
    proc = subprocess.run(
        [ffmpeg(), "-i", wav, "-af", "silencedetect=noise=-35dB:d=0.6", "-f", "null", "-"],
        capture_output=True, text=True, timeout=600,
    )
    text = proc.stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", text)]
    total = duration_of(wav)

    # invert silences into speech segments
    silences = list(zip(starts, [e for e in ends]))
    segments, cursor = [], 0.0
    for s, e in silences:
        if s - cursor > 1.0:
            segments.append({"start": round(cursor, 2), "end": round(s, 2)})
        cursor = e
    if total - cursor > 1.0:
        segments.append({"start": round(cursor, 2), "end": round(total, 2)})
    return segments or [{"start": 0.0, "end": round(total, 2)}]


def _video_codec(video):
    try:
        proc = subprocess.run(
            [ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name", "-of", "csv=p=0", video],
            capture_output=True, text=True, timeout=20)
        return proc.stdout.strip().splitlines()[0].lower()
    except (OSError, IndexError, subprocess.SubprocessError):
        return ""


def _keyframe_marks(video):
    """Real decoder keyframe timestamps, read from the container in milliseconds.

    Encoders put keyframes on scene changes, so they are a usable edit-point proxy.
    This is the only fast path on codecs whose decoder ignores -skip_frame nokey:
    a 50 fps AV1 source decoded every frame for 16 minutes before this existed."""
    try:
        proc = subprocess.run(
            [ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
             "packet=pts_time,flags", "-of", "csv=p=0", video],
            capture_output=True, text=True, errors="replace", timeout=90)
    except (OSError, subprocess.SubprocessError):
        return []
    marks = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2 or "K" not in parts[1].upper():
            continue
        try:
            t = float(parts[0])
        except ValueError:
            continue
        if t > 0.5:
            marks.append(round(t, 3))
    return sorted(set(marks))


def scene_cuts(video, threshold=0.30):
    """Camera/scene change timestamps — the visual second pair of eyes. Peaks in
    cut-rate coincide with action (battles, goals, reveals) even when the transcript
    is sparse commentary. Returns sorted [t, ...].

    AV1/VP9 decoding ignores -skip_frame nokey in the bundled build, so those codecs
    use the container's real keyframe marks instead of a full decode. Other codecs
    keep the scene-diff scan, capped so one slow file cannot stall a job for 15
    minutes; on timeout the keyframes are the fallback, not an empty list."""
    if _video_codec(video) in ("av1", "vp9"):
        marks = _keyframe_marks(video)
        if marks:
            return marks
    try:
        proc = subprocess.run(
            [ffmpeg(), "-skip_frame", "nokey", "-i", video, "-vf",
             f"select='gt(scene,{max(0.10, float(threshold) * 0.4)})',metadata=print:file=-",
             "-an", "-sn", "-f", "null", "-"],
            capture_output=True, text=True, errors="replace", timeout=240)
        return sorted(float(m) for m in re.findall(r"pts_time:([\d.]+)", proc.stdout))
    except Exception:
        return _keyframe_marks(video)


def _video_size(path):
    try:
        proc = subprocess.run(
            [ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=p=0:s=x", path],
            capture_output=True, text=True, timeout=20)
        w, h = (int(v) for v in proc.stdout.strip().split("x")[:2])
        return w, h
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0, 0


def detect_active_area(video, samples=4, seconds=2.0):
    """Measure the real picture rectangle inside a pillarboxed/letterboxed source.

    Returns (left, top, right, bottom) as fractions of the frame, or None when the
    source already uses the full frame. cropdetect on a few short samples; the most
    common rectangle wins because a single dark shot can report a false border.
    A crop is only trusted when it is plausible (>=50% of the frame).
    """
    sw, sh = _video_size(video)
    if not sw or not sh:
        return None
    try:
        dur = duration_of(video)
    except Exception:
        dur = 0.0
    if dur <= 0:
        return None
    found = []
    for frac in (0.08, 0.30, 0.55, 0.80):
        off = max(0.0, dur * frac - seconds / 2)
        try:
            proc = subprocess.run(
                [ffmpeg(), "-hide_banner", "-nostats", "-ss", f"{off:.2f}",
                 "-t", f"{seconds:.1f}", "-i", video,
                 "-vf", "cropdetect=24:2:0", "-an", "-sn", "-f", "null", "-"],
                capture_output=True, text=True, errors="replace", timeout=90)
        except (OSError, subprocess.SubprocessError):
            continue
        hits = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", proc.stderr)
        if hits:
            found.append(tuple(int(v) for v in hits[-1]))
    if not found:
        return None
    w, h, x, y = Counter(found).most_common(1)[0][0]
    if w <= 0 or h <= 0 or w < sw * 0.5 or h < sh * 0.5:
        return None
    if x < 0 or y < 0 or x + w > sw + 1 or y + h > sh + 1:
        return None
    if w >= sw * 0.995 and h >= sh * 0.995:
        return None
    left, top = x / float(sw), y / float(sh)
    right, bottom = (x + w) / float(sw), (y + h) / float(sh)
    hbar = left >= 0.015 or right <= 0.985
    vbar = top >= 0.015 or bottom <= 0.985
    # Only a centred pillarbox or letterbox may be treated as a bar. A dark studio
    # background is also "black" to cropdetect (the Raj Shamani set reports a 36%
    # left band and a 20% top band); cropping that away would delete the subject.
    # Require one axis only and near-symmetry, otherwise keep the full frame.
    if hbar and not vbar:
        if abs(left - (1.0 - right)) > 0.02:
            return None
    elif vbar and not hbar:
        if abs(top - (1.0 - bottom)) > 0.02:
            return None
    else:
        return None
    return (round(left, 4), round(top, 4), round(right, 4), round(bottom, 4))


def loudness_profile(wav, bucket=0.5):
    """Per-bucket RMS loudness (dBFS) for the virality engine's energy factor.
    Returns (series, mean_db): series is a list of (t_mid, rms_db) samples."""
    proc = subprocess.run(
        [ffmpeg(), "-i", wav, "-af",
         f"astats=metadata=1:reset={max(1, int(bucket * 64))},"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=900,
    )
    series, t = [], None
    for line in proc.stdout.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"RMS_level=(-?[\d.]+|-inf)", line)
        if m and t is not None:
            raw = m.group(1)
            db = -90.0 if raw == "-inf" else float(raw)
            series.append((t, db))
    mean_db = sum(db for _, db in series) / len(series) if series else -30.0
    return series, mean_db


def _srt_time(t):
    ms = int(round((t - math.floor(t)) * 1000))
    s = int(t)
    return f"{s // 3600:02}:{(s % 3600) // 60:02}:{s % 60:02},{ms:03}"


def write_srt(path, entries):
    """entries: [{start, end, text}] — times relative to the clip."""
    with open(path, "w", encoding="utf-8") as f:
        for i, e in enumerate(entries, 1):
            f.write(f"{i}\n{_srt_time(e['start'])} --> {_srt_time(e['end'])}\n{e['text']}\n\n")


STYLE = "force_style='Fontsize=13,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=48'"


def _video_stream_index(src):
    """Pick the real moving video stream, not a cover-art still in stream 0."""
    try:
        out = run([ffprobe(), "-v", "error", "-select_streams", "v",
                   "-show_streams", "-of", "json", src], timeout=20).stdout
        streams = json.loads(out).get("streams") or []
        best, best_score = 0, -1
        for st in streams:
            idx = int(st.get("index", 0))
            try:
                frames = int(st.get("nb_frames") or 0)
            except (TypeError, ValueError):
                frames = 0
            try:
                dur = float(st.get("duration") or 0)
            except (TypeError, ValueError):
                dur = 0.0
            codec = str(st.get("codec_name") or "").lower()
            score = (1 if frames > 1 else 0) + (1 if dur > 0.1 else 0) +                     (1 if codec not in ("mjpeg", "png", "bmp") else 0)
            if score > best_score:
                best, best_score = idx, score
        return best
    except Exception:
        return 0


def _focus_x_expr(path, active=None):
    """Build a per-frame crop-x expression from [(t, centre_fraction), ...].

    The expression is piecewise linear and clamped to the source. When ``active`` is
    the detected picture rectangle (left, top, right, bottom as fractions), the crop
    is also clamped inside it so a pillarboxed source never contributes black bars.
    Commas inside the expression are escaped because ffmpeg's filter parser uses
    commas as separators.
    """
    if not path:
        return None
    lo, hi = (0.0, 1.0)
    if active:
        lo, hi = max(0.0, min(1.0, float(active[0]))), min(1.0, float(active[2]))

    def x(frac):
        desired = f"iw*{float(frac):.4f}-ih*9/32"
        if active and hi > lo:
            left, right = f"iw*{lo:.4f}", f"iw*{hi:.4f}-ih*9/16"
            inside = (f"if(gt({left}\\,{right})\\,"
                      f"max(0\\,min(iw-ih*9/16\\,iw*{(lo + hi) / 2:.4f}-ih*9/32))\\,"
                      f"max({left}\\,min({right}\\,{desired})))")
            return inside
        return f"max(0\\,min(iw-ih*9/16\\,{desired}))"

    expr = x(path[-1][1])
    for (t0, f0), (t1, f1) in reversed(list(zip(path, path[1:]))):
        if t1 <= t0:
            continue
        seg = (f"({x(f0)}+({x(f1)}-{x(f0)})*"
               f"(t-{float(t0):.3f})/{float(t1 - t0):.3f})")
        expr = f"if(lt(t\\,{float(t1):.3f})\\,{seg}\\,{expr})"
    return expr


def _filtergraph(framing, sub_name, dur=0.0, grade_film=False, grain=False, ratio="9:16",
                 crop_x=None, vignette=True, auto_zoom=False, focus_path=None,
                 vsrc="0:v", active=None):
    """Vertical reframing filter chains. 'focus' is a full-height 9:16 crop that
    follows the subject; 'blur' fits the whole frame on a blurred background; crop
    variants cut to 9:16 with a fixed focus. Every chain ends with a short fade.

    ``active`` is the measured picture rectangle inside a pillarboxed/letterboxed
    source. Crops are clamped inside it; the current shot's subject is never
    replaced by the source's black bar."""
    lo, hi = (0.0, 1.0)
    if active:
        lo, hi = max(0.0, min(1.0, float(active[0]))), min(1.0, float(active[2]))
    safe_frac = max(0.01, hi - lo)

    def fixed_x(value):
        value = max(0, int(value))
        if not active:
            return f"min({value}\\,iw-ow)"
        left, right = f"iw*{lo:.4f}", f"iw*{hi:.4f}-ow"
        return (f"if(gt({left}\\,{right})\\,"
                f"max(0\\,min(iw-ow\\,iw*{(lo + hi) / 2:.4f}-ow/2))\\,"
                f"max({left}\\,min({right}\\,{value})))")
    fv_in = "fade=t=in:st=0:d=0.18"
    # The tail pad is where the picture should breathe; a 0.12s fade is enough to
    # avoid a hard pop without turning the last beat black.
    fv_out = f"fade=t=out:st={max(0.0, dur - 0.12):.2f}:d=0.12"
    sub = f",subtitles={sub_name}" if sub_name else ""
    grade = (f",{cinema.cinematic_filters(grain=grain, vignette=vignette)}"
             if grade_film else "")
    W, H = cinema.ratio_size(ratio)
    zoom = (f",zoompan=z='min(zoom+0.0004,1.05)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30" if auto_zoom else "")
    active_w = f"min(iw*{safe_frac:.4f}\\,ih*9/16)" if active else "min(iw\\,ih*9/16)"
    if framing == "crop-left":
        x = f"iw*{lo:.4f}" if active else "0"
        return None, (f"crop=w={active_w}:h=min(ih\\,iw*16/9):x={x}:y=(ih-oh)/2,"
                      f"scale={W}:{H},fps=30{zoom},{fv_in},{fv_out}{grade}{sub}")
    if framing == "crop-right":
        x = f"iw*{hi:.4f}-ow" if active else "iw-ow"
        return None, (f"crop=w={active_w}:h=min(ih\\,iw*16/9):x={x}:y=(ih-oh)/2,"
                      f"scale={W}:{H},fps=30{zoom},{fv_in},{fv_out}{grade}{sub}")
    if framing in ("crop", "auto"):
        if framing == "auto" and focus_path:
            x = _focus_x_expr(focus_path, active)
        else:
            x = ("(iw-ow)/2" if crop_x is None else fixed_x(crop_x))
            if active and crop_x is None:
                x = f"iw*{(lo + hi) / 2:.4f}-ow/2"
        return None, (f"crop=w={active_w}:h=min(ih\\,iw*16/9):x={x}:y=(ih-oh)/2,"
                      f"scale={W}:{H},fps=30{zoom},{fv_in},{fv_out}{grade}{sub}")
    if framing == "focus":
        x = _focus_x_expr(focus_path, active) or (
            f"iw*{(lo + hi) / 2:.4f}-ow/2" if active else "(iw-ow)/2")
        # min() keeps a portrait source from asking for a crop wider than the frame.
        return None, (f"crop=w={active_w}:h=min(ih\\,iw*16/9):"
                      f"x={x}:y=(ih-oh)/2,scale={W}:{H},fps=30{zoom},"
                      f"{fv_in},{fv_out}{grade}{sub}")
    # blur-pad: full frame visible, background = a low-resolution blurred copy.
    # Blurring at 1/4 size and scaling back is visually identical here and several
    # times cheaper than boxblur=20:5 on the full 1080x1920 canvas.
    bw, bh = max(2, (W // 4) // 2 * 2), max(2, (H // 4) // 2 * 2)
    chain = (f"[{vsrc}]split=2[bg][fg];"
             f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
             f"crop={W}:{H},scale={bw}:{bh},boxblur=6:2,scale={W}:{H}[bgb];"
             "[fg]scale=%d:-2[fgs];" % W +
             f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p,fps=30{zoom},{fv_in},{fv_out}{grade}{sub}[v]")
    return chain, None


def _audio_fade(dur, lead=0.0):
    """Audio fade in/out. The old audio-lead path is disabled because it delayed
    audio without delaying picture; this function now only fades."""
    return (f"afade=t=in:st=0:d=0.15,"
            f"afade=t=out:st={max(0.0, dur - 0.18):.2f}:d=0.18")


def thumbnail(src, at, out, width=540):
    """One frame from the rendered clip, used as the card poster. Cheap and safe:
    a thumbnail failure never fails the clip."""
    try:
        run([ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0.0, float(at)):.3f}",
             "-i", src, "-frames:v", "1", "-vf", f"scale={int(width)}:-2",
             "-q:v", "3", out], timeout=30)
        return out
    except Exception:
        return None


def cut_clip(src, start, end, out, sub_name=None, cwd=None, framing="focus",
             grade=True, grain=False, ratio="9:16", audio_lead=0.0, crop_x=None,
             vignette=True, auto_zoom=False, focus_path=None, active=None):
    """Cut [start,end], reframe vertical (default: focus crop that follows the
    subject), burn subtitles (.ass) if given, polish edges with audio+video fades.
    sub_name is relative to cwd (pass the clips dir)."""
    duration = round(end - start, 2)
    vsrc = f"0:{_video_stream_index(src)}"
    complex_fg, simple_vf = _filtergraph(framing, sub_name, duration,
                                         grade_film=grade, grain=grain, ratio=ratio,
                                         crop_x=crop_x, vignette=vignette,
                                         auto_zoom=auto_zoom, focus_path=focus_path,
                                         vsrc=vsrc, active=active)
    # The old J-cut delayed audio without delaying picture, which put sound 350 ms
    # late. It is disabled until a real audio-lead graph (with caption shift) exists.
    lead = 0.0
    af = ["-af", _audio_fade(duration)]
    if lead > 0.01:
        # pull the picture a touch later so the audio (which starts at -ss start-lead) is already
        # running when the picture appears — the incoming cut "leads" with sound
        af = ["-af", f"adelay={int(lead * 1000)}|{int(lead * 1000)}," + _audio_fade(duration + lead)]
    base = [ffmpeg(), "-y", "-ss", f"{max(0.0, start - lead):.2f}", "-i", src,
            "-t", f"{(duration + lead):.2f}"]
    if complex_fg is not None:
        args = base + ["-filter_complex", complex_fg, "-map", "[v]", "-map", "0:a?", *af,
                       "-c:v", "libx264", "-preset", "superfast", "-crf", "25",
                       "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    else:
        args = base + ["-vf", simple_vf, "-map", vsrc, "-map", "0:a?", *af,
                       "-c:v", "libx264", "-preset", "superfast", "-crf", "25",
                       "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    try:
        run(args, cwd=cwd, timeout=max(900, int((duration + lead) * 12)))
    except RuntimeError:
        if sub_name:  # libass missing / subtitle parse issue — retry WITHOUT captions
            complex_fg2, simple_vf2 = _filtergraph(framing, None, duration,
                                                   grade_film=grade, grain=grain, ratio=ratio,
                                                   crop_x=crop_x, vignette=vignette,
                                                   auto_zoom=auto_zoom,
                                                   focus_path=focus_path, vsrc=vsrc,
                                                   active=active)
            if complex_fg2 is not None:
                args = base + ["-filter_complex", complex_fg2, "-map", "[v]", "-map", "0:a?", *af,
                               "-c:v", "libx264", "-preset", "superfast", "-crf", "25",
                               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
            else:
                args = base + ["-vf", simple_vf2, "-map", vsrc, "-map", "0:a?", *af,
                               "-c:v", "libx264", "-preset", "superfast", "-crf", "25",
                               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
            run(args, cwd=cwd, timeout=max(900, int((duration + lead) * 12)))
            return out + " (captions skipped: libass burn failed)"
        raise
    return out


DEMO_SCRIPT = (
    "Here is the secret nobody tells you about going viral. "
    "The first three seconds decide everything. If your hook is weak, nothing else matters. "
    "Test it yourself. Watch how long people stay when the opening asks a real question. "
    "Now, the second rule. Cut the boring parts. Every pause, every um, every slow intro is a scroll. "
    "The best clips are complete stories. A question, a tension, and a payoff. Nothing else survives. "
    "Third rule. Captions are not optional. Most people watch on mute. "
    "Word by word captions can double your watch time, and watch time is the algorithm's favorite food. "
    "And the last rule. Post consistently, study your own numbers, and let the data pick your next topic. "
    "That is the whole playbook. Simple, but almost nobody does it every single day."
)


def _demo_voice(wav_path):
    """Windows SAPI (COM) TTS → real spoken narration for the demo (offline, no deps)."""
    import base64
    ps = (
        "$voice = New-Object -ComObject SAPI.SpVoice\n"
        "$file = New-Object -ComObject SAPI.SpFileStream\n"
        f"$file.Open('{wav_path}', 3, $false)\n"
        "$voice.AudioOutputStream = $file\n"
        "$voice.Rate = 1\n"
        "$voice.Speak(@'\n" + DEMO_SCRIPT + "\n'@)\n"
        "$file.Close()\n"
    )
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                       capture_output=True, timeout=300)
        return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 100000
    except Exception:
        return False


def excitement_peaks(series, mean_db, top_frac=0.30, merge_gap=6.0):
    """Crowd/engine ROAR peaks: where loudness runs hot well above the video's own
    baseline. For a race this is the battle, the overtake, the win — commentary is
    sparse there, but the audio never lies. Returns [(start, end, heat)] regions,
    strongest last."""
    if len(series) < 8:
        return []
    dbs = sorted(db for _, db in series)
    thresh = dbs[max(0, int(len(dbs) * (1.0 - top_frac)))]
    raw, cur = [], None
    for t, db in series:
        if db >= thresh:
            if cur is None:
                cur = [t, t, db - mean_db]
            else:
                cur[1] = t
                cur[2] = max(cur[2], db - mean_db)
        else:
            if cur:
                raw.append(cur)
            cur = None
    if cur:
        raw.append(cur)
    merged = []
    for r in raw:
        if merged and r[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = r[1]
            merged[-1][2] = max(merged[-1][2], r[2])
        else:
            merged.append(r)
    return [(round(a, 2), round(b, 2), round(h, 2)) for a, b, h in merged if b - a >= 4.0]


def laughter_regions(wav, base_wav=None):
    """Detect audience/panel laughter acoustically — the strongest viral signal for
    comedy/podcast content. Method: band-pass 300-6000 Hz (speech/laughter band),
    loudness delta vs the rolling baseline, moderate zero-crossing rate. Returns
    [(start, end, peak_db_delta)] merged into regions > 0.8s.
    base_wav: another wav whose overall mean anchors the delta (optional)."""
    proc = subprocess.run(
        [ffmpeg(), "-i", wav, "-af",
         "highpass=f=300,lowpass=f=6000,astats=metadata=1:reset=32,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True, errors="replace", timeout=900,
    )
    series, t = [], None
    for line in proc.stdout.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"RMS_level=(-?[\d.]+|-inf)", line)
        if m and t is not None:
            raw = m.group(1)
            db = -90.0 if raw == "-inf" else float(raw)
            series.append((t, db))
    if len(series) < 8:
        return []
    ref = base_wav if base_wav else wav
    _, mean_db = loudness_profile(ref)
    # laughter = energy bursts clearly above the video's own baseline
    thresh = mean_db + 7.0
    raw_regions, cur = [], None
    for t, db in series:
        if db > thresh:
            if cur is None:
                cur = [t, t, db - mean_db]
            else:
                cur[1] = t
                cur[2] = max(cur[2], db - mean_db)
        else:
            if cur and cur[1] - cur[0] >= 0.8:
                raw_regions.append(tuple(cur))
            cur = None
    if cur and cur[1] - cur[0] >= 0.8:
        raw_regions.append(tuple(cur))
    # merge regions separated by < 1.5s (laughter comes in waves)
    merged = []
    for r in raw_regions:
        if merged and r[0] - merged[-1][1] < 1.5:
            merged[-1] = (merged[-1][0], r[1], max(merged[-1][2], r[2]))
        else:
            merged.append(r)
    return merged


def laughter_score(wav_regions, a, b):
    """0-1: how much detected laughter falls inside/at a candidate window [a,b]."""
    if not wav_regions:
        return 0.0
    total = 0.0
    for s, e, peak in wav_regions:
        overlap = min(b, e + 1.0) - max(a, s)  # +1s: the reaction trailing the joke counts
        if overlap > 0:
            weight = min(1.0, peak / 12.0)      # louder burst vs baseline → stronger
            total += overlap * weight
    window = max(1.0, b - a)
    return min(1.0, total / (window * 0.35))    # ~35% laugh coverage ≈ saturated


def make_demo_video(out, dur=96):
    """Test source. Real spoken narration when Windows SAPI is available (so Whisper,
    captions and scoring all run on genuine speech); tone cycles as fallback."""
    import tempfile
    voice = os.path.join(tempfile.gettempdir(), "clipblitz_demo_voice.wav")
    if _demo_voice(voice):
        run([ffmpeg(), "-y",
             "-f", "lavfi", "-i", f"testsrc2=size=720x1280:rate=30:duration={dur}",
             "-i", voice, "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", out], timeout=300)
        return
    audio = (
        "aevalsrc=if(lt(mod(t\\,8)\\,5)\\,0.4*sin(880*2*PI*t)\\,0):s=44100:d=%d" % dur
    )
    run([ffmpeg(), "-y",
         "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={dur}",
         "-f", "lavfi", "-i", audio,
         "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out],
        timeout=120)
