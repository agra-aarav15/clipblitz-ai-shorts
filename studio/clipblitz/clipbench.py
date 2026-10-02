"""ClipBench - one board for the ranking claims this studio makes.

Every claim about "the model helps" is scored the same way, on the same evidence, with
the same rule:

  * CONTENDERS ARE SCORING FUNCTIONS over one complete vector. The shipped baselines
    (the engine's own measured factor mean, and the scout's measured feature mean) are
    always on the board; so is a fixed one-shot weight set that never learns - the
    shape of a ranker with no feedback loop - and, when one is active, the trained
    model's own function.
  * THE SPLIT IS THE ONE THE MODELS ARE JUDGED ON. Taste pairs come from the trainer's
    own chronological split (newest fifth held out); scout pairs come from the scout's
    own pair mining and the same fraction. Nothing is ever scored on a pair a fit could
    have seen, and no contender gets its own private split.
  * A TIE IS NOT A WIN, exactly as in trainer.rate(): a model earns its place by
    separating what the owner chose from what they did not. A constant scorer therefore
    scores zero here, which is why the coin-flip reference is reported as a number
    (0.5) rather than as a scorer.
  * NO EVIDENCE IS AN HONEST ANSWER. Below MIN_PAIRS a family reports "insufficient"
    with its real counts, and a contender with no active model reports None rather than
    a number that does not exist.

Offline and deterministic: it reads the install's own stores (`learning` events, the
trainer's active model, the scout's judgments and model) and writes one board plus one
log line. It never fits, never touches jobs.json, never reaches the network, and is
absent entirely when the lab is off (CB_LAB=0) or the board is switched off
(CB_CLIPBENCH=off).
"""

import json
import os
import time

from . import config, learning, scout, trainer

MAX_LOG = 200               # run lines kept in bench_log.json
MIN_PAIRS = 6               # below this a family says "insufficient", never a number

# A plausible fixed weight set over the six engine factors, chosen once and never
# updated: the shape of a ranker with no feedback loop. It is a declared stand-in, not a
# measurement of any specific product, and it is never tuned against the holdout.
ONESHOT_FACTOR_WEIGHTS = {"hook": 0.30, "story": 0.25, "payoff": 0.25,
                          "energy": 0.10, "pacing": 0.05, "event": 0.05}

# The same idea in the metadata space: reach and freshness dominate, the rest is a
# rounding error, and nothing here reads the owner's calls.
ONESHOT_FEATURE_WEIGHTS = {"velocity": 0.20, "reach": 0.50, "freshness": 0.30,
                           "duration_fit": 0.0, "title_signal": 0.0, "channel_fit": 0.0}

NOTE = ("Every contender is scored on the same chronologically held-out pairs; a tie is "
        "not a win, so a coin flip is 0.50 and a constant scorer is 0.00. The one-shot "
        "row is a fixed weight set that never learns - the shape of a ranker with no "
        "feedback loop - and it is allowed to win.")


def enabled():
    """The lab flag and this board's own switch, both off by default never - off by
    request. CB_LAB=0 removes the whole layer, CB_CLIPBENCH=off just this board."""
    if not config.CONFIG.get("lab"):
        return False
    mode = str(config.CONFIG.get("bench_mode") or "on").strip().lower()
    return mode not in ("0", "off", "false", "no")


def _path(name):
    return os.path.join(config.CONFIG["data_dir"], name)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _board():
    data = _read(_path("bench.json"))
    return data if isinstance(data, dict) else None


def _log():
    data = _read(_path("bench_log.json"))
    return data if isinstance(data, list) else []


# --------------------------------------------------------------------- the evidence

def _taste_pairs():
    """The trainer's own human pairs, split exactly as the trainer splits them:
    (train, hold, hold_n) of (kept_vec, alternative_vec, weight, t)."""
    return trainer._human_pairs(learning.events())          # noqa: SLF001 - one split, one truth


def _scout_pairs():
    """The scout's own mined pairs, split by the same holdout fraction its fit uses:
    (train, hold) of (make_vec, pass_vec, weight, t)."""
    data = scout._store()                                   # noqa: SLF001
    pairs = scout._pairs(data.get("judgments") or [])        # noqa: SLF001
    n = len(pairs)
    if not n:
        return [], [], 0
    hold_n = max(1, int(round(n * trainer.HOLDOUT_FRACTION)))
    return pairs[:n - hold_n], pairs[n - hold_n:], hold_n


# ------------------------------------------------------------------- the contenders

def _mean_score(vec):
    return sum(vec) / len(vec)


def _weights_score(vec, names, weights):
    return sum(float(weights.get(k) or 0.0) * vec[i] for i, k in enumerate(names))


def _model_score(vec, model, names):
    """The trained model's own ranking function: theta . (x / scale). None without an
    active model - a contender with no model is absent, not zero."""
    if not model:
        return None
    weights, scale = model.get("weights") or {}, model.get("scale") or {}
    try:
        out = 0.0
        for i, k in enumerate(names):
            s = float(scale.get(k) or 1.0) or 1.0
            out += float(weights[k]) * (float(vec[i]) / s)
        return out
    except (KeyError, TypeError, ValueError):
        return None


def _scout_model_score(vec):
    """The shipped scout rank score: the measured mean plus the gated model's shift."""
    base = _mean_score(vec)
    if not scout._model():                                  # noqa: SLF001
        return base
    return base + scout.model_adjust(vec)


def taste_contenders():
    """{name: scorer or None} over one complete factor vector. None = unavailable."""
    model = trainer._model()                                # noqa: SLF001
    return {
        "virality": _mean_score,
        "one-shot": lambda v: _weights_score(v, trainer.FEATURES, ONESHOT_FACTOR_WEIGHTS),
        "taste-model": (None if not model
                        else lambda v: _model_score(v, model, trainer.FEATURES)),
    }


def scout_contenders():
    """{name: scorer or None} over one complete metadata feature vector."""
    model = scout._model()                                  # noqa: SLF001
    return {
        "measured": _mean_score,
        "one-shot": lambda v: _weights_score(v, scout.FEATURES, ONESHOT_FEATURE_WEIGHTS),
        "scout-model": (None if not model else _scout_model_score),
    }


def _score(scorer, pairs):
    """Strict pairwise accuracy plus the tie count, or None without a scorer/pairs."""
    if scorer is None or not pairs:
        return None
    wins = ties = 0
    for win, lose, *_rest in pairs:
        try:
            d = float(scorer(win)) - float(scorer(lose))
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        if d > 0:
            wins += 1
        elif d == 0:
            ties += 1
    return {"accuracy": round(wins / len(pairs), 4), "wins": wins,
            "ties": ties, "pairs": len(pairs)}


def _family(train, hold, hold_n, contenders, baseline, challenger):
    """One row of the board: every contender scored on the same held-out pairs, and a
    verdict that is allowed to say the challenger lost."""
    scored = {}
    for name, scorer in contenders.items():
        scored[name] = {
            "holdout": _score(scorer, [(w, l) for w, l, *_ in hold]),
            "train": _score(scorer, [(w, l) for w, l, *_ in train]),
            "available": scorer is not None,
        }
    held = scored.get(challenger, {}).get("holdout")
    base = scored.get(baseline, {}).get("holdout")
    total = len(train) + len(hold)
    if held is None and base is not None and total >= MIN_PAIRS and hold_n:
        # the baseline scored but the challenger has nothing to score with: that is a
        # missing model, not missing evidence, and the two are reported differently
        status = "no-model"
        verdict = (f"{challenger} is not available: no active model yet, so this board "
                   f"scores the baselines only ({base['accuracy']:.2f} on {hold_n} "
                   f"held-out pair(s))")
    elif not hold_n or held is None or base is None:
        verdict = (f"insufficient evidence: {len(hold)} held-out pair(s) of {total}; "
                   f"needs at least {MIN_PAIRS} pairs and both rows available")
        status = "insufficient"
    else:
        diff = held["accuracy"] - base["accuracy"]
        status = "scored"
        if diff > 0:
            verdict = (f"{challenger} beats {baseline} by +{diff:.2f} on {hold_n} "
                       f"held-out pair(s) ({held['accuracy']:.2f} vs {base['accuracy']:.2f})")
        elif diff < 0:
            verdict = (f"{challenger} does not beat {baseline} on the held-out pairs "
                       f"({held['accuracy']:.2f} vs {base['accuracy']:.2f}) - no claim")
        else:
            verdict = (f"{challenger} and {baseline} are level on the held-out pairs "
                       f"({held['accuracy']:.2f} each)")
    return {
        "status": status,
        "pairs": len(train) + len(hold),
        "train_pairs": len(train),
        "holdout_pairs": hold_n,
        "baseline": baseline,
        "challenger": challenger,
        "contenders": scored,
        "chance": 0.5,
        "verdict": verdict,
    }


# ------------------------------------------------------------------------- the board

def run(reason="manual"):
    """One board. Appends exactly one line to bench_log.json and returns the board;
    it never writes a model and never changes a store it reads."""
    if not enabled():
        return {"enabled": False, "ran": False,
                "reason": "the scoreboard is off (CB_CLIPBENCH=off or CB_LAB=0)"}
    day = time.strftime("%Y-%m-%d")
    events = learning.events()
    taste_train, taste_hold, taste_hold_n = _taste_pairs()
    scout_train, scout_hold, scout_hold_n = _scout_pairs()

    families = {
        "taste": _family(taste_train, taste_hold, taste_hold_n, taste_contenders(),
                         "virality", "taste-model"),
        "scout": _family(scout_train, scout_hold, scout_hold_n, scout_contenders(),
                         "measured", "scout-model"),
    }
    families["taste"]["evidence"] = {
        "events": len(events),
        "machine_pairs": len(trainer._machine_pairs()),         # noqa: SLF001
        "min_fit_events": trainer.MIN_FIT_EVENTS,
        "model_active": bool(trainer._model()),                 # noqa: SLF001
    }
    families["scout"]["evidence"] = {
        "judgments": len(scout._store().get("judgments") or []),  # noqa: SLF001
        "min_judgments": scout.MIN_JUDGMENTS,
        "model_active": bool(scout._model()),                     # noqa: SLF001
    }
    board = {
        "enabled": True,
        "ran": True,
        "reason": reason,
        "day": day,
        "t": round(time.time(), 1),
        "version": max([r.get("version") or 0 for r in _log()] or [0]) + 1,
        "families": families,
        "note": NOTE,
    }
    _write(_path("bench.json"), board)
    log = _log()
    log.append({"day": day, "version": board["version"], "reason": reason,
                "taste": families["taste"]["contenders"]["taste-model"]["holdout"] and
                families["taste"]["contenders"]["taste-model"]["holdout"]["accuracy"],
                "scout": families["scout"]["contenders"]["scout-model"]["holdout"] and
                families["scout"]["contenders"]["scout-model"]["holdout"]["accuracy"],
                "verdicts": {k: v["verdict"] for k, v in families.items()}})
    _write(_path("bench_log.json"), log[-MAX_LOG:])
    return board


def state():
    """The card's payload: the last board (or an honest emptiness), the run count and
    the switch. Reads two small files; never scores anything."""
    board = _board()
    log = _log()
    out = {
        "enabled": enabled(),
        "runs": len(log),
        "last": {"day": board.get("day"), "version": board.get("version"),
                 "reason": board.get("reason")} if board else None,
        "board": board,
        "note": NOTE,
    }
    if not enabled():
        out["board"] = None
        out["next"] = "the scoreboard is off (CB_CLIPBENCH=off or CB_LAB=0)"
    elif not board:
        out["next"] = "no board yet - run it and it scores whatever this install has"
    else:
        out["next"] = "run again after more choices or judgments; nothing is cached"
    return out


def reset():
    """Forget the boards, not the models they measured."""
    for name in ("bench.json", "bench_log.json"):
        try:
            os.remove(_path(name))
        except OSError:
            pass
    return state()
