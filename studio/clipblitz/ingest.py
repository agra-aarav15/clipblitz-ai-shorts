"""Video ingestion: paste a YouTube (or any supported site) URL → yt-dlp,
or a direct media link (.mp4 etc.) → plain download. stdlib + bundled yt-dlp.

Same video URLs are cached by video id — re-running a link never re-downloads 1 GB.
"""

import glob
import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.request

from .config import ffmpeg, ytdlp

MEDIA_RE = re.compile(r"\.(mp4|mov|mkv|webm|m4v|avi)(\?|#|$)", re.I)
MEDIA_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")


def _pick_downloaded(hits):
    """The video among yt-dlp's outputs — chosen by extension, never by name order.

    yt-dlp writes a `.info.json` metadata sidecar (and, mid-download, `.part` /
    `.ytdl` files) next to the media, and alphabetically `.info.json` sorts BEFORE
    `.mp4`. Picking `sorted(hits)[0]` therefore handed ffmpeg the metadata file and
    every such job died at the probe with "Invalid data found when processing input".
    """
    return next((h for h in hits if h.lower().endswith(MEDIA_EXTS)), None)


def _cache_key(url):
    """Stable per-video key: the YouTube video id when the link is one, else the URL hash."""
    m = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/))([\w-]{6,})", url)
    if m:
        return "yt_" + m.group(1)
    return "u_" + hashlib.md5(url.encode()).hexdigest()[:12]


def download(url, dest_dir):
    if not re.match(r"^https?://", url or ""):
        raise RuntimeError("Give a full video URL starting with http(s)://")
    os.makedirs(dest_dir, exist_ok=True)
    if MEDIA_RE.search(url):
        return _direct(url, dest_dir)
    return _ytdlp(url, dest_dir)


def _direct(url, dest_dir):
    name = re.sub(r"[^\w.-]", "_", url.split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1] or "video.mp4")
    dest = os.path.join(dest_dir, f"{int(time.time())}_{name}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ClipBlitz/0.2)"})
    with urllib.request.urlopen(req, timeout=900) as res, open(dest, "wb") as f:
        while True:
            chunk = res.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return dest


def info_for(video_path):
    """The yt-dlp metadata sidecar for a downloaded video ({} when there is none).

    yt-dlp already fetched this during the download - we only ask it to write the
    info JSON next to the file, so source awareness costs no extra network call.
    """
    if not video_path:
        return {}
    side = os.path.splitext(video_path)[0] + ".info.json"
    try:
        data = json.load(open(side, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data.get(k) for k in ("id", "title", "uploader", "channel",
                                     "uploader_id", "webpage_url", "duration")}


def _existing_cached(dest_dir, tag):
    """A finished, readable download for this video from an earlier attempt?"""
    for hit in sorted(glob.glob(os.path.join(dest_dir, f"{tag}_*.*"))):
        if not hit.lower().endswith(MEDIA_EXTS):      # never the .info.json sidecar
            continue
        from . import ffmpeg_tools
        if ffmpeg_tools.is_readable(hit):
            return hit
    return None


# ---------------------------------------------------------------- YouTube captions
#
# yt-dlp writes the timed captions next to the video. YouTube's json3 form carries
# word offsets, so the same word-level data the caption renderer needs comes from
# the source instead of a paid/rate-limited speech API. VTT/SRT are the fallback
# (words are distributed inside each cue when the file has no word timings).

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")


def _seconds(hours, minutes, seconds, frac):
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(frac.ljust(3, "0")) / 1000.0


def _clean_text(value):
    value = html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))
    return re.sub(r"\s+", " ", value).strip()


def parse_json3(path):
    """YouTube json3 -> [{word, start, end}, ...]."""
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    words = []
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        base = float(event.get("tStartMs") or 0) / 1000.0
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        segs = [s for s in (event.get("segs") or []) if isinstance(s, dict)]
        starts = []
        for seg in segs:
            offset = float(seg.get("tOffsetMs") or 0) / 1000.0
            starts.append(base + offset)
        for i, seg in enumerate(segs):
            text = _clean_text(seg.get("utf8"))
            if not text:
                continue
            start = starts[i]
            end = starts[i + 1] if i + 1 < len(starts) else base + duration
            if end <= start:
                end = start + max(0.2, duration / max(1, len(segs)))
            words.append({"word": text, "start": round(start, 3), "end": round(end, 3)})
    return _merge_words(words)


def _parse_cue_time(line):
    m = _TS.search(line.split("-->")[0])
    if not m:
        return None
    return _seconds(*m.groups())


def parse_vtt(path):
    """WebVTT/SRT -> words. Per-word cue tags are used when present; otherwise the
    cue's words share its span evenly (the renderer only needs the spoken window)."""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    words = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        arrow = next((ln for ln in lines if "-->" in ln), "")
        if not arrow:
            continue
        start = _parse_cue_time(arrow)
        end = _parse_cue_time(arrow.split("-->", 1)[1]) if "-->" in arrow else None
        if start is None or end is None or end <= start:
            continue
        body = " ".join(ln for ln in lines if "-->" not in ln and not ln.strip().isdigit())
        body = _clean_text(body)
        if not body:
            continue
        tokens = body.split()
        step = (end - start) / max(1, len(tokens))
        for i, token in enumerate(tokens):
            words.append({"word": token, "start": round(start + i * step, 3),
                          "end": round(start + (i + 1) * step, 3)})
    return _merge_words(words)


def _merge_words(words):
    """Sorted, de-duplicated words; rolling YouTube captions can repeat a line."""
    out = []
    for w in sorted(words, key=lambda x: (x["start"], x["end"])):
        if w["end"] <= w["start"]:
            continue
        if out and w["start"] < out[-1]["start"] - 0.01:
            continue
        if out and w["word"].strip().lower() == out[-1]["word"].strip().lower() \
                and abs(w["start"] - out[-1]["start"]) < 0.05:
            continue
        out.append(w)
    return out


def parse_subtitle(path):
    """Words from a .json3 / .vtt / .srt file, or []."""
    low = path.lower()
    if low.endswith(".json3"):
        return parse_json3(path)
    if low.endswith((".vtt", ".srt")):
        return parse_vtt(path)
    return []


def _preferred_languages(video_path):
    """The source language first, then English. YouTube serves dozens of translated
    caption tracks; choosing the one with the most words picked a Urdu translation of
    an English MrBeast video and made the judge useless."""
    stem = os.path.splitext(video_path)[0]
    prefs = []
    try:
        info = json.load(open(stem + ".info.json", encoding="utf-8"))
        lang = str(info.get("language") or "").split("-")[0].strip().lower()
        if len(lang) >= 2:
            prefs.append(lang)
    except (OSError, ValueError):
        pass
    if "en" not in prefs:
        prefs.append("en")
    return prefs


def _caption_priority(path, prefs):
    """(language rank, original-track rank). Lower wins. A downloaded name looks like
    `...exe.en-orig.json3` or `...exe.ur-pt.json3`; the language is the segment before
    the container extension."""
    name = os.path.basename(path)
    m = re.search(r"\.([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)?)\.(?:json3|vtt|srt)$", name)
    lang = (m.group(1) if m else "").lower().replace("_", "-")
    base = lang.split("-")[0]
    try:
        rank = prefs.index(base)
    except ValueError:
        rank = len(prefs)
    original = 0 if "orig" in lang else 1
    return (rank, original)


def captions_for(video_path):
    """Timed segments from the source's downloaded captions, or [] when there are
    none (or they are too thin to trust).

    Prefer the source language (from the yt-dlp info sidecar), then English, then an
    original track over a translation, and only then the richest track. A translation
    with more words is not a better transcript: the judge must read what was said.
    """
    if not video_path:
        return []
    stem = os.path.splitext(video_path)[0]
    prefs = _preferred_languages(video_path)
    candidates = []
    for ext in ("json3", "vtt", "srt"):
        candidates += sorted(glob.glob(stem + ".*." + ext))
    ranked = []
    for path in candidates:
        words = parse_subtitle(path)
        if len(words) < 20:
            continue
        try:
            from . import stt
            segments = stt._segments_from_words(words)
        except Exception:
            segments = [{"start": words[0]["start"], "end": words[-1]["end"],
                         "text": " ".join(w["word"] for w in words), "words": words}]
        if len(segments) < 3:
            continue
        ranked.append((_caption_priority(path, prefs), len(words), path, segments))
    if not ranked:
        return []
    ranked.sort(key=lambda row: (row[0], -row[1]))
    return ranked[0][3]


def _ytdlp(url, dest_dir):
    tag = _cache_key(url)
    cached = _existing_cached(dest_dir, tag)
    if cached:
        return cached

    stamp = int(time.time())
    tpl = os.path.join(dest_dir, f"{tag}_{stamp}_%(title).60s.%(ext)s")
    ffdir = os.path.dirname(ffmpeg())

    attempts = [
        [],  # default player clients first
        ["--extractor-args", "youtube:player_client=default,android,web_safari"],  # bot-check workaround
    ]
    last_err = None
    for extra in attempts:
        # Prefer H.264 at 1080p. YouTube otherwise serves AV1/VP9, which the
        # bundled ffmpeg decodes far more slowly (and older essentials builds
        # have no dav1d at all). The clip renderer only needs 1080p.
        # Captions are optional: a 429 on one subtitle language must never abort
        # the video download. Without --ignore-errors yt-dlp exits and the job dies
        # before the transcript fallback can run.
        cmd = [ytdlp(), "--no-playlist", "--no-warnings", "--ignore-errors",
               "-S", "vcodec:h264,res:1080,acodec:aac",
               "-f", "bv*+ba/b", "--merge-output-format", "mp4",
               "--write-info-json",
               # YouTube already has a timed transcript for most videos. Fetching it
               # means the link->clips path needs no speech-to-text API at all.
               "--write-subs", "--write-auto-subs",
               "--sub-langs", "en.*,hi.*,ur.*,en,hi,ur",
               "--sub-format", "json3/vtt/best",
               "-o", tpl]
        if ffdir:
            cmd += ["--ffmpeg-location", ffdir]
        cmd += extra
        cmd.append(url)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=3600)
        except FileNotFoundError:
            raise RuntimeError("yt-dlp not found — put yt-dlp.exe in clipblitz/bin/ (see README)")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Download timed out — try a shorter video")
        hits = sorted(glob.glob(os.path.join(dest_dir, f"{tag}_{stamp}_*.*")))
        video = _pick_downloaded(hits)
        # A caption 429 makes yt-dlp exit non-zero even though the video itself
        # finished. If a video file is here, take it; a truncated file fails the
        # pipeline's probe with its own clear error.
        if video and (proc.returncode == 0 or os.path.getsize(video) > 1024 * 1024):
            return video
        if proc.returncode == 0:
            raise RuntimeError("Download finished but no video file was produced")
        last_err = (proc.stderr or "").strip().splitlines()[-3:]

    joined = " | ".join(last_err or ["yt-dlp error"])
    if "Sign in to confirm" in joined or "bot" in joined.lower():
        joined += (" — YouTube wants proof you're human for this link. Opening/using the video in a "
                   "browser once, or adding cookies, fixes it; private/age-restricted videos need cookies.")
    raise RuntimeError("Download failed: " + joined)
