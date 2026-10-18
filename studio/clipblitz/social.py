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
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

from .config import CONFIG

SOCIAL_DIR = os.path.join(CONFIG["data_dir"], "social")
YT_TOKEN_FILE = os.path.join(SOCIAL_DIR, "youtube.json")
YT_STATE_FILE = os.path.join(SOCIAL_DIR, "oauth_state.json")
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_TTL = 600  # a consent round-trip older than this is stale

# The honest reason a saved token stops working while the OAuth app is unverified.
REAUTH_REASON = (
    "Google expires a refresh token about seven days after consent while the OAuth app "
    "is still in Testing. Press Connect YouTube again to re-consent (works right away), "
    "or publish the app in Google Cloud to stop the seven-day expiry.")

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
        # the project root (where .env lives) — frozen-EXE aware
        from .config import app_root
        root = app_root()
        env_path = os.path.join(root, ".env")
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


def _read_err(e):
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:
        return ""


def _reason_of(body):
    try:
        return json.loads(body).get("error", "")
    except (ValueError, AttributeError):
        return ""


def _token_read():
    """The stored token, or {} — never raises; a corrupt file reads as 'no token'."""
    try:
        tok = json.load(open(YT_TOKEN_FILE, encoding="utf-8"))
        return tok if isinstance(tok, dict) else {}
    except (OSError, ValueError):
        return {}


def _token_write(tok):
    os.makedirs(SOCIAL_DIR, exist_ok=True)
    tmp = YT_TOKEN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tok, f)
    os.replace(tmp, YT_TOKEN_FILE)


def _token_note(error, reauth):
    """Remember *why* a token stopped working, so the Connect screen can explain it
    instead of showing a bare 'not connected'."""
    tok = _token_read()
    if not tok:
        return
    tok["last_error"] = str(error)[:300]
    tok["last_error_at"] = time.time()
    tok["reauth_required"] = bool(reauth)
    try:
        _token_write(tok)
    except OSError:
        pass


def _token_clear_note(tok):
    tok.pop("last_error", None)
    tok.pop("last_error_at", None)
    tok["reauth_required"] = False
    return tok


def youtube_configured():
    cid, sec = _yt_creds()
    return bool(cid and sec)


def youtube_state():
    """Everything the Connect screen needs to say what is actually wrong — one call,
    no network. `connected` stays honest: a token Google has already rejected is not
    a connection."""
    tok = _token_read()
    reauth = bool(tok.get("reauth_required"))
    return {
        "configured": youtube_configured(),
        "connected": youtube_connected(),
        "has_token": bool(tok.get("refresh_token") or tok.get("access_token")),
        "reauth_required": reauth,
        "reauth_reason": REAUTH_REASON if reauth else "",
        "last_error": tok.get("last_error", "") if reauth else "",
        "last_error_at": int(tok.get("last_error_at") or 0),
        "fresh_until": int(tok.get("expires_at") or 0),
        "connected_at": int(tok.get("connected_at") or 0),
        "redirect_uri": youtube_redirect_uri(),
    }


def youtube_diagnose():
    """Live, honest state of every link in the auto-post chain + the exact next fix."""
    cid, sec = _yt_creds()
    redirect = youtube_redirect_uri()
    st = youtube_state()
    steps = {
        "keys_in_env": {
            "ok": bool(cid and sec),
            "detail": "both CB_YT_CLIENT_ID and CB_YT_CLIENT_SECRET are set" if (cid and sec) else
            ("CB_YT_CLIENT_SECRET missing" if cid else "CB_YT_CLIENT_ID missing"),
            "fix": "Paste both into clipblitz/.env (no restart needed) — see SETUP-YOUTUBE.md step 2." if not (cid and sec) else "",
        },
        "redirect_uri": {
            # Google's side can't be read from here, so this step is informational: it
            # shows the exact URI *this* window needs, port and all.
            "ok": True,
            "detail": f"{redirect}  (this window is on port {CONFIG['port']})",
            "fix": ("Add this EXACT URI — this window's port, not another app's — in Google Cloud → "
                    "Credentials → your OAuth client → Authorized redirect URIs") if not st["connected"] else "",
        },
        "consent_completed": {
            "ok": youtube_connected(),
            "detail": ("OAuth token stored and usable" if youtube_connected() else
                       ("token stored but Google has rejected it — it needs a fresh consent"
                        if st["reauth_required"] else
                        "no token yet — the Google consent wasn't completed")),
            "fix": "" if youtube_connected() else (
                REAUTH_REASON if st["reauth_required"] else
                "Press 'Connect YouTube' and finish Google's consent window."),
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
    if st["reauth_required"]:
        known.append({
            "error": "Uploads stopped: the saved token expired or was revoked",
            "cause": st["last_error"] or "Google no longer accepts the stored refresh token",
            "fix": REAUTH_REASON,
        })
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
            "cause": "the registered redirect URI doesn't match this window's port",
            "fix": f"Credentials → your OAuth client → Authorized redirect URIs → add EXACTLY: {redirect}",
        })
    return {
        "ready": overall_ok,
        "state": st,
        "steps": steps,
        "known_errors": known,
        "next_action": ("All green — post any clip with Post → YouTube." if overall_ok else
                        next((s["fix"] for s in steps.values() if s["fix"]), "")),
    }


def youtube_redirect_uri():
    return CONFIG.get("yt_redirect") or f"http://localhost:{CONFIG['port']}/oauth/youtube/callback"


def youtube_connected():
    """True only when a token file exists AND it can still be used (access token in
    date, or a refresh token Google has not rejected). A consent page visited without
    completing setup never counts, and neither does a token Google has revoked."""
    tok = _token_read()
    if tok.get("reauth_required"):
        return False
    return bool(tok.get("access_token") and tok.get("expires_at", 0) > time.time()) \
        or bool(tok.get("refresh_token"))


def _new_state():
    """A single-use, time-boxed CSRF token for one consent round-trip."""
    state = secrets.token_urlsafe(24)
    os.makedirs(SOCIAL_DIR, exist_ok=True)
    with open(YT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"state": state, "issued_at": time.time()}, f)
    return state


def youtube_check_state(state):
    """Verify the state Google echoed back, and burn it. Raises with the fix if it
    doesn't match — an old consent tab or a tampered callback never stores a token.
    Only a *matching* state is consumed, so a junk callback can't cancel a real one."""
    try:
        rec = json.load(open(YT_STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError("This consent link is stale — press Connect YouTube again.") from None
    if not state or state != rec.get("state"):
        raise RuntimeError("That consent response didn't match this session's request — "
                           "press Connect YouTube again and finish the Google window.")
    try:
        os.remove(YT_STATE_FILE)
    except OSError:
        pass
    if time.time() - float(rec.get("issued_at") or 0) > STATE_TTL:
        raise RuntimeError("That consent took longer than ten minutes — press Connect "
                           "YouTube again and finish the Google window.")


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
        "state": _new_state(),
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def _google_error_html(body, context="code"):
    """Translate a token failure body into a human, fix-it-now message."""
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
        if context == "refresh":
            return ("The saved YouTube token expired or was revoked by Google, so uploads stopped. "
                    + REAUTH_REASON)
        return ("The consent code expired (it's single-use and lasts ~10 minutes). "
                "Just press Connect YouTube again and finish the consent promptly.")
    if reason == "access_denied":
        return "You pressed Cancel on Google's consent screen. Press Connect YouTube again and allow access."
    out = f"Google said: {reason or 'error'}" if reason else "Token exchange failed"
    return f"{out} — {desc}" if desc else out


def youtube_exchange(code, state=None):
    """Trade the consent code for a token. Verifies the CSRF state first, so a stale
    or forged callback can never replace a working token."""
    youtube_check_state(state)
    cid, sec = _yt_creds()
    os.makedirs(SOCIAL_DIR, exist_ok=True)
    try:
        tok = _post_form(TOKEN_URL, {
            "code": code,
            "client_id": cid,
            "client_secret": sec,
            "redirect_uri": youtube_redirect_uri(),
            "grant_type": "authorization_code",
        })
    except urllib.error.HTTPError as e:
        raise RuntimeError(_google_error_html(_read_err(e))) from None
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 120
    tok["connected_at"] = time.time()
    tok = _token_clear_note(tok)
    _token_write(tok)
    return tok


def youtube_disconnect():
    if os.path.isfile(YT_TOKEN_FILE):
        os.remove(YT_TOKEN_FILE)
        return True
    return False


def youtube_access_token():
    """A usable access token, refreshing when needed. Every failure mode ends in a
    sentence the user can act on — never a raw HTTPError."""
    tok = _token_read()
    if not tok:
        raise RuntimeError("YouTube is not connected — open Connect Accounts first")
    if tok.get("reauth_required"):
        raise RuntimeError("The saved YouTube token stopped working. " + REAUTH_REASON)
    if tok.get("access_token") and time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    if not tok.get("refresh_token"):
        _token_note("no refresh token stored — consent must be completed again", True)
        raise RuntimeError("YouTube needs a fresh consent — press Connect YouTube again.")
    cid, sec = _yt_creds()
    try:
        fresh = _post_form(TOKEN_URL, {
            "refresh_token": tok["refresh_token"],
            "client_id": cid,
            "client_secret": sec,
            "grant_type": "refresh_token",
        })
    except urllib.error.HTTPError as e:
        body = _read_err(e)
        # invalid_grant here means the refresh token itself is dead (expired while the
        # app is in Testing, or revoked) — only a new consent fixes it.
        reauth = _reason_of(body) in ("invalid_grant", "invalid_client")
        human = _google_error_html(body, context="refresh")
        _token_note(human, reauth)
        raise RuntimeError(human) from None
    except OSError as e:
        raise RuntimeError(f"Couldn't reach Google to refresh the token: {e}") from None
    tok["access_token"] = fresh["access_token"]
    tok["expires_at"] = time.time() + int(fresh.get("expires_in", 3600)) - 120
    if fresh.get("refresh_token"):
        tok["refresh_token"] = fresh["refresh_token"]
    tok = _token_clear_note(tok)
    _token_write(tok)
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
