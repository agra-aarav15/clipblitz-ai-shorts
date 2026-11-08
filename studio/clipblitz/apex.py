"""APEX — the hook-first engine.

What makes this a different engine, not a re-skin of the ProX spine:

  * ProX v5 and B2 Pro X are STORY-first. They find a story arc and let it run 18-75s,
    trusting that a landing ending earns the watch. That is the right cut for a moment
    the viewer already wants — but it is not what stops a scroll.
  * APEX is RETENTION-first. It mines a different signal — sparks, not stories — and it
    wins or loses in the first two seconds. A spark is a spoken line that makes the
    next second mandatory: an open question, a hard number, a contrarian claim, a
    "you won't believe" hook. The cut is then the tightest window that lands that
    spark's payoff — 8-30s, never a scene.

  Three concrete differences from the story engines:

  1. SEEDING  — candidates come from spark_lines() (a deterministic curiosity scan of
     the transcript) merged with the measured peak moments, not from story arcs.
  2. SCORING  — a hook-first weight profile (hook + event dominate; a slow open is a
     real cost) plus a hook_open factor the story engines only use as a tiebreak.
  3. WINDOW   — the cut is built around the spark's payoff and capped short; the edge
     snap is the same honest sentence-edge rule, but the bounds target retention.

  Everything is deterministic measurement on the same inputs (transcript, energy,
  laughter, scene cuts). No AI is required; with a brain it still runs its own spark
  pass, then the shared judge verifies the final cut exactly like the other engines.
"""

import re

from . import virality as V

# The engine's own identity. These surface on the card and in the learning store so
# the taste model can learn APEX's cuts separately from the story engines'.
ENGINE_ID = "apex"
ENGINE_NAME = "APEX hook-first"

# Tight retention window: a hook clip lives or dies fast. Below 8s there is no payoff;
# past 30s it has become the story cut another engine already makes.
MIN_S = 8.0
MAX_S = 30.0

# Curiosity signals a hook can be built on. Weaker than the banned-hype list on
# purpose — these mark an OPENING that pulls, not content that is itself an ad.
QUESTION_OPENERS = ("how", "why", "what", "when", "who", "which", "did", "can",
                    "will", "is", "are", "would")
CLAIM_WORDS = ("never", "always", "worst", "best", "biggest", "secret", "truth",
               "nobody", "everyone", "actually", "really", "proved", "proves",
               "wrong", "mistake", "stop", "don't", "shouldn't", "can't")
CHALLENGE_PHRASES = ("you won't believe", "watch what happens", "wait for it",
                     "this changes", "i was wrong", "let me prove", "here's why",
                     "the truth about", "nobody talks about")


def _sentences(segments):
    """Flatten to sentence-level beats with text + bounds (same shape rank() uses)."""
    out = []
    for s in segments or []:
        t = (s.get("text") or "").strip()
        if t and s.get("end", 0) > s.get("start", 0):
            out.append({"start": s["start"], "end": s["end"], "text": t,
                        "words": s.get("words") or []})
    return out


def spark_lines(segments):
    """Score every sentence for its cold-open pull. Returns [{start,end,text,pull,kind}].

    Deterministic — reads the words, never the LLM. A spark is a line whose first few
    words force the next second; the pull score ranks them so the strongest sparks
    seed cuts first. A line can be a question, a hard claim, a challenge phrase, or
    carry a number/stat — the four reliable scroll-stoppers.
    """
    out = []
    for s in _sentences(segments):
        head = " ".join(w["word"] for w in s["words"][:12]) if s["words"] else s["text"][:90]
        low = head.lower().strip()
        if not low:
            continue
        # the banned hype class can never open a hook clip either — a greeting that
        # trips a curiosity marker ("everyone", "today") is still a greeting.
        if V._is_hype(s["text"]) or V._is_hype(head):
            continue
        pull, kind = 0.0, ""
        first = re.findall(r"[a-z']+", low)[:1] or [""]
        if "?" in head[:80] or first[0] in QUESTION_OPENERS:
            pull, kind = 1.0, "question"
        n_claim = sum(1 for w in re.findall(r"[a-z']+", low) if w in CLAIM_WORDS)
        if n_claim:
            pull, kind = max(pull, 0.55 + 0.15 * min(n_claim, 3)), "claim"
        if any(p in low for p in CHALLENGE_PHRASES):
            pull, kind = max(pull, 0.95), "challenge"
        if any(ch.isdigit() for ch in head[:26]):
            pull, kind = max(pull, 0.6), "number"
        # a spoken exclamation carries pull even without a curiosity marker
        if "!" in head and pull < 0.4:
            pull, kind = 0.4, "burst"
        if pull > 0:
            out.append({"start": s["start"], "end": s["end"], "text": s["text"],
                        "pull": round(pull, 3), "kind": kind})
    return out


def _payoff_end(segments, seed, limit=MAX_S):
    """The earliest sentence end that lands the spark's payoff, inside the window cap.

    A hook cut ends where the question answers / the claim lands — the first strong
    sentence boundary after a minimal beat, not the whole story's tail."""
    sents = _sentences(segments)
    best = None
    for s in sents:
        if s["end"] <= seed:
            continue
        span = s["end"] - seed
        if span < MIN_S:
            continue
        if span > limit:
            break
        # a clean sentence ending (punctuation) is a landing; prefer the tightest one
        if s["text"][-1:] in ".!?…":
            best = s["end"]
            break
        if best is None:
            best = s["end"]
    if best is None:
        best = seed + min(limit, 24.0)
    return min(best, seed + limit)


def _cold_bounds(segments, seed, duration):
    """The tight hook window around a spark: start just before the spark line, end at
    the payoff. Re-snap to sentence edges so the open never starts mid-word."""
    a = seed
    b = _payoff_end(segments, seed)
    if b - a < MIN_S:
        b = min(duration, a + MIN_S + 2)
    if b - a > MAX_S:
        b = a + MAX_S
    return a, b


def _hook_speed(c, segments):
    """0-1: how many seconds before the first high-pull line inside the cut. The whole
    point of the engine — a clip that makes you wait is a failure here, a virtue in a
    story engine."""
    sparks = spark_lines([{"start": c["start"], "end": c["end"],
                           "text": V._text_in(segments, c["start"], c["start"] + 6, 200),
                           "words": V._words_in(segments, c["start"], c["start"] + 6)}])
    if not sparks:
        return 0.0
    delay = max(0.0, sparks[0]["start"] - c["start"])
    return round(1.0 / (1.0 + delay / 1.5), 3)


def _burst_factor(segments, a, b):
    """0-1: density of strong spark lines inside the cut — a clip that keeps re-hooking
    holds better than one that hooks once then coasts."""
    sparks = spark_lines([s for s in _sentences(segments) if a <= s["start"] < b])
    if not sparks:
        return 0.0
    strong = sum(1 for s in sparks if s["pull"] >= 0.6)
    return round(min(1.0, 0.4 + 0.3 * strong), 3)


def _apex_weights():
    """The engine's own score blend. Hook and the measured peak dominate; story
    coherence is still a factor (a random clip is still random) but is not trusted to
    carry the ranking. The owner's own choices on this engine refine it via
    learning.adjustment('apex'), once that engine has enough of its own evidence."""
    try:
        from . import learning
        adj = learning.adjustment(ENGINE_ID)
    except Exception:
        adj = {}
    base = {"hook": 0.34, "story": 0.14, "payoff": 0.18, "energy": 0.16,
            "pacing": 0.12, "event": 0.06}
    if not adj:
        return base
    return {k: v * adj.get(k, 1.0) for k, v in base.items()}


def _score(c, segments, j):
    """Score one candidate: the hook-first blend + the shared measured factors."""
    w = _apex_weights()
    factors = {
        "hook": max(0.0, min(1.0, c.get("hook_speed", 0.0) * 0.6 +
                             V._score10(j.get("hook")) / 10.0 * 0.4)),
        "story": max(0.0, min(1.0, V._score10(j.get("coherence")) / 10.0)),
        "payoff": max(0.0, min(1.0, V._score10(j.get("payoff")) / 10.0)),
        "energy": c["measured"]["energy"],
        "pacing": c["measured"]["pacing"],
        "event": c["measured"].get("event", 0.0),
    }
    if c["measured"].get("tail_laugh", 0) > 0:
        factors["payoff"] = max(factors["payoff"], 0.35 + 0.65 * c["measured"]["tail_laugh"])
    blend = sum(w.get(k, 0.0) * v for k, v in factors.items())
    wsum = sum(w.get(k, 0.0) for k in factors) or 1.0
    score = int(round(30 + 69 * ((blend / wsum) ** 1.15)))
    if j.get("ends_abrupt"):
        score = min(score, 55)
    if not j.get("alone", True):
        score = min(score, 45)
    if factors["event"] >= 0.7:
        score = min(99, score + 4)
    c["factors"] = {k: int(round(v * 100)) for k, v in factors.items()}
    c["factors"]["laughter"] = int(round(c["measured"]["laughter"] * 100))
    c["score"] = max(1, min(99, score))
    c["verdict"] = (j.get("verdict") or "").strip()[:160]
    c["qc"] = "verified" if not V.judge_fail(j) else "unverified"
    c["reason"] = V._verdict_reason(j, c)
    return c


def rank(segments, duration, count=3, energy=None, laughs=None, scenes=None,
         cinema_marks=None, motion=None):
    """The APEX pass. Returns (moments, candidates, picker, content_type) — the same
    tuple the story engines return so the pipeline treats it identically.

    cinema_marks/motion are accepted for interface parity; APEX is a spoken-hook
    engine and does not re-time to shot boundaries, so it ignores them on purpose.
    """
    sents = _sentences(segments)
    if not sents:
        return V._even_windows(duration, count), [], "apex-windows", "other"

    # 1) seed: sparks (curiosity lines) + the video's measured peak moments, so a hook
    #    cut still lands the loudest event when no clever line is present.
    moments = V.mine_moments(segments, duration, energy, laughs, scenes)
    sparks = spark_lines(segments)
    seeds = sorted({round(s["start"], 2) for s in sparks if s["pull"] >= 0.5} |
                   {round(m["seed"], 2) for m in moments if m.get("heat", 0) > 0
                    or m.get("roar", 0) > 2})

    if not seeds:
        return V._even_windows(duration, count), [], "apex-windows", "other"

    # 2) draft candidates: one tight window per seed, deduped by near-identical start.
    cands = []
    seen = []
    for seed in seeds:
        a, b = _cold_bounds(segments, seed, duration)
        if any(abs(a - x) < 6 for x in seen):
            continue
        seen.append(a)
        cands.append({"start": round(a, 2), "end": round(b, 2),
                      "title": V._text_in(segments, a, b, 70),
                      "hook": V._text_in(segments, a, a + 6, 60),
                      "story_start": a})
    if not cands:
        return V._even_windows(duration, count), [], "apex-windows", "other"

    for c in cands:
        V.snap(c, segments, duration)
        # keep it tight after the snap (snap can stretch to a sentence edge)
        if c["end"] - c["start"] > MAX_S:
            c["end"] = round(c["start"] + MAX_S, 2)
        V.extend_through_laughter([c], laughs, duration, segments, max_ext=6.0)
        if c["end"] - c["start"] > MAX_S:
            c["end"] = round(c["start"] + MAX_S, 2)
    V.measure(cands, segments, energy, laughs, moments)

    # hook-speed + burst are the engine's own factors; fold them in before scoring.
    for c in cands:
        c["hook_speed"] = _hook_speed(c, segments)
        c["measured"]["burst"] = _burst_factor(segments, c["start"], c["end"])

    # 3) judge the strongest exactly like the other engines — the same QC gate.
    cands.sort(key=lambda c: -(0.5 * c.get("hook_speed", 0)
                               + 0.3 * c["measured"].get("event", 0)
                               + 0.2 * c["measured"]["energy"]))
    top_pool = cands[:max(count + 2, 5)]
    judgements = {}
    picker = "apex-hook"
    if V.has_brain():
        try:
            judgements = V.judge_cuts(top_pool, segments)
            picker = "apex-editor"
        except Exception:
            judgements = {}
    for i, c in enumerate(top_pool):
        if not isinstance(c, dict):
            continue
        j = judgements.get(i) or dict(V._OFFLINE_J,
                                      verdict="judge unavailable — measured factors only")
        _score(c, segments, j)
    top_pool = [c for c in top_pool if isinstance(c, dict)]
    top_pool.sort(key=lambda c: -c["score"])

    # 4) the podium: ending gate + spread + content dedupe — same honesty as rank().
    #    Hook cuts are short, so the spread is tighter than a story engine's: two good
    #    hooks can live closer together without being the same clip.
    passing = [c for c in top_pool if c.get("qc") == "verified"
               or c["measured"].get("tail_laugh", 0) >= 0.25]
    rest = [c for c in top_pool if c not in passing]
    picked, spread = [], max(18.0, 0.06 * duration)
    for pool in (passing, rest, top_pool):
        for c in pool:
            if len(picked) >= count:
                break
            if c in picked:
                continue
            if all(abs(c["start"] - p["start"]) > spread for p in picked) \
               and all(abs(c["start"] - p["start"]) > 8 for p in picked):
                picked.append(c)
        if len(picked) >= count:
            break
    for c in picked:
        c["selected"] = True
    return picked, top_pool[:10], picker, "other"


def rank_single(segments, duration, energy, start, end):
    """A manual APEX window — measured on the engine's own factors."""
    c = {"start": float(start), "end": float(end), "title": "Custom cut",
         "hook": "", "reason": "your manual selection"}
    V.snap(c, segments, duration)
    V.measure([c], segments, energy, None)
    c["hook_speed"] = _hook_speed(c, segments)
    c["measured"]["burst"] = _burst_factor(segments, c["start"], c["end"])
    j = dict(V._OFFLINE_J, verdict="manual cut — measured factors only")
    if V.has_brain():
        try:
            j = V.judge_cuts([c], segments)[0]
        except Exception:
            pass
    return _score(c, segments, j)
