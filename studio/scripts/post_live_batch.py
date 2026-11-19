#!/usr/bin/env python3
"""Post the saved live clips that YouTube's daily upload limit blocked.

Run this once after YouTube resets its account limit (about midnight Pacific).
It deliberately does NOT try to evade the limit: the first uploadLimitExceeded
response stops the batch. Nothing is uploaded twice.

Usage:
    python scripts/post_live_batch.py --max 3
    python scripts/post_live_batch.py --max 3 --dry-run
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:4300"
CLIPS = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                     "ClipBlitz Studio", "clips")


def api(path, body=None, timeout=240):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:600]}
    except Exception as e:
        return {"error": str(e)[:300]}


def is_blocked(post):
    y = (post or {}).get("youtube") or {}
    return (not y.get("link")) and y.get("status") in (
        "platform_daily_limit", "daily_limit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", default="",
                    help="Only clips modified after this local time (HH:MM, default 09:30 today)")
    args = ap.parse_args()

    sessions = api("/api/live")
    if isinstance(sessions, dict) and sessions.get("error"):
        print("ClipBlitz is not running:", sessions["error"])
        return 2
    order = {"qSyo5d-dVzA": 0, "zf0rONfLFQw": 1, "VZqAPdUvqnQ": 2,
             "DOy7faJ4REg": 3, "h3qEwM6k074": 4}
    today = datetime.date.today()
    if args.since:
        hh, mm = (int(x) for x in args.since.split(":", 1))
        since = datetime.datetime.combine(today, datetime.time(hh, mm)).timestamp()
    else:
        since = datetime.datetime.combine(today, datetime.time(9, 30)).timestamp()
    candidates = []
    for s in sessions:
        if not s.get("rights_ok"):
            continue
        for c in s.get("clips") or []:
            if not is_blocked(c.get("post")):
                continue
            path = os.path.join(CLIPS, os.path.basename(c.get("file") or ""))
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime < since:
                continue
            candidates.append((mtime, s["id"], c.get("file") or "",
                               c.get("title") or ""))
    candidates.sort(key=lambda row: row[0], reverse=True)
    print("candidates:")
    for row in candidates:
        print(" ", datetime.datetime.fromtimestamp(row[0]).strftime("%H:%M"),
              row[1], row[2], row[3][:80])
    if args.dry_run:
        return 0

    posted = 0
    for _mtime, sid, filename, title in candidates:
        if posted >= max(1, args.max):
            break
        print("posting", sid, filename)
        res = api("/api/live/post", {"id": sid, "file": filename, "privacy": "public"})
        if res.get("error"):
            print("  failed:", res["error"][:500])
            # Stop at the platform gate; retrying does not help.
            if "uploadLimitExceeded" in res["error"] or "daily upload limit" in res["error"].lower():
                print("  YouTube's account limit is still in force. Stopping.")
                break
            continue
        link = (((res.get("clip") or {}).get("post") or {}).get("youtube") or {}).get("link")
        print("  published:", link)
        posted += 1
    print("posted", posted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
