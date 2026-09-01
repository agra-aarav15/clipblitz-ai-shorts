import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env(path):
    """Tiny .env loader (stdlib) — real environment variables still win."""
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
    except OSError:
        pass


_load_env(os.path.join(ROOT, ".env"))

CONFIG = {
    "port": int(os.environ.get("CB_PORT", "4301")),
    "data_dir": os.environ.get("CB_DATA", os.path.join(ROOT, "data")),
    # AI (OpenAI-compatible) used for virality scoring + captions timing;
    # without a key ClipBlitz falls back to fully-offline heuristics.
    "ai_base": os.environ.get("CB_AI_BASE", "https://api.openai.com/v1"),
    "ai_key": os.environ.get("CB_AI_KEY", ""),
    "ai_model": os.environ.get("CB_AI_MODEL", "gpt-4o-mini"),
    # speech-to-text: auto | api | local | heuristic
    "stt": os.environ.get("CB_STT", "auto"),
    "stt_model": os.environ.get("CB_STT_MODEL", "whisper-1"),
    "whisper_model": os.environ.get("CB_WHISPER_MODEL", "tiny"),
    # v2: clips + social
    "top_n": int(os.environ.get("CB_TOP_N", "3")),
    "privacy": os.environ.get("CB_PRIVACY", "public"),
    "yt_client_id": os.environ.get("CB_YT_CLIENT_ID", ""),
    "yt_client_secret": os.environ.get("CB_YT_CLIENT_SECRET", ""),
}

# locate ffmpeg: env dir → repo bin/ portable download → PATH
_ffdir = os.environ.get("CB_FFMPEG_DIR") or ""
if not _ffdir:
    hits = glob.glob(os.path.join(ROOT, "bin", "ffmpeg*", "bin"))
    _ffdir = hits[0] if hits else ""


def ffmpeg():
    if _ffdir:
        return os.path.join(_ffdir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    return "ffmpeg"  # hope it's on PATH


def ffprobe():
    if _ffdir:
        return os.path.join(_ffdir, "ffprobe.exe" if os.name == "nt" else "ffprobe")
    return "ffprobe"


def ffmpeg_available():
    import subprocess
    try:
        subprocess.run([ffmpeg(), "-version"], capture_output=True, timeout=15)
        return True
    except Exception:
        return False


def ytdlp():
    """Bundled yt-dlp in bin/ wins; fall back to PATH."""
    bundled = os.path.join(ROOT, "bin", "yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if os.path.isfile(bundled):
        return bundled
    return "yt-dlp"


def ytdlp_available():
    import subprocess
    try:
        subprocess.run([ytdlp(), "--version"], capture_output=True, timeout=20)
        return True
    except Exception:
        return False


def stt_mode():
    mode = CONFIG["stt"]
    if mode == "auto":
        if CONFIG["ai_key"]:
            return "api"
        try:
            import faster_whisper  # noqa: F401
            return "local"
        except ImportError:
            return "heuristic"
    return mode
