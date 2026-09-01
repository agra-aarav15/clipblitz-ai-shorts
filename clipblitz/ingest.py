"""Video ingestion: paste a YouTube (or any supported site) URL → yt-dlp,
or a direct media link (.mp4 etc.) → plain download. stdlib + bundled yt-dlp.

Same video URLs are cached by video id — re-running a link never re-downloads 1 GB.
"""

import glob
import hashlib
import os
import re
import subprocess
import time
import urllib.request

from .config import ffmpeg, ytdlp

MEDIA_RE = re.compile(r"\.(mp4|mov|mkv|webm|m4v|avi)(\?|#|$)", re.I)


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


def _existing_cached(dest_dir, tag):
    """A finished, readable download for this video from an earlier attempt?"""
    for hit in glob.glob(os.path.join(dest_dir, f"{tag}_*.*")):
        if hit.endswith((".part", ".ytdl")):
            continue
        from . import ffmpeg_tools
        if ffmpeg_tools.is_readable(hit):
            return hit
    return None


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
        cmd = [ytdlp(), "--no-playlist", "--no-warnings", "-f", "bv*+ba/b",
               "--merge-output-format", "mp4", "-o", tpl]
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
        if proc.returncode == 0:
            hits = sorted(glob.glob(os.path.join(dest_dir, f"{tag}_{stamp}_*.*")))
            video = next((h for h in hits if not h.endswith((".part", ".ytdl"))), None)
            if not video:
                raise RuntimeError("Download finished but no file was produced")
            return video
        last_err = (proc.stderr or "").strip().splitlines()[-3:]

    joined = " | ".join(last_err or ["yt-dlp error"])
    if "Sign in to confirm" in joined or "bot" in joined.lower():
        joined += (" — YouTube wants proof you're human for this link. Opening/using the video in a "
                   "browser once, or adding cookies, fixes it; private/age-restricted videos need cookies.")
    raise RuntimeError("Download failed: " + joined)
