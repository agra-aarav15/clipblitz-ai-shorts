"""The daily cycle: it finds, it cuts, it asks — and it never judges for the owner.

The owner asked the studio to keep working while they are away, so this module is the
one part of ClipBlitz that acts on a timer instead of on a click. Its contract is
narrow on purpose, and every clause of it is enforced here rather than promised:

  * It SEARCHES through the scout's own metadata-only call. No new network path, no
    new provider, no key: the same bundled yt-dlp the Scout screen uses.
  * It CUTS at most `CB_DAILY_CUTS` of its own top-ranked picks per day (default 1),
    and only when the machine is actually render-capable. The import goes through the
    normal pipeline, so the rights layer applies exactly as it always does — under a
    strict gate the job is held before it renders and this module says so out loud.
  * It NEVER records a judgment. Scout verdicts stay null and the pair queue stays
    empty until the owner calls it. A fabricated label would poison the very model
    the owner is training, so the machine does not get a vote on its own taste — it
    only gets to put finished cuts in front of the owner and ask.
  * It NEVER publishes. `auto_post` is untouched; every post still needs the owner.
  * It REREADS every number from the store that owns it (scout, jobs, clipbench,
    trainer, learning) instead of keeping a second copy that could drift.

One cycle per local day, run by the server's scheduler thread on the first tick after
`CB_DAILY_HOUR`. A machine that was off for a week catches up on the next tick — the
day it was away is simply not a day it worked. `CB_DAILY=off` removes the whole layer.
"""

import json
import os
import time

from .config import CONFIG

MAX_PLAN = 12            # proposals kept in the day's plan
MAX_LOG = 200            # cycle lines kept in data/daily_log.json
TICK_SLACK = 1           # a tick may be delayed; only the day matters, not the minute


def enabled():
    """On by default, and absent the moment the lab layer goes off (CB_LAB=0)."""
    mode = str(CONFIG.get("daily_mode") or "on").strip().lower()
    if mode in ("0", "off", "false", "no"):
        return False
    return bool(CONFIG.get("lab", True))


def _path(name):
    return os.path.join(CONFIG["data_dir"], name)


def _read(path, default):
    try:
        data = json.load(open(path, encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write(path, data):
    try:
        os.makedirs(CONFIG["data_dir"], exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _store():
    """data/daily.json — the day's own record. Missing means it has not run yet."""
    return _read(_path("daily.json"),
                 {"version": 1, "day": "", "runs": 0, "today": None, "best": None})


def _save(data):
    _write(_path("daily.json"), data)


def _log():
    return _read(_path("daily_log.json"), [])


def _log_append(line):
    rows = _log()
    rows.append(line)
    _write(_path("daily_log.json"), rows[-MAX_LOG:])


def _today(now=None):
    return time.strftime("%Y-%m-%d", time.localtime(now or time.time()))


def _hour(now=None):
    return int(time.strftime("%H", time.localtime(now or time.time())))


def niches():
    """The niches the owner told the studio to watch. Config, never invented here."""
    return [n for n in (CONFIG.get("daily_niches") or []) if n][:6]


def due(now=None):
    """(is a cycle owed today, why not) — the whole scheduling rule, in one place."""
    if not enabled():
        return False, "the daily cycle is off (CB_DAILY=off or CB_LAB=0)"
    day = _today(now)
    if _store().get("day") == day:
        return False, "today's cycle already ran"
    if _hour(now) < int(CONFIG.get("daily_hour") or 0):
        return False, f"waiting for {int(CONFIG.get('daily_hour') or 0):02d}:00 local"
    return True, "due"


def _job_summary(j):
    """The one clip worth showing from a finished job, with its measured score."""
    clips = [c for c in (j.get("clips") or []) if isinstance(c, dict)]
    if not clips:
        return None
    best = max(clips, key=lambda c: (c.get("score") or 0))
    return {
        "job": j.get("id"), "file": best.get("file"), "score": best.get("score"),
        "engine": best.get("engine") or j.get("engine") or "",
        "title": best.get("title") or j.get("name") or "",
        "reason": best.get("reason") or "", "qc": best.get("qc") or "",
        "start": best.get("start"), "end": best.get("end"),
        "duration": best.get("duration"), "clip_index": clips.index(best),
        "clips": len(clips),
    }


def _daily_jobs():
    from . import pipeline
    out = []
    for j in pipeline.JOBS.values():
        src = j.get("source") or {}
        if src.get("via") == "daily":
            out.append(j)
    return sorted(out, key=lambda j: -(j.get("created") or 0))


def harvest():
    """Read the jobs this module started back out of the pipeline. Cheap, read-only,
    and safe to call on any tick: it records what finished and what is still running."""
    store = _store()
    jobs = _daily_jobs()
    day = _today()
    held = [j for j in jobs if j.get("rights_hold")]
    # a held import is not progress: it is waiting on the owner, not on the machine,
    # so it is reported as held and never counted as "still cutting"
    running = [j for j in jobs if j.get("status") in ("queued", "running", "posting")
               and not j.get("rights_hold")]
    best = None
    for j in jobs:
        # only work that finished TODAY may be called "today's pick"; a cut from
        # yesterday is yesterday's news, and saying otherwise would be a small lie
        if j.get("status") != "done" or _today(j.get("created")) != day:
            continue
        s = _job_summary(j)
        if s and (best is None or (s.get("score") or 0) > (best.get("score") or 0)):
            best = s
    today = store.get("today") or {}
    # recomputed on every harvest, never carried over: if nothing finished today there
    # is nothing to show, and a stale pick would be the one lie this card could tell
    if best:
        today["best"] = best
    else:
        today.pop("best", None)
    if running:
        today["still_cutting"] = [{"job": j.get("id"), "stage": j.get("stage"),
                                   "progress": j.get("progress"), "name": j.get("name")}
                                  for j in running[:3]]
    else:
        today.pop("still_cutting", None)
    if held:
        today["held"] = [{"job": j.get("id"), "name": j.get("name"),
                          "why": j.get("stage")} for j in held[:3]]
    else:
        today.pop("held", None)
    store["today"] = today
    if best and (store.get("best") or {}).get("file") != best.get("file"):
        store["best"] = best
    _save(store)
    return {"running": len(running), "held": len(held), "best": best}


def _pairs_waiting():
    """The owner's queue, straight from the module that owns it (never a copy)."""
    try:
        from . import pipeline, scout
        if not scout.enabled():
            return 0
        return len(scout.judgment_queue(list(pipeline.JOBS.values())))
    except Exception:
        return 0


def _search(query, limit):
    from . import scout
    return scout.search(query, limit)


def _start_cut(prop, engine, top_n, starter=None):
    """Import one proposal through the normal path — without a counterfeit judgment.

    The Scout screen calls scout.judge(..., "make") because a human pressed the button.
    Here nobody did, so the proposal keeps `verdict: None`: the cut is the machine's
    work, the verdict stays the owner's call.
    """
    from . import pipeline
    url = str(prop.get("url") or "")
    if not url.lower().startswith(("http://", "https://")):
        return None, "this proposal carries no URL to import"
    if starter is not None:
        return starter(prop), None
    jid = pipeline.new_job(prop.get("title") or prop.get("id") or url[:60],
                           top_n=top_n, engine=engine,
                           source={"kind": "youtube" if "youtube." in url else "url",
                                   "url": url,
                                   "uploader": prop.get("channel") or "",
                                   "title": prop.get("title") or "",
                                   "via": "daily"})
    pipeline.start_from_url(jid, url)
    return jid, None


def _render_capable():
    """The same hardware verdict the Studio screen shows. No guesses here either."""
    try:
        from . import hardware
        hw = hardware.profile()
        return bool(hw.get("render_capable")), hw.get("reason") or ""
    except Exception as e:
        return False, f"hardware check failed: {e}"


def run(reason="manual", queries=None, cuts=None, searcher=None, starter=None,
        now=None):
    """One cycle. Searches each niche, picks the day's plan, cuts at most `cuts` of it,
    then runs the board and the refit cadence. Returns the day's record as JSON.

    `searcher` and `starter` are injectable so the offline test suite never touches the
    network and never writes a job. Nothing here blocks on a render: the pipeline runs
    in its own thread and the next tick harvests it.
    """
    if not enabled():
        return {"enabled": False, "ran": False,
                "reason": "the daily cycle is off (CB_DAILY=off or CB_LAB=0)"}

    day, at = _today(now), round(time.time(), 1)
    qs = [q for q in (queries or niches()) if str(q).strip()][:6]
    searches, plan = [], []
    for q in qs:
        try:
            res = (searcher or _search)(q, int(CONFIG.get("daily_results") or 8))
        except Exception as e:
            searches.append({"q": q, "error": str(e)[:200]})
            continue
        if res.get("error"):
            searches.append({"q": q, "error": str(res["error"])[:200]})
            continue
        rows = res.get("proposals") or []
        searches.append({"q": q, "found": res.get("found"), "added": res.get("added"),
                         "method": res.get("method")})
        for p in rows:
            p = dict(p)
            p["query"] = q
            plan.append(p)
    plan.sort(key=lambda p: -(p.get("rank_score") or 0))
    plan = plan[:MAX_PLAN]

    try:
        cuts = int(CONFIG.get("daily_cuts") if cuts is None else cuts)
    except (TypeError, ValueError):
        cuts = 1
    cuts = max(0, min(3, cuts))

    capable, why = _render_capable()
    started = []
    if cuts and plan and capable:
        busy = [j for j in _daily_jobs() if j.get("status") in ("queued", "running")]
        if busy:
            started.append({"skipped": "the previous cut is still running",
                            "job": busy[0].get("id")})
        else:
            for prop in plan[:cuts]:
                try:
                    jid, err = (starter or _start_cut)(prop, CONFIG.get("engine_default", "b2"),
                                                       int(CONFIG.get("top_n") or 3))
                except Exception as e:
                    jid, err = None, str(e)[:200]
                if err:
                    started.append({"proposal": prop.get("id"), "error": err})
                    continue
                started.append({"proposal": prop.get("id"), "job": jid,
                                "title": prop.get("title") or "",
                                "url": prop.get("url") or "",
                                "score": prop.get("rank_score"),
                                "engine": CONFIG.get("engine_default", "b2")})
    elif cuts and plan and not capable:
        started.append({"skipped": "this machine cannot render right now",
                        "reason": why})
    elif not plan:
        started.append({"skipped": "the search came back with nothing to cut"})

    # the board and the refit cadence both reread the stores they own
    board = None
    try:
        from . import clipbench
        if clipbench.enabled():
            board = clipbench.run(reason="daily")
    except Exception as e:
        board = {"error": str(e)[:200]}
    for name in ("trainer", "scout"):
        try:
            mod = __import__(f"clipblitz.{name}", fromlist=["auto_fit"])
            mod.auto_fit()
        except Exception:
            pass

    today = {"day": day, "at": at, "reason": reason, "niches": qs,
             "searches": searches, "plan": plan,
             "started": started, "cuts_allowed": cuts, "render_capable": capable}
    store = _store()
    store["day"], store["today"] = day, today
    store["runs"] = int(store.get("runs") or 0) + 1
    _save(store)
    harvest()
    store = _store()
    best = (store.get("today") or {}).get("best")
    _log_append({"day": day, "at": at, "reason": reason,
                 "found": sum(s.get("found") or 0 for s in searches),
                 "errors": [s["q"] for s in searches if s.get("error")],
                 "started": [s.get("job") for s in started if s.get("job")],
                 "best": (best or {}).get("score"),
                 "pairs_waiting": _pairs_waiting(),
                 "board": {k: (v or {}).get("verdict")
                           for k, v in ((board or {}).get("families") or {}).items()}})
    out = dict(today)
    out.update({"enabled": True, "ran": True})
    return out


def tick(reason="cadence"):
    """The heartbeat the server runs. Harvests what finished, runs today's cycle once
    it is due, and writes one line when it does. Cheap when there is nothing to do."""
    if not enabled():
        return {"enabled": False, "ran": False}
    harvest()
    owed, why = due()
    if not owed:
        return {"enabled": True, "ran": False, "reason": why}
    out = run(reason=reason)
    out["reason"] = why
    return out


def state():
    """Everything the Today card shows, read from the stores that own each number."""
    store = _store()
    today = store.get("today") or {}
    harvest()
    store = _store()
    today = store.get("today") or {}
    # today's pick is today's, full stop. The all-time best is exposed separately and
    # labelled as what it is, so the card can never present an old cut as today's.
    best = today.get("best")
    pairs = _pairs_waiting()
    taste = scout_block = None
    verdicts = {}
    try:
        from . import trainer
        t = trainer.state()
        taste = {"active": t.get("active"), "events": t.get("events"),
                 "min_events": t.get("min_events"), "remaining": t.get("remaining"),
                 "waiting_for": t.get("waiting_for"), "holdout": t.get("holdout"),
                 "version": t.get("version")}
    except Exception:
        pass
    try:
        from . import scout
        s = scout.state()
        scout_block = {"active": s.get("active"), "judgments": s.get("judgments"),
                       "min_judgments": s.get("min_judgments"),
                       "remaining": s.get("remaining"),
                       "waiting_for": s.get("waiting_for")}
    except Exception:
        pass
    try:
        from . import clipbench
        b = clipbench.state()
        verdicts = {k: (v or {}).get("verdict")
                    for k, v in ((b.get("board") or {}).get("families") or {}).items()}
    except Exception:
        pass
    owed, why = due()

    if best:
        ask = (f"Today's best cut is clip {(best.get('clip_index') or 0) + 1} of job "
               f"{best.get('job')} — {best.get('engine')}, score {best.get('score')}. "
               f"{pairs} pair(s) are waiting for your call; the taste model needs "
               f"{(taste or {}).get('remaining') or 0} more real choices before it may "
               f"move anything.")
    elif today.get("held"):
        ask = ("Today's import is held by the clearance gate — answer the rights question "
               "on the Clips screen and it will render.")
    elif today.get("still_cutting"):
        ask = (f"Still cutting today's pick (job {today['still_cutting'][0].get('job')}, "
               f"{today['still_cutting'][0].get('progress')}%). Nothing to rate yet.")
    elif today.get("started"):
        ask = "Today's cycle ran but produced no clip to show. The log says why."
    else:
        ask = f"No cycle has run today yet ({why})."

    return {
        "enabled": enabled(),
        "day": _today(),
        "ran_today": store.get("day") == _today(),
        "due": owed,
        "due_reason": why,
        "hour": int(CONFIG.get("daily_hour") or 0),
        "tick_seconds": int(CONFIG.get("daily_tick") or 600),
        "cuts_allowed": int(CONFIG.get("daily_cuts") or 0),
        "niches": niches(),
        "runs": store.get("runs") or 0,
        "today": today,
        "best": best,
        "last_best": store.get("best"),
        "ask": ask,
        "pairs_waiting": pairs,
        "taste": taste,
        "scout_model": scout_block,
        "board": verdicts,
        "log": _log()[-5:],
        "note": ("This is the only part of the studio that acts on a timer. It selects, "
                 "cuts and asks; it never records a judgment and it never publishes — "
                 "those stay yours. CB_DAILY=off turns it off entirely."),
    }


def reset():
    """Forget the daily record. It does not touch the scout, the choices or the models
    those trained — this only clears the schedule's own memory."""
    for name in ("daily.json", "daily_log.json"):
        try:
            os.remove(_path(name))
        except OSError:
            pass
