"""The learning loop: the engine gets better from what the owner actually keeps.

Honest, local, deterministic and reversible. No cloud, no training service, no pip.

Every choice made on a FINISHED clip is one preference event:

  post     the owner decided this cut was worth publishing
  render   a lab runner-up or a restyle was worth rendering
  custom   the owner dragged a window by hand

We store the MEASURED features of that clip — engine, score, length, whether the
ending actually rode out on a laugh, whether the opening was a real question — in
data/learning.json. Once there are at least MIN_EVENTS events the ranking weights
are nudged toward the features the owner keeps, by at most +/-10% per factor.
Below that threshold nothing is nudged at all: the engine behaves exactly as it
did before the first event.

The "What I've learned" card shows only counts, shares and a median computed from
these same events. Nothing here is invented, and Reset empties the store.
"""

import json
import os
import time

from .config import CONFIG

MIN_EVENTS = 10          # no nudge before this many logged choices
MAX_DELTA = 0.10         # never more than +/-10% on a single factor
MAX_EVENTS = 500         # the store keeps the owner's most recent choices

QUESTION_OPENERS = ("how ", "why ", "what ", "when ", "who ", "which ", "did ",
                    "can ", "will ", "is ", "are ")


def _file():
    """Read the data dir lazily so tests (and a changed CB_DATA) always hit the
    directory that is current right now, not the one seen at import time."""
    return os.path.join(CONFIG["data_dir"], "learning.json")


def _load():
    try:
        data = json.load(open(_file(), encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("events", [])
            return data
    except (OSError, ValueError):
        pass
    return {"events": []}


def _save(data):
    try:
        os.makedirs(CONFIG["data_dir"], exist_ok=True)
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _file())
    except OSError:
        pass


def question_hook(clip):
    """Was the cut's opening a real question hook? Deterministic, reads only the
    clip's own text — the same rule the ranking uses for its tie-break."""
    text = (clip.get("hook") or "").strip() or (clip.get("title") or "").strip()
    if not text:
        return False
    if "?" in text[:80]:
        return True
    return any(text.lower().startswith(w) for w in QUESTION_OPENERS)


def log(kind, clip=None, job=None):
    """Record one real choice. Called from the posting and rendering paths only."""
    clip = clip or {}
    job = job or {}
    try:
        duration = float(clip.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    event = {
        "t": round(time.time(), 1),
        "kind": kind,
        "engine": clip.get("engine_id") or job.get("engine_id") or "",
        "score": clip.get("score") or 0,
        "duration": round(duration, 1),
        "laugh_ending": bool(clip.get("laugh_ending")),
        "question_hook": question_hook(clip),
        "source": (job.get("source") or {}).get("kind", ""),
        "rights": job.get("rights_ok") or "",
    }
    data = _load()
    data["events"] = (data.get("events") or [])[-MAX_EVENTS + 1:] + [event]
    _save(data)
    return event


def reset():
    _save({"events": []})


def _median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _shares(events):
    n = len(events)
    if not n:
        return 0.0, 0.0
    laugh = sum(1 for e in events if e.get("laugh_ending")) / n
    question = sum(1 for e in events if e.get("question_hook")) / n
    return laugh, question


def adjustment():
    """{factor: multiplier} for the ranking weights, or {} while there is not enough
    evidence. Deterministic, and every delta is clamped to +/-10%."""
    events = _load().get("events") or []
    n = len(events)
    if n < MIN_EVENTS:
        return {}
    laugh, question = _shares(events)
    median = _median([e["duration"] for e in events if e.get("duration")])
    adj = {}
    if laugh >= 0.50:
        adj["payoff"] = 1.10          # the owner keeps cuts that land on a laugh
    elif laugh <= 0.15:
        adj["payoff"] = 0.94
    if question >= 0.40:
        adj["hook"] = 1.10            # the owner keeps cuts that open on a question
    elif question <= 0.05:
        adj["hook"] = 0.95
    if median and median <= 35.0:
        adj["pacing"] = 1.06          # short cuts win: reward the tighter band
    elif median and median >= 55.0:
        adj["story"] = 1.06           # long cuts win: reward the fuller story
    return {k: max(1 - MAX_DELTA, min(1 + MAX_DELTA, v)) for k, v in adj.items()}


def profile():
    """Everything the Connect screen shows — counts, shares and a median of real
    logged choices. No estimation, no invented numbers."""
    events = _load().get("events") or []
    n = len(events)
    laugh, question = _shares(events)
    lengths = [e["duration"] for e in events if e.get("duration")]
    engines = {}
    kinds = {}
    for e in events:
        if e.get("engine"):
            engines[e["engine"]] = engines.get(e["engine"], 0) + 1
        if e.get("kind"):
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    adj = adjustment()
    return {
        "events": n,
        "min_events": MIN_EVENTS,
        "active": n >= MIN_EVENTS,
        "remaining": max(0, MIN_EVENTS - n),
        "laugh_ending": {"count": sum(1 for e in events if e.get("laugh_ending")),
                         "share": round(laugh, 3)},
        "question_hook": {"count": sum(1 for e in events if e.get("question_hook")),
                          "share": round(question, 3)},
        "median_length": round(_median(lengths), 1),
        "longest": round(max(lengths), 1) if lengths else 0.0,
        "shortest": round(min(lengths), 1) if lengths else 0.0,
        "engines": engines,
        "kinds": kinds,
        "weights": {k: round(v, 4) for k, v in adj.items()},
        "last": events[-1]["t"] if events else None,
    }
