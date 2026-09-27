"""API key management: the Power-up / Connect UI writes keys straight into .env.

Everything downstream hot-reloads (brains(), social, STT model resolution), so a
saved key is live on the very next job — no restart. Values never leave this
machine except to their own provider during an explicit test call.
"""

import json
import os
import re
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(_ROOT, ".env")

# logical name -> .env variable
KEY_VARS = {
    "groq": "CB_AI_KEY",
    "gemini": "CB_GEMINI_KEY",
    "yt_client_id": "CB_YT_CLIENT_ID",
    "yt_client_secret": "CB_YT_CLIENT_SECRET",
}

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/openai/models"


def _mask(value):
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 10:
        return v[:2] + "••••"
    return v[:5] + "••••••" + v[-4:]


def status():
    """What the UI needs: which keys exist, masked previews, provider hints."""
    from .brains import brains
    try:
        lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    env = {}
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    brain_names = [b["name"] for b in brains()]
    model = next((b["model"] for b in brains() if b["name"] == "groq"), "openai/gpt-oss-120b")
    return {
        "groq": {"set": bool(env.get("CB_AI_KEY", "").strip()),
                 "masked": _mask(env.get("CB_AI_KEY", "")),
                 "hint": "free key → console.groq.com/keys", "model": model,
                 "chip": "REQUIRED"},
        "gemini": {"set": bool(env.get("CB_GEMINI_KEY", "").strip()),
                   "masked": _mask(env.get("CB_GEMINI_KEY", "")),
                   "hint": "free key → aistudio.google.com/apikey", "model": "gemini-2.0-flash",
                   "chip": "RECOMMENDED"},
        "yt_client_id": {"set": bool(env.get("CB_YT_CLIENT_ID", "").strip()),
                         "masked": _mask(env.get("CB_YT_CLIENT_ID", "")),
                         "hint": "Google Cloud → OAuth client ID", "model": "",
                         "chip": "FOR AUTO-POST"},
        "yt_client_secret": {"set": bool(env.get("CB_YT_CLIENT_SECRET", "").strip()),
                             "masked": _mask(env.get("CB_YT_CLIENT_SECRET", "")),
                             "hint": "guide → Setup tab, 4 steps", "model": "",
                             "chip": "FOR AUTO-POST"},
        "brains": brain_names,
    }


def save(updates):
    """Merge {logical_name: value} into .env, preserving every other line.
    Commented-out placeholder lines get uncommented in place; unknown keys append."""
    updates = {k: (v or "").strip() for k, v in (updates or {}).items()
               if k in KEY_VARS and (v or "").strip()}
    if not updates:
        return {"saved": [], "status": status()}
    try:
        lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    except OSError:
        lines = ["# ClipBlitz - live configuration (gitignored, never commit)"]

    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^#?\s*([A-Z_0-9]+)\s*=", stripped)
        if m:
            var = m.group(1)
            hit = next((lk for lk, vv in KEY_VARS.items() if vv == var and lk in remaining), None)
            if hit:
                out.append(f"{var}={remaining.pop(hit)}")
                continue
        out.append(line)
    for lk, vv in remaining.items():  # var not present in the file yet
        out.append(f"{KEY_VARS[lk]}={vv}")
    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:  # keep LF stable on Windows
        f.write("\n".join(out).rstrip("\n") + "\n")
    os.replace(tmp, ENV_PATH)
    return {"saved": list(updates.keys()), "status": status()}


def test(which, value=None):
    """Actually call the provider with the given (or stored) key. Returns {ok, detail}."""
    value = (value or "").strip()
    if not value:
        var = KEY_VARS.get(which, "")
        try:
            for line in open(ENV_PATH, encoding="utf-8"):
                m = re.match(rf"^{var}\s*=\s*(.+)", line.strip())
                if m:
                    value = m.group(1).strip()
        except OSError:
            pass
    if not value:
        return {"ok": False, "detail": "no key to test — paste one first"}

    try:
        if which == "groq":
            req = urllib.request.Request(GROQ_MODELS_URL,
                                         headers={"Authorization": "Bearer " + value,
                                                  "User-Agent": "ClipBlitz/3.2"})
            with urllib.request.urlopen(req, timeout=15) as r:
                n = len(json.load(r).get("data", []))
            return {"ok": True, "detail": f"online · {n} models available"}
        if which == "gemini":
            req = urllib.request.Request(GEMINI_MODELS_URL,
                                         headers={"Authorization": "Bearer " + value,
                                                  "User-Agent": "ClipBlitz/3.2"})
            with urllib.request.urlopen(req, timeout=15) as r:
                n = len(json.load(r).get("models", []))
            return {"ok": True, "detail": f"online · {n} models available"}
        if which in ("yt_client_id", "yt_client_secret"):
            ok = len(value) > 20 and (which == "yt_client_secret" or
                                      value.endswith("apps.googleusercontent.com") or
                                      re.match(r"^\d+-[a-z0-9]+$", value.split(".apps")[0]))
            return {"ok": ok, "detail": "format looks right — press Connect YouTube to finish OAuth"
                    if ok else "that doesn't look like a Google OAuth credential"}
    except urllib.error.HTTPError as e:
        code = e.code
        if code in (401, 403):
            return {"ok": False, "detail": f"rejected by provider ({code}) — check the key"}
        return {"ok": False, "detail": f"provider error {code}"}
    except Exception as e:
        return {"ok": False, "detail": f"network error: {str(e)[:80]}"}
