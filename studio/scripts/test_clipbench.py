"""ClipBench tests for ClipBlitz Studio - stdlib only, offline, no network, no ffmpeg.

Run from the studio root:   python scripts/test_clipbench.py

What is proven:

  1. EVERY CLAIM IS SCORED THE SAME WAY. The shipped baselines, the trained models and
     a fixed one-shot weight set that never learns run on the same pairs with the same
     rule - a tie is not a win - and the coin-flip reference is reported as 0.50 rather
     than pretending a constant scorer has an edge.
  2. NO LEAKAGE. The held-out slice is the newest fifth, so a model that is only right
     about the older choices scores 0.00 on the board; the test builds exactly that
     time-inverted pair set to prove the split is chronological and not a sample.
  3. IT CAN SAY THE MODEL LOST. An inverted model is scored as beaten by the plain
     baseline, and the verdict says so in words.
  4. NO EVIDENCE IS AN HONEST ANSWER. An empty install scores nothing: both families
     report "insufficient" with their real counts, no row invents a number, and "no
     active model" is a status of its own, not a low score.
  5. CB_CLIPBENCH=off and CB_LAB=0 remove the board: no run, no file, a 409 route and no
     clipbench key in the health payload. (The first health call is a hardware probe and
     is warmed up before it is asserted on, so a bare checkout without bin/ cannot time
     the suite out.)
  6. THE SURFACES AGREE. GET/POST /api/clipbench, the clipbench MCP tool and
     `run.py --bench` return the same board from the same stores.

Every store lives in a throwaway temp data dir, so this never touches real data.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_bench_")

from clipblitz import agent, clipbench, pipeline, scout, trainer  # noqa: E402

RESULTS = []
agent.port_open = lambda *a, **k: False      # never route a tool at a live studio

FACTORS = list(trainer.FEATURES)             # hook, story, payoff, energy, pacing, event
FEATURES = list(scout.FEATURES)              # velocity, reach, freshness, duration_fit, ...


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def data_path(name):
    return os.path.join(CONFIG["data_dir"], name)


def write_json(name, obj):
    with open(data_path(name), "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return data_path(name)


def clear_stores():
    for name in ("learning.json", "model.json", "model_log.json", "scout.json",
                 "scout_model.json", "scout_model_log.json", "bench.json",
                 "bench_log.json", "jobs.json"):
        try:
            os.remove(data_path(name))
        except OSError:
            pass


def factors(**kw):
    return {k: float(kw.get(k, 50.0)) for k in FACTORS}


def features(**kw):
    return {k: float(kw.get(k, 50.0)) for k in FEATURES}


def write_learning_pairs(pairs):
    """pairs: [(kept_factors, sib_factors)] in chronological order -> a v3 store."""
    events = []
    for i, (kept, sib) in enumerate(pairs):
        events.append({"kind": "keep", "t": 1_000_000 + i * 1000, "engine": "b2",
                       "score": 80, "factors": kept,
                       "sib": [{"score": 70, "factors": sib}]})
    write_json("learning.json", {"version": 3, "events": events})
    return len(events)


def write_scout_judgments(makes, passes):
    """One query, chronological, every row carrying the features measured then."""
    judgments = []
    for i, f in enumerate(makes):
        judgments.append({"t": 2_000_000 + i * 1000, "id": f"make{i}", "query": "bench niche",
                          "verdict": "make", "features": f, "vec": [f[k] for k in FEATURES]})
    for i, f in enumerate(passes):
        judgments.append({"t": 2_100_000 + i * 1000, "id": f"pass{i}", "query": "bench niche",
                          "verdict": "pass", "features": f, "vec": [f[k] for k in FEATURES]})
    write_json("scout.json", {"version": 1, "queries": [], "proposals": [],
                              "judgments": judgments, "calls": []})
    return len(judgments)


def write_model(name, names, weights):
    write_json(name, {"version": 1, "active": True, "day": "2026-01-01", "t": 0.0,
                      "weights": {k: float(weights.get(k, 0.0)) for k in names},
                      "scale": {k: 1.0 for k in names},
                      "holdout": 1.0, "holdout_n": 2, "note": "test model"})


def test_modes():
    CONFIG["lab"], CONFIG["bench_mode"] = True, "on"
    check("modes: the scoreboard is on by default", clipbench.enabled() is True)
    CONFIG["bench_mode"] = "off"
    check("modes: CB_CLIPBENCH=off removes it", clipbench.enabled() is False)
    res = clipbench.run(reason="off-test")
    check("modes: a run while off is refused with the reason",
          res["ran"] is False and "off" in res["reason"]
          and not os.path.isfile(data_path("bench.json")))
    CONFIG["bench_mode"] = "on"
    CONFIG["lab"] = False
    check("modes: CB_LAB=0 removes it too", clipbench.enabled() is False)
    CONFIG["lab"] = True


def test_empty_install():
    clear_stores()
    board = clipbench.run(reason="empty")
    check("empty: a board still runs, and says so", board["ran"] is True
          and board["version"] == 1 and board["day"])
    for fam in ("taste", "scout"):
        f = board["families"][fam]
        check(f"empty: the {fam} family reports insufficient, with real counts",
              f["status"] == "insufficient" and f["pairs"] == 0 and f["holdout_pairs"] == 0
              and "insufficient" in f["verdict"], f["verdict"])
        check(f"empty: the {fam} baseline row is available but invents no number",
              f["contenders"][f["baseline"]]["available"] is True
              and f["contenders"][f["baseline"]]["holdout"] is None)
        check(f"empty: the {fam} challenger has no row to score", 
              f["contenders"][f["challenger"]]["holdout"] is None)
    check("empty: the coin-flip reference is a number, not a scorer",
          board["families"]["taste"]["chance"] == 0.5)
    check("empty: the board is written where the card reads it",
          json.load(open(data_path("bench.json"), encoding="utf-8"))["version"] == 1)
    log = json.load(open(data_path("bench_log.json"), encoding="utf-8"))
    check("empty: one log line per run with the agreed keys",
          len(log) == 1 and set(log[0]) == {"day", "version", "reason", "taste", "scout",
                                            "verdicts"}, str(log[0])[:160])
    state = clipbench.state()
    check("state: it reports the last board and the run count",
          state["runs"] == 1 and state["last"]["version"] == 1
          and state["board"]["day"] == board["day"])
    check("state: it says what to do next", "run again" in state["next"])
    clipbench.reset()
    check("reset: it forgets the boards, not the models",
          clipbench.state()["board"] is None and clipbench.state()["runs"] == 0)


def test_missing_model_is_its_own_status():
    clear_stores()
    pairs = [(factors(hook=70, **{k: 44.0 for k in FACTORS if k != "hook"}),
              factors(hook=30, **{k: 54.0 for k in FACTORS if k != "hook"})) for _ in range(8)]
    write_learning_pairs(pairs)
    fam = clipbench.run(reason="no-model")["families"]["taste"]
    check("no-model: enough evidence without a trained model is its own status",
          fam["status"] == "no-model" and fam["pairs"] >= clipbench.MIN_PAIRS, fam["status"])
    check("no-model: the verdict names the missing model, not missing evidence",
          "no active model" in fam["verdict"], fam["verdict"])
    check("no-model: the baseline is still scored on the held-out pairs",
          fam["contenders"]["virality"]["holdout"]["pairs"] == fam["holdout_pairs"])


def test_taste_family_can_win_and_lose():
    clear_stores()
    # (a) the plain factor mean is wrong here; the model's hook weight fixes it
    pairs = [(factors(hook=70, **{k: 44.0 for k in FACTORS if k != "hook"}),
              factors(hook=30, **{k: 54.0 for k in FACTORS if k != "hook"})) for _ in range(8)]
    write_learning_pairs(pairs)
    write_model("model.json", FACTORS, {"hook": 1.0})
    fam = clipbench.run(reason="taste-win")["families"]["taste"]
    base = fam["contenders"]["virality"]["holdout"]
    held = fam["contenders"]["taste-model"]["holdout"]
    check("taste: the trained model is scored on the same held-out pairs",
          held["pairs"] == fam["holdout_pairs"], str(held))
    check("taste: a model that separates the choices beats the plain baseline",
          base["accuracy"] == 0.0 and held["accuracy"] == 1.0
          and fam["status"] == "scored" and "beats" in fam["verdict"], fam["verdict"])
    check("taste: every contender gets train AND holdout numbers",
          all(fam["contenders"][n]["train"] is not None for n in
              ("virality", "one-shot", "taste-model")))
    # (b) the same evidence with an inverted model: the board must say it lost
    write_model("model.json", FACTORS, {"hook": -1.0})
    pairs = [(factors(hook=70, **{k: 54.0 for k in FACTORS if k != "hook"}),
              factors(hook=30, **{k: 45.0 for k in FACTORS if k != "hook"})) for _ in range(8)]
    write_learning_pairs(pairs)
    fam = clipbench.run(reason="taste-lose")["families"]["taste"]
    check("taste: an inverted model is scored as beaten by the baseline",
          fam["contenders"]["virality"]["holdout"]["accuracy"] == 1.0
          and fam["contenders"]["taste-model"]["holdout"]["accuracy"] == 0.0
          and "does not beat" in fam["verdict"], fam["verdict"])
    check("taste: the one-shot stand-in is on the board too",
          fam["contenders"]["one-shot"]["holdout"] is not None)


def test_holdout_is_chronological():
    clear_stores()
    # the older four fifths reward the model, the newest fifth is inverted: a random
    # split would score well, the chronological one must score 1.00 train / 0.00 holdout
    old = (factors(hook=70, **{k: 44.0 for k in FACTORS if k != "hook"}),
           factors(hook=30, **{k: 54.0 for k in FACTORS if k != "hook"}))
    new = (factors(hook=30, **{k: 54.0 for k in FACTORS if k != "hook"}),
           factors(hook=70, **{k: 44.0 for k in FACTORS if k != "hook"}))
    pairs = [old] * 8 + [new] * 2
    write_learning_pairs(pairs)
    write_model("model.json", FACTORS, {"hook": 1.0})
    fam = clipbench.run(reason="leakage")["families"]["taste"]
    check("splits: the held-out slice is the newest fifth",
          fam["pairs"] == 10 and fam["holdout_pairs"] == 2
          and fam["train_pairs"] == 8, str(fam["pairs"]))
    check("splits: a model right only about the old choices scores 0.00 held out",
          fam["contenders"]["taste-model"]["train"]["accuracy"] == 1.0
          and fam["contenders"]["taste-model"]["holdout"]["accuracy"] == 0.0,
          str(fam["contenders"]["taste-model"])[:160])


def test_a_tie_is_not_a_win():
    clear_stores()
    same = factors(hook=60)
    write_learning_pairs([(same, dict(same)) for _ in range(8)])
    write_model("model.json", FACTORS, {"hook": 1.0})
    fam = clipbench.run(reason="ties")["families"]["taste"]
    row = fam["contenders"]["virality"]["holdout"]
    check("ties: a constant scorer scores 0.00, with the ties counted",
          row["accuracy"] == 0.0 and row["ties"] == row["pairs"], str(row))
    check("ties: the coin-flip reference is still reported as 0.50", fam["chance"] == 0.5)


def test_scout_family_can_win_and_lose():
    clear_stores()
    # (a) the measured mean is wrong here; the velocity weight fixes it
    makes = [features(velocity=70, **{k: 44.0 for k in FEATURES if k != "velocity"})
             for _ in range(5)]
    passes = [features(velocity=30, **{k: 54.0 for k in FEATURES if k != "velocity"})
              for _ in range(5)]
    write_scout_judgments(makes, passes)
    write_model("scout_model.json", FEATURES, {"velocity": 1.0})
    fam = clipbench.run(reason="scout-win")["families"]["scout"]
    check("scout: the measured mean is the baseline and the model rides on it",
          fam["contenders"]["measured"]["holdout"]["accuracy"] == 0.0
          and fam["contenders"]["scout-model"]["holdout"]["accuracy"] == 1.0
          and "beats" in fam["verdict"], fam["verdict"])
    check("scout: pairs come from the scout's own mining, both verdicts required",
          fam["pairs"] >= clipbench.MIN_PAIRS and fam["holdout_pairs"] >= 1
          and fam["evidence"]["judgments"] == 10, str(fam["pairs"]))
    # (b) baseline right, model wrong about the owner: the makes here are LOW velocity,
    # and a model that over-weights velocity pushes them down far enough to lose
    makes = [features(velocity=30, **{k: 60.0 for k in FEATURES if k != "velocity"})
             for _ in range(5)]
    passes = [features(velocity=70, **{k: 50.0 for k in FEATURES if k != "velocity"})
              for _ in range(5)]
    write_scout_judgments(makes, passes)
    write_model("scout_model.json", FEATURES, {"velocity": 1.0})
    fam = clipbench.run(reason="scout-lose")["families"]["scout"]
    check("scout: a model wrong about the owner does not beat the measured baseline",
          fam["contenders"]["measured"]["holdout"]["accuracy"] == 1.0
          and fam["contenders"]["scout-model"]["holdout"]["accuracy"] == 0.0
          and "does not beat" in fam["verdict"], fam["verdict"])


def test_api_and_health():
    import http.client
    import threading
    from clipblitz import server as studio_server

    clear_stores()
    pairs = [(factors(hook=70, **{k: 44.0 for k in FACTORS if k != "hook"}),
              factors(hook=30, **{k: 54.0 for k in FACTORS if k != "hook"})) for _ in range(8)]
    write_learning_pairs(pairs)
    write_model("model.json", FACTORS, {"hook": 1.0})
    httpd = studio_server.QuietServer(("127.0.0.1", 0), studio_server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        # The first health call measures the machine (and waits out every ffmpeg it
        # cannot find), so it can take tens of seconds on a cold, bare checkout. Warm it
        # once here: the checks below are about the payload, not about start-up latency.
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)

        def req(method, path, payload=None):
            body = json.dumps(payload).encode() if payload is not None else None
            headers = {"Content-Type": "application/json"} if body else {}
            conn.request(method, path, body=body, headers=headers)
            res = conn.getresponse()
            return res.status, json.loads(res.read() or b"{}")

        req("GET", "/api/health")
        status, res = req("GET", "/api/health")
        check("api: health carries the scoreboard only while it is on",
              status == 200 and res.get("clipbench") == {"enabled": True}, f"{status}")
        status, res = req("GET", "/api/clipbench")
        check("api: the read route answers before any board exists",
              status == 200 and res["enabled"] is True and res["board"] is None, f"{status}")
        status, res = req("POST", "/api/clipbench")
        check("api: the run route writes a board through the real handler",
              status == 200 and res["ran"] is True and res["families"]["taste"]["pairs"] == 8,
              f"{status} {str(res)[:120]}")
        status, res = req("GET", "/api/clipbench")
        check("api: the board is then readable, with its verdict",
              status == 200 and res["board"]["version"] == 1
              and res["board"]["families"]["taste"]["verdict"], f"{status}")
        status, res = req("GET", "/api/jobs")
        check("api: the routes next to it still work", status == 200, f"{status}")
        CONFIG["lab"] = False
        status, res = req("POST", "/api/clipbench")
        check("api: a run with the lab off is a 409, not a silent pass",
              status == 409 and "off" in res["error"], f"{status}")
        status, res = req("GET", "/api/health")
        check("api: with the lab off the health payload has no clipbench key",
              status == 200 and "clipbench" not in res, f"{status}")
        CONFIG["lab"] = True
    finally:
        httpd.shutdown()


def test_tool_and_cli():
    clear_stores()
    pairs = [(factors(hook=70, **{k: 44.0 for k in FACTORS if k != "hook"}),
              factors(hook=30, **{k: 54.0 for k in FACTORS if k != "hook"})) for _ in range(8)]
    write_learning_pairs(pairs)
    payload, is_err = agent.call_tool("clipbench", {})
    check("mcp: clipbench reads the board without running one",
          is_err is False and "board" in payload and "runs" in payload
          and os.path.isfile(data_path("bench.json")) is False)
    payload, is_err = agent.call_tool("clipbench", {"run": True})
    check("mcp: clipbench with run=true scores the stores",
          is_err is False and payload["ran"] is True
          and payload["families"]["taste"]["pairs"] == 8)
    tools = agent.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    check("mcp: the tool is declared alongside the other ten",
          len(tools) == 11 and "clipbench" in {t["name"] for t in tools})
    env = dict(os.environ)
    env.update({"CB_DATA": CONFIG["data_dir"], "PYTHONIOENCODING": "utf-8"})
    out = subprocess.run([sys.executable, os.path.join(STUDIO, "run.py"), "--bench"],
                         capture_output=True, text=True, env=env, timeout=180)
    try:
        payload = json.loads(out.stdout)
        ok = out.returncode == 0 and payload["ran"] is True and payload["families"]
    except ValueError:
        ok = False
    check("cli: 'run.py --bench' prints the board as JSON", ok, (out.stdout or out.stderr)[:160])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = agent.main(["tools"])
    check("cli: 'tools' still prints every schema as JSON",
          rc == 0 and len(json.loads(buf.getvalue())) == 11)


def main():
    test_modes()
    test_empty_install()
    test_missing_model_is_its_own_status()
    test_taste_family_can_win_and_lose()
    test_holdout_is_chronological()
    test_a_tie_is_not_a_win()
    test_scout_family_can_win_and_lose()
    test_api_and_health()
    test_tool_and_cli()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
