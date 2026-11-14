"""Generic provider store tests - stdlib only, no external network.

Run from the studio root:   python scripts/test_providers.py

Locks down the single "Add provider" model: validation, masked secrets, persistence,
ordering, the brain pool, speech-to-text selection, model discovery and a live test
against a local OpenAI-compatible stub.
"""

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402
from clipblitz import providers, brains, stt  # noqa: E402

RESULTS = []
TMP = tempfile.mkdtemp(prefix="cb_providers_")
CONFIG["data_dir"] = TMP


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def reset():
    try:
        os.remove(providers._file())
    except OSError:
        pass
    providers._CACHE.update(at=0.0, mtime=None, data=None)


class Stub(BaseHTTPRequestHandler):
    key = "good-key-123456"
    calls = []

    def log_message(self, *a):
        pass

    def _json(self, code, obj, extra=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        return self.headers.get("Authorization") == f"Bearer {self.key}"

    def do_GET(self):
        Stub.calls.append(("GET", self.path))
        if self.path.endswith("/models") and self._auth():
            return self._json(200, {"object": "list", "data": [{"id": "model-a"}, {"id": "model-b"}]})
        return self._json(401, {"error": "bad key"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        Stub.calls.append(("POST", self.path, body.get("model")))
        if not self._auth():
            return self._json(401, {"error": "bad key"})
        return self._json(200, {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"total_tokens": 12},
        })


def test_store():
    reset()
    check("providers: no store yet", providers.load() is None and providers.pool() is None)

    old_legacy = brains.legacy_pool
    brains.legacy_pool = lambda: [
        {"name": "Legacy Groq", "base": "https://grow.example/v1", "key": "legacy-secret-1234",
         "model": "model-x", "headers": {}, "stt": True, "stt_model": "whisper-x"},
        {"name": "no-key", "base": "https://nokey.example/v1", "key": "", "model": "m"},
    ]
    try:
        pub = providers.public()
    finally:
        brains.legacy_pool = old_legacy
    check("providers: opening Connect imports the legacy entries once",
          pub["count"] == 1 and pub["providers"][0]["name"] == "Legacy Groq", str(pub["count"]))
    row = pub["providers"][0]
    check("providers: a key is never returned in clear",
          "legacy-secret-1234" not in json.dumps(pub) and row["has_key"] and row["key_hint"] == "1234",
          row.get("key_hint"))
    check("providers: the store file is owner-only on POSIX",
          not hasattr(os, "geteuid") or (os.stat(providers._file()).st_mode & 0o777) == 0o600)

    added = providers.upsert({"name": "Stub", "base": "http://127.0.0.1:9/v1",
                              "api_key": "stub-secret-5678", "model": "model-a",
                              "context": 128000, "max_tokens": 512,
                              "temperature": 0.2, "headers": {"X-Test": "yes"}})
    check("providers: add persists a new endpoint", added["count"] == 2)
    stub = next(p for p in added["providers"] if p["name"] == "Stub")
    check("providers: advanced fields survive a round trip",
          stub["context"] == 128000 and stub["max_tokens"] == 512 and stub["temperature"] == 0.2,
          str(stub))
    check("providers: custom header values are not returned",
          stub["header_names"] == ["X-Test"] and "yes" not in json.dumps(stub), str(stub.get("header_names")))

    kept = providers.upsert({"id": stub["id"], "name": "Stub", "base": "http://127.0.0.1:9/v1",
                             "model": "model-b"})
    kept_stub = next(p for p in kept["providers"] if p["id"] == stub["id"])
    check("providers: a blank key keeps the saved one",
          kept_stub["has_key"] and kept_stub["model"] == "model-b", str(kept_stub))
    cleared = providers.upsert({"id": stub["id"], "name": "Stub", "base": "http://127.0.0.1:9/v1",
                                "model": "model-b", "clear_key": True})
    check("providers: a key can be cleared",
          not next(p for p in cleared["providers"] if p["id"] == stub["id"])["has_key"])

    for bad, why in (
        ({"name": "x", "base": "ftp://x", "model": "m"}, "base"),
        ({"name": "", "base": "https://x", "model": "m"}, "name"),
        ({"name": "x", "base": "https://x", "model": ""}, "model"),
    ):
        try:
            providers.upsert(bad)
            ok = False
        except ValueError:
            ok = True
        check(f"providers: validation rejects a bad {why}", ok)

    order = [p["id"] for p in cleared["providers"]]
    reordered = providers.reorder(list(reversed(order)))
    check("providers: order is stored",
          [p["id"] for p in reordered["providers"]] == list(reversed(order)))

    rows = providers.pool()
    check("providers: the brain pool is the enabled entries",
          [r["model"] for r in rows] == [p["model"] for p in reordered["providers"] if p["enabled"]],
          str([(r["name"], r["model"]) for r in rows]))

    # enabled/disabled
    first = reordered["providers"][0]
    providers.upsert({"id": first["id"], "name": first["name"], "base": first["base"],
                      "model": first["model"], "enabled": False})
    check("providers: a disabled entry leaves the pool",
          all(r["id"] != first["id"] for r in (providers.pool() or [])))

    # empty store means no AI, not a fallback to legacy
    for p in list((providers.load() or {"providers": []})["providers"]):
        providers.delete(p["id"])
    BRAINS = brains.brains()
    check("providers: deleting every provider means offline mode",
          BRAINS == [] and providers.load() is not None, str(BRAINS))


def test_stt_selection():
    reset()
    providers.upsert({"name": "A", "base": "https://a.example/v1", "model": "m-a",
                      "stt": False})
    providers.upsert({"name": "B", "base": "https://b.example/v1", "model": "m-b",
                      "stt": True, "stt_model": "whisper-b", "api_key": "k-123456789"})
    p = providers.stt_provider()
    check("providers: the STT provider is the marked entry",
          p and p["name"] == "B" and p["stt_model"] == "whisper-b",
          str(p and {k: p[k] for k in ("name", "stt_model")}))
    target = stt._target()
    check("providers: transcription targets the marked provider",
          target["base"] == "https://b.example/v1" and target["model"] == "whisper-b",
          str(target))


def test_live_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/v1"
    try:
        models = providers.find_models(base, Stub.key)
        check("providers: Find models reads the provider's own list",
              models == ["model-a", "model-b"], str(models))
        try:
            providers.find_models(base, "wrong-key-000000")
            ok = False
        except ValueError as e:
            ok = "401" in str(e)
        check("providers: a rejected key is reported, not hidden", ok)

        result = providers.test({"name": "Stub", "base": base, "model": "model-a",
                                 "api_key": Stub.key})
        check("providers: Test connection talks to the configured endpoint",
              result["ok"] and result["latency_ms"] >= 0 and result["model"] == "model-a",
              str(result))
        check("providers: Test connection used the exact model id",
              ("POST", "/v1/chat/completions", "model-a") in Stub.calls, str(Stub.calls[-2:]))
        try:
            providers.test({"name": "Stub", "base": base, "model": "model-a",
                            "api_key": "wrong-key-000000"})
            ok = False
        except ValueError as e:
            ok = "401" in str(e) and "wrong-key" not in str(e)
        check("providers: a failing Test is an error and masks the key", ok)
    finally:
        server.shutdown()
        server.server_close()


def test_ui_contract():
    html = open(os.path.join(STUDIO, "web", "index.html"), encoding="utf-8").read()
    js = open(os.path.join(STUDIO, "web", "app.js"), encoding="utf-8").read()
    check("providers: Connect has one Add provider button", "provider-add" in html)
    check("providers: the popup has base, key, model and context",
          all(x in html for x in ("pv-base", "pv-key", "pv-model", "pv-context")))
    check("providers: the popup has Find models and Test", "pv-find" in html and "pv-test" in html)
    check("providers: the old fixed provider grid is gone", "provider-keys" not in html)
    check("providers: the UI calls the generic endpoints",
          "/api/providers" in js and "/api/providers/find-models" in js)


def main():
    test_store()
    test_stt_selection()
    test_live_stub()
    test_ui_contract()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
