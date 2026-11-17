"""Live chat spike radar.

The idea is deliberately simple and free:

  watch a YouTube or Twitch live chat continuously
  -> persist every message to disk
  -> find bursts where chat accelerates far above its own baseline
  -> remember a 25s-before / 15s-after window for each burst
  -> when the stream ends, download only those sections and render them vertical

It does not need an API key, an LLM, or a browser session. The live chat is read from
YouTube's public web continuation endpoint (or Twitch's anonymous IRC chat), the
recording is fetched with yt-dlp, and the renderer is the same ffmpeg path the studio
already uses. Twitch is handled from the live DVR window, so no full-stream recording
is needed; the trade-off is that a spike must be rendered before it leaves DVR.

Restart behaviour is the point: state and chat are appended to
``<data>/live/<video_id>/``. If the app or the machine is closed while the stream is
still live, the next boot probes the stream, resumes the watcher, and finalizes if the
stream ended while we were away. If the app was away for the whole stream, the live
chat replay is fetched when available.
"""

from __future__ import annotations

import glob
import html as _html
import json
import os
import re
import socket
import ssl
import statistics
import subprocess
import threading
import time
import urllib.request

from . import captions, ffmpeg_tools, ingest, social, virality
from .config import CONFIG, ffmpeg, ytdlp

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
CLIENT_VERSION = "2.20241115.01.00"
WATCH = "https://www.youtube.com/watch?v={vid}"
CHAT_INITIAL = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
CHAT_REPLAY = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat_replay"

VIDEO_ID_RE = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|live/|shorts/|embed/))"
                         r"([A-Za-z0-9_-]{11})")
TWITCH_RE = re.compile(r"twitch\.tv/([A-Za-z0-9_]{3,25})", re.I)
TWITCH_RESERVED = {"directory", "videos", "settings", "subscriptions", "inventory",
                   "wallet", "drops", "search", "p", "downloads", "turbo"}

DEFAULT_BEFORE = 25.0
DEFAULT_AFTER = 15.0
DEFAULT_MAX_CLIPS = 6

_LOCK = threading.RLock()
_SESSIONS = {}
_THREADS = {}
_LOADED = False
_SPIKE_MAX = 8


# ------------------------------------------------------------------ small utils

def _now():
    return time.time()


def _root():
    return os.path.join(CONFIG["data_dir"], "live")


def _session_dir(vid):
    return os.path.join(_root(), vid)


def _session_path(vid):
    return os.path.join(_session_dir(vid), "session.json")


def _chat_path(vid):
    return os.path.join(_session_dir(vid), "chat.jsonl")


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            out = json.load(f)
        return out if isinstance(out, (dict, list)) else default
    except (OSError, ValueError):
        return default


def _load_sessions(force=False):
    """Load every persisted session once. Never start network work at import time."""
    global _LOADED
    with _LOCK:
        if _LOADED and not force:
            return
        _SESSIONS.clear()
        if os.path.isdir(_root()):
            for name in sorted(os.listdir(_root())):
                data = _read_json(os.path.join(_root(), name, "session.json"), {})
                if isinstance(data, dict) and data.get("video_id"):
                    data.setdefault("clips", [])
                    data.setdefault("spikes", [])
                    _SESSIONS[data["video_id"]] = data
        _LOADED = True


def _save(s):
    _atomic_json(_session_path(s["video_id"]), s)


def _terminal(s):
    return s.get("status") in ("done", "error", "stopped")


def _hm(t):
    t = max(0, int(float(t or 0)))
    h, rem = divmod(t, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _clean(value, limit=500):
    value = _html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _runs_text(obj):
    if not isinstance(obj, dict):
        return ""
    if obj.get("simpleText"):
        return _clean(obj.get("simpleText"))
    return _clean("".join(str(r.get("text") or "") for r in (obj.get("runs") or [])
                          if isinstance(r, dict)))


def _num(value):
    try:
        if value in (None, "", "NA", "None"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ YouTube metadata

def video_id(url):
    raw = str(url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw
    m = VIDEO_ID_RE.search(raw)
    return m.group(1) if m else ""


def canonical(url):
    raw = str(url or "").strip()
    vid = raw if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw) else video_id(raw)
    return WATCH.format(vid=vid) if vid else ""


def platform_of(url):
    """Which live-chat transport this URL needs. Unknown URLs default to YouTube."""
    raw = str(url or "").strip()
    return "twitch" if TWITCH_RE.search(raw) or raw.lower().startswith("tw_") else "youtube"


def twitch_login(url):
    """The lower-case channel login from a Twitch URL (not the display name)."""
    raw = str(url or "").strip()
    if raw.lower().startswith("tw_"):
        raw = raw[3:]
    m = TWITCH_RE.search(raw)
    if m:
        login = m.group(1).lower()
        return "" if login in TWITCH_RESERVED else login
    if re.fullmatch(r"[A-Za-z0-9_]{3,25}", raw) and raw.lower() not in TWITCH_RESERVED:
        return raw.lower()
    return ""


def session_id(url):
    """A filesystem/API-safe id for either platform."""
    if platform_of(url) == "twitch":
        login = twitch_login(url)
        return "tw_" + login if login else ""
    return video_id(url)


def _probe(url):
    """Metadata through the bundled yt-dlp. One subprocess, no Python API dependency."""
    sep = "\x1f"
    template = sep.join([
        "%(id)s", "%(is_live)s", "%(live_status)s", "%(was_live)s",
        "%(timestamp)s", "%(release_timestamp)s", "%(duration)s",
        "%(title)s", "%(channel)s", "%(uploader)s", "%(webpage_url)s",
    ])
    cmd = [ytdlp(), "--no-playlist", "--no-warnings", "--skip-download",
           "--print", template, url]
    ffdir = os.path.dirname(ffmpeg())
    if ffdir:
        cmd += ["--ffmpeg-location", ffdir]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=120)
    except FileNotFoundError:
        raise RuntimeError("yt-dlp is missing - the bundled copy is required.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("YouTube did not answer the live-status check in time.")

    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    row = lines[-1].split(sep) if lines else []
    if len(row) < 11:
        tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
        raise RuntimeError("Could not read this live URL. " + (tail or "yt-dlp returned no metadata."))
    (vid, is_live, live_status, was_live, timestamp, release_ts, duration,
     title, channel, uploader, page) = row[:11]
    vid = (vid or video_id(url)).strip()
    live = str(is_live).strip().lower() == "true"
    was = str(was_live).strip().lower() == "true"
    status = str(live_status or "").strip()
    start = _num(release_ts) or _num(timestamp)
    return {
        "video_id": vid,
        "url": page if page.startswith("http") else canonical(vid),
        "title": _clean(title, 240) or "Untitled live stream",
        "channel": _clean(channel, 160) or _clean(uploader, 160) or "YouTube",
        "duration": _num(duration),
        "stream_start": start,
        "is_live": live,
        "was_live": was,
        "live_status": status,
        "ended": bool(was and not live and status not in ("is_upcoming", "is_live")),
        "upcoming": status == "is_upcoming",
    }


def _probe_twitch(url):
    """Twitch metadata through yt-dlp. Offline is a state, not an exception."""
    login = twitch_login(url)
    if not login:
        raise RuntimeError("Paste a Twitch channel URL, e.g. https://www.twitch.tv/name.")
    sep = ""
    template = sep.join(["%(id)s", "%(is_live)s", "%(live_status)s",
                         "%(timestamp)s", "%(title)s", "%(uploader)s", "%(webpage_url)s",
                         "%(description)s"])
    cmd = [ytdlp(), "--no-playlist", "--no-warnings", "--skip-download",
           "--print", template, "https://www.twitch.tv/" + login]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=120)
    except FileNotFoundError:
        raise RuntimeError("yt-dlp is missing - the bundled copy is required.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Twitch did not answer the live-status check in time.")
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    row = lines[-1].split(sep) if lines else []
    offline = ("not currently live" in (proc.stderr or "").lower()
               or "channel is offline" in (proc.stderr or "").lower())
    if len(row) < 7:
        if offline:
            return {
                "platform": "twitch", "video_id": "tw_" + login, "source_id": "",
                "url": "https://www.twitch.tv/" + login, "login": login,
                "title": login, "channel": login, "stream_start": None,
                "duration": None, "is_live": False, "offline": True, "ended": False,
                "upcoming": False,
            }
        tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
        raise RuntimeError("Could not read this Twitch channel. " + (tail or "no metadata."))
    source_id, is_live, live_status, timestamp, title, uploader, page = row[:7]
    description = row[7] if len(row) > 7 else ""
    live = str(is_live).strip().lower() == "true"
    start = _num(timestamp)
    if start and start > 1_000_000_000:
        start_value = start
    else:
        start_value = None
    return {
        "platform": "twitch", "video_id": "tw_" + login, "source_id": source_id.strip(),
        "url": page.strip() or ("https://www.twitch.tv/" + login), "login": login,
        "title": _clean(description, 240) or _clean(title, 240) or login,
        "channel": _clean(uploader, 160) or login,
        "stream_start": start_value, "duration": None,
        "is_live": live, "offline": not live, "ended": False,
        "upcoming": False, "live_status": live_status,
    }


# ------------------------------------------------------------------ chat transport

def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def _initial_data(page):
    m = re.search(r"ytInitialData\s*=\s*(\{.*?\});\s*</script>", page, re.S)
    if not m:
        m = re.search(r'ytInitialData"\s*:\s*(\{.*?\})\s*,\s*"ytInitialPlayerResponse', page, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def _continuation(lc, replay=False):
    """The first usable continuation in a liveChatRenderer, in preference order."""
    continuations = (lc or {}).get("continuations") or []
    preferred = (("replayContinuationData", "reloadContinuationData",
                  "invalidationContinuationData", "timedContinuationData") if replay else
                 ("reloadContinuationData", "invalidationContinuationData",
                  "timedContinuationData"))
    for name in preferred:
        for c in continuations:
            if isinstance(c, dict):
                data = c.get(name) or {}
                if data.get("continuation"):
                    return str(data["continuation"])
    for c in continuations:
        if isinstance(c, dict):
            for value in c.values():
                if isinstance(value, dict) and value.get("continuation"):
                    return str(value["continuation"])
    return ""


def _initial_chat(vid, replay=False):
    page = _get(WATCH.format(vid=vid), timeout=45)
    data = _initial_data(page)
    if not data:
        raise RuntimeError("YouTube's watch page did not contain live chat data.")
    lc = _find_key(data, "liveChatRenderer")
    cont = _continuation(lc, replay=replay)
    if not cont:
        for key in ("replayContinuationData", "reloadContinuationData",
                    "invalidationContinuationData"):
            found = _find_key(data, key)
            if isinstance(found, dict) and found.get("continuation"):
                cont = str(found["continuation"])
                break
    if not cont:
        raise RuntimeError("This stream has no live chat continuation (chat may be disabled).")
    return cont


def _post_chat(cont, replay=False):
    body = json.dumps({
        "context": {"client": {"clientName": "WEB", "clientVersion": CLIENT_VERSION,
                                "hl": "en", "gl": "US"}},
        "continuation": cont,
    }).encode()
    req = urllib.request.Request(CHAT_REPLAY if replay else CHAT_INITIAL, data=body,
                                 headers={
                                     "Content-Type": "application/json",
                                     "User-Agent": UA,
                                     "X-YouTube-Client-Name": "1",
                                     "X-YouTube-Client-Version": CLIENT_VERSION,
                                     "Origin": "https://www.youtube.com",
                                     "Referer": "https://www.youtube.com/",
                                 })
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.loads(res.read().decode("utf-8", "replace"))
    cc = (data.get("continuationContents") or {}).get("liveChatContinuation") or {}
    actions = cc.get("actions") or []
    next_cont = ""
    timeout_ms = 0
    for c in cc.get("continuations") or []:
        if not isinstance(c, dict):
            continue
        for value in c.values():
            if not isinstance(value, dict):
                continue
            if not next_cont and value.get("continuation"):
                next_cont = str(value["continuation"])
            if value.get("timeoutMs"):
                timeout_ms = int(value["timeoutMs"] or 0)
    return actions, next_cont, timeout_ms


def _twitch_parse(line, stream_start=None):
    """One IRC line -> the same tiny message shape used by YouTube.

    Twitch tags are optional: anonymous connections still get display names and the
    message, just without tmi-sent-ts. When the timestamp is missing we fall back to
    wall-clock time, which is enough for spike detection while connected live.
    """
    if not line or "PRIVMSG" not in line:
        return None
    tags = {}
    raw = line.rstrip("\r\n")
    if raw.startswith("@"):
        tag_part, _, raw = raw[1:].partition(" ")
        for part in tag_part.split(";"):
            key, _, value = part.partition("=")
            tags[key] = value
    m = re.match(r"^:([^!]+)![^ ]+ PRIVMSG #[^ ]+ :(.*)$", raw)
    if not m:
        return None
    login, text = m.group(1), m.group(2).strip()
    if not text:
        return None
    ts = _num(tags.get("tmi-sent-ts"))
    if ts and ts > 1_000_000_000_000:
        ts /= 1000.0
    wall = ts if ts and ts > 1_000_000_000 else _now()
    start = _num(stream_start)
    t = max(0.0, wall - start) if start else None
    author = tags.get("display-name") or login
    mid = tags.get("id") or ("tw:%s:%s" % (int(wall * 1000), abs(hash((login, text))) % 10**9))
    return {
        "id": str(mid), "wall": round(float(wall), 3),
        "t": round(float(t), 3) if t is not None else None,
        "author": "@" + str(author)[:80], "text": text[:500], "kind": "twitch",
    }


def _twitch_connect(login):
    """Anonymous Twitch IRC. No token, no app registration, no browser session."""
    ctx = ssl.create_default_context()
    last = None
    for host, port, use_tls in (("irc.chat.twitch.tv", 6697, True),
                                ("irc.chat.twitch.tv", 6667, False)):
        try:
            sock = socket.create_connection((host, port), timeout=15)
            if use_tls:
                sock = ctx.wrap_socket(sock, server_hostname=host)
            nick = "justinfan%d" % (10000 + (os.getpid() % 80000))
            sock.sendall(("PASS SCHMOOPIIE\r\nNICK %s\r\n"
                          "CAP REQ :twitch.tv/tags\r\nJOIN #%s\r\n"
                          % (nick, login)).encode())
            sock.settimeout(1.0)
            return sock
        except Exception as e:      # try the next port; keep the last reason
            last = e
    raise RuntimeError("Could not reach Twitch chat: %s" % (last or "unknown error"))


def _twitch_chat(s):
    """Blocking receive loop. Returns only when the session is no longer watching."""
    login = s.get("login") or twitch_login(s.get("url") or "")
    seen = _load_chat_ids(s)
    attempt = 0
    while s.get("status") == "watching" and not _terminal(s):
        try:
            sock = _twitch_connect(login)
            s["stage"] = "watching Twitch chat"
            s["errors"] = 0
            _save(s)
            last_probe = 0.0
            while s.get("status") == "watching" and not _terminal(s):
                if _now() - last_probe > 45:
                    try:
                        meta = _probe_twitch("https://www.twitch.tv/" + login)
                    except Exception:
                        # A metadata probe is advisory. The IRC socket is still the
                        # live connection; do not drop a good watch over a slow probe.
                        meta = {"unknown": True}
                    last_probe = _now()
                    if meta.get("is_live"):
                        if meta.get("stream_start") and not s.get("stream_start"):
                            s["stream_start"] = meta["stream_start"]
                        if meta.get("title"):
                            s["title"] = meta["title"]
                        _save(s)
                    elif not meta.get("unknown"):
                        s["status"] = "finalizing"
                        s["stage"] = "stream ended - making clips from DVR"
                        _save(s)
                        break
                try:
                    data = sock.recv(65535)
                    if not data:
                        break
                    text = data.decode("utf-8", "replace")
                    batch = []
                    for line in text.splitlines():
                        if line.startswith("PING"):
                            try:
                                sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                            except OSError:
                                pass
                            continue
                        msg = _twitch_parse(line, s.get("stream_start"))
                        if msg:
                            batch.append(msg)
                    if batch:
                        _append_messages(s, batch, seen)
                        s["stage"] = "watching Twitch chat"
                        _save(s)
                        _maybe_render_live(s)
                except socket.timeout:
                    # A spike can end during a silent patch; keep the render clock
                    # moving even when no new chat line arrives.
                    _maybe_render_live(s)
            try:
                sock.close()
            except Exception:
                pass
            if s.get("status") != "watching":
                break
            # EOF/connection reset while still live: reconnect, with backoff.
            attempt += 1
            if attempt >= 8:
                s["status"] = "error"
                s["stage"] = "lost the Twitch chat"
                s["error"] = "Twitch chat disconnected repeatedly"
                _save(s)
                break
            time.sleep(min(30, 2 * attempt))
        except Exception as e:
            attempt += 1
            s["errors"] = int(s.get("errors") or 0) + 1
            s["last_error"] = str(e)[:300]
            _save(s)
            if attempt >= 8:
                s["status"] = "error"
                s["stage"] = "lost the Twitch chat"
                s["error"] = str(e)[:400]
                _save(s)
                break
            time.sleep(min(30, 2 * attempt))


def _message(action, s, offset_override=None):
    """One addChatItemAction -> the tiny shape we persist. Skip gifts/system noise.

    Replay batches wrap the real action:
      {"replayChatItemAction": {"videoOffsetTimeMsec": "...", "actions": [...]}}
    so unwrap those first and use the replay's own video offset, which is exact.
    """
    if isinstance(action, dict) and isinstance(action.get("replayChatItemAction"), dict):
        replay = action["replayChatItemAction"]
        off = _num(replay.get("videoOffsetTimeMsec"))
        if off is not None:
            offset_override = off / 1000.0
        for sub in replay.get("actions") or []:
            got = _message(sub, s, offset_override=offset_override)
            if got:
                return got
        return None
    item = (action or {}).get("addChatItemAction", {}).get("item") or {}
    if not isinstance(item, dict):
        return None
    renderer = None
    kind = ""
    for name in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer",
                 "liveChatMembershipItemRenderer",
                 "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer"):
        if isinstance(item.get(name), dict):
            renderer, kind = item[name], name
            break
    if not renderer:
        return None

    text = _runs_text(renderer.get("message"))
    if not text:
        text = _runs_text(renderer.get("headerSubtext")) or _runs_text(renderer.get("headerPrimaryText"))
    amount = _runs_text(renderer.get("purchaseAmountText"))
    if amount:
        text = (text + " " + amount).strip()
    if not text:
        return None

    ts_us = _num(renderer.get("timestampUsec"))
    if offset_override is not None:
        ts = max(0.0, float(offset_override))
        wall = _now()
    elif ts_us is None:
        ts = None
        wall = _now()
    else:
        sec = ts_us / 1_000_000.0
        # Live messages carry an absolute Unix timestamp; replay messages often carry
        # a video offset. Both are handled by the same normaliser.
        if sec > 1_000_000_000:
            wall = sec
            start = _num(s.get("stream_start"))
            ts = max(0.0, sec - start) if start else None
        else:
            ts = max(0.0, sec)
            wall = _now()

    author = _runs_text(renderer.get("authorName"))
    mid = str(renderer.get("id") or "")
    if not mid:
        mid = "%s:%s" % (int(wall * 1000), abs(hash((author, text))) % 10**9)
    return {
        "id": mid,
        "wall": round(float(wall), 3),
        "t": round(float(ts), 3) if ts is not None else None,
        "author": author[:80],
        "text": text[:500],
        "kind": kind,
    }


def _load_chat_ids(s):
    ids = set()
    try:
        with open(_chat_path(s["video_id"]), encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if row.get("id"):
                        ids.add(str(row["id"]))
                except ValueError:
                    continue
    except OSError:
        pass
    return ids


def _append_messages(s, messages, seen=None):
    """Append new messages exactly once. Returns how many were added."""
    if not messages:
        return 0
    path = _chat_path(s["video_id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seen = seen if seen is not None else _load_chat_ids(s)
    added = 0
    last = _num(s.get("last_message")) or 0.0
    with open(path, "a", encoding="utf-8") as f:
        for msg in messages:
            if not msg or not msg.get("id") or msg["id"] in seen:
                continue
            seen.add(msg["id"])
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            added += 1
            if msg.get("t") is not None:
                last = max(last, float(msg["t"]))
        f.flush()
    s["message_count"] = int(s.get("message_count") or 0) + added
    s["last_message"] = round(last, 3) if last else None
    if added:
        latest = max((m for m in messages if m.get("wall")), key=lambda m: m.get("wall") or 0, default=None)
        if latest:
            s["last_message_wall"] = latest.get("wall")
    return added


def _load_messages(s, limit=None):
    rows = []
    try:
        with open(_chat_path(s["video_id"]), encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("t") is not None:
                    rows.append(row)
    except OSError:
        return []
    rows.sort(key=lambda r: (float(r["t"]), r.get("wall") or 0))
    return rows[-limit:] if limit else rows


# ------------------------------------------------------------------ spikes

def detect_spikes(messages, before=DEFAULT_BEFORE, after=DEFAULT_AFTER,
                  max_clips=DEFAULT_MAX_CLIPS, duration=None):
    """Find chat acceleration and turn each burst into a clip window.

    Baseline is the median 5-second bucket for this stream, so a quiet chat and a
    screaming chat are both judged against themselves. The window deliberately starts
    before the burst: the thing people reacted to happened before they typed.
    """
    rows = [m for m in messages if m.get("t") is not None]
    if len(rows) < 6:
        return []
    t0 = min(float(m["t"]) for m in rows)
    t1 = max(float(m["t"]) for m in rows)
    if duration:
        t1 = min(t1, float(duration))
    if t1 <= t0:
        return []
    span = max(5.0, t1 - t0)
    bucket = 5.0
    n = int(span // bucket) + 1
    counts = [0] * n
    authors = [set() for _ in range(n)]
    rows_by_bucket = [[] for _ in range(n)]
    for m in rows:
        idx = int(max(0.0, float(m["t"]) - t0) // bucket)
        if idx >= n:
            continue
        counts[idx] += 1
        if m.get("author"):
            authors[idx].add(m["author"])
        rows_by_bucket[idx].append(m)
    observed = [c for c in counts if c]
    baseline = statistics.median(observed) if observed else 0
    threshold = max(4.0, baseline * 2.5)
    spike_idx = [i for i, c in enumerate(counts) if c >= threshold and c >= 4]
    if not spike_idx:
        return []

    regions = []
    for i in spike_idx:
        a = t0 + i * bucket
        b = a + bucket
        if regions and a - regions[-1]["end"] <= 1.0:
            regions[-1]["end"] = b
            regions[-1]["buckets"].append(i)
        else:
            regions.append({"start": a, "end": b, "buckets": [i]})

    candidates = []
    for reg in regions:
        idxs = reg["buckets"]
        count = sum(counts[i] for i in idxs)
        uniq = len(set().union(*(authors[i] for i in idxs))) if idxs else 0
        peak_i = max(idxs, key=lambda i: counts[i])
        peak = t0 + peak_i * bucket + bucket / 2
        score = (count / max(1.0, baseline * max(1, len(idxs)))) + (uniq / 25.0)
        start = max(0.0, reg["start"] - before)
        end = reg["end"] + after
        if duration:
            end = min(float(duration), end)
        if end - start < 12:
            end = start + 12
            if duration:
                end = min(float(duration), end)
        if end <= start:
            continue
        top = []
        for i in idxs:
            top.extend(rows_by_bucket[i])
        top.sort(key=lambda m: (-len(m.get("text") or ""), -(m.get("wall") or 0)))
        top = [m for m in top if len(m.get("text") or "") >= 3][:5]
        candidates.append({
            "id": "s%d" % (len(candidates) + 1),
            "key": "%d-%d" % (round(reg["start"]), round(reg["end"])),
            "peak": round(peak, 2),
            "start": round(start, 2),
            "end": round(end, 2),
            "burst_start": round(reg["start"], 2),
            "burst_end": round(reg["end"], 2),
            "messages": count,
            "authors": uniq,
            "score": round(score, 2),
            "top": [{"author": m.get("author") or "", "text": m.get("text") or ""}
                    for m in top],
        })

    candidates.sort(key=lambda c: (-c["score"], -c["messages"]))
    out = []
    for c in candidates:
        overlap = any(not (c["end"] <= k["start"] or c["start"] >= k["end"]) for k in out)
        if overlap:
            continue
        out.append(c)
        if len(out) >= max(1, int(max_clips or DEFAULT_MAX_CLIPS)):
            break
    for i, c in enumerate(out, 1):
        c["rank"] = i
    return out


def _title_for(spike, source_title=""):
    """Pick a readable reaction from the chat, then add stream context.

    The chat top list is noisy: it contains greetings, replies and URLs. Prefer a
    complete phrase of roughly 3-10 words, reject the obvious noise, and keep the
    stream title as a short prefix so a viewer knows where the clip came from.
    """
    scored = []
    for text in [t["text"] for t in spike.get("top") or [] if t.get("text")]:
        if re.search(r"https?://|www\.", text, re.I):
            continue
        title = virality.clean_title(text, 80)
        words = title.split()
        if len(words) < 3 or len(title) < 16:
            continue
        low = title.lower()
        if re.match(r"^@|^(hi|hey|hello|gm|good morning|thanks|thank you)(?![A-Za-z])", low) and len(words) < 12:
            continue
        score = 0
        if 28 <= len(title) <= 68:
            score += 20
        score -= abs(len(title) - 45) / 3.0
        if len(words) >= 4:
            score += 6
        if title.count("!") or title.count("?"):
            score += 2
        if title.isupper():
            score -= 12
        scored.append((score, title))
    picked = max(scored, key=lambda x: x[0])[1] if scored else ""
    source = virality.clean_title(source_title, 40)
    if picked and source and source.lower() not in picked.lower():
        return virality.clean_title("%s — %s" % (source, picked), 95)
    return picked or "Chat lost it at %s" % _hm(spike.get("peak", 0))


def _meta_for(spike, source_title=""):
    title = _title_for(spike, source_title)
    top = [t["text"] for t in spike.get("top") or []][:3]
    desc = ("Live chat spike: %d messages from %d people. The room reacted here. %s"
            % (int(spike.get("messages") or 0), int(spike.get("authors") or 0),
               " / ".join(top))).strip()
    return {
        "title": title,
        "description": desc[:900],
        "hashtags": ["#shorts", "#live", "#clip", "#streamer"],
    }


# ------------------------------------------------------------------ download + render

def _download_subtitles(s):
    if s.get("platform") == "twitch":
        return os.path.join(_session_dir(s["video_id"]), "captions")
    vid = s["video_id"]
    outdir = os.path.join(_session_dir(vid), "captions")
    os.makedirs(outdir, exist_ok=True)
    if glob.glob(os.path.join(outdir, "*.json3")) or glob.glob(os.path.join(outdir, "*.vtt")):
        return outdir
    cmd = [ytdlp(), "--no-playlist", "--no-warnings", "--ignore-errors",
           "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-langs", "en.*,en", "--sub-format", "json3/vtt/best"]
    ff = ffmpeg()
    if not os.path.isfile(ff):
        import shutil
        ff = shutil.which(ff) or ""
    if ff:
        cmd += ["--ffmpeg-location", os.path.dirname(ff) or ff]
    cmd += ["-o", os.path.join(outdir, "%(id)s.%(ext)s"), s["url"]]
    try:
        subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return outdir


def _words(s):
    files = []
    for ext in ("json3", "vtt", "srt"):
        files += glob.glob(os.path.join(_session_dir(s["video_id"]), "captions", "*." + ext))
    if not files:
        return []
    def rank(path):
        name = os.path.basename(path).lower()
        return (0 if ".en" in name else 1, 0 if name.endswith(".json3") else 1)
    for path in sorted(files, key=rank):
        words = ingest.parse_subtitle(path)
        if len(words) >= 10:
            return words
    return []


def _download_section(s, spike):
    """Download only [start,end] from the finished recording. Returns (path, duration)."""
    vid = s["video_id"]
    outdir = os.path.join(_session_dir(vid), "sections")
    os.makedirs(outdir, exist_ok=True)
    start, end = float(spike["start"]), float(spike["end"])
    target = os.path.join(outdir, "%s_%06d.mp4" % (spike["id"], int(start)))
    if os.path.isfile(target) and os.path.getsize(target) > 50_000:
        try:
            return target, ffmpeg_tools.duration_of(target)
        except Exception:
            pass
    cmd = [ytdlp(), "--no-playlist", "--no-warnings", "--ignore-errors",
           "--download-sections", "*%.2f-%.2f" % (start, end),
           "--force-keyframes-at-cuts", "--merge-output-format", "mp4"]
    if s.get("platform") == "twitch":
        cmd += ["-f", "best[height<=720]/best"]
    else:
        cmd += ["-f", "bv*[height<=1080]+ba/b"]
    # yt-dlp needs ffmpeg for DASH/HLS merging and keyframe cuts. `ffmpeg()` can be
    # the bare word "ffmpeg" when it is on PATH; passing dirname("ffmpeg") == "" made
    # yt-dlp think no ffmpeg existed. Resolve the real path first.
    ff = ffmpeg()
    if not os.path.isfile(ff):
        import shutil
        ff = shutil.which(ff) or ""
    if ff:
        cmd += ["--ffmpeg-location", os.path.dirname(ff) or ff]
    cmd += ["-o", target, s["url"]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=900)
    except subprocess.TimeoutExpired:
        raise RuntimeError("The section download timed out.")
    if not os.path.isfile(target) or os.path.getsize(target) < 50_000:
        tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
        raise RuntimeError("Could not download the spike section. " + (tail or "yt-dlp produced no file."))
    return target, ffmpeg_tools.duration_of(target)


def _render_section(s, spike, section, section_duration, words):
    vid = s["video_id"]
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    os.makedirs(clips_dir, exist_ok=True)
    base = "live_%s_%s" % (vid, spike["id"])
    out = os.path.join(clips_dir, base + ".mp4")
    meta = _meta_for(spike, s.get("title") or "")
    ass_name = None
    if words:
        ass_path = os.path.join(clips_dir, base + ".ass")
        captions.build_ass(words, (float(spike["start"]), float(spike["end"])),
                           "wordpop", 1.0, "bottom", ass_path)
        ass_name = base + ".ass"
    ffmpeg_tools.cut_clip(section, 0.0, float(section_duration), out, ass_name,
                          cwd=clips_dir, framing="focus", grade=True, ratio="9:16",
                          vignette=True, auto_zoom=False)
    thumb = None
    try:
        thumb_path = os.path.join(clips_dir, base + ".jpg")
        if ffmpeg_tools.thumbnail(out, min(1.0, max(0.2, section_duration * 0.15)), thumb_path):
            thumb = "/clips/" + base + ".jpg"
    except Exception:
        pass
    return {
        "file": "/clips/" + base + ".mp4",
        "thumb": thumb,
        "title": meta["title"],
        "description": meta["description"],
        "hashtags": meta["hashtags"],
        "start": round(float(spike["start"]), 1),
        "end": round(float(spike["end"]), 1),
        "peak": round(float(spike["peak"]), 1),
        "duration": round(float(section_duration), 1),
        "rank": int(spike.get("rank") or 0),
        "spike_id": spike["id"],
        "spike_key": spike.get("key") or "",
        "messages": int(spike.get("messages") or 0),
        "authors": int(spike.get("authors") or 0),
        "chat": spike.get("top") or [],
        "source": {"video_id": vid, "title": s.get("title"), "channel": s.get("channel")},
        "width": 1080, "height": 1920,
    }


# ------------------------------------------------------------------ session lifecycle

def _summary(s):
    return {
        "id": s["video_id"],
        "video_id": s["video_id"],
        "url": s.get("url"),
        "title": s.get("title"),
        "channel": s.get("channel"),
        "status": s.get("status"),
        "stage": s.get("stage"),
        "progress": int(s.get("progress") or 0),
        "added": s.get("added"),
        "last_poll": s.get("last_poll"),
        "message_count": int(s.get("message_count") or 0),
        "spike_count": len(s.get("spikes") or []),
        "spikes": (s.get("spikes") or [])[:_SPIKE_MAX],
        "clips": s.get("clips") or [],
        "error": s.get("error"),
        "empty_reason": s.get("empty_reason"),
        "platform": s.get("platform") or "youtube",
        "auto_post": bool(s.get("auto_post")),
        "privacy": s.get("privacy") or "unlisted",
        "rights_ok": bool(s.get("rights_ok")),
        "render_policy": s.get("render_policy") or "quiet",
        "last_render": s.get("last_render"),
        "before": s.get("before"),
        "after": s.get("after"),
        "max_clips": s.get("max_clips"),
    }


def list_sessions():
    with _LOCK:
        _load_sessions()
        rows = sorted(_SESSIONS.values(), key=lambda s: -float(s.get("added") or 0))
        return [_summary(s) for s in rows]


def get_session(vid):
    with _LOCK:
        _load_sessions()
        s = _SESSIONS.get(vid)
        if not s:
            return None
        out = _summary(s)
        out["chat_tail"] = _load_messages(s, 30)
        return out


def _set(s, **kw):
    with _LOCK:
        s.update(kw)
        _save(s)


def _ensure_thread(vid):
    with _LOCK:
        th = _THREADS.get(vid)
        if th and th.is_alive():
            return
        th = threading.Thread(target=_run, args=(vid,), daemon=True,
                              name="live-chat-%s" % vid)
        _THREADS[vid] = th
        th.start()


def _start_twitch(url, before=DEFAULT_BEFORE, after=DEFAULT_AFTER,
                  max_clips=DEFAULT_MAX_CLIPS, auto_post=False, privacy="unlisted",
                  rights_ok=False, render_policy="instant"):
    login = twitch_login(url)
    if not login:
        raise RuntimeError("Paste a Twitch channel URL, e.g. https://www.twitch.tv/name.")
    sid = "tw_" + login
    with _LOCK:
        _load_sessions()
        s = _SESSIONS.get(sid)
        if s:
            s["before"] = float(before or s.get("before") or DEFAULT_BEFORE)
            s["after"] = float(after or s.get("after") or DEFAULT_AFTER)
            s["max_clips"] = int(max_clips or s.get("max_clips") or DEFAULT_MAX_CLIPS)
            s["auto_post"] = bool(auto_post)
            s["privacy"] = privacy if privacy in ("public", "unlisted", "private") else "unlisted"
            s["rights_ok"] = bool(rights_ok)
            if render_policy in ("quiet", "instant"):
                s["render_policy"] = render_policy
            if _terminal(s):
                s["status"] = "waiting"
                s["stage"] = "resuming the Twitch radar"
                s["error"] = None
                s["errors"] = 0
            _save(s)
            _ensure_thread(sid)
            return _summary(s)

    meta = _probe_twitch("https://www.twitch.tv/" + login)
    now = _now()
    s = {
        "id": sid, "video_id": sid, "platform": "twitch", "login": login,
        "source_id": meta.get("source_id") or "",
        "url": meta.get("url") or ("https://www.twitch.tv/" + login),
        "title": meta.get("title") or login, "channel": meta.get("channel") or login,
        "stream_start": meta.get("stream_start"), "duration": None,
        "added": now, "last_poll": None, "last_meta_probe": now,
        "message_count": 0, "last_message": None, "last_message_wall": None,
        "status": "watching" if meta.get("is_live") else "waiting",
        "stage": "watching Twitch chat" if meta.get("is_live")
                 else "waiting for Twitch to go live",
        "progress": 2, "spikes": [], "clips": [], "error": None, "empty_reason": None,
        "continuation": "", "errors": 0,
        "before": float(before or DEFAULT_BEFORE), "after": float(after or DEFAULT_AFTER),
        "max_clips": int(max_clips or DEFAULT_MAX_CLIPS),
        "auto_post": bool(auto_post),
        "privacy": privacy if privacy in ("public", "unlisted", "private") else "unlisted",
        "rights_ok": bool(rights_ok), "last_render": None,
        "render_policy": render_policy if render_policy in ("quiet", "instant") else "instant",
    }
    os.makedirs(_session_dir(sid), exist_ok=True)
    with _LOCK:
        _SESSIONS[sid] = s
        _save(s)
    _ensure_thread(sid)
    return _summary(s)


def start(url, before=DEFAULT_BEFORE, after=DEFAULT_AFTER, max_clips=DEFAULT_MAX_CLIPS,
          auto_post=False, privacy="unlisted", rights_ok=False, render_policy=None):
    """Resolve a live URL, persist it, and start/resume watching. Idempotent."""
    if platform_of(url) == "twitch":
        return _start_twitch(url, before=before, after=after, max_clips=max_clips,
                             auto_post=auto_post, privacy=privacy, rights_ok=rights_ok,
                             render_policy=render_policy)
    vid = video_id(url)
    if not vid:
        raise RuntimeError("Paste a YouTube live URL (watch?v=... or /live/...).")
    with _LOCK:
        _load_sessions()
        if vid in _SESSIONS:
            s = _SESSIONS[vid]
            s["before"] = float(before or s.get("before") or DEFAULT_BEFORE)
            s["after"] = float(after or s.get("after") or DEFAULT_AFTER)
            s["max_clips"] = int(max_clips or s.get("max_clips") or DEFAULT_MAX_CLIPS)
            s["auto_post"] = bool(auto_post)
            s["privacy"] = privacy if privacy in ("public", "unlisted", "private") else "unlisted"
            s["rights_ok"] = bool(rights_ok)
            if render_policy in ("quiet", "instant"):
                s["render_policy"] = render_policy
            if _terminal(s):
                # Re-starting a stopped/errored/finished session should retry, not
                # silently return a dead card. Keep its chat and clips; probe again.
                s["status"] = "waiting"
                s["stage"] = "resuming the live radar"
                s["error"] = None
                s["errors"] = 0
            _save(s)
            _ensure_thread(vid)
            return _summary(s)

    meta = _probe(canonical(vid))
    if not meta.get("video_id"):
        raise RuntimeError("That link did not resolve to a YouTube video.")
    vid = meta["video_id"]
    now = _now()
    s = {
        "id": vid, "video_id": vid, "url": meta["url"] or canonical(vid),
        "title": meta["title"], "channel": meta["channel"],
        "stream_start": meta.get("stream_start"), "duration": meta.get("duration"),
        "added": now, "last_poll": None, "last_meta_probe": now,
        "message_count": 0, "last_message": None,
        "status": "watching" if meta.get("is_live") else
                  "finalizing" if meta.get("ended") else "waiting",
        "stage": "watching live chat" if meta.get("is_live") else
                 "waiting for the stream to start" if meta.get("upcoming") else
                 "stream ended - preparing clips",
        "progress": 2, "spikes": [], "clips": [], "error": None, "empty_reason": None,
        "continuation": "", "errors": 0,
        "before": float(before or DEFAULT_BEFORE), "after": float(after or DEFAULT_AFTER),
        "max_clips": int(max_clips or DEFAULT_MAX_CLIPS),
        "auto_post": bool(auto_post), "privacy": privacy if privacy in ("public", "unlisted", "private") else "unlisted",
        "rights_ok": bool(rights_ok), "last_render": None, "last_message_wall": None,
        "platform": "youtube",
        "render_policy": render_policy if render_policy in ("quiet", "instant") else "quiet",
    }
    os.makedirs(_session_dir(vid), exist_ok=True)
    with _LOCK:
        _SESSIONS[vid] = s
        _save(s)
    _ensure_thread(vid)
    return _summary(s)


def stop(vid):
    with _LOCK:
        _load_sessions()
        s = _SESSIONS.get(vid)
        if not s:
            return None
        if s.get("status") not in ("done",):
            s["status"] = "stopped"
            s["stage"] = "stopped by you"
            _save(s)
        return _summary(s)


def render_now(vid):
    with _LOCK:
        _load_sessions()
        s = _SESSIONS.get(vid)
        if not s:
            raise RuntimeError("Unknown live session.")
        if s.get("status") == "done":
            return _summary(s)
        s["force_finalize"] = True
        s["status"] = "finalizing"
        s["stage"] = "checking the recording"
        s["progress"] = max(8, int(s.get("progress") or 0))
        _save(s)
    _ensure_thread(vid)
    return get_session(vid)


def resume():
    """Called once by the server at boot. Never blocks the HTTP listener."""
    with _LOCK:
        _load_sessions()
        active = [s for s in _SESSIONS.values() if not _terminal(s)]
    for s in active:
        _ensure_thread(s["video_id"])
    return len(active)


def _probe_and_update(s):
    if s.get("platform") == "twitch":
        meta = _probe_twitch(s.get("url") or ("https://www.twitch.tv/" + (s.get("login") or "")))
    else:
        meta = _probe(s.get("url") or canonical(s["video_id"]))
    with _LOCK:
        if meta.get("video_id"):
            s["video_id"] = meta["video_id"]
            s["url"] = meta["url"] or s.get("url")
            s["title"] = meta.get("title") or s.get("title")
            s["channel"] = meta.get("channel") or s.get("channel")
            s["source_id"] = meta.get("source_id") or s.get("source_id")
            s["stream_start"] = s.get("stream_start") or meta.get("stream_start")
            if meta.get("duration"):
                s["duration"] = meta["duration"]
            s["last_meta_probe"] = _now()
            _save(s)
    return meta


def _collect_replay(s):
    """Fetch the whole live-chat replay when it is available. Used after the stream
    ended, especially when the app was closed for part of it."""
    if s.get("replay_done"):
        return 0
    vid = s["video_id"]
    try:
        cont = _initial_chat(vid, replay=True)
    except Exception:
        s["replay_done"] = True
        s["replay_error"] = "chat replay unavailable"
        _save(s)
        return 0
    seen = _load_chat_ids(s)
    total, batches = 0, 0
    while cont and batches < 200:
        batches += 1
        try:
            actions, nxt, _timeout = _post_chat(cont, replay=True)
        except Exception as e:
            s["replay_error"] = str(e)[:200]
            break
        msgs = [m for m in (_message(a, s) for a in actions) if m]
        added = _append_messages(s, msgs, seen)
        total += added
        if os.environ.get("CB_LIVE_DEBUG"):
            import hashlib as _h
            print("[live] replay batch %d actions=%d msgs=%d added=%d next=%s "
                  "in=%s out=%s same=%s"
                  % (batches, len(actions), len(msgs), added, bool(nxt),
                     _h.md5(cont.encode()).hexdigest()[:8],
                     _h.md5((nxt or "").encode()).hexdigest()[:8], nxt == cont),
                  flush=True)
        if nxt and nxt == cont:
            s["replay_error"] = "replay token did not advance"
            break
        s["continuation"] = nxt
        cont = nxt
        s["last_poll"] = _now()
        s["stage"] = "reading the chat replay (%d messages)" % s["message_count"]
        s["progress"] = min(18, 8 + batches // 5)
        _save(s)
        if not nxt:
            break
        time.sleep(0.15)
    s["replay_done"] = True
    _save(s)
    return total


def _stream_now(s):
    """The current recording offset, even while chat is silent.

    The newest message gives us an exact (video offset, wall clock) anchor. If the
    chat is quiet, add the elapsed wall time to the anchor instead of assuming the
    stream clock and the machine clock started together.
    """
    last_t, last_wall = _num(s.get("last_message")), _num(s.get("last_message_wall"))
    if last_t is not None and last_wall:
        return max(0.0, last_t + max(0.0, time.time() - last_wall))
    start = _num(s.get("stream_start"))
    if start:
        return max(0.0, time.time() - start)
    return None


def _auto_post(s, clip):
    """Upload one live clip to YouTube when the owner asked for it and cleared rights."""
    if not s.get("auto_post"):
        return
    if not s.get("rights_ok"):
        clip.setdefault("post", {})["youtube"] = {
            "status": "waiting_for_rights",
            "note": "Tick the rights box before ClipBlitz will upload this stream.",
        }
        return
    path = os.path.join(CONFIG["data_dir"], "clips", os.path.basename(clip.get("file") or ""))
    if not os.path.isfile(path):
        clip.setdefault("post", {})["youtube"] = {"status": "error", "note": "clip file missing"}
        return
    if not social.youtube_connected():
        clip.setdefault("post", {})["youtube"] = {
            "status": "not_connected",
            "note": "Connect YouTube in Connect, then this clip can be posted.",
        }
        return
    try:
        link = social.youtube_upload(
            path,
            clip.get("title") or "Live clip",
            clip.get("description") or "",
            clip.get("hashtags") or [],
            s.get("privacy") or "unlisted",
        )
        clip.setdefault("post", {})["youtube"] = {"status": "published", "link": link}
    except Exception as e:
        clip.setdefault("post", {})["youtube"] = {"status": "error",
                                                  "note": str(e)[:240]}


def post_clip(vid, filename, privacy=None):
    """Post one already-rendered live clip after the owner has cleared rights."""
    with _LOCK:
        _load_sessions()
        s = _SESSIONS.get(vid)
        if not s:
            raise RuntimeError("Unknown live session.")
        clip = next((c for c in (s.get("clips") or [])
                     if os.path.basename(c.get("file") or "") == os.path.basename(filename)), None)
        if not clip:
            raise RuntimeError("That clip is not in this session.")
        if not s.get("rights_ok"):
            raise RuntimeError("Tick the rights box before uploading this stream.")
        path = os.path.join(CONFIG["data_dir"], "clips", os.path.basename(clip.get("file") or ""))
        if not os.path.isfile(path):
            raise RuntimeError("The clip file is missing.")
        if not social.youtube_connected():
            raise RuntimeError("Connect YouTube on the Connect screen first.")
        link = social.youtube_upload(
            path, clip.get("title") or "Live clip", clip.get("description") or "",
            clip.get("hashtags") or [], privacy or s.get("privacy") or "unlisted")
        clip.setdefault("post", {})["youtube"] = {"status": "published", "link": link}
        _save(s)
        return clip


def set_settings(vid, auto_post=None, privacy=None, rights_ok=None, render_policy=None):
    with _LOCK:
        _load_sessions()
        s = _SESSIONS.get(vid)
        if not s:
            raise RuntimeError("Unknown live session.")
        if auto_post is not None:
            s["auto_post"] = bool(auto_post)
        if privacy is not None:
            s["privacy"] = privacy if privacy in ("public", "unlisted", "private") else "unlisted"
        if rights_ok is not None:
            s["rights_ok"] = bool(rights_ok)
        if render_policy in ("quiet", "instant"):
            s["render_policy"] = render_policy
        _save(s)
        return _summary(s)


def _render_one(s, spike, total):
    """Download + render one spike. Safe to call repeatedly; finished spikes skip."""
    if any(c.get("spike_key") == spike.get("key") for c in (s.get("clips") or [])):
        return None
    _download_subtitles(s)
    words = _words(s)
    section, dur = _download_section(s, spike)
    clip = _render_section(s, spike, section, dur, words)
    clip["rank"] = len(s.get("clips") or []) + 1
    s.setdefault("clips", []).append(clip)
    _auto_post(s, clip)
    _save(s)
    return clip


def _maybe_render_live(s):
    """Render one remembered spike during a quiet patch, not while chat is exploding."""
    if s.get("status") != "watching":
        return
    now = _stream_now(s)
    if now is None:
        return
    policy = s.get("render_policy") or "quiet"
    scan_every = 5 if policy == "instant" else 20
    if now - float(s.get("last_spike_scan") or 0) >= scan_every:
        rows = _load_messages(s)
        if len(rows) >= 6:
            s["spikes"] = detect_spikes(
                rows, before=float(s.get("before") or DEFAULT_BEFORE),
                after=float(s.get("after") or DEFAULT_AFTER),
                max_clips=int(s.get("max_clips") or DEFAULT_MAX_CLIPS),
                duration=None)
            s["last_spike_scan"] = round(now, 1)
            _save(s)
    lead = 2 if policy == "instant" else 6
    pending = [sp for sp in (s.get("spikes") or [])
               if not any(c.get("spike_key") == sp.get("key") for c in (s.get("clips") or []))
               and float(sp.get("end") or 0) + lead <= now]
    if not pending:
        return
    if now - float(s.get("last_render") or 0) < (8 if policy == "instant" else 45):
        return
    spike = max(pending, key=lambda x: (float(x.get("score") or 0), int(x.get("messages") or 0)))
    if policy != "instant":
        rows = _load_messages(s)
        recent = [m for m in rows if float(m.get("t") or 0) >= now - 20]
        rate = len(recent) / 20.0
        burst_secs = max(1.0, float(spike.get("burst_end") or 0) - float(spike.get("burst_start") or 0))
        spike_rate = float(spike.get("messages") or 0) / burst_secs
        # "Chat is low" is relative to this stream and this spike, not a global number.
        threshold = max(0.45, spike_rate * 0.35)
        if rate > threshold:
            return
    s["last_render"] = round(now, 1)
    s["stage"] = "chat is quiet - rendering a saved spike"
    s["progress"] = min(94, 30 + int(55 * len(s.get("clips") or []) / max(1, len(s.get("spikes") or []))))
    _save(s)
    try:
        _render_one(s, spike, len(s.get("spikes") or []))
        s["stage"] = "clip saved - still watching"
        _save(s)
    except Exception as e:
        s.setdefault("clip_errors", []).append({"spike": spike.get("id"),
                                                "error": str(e)[:300]})
        s["last_error"] = str(e)[:300]
        _save(s)


def _finalize(s):
    s["status"] = "finalizing"
    s["stage"] = "stream ended - checking the recording"
    s["progress"] = max(10, int(s.get("progress") or 0))
    _save(s)
    try:
        meta = _probe_and_update(s)
    except Exception:
        meta = {}
    if meta.get("is_live") and not s.get("force_finalize"):
        s["status"] = "watching"
        s["stage"] = "the stream is still live"
        _save(s)
        return
    if meta.get("is_live") and s.get("force_finalize"):
        # "Render now" is explicit: use the DVR from the live stream and make clips
        # immediately instead of waiting for the broadcast to end.
        s["force_finalize"] = False
        s["stage"] = "rendering the spikes saved so far"
        _save(s)

    # If we were away for the whole stream, replay gives us the missed chat.
    if s.get("platform") != "twitch" and int(s.get("message_count") or 0) < 100:
        s["stage"] = "reading the live chat replay"
        _save(s)
        try:
            _collect_replay(s)
        except Exception:
            pass

    rows = _load_messages(s)
    s["message_count"] = max(int(s.get("message_count") or 0), len(rows))
    spikes = detect_spikes(rows, before=float(s.get("before") or DEFAULT_BEFORE),
                           after=float(s.get("after") or DEFAULT_AFTER),
                           max_clips=int(s.get("max_clips") or DEFAULT_MAX_CLIPS),
                           duration=s.get("duration"))
    s["spikes"] = spikes
    s["stage"] = "measuring chat spikes"
    s["progress"] = 22
    _save(s)
    if not spikes:
        s["status"] = "done"
        s["progress"] = 100
        s["stage"] = "no chat spikes found"
        s["empty_reason"] = ("The chat stayed flat (or had no usable timestamps). "
                             "Try a stream with a busy chat.")
        _save(s)
        return

    s["stage"] = "downloading source captions"
    s["progress"] = 28
    _save(s)
    _download_subtitles(s)
    words = _words(s)

    done = {c.get("spike_key") for c in (s.get("clips") or [])}
    for i, spike in enumerate(spikes, 1):
        if spike.get("key") in done:
            continue
        s["stage"] = "downloading clip %d/%d" % (i, len(spikes))
        s["progress"] = 30 + int(55 * (i - 1) / max(1, len(spikes)))
        _save(s)
        try:
            s["stage"] = "rendering clip %d/%d" % (i, len(spikes))
            _save(s)
            _render_one(s, spike, len(spikes))
            s["progress"] = 30 + int(55 * i / max(1, len(spikes)))
            _save(s)
        except Exception as e:
            s.setdefault("clip_errors", []).append({"spike": spike.get("id"),
                                                    "error": str(e)[:300]})
            _save(s)
    s["status"] = "done"
    s["progress"] = 100
    s["stage"] = "%d clip(s) ready" % len(s.get("clips") or [])
    if not s.get("clips"):
        s["empty_reason"] = "The spikes were found, but no section could be downloaded/rendered."
    _save(s)


def _run_twitch(vid):
    s = _SESSIONS.get(vid)
    if not s:
        return
    try:
        while not _terminal(s):
            if s.get("status") == "finalizing":
                _finalize(s)
                return
            if s.get("status") == "waiting":
                try:
                    meta = _probe_twitch(s.get("url") or "")
                except Exception:
                    meta = {"unknown": True}
                if meta.get("is_live"):
                    s["status"] = "watching"
                    s["stream_start"] = meta.get("stream_start") or s.get("stream_start")
                    s["title"] = meta.get("title") or s.get("title")
                    s["channel"] = meta.get("channel") or s.get("channel")
                    s["stage"] = "watching Twitch chat"
                    _save(s)
                    _twitch_chat(s)
                else:
                    s["stage"] = "waiting for Twitch to go live"
                    _save(s)
                    time.sleep(20)
            elif s.get("status") == "watching":
                _twitch_chat(s)
            else:
                time.sleep(5)
    except Exception as e:
        with _LOCK:
            s["status"] = "error"
            s["stage"] = "Twitch watcher failed"
            s["error"] = str(e)[:500]
            _save(s)


def _run(vid):
    s = _SESSIONS.get(vid)
    if not s:
        return
    if s.get("platform") == "twitch":
        return _run_twitch(vid)
    try:
        seen = _load_chat_ids(s)
        while not _terminal(s):
            status = s.get("status")
            if status in ("finalizing", "rendering"):
                _finalize(s)
                return
            if status in ("watching", "waiting"):
                last_probe = float(s.get("last_meta_probe") or 0)
                if _now() - last_probe > 60:
                    meta = _probe_and_update(s)
                    if meta.get("is_live"):
                        if s.get("status") != "watching":
                            s["status"] = "watching"
                            s["stage"] = "watching live chat"
                            _save(s)
                    elif meta.get("ended"):
                        s["status"] = "finalizing"
                        s["stage"] = "stream ended - preparing clips"
                        _save(s)
                        _finalize(s)
                        return
                    elif meta.get("upcoming"):
                        s["status"] = "waiting"
                        s["stage"] = "waiting for the stream to start"
                        _save(s)
                    else:
                        s["status"] = "waiting"
                        s["stage"] = "waiting for a live signal"
                        _save(s)

            if s.get("status") == "watching":
                try:
                    cont = s.get("continuation") or _initial_chat(vid, replay=False)
                    actions, nxt, timeout_ms = _post_chat(cont, replay=False)
                    msgs = [m for m in (_message(a, s) for a in actions) if m]
                    _append_messages(s, msgs, seen)
                    s["continuation"] = nxt
                    s["last_poll"] = _now()
                    s["errors"] = 0
                    s["stage"] = "watching live chat"
                    _save(s)
                    _maybe_render_live(s)
                    time.sleep(max(2.0, min(15.0, (timeout_ms or 5000) / 1000.0)))
                except Exception as e:
                    s["errors"] = int(s.get("errors") or 0) + 1
                    s["last_error"] = str(e)[:300]
                    s["continuation"] = ""
                    _save(s)
                    if s["errors"] >= 8:
                        s["status"] = "error"
                        s["stage"] = "lost the live chat"
                        s["error"] = str(e)[:400]
                        _save(s)
                        return
                    time.sleep(min(30, 3 * s["errors"]))
            else:
                time.sleep(20)
    except Exception as e:
        with _LOCK:
            s["status"] = "error"
            s["stage"] = "live watcher failed"
            s["error"] = str(e)[:500]
            _save(s)


# Load persisted state when imported, but do not start any threads here: the server
# calls resume() once it is ready, and tests can call the pure helpers safely.
_load_sessions()
