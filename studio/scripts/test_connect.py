"""Connect-screen tests - stdlib only, no network.

Run from the studio root:   python scripts/test_connect.py

The Connect screen used to expose only Groq and Gemini. These tests lock down the
provider list, the .env merge, and the routing validation that the UI calls.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz import keys  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def test_provider_list():
    st = keys.status()
    names = [p["key"] for p in st.get("providers", [])]
    want = {"groq", "gemini", "cerebras", "openrouter", "together", "openai",
            "pollinations", "local_base", "local_model", "ai_order"}
    check("connect: every supported provider is exposed", want <= set(names), str(names))
    check("connect: provider metadata has labels and hints",
          all(p.get("label") and p.get("hint") for p in st["providers"]))
    check("connect: secrets are never returned in clear",
          all(not (p.get("secret") and p.get("masked") and "****" not in p["masked"])
              for p in st["providers"] if p.get("set")))


def test_save_merge():
    old = keys.ENV_PATH
    tmp = tempfile.mkdtemp(prefix="cb_keys_")
    path = os.path.join(tmp, ".env")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("CB_AI_KEY=old-groq\n# CB_LOCAL_MODEL=qwen2.5:3b\n")
        keys.ENV_PATH = path
        r = keys.save({"local_model": "clipblitz-local", "ai_order": "groq,local"})
        text = open(path, encoding="utf-8").read()
        check("connect: save reports the fields it wrote",
              set(r.get("saved") or []) == {"local_model", "ai_order"}, str(r.get("saved")))
        check("connect: save preserves an existing key", "CB_AI_KEY=old-groq" in text)
        check("connect: save uncomments a placeholder in place",
              "CB_LOCAL_MODEL=clipblitz-local" in text)
        check("connect: save appends a new variable", "CB_AI_ORDER=groq,local" in text)
    finally:
        keys.ENV_PATH = old
        try:
            os.remove(path)
            os.rmdir(tmp)
        except OSError:
            pass


def test_order_validation():
    check("connect: a valid provider order passes",
          keys.test("ai_order", "groq,gemini,local,pollinations")["ok"])
    bad = keys.test("ai_order", "groq,not-a-provider")
    check("connect: an unknown provider is rejected", not bad["ok"], bad.get("detail"))


def main():
    test_provider_list()
    test_save_merge()
    test_order_validation()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
