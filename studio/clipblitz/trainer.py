"""The taste model: what this owner actually keeps, fit locally and only activated
when a held-out slice of real choices says it got better.

No cloud, no pip, no randomness. The model is a pairwise logistic ranker over the six
measured factors every candidate and clip already carries (hook, story, payoff,
energy, pacing, event). Two honest sources of evidence feed it:

  PRE-TRAIN   pairs mined from the judge verdicts the pipeline itself stored in
              data/jobs.json - inside one job, the higher-scored candidate versus a
              lower-scored one, when the judge separated them. A machine label is a
              prior (weight 0.35); it is not evidence about what the owner would keep.
  POST-TRAIN  pairs from the owner's own logged choices (post / render / custom /
              judge): the kept cut versus each sibling candidate it was chosen over.
              They carry their recency weight; a sibling-less v2 event falls back to
              the pool mean at half weight, because a mean is one weak comparator.

Every fit is a pure function of the store: weights start at zero, the gradient is
full-batch, the iteration order is the store order, and recency is measured against
the NEWEST logged choice - never the wall clock. The same store always fits the same
model.

The gate: the newest fifth of the human pairs is held out, the candidate is judged on
kept-beats-sibling there, and it replaces the active model only if it clears 0.55 and
strictly beats the incumbent on those same pairs. A rejected candidate is dropped,
the incumbent stays, and the attempt is one line in data/model_log.json:

    {"day": "...", "version": 3, "pairs": 187, "holdout": 0.66,
     "holdout_n": 32, "activated": true, "reason": "..."}

The active model only ever touches the ranking through learning.adjustment(), as a
+/-6% layer inside the existing +/-10% cap; the two engines' render paths are not
involved at all. CB_LAB=0 removes the whole layer: no siblings are stored, nothing
refits, learning.profile() carries no model block, and the studio is v4.1.0 again.
"""

import json
import math
import os
import time

from . import learning
from .config import CONFIG

FEATURES = ("hook", "story", "payoff", "energy", "pacing", "event")

MIN_FIT_EVENTS = 20        # no fit before this many real logged choices
REFIT_EVERY = 5            # one new fit attempt per this many further choices
ACTIVATE_RATE = 0.55       # a candidate must clear this on the held-out choices
HOLDOUT_FRACTION = 0.20    # newest slice of human pairs, held out chronologically
PRETRAIN_MARGIN = 5.0      # judge-score gap that makes one machine pair
PRETRAIN_PAIRS_PER_JOB = 24
MACHINE_WEIGHT = 0.35      # a judge verdict is a prior, not the owner's evidence
POOL_WEIGHT = 0.5          # a v2 event's pool mean is one weak comparator
MAX_HUMAN_PAIRS = 2000     # a fit stays bounded on a long-lived install
MAX_MACHINE_PAIRS = 600
ITERATIONS = 200           # full-batch steps; stops early once the step is tiny
LEARNING_RATE = 0.5
CONVERGED = 1e-6           # stop when no single coordinate moves more than this per step
L2 = 0.01
MODEL_DELTA = 0.06         # the model layer's own slice of the global cap


def enabled():
    """Is the lab on? CB_LAB=0 (or an explicit learning off) removes the whole layer."""
    if not CONFIG.get("lab", True):
        return False
    return str(CONFIG.get("learning_mode", "full")).lower() != "off"


def _path(name):
    return os.path.join(CONFIG["data_dir"], name)


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


def _vec(factors):
    """A complete measured factor vector, or None. A partial breakdown never trains
    the model: an imputed factor would be an invented measurement."""
    out = []
    for k in FEATURES:
        v = (factors or {}).get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        out.append(float(v))
    return out


def _recency(t, newest):
    """Half-life weighting against the newest logged choice, so a fit is a pure
    function of the store rather than of the clock."""
    age_days = max(0.0, (newest - float(t or 0.0)) / 86400.0)
    return math.pow(0.5, age_days / learning.HALF_LIFE_DAYS)


def _machine_pairs():
    """Within-job judge verdicts as pairs: the higher-scored candidate versus a
    lower-scored one, only when the judge separated them by PRETRAIN_MARGIN.
    Deterministic order: job-file order, then score desc, then window start."""
    jobs = _read(_path("jobs.json"))
    if not isinstance(jobs, list):
        return []
    pairs = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        rows = []
        for c in (j.get("candidates") or []):
            if not isinstance(c, dict):
                continue
            vec, score = _vec(c.get("factors")), c.get("score")
            if vec is None or not isinstance(score, (int, float)) or isinstance(score, bool):
                continue
            start = c.get("start")
            when = float(start) if isinstance(start, (int, float)) else 0.0
            rows.append((float(score), when, vec))
        rows.sort(key=lambda r: (-r[0], r[1]))
        made = 0
        for i in range(len(rows)):
            if made >= PRETRAIN_PAIRS_PER_JOB or len(pairs) >= MAX_MACHINE_PAIRS:
                break
            for k in range(i + 1, len(rows)):
                if rows[i][0] - rows[k][0] < PRETRAIN_MARGIN:
                    break
                pairs.append((rows[i][2], rows[k][2], MACHINE_WEIGHT))
                made += 1
                if made >= PRETRAIN_PAIRS_PER_JOB or len(pairs) >= MAX_MACHINE_PAIRS:
                    break
    return pairs


def _human_pairs(events):
    """The owner's real choices as (kept, alternative, weight, t) pairs, split
    chronologically into (train, holdout, holdout_n). The newest fifth is held out;
    a fit that never saw the newest choices cannot be judged on a memory of them."""
    newest = max([float(e.get("t") or 0.0) for e in events] or [0.0])
    pairs = []
    for e in events:
        kept = _vec(e.get("factors"))
        if kept is None:
            continue
        t = float(e.get("t") or 0.0)
        w = _recency(t, newest)
        seen = 0
        for s in (e.get("sib") or []):
            sib = _vec((s or {}).get("factors"))
            if sib is None:
                continue
            pairs.append((kept, sib, w, t))
            seen += 1
        if not seen:
            pool = _vec(e.get("pool"))
            if pool is not None:
                pairs.append((kept, pool, w * POOL_WEIGHT, t))
    pairs = pairs[-MAX_HUMAN_PAIRS:]
    n = len(pairs)
    hold_n = max(1, int(round(n * HOLDOUT_FRACTION))) if n else 0
    return pairs[:n - hold_n], pairs[n - hold_n:], hold_n


def _sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _fit(pairs):
    """Deterministic full-batch pairwise logistic fit.

    The loss is  sum(w * log(1 + exp(-(s(kept) - s(other))))) + L2 * ||theta||^2 ,
    minimised from a zero start by fixed-step gradient descent. Features are scaled
    by their spread across the TRAINING pairs only (never the holdout), and because
    a pairwise difference cancels the mean, the fit has no clock and no randomness:
    the same store always produces the same theta. Returns (theta, scale) or None.
    """
    if not pairs:
        return None
    n = len(pairs)
    var = [0.0] * len(FEATURES)
    for pair in pairs:                       # (kept, alternative, weight[, t]) pairs
        win, lose = pair[0], pair[1]
        for k in range(len(FEATURES)):
            d = win[k] - lose[k]
            var[k] += d * d
    scale = [math.sqrt(v / n) if v > 1e-12 else 1.0 for v in var]
    diffs = [tuple((p[0][k] - p[1][k]) / scale[k] for k in range(len(FEATURES)))
             for p in pairs]
    theta = [0.0] * len(FEATURES)
    inv_n = 1.0 / n
    for _step in range(ITERATIONS):
        g0 = g1 = g2 = g3 = g4 = g5 = 0.0
        for pair, diff in zip(pairs, diffs):
            # unrolled over the six factors: the same arithmetic as the loop, fast
            # enough that an inline refit stays well under a second at full store
            d = (theta[0] * diff[0] + theta[1] * diff[1] + theta[2] * diff[2]
                 + theta[3] * diff[3] + theta[4] * diff[4] + theta[5] * diff[5])
            share = pair[2] * (_sigmoid(d) - 1.0)
            g0 += share * diff[0]
            g1 += share * diff[1]
            g2 += share * diff[2]
            g3 += share * diff[3]
            g4 += share * diff[4]
            g5 += share * diff[5]
        biggest = 0.0
        for k, g in enumerate((g0, g1, g2, g3, g4, g5)):
            step = LEARNING_RATE * (g * inv_n + L2 * theta[k])
            theta[k] -= step
            if abs(step) > biggest:
                biggest = abs(step)
        if biggest < CONVERGED:
            break
    return theta, scale


def _rate(theta, scale, pairs):
    """Strict kept-beats-sibling rate on these pairs: a tie is not a win, because the
    model only earns its place by actually separating the kept cut from the rest."""
    if not pairs:
        return None
    wins = 0
    for win, lose, *_rest in pairs:
        d = sum(theta[k] * (win[k] - lose[k]) / scale[k] for k in range(len(FEATURES)))
        if d > 0:
            wins += 1
    return wins / len(pairs)


def _decide(cand_rate, inc_rate, hold_n):
    """The activation gate as one function: evidence first, incumbent second."""
    if not hold_n or cand_rate is None:
        return False, "no held-out choices yet - a machine prior alone never moves the ranking"
    if cand_rate < ACTIVATE_RATE:
        return False, (f"held-out kept-beats-sibling {cand_rate:.2f} is below "
                       f"{ACTIVATE_RATE:.2f}")
    if inc_rate is not None and cand_rate <= inc_rate:
        return False, (f"new model {cand_rate:.2f} did not beat the active model's "
                       f"{inc_rate:.2f}")
    if inc_rate is None:
        return True, (f"first model activated: kept-beats-sibling {cand_rate:.2f} on "
                      f"{hold_n} held-out choice pair(s)")
    return True, (f"replaced the active model: {cand_rate:.2f} beats {inc_rate:.2f} on "
                  f"{hold_n} held-out choice pair(s)")


def _model():
    data = _read(_path("model.json"))
    if isinstance(data, dict) and data.get("active"):
        return data
    return None


def _fits():
    data = _read(_path("model_log.json"))
    return data if isinstance(data, list) else []


def blend():
    """{factor: multiplier} for the active model, or {} when none is active.

    The strongest coefficient keeps the full +/-MODEL_DELTA slice and the rest are
    scaled against it, so the layer can never exceed its cap no matter how many
    factors the model uses. Positive coefficients raise a factor (the owner keeps
    cuts that measure above the alternatives); negative ones lower it.
    """
    m = _model()
    if not m:
        return {}
    weights = m.get("weights") or {}
    top = max([abs(v) for v in weights.values() if isinstance(v, (int, float))] or [0.0])
    if top <= 0:
        return {}
    return {k: round(1.0 + MODEL_DELTA * (float(v) / top), 4)
            for k, v in weights.items()
            if isinstance(v, (int, float)) and k in FEATURES}


def run_fit(reason="manual"):
    """One fit attempt. Appends exactly one record line to model_log.json and returns
    it; on a win it also replaces model.json. A rejected candidate leaves the active
    model exactly as it was."""
    if not enabled():
        return {"enabled": False, "attempted": False, "activated": False,
                "reason": "the learning lab is off (CB_LAB=0)"}
    events = learning.events()
    machine = _machine_pairs()
    human_train, hold, hold_n = _human_pairs(events)
    train = machine + human_train
    day = time.strftime("%Y-%m-%d")
    if not train and not hold:
        return {"enabled": True, "attempted": False, "activated": False, "day": day,
                "reason": "nothing to fit yet: no logged choices and no judged candidates"}

    fitted = _fit(train)
    record = {
        "day": day,
        "version": max([r.get("version") or 0 for r in _fits()] or [0]) + 1,
        "events": len(events),
        "pairs": len(train),
        "machine_pairs": len(machine),
        "human_pairs": len(human_train),
        "holdout": None,
        "holdout_n": 0,
        "activated": False,
        "reason": "",
    }
    if fitted is None:
        record["reason"] = "no complete factor pairs to learn from yet"
        activated, why = False, record["reason"]
        theta = scale = None
    else:
        theta, scale = fitted
        cand_rate = _rate(theta, scale, [(w, l) for w, l, *_ in hold])
        record["holdout"] = round(cand_rate, 4) if cand_rate is not None else None
        record["holdout_n"] = hold_n
        incumbent = _model()
        inc_rate = None
        if incumbent and hold:
            iw, isc = incumbent.get("weights") or {}, incumbent.get("scale") or {}
            try:
                inc_rate = _rate([float(iw[k]) for k in FEATURES],
                                 [float(isc[k]) for k in FEATURES],
                                 [(w, l) for w, l, *_ in hold])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                inc_rate = None
        activated, why = _decide(cand_rate, inc_rate, hold_n)
        record["activated"] = bool(activated)
        record["reason"] = why
    if activated:
        model = {
            "version": record["version"], "active": True, "day": day,
            "t": round(time.time(), 1),
            "weights": {k: round(theta[i], 6) for i, k in enumerate(FEATURES)},
            "scale": {k: round(scale[i], 4) for i, k in enumerate(FEATURES)},
            "holdout": record["holdout"], "holdout_n": record["holdout_n"],
            "train_pairs": len(train), "machine_pairs": len(machine),
            "human_pairs": len(human_train),
            "note": ("A local pairwise ranker over the measured factors, fit from this "
                     "install's own judge history and real choices. It nudges ranking "
                     "weights by at most 6% per factor, reproducible from the store."),
        }
        _write(_path("model.json"), model)
    fits = _fits()
    fits.append(record)
    _write(_path("model_log.json"), fits[-200:])
    out = dict(record)
    out.update({"enabled": True, "attempted": True, "trigger": reason})
    return out


def auto_fit():
    """The day-by-day cadence: refit after every REFIT_EVERY further real choices,
    once MIN_FIT_EVENTS exist. Cheap when it does nothing; absent when the lab is off."""
    if not enabled():
        return None
    events = learning.events()
    if len(events) < MIN_FIT_EVENTS:
        return None
    fits = _fits()
    since = len(events) - ((fits[-1].get("events") or 0) if fits else 0)
    if since < REFIT_EVERY:
        return None
    return run_fit(reason="cadence")


def state():
    """The model block for learning.profile() / the learning_state tool. Reads two
    small files and counts the store; it never refits and never touches jobs.json."""
    fits = _fits()
    model = _model()
    count = len(learning.events())
    last = fits[-1] if fits else None
    since = count - (last.get("events") or 0) if last else count
    if count < MIN_FIT_EVENTS:
        remaining, waiting_for = MIN_FIT_EVENTS - count, "choices"
    elif since < REFIT_EVERY:
        remaining, waiting_for = REFIT_EVERY - since, "choices"
    else:
        remaining, waiting_for = 0, "the next choice"
    return {
        "enabled": True,
        "active": bool(model),
        "version": (model or {}).get("version"),
        "trained": (model or {}).get("day"),
        "holdout": (model or {}).get("holdout"),
        "holdout_n": (model or {}).get("holdout_n"),
        "weights": (model or {}).get("weights") or {},
        "multipliers": blend(),
        "events": count,
        "min_events": MIN_FIT_EVENTS,
        "refit_every": REFIT_EVERY,
        "remaining": remaining,
        "waiting_for": waiting_for,
        "fits": [{k: r.get(k) for k in ("day", "version", "pairs", "holdout",
                                        "activated", "reason")} for r in fits[-3:]],
        "note": ("A local pairwise ranker over the measured factors. It activates only "
                 "when the newest fifth of the owner's real choices says it ranks the "
                 "kept cut above the candidates it beat, at 0.55 or better; it only "
                 "ever moves ranking weights, never a render."),
    }


def reset():
    """Forget the model with the choices that trained it."""
    for path in (_path("model.json"), _path("model_log.json")):
        try:
            os.remove(path)
        except OSError:
            pass
