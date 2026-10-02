"""The learning loop: both engines get better from what the owner actually keeps.

Honest, local, deterministic and reversible. No cloud, no training service, no pip.

Every choice made on a FINISHED clip is one preference event:

  post     the owner decided this cut was worth publishing
  render   a lab runner-up or a restyle was worth rendering
  custom   the owner dragged a window by hand
  judge    the owner picked one cut over another (the rejected one rides in as `other`)

Since v3 each event also carries up to MAX_SIBLINGS of the offered alternatives the cut
was chosen over - their judge score and measured factor vector - which is what lets the
local taste model (clipblitz/trainer.py) learn "kept versus offered", not just "kept".

We store the MEASURED features of that clip — engine, score, length, whether the
ending actually rode out on a laugh, whether the opening was a real question — plus
the clip's own factor breakdown (hook/story/payoff/energy/pacing) and, when the job
still had its candidate pool, what that pool averaged. That last part is the whole
point of v2: the engine can compare the cuts the owner KEEPS against the cuts it
offered alongside them, so it learns which measured factor this owner over-indexes
on, not just which endings they laugh at.

Three layers, each with its own evidence threshold:

  global     >= MIN_EVENTS logged choices nudge the ranking weights,
             by at most +/-MAX_DELTA (+/-10%) per factor
  engine     >= MIN_ENGINE_EVENTS choices ON THAT ENGINE add a small
             refinement on top (+/-MAX_ENGINE_DELTA), so "both engines"
             can drift apart into what each is actually good at for this owner
  factors    >= MIN_POOL_EVENTS choices that carry a candidate pool show which
             measured factor beat its own pool average, capped at
             +/-MAX_FACTOR_DELTA

Older choices count for less (HALF_LIFE_DAYS), so the engine keeps up with taste
instead of being haunted by the first week of use. Nothing is nudged below the
thresholds: a fresh install behaves exactly as it did before the first event.
Every nudge is reproducible from the store alone, and Reset empties everything.

A fourth gate sits on top of the three layers: the trained model (clipblitz/trainer.py)
contributes at most +/-6% per factor, and only while a held-out slice of the owner's
real choices says it improved their ranking. It is additive and removable; with the
lab off, or before its own thresholds are met, nothing here changes.

The "What I've learned" card shows counts, shares, medians and the multipliers
computed from these same events. Nothing here is invented.
"""

import json
import math
import os
import time

from .config import CONFIG

MIN_EVENTS = 10          # no global nudge before this many logged choices
MIN_ENGINE_EVENTS = 15   # an engine-specific refinement needs its own evidence
MIN_POOL_EVENTS = 8      # factor learning needs this many choices with a candidate pool
MAX_DELTA = 0.10         # never more than +/-10% on a single factor (all layers)
MAX_ENGINE_DELTA = 0.05  # the engine refinement's own slice of that budget
MAX_FACTOR_DELTA = 0.06  # the factor-over-index layer's own slice
MAX_EVENTS = 500         # the store keeps the owner's most recent choices
MAX_SIBLINGS = 8         # offered alternatives stored per choice (the trainer's evidence)
HALF_LIFE_DAYS = 45.0    # a choice this old counts half as much as today's
MIN_POOL_GAP = 1.0       # keep a candidate pool only if it had alternatives to beat
MIN_FACTOR_DELTA = 5.0   # a factor must beat its pool by this much (0-100 scale)
STORE_VERSION = 3        # v3 adds the `sib` sibling vectors; v2 events still load

QUESTION_OPENERS = ("how ", "why ", "what ", "when ", "who ", "which ", "did ",
                    "can ", "will ", "is ", "are ")

FACTORS = ("hook", "story", "payoff", "energy", "pacing", "event")

ENGINE_NAMES = {"prox": "ProX v5", "b2": "B2 Pro X"}


def _file():
    """Read the data dir lazily so tests (and a changed CB_DATA) always hit the
    directory that is current right now, not the one seen at import time."""
    return os.path.join(CONFIG["data_dir"], "learning.json")


def _load():
    try:
        data = json.load(open(_file(), encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("events", [])
            data.setdefault("version", STORE_VERSION)
            return data
    except (OSError, ValueError):
        pass
    return {"events": [], "version": STORE_VERSION}


def _save(data):
    try:
        os.makedirs(CONFIG["data_dir"], exist_ok=True)
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _file())
    except OSError:
        pass


def events():
    """The logged choices, oldest first - the store the model is fit from."""
    return _load().get("events") or []


def _lab():
    """The trainer module when the lab is on and importable, else None. The store has
    to keep working even if the optional layer is missing or broken."""
    try:
        from . import trainer
        return trainer if trainer.enabled() else None
    except Exception:
        return None


def question_hook(clip):
    """Was the cut's opening a real question hook? Deterministic, reads only the
    clip's own text — the same rule the ranking uses for its tie-break."""
    text = (clip.get("hook") or "").strip() or (clip.get("title") or "").strip()
    if not text:
        return False
    if "?" in text[:80]:
        return True
    return any(text.lower().startswith(w) for w in QUESTION_OPENERS)


def _clean_factors(raw):
    """Only the numeric, measured factors. Anything else is dropped rather than
    guessed at, so a malformed clip can never poison the store."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for k in FACTORS:
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(max(0.0, min(100.0, float(v))), 1)
    return out


def _pool_mean(job):
    """The mean factor breakdown of the candidates the engine OFFERED for this job.

    'Kept this cut' only means something next to 'instead of what?'. The pool is
    every candidate the run produced, so the mean is a real measurement of the
    alternative. Returns {} when the job kept no usable pool."""
    pool = (job or {}).get("candidates") or []
    rows = [_clean_factors(c.get("factors")) for c in pool if isinstance(c, dict)]
    rows = [r for r in rows if r]
    if len(rows) < 2:
        return {}
    out = {}
    for k in FACTORS:
        vals = [r[k] for r in rows if k in r]
        if vals:
            out[k] = round(sum(vals) / len(vals), 1)
    return out


def _same_window(cand, start, end, tol=0.75):
    """Is this candidate the very window that was kept? Then it is no alternative."""
    try:
        return (abs(float(cand.get("start")) - start) <= tol
                and abs(float(cand.get("end")) - end) <= tol)
    except (TypeError, ValueError):
        return False


def _sib_entry(item):
    """One offered alternative, compact: its judge score and its measured factors."""
    if not isinstance(item, dict):
        return None
    factors = _clean_factors(item.get("factors"))
    if not factors:
        return None
    score = item.get("score")
    return {"score": score if (isinstance(score, (int, float))
                               and not isinstance(score, bool)) else None,
            "factors": factors}


def _siblings(clip, job, other):
    """Up to MAX_SIBLINGS real alternatives the kept cut was chosen over: the head-to-
    head loser when this was a judgement (`other`), then the job's candidate pool,
    strongest score first - the near-misses matter most. The kept window itself is
    excluded; a cut cannot be an alternative to itself. Every value is measured."""
    out = []
    if other:
        entry = _sib_entry(other)
        if entry:
            out.append(entry)
    clip = clip or {}
    try:
        k_start, k_end = float(clip.get("start")), float(clip.get("end"))
    except (TypeError, ValueError):
        k_start = k_end = None
    rows = []
    for c in ((job or {}).get("candidates") or []):
        if not isinstance(c, dict):
            continue
        if k_start is not None and _same_window(c, k_start, k_end):
            continue
        entry = _sib_entry(c)
        if entry:
            rows.append(entry)
    rows.sort(key=lambda e: -(e.get("score") or 0))
    out.extend(rows)
    return out[:MAX_SIBLINGS]


def log(kind, clip=None, job=None, other=None):
    """Record one real choice. Called from the posting, rendering and judging paths.

    kind: post | render | custom | judge. A judge event is a head-to-head call, so the
    rejected cut rides in as `other` and is stored as a sibling against the winner.
    """
    clip = clip or {}
    job = job or {}
    try:
        duration = float(clip.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    pool = _pool_mean(job)
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
    factors = _clean_factors(clip.get("factors"))
    if factors:
        event["factors"] = factors
    if pool:
        event["pool"] = pool
        event["pool_n"] = len([c for c in (job.get("candidates") or [])
                               if isinstance(c, dict)])
    lab = _lab()
    if lab:
        siblings = _siblings(clip, job, other)
        if siblings:
            event["sib"] = siblings
    data = _load()
    data["events"] = (data.get("events") or [])[-MAX_EVENTS + 1:] + [event]
    data["version"] = STORE_VERSION
    _save(data)
    if lab:
        try:
            lab.auto_fit()          # the day-by-day cadence; a no-op until it is earned
        except Exception:
            pass                    # a fit is an optimisation - it must never break a post
    return event


def reset():
    """Empty the store and forget the model it trained - 'back to base' means both."""
    _save({"events": [], "version": STORE_VERSION})
    lab = _lab()
    if lab:
        lab.reset()


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


# ------------------------------------------------------- recency-weighted view

def _recency(event, now=None):
    """A choice's weight: 1.0 today, 0.5 after HALF_LIFE_DAYS, monotonically lower
    after that. Deterministic — it is a pure function of the stored timestamp."""
    now = now if now is not None else time.time()
    try:
        age_days = max(0.0, (now - float(event.get("t") or 0.0)) / 86400.0)
    except (TypeError, ValueError):
        age_days = 0.0
    return math.pow(0.5, age_days / HALF_LIFE_DAYS)


def _wshare(events, key, now=None):
    """Recency-weighted share of a boolean feature. Falls back to the plain share
    when every event is weightless (all timestamps missing/future-free)."""
    tot = sum(_recency(e, now) for e in events)
    if tot <= 0:
        return _shares(events)[0 if key == "laugh_ending" else 1]
    hit = sum(_recency(e, now) for e in events if e.get(key))
    return hit / tot


def _wmedian(events, now=None):
    """Recency-weighted median clip length. Weighted-median: the value at which the
    accumulated weight first reaches half of the total."""
    pairs = sorted((float(e.get("duration") or 0.0), _recency(e, now))
                   for e in events if e.get("duration"))
    if not pairs:
        return 0.0
    total = sum(w for _, w in pairs)
    if total <= 0:
        return _median([d for d, _ in pairs])
    acc = 0.0
    for d, w in pairs:
        acc += w
        if acc >= total / 2.0:
            return d
    return pairs[-1][0]


# ----------------------------------------------------------- the three layers

def _clamp(mult):
    return max(1 - MAX_DELTA, min(1 + MAX_DELTA, mult))


def _rules(events, now=None):
    """The base taste rules, on recency-weighted shares: the endings this owner
    keeps, the openings they keep, and how long the cuts they keep run."""
    if not events:
        return {}
    laugh = _wshare(events, "laugh_ending", now)
    question = _wshare(events, "question_hook", now)
    median = _wmedian(events, now)
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
    return adj


def _io_share(events):
    """Share of recent choices that came from the owner over-riding the podium
    (a lab re-render or a hand-dragged window). A real measured share, shown on
    the card — never used to guess at anything the store does not contain."""
    n = len(events)
    if not n:
        return 0.0
    return sum(1 for e in events if e.get("kind") in ("render", "custom")) / n


def factor_bias(events, now=None):
    """How far the KEPT cut beat its own candidate pool, per measured factor.

    For every event that stored both its own factors and the pool it was chosen
    from, this is the mean (kept - pool) in factor points. A factor the owner
    consistently keeps above its pool gets a small boost; a factor they keep
    below its pool gets a small penalty. Both capped at +/-MAX_FACTOR_DELTA and
    only applied once MIN_POOL_EVENTS such choices exist.
    """
    rows = [e for e in events if e.get("factors") and e.get("pool")]
    if len(rows) < MIN_POOL_EVENTS:
        return {}, {}
    deltas, weights = {}, {}
    for e in rows:
        w = _recency(e, now)
        for k, v in e["factors"].items():
            if k not in e["pool"]:
                continue
            deltas.setdefault(k, 0.0)
            weights.setdefault(k, 0.0)
            deltas[k] += (v - e["pool"][k]) * w
            weights[k] += w
    bias, evidence = {}, {}
    for k, acc in deltas.items():
        tot = weights.get(k) or 0.0
        if tot <= 0:
            continue
        mean = acc / tot
        evidence[k] = round(mean, 1)
        if mean >= MIN_FACTOR_DELTA:          # beats the pool: this owner wants more of it
            bias[k] = 1 + min(MAX_FACTOR_DELTA, mean / 100.0 * 2.0)
        elif mean <= -MIN_FACTOR_DELTA:       # kept below its pool: matters less than it looks
            bias[k] = 1 - min(MAX_FACTOR_DELTA, -mean / 100.0 * 2.0)
    return bias, evidence


def adjustment(engine=None):
    """{factor: multiplier} for the ranking weights, or {} while there is not enough
    evidence. Deterministic, and every delta is clamped to +/-MAX_DELTA (10%).

    engine=None is the global profile. Passing an engine id adds that engine's own
    refinement on top, which needs MIN_ENGINE_EVENTS choices on that engine.
    """
    events = _load().get("events") or []
    if len(events) < MIN_EVENTS:
        return {}
    now = time.time()
    adj = dict(_rules(events, now))
    bias, _ = factor_bias(events, now)
    for k, mult in bias.items():           # fold the factor layer in multiplicatively
        adj[k] = adj.get(k, 1.0) * mult
    if engine:
        for k, mult in engine_refinement(events, engine, now).items():
            adj[k] = adj.get(k, 1.0) * mult
    lab = _lab()
    if lab:                        # the trained model's slice, while one is active
        for k, mult in lab.blend().items():
            adj[k] = adj.get(k, 1.0) * mult
    return {k: round(_clamp(v), 4) for k, v in adj.items()}


def engine_refinement(events, engine, now=None):
    """How this engine's kept cuts differ from the owner's taste overall.

    B2 and ProX produce different edits; after enough choices on one engine we can
    say whether this owner keeps, say, more laughs on that engine than on average,
    and push only that engine's weights. Needs MIN_ENGINE_EVENTS on that engine,
    and any single factor moves by at most MAX_ENGINE_DELTA (5%) at this layer.
    """
    if not engine:
        return {}
    mine = [e for e in events if e.get("engine") == engine]
    if len(mine) < MIN_ENGINE_EVENTS:
        return {}
    base = _rules(events, now)
    own = _rules(mine, now)
    if not own:
        return {}
    out = {}
    for k, mult in own.items():
        delta = mult - base.get(k, 1.0)
        if abs(delta) < 1e-9:
            continue
        out[k] = 1.0 + max(-MAX_ENGINE_DELTA, min(MAX_ENGINE_DELTA, delta))
    return out


def profile():
    """Everything the Connect screen shows — counts, shares, medians and the
    multipliers computed from real logged choices. No estimation, no invented
    numbers. Everything the card does not use is still true and inspectable."""
    events = _load().get("events") or []
    n = len(events)
    now = time.time()
    laugh, question = _shares(events)
    laugh_w = _wshare(events, "laugh_ending", now)
    question_w = _wshare(events, "question_hook", now)
    lengths = [e["duration"] for e in events if e.get("duration")]
    engines, kinds = {}, {}
    for e in events:
        if e.get("engine"):
            engines[e["engine"]] = engines.get(e["engine"], 0) + 1
        if e.get("kind"):
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    adj = adjustment()
    _, evidence = factor_bias(events, now)

    per_engine = {}
    for eng in sorted(engines):
        mine = [e for e in events if e.get("engine") == eng]
        ml, mq = _shares(mine)
        per_engine[eng] = {
            "name": ENGINE_NAMES.get(eng, eng),
            "events": len(mine),
            "min_events": MIN_ENGINE_EVENTS,
            "active": len(mine) >= MIN_ENGINE_EVENTS,
            "remaining": max(0, MIN_ENGINE_EVENTS - len(mine)),
            "laugh_ending": {"count": sum(1 for e in mine if e.get("laugh_ending")),
                             "share": round(ml, 3)},
            "question_hook": {"count": sum(1 for e in mine if e.get("question_hook")),
                              "share": round(mq, 3)},
            "median_length": round(_median([e["duration"] for e in mine
                                            if e.get("duration")]), 1),
            "lengths": [round(_wmedian(mine, now), 1)],
            "weights": {k: round(v, 4)
                        for k, v in adjustment(eng).items()},
            "refinement": {k: round(v, 4)
                           for k, v in engine_refinement(events, eng, now).items()},
        }

    out = {
        "version": STORE_VERSION,
        "events": n,
        "min_events": MIN_EVENTS,
        "active": n >= MIN_EVENTS,
        "remaining": max(0, MIN_EVENTS - n),
        "laugh_ending": {"count": sum(1 for e in events if e.get("laugh_ending")),
                         "share": round(laugh, 3),
                         "weighted_share": round(laugh_w, 3)},
        "question_hook": {"count": sum(1 for e in events if e.get("question_hook")),
                          "share": round(question, 3),
                          "weighted_share": round(question_w, 3)},
        "median_length": round(_median(lengths), 1),
        "longest": round(max(lengths), 1) if lengths else 0.0,
        "shortest": round(min(lengths), 1) if lengths else 0.0,
        "engines": engines,
        "kinds": kinds,
        "weights": {k: round(v, 4) for k, v in adj.items()},
        # the two deeper layers, exposed so the card can explain itself
        "half_life_days": HALF_LIFE_DAYS,
        "engine_min_events": MIN_ENGINE_EVENTS,
        "refinements": {eng: info["refinement"] for eng, info in per_engine.items()},
        "per_engine": per_engine,
        "factor_over_index": evidence,       # kept minus its own pool, 0-100 points
        "factor_min_events": MIN_POOL_EVENTS,
        "factor_choices": sum(1 for e in events if e.get("factors") and e.get("pool")),
        "override_share": round(_io_share(events), 3),
        "why": _why(events, adj, evidence, now),
        "last": events[-1]["t"] if events else None,
    }
    lab = _lab()
    if lab:
        out["model"] = lab.state()
    return out


def _why(events, adj, evidence, now):
    """Plain-language reasons, each one traceable to the numbers above it. Only
    emits a line for a nudge that is actually in effect."""
    if len(events) < MIN_EVENTS:
        return []
    out = []
    n = len(events)
    laughs = sum(1 for e in events if e.get("laugh_ending"))
    if "payoff" in adj:
        if adj["payoff"] > 1.0:
            out.append(f"payoff x{adj['payoff']:.2f}: {laughs} of {n} kept cuts end on a "
                       "measured laugh")
        else:
            out.append(f"payoff x{adj['payoff']:.2f}: only {laughs} of {n} kept cuts end "
                       "on a measured laugh")
    if "hook" in adj:
        q = sum(1 for e in events if e.get("question_hook"))
        if adj["hook"] > 1.0:
            out.append(f"hook x{adj['hook']:.2f}: {q} of {n} kept cuts open on a question")
        else:
            out.append(f"hook x{adj['hook']:.2f}: {q} of {n} kept cuts open on a question — "
                       "openings are not what you keep these cuts for")
    for k in ("pacing", "story"):
        if k in adj:
            out.append(f"{k} x{adj[k]:.2f}: the cuts you keep run a median of "
                       f"{_wmedian(events, now):.0f}s")
    for k, mean in sorted(evidence.items()):
        if abs(mean) >= MIN_FACTOR_DELTA:
            out.append(f"{k} {mean:+.0f} vs the pool mean: you keep cuts that measure "
                       f"{'above' if mean > 0 else 'below'} the candidates offered with them")
    return out
