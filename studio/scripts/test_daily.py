"""Daily-cycle tests for ClipBlitz Studio - stdlib only, offline, no ffmpeg, no network.

Run from the studio root:   python scripts/test_daily.py

What is proven:

  1. IT NEVER JUDGES FOR THE OWNER. A cycle searches and cuts, and afterwards the scout
     store still holds zero verdicts. The machine gets no vote on its own taste; the
     only thing a cycle produces is finished work for the owner to call.
  2. IT CUTS AT MOST WHAT THE CONFIG ALLOWS, and nothing at all on a machine that
     cannot render, or when the previous cut is still running - each with a written
     reason instead of a silent skip.
  3. ONE CYCLE PER LOCAL DAY, at or after CB_DAILY_HOUR, and a machine that was off for
     a week simply works on the next tick. tick() is a no-op when nothing is owed.
  4. IT REREADS, IT DOES NOT INVENT. Today's pick is harvested back out of the pipeline
     job that actually finished; a running job is reported as running; a job held by
     the clearance gate is reported as held. No second copy of the truth.
  5. IT NEVER PUBLISHES. auto_post is never set by this module.
  6. THE OWNER'S NOTE IS KEPT AND QUOTED BACK. A judgement can carry the owner's own
     words about what was wrong; the note is stored (whitespace collapsed, capped),
     deduplicated newest-first, and appended to the QC judge prompt - while an empty
     store leaves the shipped prompt byte for byte identical.
  7. CB_DAILY=off removes the whole layer: no search, no cut, no writes.

Every store lives in a throwaway temp data dir, so this never touches real data.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_daily_")

from clipblitz import daily, learning, pipeline, scout, virality  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def proposal(i, score=None, query="test niche"):
    p = {"id": f"vid{i}", "url": f"https://www.youtube.com/watch?v=vid{i}",
         "title": f"Video {i}", "channel": "Chan", "query": query,
         "rank_score": score, "score": score, "features": {}, "reasons": []}
    return p


def fake_search(rows):
    def search(query, limit=10):
        got = [dict(p, query=query) for p in rows[:limit]]
        return {"enabled": True, "query": query, "method": "test metadata",
                "found": len(got), "added": len(got), "stored": len(got),
                "proposals": got, "trend": None}
    return search


def fresh(day_when="2026-10-02"):
    """A clean schedule that has already run on `day_when`."""
    daily.reset()
    store = daily._store()
    store.update({"day": day_when, "runs": 1, "today": {"day": day_when}})
    daily._save(store)
    return store


def make_job(job_id, status, clips, via="daily", source_extra=None):
    src = {"kind": "youtube", "url": "https://youtu.be/x"}
    src.update(source_extra or {})
    if via:
        src["via"] = via
    job = {"id": job_id, "name": f"{job_id}.mp4", "status": status, "stage": status,
           "progress": 100, "created": time.time(), "clips": clips, "candidates": [],
           "segments": [], "source": src, "engine": "B2 Pro X", "engine_id": "b2"}
    pipeline.JOBS[job_id] = job
    return job


def clip(i, score):
    return {"file": f"/clips/{i}.mp4", "score": score, "title": f"Clip {i}",
            "engine": "B2 Pro X", "engine_id": "b2", "start": 10.0, "end": 40.0,
            "duration": 30.0, "reason": "payoff on the laugh", "qc": "verified",
            "factors": {"hook": 70, "story": 80, "payoff": 80, "energy": 60,
                        "pacing": 90, "laughter": 40}}


print("=== 1. one cycle: it searches, it cuts once, it never judges ===")

CONFIG["daily_hour"] = 0
CONFIG["daily_cuts"] = 1
CONFIG["daily_niches"] = ["gaming fails"]
CONFIG["daily_results"] = 6

for jid in list(pipeline.JOBS):
    pipeline.JOBS.pop(jid, None)
fresh("2026-09-30")                    # last run two days ago
started_jobs = []


def starter(prop, engine, top_n):
    jid = f"job{len(started_jobs) + 1:02d}"
    started_jobs.append((jid, prop["id"], engine, top_n))
    make_job(jid, "running", [])       # a real pipeline would be cutting now
    return jid, None


rows = [proposal(i, score=90 - i * 5) for i in range(4)]
out = daily.run(reason="test", searcher=fake_search(rows), starter=starter)

check("the cycle ran", out.get("ran") is True)
check("it searched the configured niche", [s.get("q") for s in out["searches"]] == ["gaming fails"])
check("the plan is ranked, best first", [p["id"] for p in out["plan"]] == ["vid0", "vid1", "vid2", "vid3"])
check("it started exactly ONE cut (CB_DAILY_CUTS=1)", len(started_jobs) == 1,
      f"{[s[1] for s in started_jobs]}")
check("it cut its own top-ranked pick", started_jobs and started_jobs[0][1] == "vid0")
check("the started cut is recorded with its job id", out["started"][0].get("job") == "job01")
check("it never recorded a scout judgment", len(scout._store()["judgments"]) == 0,
      f"{len(scout._store()['judgments'])} verdict(s)")
check("the proposal it cut still has no verdict",
      all(p.get("verdict") is None for p in scout._store()["proposals"]))
check("no choice was logged as if a human made it", learning.events() == [])
check("it never turned auto_post on", not any(j.get("auto_post") for j in pipeline.JOBS.values()))
check("one line was written to the daily log", len(daily._log()) == 1)

print("\n=== 2. one cycle per local day, and a machine that was off catches up ===")

_owed, why = daily.due()
check("today is no longer owed", _owed is False, why)
again = daily.tick(reason="test")
check("tick() is a no-op once the day is done", again.get("ran") is False, again.get("reason"))

CONFIG["daily_hour"] = 23
fresh("2026-09-30")
owed, why = daily.due(now=time.mktime((2026, 10, 2, 10, 0, 0, 0, 0, -1)))
check("before the hour it is not owed", owed is False, why)
check("and it says which hour it waits for", "23:00" in why, why)
owed, _ = daily.due(now=time.mktime((2026, 10, 2, 23, 30, 0, 0, 0, -1)))
check("at the hour, a day that has not run is owed", owed is True)
CONFIG["daily_hour"] = 0

print("\n=== 3. it cuts nothing it is not allowed to cut ===")

fresh("2026-09-30")
CONFIG["daily_cuts"] = 0
started_jobs.clear()
out = daily.run(reason="test", searcher=fake_search(rows), starter=starter)
check("CB_DAILY_CUTS=0 starts nothing", started_jobs == [])
check("...and still searches", len(out["plan"]) == 4)

fresh("2026-09-30")
CONFIG["daily_cuts"] = 1
started_jobs.clear()
daily._render_capable = lambda: (False, "not enough cores")
out = daily.run(reason="test", searcher=fake_search(rows), starter=starter)
check("a machine that cannot render starts nothing", started_jobs == [])
check("...and says why", out["started"][0].get("reason") == "not enough cores",
      json.dumps(out["started"][0])[:80])
daily._render_capable = lambda: (True, "ready")

fresh("2026-09-30")
pipeline.JOBS["busy"] = {"id": "busy", "status": "running", "created": time.time(),
                         "clips": [], "source": {"via": "daily"}}
started_jobs.clear()
out = daily.run(reason="test", searcher=fake_search(rows), starter=starter)
check("a cut already running blocks a second one", started_jobs == [])
check("...with the reason written down", "still running" in json.dumps(out["started"]))
pipeline.JOBS.pop("busy", None)

fresh("2026-09-30")
started_jobs.clear()
out = daily.run(reason="test", searcher=fake_search([]), starter=starter)
check("an empty search starts nothing", started_jobs == [])
check("...and says the search came back empty",
      "nothing to cut" in json.dumps(out["started"]))

print("\n=== 4. today's pick is harvested back out of the real job ===")

for jid in list(pipeline.JOBS):
    pipeline.JOBS.pop(jid, None)
fresh("2026-10-02")
make_job("aaa11111", "done", [clip(1, 61), clip(2, 88), clip(3, 70)])
make_job("bbb22222", "running", [])
make_job("ccc33333", "done", [clip(1, 40)])
make_job("other999", "done", [clip(1, 99)], via=None)      # not this module's job
h = daily.harvest()
check("the best finished cut is picked by score", h["best"]["score"] == 88, json.dumps(h["best"])[:90])
check("...and it is the clip index that actually scored 88", h["best"]["clip_index"] == 1)
check("harvest counts what is still cutting", h["running"] == 1, str(h["running"]))
check("a running job is reported as still cutting",
      len(daily.state()["today"].get("still_cutting") or []) == 1,
      json.dumps(daily.state()["today"].get("still_cutting"))[:90])
check("a job this module did not start is ignored", h["best"]["job"] != "other999")

st = daily.state()
check("state() exposes today's pick as best", st["best"]["score"] == 88)
check("state() carries the ask in plain language", "job aaa11111" in st["ask"], st["ask"][:90])
check("state() reports the pairs waiting", isinstance(st["pairs_waiting"], int))
check("state() carries the taste model's real counts", st["taste"] is not None)
check("state() carries the board's verdicts", isinstance(st["board"], dict))
check("state() tells the truth about never judging",
      "never records a judgment" in st["note"])

print("\n=== 5. a held import is reported, not hidden ===")

for jid in ("aaa11111", "ccc33333", "bbb22222"):   # nothing finished today now
    pipeline.JOBS.pop(jid, None)
yesterday = make_job("yest5555", "done", [clip(1, 97)])
yesterday["created"] = time.time() - 86400
daily.harvest()
st = daily.state()
check("a cut that finished yesterday is NOT today's pick", st["best"] is None,
      json.dumps(st["best"])[:80])
check("...the all-time best is reported separately and labelled",
      (st["last_best"] or {}).get("score") == 88, json.dumps(st["last_best"])[:80])

make_job("held4444", "queued", [], source_extra={"via": "daily"})
pipeline.JOBS["held4444"]["rights_hold"] = True
pipeline.JOBS["held4444"]["stage"] = "held: answer the rights question"
h = daily.harvest()
check("a held import is counted", h["held"] == 1, str(h["held"]))
check("a held import appears in today's record",
      len(daily.state()["today"].get("held") or []) == 1,
      json.dumps(daily.state()["today"].get("held"))[:90])
st = daily.state()
check("...and the ask says it is held", "clearance gate" in st["ask"] or "rights" in st["ask"],
      st["ask"][:110])

print("\n=== 6. the owner's note is kept, and it reaches the judge prompt ===")

check("no notes on a fresh store", learning.owner_notes() == [])
check("an empty store leaves the judge prompt untouched", virality._owner_guidance() == "")
base = virality.JUDGE_PROMPT.format(clips='[{"index":0}]')
check("...byte for byte", base + virality._owner_guidance() == base)

ev = learning.log("judge", clip(1, 55), {"engine_id": "b2", "source": {}},
                  other=clip(2, 60), note="   ends mid-sentence,   the laugh is cut off  ")
check("the note is stored on the choice", ev.get("note") == "ends mid-sentence, the laugh is cut off",
      repr(ev.get("note")))
check("whitespace is collapsed, the words are not", "\n" not in (ev.get("note") or ""))
learning.log("judge", clip(1, 50), {"engine_id": "b2", "source": {}},
             note="ends mid-sentence, the laugh is cut off")
check("a repeated complaint is not duplicated", len(learning.owner_notes()) == 1,
      json.dumps(learning.owner_notes()))
learning.log("judge", clip(1, 50), {"engine_id": "b2", "source": {}}, note="starts on filler")
check("newest complaint comes first", learning.owner_notes()[0] == "starts on filler")
check("a choice with no note stays clean", "note" not in learning.log(
    "render", clip(1, 50), {"engine_id": "b2", "source": {}}))
long_note = learning.log("judge", clip(1, 50), {"engine_id": "b2", "source": {}},
                         note="x" * 900)
check("a note can never be unbounded", len(long_note["note"]) == learning.NOTE_MAX,
      str(len(long_note["note"])))

g = virality._owner_guidance()
check("both complaints are quoted back", "starts on filler" in g and "laugh is cut off" in g)
check("...as an instruction, not a suggestion", "STANDING COMPLAINTS" in g and "outrank" in g)
check("...and the shipped prompt is still the prefix", g.startswith("\n\nSTANDING COMPLAINTS"))
check("the /api/learning payload carries the notes", learning.profile()["notes"]["count"] == 4,
      str(learning.profile()["notes"]["count"]))
check("...with what they are used for", "QC judge" in learning.profile()["notes"]["feeds"])

print("\n=== 7. CB_DAILY=off removes the whole layer ===")

before = daily._log()
CONFIG["daily_mode"] = "off"
check("the layer reports itself off", daily.enabled() is False)
check("it refuses to run", daily.run(reason="test").get("ran") is False)
check("nothing is owed", daily.due()[0] is False)
check("tick() does nothing", daily.tick().get("ran") is False)
check("state() still answers honestly", daily.state()["enabled"] is False)
check("and it wrote nothing", daily._log() == before)
check("the health block would carry no daily key", not daily.enabled())
CONFIG["daily_mode"] = "on"

print("\n=== 8. reset() forgets the schedule, not the owner's evidence ===")

notes_before = len(learning.owner_notes())
daily._write(daily._path("daily.json"), {"version": 1, "day": "x", "runs": 9})
daily.reset()
check("the daily record is gone", daily._store().get("runs") in (0, None),
      str(daily._store().get("runs")))
check("the owner's notes survive a schedule reset", len(learning.owner_notes()) == notes_before)
check("so do the choices they came from", len(learning.events()) > 0)

print("\n=== 9. the pick is downloaded as a video, never as its metadata sidecar ===")

from clipblitz import ingest  # noqa: E402

# the exact shape that killed a real job: yt-dlp writes both files, and .info.json
# sorts before .mp4 alphabetically, so name order picked the metadata
base = "yt_2rwZdzy-1FY_1790941289_Is This Coded (Game Fails #528)"
hits = [f"{base}.info.json", f"{base}.mp4"]
check("the video is chosen, not the .info.json sidecar",
      ingest._pick_downloaded(hits) == f"{base}.mp4",
      str(ingest._pick_downloaded(hits)).split("_")[-1])
check("a metadata-only download is refused rather than rendered",
      ingest._pick_downloaded([f"{base}.info.json"]) is None)
check("a half-finished download is never used",
      ingest._pick_downloaded([f"{base}.mp4.part", f"{base}.mp4.ytdl"]) is None)
check("a thumbnail next to the media does not win either",
      ingest._pick_downloaded([f"{base}.webp", f"{base}.mkv"]).endswith(".mkv"))
check("every media extension this studio accepts is recognised",
      all(ingest._pick_downloaded([f"x{e}"]) == f"x{e}" for e in ingest.MEDIA_EXTS))

passed = sum(1 for _n, ok, _d in RESULTS if ok)
failed = len(RESULTS) - passed
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
