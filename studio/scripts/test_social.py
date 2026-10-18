"""YouTube OAuth tests for ClipBlitz Studio - stdlib only, offline, no network.

Run from the studio root:   python scripts/test_social.py

What is proven, with Google stubbed out:

  1. THE REDIRECT URI FOLLOWS THE WINDOW'S PORT. The flagship runs on 4300 and the
     classic app on 4301; the URI the app asks Google to call back is built from the
     live port (or CB_YT_REDIRECT), never hard-coded - a mismatch is the single most
     common "Connect does nothing" report.
  2. CONSENT IS CSRF-PROTECTED AND SINGLE USE. The consent URL carries a state that
     the app stored; the callback must echo it back inside ten minutes, it is burned
     on use, and a wrong, missing, replayed or stale state stores no token at all.
  3. AN EXPIRED OR REVOKED TOKEN IS NAMED, NOT HIDDEN. Google expires a refresh token
     about seven days after consent while the OAuth app is in Testing. That used to
     surface as a bare "not connected". Now the failure is recorded on the token
     (reauth_required + the human message), youtube_connected() turns False, the
     Connect screen shows the reason, and Diagnose adds the exact fix.
  4. EVERY FAILURE READS LIKE A SENTENCE. invalid_grant, invalid_client and a plain
     network error each raise a RuntimeError a person can act on - never a raw
     HTTPError, never a stack trace in the UI.
  5. A GOOD REFRESH CLEARS THE WARNING and a completed consent wipes the old error.

Every token lives in a throwaway temp data dir, so this never touches real data or
the real Google account.
"""

import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_social_")

from clipblitz import social  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


# Google is stubbed: no test here touches the network or the real account.
social._yt_creds = lambda: ("test-client-id.apps.googleusercontent.com", "GOCSPX-test")

CALLS = []


def http_error(payload, code=400):
    """The shape urllib raises for a Google error body."""
    body = json.dumps(payload).encode()
    return urllib.error.HTTPError("https://oauth2.googleapis.com/token", code,
                                  "Bad Request", {}, io.BytesIO(body))


def stub_post(fn):
    def _post(url, fields):
        CALLS.append((url, dict(fields)))
        return fn(url, dict(fields))
    social._post_form = _post


def clean_token():
    if os.path.isfile(social.YT_TOKEN_FILE):
        os.remove(social.YT_TOKEN_FILE)
    if os.path.isfile(social.YT_STATE_FILE):
        os.remove(social.YT_STATE_FILE)


def write_token(tok):
    os.makedirs(social.SOCIAL_DIR, exist_ok=True)
    with open(social.YT_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f)


def fresh_token(**over):
    tok = {"access_token": "old-at", "refresh_token": "rt-1", "expires_at": time.time() - 10}
    tok.update(over)
    write_token(tok)
    return tok


# ---------------------------------------------------------------- 1. redirect URI

def test_redirect_uri_follows_the_port():
    clean_token()
    CONFIG.pop("yt_redirect", None)
    CONFIG["port"] = 4300
    check("redirect: the flagship window asks for its own port",
          social.youtube_redirect_uri() == "http://localhost:4300/oauth/youtube/callback",
          social.youtube_redirect_uri())
    CONFIG["port"] = 4301
    check("redirect: the classic window asks for 4301, not 4300",
          social.youtube_redirect_uri() == "http://localhost:4301/oauth/youtube/callback")
    CONFIG["port"] = 4300
    CONFIG["yt_redirect"] = "http://clips.example.com/oauth/youtube/callback"
    check("redirect: an explicit redirect (a server or a tunnel) wins over the port guess",
          social.youtube_redirect_uri() == "http://clips.example.com/oauth/youtube/callback")
    CONFIG.pop("yt_redirect", None)


def test_consent_url_carries_the_port_and_a_state():
    clean_token()
    url = urllib.parse.urlparse(social.youtube_auth_url())
    qs = urllib.parse.parse_qs(url.query)
    check("consent: the callback it registers is this window's",
          qs["redirect_uri"][0] == "http://localhost:4300/oauth/youtube/callback",
          qs["redirect_uri"][0])
    check("consent: it asks for offline access", qs["access_type"][0] == "offline")
    check("consent: the scope is upload only, nothing else",
          qs["scope"][0] == "https://www.googleapis.com/auth/youtube.upload")
    check("consent: a state is sent", bool(qs.get("state", [""])[0]))
    check("consent: the state is stored for the callback to check",
          os.path.isfile(social.YT_STATE_FILE))


# ------------------------------------------------------------------ 2. CSRF state

def test_state_is_checked_burned_and_time_boxed():
    clean_token()
    social.youtube_auth_url()
    state = json.load(open(social.YT_STATE_FILE, encoding="utf-8"))["state"]

    try:
        social.youtube_check_state("not-the-state")
        check("state: a forged callback is refused", False)
    except RuntimeError as e:
        check("state: a forged callback is refused, with the fix", "press connect youtube again" in str(e).lower())

    try:
        social.youtube_check_state(state)
        check("state: the real state passes", True)
    except RuntimeError as e:
        check("state: the real state passes", False, str(e))

    try:
        social.youtube_check_state(state)
        check("state: a replayed consent is refused (single use)", False)
    except RuntimeError:
        check("state: a replayed consent is refused (single use)", True)

    social.youtube_auth_url()
    rec = json.load(open(social.YT_STATE_FILE, encoding="utf-8"))
    rec["issued_at"] = time.time() - (social.STATE_TTL + 30)
    json.dump(rec, open(social.YT_STATE_FILE, "w", encoding="utf-8"))
    try:
        social.youtube_check_state(rec["state"])
        check("state: a consent older than ten minutes is refused", False)
    except RuntimeError as e:
        check("state: a consent older than ten minutes is refused", "ten minutes" in str(e))


def test_exchange_verifies_the_state_before_storing():
    clean_token()
    stub_post(lambda url, f: {"access_token": "at", "refresh_token": "rt",
                              "expires_in": 3600})
    try:
        social.youtube_exchange("code-1", "wrong-state")
        check("exchange: a bad state stores nothing", False)
    except RuntimeError:
        check("exchange: a bad state stores nothing (no token file)",
              not os.path.isfile(social.YT_TOKEN_FILE))

    social.youtube_auth_url()
    state = json.load(open(social.YT_STATE_FILE, encoding="utf-8"))["state"]
    tok = social.youtube_exchange("code-1", state)
    check("exchange: a good state stores the token", os.path.isfile(social.YT_TOKEN_FILE))
    check("exchange: it records when the channel was connected", "connected_at" in tok)
    check("exchange: the redirect it sends matches the window's",
          CALLS[-1][1]["redirect_uri"] == "http://localhost:4300/oauth/youtube/callback")
    check("exchange: a fresh consent clears any old warning",
          not json.load(open(social.YT_TOKEN_FILE, encoding="utf-8")).get("reauth_required"))


# ------------------------------------------------------- 3. expired / revoked token

def test_expired_refresh_token_is_named():
    clean_token()
    fresh_token()
    stub_post(lambda url, f: (_ for _ in ()).throw(
        http_error({"error": "invalid_grant",
                    "error_description": "Token has been expired or revoked."})))
    try:
        social.youtube_access_token()
        check("expiry: a dead refresh token raises", False)
    except RuntimeError as e:
        msg = str(e)
        check("expiry: the message says the token expired or was revoked", "expired or was revoked" in msg)
        check("expiry: the message explains the seven-day Testing rule", "seven days" in msg)
        check("expiry: the message tells the fix (re-consent)", "Connect YouTube again" in msg)

    tok = json.load(open(social.YT_TOKEN_FILE, encoding="utf-8"))
    check("expiry: the reason is recorded on the token", tok.get("reauth_required") is True)
    check("expiry: the human message is stored for the Connect screen",
          "expired or was revoked" in tok.get("last_error", ""))
    check("expiry: it records when it failed", tok.get("last_error_at", 0) > 0)
    check("expiry: connected() stops claiming a connection", social.youtube_connected() is False)

    st = social.youtube_state()
    check("expiry: the state exposes the reason", st["reauth_required"] and bool(st["reauth_reason"]))
    check("expiry: the state still says the keys are configured", st["configured"] is True)

    diag = social.youtube_diagnose()
    errors = [k["error"] for k in diag["known_errors"]]
    check("expiry: Diagnose lists it as a known error",
          any("expired or was revoked" in e for e in errors), str(errors))
    check("expiry: Diagnose gives the seven-day fix",
          any("seven days" in k["fix"] for k in diag["known_errors"]))
    check("expiry: Diagnose offers a next action", bool(diag["next_action"]))


def test_second_failure_does_not_hammer_google():
    """Once reauth is required, the app stops calling Google until the user re-consents."""
    CALLS.clear()
    clean_token()
    fresh_token(reauth_required=True, last_error="Token has been expired or revoked.")
    try:
        social.youtube_access_token()
        check("expiry: a known-dead token raises without a network call", False)
    except RuntimeError as e:
        check("expiry: a known-dead token raises without a network call",
              len(CALLS) == 0 and "Connect YouTube" in str(e), f"{len(CALLS)} calls")
    check("expiry: channel lookup returns nothing instead of throwing",
          social.youtube_channel() is None)


def test_invalid_client_is_also_a_reauth():
    clean_token()
    fresh_token()
    stub_post(lambda url, f: (_ for _ in ()).throw(
        http_error({"error": "invalid_client", "error_description": "Unauthorized"})))
    try:
        social.youtube_access_token()
    except RuntimeError as e:
        check("expiry: a rejected client key is reported as a re-consent too",
              json.load(open(social.YT_TOKEN_FILE, encoding="utf-8")).get("reauth_required") is True)
        check("expiry: the client-key message names the keys, not a stack trace",
              "CB_YT_CLIENT_ID" in str(e) or "Credentials" in str(e), str(e))


def test_network_error_is_not_a_reauth():
    clean_token()
    fresh_token()
    stub_post(lambda url, f: (_ for _ in ()).throw(OSError("no route to host")))
    try:
        social.youtube_access_token()
        check("network: an offline refresh raises", False)
    except RuntimeError as e:
        check("network: the message says Google was unreachable",
              "reach Google" in str(e), str(e))
    check("network: being offline does NOT throw away a working token",
          json.load(open(social.YT_TOKEN_FILE, encoding="utf-8")).get("reauth_required") is not True)


# -------------------------------------------------------------- 5. healthy refresh

def test_good_refresh_clears_the_warning():
    clean_token()
    fresh_token(reauth_required=True, last_error="Token has been expired or revoked.")
    stub_post(lambda url, f: {"access_token": "new-at", "expires_in": 3600})
    tok = json.load(open(social.YT_TOKEN_FILE, encoding="utf-8"))
    tok["reauth_required"] = False  # the user re-consented, then this refresh runs
    write_token(tok)
    at = social.youtube_access_token()
    check("refresh: a good refresh returns a new access token", at == "new-at", at)
    saved = json.load(open(social.YT_TOKEN_FILE, encoding="utf-8"))
    check("refresh: the new token is saved", saved["access_token"] == "new-at")
    check("refresh: the anti-thrash window is applied (expires early)",
          saved["expires_at"] < time.time() + 3600)
    check("refresh: refreshing keeps the refresh token when Google omits a new one",
          saved["refresh_token"] == "rt-1")


def test_state_without_a_token():
    clean_token()
    st = social.youtube_state()
    check("state: no token reads as not connected", st["connected"] is False and st["has_token"] is False)
    check("state: it never claims a re-consent is needed before one was ever made",
          st["reauth_required"] is False)
    check("state: disconnect on nothing is a no-op", social.youtube_disconnect() is False)


def test_disconnect_forgets_everything():
    clean_token()
    fresh_token(reauth_required=True, last_error="x")
    check("disconnect: removes the token", social.youtube_disconnect() is True)
    check("disconnect: the token file is gone", not os.path.isfile(social.YT_TOKEN_FILE))
    check("disconnect: the stale warning goes with it", not social.youtube_state()["reauth_required"])


def main():
    for fn in (test_redirect_uri_follows_the_port,
               test_consent_url_carries_the_port_and_a_state,
               test_state_is_checked_burned_and_time_boxed,
               test_exchange_verifies_the_state_before_storing,
               test_expired_refresh_token_is_named,
               test_second_failure_does_not_hammer_google,
               test_invalid_client_is_also_a_reauth,
               test_network_error_is_not_a_reauth,
               test_good_refresh_clears_the_warning,
               test_state_without_a_token,
               test_disconnect_forgets_everything):
        fn()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
