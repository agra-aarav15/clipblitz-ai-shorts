"""Generic OpenAI-compatible providers - one config store, no hardcoded vendor grid.

Every entry is the same shape:

    {id, name, base, key, model, context, max_tokens, temperature, headers,
     stt, stt_model, enabled}

The Connect screen adds/edits these entries in a modal (base URL, optional key, exact
model id, context and advanced fields). Keys are stored in data/providers.json with
owner-only permissions and are never returned by the API unmasked.

The store is the source of truth once it exists. Before it exists, brains() keeps
using the legacy .env pool, so an existing install and CI keep working; opening
Connect migrates the legacy entries once.
"""

import json
import os
import re
import threading
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .config import CONFIG

VERSION = 1
MODEL_RE = re.compile(r"^[\w.\-:/@+]{1,200}$")
NAME_MAX = 60
HEADER_MAX = 24
CACHE_SECONDS = 1.0

_LOCK = threading.RLock()
_CACHE = {"at": 0.0, "mtime": None, "data": None}


def _file():
    return os.path.join(CONFIG["data_dir"], "providers.json")


def exists():
    return os.path.isfile(_file())


def _empty():
    return {"version": VERSION, "providers": []}


def _read():
    path = _file()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rows = data.get("providers")
    if not isinstance(rows, list):
        rows = []
    clean = []
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            clean.append(_normalise(row))
    return {"version": VERSION, "providers": clean}


def load():
    """The store, or None when it has never been created. Cached by mtime."""
    path = _file()
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    now = datetime.now(timezone.utc).timestamp()
    if (_CACHE["data"] is not None and _CACHE["mtime"] == mtime
            and now - _CACHE["at"] < CACHE_SECONDS):
        return _CACHE["data"]
    data = _read()
    if data is None:
        return None
    _CACHE.update(at=now, mtime=mtime, data=data)
    return data


def _save(data):
    with _LOCK:
        path = _file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "providers": data["providers"]}, f,
                      indent=1, ensure_ascii=False)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        _CACHE.update(at=0.0, mtime=None, data=None)


def _text(value, limit):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()[:limit]


def _normalise(row):
    """Whatever is on disk, only this shape is used by the rest of the app."""
    return {
        "id": str(row.get("id") or ("p_" + uuid.uuid4().hex[:10])),
        "name": _text(row.get("name"), NAME_MAX) or "Provider",
        "base": _text(row.get("base"), 500).rstrip("/"),
        "key": str(row.get("key") or "").strip(),
        "model": _text(row.get("model"), 200),
        "context": _int(row.get("context"), 0),
        "max_tokens": _int(row.get("max_tokens"), 0),
        "temperature": _float(row.get("temperature")),
        "headers": _headers(row.get("headers")),
        "stt": bool(row.get("stt")),
        "stt_model": _text(row.get("stt_model"), 200),
        "enabled": row.get("enabled", True) is not False,
        "created": row.get("created") or "",
    }


def _int(value, default=0):
    try:
        return max(0, min(10_000_000, int(float(value))))
    except (TypeError, ValueError):
        return default


def _float(value):
    if value in (None, ""):
        return None
    try:
        return round(max(0.0, min(2.0, float(value))), 3)
    except (TypeError, ValueError):
        return None


def _headers(value):
    if not isinstance(value, dict):
        return {}
    out = {}
    for k, v in list(value.items())[:HEADER_MAX]:
        name = _text(k, 80)
        if not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            continue
        out[name] = _text(v, 500)
    return out


def _validate(row):
    name = _text(row.get("name"), NAME_MAX)
    if not name:
        raise ValueError("Give the provider a name.")
    base = _text(row.get("base"), 500).rstrip("/")
    if base:
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Base URL must start with http:// or https://")
        if " " in base:
            raise ValueError("Base URL cannot contain spaces.")
    model = _text(row.get("model"), 200)
    stt_model = _text(row.get("stt_model"), 200)
    if model and not MODEL_RE.match(model):
        raise ValueError("Model id may contain letters, digits and . - : / @ + only.")
    if stt_model and not MODEL_RE.match(stt_model):
        raise ValueError("Transcription model id has invalid characters.")
    if not model and not (row.get("stt") and stt_model):
        raise ValueError("Enter the exact model id.")
    if not base and not model:
        raise ValueError("Enter the provider's base URL and model.")
    return {
        "name": name, "base": base, "model": model,
        "stt": bool(row.get("stt")), "stt_model": stt_model,
        "context": _int(row.get("context"), 0),
        "max_tokens": _int(row.get("max_tokens"), 0),
        "temperature": _float(row.get("temperature")),
        "headers": _headers(row.get("headers")),
        "enabled": row.get("enabled", True) is not False,
    }


def _unique_name(name, rows, keep_id=None):
    names = {r["name"].strip().lower() for r in rows if r["id"] != keep_id}
    if name.lower() not in names:
        return name
    for n in range(2, 100):
        candidate = f"{name} {n}"[:NAME_MAX]
        if candidate.lower() not in names:
            return candidate
    return f"{name} {uuid.uuid4().hex[:4]}"[:NAME_MAX]


def public():
    """The safe view for the Connect screen. No full key, no secret header value."""
    data = load()
    if data is None:
        data = load_or_import()
    rows = data["providers"] if data else []
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "name": r["name"], "base": r["base"],
            "model": r["model"], "context": r["context"],
            "max_tokens": r["max_tokens"], "temperature": r["temperature"],
            "header_names": sorted(r["headers"]),
            "stt": r["stt"], "stt_model": r["stt_model"],
            "enabled": r["enabled"], "has_key": bool(r["key"]),
            "key_hint": (r["key"][-4:] if len(r["key"]) >= 8 else ""),
        })
    active = next((r["name"] for r in rows if r["enabled"] and r["stt"]
                   and r["stt_model"]), "")
    return {"providers": out, "count": len(out), "stt_provider": active,
            "ready": any(r["enabled"] and (r["model"] or r["stt_model"]) for r in rows),
            "store": _file()}


def load_or_import():
    """First visit to Connect: turn the legacy .env providers into editable entries."""
    data = load()
    if data is not None:
        return data
    rows = []
    try:
        from . import brains
        legacy = brains.legacy_pool()
    except Exception:
        legacy = []
    for entry in legacy:
        name = entry.get("name") or "Provider"
        if not entry.get("base"):
            continue
        if not entry.get("key") and not str(name).startswith(("local", "ollama")):
            continue
        rows.append(_normalise({
            "id": "p_" + uuid.uuid4().hex[:10],
            "name": name, "base": entry.get("base"), "key": entry.get("key"),
            "model": entry.get("model"), "headers": entry.get("headers") or {},
            "stt": str(name) in ("groq", "openai") or "whisper" in str(entry.get("model", "")).lower(),
            "stt_model": (os.environ.get("CB_STT_MODEL") or
                          ("whisper-large-v3-turbo" if "groq" in (entry.get("base") or "") else "")),
            "enabled": True,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }))
    data = {"version": VERSION, "providers": rows}
    _save(data)
    return data


def upsert(payload):
    if not isinstance(payload, dict):
        raise ValueError("bad provider")
    # Adding the first provider must not silently import the legacy .env pool; the
    # one-time migration runs on the first Connect read, not on a direct POST.
    data = load() or {"version": VERSION, "providers": []}
    rows = data["providers"]
    pid = str(payload.get("id") or "").strip()
    existing = next((r for r in rows if r["id"] == pid), None)
    row = _validate({
        "name": payload.get("name"), "base": payload.get("base"),
        "model": payload.get("model"), "context": payload.get("context"),
        "max_tokens": payload.get("max_tokens"),
        "temperature": payload.get("temperature"),
        "headers": payload.get("headers") if "headers" in payload else (existing or {}).get("headers"),
        "stt": payload.get("stt", (existing or {}).get("stt", False)),
        "stt_model": payload.get("stt_model", (existing or {}).get("stt_model", "")),
        "enabled": payload.get("enabled", (existing or {}).get("enabled", True)),
    })
    if existing is None:
        row["id"] = "p_" + uuid.uuid4().hex[:10]
        row["created"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row["key"] = str(payload.get("api_key") or "").strip()
        rows.append(row)
    else:
        row["id"] = existing["id"]
        row["created"] = existing.get("created") or ""
        if payload.get("clear_key"):
            row["key"] = ""
        elif str(payload.get("api_key") or "").strip():
            row["key"] = str(payload["api_key"]).strip()
        else:
            row["key"] = existing.get("key", "")
        existing.update(row)
    row["name"] = _unique_name(row["name"], rows, keep_id=row["id"])
    _save(data)
    return public()


def delete(pid):
    data = load() or {"version": VERSION, "providers": []}
    before = len(data["providers"])
    data["providers"] = [r for r in data["providers"] if r["id"] != pid]
    _save(data)
    return {"deleted": before != len(data["providers"]), **public()}


def reorder(ids):
    data = load() or {"version": VERSION, "providers": []}
    order = {str(pid): i for i, pid in enumerate(ids or [])}
    data["providers"].sort(key=lambda r: order.get(r["id"], len(order)))
    _save(data)
    return public()


def pool():
    """Enabled entries as brains: {name, base, key, model, headers, ...}."""
    data = load()
    if data is None:
        return None
    out = []
    for r in data["providers"]:
        if not r["enabled"]:
            continue
        if not r["base"] or not (r["model"] or (r["stt"] and r["stt_model"])):
            continue
        out.append({
            "id": r["id"], "name": r["name"], "label": r["name"],
            "base": r["base"], "key": r["key"], "model": r["model"],
            "headers": dict(r["headers"]), "context": r["context"],
            "max_tokens": r["max_tokens"], "temperature": r["temperature"],
            "stt": r["stt"], "stt_model": r["stt_model"],
        })
    return out


def stt_provider():
    data = load()
    if data is None:
        return None
    for r in data["providers"]:
        if r["enabled"] and r["stt"] and r["stt_model"] and r["base"]:
            return dict(r)
    return None


def _sanitize(text, key=""):
    s = str(text or "")[:400]
    if key and len(key) >= 6:
        s = s.replace(key, "<key>")
    return s


def _request_json(url, headers, payload=None, timeout=30):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "ClipBlitz/5.5", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8", "replace"))


def find_models(base, key="", headers=None, pid=None):
    base = str(base or "").strip().rstrip("/")
    if not re.match(r"^https?://", base):
        raise ValueError("Base URL must start with http:// or https://")
    stored = {}
    if pid:
        data = load() or {"providers": []}
        stored = next((r for r in data["providers"] if r["id"] == pid), {}) or {}
        if not key:
            key = stored.get("key", "")
        if not headers:
            headers = stored.get("headers") or {}
    hdr = {"Authorization": f"Bearer {key}"} if key else {}
    hdr.update(_headers(headers))
    try:
        data = _request_json(f"{base}/models", hdr)
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code} from /models")
    except Exception as e:
        raise ValueError(f"Could not reach /models: {type(e).__name__}")
    found = []
    for m in (data.get("data") or data.get("models") or []):
        if isinstance(m, dict):
            mid = m.get("id") or m.get("name") or ""
            if isinstance(mid, str):
                found.append(mid.split("/")[-1] if mid.startswith("models/") else mid)
    return sorted({m for m in found if m})[:500]


def test(payload):
    """One tiny chat request with the form's values (unsaved is fine)."""
    row = _validate({
        "name": payload.get("name") or "Provider", "base": payload.get("base"),
        "model": payload.get("model"), "context": payload.get("context"),
        "max_tokens": payload.get("max_tokens"),
        "temperature": payload.get("temperature"),
        "headers": payload.get("headers"),
        "stt": payload.get("stt"), "stt_model": payload.get("stt_model"),
    })
    key = str(payload.get("api_key") or "").strip()
    if not key and payload.get("id"):
        data = load() or {"providers": []}
        old = next((r for r in data["providers"] if r["id"] == payload["id"]), None)
        key = (old or {}).get("key", "")
        if not payload.get("headers") and old:
            row["headers"] = old.get("headers") or {}
    if not row["model"]:
        raise ValueError("Enter the exact model id to test chat.")
    started = datetime.now(timezone.utc).timestamp()
    hdr = {"Authorization": f"Bearer {key}"} if key else {}
    hdr.update(row["headers"])
    body = {
        "model": row["model"],
        "messages": [{"role": "user", "content": 'Reply with JSON only: {"ok": true}'}],
        "temperature": 0.1,
        "max_tokens": 32,
    }
    if row.get("temperature") is not None:
        body["temperature"] = row["temperature"]
    if row.get("max_tokens"):
        body["max_tokens"] = row["max_tokens"]
    try:
        data = _request_json(f"{row['base']}/chat/completions", hdr, body, timeout=45)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = _sanitize(e.read().decode("utf-8", "replace"), key)
        except Exception:
            pass
        raise ValueError(f"HTTP {e.code} {detail}".strip())
    except Exception as e:
        raise ValueError(f"Could not reach chat/completions: {type(e).__name__}")
    answer = ""
    try:
        answer = (data["choices"][0]["message"].get("content") or "")[:160]
    except (KeyError, IndexError, TypeError):
        pass
    return {"ok": True, "model": row["model"],
            "latency_ms": int((datetime.now(timezone.utc).timestamp() - started) * 1000),
            "answer": answer, "usage": data.get("usage") or {}}
