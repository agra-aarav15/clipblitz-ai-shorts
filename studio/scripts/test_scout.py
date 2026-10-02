"""Scout tests for ClipBlitz Studio - stdlib only, offline, no ffmpeg, no network.

Run from the studio root:   python scripts/test_scout.py

What is proven:

  1. DISCOVERY IS METADATA ONLY. The fetch runs yt-dlp with --dump-json and a ytsearch
     query and nothing that touches media; a flat-search fallback exists for when the
     site will not serve per-video metadata; the offline suite substitutes that single
     network call and exercises everything downstream for real.
  2. FEATURES ARE MEASURED, NEVER IMPUTED. Six 0..100 features come from fields the
     source actually reported; a missing view count or publish date leaves velocity
     and reach as None, listed as unmeasured, and it never enters a fit.
  3. JUDGMENTS ARE EVIDENCE. make/pass calls are stored with the features measured at
     judgment time, pairs are mined within one search, and the scout model activates
     only when the newest fifth of the pairs says it ranks make above pass at 0.55 or
     better - and the fit core is the same deterministic one the taste model uses.
  4. THE JUDGMENT QUEUE IS REAL WORK. Only existing files are offered, only same-moment
     two-engine pairs qualify, and a pair that was judged is not offered twice. The
     judgment itself is logged through the learning store, so the taste model gets a
     genuine kept-versus-rejected pair.
  5. CB_SCOUT=off (and CB_LAB=0) remove the scout: no searches, no judgments, no model,
     no queue, no files.

Every store lives in a throwaway temp data dir, so this never touches real data.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_scout_")

from clipblitz import agent, learning, pipeline, scout  # noqa: E402

RESULTS = []

# never route an agent tool call at a live studio this suite does not own
agent.port_open = lambda *a, **k: False


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def row(i, views=10000, days_old=10, dur=1200, title="How to cook rice fast",
        channel="Chef X"):
    return {"id": f"vid{i}", "title": title, "channel": channel, "duration": dur,
            "view_count": views, "timestamp": time.time() - days_old * 86400,
            "webpage_url": f"https://www.youtube.com/watch?v=vid{i}"}


def fake_fetch(rows):
    def fetch(query, limit):
        return rows[:limit], "test metadata"
    return fetch


def write_jobs(channel="Chef X"):
    """A minimal jobs.json so channel history has something real to measure."""
    path = os.path.join(CONFIG["data_dir"], "jobs.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"id": "old1", "status": "done", "created": 1,
                    "source": {"kind": "youtube", "uploader": channel}}], f)


def test_modes():
    CONFIG["lab"], CONFIG["scout_mode"] = True, "on"
    check("scout: on by default", scout.enabled() is True)
    CONFIG["scout_mode"] = "off"
    check("scout: CB_SCOUT=off removes it", scout.enabled() is False)
    res = scout.search("anything", fetch=fake_fetch([row(1)]))
    check("scout: a search while off is refused with the reason",
          res["enabled"] is False and "off" in res["reason"]
          and not os.path.isfile(os.path.join(CONFIG["data_dir"], "scout.json")))
    CONFIG["scout_mode"] = "on"
    CONFIG["lab"] = False
    check("scout: CB_LAB=0 removes it too", scout.enabled() is False)
    CONFIG["lab"] = True


def test_parsing():
    p = scout._proposal({"id": "abc123", "title": "T", "channel": "C", "duration": 90,
                         "view_count": 500, "timestamp": 1700000000,
                         "webpage_url": "https://youtu.be/abc123"}, "q", 7)
    check("parse: a full metadata row becomes a stored proposal",
          p["id"] == "abc123" and p["duration"] == 90.0 and p["views"] == 500
          and p["published"] == 1700000000 and p["verdict"] is None)
    p2 = scout._proposal({"id": "abc123", "upload_date": "20240131", "duration": "60"},
                         "q", 7)
    check("parse: an upload_date string becomes a publish timestamp",
          p2["published"] and time.strftime("%Y-%m-%d", time.localtime(p2["published"]))
          == "2024-01-31")
    check("parse: a row without an id is not a proposal",
          scout._proposal({"title": "no id"}, "q", 1) is None)
    check("parse: a bare id gets a watch URL",
          scout._proposal({"id": "abcdefghijk"}, "q", 1)["url"].startswith("https://"))


def test_fetch_is_metadata_only():
    calls = []

    class FakeProc:
        def __init__(self, stdout):
            self.stdout, self.stderr, self.returncode = stdout, "", 0

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            return FakeProc("")            # first attempt finds nothing
        return FakeProc(json.dumps({"id": "x1", "title": "T"}) + "\n")

    saved = scout.subprocess.run
    scout.subprocess.run = fake_run
    try:
        rows, method = scout._fetch("a niche", 3)
    finally:
        scout.subprocess.run = saved
    first = " ".join(calls[0])
    check("fetch: it asks yt-dlp for JSON metadata, never media",
          "--dump-json" in first and "ytsearch3:a niche" in first
          and "--write-info-json" not in first and " -f " not in first
          and "--flat-playlist" not in first, first)
    check("fetch: a flat-search fallback exists and is labelled honestly",
          "--flat-playlist" in " ".join(calls[1]) and method == "flat metadata"
          and len(rows) == 1)


def test_features_are_measured():
    write_jobs("Chef X")
    now = time.time()
    hist = scout.channel_history()
    strong = {"views": 1_000_000, "published": now - 2 * 86400, "duration": 1200,
              "title": "How did this 3-ingredient dish go wrong?", "channel": "Chef X"}
    weak = {"views": 10, "published": now - 3000 * 86400, "duration": 5,
            "title": "plain words", "channel": "Unknown Channel"}
    fs, fw = scout.features(strong, hist), scout.features(weak, hist)
    check("features: every one is a measured 0..100 number",
          all(isinstance(fs[k], (int, float)) and 0 <= fs[k] <= 100
              for k in scout.FEATURES), str(fs))
    check("features: the fast fresh long clip-ready video beats the dead one",
          scout.measured_score(fs) > scout.measured_score(fw))
    check("features: channel history comes from real jobs, not vibes",
          fs["channel_fit"] == 100.0 and fw["channel_fit"] == 0.0)
    blind = scout.features({"views": None, "published": None, "duration": 1200,
                            "title": "plain", "channel": ""}, hist)
    check("features: unreported views/publish dates stay None, never imputed",
          blind["velocity"] is None and blind["reach"] is None
          and blind["freshness"] is None and blind["duration_fit"] is not None)
    vals = [v for v in blind.values() if isinstance(v, (int, float))]
    check("features: a missing field is excluded from the score",
          scout.measured_score(blind) == round(sum(vals) / len(vals), 1)
          and len(vals) == 3, f"{len(vals)} measured")
    check("features: a partial vector cannot train or adjust anything",
          scout._vec(blind) is None and scout.model_adjust(None) == 0.0)


def test_rank_and_search():
    rows = [row(1, views=2000, days_old=3), row(2, views=5_000_000, days_old=1),
            row(3, views=500, days_old=400)]
    res = scout.search("chef shorts", 3, fetch=fake_fetch(rows))
    check("search: it stores the proposals and reports what it found",
          res["enabled"] and res["found"] == 3 and res["added"] == 3
          and res["stored"] == 3 and res["method"] == "test metadata")
    check("search: the queue is ranked by measured score, deterministically",
          [p["id"] for p in res["proposals"]] == [p["id"] for p in scout.rank(res["proposals"])])
    check("search: every row carries its feature breakdown and why-lines",
          all(len(p["reasons"]) >= 2 and len(p["features"]) == 6
              for p in res["proposals"]))
    again = scout.search("chef shorts", 3, fetch=fake_fetch(rows))
    check("search: a repeat search adds nothing twice", again["added"] == 0
          and again["stored"] == 3)
    trend = again["trend"]
    check("trend: medians and freshness come from the rows",
          trend["results"] == 3 and trend["median_views"] == 2000
          and trend["fresh_share"] > 0 and "note" in trend)
    bad = scout.search("chef shorts", 3,
                       fetch=lambda q, n: (_ for _ in ()).throw(RuntimeError("site refused")))
    check("search: a refused search is reported, not guessed around",
          bad.get("error", "").startswith("site refused") and "proposals" not in bad)
    check("search: an empty query is a clean error",
          scout.search("   ", fetch=fake_fetch(rows)).get("error"))


def test_judgments_and_pairs():
    data = scout._store()
    pid = data["proposals"][0]["id"]
    check("judge: a made-up verdict is refused",
          scout.judge(pid, "maybe").get("error") == "verdict must be 'make' or 'pass'")
    check("judge: an unknown proposal is refused",
          scout.judge("nope", "make").get("error") == "unknown proposal")
    res = scout.judge(pid, "make")
    check("judge: a real call is stored with the features measured then",
          res["verdict"] == "make" and res["judgments"] == 1
          and scout._store()["judgments"][0]["vec"] is not None)
    check("judge: the proposal carries its verdict back to the queue",
          any(p["id"] == pid and p["verdict"] == "make"
              for p in scout.queue()["proposals"]))
    check("cadence: one judgment is not a model",
          res["fit"] is None and scout.state()["active"] is False
          and scout.state()["remaining"] == scout.MIN_JUDGMENTS - 1)
    scout.search("only makes", 2, fetch=fake_fetch([row(9, views=100), row(10, views=200)]))
    for p in scout.queue()["proposals"]:
        scout.judge(p["id"], "make")
    check("pairs: a search with only makes contributes nothing to fit",
          scout._pairs(scout._store()["judgments"]) == []
          and scout.fit()["attempted"] is False)


def test_model_gate():
    scout.reset()                       # a self-contained store for the gate's own story
    model_path = os.path.join(CONFIG["data_dir"], "scout_model.json")
    # a clean signal: four makes that measure high, four passes that measure low
    makes = [row(f"m{i}", views=1_000_000, days_old=2, dur=1200,
                 title="How did this 3-ingredient dish go wrong?") for i in range(4)]
    passes = [row(f"p{i}", views=3, days_old=2000, dur=4, title="plain words",
                  channel="Unknown Channel") for i in range(4)]
    scout.search("gate test", 8, fetch=fake_fetch(makes + passes))
    judged = [p for p in scout.queue()["proposals"]
              if p["id"].startswith(("vidm", "vidp"))]
    fit_out = None
    for p in judged:
        out = scout.judge(p["id"], "make" if p["id"].startswith("vidm") else "pass")
        if out.get("fit"):
            fit_out = out["fit"]
    check("gate: eight real calls produce a first fit", fit_out is not None
          and fit_out["attempted"] is True and fit_out["version"] == 1)
    check("gate: the clean signal activates the scout model",
          fit_out["activated"] is True and fit_out["holdout"] >= 0.55
          and fit_out["holdout_n"] >= 1, str(fit_out)[:160])
    check("gate: the active model is written and readable", os.path.isfile(model_path))
    state = scout.state()
    check("state: it reports the real version, holdout and cadence",
          state["active"] is True and state["version"] == 1
          and state["holdout"] >= 0.55 and state["judgments"] == 8
          and state["remaining"] == scout.REFIT_EVERY
          and len(state["fits"]) == 1, str(state)[:200])
    fits = scout._fits()
    check("log: exactly one line per attempt with the agreed keys",
          len(fits) == 1 and set(fits[0]) == {"day", "version", "judgments", "pairs",
                                              "holdout", "holdout_n", "activated",
                                              "reason"}
          and fits[0]["activated"] is True, str(fits[0])[:160])

    # the next four calls are INVERTED against everything learned before them: weak
    # makes and strong passes, so the newest fifth cannot be separated and must be
    # rejected on the held-out rate itself
    inverted = [row("x0", views=3, days_old=2000, dur=4, title="plain words",
                    channel="Unknown Channel"),
                row("x1", views=4, days_old=1900, dur=5, title="still plain",
                    channel="Unknown Channel"),
                row("x2", views=1_000_000, days_old=2, dur=1200,
                    title="How did this dish go wrong?"),
                row("x3", views=900_000, days_old=3, dur=1150,
                    title="Why did this dish fail?")]
    scout.search("gate inverted", 4, fetch=fake_fetch(inverted))
    byte_before = open(model_path, "rb").read()
    rejected = None
    for p in scout.queue()["proposals"]:
        if p["id"].startswith("vidx"):
            out = scout.judge(p["id"], "make" if p["id"].endswith(("0", "1")) else "pass")
            if out.get("fit"):
                rejected = out["fit"]
    check("gate: a candidate that cannot separate the calls is rejected",
          rejected is not None and rejected["activated"] is False
          and "below" in rejected["reason"], str(rejected)[:140])
    check("gate: a rejection leaves the active model byte-for-byte intact",
          open(model_path, "rb").read() == byte_before)
    check("gate: the rejection is still one honest log line",
          len(scout._fits()) == 2 and scout._fits()[-1]["activated"] is False
          and scout._fits()[-1]["version"] == 2)
    check("gate: the gate's own words are about make versus pass",
          "make-beats-pass" in scout._decide(0.6, None, 5)[1]
          and "below" in scout._decide(0.5, None, 5)[1]
          and scout._decide(0.6, None, 0)[0] is False)


def test_judgment_queue():
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    os.makedirs(clips_dir, exist_ok=True)

    def clip(name, engine, moment, start=10.0, end=40.0):
        with open(os.path.join(clips_dir, name), "wb") as f:
            f.write(b"x" * 64)
        return {"file": f"/clips/{name}", "engine_id": engine,
                "engine": "ProX v5" if engine == "prox" else "B2 Pro X",
                "moment": moment, "title": "A cut", "score": 80, "start": start,
                "end": end, "duration": end - start, "factors": {"hook": 50}}

    jobs = [
        {"id": "both1", "name": "episode.mp4", "created": 10, "clips": [
            clip("b1_1.mp4", "prox", 1), clip("b1_2.mp4", "b2", 1)]},
        {"id": "single1", "name": "other.mp4", "created": 20, "clips": [
            clip("s1_1.mp4", "b2", 1), clip("s1_2.mp4", "b2", 2)]},
        {"id": "gone1", "name": "gone.mp4", "created": 30, "clips": [
            {"file": "/clips/missing_a.mp4", "engine_id": "prox", "moment": 1},
            {"file": "/clips/missing_b.mp4", "engine_id": "b2", "moment": 1}]},
    ]
    pairs = scout.judgment_queue(jobs)
    check("queue: only a same-moment two-engine pair with real files qualifies",
          len(pairs) == 1 and pairs[0]["job"] == "both1"
          and {pairs[0]["a"]["engine"], pairs[0]["b"]["engine"]} == {"prox", "b2"})
    check("queue: the pair carries what a judgment needs",
          pairs[0]["a"]["index"] != pairs[0]["b"]["index"]
          and pairs[0]["a"]["factors"] and "kept-versus-rejected" in pairs[0]["why"])
    scout.record_call("both1", 1, 0, 1)
    check("queue: a pair that was judged is not offered twice",
          scout.judgment_queue(jobs) == [])


def test_lab_off():
    CONFIG["lab"] = False
    check("off: search refuses without touching the store",
          scout.search("x", fetch=fake_fetch([row(1)]))["enabled"] is False)
    check("off: judging refuses", scout.judge("vid1", "make")["enabled"] is False)
    check("off: no fit", scout.fit()["enabled"] is False)
    check("off: the queue reports itself off",
          scout.queue()["enabled"] is False and scout.judgment_queue([]) == [])
    CONFIG["lab"] = True


def test_api():
    import http.client
    import threading
    from clipblitz import server as studio_server

    saved_fetch, scout._fetch = scout._fetch, fake_fetch([row(31, views=900_000)])
    saved_start, pipeline.start_from_url = pipeline.start_from_url, \
        lambda jid, url: (pipeline.JOBS[jid].update(status="queued", stage="importing"),
                          jid)[1]
    write_jobs("Chef X")
    httpd = studio_server.QuietServer(("127.0.0.1", 0), studio_server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)

        def req(method, path, payload=None):
            body = json.dumps(payload).encode() if payload is not None else None
            headers = {"Content-Type": "application/json"} if body else {}
            conn.request(method, path, body=body, headers=headers)
            res = conn.getresponse()
            return res.status, json.loads(res.read() or b"{}")

        status, res = req("POST", "/api/scout/search", {"query": "api niche", "limit": 3})
        check("api: a search runs through the real route and stores proposals",
              status == 200 and res["added"] == 1 and res["proposals"], f"{status}")
        pid = res["proposals"][0]["id"]
        status, res = req("GET", "/api/scout")
        check("api: the queue read carries proposals, trend, model and clip pairs",
              status == 200 and res["proposals"] and res["trend"]
              and "model" in res and "pairs" in res and "clip_model" in res, f"{status}")
        status, res = req("POST", "/api/scout/judge", {"proposal": pid, "verdict": "nope"})
        check("api: an invented verdict is a 400", status == 400, f"{status}")
        status, res = req("POST", "/api/scout/judge", {"proposal": pid, "verdict": "pass"})
        check("api: a real call is recorded", status == 200 and res["verdict"] == "pass")
        status, res = req("POST", "/api/scout/make", {"proposal": "nope"})
        check("api: making an unknown proposal is a clean 404", status == 404)
        status, res = req("POST", "/api/scout/make", {"proposal": pid, "top_n": 2})
        check("api: make judges the proposal and imports through the normal path",
              status == 200 and res["job_id"] and res["verdict"] == "make"
              and pipeline.JOBS[res["job_id"]]["status"] == "queued", f"{status}")
        check("api: the make imported the proposal's own URL",
              pipeline.JOBS[res["job_id"]]["source"]["url"] ==
              scout.proposal(pid)["url"])
    finally:
        scout._fetch = saved_fetch
        pipeline.start_from_url = saved_start
        httpd.shutdown()
        httpd.server_close()


def test_tool_and_cli():
    saved_fetch, scout._fetch = scout._fetch, fake_fetch([row(41, views=4000)])
    try:
        payload, is_err = agent.call_tool("scout_search", {"query": "tool niche"})
        check("mcp: scout_search returns ranked metadata through the shared module",
              is_err is False and payload["found"] == 1 and payload["proposals"])
        payload, is_err = agent.call_tool("scout_search", {})
        check("mcp: scout_search without a query is a tool error",
              is_err is True and "query is required" in payload["error"])
        payload, is_err = agent.call_tool("scout_queue", {})
        check("mcp: scout_queue returns the queue and the model state",
              is_err is False and "proposals" in payload and "model" in payload)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = agent.main(["scout", "cli niche", "--limit", "1", "--json"])
        out = json.loads(buf.getvalue())
        check("cli: 'scout' prints the ranked result as JSON",
              rc == 0 and out["found"] == 1 and out["proposals"])
    finally:
        scout._fetch = saved_fetch


def main():
    test_modes()
    test_parsing()
    test_fetch_is_metadata_only()
    test_features_are_measured()
    test_rank_and_search()
    test_judgments_and_pairs()
    test_model_gate()
    test_judgment_queue()
    test_lab_off()
    test_api()
    test_tool_and_cli()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
