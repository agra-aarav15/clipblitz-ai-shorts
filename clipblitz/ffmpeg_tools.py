"""ffmpeg wrappers: probing, audio extraction, speech detection, 9:16 cutting, demo video."""

import json
import math
import os
import re
import subprocess

from .config import ffmpeg, ffprobe


def run(args, timeout=900, cwd=None):
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          errors="replace",  # tool output can carry any byte (smart quotes etc.)
                          timeout=timeout, cwd=cwd)
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


def scene_cuts(video, threshold=0.30):
    """Camera/scene change timestamps — the visual second pair of eyes. Peaks in
    cut-rate coincide with action (battles, goals, reveals) even when the transcript
    is sparse commentary. Returns sorted [t, ...]."""
    try:
        proc = subprocess.run(
            [ffmpeg(), "-i", video, "-vf",
             f"scale=320:-2,select='gt(scene,{threshold})',metadata=print:file=-",
             "-an", "-f", "null", "-"],
            capture_output=True, text=True, errors="replace", timeout=900)
        return sorted(float(m) for m in re.findall(r"pts_time:([\d.]+)", proc.stdout))
    except Exception:
        return []


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


def _filtergraph(framing, sub_name, dur=0.0):
    """Vertical reframing filter chains. 'blur' fits the WHOLE frame on a blurred
    background (nothing cut off — default); crop variants cut to 9:16 with a focus.
    Every chain ends with a short fade-in/out so cut edges never feel chopped."""
    fv_in = "fade=t=in:st=0:d=0.18"
    fv_out = f"fade=t=out:st={max(0.0, dur - 0.22):.2f}:d=0.22"
    sub = f",subtitles={sub_name}" if sub_name else ""
    if framing == "crop-left":
        return None, f"crop=ih*9/16:ih:0:0,scale=1080:1920,{fv_in},{fv_out}{sub}"
    if framing == "crop-right":
        return None, f"crop=ih*9/16:ih:(iw-ih*9/16):0,scale=1080:1920,{fv_in},{fv_out}{sub}"
    if framing == "crop":
        return None, f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920,{fv_in},{fv_out}{sub}"
    # blur-pad: full frame visible, background = zoomed blurred copy
    chain = ("[0:v]split=2[bg][fg];"
             "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
             "crop=1080:1920,boxblur=20:5[bgb];"
             "[fg]scale=1080:-2[fgs];"
             f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p,{fv_in},{fv_out}{sub}[v]")
    return chain, None


def _audio_fade(dur):
    return f"afade=t=in:st=0:d=0.15,afade=t=out:st={max(0.0, dur - 0.18):.2f}:d=0.18"


def cut_clip(src, start, end, out, sub_name=None, cwd=None, framing="blur"):
    """Cut [start,end], reframe vertical (default: blur-pad so nobody gets cut off),
    burn subtitles (.ass) if given, polish edges with audio+video fades.
    sub_name is relative to cwd (pass the clips dir)."""
    duration = round(end - start, 2)
    complex_fg, simple_vf = _filtergraph(framing, sub_name, duration)
    af = ["-af", _audio_fade(duration)]
    base = [ffmpeg(), "-y", "-ss", f"{start:.2f}", "-i", src, "-t", f"{duration:.2f}"]
    if complex_fg is not None:
        args = base + ["-filter_complex", complex_fg, "-map", "[v]", "-map", "0:a?", *af,
                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                       "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    else:
        args = base + ["-vf", simple_vf, "-map", "0:a?", *af,
                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                       "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    try:
        run(args, cwd=cwd)
    except RuntimeError:
        if sub_name:  # libass missing / subtitle parse issue — retry WITHOUT captions
            complex_fg2, simple_vf2 = _filtergraph(framing, None, duration)
            if complex_fg2 is not None:
                args = base + ["-filter_complex", complex_fg2, "-map", "[v]", "-map", "0:a?", *af,
                               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
            else:
                args = base + ["-vf", simple_vf2, "-map", "0:a?", *af,
                               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
            run(args, cwd=cwd)
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
