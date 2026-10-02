"""Trainer tests for ClipBlitz Studio - stdlib only, offline, no ffmpeg.

Run from the studio root:   python scripts/test_trainer.py

What is proven:

  1. THE STORE LEARNS "KEPT VERSUS OFFERED". A choice stores up to MAX_SIBLINGS real
     alternatives (score + measured factors), never the kept window itself; a v2 event
     without siblings still loads and still contributes its pool comparison.
  2. THE FIT IS A PURE FUNCTION OF THE STORE. Two fits on the same pairs produce the
     same weights; a refit that cannot strictly beat the active model is rejected and
     leaves model.json byte-for-byte untouched.
  3. THE GATE IS EVIDENCE, NOT HOPE. A candidate activates only when the newest fifth
     of real choices says it ranks kept cuts above what they beat, at 0.55 or better;
     machine judge pairs alone never activate anything.
  4. THE CADENCE IS DAY BY DAY. Nothing fits below MIN_FIT_EVENTS choices; after that,
     one attempt per REFIT_EVERY further choices, each one line in data/model_log.json.
  5. CB_LAB=0 REMOVES THE LAYER. No sibling vectors stored, no fits, no model block in
     profile(), no model files: exactly the v4.1.0 learning behavior.

Every store lives in a throwaway temp data dir, so this never touches real data.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_train_")

from clipblitz import agent, learning, trainer  # noqa: E402

RESULTS = []
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

BASE = {"hook": 50, "story": 50, "payoff": 50, "energy": 50, "pacing": 50, "event": 50}


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def factors(**kw):
    out = dict(BASE)
    out.update(kw)
    return out


def clip(**kw):
    base = {"engine_id": "b2", "score": 80, "duration": 40.0, "laugh_ending": False,
            "hook": "A plain opening line", "title": "A clip"}
    base.update(kw)
    return base


def event(t, kept=None, sibs=None, kind="post", engine="b2"):
    """One stored choice, written directly so tests control the store exactly."""
    out = {"t": t, "kind": kind, "engine": engine, "score": 80, "duration": 40.0,
           "laugh_ending": False, "question_hook": False, "source": "", "rights": "own"}
    if kept:
        out["factors"] = kept
    if sibs is not None:
        out["sib"] = [{"score": 70 - i, "factors": s} for i, s in enumerate(sibs)]
    return out


def setup(events=None, jobs=None):
    """A fresh throwaway store for one scenario."""
    os.makedirs(CONFIG["data_dir"], exist_ok=True)
    learning.reset()
    trainer.reset()
    for name in ("jobs.json", "model.json", "model_log.json"):
        path = os.path.join(CONFIG["data_dir"], name)
        if os.path.exists(path):
            os.remove(path)
    if jobs is not None:
        with open(os.path.join(CONFIG["data_dir"], "jobs.json"), "w", encoding="utf-8") as f:
            json.dump(jobs, f)
    if events is not None:
        with open(learning._file(), "w", encoding="utf-8") as f:
            json.dump({"events": events, "version": learning.STORE_VERSION}, f)


def learnable_events(n=30, spread=True):
    """n real choices where the kept cut measures clearly above every sibling on
    payoff: a consistent signal the model can honestly find."""
    now = time.time()
    evs = []
    for i in range(n):
        kept = factors(payoff=78 + (i % 5) if spread else 80)
        sibs = [factors(payoff=38 + ((i * 7) % 5) if spread else 40) for _ in range(8)]
        evs.append(event(now - (n - i) * 3600, kept=kept, sibs=sibs))
    return evs


def judged_jobs(n=2):
    jobs = []
    for j in range(n):
        cands = []
        for i, score in enumerate((88, 70, 62, 50)):
            cands.append({"score": score, "start": i * 30.0, "end": i * 30.0 + 25.0,
                          "factors": factors(payoff=50 + i * 5)})
        jobs.append({"id": f"j{j}", "created": time.time() - j * 86400,
                     "candidates": cands})
    return jobs


def model_path():
    return os.path.join(CONFIG["data_dir"], "model.json")


# ------------------------------------------------------------ 1. the v3 store

def test_store_stores_siblings():
    setup()
    job = {"engine_id": "b2", "candidates": [
        {"score": 70, "start": 300.0, "end": 330.0, "factors": factors(hook=60)},
        {"score": 90, "start": 100.0, "end": 130.0, "factors": factors(hook=90)},
        {"score": 80, "start": 200.0, "end": 230.0, "factors": factors(hook=80)},
        {"score": 95, "start": 10.0, "end": 40.0, "factors": factors(hook=95)},
    ]}
    e = learning.log("post", clip(start=10.0, end=40.0, factors=factors(hook=97)), job)
    check("store: v3 stamps the store version", learning.STORE_VERSION == 3)
    sib = e.get("sib") or []
    check("store: the choice carries its offered alternatives", len(sib) == 3,
          str(len(sib)))
    check("store: the kept window itself is never a sibling",
          all(not (s["score"] == 95 and s["factors"]["hook"] == 95) for s in sib))
    check("store: alternatives are strongest-score first",
          [s["score"] for s in sib] == [90, 80, 70], str([s["score"] for s in sib]))
    check("store: every alternative keeps its measured factors",
          all(set(s["factors"]) == set(learning.FACTORS) for s in sib))

    cands = [{"score": 60 + i, "start": i * 10.0, "end": i * 10.0 + 8.0,
              "factors": factors(hook=40 + i)} for i in range(12)]
    e = learning.log("post", clip(start=999.0, end=1000.0, factors=factors()),
                     {"candidates": cands})
    check("store: at most MAX_SIBLINGS alternatives are kept",
          len(e["sib"]) == learning.MAX_SIBLINGS == 8, str(len(e["sib"])))

    winner, loser = clip(factors=factors(payoff=90)), clip(factors=factors(payoff=30))
    e = learning.log("judge", winner, None, other=loser)
    check("store: a judgement stores the rejected cut as its sibling",
          e["kind"] == "judge" and len(e["sib"]) == 1
          and e["sib"][0]["factors"]["payoff"] == 30)


def test_v2_events_still_load_and_train():
    now = time.time()
    legacy = [event(now - (10 - i) * 90000, kept=factors(payoff=80)) for i in range(10)]
    for e in legacy:                      # v2 shape: a pool mean, no sibling vectors
        e["pool"] = factors(payoff=50)
        e["pool_n"] = 9
    setup(events=legacy)
    check("v2: a sibling-less store still loads", len(learning.events()) == 10)
    check("v2: profile still reports it", learning.profile()["model"]["events"] == 10)
    res = trainer.run_fit()
    check("v2: the fit falls back to the pool mean as one weak comparator",
          res["attempted"] and res["human_pairs"] == 8 and res["holdout_n"] == 2,
          f"human {res.get('human_pairs')} holdout {res.get('holdout_n')}")
    check("v2: the pool comparison can honestly clear the gate",
          res["activated"] is True and res["holdout"] == 1.0, str(res.get("holdout")))


# ------------------------------------------------- 2. pretrain from judge history

def test_pretrain_pairs_from_judge_history():
    setup(jobs=judged_jobs(2))
    res = trainer.run_fit()
    check("pretrain: judge verdicts become machine pairs",
          res["attempted"] and res["machine_pairs"] == 12, str(res.get("machine_pairs")))
    check("pretrain: a machine prior alone never activates a model",
          res["activated"] is False and res["holdout"] is None)
    check("pretrain: the reason says what is missing",
          "held-out" in res["reason"], res["reason"])
    jobs = judged_jobs(1)
    jobs[0]["candidates"] = jobs[0]["candidates"][:2]     # 88 vs 70: one pair
    setup(jobs=jobs)
    res = trainer.run_fit()
    check("pretrain: the margin rule rejects near-ties",
          res["machine_pairs"] == 1, str(res.get("machine_pairs")))


# ----------------------------------------------------------- 3. the gate itself

def test_gate_rule():
    check("gate: no held-out choices -> rejected", trainer._decide(None, None, 0)[0] is False)
    check("gate: below 0.55 -> rejected", trainer._decide(0.50, None, 20)[0] is False)
    check("gate: 0.55 exactly clears the absolute bar",
          trainer._decide(0.55, None, 20)[0] is True)
    check("gate: a candidate below the incumbent is rejected",
          trainer._decide(0.60, 0.65, 20)[0] is False)
    check("gate: a tie does not replace the incumbent",
          trainer._decide(0.70, 0.70, 20)[0] is False)
    check("gate: a strict improvement replaces it",
          trainer._decide(0.72, 0.70, 20)[0] is True)


def test_fit_activates_and_is_deterministic():
    setup(events=learnable_events(30))
    first = trainer.run_fit()
    check("fit: a real signal activates the first model",
          first["activated"] is True and first["holdout"] == 1.0, str(first.get("holdout")))
    model = json.load(open(model_path(), encoding="utf-8"))
    check("fit: the model stores weights and scale for every factor",
          set(model["weights"]) == set(trainer.FEATURES)
          and set(model["scale"]) == set(trainer.FEATURES))
    check("fit: payoff learned the real direction", model["weights"]["payoff"] > 0)
    check("fit: payoff is the strongest factor",
          max(model["weights"], key=lambda k: abs(model["weights"][k])) == "payoff")

    events = learning.events()
    train = trainer._machine_pairs() + trainer._human_pairs(events)[0]
    check("determinism: the same pairs fit the same weights",
          trainer._fit(train) == trainer._fit(train))
    check("determinism: a refit on the same pairs records the same holdout",
          trainer.run_fit()["holdout"] == first["holdout"])


def test_rejections_leave_the_incumbent_intact():
    setup(events=learnable_events(30))
    trainer.run_fit()
    before = json.dumps(json.load(open(model_path(), encoding="utf-8")), sort_keys=True)

    now = time.time()
    evs = learning.events()
    for i in range(5):                    # choices that separate nothing: no signal
        evs.append(event(now + i, kept=factors(payoff=55), sibs=[factors(payoff=55)]))
    learning._save({"events": evs, "version": learning.STORE_VERSION})
    res = trainer.run_fit()
    check("gate: a refit that only ties the incumbent is rejected",
          res["activated"] is False and "did not beat" in res["reason"], res["reason"])
    check("gate: the rejected candidate left the active model byte-for-byte intact",
          json.dumps(json.load(open(model_path(), encoding="utf-8")), sort_keys=True) == before)
    fits = trainer._fits()
    check("gate: the rejection is one line in the fit log",
          len(fits) == 2 and fits[-1]["activated"] is False, str(len(fits)))

    now = time.time()
    noise = [event(now - (30 - i) * 3600, kept=factors(payoff=60),
                   sibs=[factors(payoff=60)]) for i in range(30)]
    setup(events=noise)
    res = trainer.run_fit()
    check("gate: a first fit that cannot separate anything writes no model file",
          res["activated"] is False and res["holdout"] == 0.0
          and not os.path.exists(model_path()), str(res.get("holdout")))


# -------------------------------------------------------- 4. the daily cadence

def test_cadence_and_log_lines():
    setup()
    learning._save({"events": learnable_events(trainer.MIN_FIT_EVENTS - 1),
                    "version": learning.STORE_VERSION})
    check("cadence: nothing fits below MIN_FIT_EVENTS", trainer.auto_fit() is None)

    learning.log("post", clip(factors=factors(payoff=90)),
                 {"engine_id": "b2", "candidates": [
                     {"score": 70, "start": 500.0, "end": 540.0,
                      "factors": factors(payoff=40)}]})
    fits = trainer._fits()
    check("cadence: the MIN_FIT_EVENTS-th choice triggers exactly one fit",
          len(fits) == 1, str(len(fits)))
    check("cadence: the fit records the store it saw", fits[0]["events"] == trainer.MIN_FIT_EVENTS)
    check("cadence: the fit line carries day, version, pairs, holdout, activated, reason",
          all(k in fits[0] for k in ("day", "version", "pairs", "holdout",
                                     "activated", "reason")))
    check("cadence: the day is a real calendar date", bool(DAY_RE.match(fits[0]["day"])),
          fits[0]["day"])
    check("cadence: the line records the evidence it used",
          fits[0]["pairs"] > 0 and fits[0]["holdout_n"] > 0)
    check("cadence: versions step one per attempt", fits[0]["version"] == 1)

    for _ in range(trainer.REFIT_EVERY - 1):
        learning.log("post", clip(factors=factors(payoff=90)), {"engine_id": "b2"})
    check("cadence: fewer than REFIT_EVERY new choices do not fit again",
          len(trainer._fits()) == 1)
    learning.log("post", clip(factors=factors(payoff=90)), {"engine_id": "b2"})
    check("cadence: the REFIT_EVERY-th new choice fits again",
          len(trainer._fits()) == 2)
    check("cadence: the second attempt is version 2",
          trainer._fits()[-1]["version"] == 2)


# ------------------------------------------------------------- 5. the surfaces

def test_profile_model_block():
    setup()
    block = learning.profile().get("model") or {}
    check("profile: the model block exists on a fresh store",
          block.get("enabled") is True and block.get("active") is False)
    setup(events=learnable_events(30))
    block = learning.profile()["model"]
    check("profile: the cadence is visible before the first fit",
          block["events"] == 30 and block["remaining"] == 0
          and block["min_events"] == trainer.MIN_FIT_EVENTS)
    trainer.run_fit()
    block = learning.profile()["model"]
    check("profile: the active model reports version, holdout and weights",
          block["active"] is True and block["version"] == 1
          and block["holdout"] == 1.0 and set(block["weights"]) == set(trainer.FEATURES))
    check("profile: the fit history is visible",
          len(block["fits"]) == 1 and block["fits"][0]["activated"] is True)
    check("profile: the model moves the ranking through the same seam",
          trainer.blend().get("payoff", 1.0) > 1.0)
    check("profile: the model layer stays inside its +/-6% slice",
          all(1 - trainer.MODEL_DELTA <= v <= 1 + trainer.MODEL_DELTA
              for v in trainer.blend().values()), str(trainer.blend()))


def test_model_reaches_adjustment_and_resets():
    setup(events=learnable_events(30))
    trainer.run_fit()
    active = learning.adjustment()
    os.remove(model_path())
    without = learning.adjustment()
    check("ranking: the active model raises payoff through adjustment()",
          active.get("payoff", 1.0) > without.get("payoff", 1.0),
          f"{active.get('payoff')} vs {without.get('payoff')}")
    check("ranking: the global +/-10% cap still holds after the model layer",
          all(1 - learning.MAX_DELTA <= v <= 1 + learning.MAX_DELTA for v in active.values()))
    trainer.run_fit()                      # activate again, then reset
    learning.reset()
    check("reset: resetting the choices also forgets the model",
          not os.path.exists(model_path()) and not os.path.exists(
              os.path.join(CONFIG["data_dir"], "model_log.json")))
    check("reset: the ranking is back on the base weights",
          "model" not in learning.profile() or
          learning.profile()["model"]["active"] is False)


def test_lab_off_is_v410():
    setup(events=learnable_events(30))
    trainer.run_fit()
    lab_was = CONFIG["lab"]
    CONFIG["lab"] = False
    try:
        e = learning.log("post", clip(factors=factors(payoff=90)),
                         {"engine_id": "b2", "candidates": [
                             {"score": 70, "start": 5.0, "end": 30.0,
                              "factors": factors(payoff=10)}]})
        check("lab off: no sibling vectors are stored", "sib" not in e)
        check("lab off: profile carries no model block", "model" not in learning.profile())
        check("lab off: the cadence never runs", trainer.auto_fit() is None)
        check("lab off: an explicit fit refuses cleanly",
              trainer.run_fit() == {"enabled": False, "attempted": False,
                                    "activated": False,
                                    "reason": "the learning lab is off (CB_LAB=0)"})
        off = learning.adjustment()
    finally:
        CONFIG["lab"] = lab_was
    trainer.reset()
    check("lab off: its ranking equals a lab-on run with no model",
          learning.adjustment() == off)


def test_agent_surface():
    names = {t["name"] for t in agent.TOOLS}
    check("mcp: train_model is declared", "train_model" in names)
    tool = [t for t in agent.TOOLS if t["name"] == "train_model"][0]
    check("mcp: train_model declares a schema and an honest description",
          isinstance(tool.get("inputSchema"), dict)
          and "never touches the render engines" in tool["description"])
    port_was = CONFIG["port"]
    CONFIG["port"] = 49999                 # pretend no studio is listening for this call
    try:
        reply = agent.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                              "params": {"name": "train_model", "arguments": {}}})
        payload = json.loads(reply["result"]["content"][0]["text"])
        check("mcp: train_model runs and reports through the tool surface",
              payload.get("enabled") is True and "attempted" in payload, str(payload)[:120])
        check("mcp: a failed fit is reported as data, not an exception",
              "isError" not in reply["result"] or reply["result"].get("isError") is not True)
    finally:
        CONFIG["port"] = port_was


def test_api_keepalive_framing():
    """POST /api/train must consume its request body. An unread body stays in the
    socket and the next request on the same keep-alive connection parses as garbage -
    exactly what the UI does when it trains and then refreshes the card."""
    import http.client
    import threading
    from clipblitz import server as studio_server

    httpd = studio_server.QuietServer(("127.0.0.1", 0), studio_server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("POST", "/api/train", body=b"{}",
                     headers={"Content-Type": "application/json", "Content-Length": "2"})
        first = conn.getresponse()
        payload = json.loads(first.read())
        conn.request("GET", "/api/learning")
        second = conn.getresponse()
        body = json.loads(second.read())
        check("api: train then learning over one keep-alive connection",
              first.status == 200 and second.status == 200
              and payload.get("enabled") is True and "model" in body,
              f"{first.status}/{second.status}")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_run_entry_train():
    def run(*args, **env_extra):
        env = dict(os.environ, CB_DATA=CONFIG["data_dir"], **env_extra)
        return subprocess.run(
            [sys.executable, os.path.join(STUDIO, "run.py"), *args],
            input="", capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=STUDIO, timeout=180, env=env)

    res = run("--train")
    payload = json.loads(res.stdout)
    check("cli: run.py --train prints one JSON fit result, no banner",
          res.returncode == 0 and "Starting ClipBlitz Studio" not in res.stdout
          and payload.get("enabled") is True, f"rc={res.returncode}")
    check("cli: the result has the same shape as the API",
          "attempted" in payload and "reason" in payload)
    off = run("--train", CB_LAB="0")
    payload = json.loads(off.stdout)
    check("cli: CB_LAB=0 is refused cleanly and exits 0",
          off.returncode == 0 and payload.get("enabled") is False, str(payload)[:120])


def main():
    test_store_stores_siblings()
    test_v2_events_still_load_and_train()
    test_pretrain_pairs_from_judge_history()
    test_gate_rule()
    test_fit_activates_and_is_deterministic()
    test_rejections_leave_the_incumbent_intact()
    test_cadence_and_log_lines()
    test_profile_model_block()
    test_model_reaches_adjustment_and_resets()
    test_lab_off_is_v410()
    test_agent_surface()
    test_api_keepalive_framing()
    test_run_entry_train()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
