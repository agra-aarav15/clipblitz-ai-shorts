"""ClipBlitz Studio web server — stdlib ThreadingHTTPServer on :4300.

  GET  /                       web UI (Studio + Candidate Lab + Connect tabs)
  GET  /api/health             capabilities report (+ engines[] + measured hardware)
  GET  /api/lan                LAN URLs for opening the studio on a phone
  GET  /api/styles             caption style presets
  GET  /api/jobs               persisted job summaries (survives refresh/restart)
  POST /api/upload?name=&style=&position=&scale=&auto_post=&privacy=   (raw file body, streamed)
  POST /api/from_url?url=&…    YouTube/media URL → yt-dlp download → full pipeline
  POST /api/demo               generated test video through the full pipeline
  GET  /api/job/<id>[?light=1] status + clips + candidates (+ transcript unless light)
  POST /api/render             {job_id, cand_index, style?}  render/re-render one candidate
  POST /api/custom             {job_id, start, end, style?}   cut a user-dragged window
  PATCH /api/job/<id>/meta/<i> {title, description, hashtags}   edit before posting
  POST /api/post               {job_id, index, platforms:[...]}  queue a post
  GET  /api/social/status      YouTube connection state
  GET  /api/social/youtube/start        -> {url} to open Google consent
  GET  /oauth/youtube/callback?code=    -> stores token, shows success page
  POST /api/social/youtube/disconnect
  GET  /clips/<file>           served with Range support for <video> playback
  GET  /media/<file>           source uploads (transcript seeking / custom cuts)
"""

import json
import os
import re
import socket
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import captions, ffmpeg_tools, hardware, learning, pipeline, social, virality
from .config import CONFIG, ffmpeg_available, stt_mode, ytdlp_available

from .config import app_root

ROOT = app_root()
WEB = os.path.join(ROOT, "web")
MAX_UPLOAD = 2 * 1024 ** 3

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")


class QuietServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that stops spamming tracebacks when a browser aborts a
    stream mid-response (WinError 10053 / broken pipe) — normal browser behaviour."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def _parse_range(header, size):
    """bytes=(\\d*)-(\\d*) → clamped (start, end). Degenerate ranges fall back to full."""
    start, end = 0, size - 1
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = min(int(m.group(1)), size - 1)
        if m.group(2):
            end = min(int(m.group(2)), size - 1)
    if start > end:
        start, end = 0, size - 1
    return start, end


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _write(self, data):
        try:
            self.wfile.write(data)
            return True
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return False

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self._write(data)

    def _file(self, path, ctype, cache="no-store"):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self._write(data)

    # ---------- GET ----------

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/lan":
            return self._json(200, {"port": CONFIG["port"], "urls": _lan_urls(CONFIG["port"])})
        if path == "/api/health":
            yt_ok = False
            if social.youtube_connected():
                yt_ok = social.youtube_channel() is not None  # real token check
            from .brains import brains
            from . import hardware
            return self._json(200, {
                "ok": True, "name": "ClipBlitz Studio", "version": "4.0.0",
                "engine": "B2 Pro X", "default_engine": CONFIG.get("engine_default", "b2"),
                "engines": [
                    {"id": "prox", "name": "ProX v5",
                     "note": "story-first cuts, judged and quality-gated"},
                    {"id": "b2", "name": "B2 Pro X",
                     "note": "cuts on shot boundaries, film grade, sound leads the cut"},
                    {"id": "both", "name": "Both engines",
                     "note": "one analysis pass, both cuts side by side"},
                ],
                "hardware": hardware.profile(),
                "ffmpeg": ffmpeg_available(), "stt": stt_mode(),
                "ai_picker": bool(brains()), "top_n": CONFIG["top_n"],
                "ytdlp": ytdlp_available(), "youtube_ready": yt_ok,
                "brains": [b["name"] for b in brains()],
                # the rights gate's options come from the server so the UI copy can
                # never drift from what the backend actually stores
                "rights": pipeline.RIGHTS, "rights_note": pipeline.RIGHTS_NOTE,
            })
        if path == "/api/styles":
            return self._json(200, captions.styles_for_api())
        if path == "/api/jobs":
            jobs = sorted(pipeline.JOBS.values(), key=lambda j: -j.get("created", 0))
            return self._json(200, [{
                "id": j["id"], "name": j.get("name"), "status": j.get("status"),
                "stage": j.get("stage"), "progress": j.get("progress"),
                "clips": len(j.get("clips", [])), "created": j.get("created"),
                "engine": j.get("engine_id", "b2"),
                "rights_ok": j.get("rights_ok"),
                "top_score": max([c.get("score", 0) for c in j.get("clips", [])], default=0),
            } for j in jobs[:20]])
        if path == "/api/learning":
            return self._json(200, learning.profile())
        if path == "/api/keys":
            from . import keys
            return self._json(200, keys.status())
        if path == "/api/social/status":
            return self._json(200, {
                "youtube": {"connected": social.youtube_connected(),
                            "configured": social.youtube_configured(),
                            "channel": social.youtube_channel() if social.youtube_connected() else None},
                "assisted": list(social.ASSISTED.keys()),
            })
        if path == "/api/social/youtube/diagnose":
            return self._json(200, social.youtube_diagnose())
        if path == "/api/social/youtube/start":
            if not social.youtube_configured():
                return self._json(400, {"error": "CB_YT_CLIENT_ID / CB_YT_CLIENT_SECRET missing in .env — see SETUP-YOUTUBE.md"})
            return self._json(200, {"url": social.youtube_auth_url()})
        if path == "/oauth/youtube/callback":
            code = qs.get("code", [""])[0]
            if not code:
                return self._file(self._success_page("Google did not return a code.", False),
                                  "text/html; charset=utf-8")
            try:
                social.youtube_exchange(code)
                return self._file(self._success_page(
                    "YouTube connected. Close this tab and go back to B2 Pro X.", True),
                    "text/html; charset=utf-8")
            except Exception as e:
                return self._file(self._success_page(f"Token exchange failed: {e}", False),
                                  "text/html; charset=utf-8")

        if path == "/" or path == "/index.html":
            return self._file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
        if path == "/app.js":
            return self._file(os.path.join(WEB, "app.js"), "text/javascript")
        if path == "/styles.css":
            return self._file(os.path.join(WEB, "styles.css"), "text/css")
        if path == "/manifest.webmanifest":
            return self._file(os.path.join(WEB, "manifest.webmanifest"),
                              "application/manifest+json")
        icon = re.fullmatch(r"/icons/([\w.-]+\.png)", path)
        if icon:
            return self._file(os.path.join(WEB, "icons", icon.group(1)), "image/png",
                              cache="public, max-age=31536000, immutable")
        # self-hosted webfonts — [\w-]+ cannot contain '/' or '..', so this is traversal-safe
        font = re.fullmatch(r"/fonts/([\w-]+\.woff2)", path)
        if font:
            return self._file(os.path.join(WEB, "fonts", font.group(1)), "font/woff2",
                              cache="public, max-age=31536000, immutable")

        job_m = re.fullmatch(r"/api/job/(\w+)", path)
        if job_m:
            info = pipeline.JOBS.get(job_m.group(1))
            if not info:
                return self._json(404, {"error": "unknown job"})
            if qs.get("light") and isinstance(info.get("segments"), list):
                slim = {k: v for k, v in info.items() if k != "segments"}
                return self._json(200, slim)
            return self._json(200, info)

        media = re.fullmatch(r"/media/([\w.-]+)", path)
        if media:
            # uploads first, then the data dir itself — the generated demo source lives
            # there, and the Transcript player needs it like any other source video.
            # [\w.-]+ cannot contain '/' or '..', so both lookups are traversal-safe.
            name = media.group(1)
            for base in (os.path.join(CONFIG["data_dir"], "uploads"), CONFIG["data_dir"]):
                cand = os.path.join(base, name)
                if os.path.isfile(cand):
                    return self._serve_file_stream(cand)
            return self._json(404, {"error": "not found"})

        clip = re.fullmatch(r"/clips/([\w.-]+)", path)
        if clip:
            return self._serve_file_stream(os.path.join(CONFIG["data_dir"], "clips", clip.group(1)))

        self._json(404, {"error": "not found"})

    def _success_page(self, msg, ok=True):
        """Monochrome result page for the OAuth redirect. Inline styles + system fonts:
        it renders before the app's own CSS has any reason to be loaded."""
        mark = ("M4.5 12.5l5 5L19.5 7" if ok else "M6 6l12 12M18 6L6 18")
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<meta http-equiv='refresh' content='4;url=/'>"
                "<title>ClipBlitz Studio</title>"
                "<style>body{background:#050505;color:#fff;font-family:system-ui,Segoe UI,sans-serif;"
                "display:grid;place-items:center;height:100vh;margin:0}"
                "div{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);"
                "backdrop-filter:blur(24px);padding:40px 56px;border-radius:24px;"
                "font-size:19px;text-align:center;max-width:520px;line-height:1.5;"
                "box-shadow:0 24px 64px rgba(0,0,0,.55)}"
                "svg{width:30px;height:30px;fill:none;stroke:#fff;stroke-width:1.8;"
                "stroke-linecap:round;stroke-linejoin:round;margin-bottom:16px}"
                "small{color:rgba(255,255,255,.4);font-size:13px;display:block;margin-top:16px;"
                "letter-spacing:.12em;text-transform:uppercase}</style></head><body><div>"
                f"<svg viewBox='0 0 24 24'><path d='{mark}'/></svg><br>" + msg +
                "<small>returning to ClipBlitz Studio</small></div></body></html>").encode("utf-8")

    # ---------- POST ----------

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)

        def json_body():
            length = self._safe_length()
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return None

        if path == "/api/demo":
            return self._demo(qs)
        if path.startswith("/api/from_url"):
            body = json_body()
            if body is None:
                return self._json(400, {"error": "bad json"})
            return self._from_url(qs)
        if path.startswith("/api/upload"):
            return self._upload(qs)
        if path == "/api/post":
            body = json_body()
            if body is None:
                return self._json(400, {"error": "bad json"})
            return self._post_clip(body)
        if path == "/api/render":
            body = json_body()
            if body is None:
                return self._json(400, {"error": "bad json"})
            return self._render(body)
        if path == "/api/custom":
            body = json_body()
            if body is None:
                return self._json(400, {"error": "bad json"})
            return self._custom(body)
        if path == "/api/learning/reset":
            learning.reset()
            return self._json(200, learning.profile())
        rights_m = re.fullmatch(r"/api/job/(\w+)/rights", path)
        if rights_m:
            return self._rights(rights_m.group(1))
        if path == "/api/social/youtube/disconnect":
            return self._json(200, {"disconnected": social.youtube_disconnect()})
        if path == "/api/social/youtube/start":
            # the UI may POST this from the Connect tab — accept both verbs
            if not social.youtube_configured():
                return self._json(400, {"error": "CB_YT_CLIENT_ID / CB_YT_CLIENT_SECRET missing in .env — see SETUP-YOUTUBE.md"})
            return self._json(200, {"url": social.youtube_auth_url()})
        if path == "/api/keys":
            from . import keys
            body = json_body()
            if body is None:
                return self._json(400, {"error": "bad json"})
            result = keys.save({k: v for k, v in body.items() if k in keys.KEY_VARS})
            result["tests"] = {k: keys.test(k) for k in result["saved"]}
            return self._json(200, result)
        if path == "/api/keys/test":
            from . import keys
            body = json_body()
            if body is None or not body.get("which"):
                return self._json(400, {"error": "which (groq|gemini|yt_client_id|yt_client_secret) required"})
            return self._json(200, keys.test(body["which"], body.get("value")))

        self._json(404, {"error": "not found"})

    def _safe_length(self):
        try:
            return max(0, int(self.headers.get("Content-Length", 0)))
        except (TypeError, ValueError):
            return 0

    def _engine(self, qs):
        eng = (qs.get("engine") or [CONFIG.get("engine_default", "b2")])[0]
        if eng not in ("prox", "b2", "both"):
            eng = CONFIG.get("engine_default", "b2")
        return eng if eng in ("prox", "b2", "both") else "b2"

    def _render_refused(self):
        hw = hardware.profile()
        if not hw.get("render_capable"):
            return self._json(503, {"error": hw["reason"], "render_capable": False})
        return None

    def _opts(self, qs):
        try:
            scale = float((qs.get("scale") or ["1"])[0])
        except ValueError:
            scale = 1.0
        style = (qs.get("style") or ["wordpop"])[0]
        framing = (qs.get("framing") or ["blur"])[0]
        try:
            top_n = int((qs.get("top_n") or [CONFIG["top_n"]])[0])
        except ValueError:
            top_n = CONFIG["top_n"]
        return {
            "style": style if style in {s["id"] for s in captions.styles_for_api()} else "wordpop",
            "framing": framing if framing in ("blur", "crop", "crop-left", "crop-right") else "blur",
            "position": (qs.get("position") or ["bottom"])[0],
            "scale": min(1.6, max(0.5, scale)),
            "top_n": min(6, max(1, top_n)),
            "auto_post": (qs.get("auto_post") or ["0"])[0] == "1",
            "privacy": (qs.get("privacy") or [CONFIG["privacy"]])[0],
            "engine": self._engine(qs),
        }

    def _demo(self, qs):
        if not ffmpeg_available():
            return self._json(500, {"error": "ffmpeg not found — see README setup"})
        refused = self._render_refused()
        if refused:
            return refused
        os.makedirs(CONFIG["data_dir"], exist_ok=True)
        demo = os.path.join(CONFIG["data_dir"], "demo_source.mp4")
        ffmpeg_tools.make_demo_video(demo)
        o = self._opts(qs)
        job_id = pipeline.new_job("demo_source.mp4", style=o["style"], position=o["position"],
                                  size_scale=o["scale"], auto_post=o["auto_post"],
                                  privacy=o["privacy"], demo=True, framing=o["framing"],
                                  top_n=o["top_n"], engine=o["engine"],
                                  source={"kind": "demo", "label": "generated demo clip"})
        pipeline.start(job_id, demo)
        self._json(200, {"job_id": job_id})

    def _from_url(self, qs):
        refused = self._render_refused()
        if refused:
            return refused
        url = (qs.get("url") or [""])[0].strip()
        if not url.lower().startswith(("http://", "https://")):
            return self._json(400, {"error": "url query parameter required"})
        o = self._opts(qs)
        name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or url[:60]
        job_id = pipeline.new_job(name, style=o["style"], position=o["position"],
                                  size_scale=o["scale"], auto_post=o["auto_post"],
                                  privacy=o["privacy"], framing=o["framing"],
                                  top_n=o["top_n"], engine=o["engine"],
                                  source={"kind": "url", "url": url})
        pipeline.start_from_url(job_id, url)
        return self._json(200, {"job_id": job_id})

    def _upload(self, qs):
        if not ffmpeg_available():
            return self._json(500, {"error": "ffmpeg not found — see README setup"})
        refused = self._render_refused()
        if refused:
            return refused
        length = self._safe_length()
        if not 0 < length <= MAX_UPLOAD:
            return self._json(400, {"error": f"file must be 0 < size <= {MAX_UPLOAD} bytes"})
        name = re.sub(r"[^\w.-]", "_", (qs.get("name") or ["video.mp4"])[0]) or "video.mp4"
        o = self._opts(qs)
        os.makedirs(os.path.join(CONFIG["data_dir"], "uploads"), exist_ok=True)
        dest = os.path.join(CONFIG["data_dir"], "uploads", f"{int(time.time())}_{name}")
        # stream straight to disk — the size is already checked via Content-Length
        with open(dest, "wb") as f:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        if not ffmpeg_tools.is_readable(dest):  # fail fast: corrupt/incomplete video
            os.remove(dest)
            return self._json(400, {
                "error": "This video file can't be read — it's probably an incomplete download "
                         "(the MP4 index 'moov atom' is missing). Re-download the video and try again."})
        job_id = pipeline.new_job(name, style=o["style"], position=o["position"],
                                  size_scale=o["scale"], auto_post=o["auto_post"],
                                  privacy=o["privacy"], framing=o["framing"],
                                  top_n=o["top_n"], engine=o["engine"],
                                  source={"kind": "upload", "label": name})
        pipeline.start(job_id, dest)
        self._json(200, {"job_id": job_id, "bytes": length})

    def _render(self, body):
        job_id = body.get("job_id", "")
        style = body.get("style")
        clip, err = pipeline.render_candidate(
            job_id, body.get("cand_index"), style=style,
            position=body.get("position"), size_scale=body.get("scale"),
            engine=body.get("engine"))
        if err:
            return self._json(400, {"error": err})
        return self._json(200, {"clip": clip})

    def _custom(self, body):
        clip, err = pipeline.render_custom(
            body.get("job_id", ""), body.get("start"), body.get("end"), style=body.get("style"),
            engine=body.get("engine"))
        if err:
            return self._json(400, {"error": err})
        return self._json(200, {"clip": clip})

    def _rights(self, job_id):
        """The rights gate: record the owner's answer for this job, then resume the
        auto-post the job was holding if it was waiting on exactly this."""
        job_ = pipeline.JOBS.get(job_id)
        if not job_:
            return self._json(404, {"error": "unknown job"})
        length = self._safe_length()
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        answer = (body.get("answer") or "").strip()
        if not pipeline.set_rights(job_, answer):
            return self._json(400, {"error": "answer must be one of: "
                                           + ", ".join(sorted(pipeline.RIGHTS_IDS))})
        resumed = pipeline.resume_autopost(job_id)
        return self._json(200, {"rights_ok": answer, "autopost_resumed": resumed})

    def _post_clip(self, body):
        job_ = pipeline.JOBS.get(body.get("job_id", ""))
        if not job_:
            return self._json(404, {"error": "unknown job"})
        if not job_.get("rights_ok"):
            # One honest question before anything leaves this machine. Answering it is a
            # single click; the clip file itself is never withheld, so posting it by hand
            # stays entirely the owner's call.
            return self._json(409, {"error": "Confirm your rights for this job first.",
                                    "rights_required": True,
                                    "rights": pipeline.RIGHTS, "note": pipeline.RIGHTS_NOTE})
        try:
            index = int(body.get("index", 0))
            platforms = body.get("platforms") or []
            if not platforms or index >= len(job_["clips"]):
                return self._json(400, {"error": "need platforms[] and a valid clip index"})
        except (TypeError, ValueError):
            return self._json(400, {"error": "bad index"})
        social.post_clip(job_, index, platforms, on_update=pipeline.save)
        learning.log("post", job_["clips"][index], job_)   # a real choice, worth learning from
        return self._json(200, {"queued": platforms})

    # ---------- PATCH ----------

    def do_PATCH(self):
        m = re.fullmatch(r"/api/job/(\w+)/meta/(\d+)", urllib.parse.urlparse(self.path).path)
        if not m:
            return self._json(404, {"error": "not found"})
        job_ = pipeline.JOBS.get(m.group(1))
        if not job_ or int(m.group(2)) >= len(job_.get("clips", [])):
            return self._json(404, {"error": "unknown job or clip"})
        length = self._safe_length()
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        clip = job_["clips"][int(m.group(2))]
        meta = clip.setdefault("meta", {})
        for key in ("title", "description", "hashtags"):
            if key in body:
                meta[key] = body[key]
        pipeline.save()
        return self._json(200, {"meta": meta})

    # ---------- media streaming ----------

    def _serve_file_stream(self, path):
        if not os.path.isfile(path):
            return self._json(404, {"error": "not found"})
        size = os.path.getsize(path)
        start, end = _parse_range(self.headers.get("Range"), size)
        rng = self.headers.get("Range") and not (start == 0 and end == size - 1)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4" if path.endswith(".mp4") else
                         ("text/plain; charset=utf-8" if path.endswith((".ass", ".post.txt", ".txt")) else "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                if not self._write(chunk):
                    return  # client went away mid-stream — perfectly normal
                remaining -= len(chunk)

    def log_message(self, fmt, *args):
        print(f"[clipblitz] {fmt % args}")


def _lan_urls(port):
    """Addresses this server is reachable on from other devices (a phone on the same
    Wi-Fi). The UDP connect only picks the default-route interface — no packet is sent."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    seen, out = set(), []
    for ip in ips:
        if ip.startswith("127.") or ip in seen:
            continue
        seen.add(ip)
        out.append(f"http://{ip}:{port}")
    return out


def serve(port=None):
    port = port or CONFIG["port"]
    try:
        srv = QuietServer(("0.0.0.0", port), Handler)
    except OSError:
        print(f"ClipBlitz Studio is already running -> http://localhost:{port}  "
              f"(open that tab; or kill the old instance first)")
        sys.exit(0)
    print(f"ClipBlitz Studio v4.0.0 (engines: ProX v5 / B2 Pro X / Both)  ->  "
          f"http://localhost:{port}", flush=True)
    from . import hardware
    hw = hardware.profile()
    for u in _lan_urls(port):
        print(f"  your phone (same Wi-Fi)  {u}", flush=True)
    print(f"  ffmpeg={ffmpeg_available()} stt={stt_mode()} ai={bool(CONFIG['ai_key'])} "
          f"yt-dlp={ytdlp_available()} youtube_configured={social.youtube_configured()} "
          f"render_capable={hw.get('render_capable')}", flush=True)
    if not hw.get("render_capable"):
        print(f"  {hw.get('reason')}", flush=True)
    srv.serve_forever()
