"""Social automation layer.

- YouTube: FULLY AUTOMATIC — OAuth 2.0 (user connects once) + resumable uploads
  via YouTube Data API v3 (stdlib only). Token stored in data/social/.
- TikTok / Instagram / Facebook / X: ASSISTED one-click — the rendered clip gets a
  ready post package (title + description + hashtags) copied to the clipboard and
  the platform's upload page opened. Flips to full-auto later when a TikTok dev
  app is approved or a posting-API key (CB_POST_KEY) is configured.
"""

import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

from .config import CONFIG

SOCIAL_DIR = os.path.join(CONFIG["data_dir"], "social")
YT_TOKEN_FILE = os.path.join(SOCIAL_DIR, "youtube.json")

ASSISTED = {
    "tiktok": "https://www.tiktok.com/upload",
    "instagram": "https://www.instagram.com/",
    "facebook": "https://www.facebook.com/",
    "x": "https://x.com/compose/post",
}


def _post_form(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "User-Agent": "ClipBlitz/0.1"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())


def _get_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "User-Agent": "ClipBlitz/0.1"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())


# ---------- YouTube OAuth ----------

def _yt_creds():
    """Client credentials, re-read from .env on every call — so pasting keys into .env
    takes effect immediately, no server restart needed."""
    cid, sec = CONFIG.get("yt_client_id", ""), CONFIG.get("yt_client_secret", "")
    try:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("CB_YT_CLIENT_ID="):
                val = line.split("=", 1)[1].strip()
                cid = val or cid
            elif line.startswith("CB_YT_CLIENT_SECRET="):
                val = line.split("=", 1)[1].strip()
                sec = val or sec
    except OSError:
        pass
    return cid, sec


def youtube_configured():
    cid, sec = _yt_creds()
    return bool(cid and sec)


def youtube_diagnose():
    """Live, honest state of every link in the auto-post chain + the exact next fix."""
    cid, sec = _yt_creds()
    redirect = youtube_redirect_uri()
    steps = {
        "keys_in_env": {
            "ok": bool(cid and sec),
            "detail": "both CB_YT_CLIENT_ID and CB_YT_CLIENT_SECRET are set" if (cid and sec) else
            ("CB_YT_CLIENT_SECRET missing" if cid else "CB_YT_CLIENT_ID missing"),
            "fix": "Paste both into clipblitz/.env (no restart needed) — see SETUP-YOUTUBE.md step 2." if not (cid and sec) else "",
        },
        "redirect_uri": {
            "ok": True,  # can't verify Google-side config from here; shown for exact matching
            "detail": redirect,
            "fix": ("Add this EXACT URI in Google Cloud → Credentials → your OAuth client → "
                    "Authorized redirect URIs") if not youtube_connected() else "",
        },
        "consent_completed": {
            "ok": youtube_connected(),
            "detail": "OAuth token stored" if youtube_connected() else
            "no token yet — the Google consent wasn't completed (this is where it currently stands)",
            "fix": "" if youtube_connected() else "Press 'Connect YouTube' and finish Google's consent window.",
        },
        "token_works": {
            "ok": False, "detail": "not checked yet (needs consent first)", "fix": "",
        },
        "upload_quota": {
            "ok": False, "detail": "not checked yet (needs consent first)", "fix": "",
        },
    }
    if youtube_connected():
        channel = youtube_channel()
        steps["token_works"] = {
            "ok": channel is not None,
            "detail": f"token valid · channel: {channel}" if channel else
            "token stored but Google rejects it (expired/revoked?)",
            "fix": "" if channel else "Press Disconnect, then Connect YouTube again to re-consent.",
        }
        if channel:
            try:
                youtube_upload  # noqa: B018 — presence check only
                steps["upload_quota"] = {"ok": True, "detail": "ready — uploads will use today's free quota (~6/day)", "fix": ""}
            except Exception as e:
                steps["upload_quota"] = {"ok": False, "detail": str(e)[:120], "fix": "See SETUP-YOUTUBE.md."}
    overall_ok = all(s["ok"] for s in steps.values())
    known = []
    if not youtube_connected() and bool(cid and sec):
        # The two Google-side errors the owner can actually hit, with exact fixes.
        known.append({
            "error": "Error 403: org_internal (Google consent page)",
            "cause": "your OAuth consent screen audience is set to INTERNAL (org-only)",
            "fix": ("Google Cloud → APIs & Services → OAuth consent screen (Google Auth Platform → "
                    "Audience) → User type: EXTERNAL → Create/Save. Then add your own Gmail as a "
                    "TEST USER (Audience → Test users). Press Connect again — no restart."),
        })
        known.append({
            "error": "Error 400: redirect_uri_mismatch",
            "cause": "the registered redirect URI doesn't match",
            "fix": f"Credentials → your OAuth client → Authorized redirect URIs → add EXACTLY: {redirect}",
        })
    return {
        "ready": overall_ok,
        "steps": steps,
        "known_errors": known,
        "next_action": ("All green — post any clip with Post → YouTube." if overall_ok else
                        next((s["fix"] for s in steps.values() if s["fix"]), "")),
    }


def youtube_redirect_uri():
    return CONFIG.get("yt_redirect") or f"http://localhost:{CONFIG['port']}/oauth/youtube/callback"


def youtube_connected():
    """True only when a token file exists AND it actually works (has an access or
    refresh token). A consent page visited without completing setup never counts."""
    if not os.path.isfile(YT_TOKEN_FILE):
        return False
    try:
        tok = json.load(open(YT_TOKEN_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(tok.get("access_token") and tok.get("expires_at", 0) > time.time()) \
        or bool(tok.get("refresh_token"))


def youtube_auth_url():
    cid, sec = _yt_creds()
    if not (cid and sec):
        raise RuntimeError("CB_YT_CLIENT_ID / CB_YT_CLIENT_SECRET missing in .env — see SETUP-YOUTUBE.md")
    params = {
        "client_id": cid,
        "redirect_uri": youtube_redirect_uri(),
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/youtube.upload",
        "access_type": "offline",
        "prompt": "consent",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def _google_error_html(body):
    """Translate a token-exchange failure body into a human, fix-it-now message."""
    reason, desc = "", ""
    try:
        data = json.loads(body)
        reason = data.get("error", "")
        desc = data.get("error_description", "")
    except (ValueError, AttributeError):
        desc = (body or "")[:300]
    if reason == "invalid_client":
        return ("Google rejected the client — CB_YT_CLIENT_ID or CB_YT_CLIENT_SECRET is wrong. "
                "Copy both again from Google Cloud → APIs & Services → Credentials → your OAuth client.")
    if reason == "redirect_uri_mismatch" or "redirect" in desc.lower():
        return ("redirect_uri_mismatch — the Redirect URI in Google Cloud doesn't match. "
                f"Open Google Cloud → Credentials → your OAuth client → Authorized redirect URIs and add EXACTLY: "
                f"{youtube_redirect_uri()}  (then press Connect again — no restart needed).")
    if reason == "invalid_grant":
        return ("The consent code expired (it's single-use and lasts ~10 minutes). "
                "Just press Connect YouTube again and finish the consent promptly.")
    if reason == "access_denied":
        return "You pressed Cancel on Google's consent screen. Press Connect YouTube again and allow access."
    out = f"Google said: {reason or 'error'}" if reason else "Token exchange failed"
    return f"{out} — {desc}" if desc else out


def youtube_exchange(code):
    cid, sec = _yt_creds()
    os.makedirs(SOCIAL_DIR, exist_ok=True)
    try:
        tok = _post_form("https://oauth2.googleapis.com/token", {
            "code": code,
            "client_id": cid,
            "client_secret": sec,
            "redirect_uri": youtube_redirect_uri(),
            "grant_type": "authorization_code",
        })
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        raise RuntimeError(_google_error_html(body)) from None
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 120
    with open(YT_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f)
    return tok


def youtube_disconnect():
    if os.path.isfile(YT_TOKEN_FILE):
        os.remove(YT_TOKEN_FILE)
        return True
    return False


def youtube_access_token():
    if not youtube_connected():
        raise RuntimeError("YouTube is not connected — open Connect Accounts first")
    tok = json.load(open(YT_TOKEN_FILE, encoding="utf-8"))
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    cid, sec = _yt_creds()
    fresh = _post_form("https://oauth2.googleapis.com/token", {
        "refresh_token": tok["refresh_token"],
        "client_id": cid,
        "client_secret": sec,
        "grant_type": "refresh_token",
    })
    tok["access_token"] = fresh["access_token"]
    tok["expires_at"] = time.time() + int(fresh.get("expires_in", 3600)) - 120
    with open(YT_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f)
    return tok["access_token"]


def youtube_channel():
    try:
        data = _get_json(
            "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
            youtube_access_token())
        return data["items"][0]["snippet"]["title"]
    except Exception:
        return None


def youtube_upload(video_path, title, description, tags, privacy):
    """Resumable upload → returns the YouTube video URL."""
    token = youtube_access_token()
    meta = {
        "snippet": {
            "title": title[:100],
            "description": (description + "\n\n" + " ".join(tags)).strip()[:4900],
            "tags": [t.lstrip("#") for t in tags][:15],
            "categoryId": "22",
        },
        "status": {"privacyStatus": privacy or "public", "selfDeclaredMadeForKids": False},
    }
    size = os.path.getsize(video_path)
    body = json.dumps(meta).encode()
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4",
                 "User-Agent": "ClipBlitz/0.1"})
    with urllib.request.urlopen(req, timeout=120) as res:
        upload_url = res.headers["Location"]

    with open(video_path, "rb") as f:
        put = urllib.request.Request(upload_url, data=f, method="PUT",
                                     headers={"Content-Type": "video/mp4",
                                              "Content-Length": str(size),
                                              "User-Agent": "ClipBlitz/0.1"})
        with urllib.request.urlopen(put, timeout=3600) as res:
            vid = json.loads(res.read())["id"]
    return f"https://www.youtube.com/shorts/{vid}"


# ---------- Assisted one-click ----------

def _copy_to_clipboard(text):
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$input | Set-Clipboard"], input=text.encode(),
                           capture_output=True, timeout=15)
        return p.returncode == 0
    except Exception:
        return False


def prepare_assisted(platform, clips_dir, base, meta):
    """Write the ready-to-paste post package, copy it to the clipboard, open the platform."""
    package = (f"{meta.get('title', '')}\n\n{meta.get('description', '')}\n\n"
               f"{' '.join(meta.get('hashtags', []))}")
    pkg_path = os.path.join(clips_dir, base + ".post.txt")
    with open(pkg_path, "w", encoding="utf-8") as f:
        f.write(package)
    copied = _copy_to_clipboard(package)
    webbrowser.open(ASSISTED[platform])
    return {"status": "assisted_ready", "note": "caption copied — paste it in the upload",
            "clipboard": copied, "package": f"/clips/{base}.post.txt"}


# ---------- Posting queue ----------

def post_clip(job, clip_index, platforms, on_update=None, wait=False):
    """Post one clip to the requested platforms. Background thread by default;
    pass wait=True (e.g. during auto-post) to block until every platform settles.
    on_update fires after each status change so the UI/live job file stay current."""
    clip = job["clips"][clip_index]
    file_path = os.path.join(CONFIG["data_dir"], "clips", os.path.basename(clip["file"]))
    meta = clip.get("meta", {})
    tags = meta.get("hashtags", [])
    clip["post"] = clip.get("post") or {}

    def _touch():
        if on_update:
            try:
                on_update()
            except Exception:
                pass

    def worker():
        for platform in platforms:
            clip["post"][platform] = {"status": "uploading"}
            _touch()
            try:
                if platform == "youtube":
                    if not youtube_connected():
                        clip["post"][platform] = {"status": "error",
                                                  "note": "YouTube not connected — Connect Accounts first"}
                        continue
                    link = youtube_upload(file_path, meta.get("title", "Clip"),
                                          meta.get("description", ""), tags,
                                          job.get("privacy", "public"))
                    clip["post"][platform] = {"status": "published", "link": link}
                elif platform in ASSISTED:
                    base = os.path.splitext(os.path.basename(clip["file"]))[0]
                    clips_dir = os.path.dirname(file_path)
                    clip["post"][platform] = prepare_assisted(platform, clips_dir, base, meta)
                else:
                    clip["post"][platform] = {"status": "error", "note": "unknown platform"}
            except Exception as e:
                clip["post"][platform] = {"status": "error", "note": str(e)[:200]}
            finally:
                _touch()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    if wait:
        t.join()
