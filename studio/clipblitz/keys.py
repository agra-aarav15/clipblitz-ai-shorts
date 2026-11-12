"""API key management: the Connect UI writes provider settings straight into .env.

Everything downstream hot-reloads (brains(), social, STT model resolution), so a
saved key is live on the very next job - no restart. Values never leave this
machine except to their own provider during an explicit test call.

The UI is generated from the same provider list the engine uses, so adding a
provider here is enough to make it configurable in Connect.
"""

import json
import os
import re
import urllib.error
import urllib.request

from .config import app_root

_ROOT = app_root()
ENV_PATH = os.path.join(_ROOT, ".env")

# logical name -> .env variable
KEY_VARS = {
    "groq": "CB_AI_KEY",
    "gemini": "CB_GEMINI_KEY",
    "cerebras": "CB_CEREBRAS_KEY",
    "openrouter": "CB_OPENROUTER_KEY",
    "together": "CB_TOGETHER_KEY",
    "openai": "CB_OPENAI_KEY",
    "pollinations": "CB_POLLINATIONS",
    "local_base": "CB_LOCAL_BASE",
    "local_model": "CB_LOCAL_MODEL",
    "ai_order": "CB_AI_ORDER",
    "yt_client_id": "CB_YT_CLIENT_ID",
    "yt_client_secret": "CB_YT_CLIENT_SECRET",
}

# The order here is the order shown in Connect. `key` is the logical name used by
# the save/test endpoints; `var` is the .env variable.
PROVIDERS = [
    {"key": "groq", "var": "CB_AI_KEY", "label": "Groq",
     "hint": "free key -> console.groq.com/keys", "placeholder": "gsk_...",
     "chip": "PRIMARY", "secret": True},
    {"key": "gemini", "var": "CB_GEMINI_KEY", "label": "Gemini",
     "hint": "free key -> aistudio.google.com/apikey", "placeholder": "AIzaSy... or AQ...",
     "chip": "FAILOVER", "secret": True},
    {"key": "cerebras", "var": "CB_CEREBRAS_KEY", "label": "Cerebras",
     "hint": "free tier -> cloud.cerebras.ai", "placeholder": "csk-...",
     "chip": "OPTIONAL", "secret": True},
    {"key": "openrouter", "var": "CB_OPENROUTER_KEY", "label": "OpenRouter",
     "hint": "free models -> openrouter.ai/keys", "placeholder": "sk-or-...",
     "chip": "OPTIONAL", "secret": True},
    {"key": "together", "var": "CB_TOGETHER_KEY", "label": "Together",
     "hint": "free tier -> api.together.xyz", "placeholder": "tgp_v1_...",
     "chip": "OPTIONAL", "secret": True},
    {"key": "openai", "var": "CB_OPENAI_KEY", "label": "OpenAI",
     "hint": "paid; only used if you add it", "placeholder": "sk-...",
     "chip": "OPTIONAL", "secret": True},
    {"key": "pollinations", "var": "CB_POLLINATIONS", "label": "Pollinations",
     "hint": "no key; on/off shared fallback", "placeholder": "on",
     "chip": "NO KEY", "secret": False},
    {"key": "local_base", "var": "CB_LOCAL_BASE", "label": "Local server",
     "hint": "Ollama default: http://127.0.0.1:11434/v1",
     "placeholder": "http://127.0.0.1:11434/v1", "chip": "PERMANENT", "secret": False},
    {"key": "local_model", "var": "CB_LOCAL_MODEL", "label": "Local model",
     "hint": "ollama pull qwen2.5:3b", "placeholder": "qwen2.5:3b",
     "chip": "PERMANENT", "secret": False},
    {"key": "ai_order", "var": "CB_AI_ORDER", "label": "Provider order",
     "hint": "comma order, e.g. groq,gemini,local,pollinations",
     "placeholder": "groq,gemini,local,pollinations", "chip": "ROUTING", "secret": False},
]

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/openai/models"
CEREBRAS_MODELS_URL = "https://api.cerebras.ai/v1/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
TOGETHER_MODELS_URL = "https://api.together.xyz/v1/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
POLLINATIONS_CHAT_URL = "https://text.pollinations.ai/openai"


def _mask(value):
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 10:
        return v[:2] + "****"
    return v[:5] + "******" + v[-4:]


def _env():
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
    return env


def _model_for(name):
    from .brains import brains
    return next((b["model"] for b in brains() if b["name"] == name), "")


def status():
    """What the UI needs: every provider, masked previews, hints and live models."""
    from .brains import brains
    env = _env()
    out = {}
    for p in PROVIDERS:
        value = env.get(p["var"], "").strip()
        if p["key"] == "pollinations":
            value = value or "on"
            is_set = value.lower() not in ("0", "off", "false", "no")
        else:
            is_set = bool(value)
        out[p["key"]] = {
            "set": is_set,
            "masked": _mask(value) if p["secret"] else value,
            "hint": p["hint"],
            "placeholder": p["placeholder"],
            "label": p["label"],
            "chip": p["chip"],
            "secret": p["secret"],
            "model": _model_for(p["key"]) if p["key"] in
                     ("groq", "gemini", "cerebras", "openrouter", "together", "openai", "local")
                     else "",
        }
    out["yt_client_id"] = {
        "set": bool(env.get("CB_YT_CLIENT_ID", "").strip()),
        "masked": _mask(env.get("CB_YT_CLIENT_ID", "")),
        "hint": "Google Cloud -> OAuth client ID", "model": "", "chip": "FOR AUTO-POST",
    }
    out["yt_client_secret"] = {
        "set": bool(env.get("CB_YT_CLIENT_SECRET", "").strip()),
        "masked": _mask(env.get("CB_YT_CLIENT_SECRET", "")),
        "hint": "guide -> Setup tab, 4 steps", "model": "", "chip": "FOR AUTO-POST",
    }
    out["brains"] = [b["name"] for b in brains()]
    out["providers"] = PROVIDERS
    return out


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


def _stored(which):
    var = KEY_VARS.get(which, "")
    return _env().get(var, "").strip()


def _models_test(url, value, label):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + value,
        "User-Agent": "ClipBlitz/5.3",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    n = len(data.get("data") or data.get("models") or [])
    return {"ok": True, "detail": f"{label} online - {n} models available"}


def test(which, value=None):
    """Actually call the provider with the given (or stored) value. Returns {ok, detail}."""
    value = (value or "").strip() or _stored(which)
    if which in ("ai_order",):
        names = [x.strip().lower() for x in value.split(",") if x.strip()]
        known = {"groq", "gemini", "cerebras", "openrouter", "together", "openai",
                 "pollinations", "local"}
        bad = [x for x in names if x not in known]
        return {"ok": not bad, "detail": "order saved" if not bad
                else "unknown provider: " + ", ".join(bad)}
    if which == "pollinations":
        if value.lower() in ("0", "off", "false", "no"):
            return {"ok": True, "detail": "Pollinations disabled"}
        try:
            req = urllib.request.Request(POLLINATIONS_CHAT_URL, data=json.dumps({
                "model": "openai",
                "messages": [{"role": "user", "content": "Reply with JSON {\"ok\":true}"}],
                "temperature": 0,
            }).encode(), headers={"Content-Type": "application/json",
                                  "User-Agent": "ClipBlitz/5.3"})
            with urllib.request.urlopen(req, timeout=20) as r:
                json.load(r)
            return {"ok": True, "detail": "Pollinations online (no key)"}
        except Exception as e:
            return {"ok": False, "detail": f"Pollinations unavailable: {str(e)[:80]}"}
    if which in ("local_base", "local_model"):
        base = (value if which == "local_base" else _stored("local_base")) or             "http://127.0.0.1:11434/v1"
        try:
            req = urllib.request.Request(base.rstrip("/") + "/models",
                                         headers={"User-Agent": "ClipBlitz/5.3"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            n = len(data.get("data") or [])
            return {"ok": True, "detail": f"local server online - {n} models"}
        except Exception as e:
            return {"ok": False, "detail": f"local server not reachable: {str(e)[:80]}"}
    if not value:
        return {"ok": False, "detail": "no value to test - paste one first"}
    try:
        if which == "groq":
            return _models_test(GROQ_MODELS_URL, value, "Groq")
        if which == "gemini":
            return _models_test(GEMINI_MODELS_URL, value, "Gemini")
        if which == "cerebras":
            return _models_test(CEREBRAS_MODELS_URL, value, "Cerebras")
        if which == "openrouter":
            return _models_test(OPENROUTER_MODELS_URL, value, "OpenRouter")
        if which == "together":
            return _models_test(TOGETHER_MODELS_URL, value, "Together")
        if which == "openai":
            return _models_test(OPENAI_MODELS_URL, value, "OpenAI")
        if which in ("yt_client_id", "yt_client_secret"):
            ok = len(value) > 20 and (which == "yt_client_secret" or
                                      value.endswith("apps.googleusercontent.com") or
                                      re.match(r"^\d+-[a-z0-9]+$", value.split(".apps")[0]))
            return {"ok": ok, "detail": "format looks right - press Connect YouTube to finish OAuth"
                    if ok else "that doesn't look like a Google OAuth credential"}
    except urllib.error.HTTPError as e:
        code = e.code
        if code in (401, 403):
            return {"ok": False, "detail": f"rejected by provider ({code}) - check the key"}
        return {"ok": False, "detail": f"provider error {code}"}
    except Exception as e:
        return {"ok": False, "detail": f"network error: {str(e)[:80]}"}
    return {"ok": False, "detail": "unknown provider"}
