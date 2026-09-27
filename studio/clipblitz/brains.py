"""Dual-brain AI layer: primary provider + automatic failover.

Keys/config are hot-loaded from .env on every call (paste a key → it works, no
restart). The primary is Groq (CB_AI_*); a Gemini key (CB_GEMINI_KEY) adds Google's
OpenAI-compatible endpoint as failover, and CB_AI_PROVIDER=gemini flips the order.

Failover triggers: rate limits (429), provider 5xx, network errors, and empty
reasoning-only answers (the gpt-oss quirk). Rate limits respect Retry-After.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = os.environ.get("CB_GEMINI_MODEL", "").strip() or "gemini-3.6-flash"


def _retired_model_successor(e):
    """Providers announce retirements with the replacement in the body
    ('... models/gemini-3.6-flash for the latest ...') — read it and self-heal."""
    try:
        body = e.read().decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r"use models/([\w.\-]+)", body) or re.search(r"models/([\w.\-]+) is no longer", body)
    return m.group(1) if m else None


def _read_env_keys():
    keys = {}
    try:
        for line in open(os.path.join(_ROOT, ".env"), encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    except OSError:
        pass
    return keys


def brains():
    """Ordered list of usable brains: [{name, base, key, model}]."""
    env = _read_env_keys()
    gemini_key = env.get("CB_GEMINI_KEY", "").strip()
    groq = {
        "name": "groq",
        "base": env.get("CB_AI_BASE", "").strip() or "https://api.groq.com/openai/v1",
        "key": env.get("CB_AI_KEY", "").strip(),
        "model": env.get("CB_AI_MODEL", "").strip() or "openai/gpt-oss-120b",
    }
    gemini = {"name": "gemini", "base": GEMINI_BASE, "key": gemini_key, "model": GEMINI_MODEL}
    order = [gemini, groq] if env.get("CB_AI_PROVIDER", "").strip().lower() == "gemini" else [groq, gemini]
    return [b for b in order if b["key"]]


def _call_one(brain, payload, timeout=180, model_override=None):
    # Each brain serves ITS OWN model — the caller's "model" field is just a hint for
    # the primary. Sending the primary's model name to the failover provider 404s.
    model = model_override or brain["model"] or payload.get("model")
    body = json.dumps({**payload, "model": model}).encode()
    req = urllib.request.Request(
        f"{brain['base'].rstrip('/')}/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "ClipBlitz/0.3",
                 "Authorization": f"Bearer {brain['key']}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        out = json.loads(res.read())
    content = out["choices"][0]["message"].get("content")
    if not content or not content.strip():
        raise EmptyAnswer(f"{brain['name']} returned an empty answer")
    return content


class EmptyAnswer(Exception):
    pass


def ai_chat(payload, attempts_per_brain=2):
    """One chat completion across brains: 429-aware retries per brain, then failover.
    Raises the last error only if every brain failed."""
    usable = brains()
    if not usable:
        raise RuntimeError("no AI key configured (CB_AI_KEY / CB_GEMINI_KEY in .env)")
    last = None
    for brain in usable:
        for attempt in range(attempts_per_brain):
            try:
                return _call_one(brain, payload)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 404:
                    successor = _retired_model_successor(e)
                    if successor:  # provider told us the replacement model — use it
                        try:
                            return _call_one(brain, payload, model_override=successor)
                        except urllib.error.HTTPError:
                            pass
                    break  # this brain can't serve this request — try the other brain
                if e.code in (400, 401, 403):
                    break  # this brain can't serve this request — try the other brain
                if e.code == 429:
                    retry_after = e.headers.get("Retry-After")
                    wait = min(90, float(retry_after)) if (retry_after or "").replace(".", "").isdigit() \
                        else 15 + attempt * 15
                    time.sleep(wait)
                    continue
                time.sleep(2 + attempt * 3)
            except (EmptyAnswer, urllib.error.URLError, TimeoutError, OSError, KeyError,
                    ValueError) as e:
                last = e
                time.sleep(2 + attempt * 3)
    raise last or RuntimeError("all AI brains failed")
