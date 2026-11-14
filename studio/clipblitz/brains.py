"""Multi-provider AI layer: ordered brains with automatic failover.

The app talks one OpenAI-compatible chat API. This module turns whatever keys are
configured into an ordered pool and fails over on rate limits, provider 5xx,
network errors and empty answers. No provider is required for the deterministic
engine; a provider only improves the editor/judge passes.

Supported without extra code:
  groq        CB_AI_KEY / CB_GROQ_KEYS, CB_AI_BASE, CB_AI_MODEL
  gemini      CB_GEMINI_KEY / CB_GEMINI_KEYS (OpenAI-compatible endpoint)
  openrouter  CB_OPENROUTER_KEY, CB_OPENROUTER_MODEL
  cerebras    CB_CEREBRAS_KEY, CB_CEREBRAS_MODEL
  together    CB_TOGETHER_KEY, CB_TOGETHER_MODEL
  openai      CB_OPENAI_KEY, CB_OPENAI_MODEL
  pollinations no key, free fallback: text.pollinations.ai/openai
  local       CB_LOCAL_BASE (default http://127.0.0.1:11434/v1), CB_LOCAL_MODEL

`CB_AI_ORDER` is a comma-separated order such as "groq,cerebras,gemini,local".
Keys/config are hot-loaded from .env on every call, so a key pasted mid-session
works without a restart. The local probe is cached for 60s and never blocks a run.
"""

import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import app_root

_ROOT = app_root()

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = os.environ.get("CB_GEMINI_MODEL", "").strip() or "gemini-3.6-flash"
POLLINATIONS_BASE = "https://text.pollinations.ai/openai"
LOCAL_BASE = os.environ.get("CB_LOCAL_BASE", "").strip() or "http://127.0.0.1:11434/v1"
LOCAL_MODEL = os.environ.get("CB_LOCAL_MODEL", "").strip() or "qwen2.5:3b"

_LOCAL_CACHE = {"at": 0.0, "ready": False, "base": ""}
_COOLDOWN = {}  # provider name -> monotonic time it may be tried again
_LAST = threading.local()  # per-thread record of the provider that answered last


def last_call():
    """{provider, model} for the most recent successful call in THIS thread.
    The editor runs chunks in parallel, so a plain global would race; the judge
    reads this immediately after its own call to record who judged the clip."""
    return getattr(_LAST, "info", None)
_CALL_ORDER = ("groq", "gemini", "cerebras", "openrouter", "together", "openai", "pollinations", "local")


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


def _split_keys(value):
    return [k.strip() for k in (value or "").split(",") if k.strip()]


def _base_ready(base):
    """A 0.2s TCP probe, cached, so a missing local server costs nothing."""
    parsed = urllib.parse.urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    now = time.time()
    if _LOCAL_CACHE["base"] == base and now - _LOCAL_CACHE["at"] < 60.0:
        return _LOCAL_CACHE["ready"]
    ready = False
    try:
        with socket.create_connection((host, port), timeout=0.2):
            ready = True
    except OSError:
        ready = False
    _LOCAL_CACHE.update({"at": now, "ready": ready, "base": base})
    return ready


def _entry(name, base, key, model, headers=None):
    return {"name": name, "base": base.rstrip("/"), "key": key or "",
            "model": model or "", "headers": headers or {}}


def _legacy_pool(env):
    pool = []

    groq_keys = _split_keys(env.get("CB_GROQ_KEYS", "")) or _split_keys(env.get("CB_AI_KEY", ""))
    groq_base = env.get("CB_AI_BASE", "").strip() or "https://api.groq.com/openai/v1"
    groq_model = env.get("CB_AI_MODEL", "").strip() or "openai/gpt-oss-120b"
    for i, key in enumerate(groq_keys):
        pool.append(_entry(f"groq{i + 1}" if len(groq_keys) > 1 else "groq",
                           groq_base, key, groq_model))

    gemini_keys = _split_keys(env.get("CB_GEMINI_KEYS", "")) or _split_keys(env.get("CB_GEMINI_KEY", ""))
    for i, key in enumerate(gemini_keys):
        pool.append(_entry(f"gemini{i + 1}" if len(gemini_keys) > 1 else "gemini",
                           GEMINI_BASE, key, GEMINI_MODEL))

    or_key = env.get("CB_OPENROUTER_KEY", "").strip()
    if or_key:
        pool.append(_entry(
            "openrouter", "https://openrouter.ai/api/v1", or_key,
            env.get("CB_OPENROUTER_MODEL", "").strip() or "meta-llama/llama-3.3-70b-instruct:free",
            {"HTTP-Referer": "http://localhost:4300", "X-Title": "ClipBlitz Studio"}))

    cb_key = env.get("CB_CEREBRAS_KEY", "").strip()
    if cb_key:
        pool.append(_entry(
            "cerebras", "https://api.cerebras.ai/v1", cb_key,
            env.get("CB_CEREBRAS_MODEL", "").strip() or "llama-3.3-70b"))

    tg_key = env.get("CB_TOGETHER_KEY", "").strip()
    if tg_key:
        pool.append(_entry(
            "together", "https://api.together.xyz/v1", tg_key,
            env.get("CB_TOGETHER_MODEL", "").strip() or "meta-llama/Llama-3.3-70B-Instruct-Turbo"))

    oa_key = env.get("CB_OPENAI_KEY", "").strip()
    if oa_key:
        pool.append(_entry(
            "openai", "https://api.openai.com/v1", oa_key,
            env.get("CB_OPENAI_MODEL", "").strip() or "gpt-4o-mini"))

    local_base = env.get("CB_LOCAL_BASE", "").strip() or LOCAL_BASE
    local_model = env.get("CB_LOCAL_MODEL", "").strip() or LOCAL_MODEL
    if local_base and _base_ready(local_base):
        pool.append(_entry("local", local_base, env.get("CB_LOCAL_KEY", "").strip() or "local",
                           local_model))

    # No-key, free fallback. It is rate-limited and not a promise of uptime; the
    # local model above is the permanent option. It stays here so a machine without
    # a local runtime can still try a hosted free tier.
    # No-key, free fallback. It is rate-limited and not a promise of uptime, but it
    # gives the judge somewhere to go when every configured key is exhausted.
    if env.get("CB_POLLINATIONS", "on").strip().lower() not in ("0", "off", "false", "no"):
        pool.append(_entry(
            "pollinations", POLLINATIONS_BASE, "",
            env.get("CB_POLLINATIONS_MODEL", "").strip() or "openai",
            {"HTTP-Referer": "http://localhost:4300", "X-Title": "ClipBlitz Studio"}))

    wanted = [x.strip().lower() for x in env.get("CB_AI_ORDER", "").split(",") if x.strip()]
    if wanted:
        rank = {name: i for i, name in enumerate(wanted)}
        pool.sort(key=lambda b: rank.get(b["name"].rstrip("0123456789"), len(wanted)))
    elif env.get("CB_AI_PROVIDER", "").strip().lower() == "gemini":
        pool.sort(key=lambda b: 0 if b["name"].startswith("gemini") else 1)
    return pool


def _apply_order(pool, env):
    wanted = [x.strip().lower() for x in env.get("CB_AI_ORDER", "").split(",") if x.strip()]
    if wanted:
        rank = {name: i for i, name in enumerate(wanted)}
        pool.sort(key=lambda b: rank.get(str(b.get("name", "")).lower(), len(wanted)))
    elif env.get("CB_AI_PROVIDER", "").strip().lower() == "gemini":
        pool.sort(key=lambda b: 0 if str(b.get("name", "")).lower().startswith("gemini") else 1)
    return pool


def legacy_pool():
    """The pre-store .env pool. Used only before providers.json exists and for the
    one-time migration when Connect is first opened."""
    return _apply_order(_legacy_pool(_read_env_keys()), _read_env_keys())


def _provider_pool(env):
    """The providers.json store is the source of truth once it exists. An empty store
    means the owner removed every provider: no AI, and the engine runs measured-only."""
    from . import providers
    stored = providers.pool()
    if stored is not None:
        return _apply_order(stored, env)
    return _apply_order(_legacy_pool(env), env)


def brains():
    """Ordered list of usable brains: [{name, base, key, model, headers}]."""
    return _provider_pool(_read_env_keys())


def brains_status():
    """Safe health payload: provider/model names only, never a key."""
    return [{"id": b.get("id", ""), "name": b.get("label") or b["name"],
             "model": b["model"], "stt": bool(b.get("stt"))} for b in brains()]


def _retired_model_successor(e):
    """Providers announce retirements with the replacement in the body
    ('... models/gemini-3.6-flash for the latest ...') — read it and self-heal."""
    try:
        body = e.read().decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r"use models/([\w.\-]+)", body) or re.search(r"models/([\w.\-]+) is no longer", body)
    return m.group(1) if m else None


_SEM_LOCK = threading.Lock()
_SEMS = {}


def _semaphore(name, capacity=1):
    with _SEM_LOCK:
        sem = _SEMS.get(name)
        if sem is None:
            sem = threading.BoundedSemaphore(capacity)
            _SEMS[name] = sem
        return sem


def _is_local(brain):
    try:
        host = urllib.parse.urlparse(str(brain.get("base") or "")).hostname or ""
    except ValueError:
        host = ""
    return host in ("127.0.0.1", "localhost", "::1") or str(brain.get("name", "")).lower().startswith(("local", "ollama"))


def _call_one(brain, payload, timeout=180, model_override=None):
    # Free tiers return 429 when two editor chunks and the judge all hit the same
    # key at once. Queue per provider instead of pretending the quota is larger.
    if _is_local(brain):
        # A local server can be TCP-ready and still take minutes to answer (cold
        # load, a small model on CPU, a huge judge prompt). It is a fallback, not a
        # blocker: cap it and cool it down on failure instead of stalling the job.
        try:
            local_cap = max(5, int(os.environ.get("CB_LOCAL_TIMEOUT", "45")))
        except (TypeError, ValueError):
            local_cap = 45
        timeout = min(timeout, local_cap)
    sem = _semaphore(brain["name"], 2 if (_is_local(brain) or brain.get("name", "").lower().startswith("openai")) else 1)
    with sem:
        return _call_one_raw(brain, payload, timeout=timeout,
                             model_override=model_override)


def _call_one_raw(brain, payload, timeout=180, model_override=None):
    # Each brain serves ITS OWN model. Sending the primary's model name to a
    # failover provider 404s, so the caller's model is only a hint.
    model = model_override or brain["model"] or payload.get("model")
    out = {**payload, "model": model}
    if brain.get("max_tokens") and not out.get("max_tokens"):
        out["max_tokens"] = brain["max_tokens"]
    if brain.get("temperature") is not None and out.get("temperature") is None:
        out["temperature"] = brain["temperature"]
    body = json.dumps(out).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "ClipBlitz/5.5"}
    if brain.get("key"):
        headers["Authorization"] = f"Bearer {brain['key']}"
    headers.update(brain.get("headers") or {})
    req = urllib.request.Request(
        f"{brain['base'].rstrip('/')}/chat/completions", data=body, method="POST",
        headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        out = json.loads(res.read())
    content = out["choices"][0]["message"].get("content")
    if not content or not content.strip():
        raise EmptyAnswer(f"{brain['name']} returned an empty answer")
    _LAST.info = {"provider": brain["name"], "model": model}
    return content


class EmptyAnswer(Exception):
    pass


def ai_chat(payload, attempts_per_brain=2, timeout=None):
    """One chat completion across brains: 429-aware retries per brain, then failover.
    A rate-limited provider goes on cooldown so parallel editor chunks do not all
    wait on the same exhausted key. Raises the last error only if every brain failed."""
    now = time.time()
    usable = [b for b in brains() if _COOLDOWN.get(b["name"], 0.0) <= now]
    if not usable:
        # Everything is cooling down. Wait only for the soonest, once.
        soonest = min(brains(), key=lambda b: _COOLDOWN.get(b["name"], 0.0), default=None)
        if soonest is None:
            raise RuntimeError(
                "no AI provider configured (set CB_AI_KEY, CB_GEMINI_KEY, "
                "CB_OPENROUTER_KEY, CB_CEREBRAS_KEY, CB_TOGETHER_KEY, CB_OPENAI_KEY, "
                "or run a local OpenAI-compatible server at CB_LOCAL_BASE)")
        wait = max(0.0, _COOLDOWN.get(soonest["name"], 0.0) - now)
        if wait > 60:
            raise RuntimeError("all AI providers are cooling down")
        time.sleep(wait + 0.2)
        usable = [b for b in brains() if _COOLDOWN.get(b["name"], 0.0) <= time.time()]
    if not usable:
        raise RuntimeError("all AI providers are cooling down")
    if timeout is None:
        try:
            timeout = max(30, min(240, int(os.environ.get("CB_AI_TIMEOUT", "60"))))
        except (TypeError, ValueError):
            timeout = 120
    else:
        timeout = max(5, min(240, int(timeout)))
    last = None
    for brain in usable:
        for attempt in range(attempts_per_brain):
            try:
                return _call_one(brain, payload, timeout=timeout)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 404:
                    successor = _retired_model_successor(e)
                    if successor:
                        try:
                            return _call_one(brain, payload, model_override=successor)
                        except urllib.error.HTTPError:
                            pass
                    break
                if e.code in (400, 401, 402, 403):
                    if brain["name"] == "pollinations" and e.code in (400, 402):
                        # The shared no-key fallback is rate-limited/paid now. Stop
                        # asking it on every chunk for the rest of the job.
                        _COOLDOWN[brain["name"]] = time.time() + 1800
                    break
                if e.code == 429:
                    # Do not burn the request budget waiting on an exhausted key:
                    # cool this provider down and fail over immediately. The editor
                    # chunks and the judge have other providers to try.
                    retry_after = e.headers.get("Retry-After")
                    wait = min(90, float(retry_after)) if (retry_after or "").replace(".", "").isdigit() \
                        else 15 + attempt * 15
                    _COOLDOWN[brain["name"]] = time.time() + max(5.0, wait)
                    break
                time.sleep(2 + attempt * 3)
            except (EmptyAnswer, urllib.error.URLError, TimeoutError, OSError, KeyError,
                    ValueError) as e:
                last = e
                if _is_local(brain):
                    # A slow/hung local model must not be retried for every editor
                    # chunk and every judge batch; one failure cools it for 5 min.
                    _COOLDOWN[brain["name"]] = time.time() + 300
                    break
                _COOLDOWN[brain["name"]] = time.time() + 15
                time.sleep(2 + attempt * 3)
    raise last or RuntimeError("all AI brains failed")
