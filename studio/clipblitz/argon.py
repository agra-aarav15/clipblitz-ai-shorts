"""ARGON - one editorial engine that replaces the three older cut modes.

Why this exists
---------------
ProX v5 is story-first, B2 Pro X is cinema-first, APEX is hook-first. Each is good at
one thing and blind to the other two. ARGON does not pick a side: it builds a
candidate graph from every reliable signal (spoken hooks, story arcs, measured peaks,
shot boundaries, motion) and lets a multi-objective editor choose the best window.

The design is deliberately honest:

  * Every number is a measurement or a judge rating. Nothing is invented.
  * Deterministic passes run the same on every machine and with no API key.
  * The LLM is used where it is genuinely better than arithmetic: mapping stories,
    judging the exact final transcript, and flagging editorial failure modes.
  * The LLM never chooses a window by itself. It may only approve, reject, or name a
    defect; every repair is deterministic, re-measured, and re-judged.
  * No engine here tries to evade content matching. Rights stay in rights.py.

Pipeline
--------
  transcript + energy + laughter + scenes + motion
       |
       v
  ANCHOR GRAPH  sparks | story arcs | peak moments | cinematic beats
       |
       v
  MULTI-SCALE WINDOWS  sentence-aligned starts/ends, 10-75s, laugh extension
       |
       v
  DETERMINISTIC MEASUREMENT  13 editorial features per candidate
       |
       v
  RETENTION JUDGE + ADVERSARIAL FLAGS (LLM when present, honest fallback when not)
       |
       v
  REPAIR LOOP (deterministic first, then one re-judge)
       |
       v
  GATED SCORE + MMR DIVERSITY -> podium + candidate lab
"""

import json
import math
import re

from . import virality as V
from .brains import ai_chat
from .config import CONFIG

ENGINE_ID = "argon"
ENGINE_NAME = "ARGON unified"

# A short is not a scene and not a blink. The band is wide on purpose: the window
# optimizer chooses the length the story actually needs, not a fixed one.
MIN_S = 10.0
MAX_S = 75.0
TARGET_S = (12.0, 16.0, 22.0, 30.0, 42.0, 58.0)

MAX_CANDIDATES = 96          # bounded work on a long episode
MAX_JUDGE = 14               # candidates the judge sees in one run
MAX_REPAIR = 8               # candidates repaired in one run
MAX_SPEAK_CHARS = 2600       # transcript sent per judge candidate, capped

# The six factors the learning store/trainer already understand, plus the ARGON
# features shown on the card. Keep the first six names stable: changing them would
# silently stop the local taste model from learning.
CORE_FACTORS = ("hook", "story", "payoff", "energy", "pacing", "event")
EXTRA_FACTORS = ("emotion", "novelty", "visual", "self_sufficient", "loop",
                 "clarity", "shareability", "open_loop", "context_dependency",
                 "failure_risk")
FEATURES = CORE_FACTORS + EXTRA_FACTORS

FILLERS = V.FILLER_STARTS

QUESTION_WORDS = ("how", "why", "what", "when", "who", "which", "did", "can",
                  "will", "is", "are", "would", "could", "should", "do", "does")

CLAIM_WORDS = ("never", "always", "worst", "best", "biggest", "secret", "truth",
               "nobody", "everyone", "actually", "really", "proved", "proves",
               "wrong", "mistake", "stop", "don't", "shouldn't", "can't", "impossible",
               "changed", "changes", "ruined", "ruins", "exposed", "banned")

CHALLENGE_PHRASES = ("you won't believe", "watch what happens", "wait for it",
                     "this changes", "i was wrong", "let me prove", "here's why",
                     "the truth about", "nobody talks about", "the reason why",
                     "what nobody tells you", "this is why")

STAKES_WORDS = ("money", "million", "billion", "career", "life", "death", "win",
                "lose", "lost", "won", "champion", "record", "banned", "fired",
                "caught", "secret", "exposed", "risk", "danger", "safe", "free")

EMOTION_WORDS = ("love", "hate", "shocked", "insane", "crazy", "unbelievable",
                 "amazing", "terrible", "afraid", "scared", "angry", "proud",
                 "cried", "laughed", "died", "won", "lost", "best", "worst")

SHARE_WORDS = ("everyone", "nobody", "never", "always", "best", "worst", "first",
               "last", "only", "biggest", "fastest", "secret", "truth", "proof",
               "mistake", "wrong", "banned", "record", "million", "billion")

RESOLUTION_WORDS = ("so that's why", "that's why", "the lesson", "turns out",
                    "which means", "and that changed", "the point is", "in the end",
                    "finally", "it worked", "it failed", "the result", "the truth is")

# A dependent opening is the most common reason a clip fails on its own. These are
# references to something outside the window, not a style judgement.
DEICTIC_OPENERS = ("he ", "she ", "they ", "it ", "this ", "that ", "these ",
                   "those ", "as i mentioned", "like i said", "going back to",
                   "the second one", "the first one", "the next one", "earlier",
                   "that guy", "that thing", "that part", "the other one")

VISUAL_DEICTICS = ("look at this", "look at that", "right here", "on screen",
                   "this chart", "this slide", "this graph", "the red line",
                   "over here", "as you can see", "watch this", "this image")

ORDINAL_WORDS = ("first", "second", "third", "fourth", "finally", "lastly")

# A flag is a concrete editorial defect, not a vibe. Fatal flags cannot fill the
# podium; warning flags lower the score and trigger a deterministic repair attempt.
FATAL_FLAGS = {"starts_mid_thought", "ends_before_payoff", "no_payoff",
               "confusing_context", "inside_joke", "not_standalone", "spoiler",
               "misleading", "empty"}
WARNING_FLAGS = {"weak_hook", "low_energy", "repetitive", "context_dependent",
                 "slow_open", "weak_ending", "too_long", "filler_open",
                 "screen_dependent", "list_incomplete"}

# ARGON's own blend. The story engines weight payoff above all; ARGON keeps payoff
# important but treats hook and story as first-class because retention is decided in
# the first seconds and comprehension is decided by the story. Profiles shift the
# shape by content type without ever zeroing a signal.
BASE_WEIGHTS = {
    "hook": 0.20, "story": 0.16, "payoff": 0.18, "emotion": 0.10,
    "energy": 0.07, "pacing": 0.06, "event": 0.06, "novelty": 0.04,
    "visual": 0.04, "self_sufficient": 0.06, "loop": 0.02,
    "clarity": 0.04, "shareability": 0.04, "open_loop": 0.03,
}
PROFILE_MULT = {
    "comedy": {"payoff": 1.15, "emotion": 1.20, "story": 0.95, "visual": 0.85},
    "podcast": {"story": 1.08, "hook": 1.05, "visual": 0.75},
    "interview": {"story": 1.08, "clarity": 1.12, "visual": 0.80},
    "speech": {"hook": 1.15, "story": 1.05, "visual": 0.70},
    "tutorial": {"clarity": 1.20, "story": 1.12, "shareability": 1.10, "visual": 0.85},
    "vlog": {"visual": 1.08, "emotion": 1.08, "story": 0.95},
    "sports": {"event": 1.35, "visual": 1.25, "story": 0.80, "hook": 0.95},
}


def _weights(content_type=None):
    """The blend for a content type, multiplied by whatever the local taste model has
    learned. The learning layer is optional and returns {} until it has evidence."""
    prof = dict(BASE_WEIGHTS)
    mult = PROFILE_MULT.get((content_type or "").lower(), {})
    for k, m in mult.items():
        prof[k] = prof.get(k, 0.0) * m
    try:
        from . import learning
        adj = learning.adjustment(ENGINE_ID)
    except Exception:
        adj = {}
    if adj:
        prof = {k: v * adj.get(k, 1.0) for k, v in prof.items()}
    return prof


def has_brain():
    """A key pasted in the UI works on the next job; never cache the import-time state."""
    try:
        from .brains import brains
        return bool(brains())
    except Exception:
        return False


# ---------------------------------------------------------------- text helpers

def _sentences(segments):
    out = []
    for s in segments or []:
        text = (s.get("text") or "").strip()
        if text and s.get("end", 0) > s.get("start", 0):
            out.append({"start": float(s["start"]), "end": float(s["end"]),
                        "text": text, "words": s.get("words") or []})
    return out


def _head(sent, n=14):
    if sent.get("words"):
        return " ".join(str(w.get("word") or "") for w in sent["words"][:n]).strip()
    return " ".join(sent["text"].split()[:n])


def _norm(text):
    return " ".join((text or "").lower().split())


def _pull(text):
    """Return (0..1 pull, kind) for a spoken opening. Deterministic, no LLM.

    The four reliable scroll-stoppers are a question, a hard number, a contrarian
    claim, and a challenge line. A greeting can contain 'everyone' and still be a
    greeting, so the hype filter runs first.
    """
    low = _norm(text)
    if not low:
        return 0.0, ""
    if V._is_hype(low):
        return 0.0, ""
    words = re.findall(r"[a-z']+", low)
    first = words[0] if words else ""
    pull, kind = 0.0, ""
    if "?" in low[:90] or first in QUESTION_WORDS:
        pull, kind = 0.92, "question"
    if any(p in low for p in CHALLENGE_PHRASES):
        pull, kind = max(pull, 1.0), "challenge"
    numbers = sum(1 for ch in low[:36] if ch.isdigit())
    number_words = len(set(re.findall(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|"
        r"million|billion|percent|half|double|triple)\b", low)))
    if numbers or number_words:
        pull, kind = max(pull, 0.66 + min(0.12, (numbers + number_words) * 0.04)), "number"
    claims = sum(1 for w in words if w in CLAIM_WORDS)
    if claims:
        pull, kind = max(pull, 0.58 + 0.12 * min(claims, 3)), "claim"
    stakes = sum(1 for w in words if w in STAKES_WORDS)
    if stakes >= 2:
        pull, kind = max(pull, 0.55), "stakes"
    if " but " in f" {low} " or low.startswith(("actually", "turns out", "the truth")):
        pull, kind = max(pull, 0.52), "contrast"
    if "!" in low and pull < 0.45:
        pull, kind = 0.42, "burst"
    return round(min(1.0, pull), 3), kind


def spark_scan(segments):
    """Every sentence that can open a scroll-stopping cut, ranked by its pull."""
    out = []
    for s in _sentences(segments):
        head = _head(s)
        pull, kind = _pull(head)
        if pull <= 0:
            continue
        out.append({"start": s["start"], "end": s["end"], "text": s["text"],
                    "head": head, "pull": pull, "kind": kind})
    return out


def _question_at_start(segments, a, width=6.0):
    text = V._text_in(segments, a, a + width, 240)
    return "?" in text[:120] or bool(re.match(
        r"^\s*(how|why|what|when|who|which|did|can|will|is|are|would|could|should)\b",
        text or "", re.I))


def _has_final_punctuation(text):
    return bool(re.search(r"[.!?…]\s*$", (text or "").strip()))


def _word_count(segments, a, b):
    return len(V._words_in(segments, a, b))


def _filler_ratio(segments, a, b):
    words = [str(w.get("word") or "").strip(".,!?…").lower()
             for w in V._words_in(segments, a, b)]
    if not words:
        return 1.0
    return sum(1 for w in words if w in FILLERS) / len(words)


def _lexical_novelty(text):
    words = [w for w in re.findall(r"[a-z']+", (text or "").lower())
             if len(w) > 2 and w not in V.STOP_WORDS]
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _shareability(text):
    low = _norm(text)
    words = set(re.findall(r"[a-z']+", low))
    score = 0.0
    if any(ch.isdigit() for ch in low[:90]):
        score += 0.28
    score += 0.24 * min(1.0, len(words & set(SHARE_WORDS)) / 3.0)
    score += 0.20 * min(1.0, len(words & set(CLAIM_WORDS)) / 3.0)
    if "?" in low[:90]:
        score += 0.12
    if "!" in low:
        score += 0.08
    return min(1.0, score)


def _emotion(text):
    low = _norm(text)
    words = set(re.findall(r"[a-z']+", low))
    hits = len(words & set(EMOTION_WORDS))
    return min(1.0, 0.20 + 0.18 * hits + (0.12 if "!" in low else 0.0))


def _resolution(text):
    low = _norm(text)
    return min(1.0, sum(1 for p in RESOLUTION_WORDS if p in low) * 0.34)


def _context_dependency(text):
    """Openings that require something outside the window. Low is better."""
    low = _norm(text)
    score = 0.0
    for p in DEICTIC_OPENERS:
        if low.startswith(p):
            score += 0.35
            break
    if any(p in low for p in VISUAL_DEICTICS):
        score += 0.35
    # A pronoun within the first eight words is a real risk, not proof; the judge
    # makes the final call. This is a measured warning signal.
    first = re.findall(r"[a-z']+", low)[:8]
    if any(w in ("he", "she", "they", "it", "this", "that", "these", "those")
           for w in first):
        score += 0.20
    return min(1.0, score)


def _list_incomplete(text):
    """A clip that says 'three rules' and only contains one is not complete."""
    low = _norm(text)
    m = re.search(r"\b(two|three|four|five|2|3|4|5)\s+"
                  r"(things|rules|ways|reasons|mistakes|steps|tips|lessons)\b", low)
    if not m:
        return 0.0
    words = set(re.findall(r"[a-z']+", low))
    ordinals = len(words & set(ORDINAL_WORDS))
    wants = {"two": 2, "2": 2, "three": 3, "3": 3, "four": 4,
             "4": 4, "five": 5, "5": 5}[m.group(1)]
    return max(0.0, min(1.0, 1.0 - ordinals / max(1, wants - 1)))


def _motion_stats(motion, a, b):
    vals = [float(v) for t, v in (motion or []) if a <= float(t) <= b]
    if not vals:
        return 0.0, 0.0
    return sum(vals) / len(vals), max(vals)


def _scene_time(value):
    """Scene marks arrive in three shapes: a float from ffmpeg_tools.scene_cuts, a
    (time, score) tuple from cinema.scene_map, or a dict from a stored job. Normalise
    once here; every downstream feature gets a plain float."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, (tuple, list)) and value:
            return float(value[0])
        if isinstance(value, dict):
            for key in ("time", "t", "start", "timestamp"):
                if value.get(key) is not None:
                    return float(value[key])
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _scene_times(scenes):
    out = []
    for value in scenes or []:
        t = _scene_time(value)
        if t is not None:
            out.append(round(t, 3))
    return sorted(set(out))


def _scene_count(scenes, a, b):
    return sum(1 for t in _scene_times(scenes) if a < t < b)


# ---------------------------------------------------------------- measurement

def measure_candidate(c, segments, energy, laughs, moments, scenes=None, motion=None):
    """Measure one candidate. Everything here is deterministic.

    The six core factors are exactly the names the local learning store/trainer
    already consume; the extra ARGON factors are shown on the card and used by the
    score, but are not silently fed into models that expect a six-dimensional vector.
    """
    V.measure([c], segments, energy, laughs, moments)
    a, b = c["start"], c["end"]
    text = V._text_in(segments, a, b, 2400)
    head = V._text_in(segments, a, a + 6.0, 320)
    tail = V._text_in(segments, max(a, b - 6.0), b + 0.5, 320)
    dur = max(0.1, b - a)
    n_words = _word_count(segments, a, b)
    wps = n_words / dur if n_words else 0.0
    filler = _filler_ratio(segments, a, b)
    pull, kind = _pull(head)
    question = _question_at_start(segments, a)
    ends_final = _has_final_punctuation(tail)
    starts_clean = not V._starts_on_filler(segments, a)
    energy_f = c["measured"]["energy"]
    laugh_f = c["measured"]["laughter"]
    tail_laugh = c["measured"].get("tail_laugh", 0.0)
    event_f = c["measured"].get("event", 0.0)
    mean_motion, peak_motion = _motion_stats(motion, a, b)
    cuts = _scene_count(scenes, a, b)
    context = _context_dependency(head)
    list_gap = _list_incomplete(text)

    feat = {
        "hook": min(1.0, 0.60 * pull + 0.24 * energy_f
                    + 0.16 * (1.0 if question else 0.0)),
        "story": min(1.0, 0.42 * (1.0 if starts_clean and ends_final else 0.55)
                     + 0.20 * (1.0 - filler) + 0.20 * min(1.0, dur / 35.0)
                     + 0.18 * (1.0 - list_gap)),
        "payoff": min(1.0, 0.48 * tail_laugh + 0.22 * (1.0 if ends_final else 0.0)
                      + 0.16 * laugh_f + 0.14 * _resolution(tail)),
        "energy": max(0.0, min(1.0, energy_f)),
        "pacing": max(0.0, min(1.0, c["measured"]["pacing"])),
        "event": max(0.0, min(1.0, event_f)),
        "emotion": min(1.0, 0.45 * _emotion(text) + 0.35 * laugh_f + 0.20 * tail_laugh),
        "novelty": max(0.0, min(1.0, _lexical_novelty(text))),
        "visual": max(0.0, min(1.0, 0.55 * mean_motion + 0.30 * peak_motion
                                + 0.15 * min(1.0, cuts / 2.0))),
        "self_sufficient": max(0.0, min(1.0, 0.36 * (1.0 if starts_clean else 0.0)
                                        + 0.30 * (1.0 if ends_final else 0.0)
                                        + 0.20 * min(1.0, n_words / 45.0)
                                        + 0.14 * (1.0 - context))),
        "loop": max(0.0, min(1.0, 0.40 * (1.0 if question else 0.0)
                             + 0.30 * (1.0 if ends_final else 0.0)
                             + 0.30 * (1.0 if question and tail_laugh >= 0.2 else 0.0))),
        "clarity": max(0.0, min(1.0, 0.50 * (1.0 - filler)
                                + 0.25 * (1.0 if starts_clean else 0.0)
                                + 0.25 * (1.0 if ends_final else 0.0))),
        "shareability": _shareability(text),
        "open_loop": max(0.0, min(1.0, pull if kind in ("question", "challenge", "claim")
                                  else 0.20)),
        "context_dependency": context,
        "failure_risk": min(1.0, 0.55 * list_gap + 0.25 * context
                            + (0.20 if not ends_final else 0.0)),
    }
    c["argo_features"] = {k: round(max(0.0, min(1.0, v)), 3) for k, v in feat.items()}
    c["hook_speed"] = _hook_speed(c, segments)
    c["anchor_kind"] = c.get("anchor_kind") or "window"
    c["hook_kind"] = kind
    c["text_stats"] = {"words": n_words, "wps": round(wps, 2), "filler": round(filler, 3),
                       "starts_clean": starts_clean, "ends_final": ends_final,
                       "question_open": question, "scenes": cuts,
                       "context_dependency": round(context, 3),
                       "list_incomplete": round(list_gap, 3)}
    return c


def _hook_speed(c, segments):
    """0..1: how quickly the first high-pull line arrives inside the cut. A hook that
    makes the viewer wait is a cost, not a virtue."""
    sparks = spark_scan([{"start": c["start"], "end": c["end"],
                          "text": V._text_in(segments, c["start"], c["start"] + 6, 220),
                          "words": V._words_in(segments, c["start"], c["start"] + 6)}])
    if not sparks:
        return 0.0
    delay = max(0.0, sparks[0]["start"] - c["start"])
    return round(1.0 / (1.0 + delay / 1.2), 3)


# ---------------------------------------------------------------- anchors + windows

def _peak_anchors(moments, limit=10):
    out = []
    for m in sorted(moments or [], key=lambda x: -(x.get("heat", 0)
                                                   + x.get("roar", 0)
                                                   + 0.5 * x.get("cuts", 0)))[:limit]:
        out.append({"start": float(m.get("seed", m.get("start", 0.0))),
                    "end": float(m.get("end", m.get("start", 0.0))),
                    "kind": "peak", "priority": 1.0,
                    "label": "measured peak"})
    return out


def _story_anchors(stories, limit=14):
    out = []
    for st in (stories or [])[:limit]:
        if not isinstance(st, dict):
            continue
        out.append({"start": float(st.get("start", 0.0)),
                    "end": float(st.get("end", 0.0)),
                    "kind": "story", "priority": 0.9,
                    "story": st, "label": st.get("summary") or "story arc"})
    return out


def _payoff_anchors(segments, laughs, limit=10):
    """Backward-chained seeds: a laugh or a resolution line is a payoff. A window that
    ends there is more likely to land than one that merely starts on a clever line."""
    out = []
    for lstart, lend, peak in sorted(laughs or [], key=lambda x: -(x[2] if len(x) > 2 else 0))[:limit]:
        out.append({"start": float(lstart), "end": float(lend),
                    "kind": "payoff", "priority": 0.75 + 0.25 * min(1.0, float(peak or 0)),
                    "label": "laughter payoff"})
    for s in _sentences(segments):
        res = _resolution(s["text"])
        if res >= 0.34 or s["text"].rstrip().endswith("!"):
            out.append({"start": s["start"], "end": s["end"], "kind": "payoff",
                        "priority": 0.62 + 0.20 * res, "label": "resolution line"})
    return out[:limit]


def _spark_anchors(sparks, limit=18):
    out = []
    for s in sorted(sparks or [], key=lambda x: -x.get("pull", 0))[:limit]:
        if s.get("pull", 0) < 0.45:
            continue
        out.append({"start": float(s["start"]), "end": float(s["end"]),
                    "kind": "spark", "priority": 0.7 + 0.3 * s["pull"],
                    "spark": s, "label": s.get("kind") or "spoken hook"})
    return out


def _cinema_anchors(scenes, motion, duration, limit=8):
    """Shot boundaries, optionally weighted by on-screen motion. ARGON can run without
    the expensive motion map: scene cuts alone still give it real edit points."""
    shots = _scene_times(scenes)
    rows = []
    out = []
    if motion:
        for t, v in (motion or []):
            t = _scene_time(t)
            if t is None:
                continue
            if any(abs(t - s) <= 2.0 for s in shots):
                rows.append((float(v), t))
        rows.sort(reverse=True)
        for v, t in rows[:limit]:
            out.append({"start": t, "end": min(duration, t + 20.0),
                        "kind": "cinema", "priority": 0.55 + 0.35 * min(1.0, v),
                        "label": "shot + motion peak"})
    else:
        for t in shots[:limit]:
            out.append({"start": t, "end": min(duration, t + 20.0),
                        "kind": "cinema", "priority": 0.45,
                        "label": "shot boundary"})
    return out


def _nearest(items, value):
    if not items:
        return None
    return min(items, key=lambda x: abs(float(x) - value))


def _snap_to_scene(t, scenes, tol=1.8):
    shots = _scene_times(scenes)
    best = _nearest(shots, t)
    if best is None or abs(float(best) - t) > tol:
        return None
    return float(best)


def _enforce_window(c, segments, duration):
    """Keep a window inside the duration, on sentence edges, out of filler, and in the
    ARGON length band. Every candidate passes through this deterministic guard."""
    sents = _sentences(segments)
    if not sents:
        c["start"] = round(max(0.0, min(duration, c["start"])), 2)
        c["end"] = round(max(c["start"] + 1.0, min(duration, c["end"])), 2)
        return c
    starts = [s["start"] for s in sents]
    ends = [s["end"] for s in sents]
    c["start"] = _nearest(starts, c["start"])
    c["end"] = _nearest(ends, c["end"])
    if V._starts_on_filler(segments, c["start"]):
        non_filler = [s["start"] for s in sents
                      if s["start"] > c["start"]
                      and not V._starts_on_filler(segments, s["start"])]
        if non_filler:
            c["start"] = non_filler[0]
    if c["end"] - c["start"] < MIN_S:
        later = [e for e in ends if c["start"] + MIN_S <= e <= c["start"] + MAX_S]
        if later:
            c["end"] = later[0]
        else:
            # A tail that sits too close to the end of the video cannot be extended.
            # Move the start back to the latest sentence edge that still gives a real
            # clip; never emit a 3-second fragment no matter where the anchor sat.
            earlier = [s for s in starts if s <= c["end"] - MIN_S
                       and not V._starts_on_filler(segments, s)]
            if earlier:
                c["start"] = max(earlier)
            else:
                # A final beat that can only be reached through filler is not a clip.
                # Drop it rather than ship a fragment that opens on "and" or "so".
                c["_drop"] = True
    if c["end"] - c["start"] > MAX_S:
        inside = [e for e in ends if c["start"] + MIN_S <= e <= c["start"] + MAX_S]
        c["end"] = inside[-1] if inside else min(duration, c["start"] + MAX_S)
    c["start"] = round(max(0.0, min(duration, c["start"])), 2)
    c["end"] = round(max(c["start"] + 1.0, min(duration, c["end"])), 2)
    return c


def _window_candidates(anchor, segments, duration, laughs, scenes):
    """Every plausible sentence-aligned window around one anchor, at several lengths.
    This is the part the old engines skipped: they drafted one window per story and
    never explored the length/edge alternatives that often contain the better cut."""
    sents = _sentences(segments)
    if not sents:
        return []
    starts = [s["start"] for s in sents]
    ends = [s["end"] for s in sents]
    seed = anchor.get("start", 0.0)
    near = sorted([s for s in starts if seed - 26.0 <= s <= seed + 4.0],
                  key=lambda x: abs(x - seed))[:4]
    if not near:
        nearest = _nearest(starts, seed)
        near = [nearest] if nearest is not None else [0.0]
    if anchor.get("kind") == "story":
        near = sorted(set(near + [float(anchor["start"])]),
                      key=lambda x: abs(x - seed))[:5]

    out = []
    targets = list(TARGET_S)
    if anchor.get("kind") == "story" and anchor.get("end"):
        story_len = float(anchor["end"]) - float(anchor["start"])
        if MIN_S <= story_len <= MAX_S:
            targets = [story_len] + targets
    for a in near:
        want_ends = []
        for target in targets:
            want = a + target
            cand = [e for e in ends if e >= a + MIN_S - 2.0]
            if not cand:
                continue
            want_ends.extend(sorted(cand, key=lambda e: abs(e - want))[:2])
        if anchor.get("end"):
            want_ends.append(float(anchor["end"]))
        for lstart, lend, _peak in (laughs or []):
            if any(abs(float(lstart) - e) <= 3.0 for e in want_ends):
                want_ends.append(float(lend) + 0.3)
        for b in sorted(set(round(float(e), 2) for e in want_ends)):
            if b - a < MIN_S - 0.01 or b - a > MAX_S + 0.01:
                continue
            c = {"start": round(a, 2), "end": round(b, 2),
                 "anchor_kind": anchor.get("kind", "window"),
                 "story": anchor.get("story"),
                 "anchor_label": anchor.get("label", ""),
                 "title": ((anchor.get("story") or {}).get("summary")
                           or V._text_in(segments, a, b, 70)
                           or anchor.get("label") or "Clip"),
                 "hook": (anchor.get("spark") or {}).get("head")
                         or (anchor.get("story") or {}).get("hook_line") or "",
                 "payoff": (anchor.get("story") or {}).get("payoff") or ""}
            _enforce_window(c, segments, duration)
            if c.get("_drop") or V._starts_on_filler(segments, c["start"]):
                continue
            # A cinematic anchor may pull an edge onto a shot boundary, but only if the
            # boundary is within 1.8s AND the sentence edge stays intact. Meaning wins.
            if anchor.get("kind") == "cinema" and scenes:
                s0 = _snap_to_scene(c["start"], scenes)
                s1 = _snap_to_scene(c["end"], scenes)
                if s0 is not None and abs(s0 - c["start"]) <= 1.8:
                    c["start"] = round(max(0.0, s0), 2)
                if s1 is not None and abs(s1 - c["end"]) <= 1.8 and s1 - c["start"] >= MIN_S:
                    c["end"] = round(min(duration, s1), 2)
                _enforce_window(c, segments, duration)
                c["cinema"] = "sentence edge + shot boundary"
            out.append(c)
    return out[:10]


def _dedupe(cands, segments):
    """Drop windows that are the same edit under a different label. A 1.2s edge
    difference is not a new cut; neither is 90% shared vocabulary."""
    out = []
    for c in sorted(cands, key=lambda x: -(x.get("_priority", 0))):
        dup = False
        for o in out:
            if abs(c["start"] - o["start"]) <= 1.2 and abs(c["end"] - o["end"]) <= 1.2:
                dup = True
                break
            if abs(c["start"] - o["start"]) <= 2.5 and abs(c["end"] - o["end"]) <= 2.5:
                ta = V.content_words(V._text_in(segments, c["start"], c["end"], 1600))
                tb = V.content_words(V._text_in(segments, o["start"], o["end"], 1600))
                if V.near_duplicate(ta, tb, 0.82):
                    dup = True
                    break
        if not dup:
            out.append(c)
    return out


ARGON_EDITOR_PROMPT = """You are a short-form editor watching a long video through a
timestamped transcript. Your job is to propose the moments that should become vertical
shorts, and to explain the exact arc of each one.

You get the transcript chunk and the measured peaks inside it. Do not invent timestamps.

For each PROPOSED CUT:
- start and end are seconds from the start of the source video
- the start must be the beginning of a spoken sentence, never filler ("um", "so", "like",
  "yeah", "and") and never a greeting, intro, sponsor read, or shout-out
- the end must be after the payoff completes: the answer, the punchline, the reveal, the
  result, or the peak reaction. Never end mid-thought or just before the laugh
- the clip must be understandable with no earlier context
- choose a length the moment needs, between 10 and 75 seconds
- prefer a cold open on a strong line over a slow warm-up
- do not propose two cuts of the same beat

Return 4-8 stories and 4-8 cuts for this chunk, covering different moments. A story is a
complete arc; a cut is the exact window to publish.

Transcript chunk:
{transcript}

Measured peaks in this chunk:
{events}

Return ONLY compact JSON, no markdown:
{{"content_type": "podcast|tutorial|vlog|interview|speech|comedy|sports|other",
"stories": [{{"start": 12.5, "end": 48.0, "summary": "what happens",
"hook_line": "the spoken line that opens it, <= 12 words",
"payoff": "how it lands"}}],
"cuts": [{{"start": 18.0, "end": 51.5, "title": "6-word title",
"hook": "the spoken opening line", "payoff": "how this cut lands",
"kind": "hook|story|peak|cinema", "confidence": 0-10,
"reason": "one line: why this window works"}}]}}
"""


def editor_pass(segments, duration, moments=None, max_chunks=6):
    """One editorial call per transcript chunk. This is the part that uses the LLM as an
    editor, not as a scorer: it proposes the actual windows and the arcs inside them.
    Returns (stories, cuts, content_type). A failure returns empty lists, never a guess."""
    if not has_brain() or not segments:
        return [], [], "other"
    stories, cuts, votes = [], [], {}
    chunks = V._chunks(segments, max_chars=8500, max_chunks=max_chunks)
    for chunk in chunks:
        if not chunk:
            continue
        a, b = float(chunk[0]["start"]), float(chunk[-1]["end"])
        events = []
        for m in moments or []:
            if b <= m["start"] or a >= m["end"]:
                continue
            events.append(f"- {m['start']:.0f}-{m['end']:.0f}s: peak "
                          f"roar +{m.get('roar', 0):.1f}dB, "
                          f"{m.get('cuts', 0)} camera cuts, "
                          f"heat {m.get('heat', 0):.1f}")
        prompt = ARGON_EDITOR_PROMPT.format(
            transcript=V._transcript(chunk)[:9000],
            events="\n".join(events[:6]) or "(no measured peaks in this chunk)",
        )
        try:
            data = V._parse_json(ai_chat({
                "model": CONFIG["ai_model"],
                "messages": [{"role": "user", "content": prompt + V._owner_guidance()}],
                "temperature": 0.3,
            }))
        except Exception:
            continue
        ct = str(data.get("content_type") or "").strip().lower()
        if ct:
            votes[ct] = votes.get(ct, 0) + 1
        for st in V._as_list(data.get("stories")):
            if not isinstance(st, dict):
                continue
            sa, sb = V._as_float(st.get("start")), V._as_float(st.get("end"))
            if sa is None or sb is None:
                continue
            sa, sb = max(0.0, min(duration, sa)), max(0.0, min(duration, sb))
            if not (6.0 <= sb - sa <= 130.0):
                continue
            summary = str(st.get("summary") or "")[:140]
            hook = str(st.get("hook_line") or "")[:140]
            if V._is_hype(summary + " " + hook):
                continue
            stories.append({"start": sa, "end": sb, "summary": summary,
                            "hook_line": hook, "payoff": str(st.get("payoff") or "")[:140]})
        for cut in V._as_list(data.get("cuts")):
            if not isinstance(cut, dict):
                continue
            ca, cb = V._as_float(cut.get("start")), V._as_float(cut.get("end"))
            if ca is None or cb is None:
                continue
            ca, cb = max(0.0, min(duration, ca)), max(0.0, min(duration, cb))
            if not (MIN_S - 0.01 <= cb - ca <= MAX_S + 0.01):
                continue
            title = str(cut.get("title") or "")[:100]
            hook = str(cut.get("hook") or "")[:140]
            if V._is_hype(title + " " + hook):
                continue
            try:
                conf = float(cut.get("confidence") or 5.0)
            except (TypeError, ValueError):
                conf = 5.0
            cuts.append({"start": ca, "end": cb, "title": title or "Clip",
                         "hook": hook, "payoff": str(cut.get("payoff") or "")[:140],
                         "anchor_kind": str(cut.get("kind") or "editor")[:20],
                         "reason": str(cut.get("reason") or "")[:180],
                         "confidence": max(0.0, min(10.0, conf))})
    # De-duplicate editor cuts by window; the LLM can repeat the same beat across chunks.
    clean = []
    for c in sorted(cuts, key=lambda x: -x.get("confidence", 5.0)):
        if any(abs(c["start"] - o["start"]) < 2.0 and abs(c["end"] - o["end"]) < 2.0
               for o in clean):
            continue
        clean.append(c)
    content_type = max(votes, key=votes.get) if votes else "other"
    return stories, clean, content_type


def _build_candidates(segments, duration, energy, laughs, moments, scenes, motion, stories, editor_cuts=None):
    scenes = _scene_times(scenes)
    sparks = spark_scan(segments)
    out = []
    for e in editor_cuts or []:
        c = {"start": float(e.get("start", 0.0)), "end": float(e.get("end", 0.0)),
             "title": e.get("title") or "Clip", "hook": e.get("hook") or "",
             "payoff": e.get("payoff") or "", "reason": e.get("reason") or "",
             "anchor_kind": "editor", "anchor_label": "editor proposal",
             "story": None, "_priority": 2.1}
        _enforce_window(c, segments, duration)
        if c.get("_drop") or V._starts_on_filler(segments, c["start"]):
            continue
        out.append(c)
    anchors = (_spark_anchors(sparks) + _payoff_anchors(segments, laughs)
               + _story_anchors(stories) + _peak_anchors(moments)
               + _cinema_anchors(scenes, motion, duration))
    # The anchor graph can contain the same second several times; keep the strongest
    # one so the candidate budget is spent on different moments, not on aliases.
    merged = []
    for a in sorted(anchors, key=lambda x: -x.get("priority", 0)):
        if any(abs(a["start"] - m["start"]) < 5.0 for m in merged):
            continue
        merged.append(a)
    cands = list(out)
    for a in merged:
        if len(cands) >= MAX_CANDIDATES:
            break
        for c in _window_candidates(a, segments, duration, laughs, scenes):
            c["_priority"] = (float(a.get("priority", 0.5))
                              + (1.0 if c["anchor_kind"] == "story" else 0.0))
            cands.append(c)
    cands = [c for c in cands if not c.get("_drop")]
    cands = _dedupe(cands, segments)[:MAX_CANDIDATES]
    for c in cands:
        measure_candidate(c, segments, energy, laughs, moments, scenes, motion)
    return cands, sparks


# ---------------------------------------------------------------- LLM judge

ARGON_JUDGE_PROMPT = """You are the retention editor and QC gate for vertical shorts.
You see the EXACT transcript a viewer will see, plus measured signals. Judge each cut as
a standalone short, not as part of the source video.

THE FIRST 3 SECONDS DECIDE WHETHER ANYONE WATCHES. THE ENDING DECIDES WHETHER THEY
FINISH AND SHARE. A cold open on a strong line is good. A cut that starts mid-thought,
requires earlier context, or stops before the payoff is a failure no matter how good
one line was.

For each clip return:
- "alone": understandable with NO other context (true/false)
- "starts_abrupt": opens mid-thought or on filler (true/false)
- "ends_abrupt": stops before the payoff/reaction completes (true/false)
- "coherence": 0-10 as a standalone story
- "hook": 0-10 for the opening
- "payoff": 0-10 for the ending landing
- "emotion": 0-10 for felt emotion (laughter, shock, tension, relief)
- "shareability": 0-10 for "would someone send this to a friend?"
- "rewatch": 0-10 for loop/rewatch value
- "clarity": 0-10 for easy comprehension at normal speed
- "retention_3s": 0-10 predicted chance a distracted viewer keeps watching past 3s
- "retention_end": 0-10 predicted chance they watch to the last frame
- "flags": array of concrete defects from this list only:
  ["starts_mid_thought","ends_before_payoff","no_payoff","confusing_context",
   "inside_joke","not_standalone","spoiler","misleading","empty","weak_hook",
   "low_energy","repetitive","context_dependent","slow_open","weak_ending",
   "too_long","filler_open","screen_dependent","list_incomplete"]
- "verdict": one short line for the creator: what makes it work or what kills it.

Do not reward a clip for being long, loud, or part of a bigger story. Reward the exact
window. If the clip is merely competent, say so; do not inflate.

Clips:
{clips}

Return ONLY compact JSON, no markdown:
{{"judgements": [{{"index": 0, "alone": true, "starts_abrupt": false,
"ends_abrupt": false, "coherence": 8, "hook": 8, "payoff": 8, "emotion": 7,
"shareability": 7, "rewatch": 6, "clarity": 8, "retention_3s": 8,
"retention_end": 8, "flags": [], "verdict": "..."}}]}}
"""


def _parse_json(text):
    raw = re.search(r"\{[\s\S]*\}", text or "")
    if not raw:
        raise ValueError("no JSON object in model output")
    return json.loads(raw.group(0))


def _as_float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _num(j, key, default=5.0):
    v = j.get(key) if isinstance(j, dict) else None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return max(0.0, min(10.0, float(v)))
    return float(default)


def _clean_flags(raw):
    out = []
    for f in (raw or []) if isinstance(raw, (list, tuple)) else []:
        s = str(f or "").strip().lower().replace(" ", "_").replace("-", "_")
        if s in FATAL_FLAGS or s in WARNING_FLAGS:
            out.append(s)
    return sorted(set(out))


def _offline_judgement(c):
    """No brain: never pretend a judge spoke. Measured factors only, labelled as such."""
    f = c.get("argo_features") or {}
    return {
        "alone": True,
        "starts_abrupt": not bool(c.get("text_stats", {}).get("starts_clean", True)),
        "ends_abrupt": not bool(c.get("text_stats", {}).get("ends_final", True)),
        "coherence": round(3.0 + 7.0 * f.get("story", 0.5), 1),
        "hook": round(3.0 + 7.0 * f.get("hook", 0.5), 1),
        "payoff": round(3.0 + 7.0 * f.get("payoff", 0.5), 1),
        "emotion": round(3.0 + 7.0 * f.get("emotion", 0.5), 1),
        "shareability": round(3.0 + 7.0 * f.get("shareability", 0.5), 1),
        "rewatch": round(3.0 + 7.0 * f.get("loop", 0.4), 1),
        "clarity": round(3.0 + 7.0 * f.get("clarity", 0.6), 1),
        "retention_3s": round(3.0 + 7.0 * f.get("hook", 0.5), 1),
        "retention_end": round(3.0 + 7.0 * f.get("payoff", 0.5), 1),
        "flags": [], "verdict": "offline mode - measured factors only, no QC judge",
        "_offline": True,
    }


def _judge_batch(cands, segments, content_type):
    """Judge the exact final transcript. One call; honest fallback when the brain is
    unavailable or returns junk. The judge never picks a window; it rates one."""
    if not cands:
        return {}
    if not has_brain():
        return {i: _offline_judgement(c) for i, c in enumerate(cands)}
    payload = []
    for i, c in enumerate(cands):
        verbatim = V._text_in(segments, c["start"], c["end"], MAX_SPEAK_CHARS)
        payload.append({
            "index": i, "title": c.get("title", "")[:100],
            "duration": round(c["end"] - c["start"], 1),
            "anchor": c.get("anchor_kind", ""),
            "verbatim": verbatim,
            "measured": {
                "hook_speed": c.get("hook_speed", 0.0),
                "energy": c["measured"]["energy"],
                "laughter": c["measured"]["laughter"],
                "tail_laugh": c["measured"].get("tail_laugh", 0.0),
                "event": c["measured"].get("event", 0.0),
                "words_per_second": c.get("text_stats", {}).get("wps", 0.0),
                "starts_clean": c.get("text_stats", {}).get("starts_clean", True),
                "ends_on_sentence": c.get("text_stats", {}).get("ends_final", True),
                "shot_cuts_inside": c.get("text_stats", {}).get("scenes", 0),
                "context_dependency": c.get("text_stats", {}).get(
                    "context_dependency", 0.0),
                "list_incomplete": c.get("text_stats", {}).get("list_incomplete", 0.0),
            },
        })
    prompt = ARGON_JUDGE_PROMPT.format(clips=json.dumps(payload, ensure_ascii=False))
    try:
        data = _parse_json(ai_chat({
            "model": CONFIG["ai_model"],
            "messages": [{"role": "user", "content": prompt + V._owner_guidance()}],
            "temperature": 0.15,
        }))
    except Exception:
        # A judge failure must not silently become a pass. Fall back to the shipped
        # six-field judge, then to the honest offline judgement.
        try:
            base = V.judge_cuts(cands, segments)
        except Exception:
            base = {}
        out = {}
        for i, c in enumerate(cands):
            j = dict(base.get(i) or _offline_judgement(c))
            j.setdefault("emotion", 5)
            j.setdefault("shareability", 5)
            j.setdefault("rewatch", 5)
            j.setdefault("clarity", j.get("coherence", 5))
            j.setdefault("retention_3s", j.get("hook", 5))
            j.setdefault("retention_end", j.get("payoff", 5))
            j.setdefault("flags", [])
            out[i] = j
        return out
    out = {}
    for raw in (data.get("judgements") or []):
        if not isinstance(raw, dict):
            continue
        i = int(_as_float(raw.get("index"), -1))
        if not 0 <= i < len(cands):
            continue
        j = {
            "alone": bool(raw.get("alone", True)),
            "starts_abrupt": bool(raw.get("starts_abrupt", False)),
            "ends_abrupt": bool(raw.get("ends_abrupt", False)),
            "coherence": _num(raw, "coherence"),
            "hook": _num(raw, "hook"),
            "payoff": _num(raw, "payoff"),
            "emotion": _num(raw, "emotion"),
            "shareability": _num(raw, "shareability"),
            "rewatch": _num(raw, "rewatch"),
            "clarity": _num(raw, "clarity"),
            "retention_3s": _num(raw, "retention_3s"),
            "retention_end": _num(raw, "retention_end"),
            "flags": _clean_flags(raw.get("flags")),
            "verdict": str(raw.get("verdict") or "")[:180],
            "_offline": False,
        }
        # The judge's own boolean fields are authoritative: derive flags when the model
        # described the defect but forgot to name it.
        if j["starts_abrupt"] and "starts_mid_thought" not in j["flags"]:
            j["flags"].append("starts_mid_thought")
        if j["ends_abrupt"] and "ends_before_payoff" not in j["flags"]:
            j["flags"].append("ends_before_payoff")
        if not j["alone"] and "not_standalone" not in j["flags"]:
            j["flags"].append("not_standalone")
        if j["payoff"] < 4.0 and "no_payoff" not in j["flags"]:
            j["flags"].append("no_payoff")
        out[i] = j
    for i, c in enumerate(cands):
        out.setdefault(i, _offline_judgement(c))
    return out


# ---------------------------------------------------------------- judge -> score

def _apply_judge(c, j):
    """Fold judge ratings into the measured features. The judge never overrides a
    measurement; it adds the one thing measurement cannot see: whether the exact
    words work as a standalone short."""
    f = c["argo_features"]
    f["hook"] = min(1.0, 0.58 * f["hook"] + 0.28 * _num(j, "hook") / 10.0
                    + 0.14 * c.get("hook_speed", 0.0))
    f["story"] = min(1.0, 0.52 * f["story"] + 0.48 * _num(j, "coherence") / 10.0)
    f["payoff"] = min(1.0, 0.50 * f["payoff"] + 0.50 * _num(j, "payoff") / 10.0)
    f["emotion"] = min(1.0, 0.55 * f["emotion"] + 0.45 * _num(j, "emotion") / 10.0)
    f["shareability"] = min(1.0, 0.55 * f["shareability"]
                            + 0.45 * _num(j, "shareability") / 10.0)
    f["clarity"] = min(1.0, 0.55 * f["clarity"] + 0.45 * _num(j, "clarity") / 10.0)
    f["loop"] = min(1.0, 0.55 * f["loop"] + 0.45 * _num(j, "rewatch") / 10.0)
    # self-sufficiency is the judge's strongest structural signal.
    if not j.get("alone", True):
        f["self_sufficient"] = min(f["self_sufficient"], 0.35)
    if j.get("starts_abrupt"):
        f["clarity"] = min(f["clarity"], 0.45)
        f["hook"] = min(f["hook"], 0.55)
    if j.get("ends_abrupt"):
        f["payoff"] = min(f["payoff"], 0.35)
    c["argo_features"] = {k: round(max(0.0, min(1.0, v)), 3) for k, v in f.items()}
    c["judge"] = j
    c["flags"] = list(j.get("flags") or [])
    return c


def _gate(c, j):
    """Non-compensatory gate: a great hook cannot save a dead ending or a clip that
    needs the rest of the episode. Returns (passed, reasons)."""
    f = c["argo_features"]
    reasons = []
    if f.get("self_sufficient", 0) < 0.40:
        reasons.append("self_sufficiency")
    if f.get("payoff", 0) < 0.38:
        reasons.append("payoff")
    if f.get("failure_risk", 0) > 0.62:
        reasons.append("failure_risk")
    if set(c.get("flags") or []) & FATAL_FLAGS:
        reasons.append("fatal_flag")
    if j.get("ends_abrupt") or not j.get("alone", True):
        reasons.append("judge")
    return (not reasons), reasons


def score_candidate(c, j, content_type):
    """Compute the calibrated score, the six learning factors, and the honest QC badge."""
    _apply_judge(c, j)
    w = _weights(content_type)
    f = c["argo_features"]
    blend = sum(w.get(k, 0.0) * f.get(k, 0.0) for k in w)
    wsum = sum(w.values()) or 1.0
    blend = max(0.0, min(1.0, blend / wsum))
    # The story engines' 30..99 calibration is kept for comparability, but a gated
    # candidate is multiplied by the same non-compensatory gate the score is built on.
    passed, gate_reasons = _gate(c, j)
    score = 30.0 + 69.0 * (blend ** 1.12)
    if f.get("event", 0.0) >= 0.7:
        score = min(99.0, score + 3.5)
    flags = set(c.get("flags") or [])
    fatal = flags & FATAL_FLAGS
    if fatal:
        score -= min(17.0, 3.4 * len(fatal))
    if flags & WARNING_FLAGS:
        score -= min(7.0, 1.2 * len(flags & WARNING_FLAGS))
    if not passed:
        score *= 0.72
    if j.get("ends_abrupt") or "ends_before_payoff" in flags:
        score = min(score, 54.0)
    if not j.get("alone", True) or "not_standalone" in flags:
        score = min(score, 47.0)
    if _num(j, "retention_3s", 5) <= 3.0:
        score = min(score, 58.0)
    if _num(j, "retention_end", 5) <= 3.0:
        score = min(score, 52.0)
    c["score"] = int(max(1.0, min(99.0, round(score))))
    c["tier"] = _tier(c["score"], passed, flags)
    c["gate"] = {"passed": passed, "reasons": gate_reasons}
    # The six learning factors + the Argon detail. The learning store intentionally
    # keeps only the six it knows; the UI can show all of them.
    c["factors"] = {k: int(round(f.get(k, 0.0) * 100)) for k in CORE_FACTORS}
    c["factors"]["laughter"] = int(round(c["measured"].get("laughter", 0.0) * 100))
    c["argon"] = {k: int(round(f.get(k, 0.0) * 100)) for k in EXTRA_FACTORS}
    c["argon"]["hook_speed"] = int(round(c.get("hook_speed", 0.0) * 100))
    c["argon"]["flags"] = sorted(flags)
    c["argon"]["retention_3s"] = int(round(_num(j, "retention_3s", 5)))
    c["argon"]["retention_end"] = int(round(_num(j, "retention_end", 5)))
    c["argon"]["gate"] = c["gate"]
    c["verdict"] = (j.get("verdict") or "").strip()[:180]
    # An offline run has measurements, not a judge. It must never wear the verified
    # badge: that is the one claim this studio refuses to invent.
    c["qc"] = ("verified" if (not j.get("_offline") and not V.judge_fail(j) and passed
                              and _num(j, "retention_3s", 5) >= 5.0
                              and _num(j, "retention_end", 5) >= 5.0)
               else "unverified")
    if c["qc"] == "unverified" and not c["verdict"]:
        c["verdict"] = "measured candidate; the judge did not confirm a landing"
    c["reason"] = _reason(c, j)
    return c


def _tier(score, passed, flags):
    if not passed or flags & FATAL_FLAGS or score < 60:
        return "reject"
    if score >= 88:
        return "viral"
    if score >= 75:
        return "strong"
    return "usable"


def _reason(c, j):
    bits = []
    flags = set(c.get("flags") or [])
    if c.get("measured", {}).get("tail_laugh", 0) > 0.25:
        bits.append("ends on measured laughter")
    if _num(j, "coherence") >= 8:
        bits.append("stands alone")
    if _num(j, "hook") >= 8:
        bits.append("strong opening")
    if _num(j, "shareability") >= 8:
        bits.append("quotable")
    if flags:
        bits.append("flag: " + ", ".join(sorted(flags)[:2]))
    if not bits:
        bits.append((j.get("verdict") or "balanced measured cut").rstrip("."))
    return f"{bits[0].capitalize()}{('; ' + '; '.join(bits[1:])) if len(bits) > 1 else ''}"


# ---------------------------------------------------------------- repair

def _repair(c, j, segments, duration, laughs, scenes):
    """Deterministic repair of a concrete defect. The LLM never redraws blindly; it
    reports a defect, and this applies the smallest fix that can remove it.
    Returns True when the window moved (caller re-measures and re-judges)."""
    flags = set(c.get("flags") or [])
    if not flags and not j.get("ends_abrupt") and j.get("alone", True):
        return False
    sents = _sentences(segments)
    if not sents:
        return False
    moved = False
    starts = [s["start"] for s in sents]
    ends = [s["end"] for s in sents]
    before = (c["start"], c["end"])

    # 1) Context / mid-thought opening: move back to the previous sentence start, but
    #    never more than 10s (a longer rerun is a different story, not a repair).
    if flags & {"starts_mid_thought", "confusing_context", "not_standalone",
                "context_dependent", "filler_open"} or j.get("starts_abrupt"):
        prev = [s for s in starts if s < c["start"] and c["start"] - s <= 10.0]
        if prev:
            c["start"] = max(prev)
            moved = True
        elif V._starts_on_filler(segments, c["start"]):
            nxt = [s for s in starts if s > c["start"] and s - c["start"] <= 10.0
                   and not V._starts_on_filler(segments, s)]
            if nxt:
                c["start"] = nxt[0]
                moved = True

    # 2) Opening is weak or slow: start on the next strong spark inside the window,
    #    if that keeps enough room for a payoff.
    if flags & {"weak_hook", "slow_open"}:
        sparks = [s for s in spark_scan(segments)
                  if c["start"] + 1.0 <= s["start"] <= c["start"] + 7.0
                  and s["pull"] >= 0.6]
        if sparks and c["end"] - sparks[0]["start"] >= MIN_S:
            c["start"] = sparks[0]["start"]
            moved = True

    # 3) Dead ending: extend to the next sentence end, then to a near laugh if one is
    #    there. The ending is the product; this is the most important repair.
    if flags & {"ends_before_payoff", "no_payoff", "weak_ending", "list_incomplete"} \
            or j.get("ends_abrupt") or j.get("payoff", 5) < 5:
        later = [e for e in ends if e > c["end"] and e <= c["end"] + 18.0]
        if later:
            c["end"] = min(duration, later[-1] if len(later) > 1 else later[0])
            moved = True
        for lstart, lend, _peak in (laughs or []):
            if c["end"] - 0.5 <= float(lstart) <= c["end"] + 8.0 \
                    and float(lend) > c["end"] and float(lend) - c["start"] <= MAX_S:
                c["end"] = min(duration, float(lend) + 0.3)
                c["laugh_ending"] = True
                moved = True
                break

    # 4) Too long: trim from the front while keeping the payoff and the minimum.
    if flags & {"too_long"} or c["end"] - c["start"] > MAX_S:
        inside = [s for s in starts if c["start"] + 4.0 < s <= c["end"] - MIN_S]
        if inside:
            c["start"] = inside[-1]
            moved = True

    if not moved:
        return False
    _enforce_window(c, segments, duration)
    return (c["start"], c["end"]) != before


def _repair_pool(pool, segments, duration, laughs, scenes, energy, moments,
                 content_type, motion):
    """Repair up to MAX_REPAIR failing candidates, then re-measure and re-judge them."""
    broken = [c for c in pool
              if set(c.get("flags") or []) & FATAL_FLAGS
              or c.get("judge", {}).get("ends_abrupt")
              or not c.get("judge", {}).get("alone", True)]
    if not broken or not has_brain():
        return 0
    touched = []
    for c in broken[:MAX_REPAIR]:
        if _repair(c, c.get("judge") or {}, segments, duration, laughs, scenes):
            measure_candidate(c, segments, energy, laughs, moments, scenes, motion)
            touched.append(c)
    if not touched:
        return 0
    judgments = _judge_batch(touched, segments, content_type)
    for i, c in enumerate(touched):
        score_candidate(c, judgments.get(i) or _offline_judgement(c), content_type)
    return len(touched)


# ---------------------------------------------------------------- selection

def _ends_well(c):
    return c.get("qc") == "verified" or c["measured"].get("tail_laugh", 0.0) >= 0.25


def _temporal_iou(a, b):
    """How much two windows are the same span of the source. A shared ending with a
    different start is often the same payoff cut twice; a shared start with a different
    ending can be a genuinely different edit, so the union is the honest denominator."""
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(1e-6, max(a["end"], b["end"]) - min(a["start"], b["start"]))
    return inter / union


def _similarity(a, b, segments, spread):
    """How much two candidates are the same editorial beat: shared words + proximity.
    Semantic-only similarity would miss the same exchange cut twice; temporal-only
    would reject two different beats near each other. Both are used."""
    ta = V.content_words(V._text_in(segments, a["start"], a["end"], 1800))
    tb = V.content_words(V._text_in(segments, b["start"], b["end"], 1800))
    lexical = (len(ta & tb) / max(1, len(ta | tb))) if ta and tb else 0.0
    temporal = max(0.0, 1.0 - abs(a["start"] - b["start"]) / max(1.0, spread))
    story = 0.0
    if a.get("story") and b.get("story") and a.get("story") is b.get("story"):
        story = 1.0
    elif a.get("story") and b.get("story") \
            and a["story"].get("summary") == b["story"].get("summary"):
        story = 0.8
    return max(lexical, 0.55 * temporal + 0.30 * lexical + 0.15 * story)


def _select(pool, count, duration, segments):
    """MMR over score, with a hard spread floor and duplicate-beat rejection. This is
    how the podium tells the whole arc instead of three cuts of the same laugh."""
    if not pool:
        return []
    candidates = sorted(pool, key=lambda c: -(c["score"] + (4 if c["qc"] == "verified" else 0)))
    passing = [c for c in candidates if _ends_well(c) and c.get("tier") != "reject"]
    rest = [c for c in candidates if c not in passing]
    spread = max(14.0, 0.08 * duration)
    picked = []
    for pool_round in (passing, rest):
        for c in pool_round:
            if len(picked) >= count:
                break
            if c in picked:
                continue
            if any(abs(c["start"] - p["start"]) < max(8.0, spread * 0.55) for p in picked):
                continue
            if any(abs(c["end"] - p["end"]) < 2.0 for p in picked):
                continue
            if any(_temporal_iou(c, p) > 0.45 for p in picked):
                continue
            if any(_similarity(c, p, segments, spread) > 0.78 for p in picked):
                continue
            # MMR: a high score can still lose to a different beat. The penalty is
            # bounded so quality remains the dominant term.
            val = c["score"] / 100.0 - 0.16 * max(
                [_similarity(c, p, segments, spread) for p in picked] or [0.0])
            c["_mmr"] = round(val, 4)
            picked.append(c)
        if len(picked) >= count:
            break
    # If the strict spread leaves the podium short, relax the temporal floor but keep
    # the duplicate-beat test. A shorter honest podium beats a duplicate.
    if len(picked) < count:
        for c in candidates:
            if len(picked) >= count:
                break
            if c in picked:
                continue
            if any(abs(c["start"] - p["start"]) < 8.0 for p in picked):
                continue
            if any(abs(c["end"] - p["end"]) < 2.0 for p in picked):
                continue
            if any(_temporal_iou(c, p) > 0.50 for p in picked):
                continue
            if any(_similarity(c, p, segments, spread) > 0.84 for p in picked):
                continue
            picked.append(c)
    for c in picked:
        c["selected"] = True
    return picked


# ---------------------------------------------------------------- public entry

def rank(segments, duration, count=3, energy=None, laughs=None, scenes=None,
         cinema_marks=None, motion=None):
    """ARGON's full pass. Same return contract as virality.rank / apex.rank:
    (picked_moments, candidate_pool, picker, content_type)."""
    count = max(1, min(8, int(count or 3)))
    if not segments:
        return V._even_windows(duration, count), [], "argon-windows", "other"

    moments = V.mine_moments(segments, duration, energy, laughs, scenes)
    content_type = "other"
    stories, editor_cuts = [], []
    if has_brain():
        try:
            stories, editor_cuts, content_type = editor_pass(segments, duration, moments)
        except Exception:
            stories, editor_cuts = [], []
    if not stories:
        stories = V.stories_offline(segments, duration, energy, laughs, moments=moments)

    cands, sparks = _build_candidates(segments, duration, energy, laughs, moments,
                                      cinema_marks or scenes, motion, stories, editor_cuts)
    if not cands:
        return V._even_windows(duration, count), [], "argon-windows", content_type
    cands.sort(key=lambda c: -(
        0.32 * c["argo_features"]["hook"]
        + 0.24 * c["argo_features"]["payoff"]
        + 0.16 * c["argo_features"]["event"]
        + 0.10 * c["argo_features"]["visual"]
        + 0.08 * c["argo_features"]["emotion"]
        + 0.06 * c["argo_features"]["shareability"]
        + 0.04 * c["argo_features"]["self_sufficient"]))
    pool = cands[:MAX_JUDGE]
    judgments = _judge_batch(pool, segments, content_type)
    for i, c in enumerate(pool):
        score_candidate(c, judgments.get(i) or _offline_judgement(c), content_type)

    # One repair round, then re-judge only the windows that moved. This is where the
    # old engines either gave up or let the LLM redraw a random window; ARGON fixes
    # the named defect deterministically.
    _repair_pool(pool, segments, duration, laughs, scenes or cinema_marks,
                 energy, moments, content_type, motion)

    picked = _select(pool, count, duration, segments)
    lab = sorted(pool, key=lambda c: -(c.get("score") or 0))[:10]
    return picked, lab, "argon-editor" if has_brain() else "argon-measured", content_type


def rank_single(segments, duration, energy, start, end, scenes=None, laughs=None,
                motion=None):
    """A manual window measured by the same engine. No invented judge: if the brain is
    absent the verdict says so."""
    c = {"start": float(start), "end": float(end), "title": "Custom cut",
         "hook": "", "anchor_kind": "manual", "reason": "your manual selection"}
    _enforce_window(c, segments, duration)
    moments = V.mine_moments(segments, duration, energy, laughs, _scene_times(scenes))
    measure_candidate(c, segments, energy, laughs, moments, _scene_times(scenes), motion)
    if has_brain():
        try:
            j = _judge_batch([c], segments, "other").get(0) or _offline_judgement(c)
        except Exception:
            j = _offline_judgement(c)
    else:
        j = _offline_judgement(c)
    return score_candidate(c, j, "other")
