"""The scout: metadata-only discovery for a niche, and the judgment queue that turns
the owner's calls into training evidence.

WHAT IT DOES. Give it a niche ("podcast clips", "gaming fails", a channel's beat) and
it asks the bundled yt-dlp for METADATA ONLY - titles, channels, view counts, publish
dates, durations. No video is downloaded, no stream is touched, and a result is just a
proposal until the owner presses Make, at which point the normal import path runs and
the whole rights layer (clearance gate included) applies exactly as it always does.

WHAT IT MEASURES. Six features, each derived from fields the source actually reported,
on a 0..100 scale. Nothing is imputed: a missing value stays None, is excluded from the
score, and is listed as unmeasured on the card.

    velocity       views per day since publication (log scale)
    reach          absolute view count (log scale)
    freshness      newer results score higher (30-day half-life)
    duration_fit   how close the source is to the sweet spot for making many shorts
    title_signal   curiosity markers actually present in the title text
    channel_fit    have you already made clips from this channel? (from your jobs.json)

WHAT IT LEARNS. Every make/pass call is stored with the features measured at judgment
time, and pairwise evidence is mined from it - within one search, every make against
every pass - then fit with the same deterministic core as the taste model
(trainer.fit_pairs / rate): the newest fifth of the pairs is held out, and a candidate
activates only at >= 0.55 make-beats-pass on that slice AND strictly above the current
model. One line per attempt lands in data/scout_model_log.json. An active scout model
shifts a proposal's score by at most +/-8 points; it never touches the render engines.

THE JUDGMENT QUEUE also offers clip head-to-heads: the same moment cut by both engines
in one "both" job. That call is the strongest evidence the taste model can get - a real
kept-versus-rejected pair with measured factors on both sides - and it is logged through
the same learning store every other choice uses.

CB_LAB=0 removes all of it; CB_SCOUT=off removes only the scout. Nothing here ever
downloads, posts, or clears a right.
"""

import json
import math
import os
import re
import subprocess
import time

from . import trainer
from .config import CONFIG, ytdlp

STORE_VERSION = 1

# exactly six features: trainer.fit_pairs/rate are the shared core and operate on
# six-coordinate 0..100 vectors (the taste model's factors have the same shape)
FEATURES = ("velocity", "reach", "freshness", "duration_fit", "title_signal", "channel_fit")

MAX_PROPOSALS = 400        # queue entries kept (oldest dropped first)
MAX_JUDGMENTS = 500        # the fit's whole evidence, capped
MAX_CALLS = 200            # judged clip head-to-heads remembered
MAX_PAIRS_PER_QUERY = 12   # bounded evidence per search
MIN_JUDGMENTS = 8          # no fit before this many real calls
REFIT_EVERY = 4            # one attempt per this many further calls
MAX_RESULTS = 20
SEARCH_TIMEOUT = 180       # seconds for the metadata query
MODEL_DELTA = 8.0          # the scout model moves a proposal score by at most this
HALF_LIFE_DAYS = 45.0      # same recency discipline as the taste model

SIGNAL_WORDS = ("how", "why", "what", "secret", "never", "best", "worst", "insane",
                "crazy", "proof", "truth", "mistake", "top", "vs", "insane", "exposed")
STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
             "is", "are", "was", "it", "this", "that", "you", "your", "my", "we",
             "his", "her", "they", "at", "from", "by", "as", "be", "not", "no",
             "but", "if", "then", "so", "do", "does", "did", "just", "new", "full",
             "official", "video", "youtube", "part", "episode", "ep"}


def enabled():
    """CB_LAB=0 removes the whole lab layer; CB_SCOUT=off removes just the scout."""
    if not CONFIG.get("lab", True):
        return False
    mode = str(CONFIG.get("scout_mode", "on") or "").strip().lower()
    return mode not in ("0", "off", "false", "no")


def _store_path():
    return os.path.join(CONFIG["data_dir"], "scout.json")


def _model_path():
    return os.path.join(CONFIG["data_dir"], "scout_model.json")


def _log_path():
    return os.path.join(CONFIG["data_dir"], "scout_model_log.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, data):
    try:
        os.makedirs(CONFIG["data_dir"], exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _store():
    data = _read(_store_path())
    if isinstance(data, dict) and isinstance(data.get("proposals"), list):
        data.setdefault("queries", [])
        data.setdefault("judgments", [])
        data.setdefault("calls", [])
        return data
    return {"version": STORE_VERSION, "queries": [], "proposals": [],
            "judgments": [], "calls": []}


# --------------------------------------------------------------- measured features

def _scale(x, lo, hi):
    """Log-scale a positive measurement onto 0..100. Linear scales make 10k and 10M
    views look like neighbours; log scales keep the order while compressing the tail."""
    try:
        x = max(float(x), float(lo))
    except (TypeError, ValueError):
        return None
    if hi <= lo:
        return 0.0
    z = (math.log(x) - math.log(lo)) / (math.log(hi) - math.log(lo))
    return round(max(0.0, min(1.0, z)) * 100.0, 1)


def _age_days(published, now=None):
    if not published:
        return None
    try:
        t = float(published)
    except (TypeError, ValueError):
        return None
    return max(0.0, ((now or time.time()) - t) / 86400.0)


def channel_history(jobs=None):
    """Which channels this owner has already imported from, measured from jobs.json.
    `done` is a finished job; `seen` is any import. A fresh install starts empty, and
    an upload with no channel simply contributes nothing - nothing is guessed."""
    if jobs is None:
        jobs = _read(os.path.join(CONFIG["data_dir"], "jobs.json")) or []
    done, seen = set(), set()
    if not isinstance(jobs, list):
        jobs = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        src = j.get("source") or {}
        ch = str(src.get("uploader") or src.get("channel") or "").strip().lower()
        if not ch:
            continue
        seen.add(ch)
        if j.get("status") == "done":
            done.add(ch)
    return {"done": done, "seen": seen}


def features(p, history=None):
    """The six measured features for one proposal, each 0..100 or None when the source
    did not report what the feature needs. Never imputed."""
    now = time.time()
    age = _age_days((p or {}).get("published"), now)
    out = {}
    views = (p or {}).get("views")
    if isinstance(views, (int, float)) and not isinstance(views, bool) and age is not None:
        speed = float(views) / max(1.0, age)
        out["velocity"] = _scale(speed, 1.0, 20000.0)
    else:
        out["velocity"] = None
    out["reach"] = (_scale(views, 1.0, 5_000_000.0)
                    if isinstance(views, (int, float)) and not isinstance(views, bool)
                    else None)
    out["freshness"] = (round(100.0 * math.pow(0.5, age / 30.0), 1)
                        if age is not None else None)
    try:
        dur = float((p or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    out["duration_fit"] = (round(100.0 * math.exp(-((math.log(dur / 1200.0)) ** 2)
                                                   / (2 * 0.85 ** 2)), 1)
                           if dur > 0 else None)
    text = str((p or {}).get("title") or "").lower()
    hits = sum(1 for w in SIGNAL_WORDS if re.search(rf"\b{re.escape(w)}\b", text))
    hits += 1 if "?" in text else 0
    hits += 1 if re.search(r"\d", text) else 0
    out["title_signal"] = round(min(100.0, hits * 34.0), 1)
    ch = str((p or {}).get("channel") or "").strip().lower()
    if history is None:
        out["channel_fit"] = None
    elif not ch:
        out["channel_fit"] = 0.0
    elif ch in history.get("done", ()):
        out["channel_fit"] = 100.0
    elif ch in history.get("seen", ()):
        out["channel_fit"] = 50.0
    else:
        out["channel_fit"] = 0.0
    return out


def _vec(feat):
    """A complete measured feature vector, or None. A partial one never trains or
    adjusts anything: an imputed feature would be an invented measurement."""
    out = []
    for k in FEATURES:
        v = (feat or {}).get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        out.append(float(v))
    return out


def measured_score(feat):
    """The mean of the features that were actually measured, or None. How many of the
    six contributed is part of the honest payload, not hidden."""
    vals = [v for v in (feat or {}).values() if isinstance(v, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def _human_views(n):
    if not isinstance(n, (int, float)):
        return "views not reported"
    n = float(n)
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= cut:
            return f"{n / cut:.1f}".rstrip("0").rstrip(".") + suffix + " views"
    return f"{int(n)} views"


def reasons(p, feat):
    """Short, honest why-lines for one proposal: what was measured, and what was not."""
    out = []
    age = _age_days((p or {}).get("published"))
    if feat.get("velocity") is not None:
        speed = float(p["views"]) / max(1.0, age)
        out.append(f"{_human_views(p.get('views'))} over {age:.0f}d -> {speed:,.0f}/day")
    else:
        out.append("views or publish date not reported - velocity and reach unmeasured")
    if feat.get("duration_fit") is not None:
        d = float(p["duration"])
        out.append(f"{int(d // 60)}m{int(d % 60):02d}s source "
                   f"(long enough to cut, short enough to mine several times)")
    if feat.get("freshness") is not None and age <= 14:
        out.append(f"published {age:.0f}d ago")
    if feat.get("title_signal"):
        out.append(f"title carries {int(feat['title_signal'] // 34)} curiosity marker(s)")
    if feat.get("channel_fit") == 100.0:
        out.append("you have already made clips from this channel")
    elif feat.get("channel_fit") == 50.0:
        out.append("you imported from this channel before, nothing finished yet")
    missing = [k for k in FEATURES if feat.get(k) is None]
    if missing:
        out.append("not measured: " + ", ".join(missing))
    return out


# ------------------------------------------------------------------- the model layer

def _model():
    data = _read(_model_path())
    if isinstance(data, dict) and data.get("active"):
        return data
    return None


def _fits():
    data = _read(_log_path())
    return data if isinstance(data, list) else []


def model_adjust(vec):
    """The active scout model's shift for one complete feature vector, in points:
    bounded by +/-MODEL_DELTA, deterministic, and zero without an active model."""
    m = _model()
    if not m or vec is None:
        return 0.0
    weights, scale = m.get("weights") or {}, m.get("scale") or {}
    z = 0.0
    for i, k in enumerate(FEATURES):
        try:
            w = float(weights[k])
            s = float(scale.get(k) or 1.0) or 1.0
        except (KeyError, TypeError, ValueError):
            return 0.0
        z += w * ((float(vec[i]) - 50.0) / s)      # centred: level alone earns nothing
    return round(MODEL_DELTA * z / (1.0 + abs(z)), 2)


def _median(values):
    ordered = sorted(v for v in values if isinstance(v, (int, float)))
    if not ordered:
        return None
    mid = len(ordered) // 2
    return (ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0)


def rank(rows, history=None):
    """Proposals ranked by measured score + the gated model adjustment, each with its
    per-feature breakdown and why-lines. Deterministic: score desc, then id."""
    hist = channel_history() if history is None else history
    out = []
    for p in rows or []:
        feat = features(p, hist)
        vec = _vec(feat)
        base = measured_score(feat)
        adjust = model_adjust(vec) if vec is not None else 0.0
        out.append({**p, "features": feat, "score": base, "model_adjust": adjust,
                    "rank_score": round((base or 0.0) + adjust, 1),
                    "reasons": reasons(p, feat)})
    out.sort(key=lambda r: (-(r["rank_score"] or 0.0), str(r.get("id") or "")))
    return out


def trend(rows):
    """What the fetched metadata actually says about this niche: medians, the words
    that keep appearing in titles, how fresh the results are, who repeats. Every
    number is computed from the results, and the note says what it is not."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return None
    now = time.time()
    views = [r.get("views") for r in rows]
    durs = [r.get("duration") for r in rows]
    fresh = [r for r in rows
             if r.get("published") and (now - float(r["published"])) <= 30 * 86400]
    words = {}
    for r in rows:
        for w in re.findall(r"[a-z0-9']+", str(r.get("title") or "").lower()):
            if len(w) < 4 or w in STOPWORDS:
                continue
            words[w] = words.get(w, 0) + 1
    channels = {}
    for r in rows:
        ch = str(r.get("channel") or "").strip()
        if ch:
            channels[ch] = channels.get(ch, 0) + 1
    md = _median(durs)
    return {
        "results": len(rows),
        "median_views": (int(_median(views)) if _median(views) is not None else None),
        "median_duration": round(md, 1) if md is not None else None,
        "fresh_share": round(len(fresh) / len(rows), 3),
        "top_words": [w for w, _n in sorted(words.items(),
                                            key=lambda kv: (-kv[1], kv[0]))[:8]],
        "repeat_channels": [c for c, n in sorted(channels.items(),
                                                 key=lambda kv: (-kv[1], kv[0]))
                            if n > 1][:5],
        "note": ("measured from the fetched metadata only; it is not an estimate of "
                 "demand, and nothing here predicts a platform's algorithm"),
    }


# -------------------------------------------------------------------- the discovery

def _proposal(row, query, at):
    """One yt-dlp metadata row -> a stored proposal. Every field is taken from what the
    extractor reported; a missing one stays missing."""
    if not isinstance(row, dict):
        return None
    vid = str(row.get("id") or "").strip()
    if not vid:
        return None
    try:
        duration = float(row.get("duration"))
    except (TypeError, ValueError):
        duration = None
    views = row.get("view_count")
    views = int(views) if isinstance(views, (int, float)) and not isinstance(views, bool) else None
    published = row.get("timestamp")
    if not isinstance(published, (int, float)) or isinstance(published, bool):
        published = None
        stamp = str(row.get("upload_date") or "")
        if re.fullmatch(r"\d{8}", stamp):
            try:
                published = time.mktime(time.strptime(stamp, "%Y%m%d"))
            except ValueError:
                published = None
    url = str(row.get("webpage_url") or row.get("url") or "")
    if not url.startswith("http") and re.fullmatch(r"[\w-]{6,}", vid):
        url = f"https://www.youtube.com/watch?v={vid}"
    return {
        "id": vid,
        "url": url,
        "title": str(row.get("title") or "")[:200],
        "channel": str(row.get("channel") or row.get("uploader") or "")[:120],
        "channel_id": str(row.get("channel_id") or row.get("uploader_id") or ""),
        "duration": duration,
        "views": views,
        "published": published,
        "live": str(row.get("live_status") or ""),
        "query": query,
        "added": at,
        "verdict": None,
        "judged_at": None,
    }


def _fetch(query, limit):
    """The one network call in this module: a metadata query through the bundled
    yt-dlp. Tries the full extract first (real view counts and publish dates - still
    metadata only, no media is downloaded), then a flat search if the site will not
    serve per-video metadata."""
    last = None
    for extra in ([], ["--flat-playlist"]):
        cmd = [ytdlp(), "--dump-json", "--ignore-errors", "--no-warnings",
               "--playlist-end", str(limit), *extra, f"ytsearch{limit}:{query}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                  timeout=SEARCH_TIMEOUT)
        except FileNotFoundError:
            raise RuntimeError("yt-dlp not found - put yt-dlp.exe in bin/ (see README)")
        except subprocess.TimeoutExpired:
            raise RuntimeError("the metadata search timed out")
        rows = []
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        if rows:
            return rows[:limit], ("metadata" if not extra else "flat metadata")
        last = (proc.stderr or "").strip().splitlines()[-2:]
    raise RuntimeError("the search returned nothing: " + " | ".join(last or ["no results"]))


def search(query, limit=10, fetch=None):
    """Discover a niche, metadata only, and store what comes back. `fetch` is injectable
    so the offline test suite never touches the network."""
    if not enabled():
        return {"enabled": False, "reason": "the scout is off (CB_SCOUT=off or CB_LAB=0)"}
    q = " ".join(str(query or "").split())[:120]
    if not q:
        return {"enabled": True, "error": "give the scout a niche to search for"}
    try:
        limit = max(1, min(int(limit or 10), MAX_RESULTS))
    except (TypeError, ValueError):
        limit = 10
    try:
        rows, method = (fetch or _fetch)(q, limit)
    except RuntimeError as e:
        return {"enabled": True, "query": q, "error": str(e)[:400]}
    at = time.time()
    fresh = [p for p in (_proposal(r, q, at) for r in rows) if p]
    data = _store()
    by_id = {p.get("id"): p for p in data["proposals"]}
    added = 0
    for p in fresh:
        old = by_id.get(p["id"])
        if old is not None:
            # already known: it belongs to the latest search's context (and keeps its
            # verdict), so a repeat search shows what it found instead of an empty queue
            old["query"] = q
            continue
        data["proposals"].append(p)
        by_id[p["id"]] = p
        added += 1
    data["queries"].append({"q": q, "at": at, "found": len(fresh), "added": added})
    data["queries"] = data["queries"][-50:]
    del data["proposals"][:-MAX_PROPOSALS]
    _write(_store_path(), data)
    ranked = rank([p for p in data["proposals"] if p.get("query") == q])
    return {"enabled": True, "query": q, "method": method, "found": len(fresh),
            "added": added, "stored": len(ranked), "proposals": ranked,
            "trend": trend(ranked),
            "note": ("metadata only: nothing was downloaded. Make runs the normal "
                     "import, and the rights layer applies exactly as it always does.")}


def proposal(proposal_id):
    return next((p for p in _store()["proposals"] if p.get("id") == proposal_id), None)


# -------------------------------------------------------------------- the judgments

def judge(proposal_id, verdict):
    """Record the owner's call on one proposal. 'make' and 'pass' are the two real
    judgments; anything else is refused. Evidence is frozen at judgment time: the
    features measured now are stored with the call and never rewritten later."""
    if not enabled():
        return {"enabled": False, "reason": "the scout is off (CB_SCOUT=off or CB_LAB=0)"}
    v = str(verdict or "").strip().lower()
    if v not in ("make", "pass"):
        return {"enabled": True, "error": "verdict must be 'make' or 'pass'"}
    data = _store()
    p = next((x for x in data["proposals"] if x.get("id") == proposal_id), None)
    if not p:
        return {"enabled": True, "error": "unknown proposal"}
    feat = features(p, channel_history())
    vec = _vec(feat)
    p["verdict"] = v
    p["judged_at"] = time.time()
    data["judgments"].append({
        "t": p["judged_at"], "id": p["id"], "query": p.get("query") or "",
        "verdict": v, "features": feat, "vec": vec,
        "title": str(p.get("title") or "")[:120],
        "channel": p.get("channel") or "",
    })
    data["judgments"] = data["judgments"][-MAX_JUDGMENTS:]
    _write(_store_path(), data)
    fit = auto_fit()          # the day-by-day cadence; a no-op until it is earned
    return {"enabled": True, "id": p["id"], "verdict": v,
            "judgments": len(data["judgments"]), "fit": fit, "model": state()}


def record_call(job_id, moment, mine, other):
    """Remember a clip head-to-head so the queue does not offer it again. The evidence
    itself lives in the learning store (learning.log('judge', ...)); this is the
    scout's own bookkeeping."""
    if not enabled():
        return False
    data = _store()
    key = {"job": job_id, "moment": moment, "mine": mine, "other": other,
           "t": time.time()}
    data["calls"].append(key)
    data["calls"] = data["calls"][-MAX_CALLS:]
    _write(_store_path(), data)
    return True


def _called(job_id, moment):
    return any(c.get("job") == job_id and c.get("moment") == moment
               for c in _store()["calls"])


def _clip_path(clip):
    name = os.path.basename(str((clip or {}).get("file") or "").split("?")[0])
    return os.path.join(CONFIG["data_dir"], "clips", name) if name else ""


def judgment_queue(jobs, limit=5):
    """Rendered pairs worth a real head-to-head: the same moment cut by both engines in
    one 'both' job. Only pairs whose files exist on disk are offered, and a pair the
    owner already judged is not offered twice."""
    if not enabled():
        return []
    pairs = []
    rows = sorted([j for j in (jobs or []) if isinstance(j, dict)],
                  key=lambda j: -(j.get("created") or 0))
    for j in rows:
        by_moment = {}
        for i, c in enumerate(j.get("clips") or []):
            if c.get("moment") is None:
                continue
            by_moment.setdefault(c["moment"], []).append((i, c))
        for m, group in sorted(by_moment.items()):
            if len(group) != 2:
                continue
            (ia, a), (ib, b) = group[0], group[1]
            if a.get("engine_id") == b.get("engine_id"):
                continue
            if not (os.path.isfile(_clip_path(a)) and os.path.isfile(_clip_path(b))):
                continue
            if _called(j.get("id"), m):
                continue
            pairs.append({
                "job": j.get("id"), "job_name": j.get("name"), "moment": m,
                "a": _pair_side(ia, a), "b": _pair_side(ib, b),
                "why": ("the same moment cut by both engines - your call here is a real "
                        "kept-versus-rejected pair for the taste model"),
            })
            if len(pairs) >= limit:
                return pairs
    return pairs


def _pair_side(index, clip):
    return {"index": index, "engine": clip.get("engine_id"),
            "engine_name": clip.get("engine"), "title": clip.get("title"),
            "score": clip.get("score"), "file": clip.get("file"),
            "start": clip.get("start"), "end": clip.get("end"),
            "duration": clip.get("duration"),
            "factors": clip.get("factors") or {}}


# ------------------------------------------------------------------------- the fit

def _pairs(judgments):
    """(make, pass, weight, t) pairs from real calls: within one search, every make the
    owner called against every pass. A search with only one kind of verdict contributes
    nothing - there is nothing to compare. Order is chronological, so the newest fifth
    can be held out."""
    rows = [j for j in (judgments or []) if isinstance(j, dict) and j.get("vec")]
    newest = max([float(j.get("t") or 0.0) for j in rows] or [0.0])
    grouped = {}
    for j in rows:
        g = grouped.setdefault(j.get("query") or "", {"make": [], "pass": []})
        g[j["verdict"] if j.get("verdict") in ("make", "pass") else "pass"].append(j)
    pairs = []
    for _q, g in grouped.items():
        made = 0
        for m in g["make"]:
            if made >= MAX_PAIRS_PER_QUERY:
                break
            for p in g["pass"]:
                pairs.append(([float(v) for v in m["vec"]],
                              [float(v) for v in p["vec"]],
                              trainer.recency(m.get("t"), newest),
                              float(m.get("t") or 0.0)))
                made += 1
                if made >= MAX_PAIRS_PER_QUERY:
                    break
    pairs.sort(key=lambda x: (x[3], tuple(x[0]), tuple(x[1])))
    return pairs


def _decide(cand_rate, inc_rate, hold_n):
    """The activation gate for the scout, in its own words: what the owner called make
    must rank above what they called pass, on the held-out newest fifth, at 0.55 or
    better - and strictly above the active model."""
    if not hold_n or cand_rate is None:
        return False, ("no held-out judgments yet - a scout model needs both makes and "
                       "passes to prove itself against")
    if cand_rate < trainer.ACTIVATE_RATE:
        return False, (f"held-out make-beats-pass {cand_rate:.2f} is below "
                       f"{trainer.ACTIVATE_RATE:.2f}")
    if inc_rate is not None and cand_rate <= inc_rate:
        return False, (f"new model {cand_rate:.2f} did not beat the active model's "
                       f"{inc_rate:.2f}")
    if inc_rate is None:
        return True, (f"first scout model activated: make-beats-pass {cand_rate:.2f} on "
                      f"{hold_n} held-out judgment pair(s)")
    return True, (f"replaced the active scout model: {cand_rate:.2f} beats {inc_rate:.2f} "
                  f"on {hold_n} held-out judgment pair(s)")


def fit(reason="manual"):
    """One scout fit attempt: the same deterministic core as the taste model, on the
    metadata feature space. One line per attempt in data/scout_model_log.json; a
    rejected candidate leaves the active model exactly as it was."""
    if not enabled():
        return {"enabled": False, "attempted": False, "activated": False,
                "reason": "the scout is off (CB_SCOUT=off or CB_LAB=0)"}
    data = _store()
    pairs = _pairs(data["judgments"])
    day = time.strftime("%Y-%m-%d")
    if not pairs:
        return {"enabled": True, "attempted": False, "activated": False, "day": day,
                "reason": ("nothing to fit yet: judge at least one make and one pass in "
                           "the same search")}
    n = len(pairs)
    hold_n = max(1, int(round(n * trainer.HOLDOUT_FRACTION)))
    train, hold = pairs[:n - hold_n], pairs[n - hold_n:]
    fitted = trainer.fit_pairs(train)
    record = {"day": day, "version": max([r.get("version") or 0 for r in _fits()] or [0]) + 1,
              "judgments": len(data["judgments"]), "pairs": len(train),
              "holdout": None, "holdout_n": hold_n, "activated": False, "reason": ""}
    if fitted is None:
        record["reason"] = "no complete measured pairs to learn from yet"
        activated, why = False, record["reason"]
    else:
        theta, scale = fitted
        cand = trainer.rate(theta, scale, [(w, l) for w, l, *_ in hold])
        record["holdout"] = round(cand, 4) if cand is not None else None
        incumbent = _model()
        inc_rate = None
        if incumbent and hold:
            iw, isc = incumbent.get("weights") or {}, incumbent.get("scale") or {}
            try:
                inc_rate = trainer.rate([float(iw[k]) for k in FEATURES],
                                        [float(isc[k]) for k in FEATURES],
                                        [(w, l) for w, l, *_ in hold])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                inc_rate = None
        activated, why = _decide(cand, inc_rate, hold_n)
        record["activated"] = bool(activated)
        record["reason"] = why
    if activated:
        model = {
            "version": record["version"], "active": True, "day": day,
            "t": round(time.time(), 1),
            "weights": {k: round(theta[i], 6) for i, k in enumerate(FEATURES)},
            "scale": {k: round(scale[i], 4) for i, k in enumerate(FEATURES)},
            "holdout": record["holdout"], "holdout_n": record["holdout_n"],
            "train_pairs": len(train), "judgments": len(data["judgments"]),
            "note": ("A local pairwise ranker over the measured metadata features. It "
                     "shifts a proposal's score by at most 8 points, activates only when "
                     "the newest fifth of your judgments says it ranks what you called "
                     "make above what you called pass, at 0.55 or better, and is "
                     "reproducible from the store alone."),
        }
        _write(_model_path(), model)
    fits = _fits()
    fits.append(record)
    _write(_log_path(), fits[-200:])
    out = dict(record)
    out.update({"enabled": True, "attempted": True, "trigger": reason})
    return out


def auto_fit():
    """The cadence: one attempt per REFIT_EVERY further judgments, once MIN_JUDGMENTS
    exist. Cheap when it does nothing; absent when the scout is off."""
    if not enabled():
        return None
    n = len(_store()["judgments"])
    if n < MIN_JUDGMENTS:
        return None
    fits = _fits()
    since = n - ((fits[-1].get("judgments") or 0) if fits else 0)
    if since < REFIT_EVERY:
        return None
    return fit(reason="cadence")


def state():
    """The scout model block for the UI and any agent: real counts, the last three
    attempts, and how many more judgments the next fit waits for."""
    data = _store()
    fits, model = _fits(), _model()
    n = len(data["judgments"])
    last = fits[-1] if fits else None
    since = n - (last.get("judgments") or 0) if last else n
    if n < MIN_JUDGMENTS:
        remaining, waiting_for = MIN_JUDGMENTS - n, "judgments"
    elif since < REFIT_EVERY:
        remaining, waiting_for = REFIT_EVERY - since, "judgments"
    else:
        remaining, waiting_for = 0, "the next judgment"
    return {
        "enabled": enabled(),
        "active": bool(model),
        "version": (model or {}).get("version"),
        "trained": (model or {}).get("day"),
        "holdout": (model or {}).get("holdout"),
        "holdout_n": (model or {}).get("holdout_n"),
        "weights": (model or {}).get("weights") or {},
        "adjust": MODEL_DELTA,
        "judgments": n,
        "min_judgments": MIN_JUDGMENTS,
        "refit_every": REFIT_EVERY,
        "remaining": remaining,
        "waiting_for": waiting_for,
        "fits": [{k: r.get(k) for k in ("day", "version", "pairs", "holdout",
                                        "activated", "reason")} for r in fits[-3:]],
        "note": ("A local pairwise ranker over the measured metadata features. It only "
                 "shifts proposal scores, never a render, and it activates only on your "
                 "own held-out judgments."),
    }


def queue(include_judged=True):
    """The Scout screen in one read: the newest search's proposals (ranked, with
    verdicts), the measured trend, and the model block."""
    data = _store()
    latest = data["queries"][-1]["q"] if data["queries"] else None
    rows = [p for p in data["proposals"] if p.get("query") == latest] if latest else []
    ranked = rank(rows)
    if not include_judged:
        ranked = [r for r in ranked if not r.get("verdict")]
    made = sum(1 for j in data["judgments"] if j.get("verdict") == "make")
    passed = sum(1 for j in data["judgments"] if j.get("verdict") == "pass")
    return {
        "enabled": enabled(),
        "query": latest,
        "queries": data["queries"][-5:],
        "proposals": ranked,
        "judged": {"make": made, "pass": passed, "total": len(data["judgments"])},
        "calls": len(data["calls"]),
        "trend": trend(ranked),
        "model": state(),
        "note": ("Metadata-only discovery. Making a proposal runs the normal import and "
                 "the rights layer applies; nothing here downloads, posts or clears a "
                 "right."),
    }


def reset():
    """Forget the queue, the judgments and the model they trained."""
    for path in (_store_path(), _model_path(), _log_path()):
        try:
            os.remove(path)
        except OSError:
            pass
