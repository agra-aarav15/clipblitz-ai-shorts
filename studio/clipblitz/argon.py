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

import bisect
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor

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
                 "failure_risk", "action", "boundary", "opening")
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

# One taxonomy for the judge, the measured pass and the card. A clip gets one
# dominant label and can carry a secondary label; "funny" is not a synonym for
# "any reaction sound". The order is the tie-break priority when cue counts tie.
EMOTION_LABELS = ("funny", "suspense", "shock", "emotional", "inspiring",
                  "angry", "wholesome", "hype", "informative", "awkward")
EMOTION_ALIASES = {
    "tense": "suspense", "tension": "suspense", "mystery": "suspense",
    "scary": "suspense", "fear": "suspense", "thriller": "suspense",
    "surprise": "shock", "surprising": "shock", "twist": "shock",
    "sad": "emotional", "heartfelt": "emotional", "moving": "emotional",
    "inspired": "inspiring", "inspirational": "inspiring", "motivational": "inspiring",
    "excited": "hype", "excitement": "hype", "energetic": "hype", "action": "hype",
    "fun": "funny", "comedy": "funny", "humorous": "funny", "hilarious": "funny",
    "cringe": "awkward", "uncomfortable": "awkward", "informative": "informative",
    "educational": "informative", "warm": "wholesome", "heartwarming": "wholesome",
    "furious": "angry", "outrage": "angry",
}

# Cues are lowercase words/phrases. A phrase counts more than a single word, and
# the acoustic reaction signal only becomes "funny" when one of these cues exists.
EMOTION_CUES = {
    "funny": ("joke", "jokes", "joking", "funny", "laugh", "laughs", "laughed",
              "laughing", "haha", "hilarious", "comedy", "punchline", "roast",
              "silly", "banter", "made me laugh", "cracked up", "stand-up",
              "standup", "comedian", "meme", "banter", "pee", "lizard",
              "godzilla", "hokey", "bananas", "biscuit", "cup of tea", "dodgy",
              "brown man", "horse with horns", "who let the dogs out", "swimming",
              "seat full of water", "sweat from", "apart from that", "that's rude",
              "i wish i could say", "something loose", "made a mistake", "oh dear",
              "no please", "you're welcome", "deer", "sweat", "tent",
              "grandstand", "sounds like", "just you", "fairly chill", "relax",
              "bananas", "biscuit", "cup of tea", "rain on my bike", "मजेदार", "मज़ेदार", "हंसी", "हँसी",
              "जोक", "जोक्स", "मजाक", "मज़ाक", "कॉमेडी", "हंस", "مزاحیہ", "ہنسی",
              "جوك", "مذاق"),
    "suspense": ("suspense", "mystery", "secret", "secrets", "what happened",
                 "who did", "missing", "investigate", "investigation", "detective",
                 "case", "clue", "evidence", "danger", "dangerous", "scared",
                 "afraid", "threat", "warning", "nervous", "tension", "tense",
                 "hidden", "behind", "trap", "suddenly", "wait", "reveal",
                 "the truth", "no idea", "someone", "door", "phone call", "vanished",
                 "राज", "रहस्य", "सच", "क्या हुआ", "कौन", "डर", "खतरा", "पुलिस",
                 "जासूस", "जांच", "सबूत", "मामला", "छुपा", "दरवाजा", "फोन", "गायब",
                 "शक", "पीछे", "راز", "کیا ہوا", "کون", "خوف", "خطرہ", "پولیس",
                 "جاسوس", "تحقیق", "ثبوت", "معاملہ", "چھپا", "دروازہ", "فون", "غائب", "شک"),
    "shock": ("shocked", "shocking", "unbelievable", "insane", "crazy", "sudden",
              "out of nowhere", "twist", "scandal", "exposed", "arrested", "caught",
              "died", "accident", "exploded", "banned", "record", "nobody expected",
              "what the hell", "oh my god", "wtf", "शॉक", "हैरान", "अचानक", "धमाका",
              "मौत", "हादसा", "सनसनी", "صدمہ", "حیران", "اچانک", "دھماکہ", "موت",
              "حادثہ"),
    "emotional": ("cried", "crying", "tears", "hurt", "pain", "lost", "grief",
                  "passed away", "vulnerable", "heartbroken", "emotional", "love",
                  "family", "mother", "father", "son", "daughter", "miss", "alone",
                  "sad", "broke down", "hardest", "trauma", "childhood", "रोया",
                  "रोई", "आंसू", "दर्द", "परिवार", "मां", "माँ", "पिता", "प्यार",
                  "टूट", "अकेला", "رویا", "آنسو", "درد", "خاندان", "ماں", "والد",
                  "محبت", "اکیلا"),
    "inspiring": ("inspired", "inspiring", "dream", "never give up", "overcome",
                  "struggle", "success", "prove", "proved", "believe", "hope",
                  "change", "journey", "worked", "win", "champion", "first",
                  "proud", "made it", "against all odds", "keep going", "सपना",
                  "हार", "जीत", "मेहनत", "कोशिश", "कामयाब", "प्रेरणा", "खुद पर",
                  "सपنا", "ہار", "جیت", "محنت", "کوشش", "کامیاب", "حوصلہ"),
    "angry": ("angry", "furious", "hate", "rage", "fight", "argument", "stupid",
              "idiot", "unfair", "betrayed", "disrespect", "shut up", "damn",
              "hell", "wronged", "screaming", "yelling", "गुस्सा", "नाराज",
              "बेइज्जती", "झगड़ा", "धोखा", "चिल्ला", "غصہ", "ناراض", "جھگڑا",
              "دھوکہ", "چیخ"),
    "wholesome": ("kind", "kindness", "helped", "helping", "thank", "grateful",
                  "sweet", "wholesome", "care", "generous", "support", "together",
                  "community", "good person", "made his day", "made her day",
                  "मदद", "शुक्रिया", "दया", "भलाई", "अच्छा", "مدد", "شکریہ",
                  "نیکی", "اچھا"),
    "hype": ("let's go", "come on", "huge", "massive", "fast", "overtake",
             "winner", "wins", "goal", "touchdown", "slam", "incredible",
             "unreal", "best ever", "championship", "record", "yes", "wow",
             "शानदार", "जबरदस्त", "तेज", "जीत", "गोल", "धमाल", "زبردست",
             "تیز", "جیت", "گول"),
    "informative": ("because", "reason", "means", "explain", "how to", "the way",
                    "research", "study", "data", "science", "actually", "lesson",
                    "learn", "understand", "here's why", "the point is", "क्यों",
                    "कैसे", "मतलब", "सबक", "जानकारी", "वजह", "کیوں", "کیسے",
                    "مطلب", "سبق", "معلومات", "وجہ"),
    "awkward": ("awkward", "cringe", "embarrassing", "uncomfortable", "silence",
                "weird", "strange", "oops", "mistake", "sorry", "uh", "um",
                "अजीब", "शर्मिंदा", "खामोशी", "गलती", "عجیب", "شرمندہ",
                "خاموشی", "غلطی"),
}
COMEDY_CUES = EMOTION_CUES["funny"]

SHARE_WORDS = ("everyone", "nobody", "never", "always", "best", "worst", "first",
               "last", "only", "biggest", "fastest", "secret", "truth", "proof",
               "mistake", "wrong", "banned", "record", "million", "billion")

RESOLUTION_WORDS = ("so that's why", "that's why", "the lesson", "turns out",
                    "which means", "and that changed", "the point is", "in the end",
                    "finally", "it worked", "it failed", "the result", "the truth is")

SUMMARY_CUES = ("the point is", "the lesson is", "what i learned", "in the end",
                "the result was", "that's why", "that is why", "the truth is",
                "what matters", "here's the thing", "so the key", "the takeaway",
                "looking back", "if i had to")

DANGLING_OPENERS = ("but", "and", "so", "because", "cause", "plus", "also", "or",
                    "nor", "which", "that's", "then", "however", "still")
DANGLING_PHRASES = ("which is why", "which means", "that's why", "that is why",
                    "so the reason", "so the main reason", "the reason is",
                    "going back to", "like i said", "as i mentioned")

ACTION_WORDS = ("overtake", "overtakes", "overtaken", "pass", "passes", "passed",
                "battle", "fight", "fights", "win", "wins", "won", "podium",
                "finish", "finished", "position", "positions", "places", "gained",
                "charge", "charges", "charging", "attack", "defend", "crash",
                "spin", "lockup", "fastest", "lap", "comeback", "recovery")

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
                 "screen_dependent", "list_incomplete", "emotion_mismatch"}
# Warning flags that name a defect the deterministic repair pass can actually fix.
# A candidate carrying one of these must reach the repair pool even when the gate
# passes; otherwise repair steps 2 (slow hook) and 4 (too long) can never run.
REPAIRABLE_FLAGS = {"weak_hook", "slow_open", "weak_ending", "too_long",
                    "list_incomplete", "context_dependent", "filler_open",
                    "starts_mid_thought"}

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
    "sports": {"event": 2.40, "visual": 1.90, "story": 0.65, "hook": 0.90,
               "payoff": 0.95, "emotion": 1.10},
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


# The same transcript is measured for dozens of candidate windows. Rebuilding the
# sentence list, and every word in the episode, for each window made a long source
# quadratic. These caches hold one transcript each (with a reference, so an id cannot
# be reused) and are read-only; invalidate by handing in a different list.
_SENT_CACHE = {}
_WORD_CACHE = {}


def _sentence_rows(segments):
    entry = _SENT_CACHE.get(id(segments))
    if entry and entry[0] is segments and entry[1] == len(segments):
        return entry[2]
    rows = _sentences(segments)
    _SENT_CACHE.clear()
    _SENT_CACHE[id(segments)] = (segments, len(segments), rows)
    return rows


def _word_rows(segments):
    """(sorted words, their starts, sentences, sentence starts) for one transcript."""
    entry = _WORD_CACHE.get(id(segments))
    if entry and entry[0] is segments and entry[1] == len(segments):
        return entry[2], entry[3], entry[4], entry[5]
    sents = _sentence_rows(segments)
    words = []
    for s in sents:
        for w in s.get("words") or []:
            try:
                ws, we = float(w.get("start")), float(w.get("end"))
            except (TypeError, ValueError):
                continue
            words.append((ws, we, str(w.get("word") or "")))
    words.sort()
    starts = [w[0] for w in words]
    sstarts = [s["start"] for s in sents]
    _WORD_CACHE.clear()
    _WORD_CACHE[id(segments)] = (segments, len(segments), words, starts, sents, sstarts)
    return words, starts, sents, sstarts


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
    for s in _sentence_rows(segments):
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


def _token_counts(low):
    """Whole-token counts for one lowercase text. Devanagari/Urdu words do not get
    reliable \b boundaries in Python's Unicode regex mode, and substring matching
    turns "तुम्हारी" into "हार" (loss); one token map serves every cue list and keeps
    the per-candidate emotion read cheap."""
    counts = {}
    for tok in re.findall(r"[^\s.,!?;:…\"'()\[\]]+", low):
        counts[tok] = counts.get(tok, 0) + 1
    return counts


def _cue_hits(low, cues, counts=None):
    """Weighted cue count. Phrases are stronger evidence than single words, so a
    line saying 'out of nowhere' beats a line containing only 'wait'."""
    if counts is None:
        counts = _token_counts(low)
    n = 0.0
    for cue in cues:
        if " " in cue:
            n += 1.5 * low.count(cue)
        else:
            n += counts.get(cue, 0)
    return n


def _comedy_context(text, content_type=None, judge_label=None):
    """Is there actual comedy evidence in the words? Acoustic energy bursts are not
    jokes: a suspense sting, a crowd roar and a laugh all raise RMS. Only a comedy
    cue (or a comedy clip type / judge label) may turn a burst into a laugh signal."""
    if (content_type or "").lower() in ("comedy",):
        return True
    if judge_label and str(judge_label).lower() in ("funny", "comedy"):
        return True
    low = _norm(text)
    return any(cue in low for cue in COMEDY_CUES)


def _emotion_profile(text, measured=None, content_type=None):
    """Deterministic emotion read from the exact words plus safe measured signals.

    Returns the dominant label, its intensity, and the full score map. It never
    interprets an acoustic burst as laughter without a comedy cue, which is how a
    tense detective scene stops being rated as a comedy just because it has a sting.
    """
    low = _norm(text)
    reaction = float((measured or {}).get("reaction", 0.0) or 0.0)
    raw = {}
    counts = _token_counts(low)
    for label in EMOTION_LABELS:
        raw[label] = _cue_hits(low, EMOTION_CUES[label], counts)
    raw["funny"] = raw.get("funny", 0.0)
    # Punctuation is weak evidence; never enough to choose an emotion by itself.
    if "?" in low:
        raw["suspense"] += 0.15
        raw["informative"] += 0.10
    if "!" in low:
        raw["shock"] += 0.12
        raw["hype"] += 0.12
    ctype = (content_type or "").lower()
    if ctype == "comedy":
        raw["funny"] += 0.8
    elif ctype == "sports":
        raw["hype"] += 0.45 + 0.55 * float((measured or {}).get("event", 0.0) or 0.0)
    elif ctype in ("interview", "podcast", "speech"):
        raw["informative"] += 0.20
    if _comedy_context(low):
        raw["funny"] += 0.55 + 0.45 * reaction
    # A reaction sound alone is not funny. It can reinforce a funny read but cannot
    # create one; the same is true for hype in a sports cut with a measured event.
    if raw["funny"] <= 0.0:
        raw["funny"] = 0.0
    top = max(raw.values()) if raw else 0.0
    if top <= 0.0:
        return {"label": "informative", "intensity": 0.2,
                "scores": {k: 0 for k in EMOTION_LABELS}, "reaction": reaction}
    # Stable priority: earlier labels win exact ties, so the output is reproducible.
    label = next(k for k in EMOTION_LABELS if raw[k] == top)
    intensity = min(1.0, top / 3.0)
    return {"label": label, "intensity": round(intensity, 3),
            "scores": {k: round(min(1.0, v / 3.0), 3) for k, v in raw.items()},
            "reaction": round(reaction, 3)}


def _emotion(text):
    """Backward-compatible intensity helper used by older tests and reports."""
    return _emotion_profile(text).get("intensity", 0.2)


def _resolution(text):
    low = _norm(text)
    return min(1.0, sum(1 for p in RESOLUTION_WORDS if p in low) * 0.34)


def _action(text):
    """Concrete sports/highlight action language. Deterministic and deliberately
    narrow: an interview about a penalty is not the same clip as the overtake."""
    words = set(re.findall(r"[a-z']+", _norm(text)))
    hits = len(words & set(ACTION_WORDS))
    return min(1.0, hits / 3.0)


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

def _opening_review(segments, a, b):
    """Measure the first sentence as a standalone opening (0..1, issue).

    A clip that opens on "But the main reason..." or on a two-word fragment makes
    the viewer supply context they do not have. This is a measurement, not an LLM
    opinion, and it is deliberately biased toward finding a defect."""
    sents = _sentence_rows(segments)
    first = next((s for s in sents if s["end"] > a + 0.01 and s["start"] < b), None)
    if first is None:
        return 0.45, "no_sentence"
    words = first.get("words") or []
    tokens = []
    for w in words:
        tok = re.sub(r"[^a-z0-9']+", "", str(w.get("word") or "").lower())
        if tok:
            tokens.append(tok)
    if not tokens:
        text = first.get("text") or ""
        tokens = re.findall(r"[a-z0-9']+", text.lower())
    content = [t for t in tokens if t not in V.FILLER_STARTS]
    low = _norm(first.get("text") or " ".join(tokens))
    issue = ""
    if tokens and (tokens[0] in DANGLING_OPENERS
                   or any(low.startswith(p) for p in DANGLING_PHRASES)):
        issue = "dangling"
    elif 0 < len(content) <= 2 and len(sents) > 1:
        issue = "fragment"
    elif a > first["start"] + 0.40:
        issue = "mid_sentence"
    if V._starts_on_filler(segments, a):
        issue = issue or "filler"
    score = {"dangling": 0.34, "fragment": 0.30, "mid_sentence": 0.52,
             "filler": 0.18, "no_sentence": 0.45}.get(issue, 1.0)
    return score, issue


def _boundary_review(segments, b):
    """Measure how clean the ending is: sentence punctuation plus the pause that
    follows it. A word cut in half scores near zero; a finished sentence with room
    after it scores near one. Returns (0..1, gap_seconds, ends_final).

    Word and sentence rows are cached per transcript and searched with bisect; the
    old per-candidate rebuild was the other half of the long-video slowdown.
    """
    words, starts, sents, sstarts = _word_rows(segments)
    if not words:
        return 0.45, 3.0, False
    hi = bisect.bisect_left(starts, b + 0.01)
    if hi == 0:
        return 0.45, 3.0, False
    # Words arrive in order, so the last word before the cut is the last start.
    # Check the few words around the edge for one still running: skipping the whole
    # transcript's max() must not hide a cut through a long/overlapping word.
    for w in reversed(words[max(0, hi - 4):hi]):
        if w[1] > b + 0.05:
            return 0.15, 0.0, False
    last = words[hi - 1]
    last_end, last_word = last[1], last[2]
    if last_end > b + 0.05:
        # The cut lands inside a word. No pause can make that a clean ending.
        return 0.15, 0.0, False
    si = bisect.bisect_left(sstarts, b - 0.01)
    tail_text = sents[si - 1]["text"] if si > 0 else ""
    final = bool(re.search(r"[.!?…][\"')\]}]*$", last_word.strip())) or bool(
        re.search(r"[.!?…][\"')\]}]*$", tail_text.strip()))
    if hi >= len(words):
        return 1.0, 3.0, final
    gap = max(0.0, words[hi][0] - last_end)
    if gap >= 4.0:
        base = 0.92
    elif gap >= 1.2:
        base = 0.82
    elif gap >= 0.45:
        base = 0.70 if final else 0.55
    elif gap >= 0.15:
        base = 0.55 if final else 0.38
    else:
        base = 0.40 if final else 0.20
    if final and gap >= 0.45:
        base += 0.08
    if last_word.rstrip().endswith("?"):
        base += 0.03
    return min(1.0, base), gap, final


def measure_candidate(c, segments, energy, laughs, moments, scenes=None, motion=None):
    """Measure one candidate. Everything here is deterministic.

    The six core factors are exactly the names the local learning store/trainer
    already consume; the extra ARGON factors are shown on the card and used by the
    score, but are not silently fed into models that expect a six-dimensional vector.
    """
    # A fresh measurement invalidates the saved pre-judge features. Repair moves a
    # window and measures it again; without this reset the new window would be scored
    # with the old window's factors (raw_features wins in score_candidate).
    c.pop("raw_features", None)
    a, b = c["start"], c["end"]
    text = V._text_in(segments, a, b, 2400)
    # Decide what kind of reaction this is BEFORE measuring: an acoustic burst is
    # called laughter only when the words contain a comedy cue. A suspense sting is
    # measured as reaction, not as a joke.
    comedy = _comedy_context(text)
    V.measure([c], segments, energy, laughs, moments, comedy=comedy)
    emotion = _emotion_profile(text, c["measured"])
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
    opening, opening_issue = _opening_review(segments, a, b)
    boundary, end_gap, boundary_final = _boundary_review(segments, b)

    feat = {
        "hook": min(1.0, 0.52 * pull + 0.22 * energy_f
                    + 0.14 * (1.0 if question else 0.0) + 0.12 * opening),
        "story": min(1.0, 0.36 * (1.0 if starts_clean and ends_final else 0.50)
                     + 0.18 * (1.0 - filler) + 0.16 * min(1.0, dur / 35.0)
                     + 0.16 * (1.0 - list_gap) + 0.14 * boundary),
        "payoff": min(1.0, 0.38 * tail_laugh + 0.16 * (1.0 if ends_final else 0.0)
                      + 0.12 * laugh_f + 0.14 * _resolution(tail) + 0.20 * boundary),
        "energy": max(0.0, min(1.0, energy_f)),
        "pacing": max(0.0, min(1.0, c["measured"]["pacing"])),
        "event": max(0.0, min(1.0, event_f)),
        "emotion": min(1.0, 0.72 * emotion["intensity"]
                         + 0.18 * laugh_f + 0.10 * tail_laugh),
        "novelty": max(0.0, min(1.0, _lexical_novelty(text))),
        "visual": max(0.0, min(1.0, 0.55 * mean_motion + 0.30 * peak_motion
                                + 0.15 * min(1.0, cuts / 2.0))),
        "self_sufficient": max(0.0, min(1.0, 0.30 * (1.0 if starts_clean else 0.0)
                                        + 0.24 * (1.0 if ends_final else 0.0)
                                        + 0.16 * min(1.0, n_words / 45.0)
                                        + 0.12 * (1.0 - context) + 0.18 * boundary)),
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
        "failure_risk": min(1.0, 0.45 * list_gap + 0.20 * context
                            + (0.15 if not ends_final else 0.0)
                            + 0.20 * (1.0 - boundary)),
        "action": _action(text),
        "boundary": boundary,
        "opening": opening,
    }
    c["argo_features"] = {k: round(max(0.0, min(1.0, v)), 3) for k, v in feat.items()}
    c["hook_speed"] = _hook_speed(c, segments)
    c["anchor_kind"] = c.get("anchor_kind") or "window"
    c["hook_kind"] = kind
    c["text_stats"] = {"words": n_words, "wps": round(wps, 2), "filler": round(filler, 3),
                       "starts_clean": starts_clean, "ends_final": ends_final,
                       "question_open": question, "scenes": cuts,
                       "context_dependency": round(context, 3),
                       "list_incomplete": round(list_gap, 3),
                       "boundary": round(boundary, 3),
                       "end_gap": round(end_gap, 2),
                       "ends_final_measured": boundary_final,
                       "opening": round(opening, 3),
                       "opening_issue": opening_issue}
    c["emotion"] = dict(emotion)
    c["emotion_label"] = emotion["label"]
    c["emotion_scores"] = dict(emotion["scores"])
    c["comedy_context"] = bool(comedy)
    return c


def _hook_speed(c, segments):
    """0..1: how quickly the first high-pull line arrives inside the cut. A hook that
    makes the viewer wait is a cost, not a virtue.

    Measure the real sentences inside the first ten seconds. Scanning one synthetic
    sentence that begins at the cut start could only ever return 0 or 1: the delay
    was always zero, so a question four seconds in scored as if there were none.
    """
    a, b = c["start"], c["end"]
    limit = min(b, a + 10.0)
    delay = None
    for s in _sentence_rows(segments):
        if s["end"] <= a + 0.01 or s["start"] >= limit:
            continue
        pull, _kind = _pull(_head(s))
        if pull >= 0.45:
            delay = max(0.0, s["start"] - a)
            break
    if delay is None:
        return 0.0
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
    for s in _sentence_rows(segments):
        res = _resolution(s["text"])
        low = _norm(s["text"])
        summary = any(cue in low[:180] for cue in SUMMARY_CUES)
        if res >= 0.34 or summary or s["text"].rstrip().endswith("!"):
            out.append({"start": s["start"], "end": s["end"], "kind": "payoff",
                        "priority": 0.62 + 0.20 * res + (0.12 if summary else 0.0),
                        "label": "self-summary" if summary else "resolution line"})
    out.sort(key=lambda x: -float(x.get("priority", 0)))
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


def _emotion_anchors(segments, limit=12):
    """One strong seed per emotion, not just per laugh. A video with a tense reveal,
    a sad confession and a funny line should put all three into the candidate budget;
    picking only acoustic peaks is what made every source look like a comedy."""
    best = {}
    for s in _sentence_rows(segments):
        p = _emotion_profile(s["text"])
        label = p["label"]
        if label == "informative" and p["intensity"] < 0.40:
            continue
        prev = best.get(label)
        if prev is None or p["intensity"] > prev[0]:
            best[label] = (p["intensity"], s)
    out = []
    for label, (intensity, s) in best.items():
        out.append({"start": float(s["start"]), "end": float(s["end"]),
                    "kind": "emotion", "priority": 0.58 + 0.30 * intensity,
                    "emotion_label": label,
                    "label": f"{label} beat"})
    out.sort(key=lambda a: -a["priority"])
    return out[:limit]


def _cinema_anchors(scenes, motion, duration, limit=8):
    """Shot boundaries, optionally weighted by on-screen motion. ARGON can run without
    the expensive motion map: scene cuts alone still give it real edit points."""
    shots = _scene_times(scenes)
    rows = []
    out = []
    if motion:
        for row in (motion or []):
            # Live runs pass (time, value) tuples; a stored/newer producer may pass a
            # dict. Normalise both instead of crashing on `for t, v in motion`.
            if isinstance(row, dict):
                t = _scene_time(row)
                value = row.get("value", row.get("motion", row.get("v", 0.0)))
            elif isinstance(row, (tuple, list)) and len(row) >= 2:
                t = _scene_time(row[0])
                value = row[1]
            else:
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if t is None:
                continue
            if any(abs(t - s) <= 2.0 for s in shots):
                rows.append((v, t))
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


def _enforce_window(c, segments, duration, reject_hype=False):
    """Keep a window inside the duration, on sentence edges, out of filler, and in the
    ARGON length band. Every candidate passes through this deterministic guard.

    ``reject_hype`` is used for machine-built and machine-repaired windows: opening on
    an intro, greeting or sponsor read is the owner's most-rejected clip shape. A cut
    the owner dragged by hand keeps the exact window they chose (rank_single leaves
    this off).
    """
    sents = _sentence_rows(segments)
    if not sents:
        c["start"] = round(max(0.0, min(duration, c["start"])), 2)
        c["end"] = round(min(duration, max(c["start"] + 1.0, c["end"])), 2)
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
    if reject_hype and V._is_hype(V._text_in(segments, c["start"], c["start"] + 5.0, 200)):
        clean = [s["start"] for s in sents
                 if c["start"] + 0.2 <= s["start"] <= c["end"] - 4.0
                 and not V._starts_on_filler(segments, s["start"])
                 and not V._is_hype(V._text_in(segments, s["start"], s["start"] + 5.0, 200))]
        if clean:
            c["start"] = clean[0]
        else:
            # Every remaining opener is a greeting or an intro. Drop the window instead
            # of shipping the exact clip the owner keeps rejecting.
            c["_drop"] = True
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
    c["end"] = round(min(duration, max(c["start"] + 1.0, c["end"])), 2)
    return c


def _window_candidates(anchor, segments, duration, laughs, scenes):
    """Every plausible sentence-aligned window around one anchor, at several lengths.
    This is the part the old engines skipped: they drafted one window per story and
    never explored the length/edge alternatives that often contain the better cut."""
    sents = _sentence_rows(segments)
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
            _enforce_window(c, segments, duration, reject_hype=True)
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
                _enforce_window(c, segments, duration, reject_hype=True)
                if c.get("_drop"):
                    continue
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
    chunks = [c for c in V._chunks(segments, max_chars=8500, max_chunks=max_chunks) if c]

    def _editor_chunk(chunk):
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
            return V._parse_json(ai_chat({
                "model": CONFIG["ai_model"],
                "messages": [{"role": "user", "content": prompt + V._owner_guidance()}],
                "temperature": 0.3,
            }))
        except Exception:
            return None

    # Chunks are independent. Parallel calls are the difference between a long
    # episode spending 20 minutes in the editor pass and spending five.
    try:
        workers = max(1, min(4, int(os.environ.get("CB_EDITOR_WORKERS", "2"))))
    except (TypeError, ValueError):
        workers = 3
    if len(chunks) > 1 and workers > 1 and has_brain():
        with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as pool:
            results = list(pool.map(_editor_chunk, chunks))
    else:
        results = [_editor_chunk(chunk) for chunk in chunks]
    for data in results:
        if not isinstance(data, dict):
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


def _pre_score(c):
    f = c.get("argo_features") or {}
    return (0.32 * f.get("hook", 0) + 0.24 * f.get("payoff", 0)
            + 0.16 * f.get("event", 0) + 0.10 * f.get("visual", 0)
            + 0.08 * f.get("emotion", 0) + 0.06 * f.get("shareability", 0)
            + 0.04 * f.get("self_sufficient", 0))


def _context_variants(cands, segments, duration, energy, laughs, moments, scenes, motion,
                      limit=8):
    """For the strongest candidates, also test the window that starts at the previous
    sentence. The common failure is a clip that opens on a question after the action
    already happened; the judge can only choose the better start if it sees both."""
    starts = [s["start"] for s in _sentence_rows(segments)]
    if not starts:
        return []
    out = []
    for c in sorted(cands, key=lambda x: -_pre_score(x))[:limit]:
        prev = [x for x in starts if x < c["start"] - 0.6 and c["start"] - x <= 10.0]
        if not prev:
            continue
        v = dict(c)
        v["start"] = round(max(prev), 2)
        v["anchor_kind"] = "context"
        v["context_variant"] = True
        _enforce_window(v, segments, duration, reject_hype=True)
        if v.get("_drop") or V._starts_on_filler(segments, v["start"]):
            continue
        measure_candidate(v, segments, energy, laughs, moments, scenes, motion)
        out.append(v)
    return out


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
        _enforce_window(c, segments, duration, reject_hype=True)
        if c.get("_drop") or V._starts_on_filler(segments, c["start"]):
            continue
        out.append(c)
    anchors = (_spark_anchors(sparks) + _payoff_anchors(segments, laughs)
               + _story_anchors(stories) + _peak_anchors(moments)
               + _emotion_anchors(segments)
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
    variants = _context_variants(cands, segments, duration, energy, laughs, moments,
                                 scenes, motion)
    if variants:
        cands = _dedupe(cands + variants, segments)[:MAX_CANDIDATES]
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
- "emotion_label": the dominant felt emotion in THIS exact window. Choose exactly
  one of: funny, suspense, shock, emotional, inspiring, angry, wholesome, hype,
  informative, awkward. A tense reveal is suspense, not funny. A crowd roar or a
  reaction sound is not comedy unless the words or action are actually comic.
- "emotion": 0-10 intensity of that dominant emotion. This is intensity, not a
  second vote on whether the clip is funny.
- "secondary_emotion": optional second label from the same list, or "" if none.
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
"emotion_label": "suspense", "secondary_emotion": "",
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


def _clean_emotion_label(value):
    """Map judge vocabulary onto the one taxonomy; unknown labels are not invented."""
    s = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    s = EMOTION_ALIASES.get(s, s)
    return s if s in EMOTION_LABELS else ""


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
        "emotion_label": c.get("emotion_label") or "informative",
        "secondary_emotion": "",
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
    # Free providers choke on a 14-candidate, 40k-character prompt. Small batches
    # are more reliable and let one failed batch fall back without losing the rest.
    if len(cands) > 3:
        chunks = [cands[i:i + 3] for i in range(0, len(cands), 3)]
        out = {}
        with ThreadPoolExecutor(max_workers=min(2, len(chunks))) as pool:
            results = list(pool.map(
                lambda part: _judge_batch(part, segments, content_type), chunks))
        for off, result in zip(range(0, len(cands), 3), results):
            for i, j in (result or {}).items():
                out[off + int(i)] = j
        return out
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
                "energy": c["measured"].get("energy", 0.0),
                "laughter": c["measured"].get("laughter", 0.0),
                "tail_laugh": c["measured"].get("tail_laugh", 0.0),
                "event": c["measured"].get("event", 0.0),
                "words_per_second": c.get("text_stats", {}).get("wps", 0.0),
                "starts_clean": c.get("text_stats", {}).get("starts_clean", True),
                "ends_on_sentence": c.get("text_stats", {}).get("ends_final", True),
                "shot_cuts_inside": c.get("text_stats", {}).get("scenes", 0),
                "context_dependency": c.get("text_stats", {}).get(
                    "context_dependency", 0.0),
                "list_incomplete": c.get("text_stats", {}).get("list_incomplete", 0.0),
                "boundary": c.get("text_stats", {}).get("boundary", 0.0),
                "opening": c.get("text_stats", {}).get("opening", 0.0),
                "opening_issue": c.get("text_stats", {}).get("opening_issue", ""),
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
            base_j = base.get(i)
            if not isinstance(base_j, dict):
                j = _offline_judgement(c)
            else:
                j = dict(base_j)
                if j.get("unjudged"):
                    # The shipped six-field judge answered without any judgement rows.
                    # That is a failed call, not an opinion: label it as measured-only
                    # so it can never be counted as a judge pass or a verified badge.
                    j = dict(_offline_judgement(c),
                             verdict="judge call incomplete - measured factors only")
            j.setdefault("emotion", 5)
            j.setdefault("emotion_label", c.get("emotion_label") or "informative")
            j.setdefault("secondary_emotion", "")
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
            "emotion_label": _clean_emotion_label(raw.get("emotion_label")),
            "secondary_emotion": _clean_emotion_label(raw.get("secondary_emotion")),
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
    # Reconcile the judge's label with the transcript. The judge sees the exact
    # words and gets the final call, except for one failure mode we can prove: it
    # calls a tense scene funny while the transcript contains suspense evidence and
    # no comedy cue. Acoustic bursts must never create a comedy label on their own.
    deterministic = _clean_emotion_label(c.get("emotion_label"))
    judge_label = _clean_emotion_label(j.get("emotion_label"))
    label = judge_label or deterministic or "informative"
    det_intensity = float((c.get("emotion") or {}).get("intensity", 0.0) or 0.0)
    mismatch = False
    if (judge_label == "funny" and not c.get("comedy_context")
            and deterministic in ("suspense", "shock", "emotional", "angry")
            and c.get("emotion_scores", {}).get(deterministic, 0.0) >= 0.25):
        mismatch = True
    # A weak judge often defaults a fast, overlapping conversation to "awkward" or
    # "informative". When the transcript has strong explicit cues for a different
    # emotion, keep the transcript's label and record the disagreement.
    if (judge_label in ("awkward", "informative") and deterministic
            and deterministic not in ("awkward", "informative")
            and det_intensity >= 0.55):
        mismatch = True
    if mismatch:
        label = deterministic
        flags = list(j.get("flags") or [])
        if "emotion_mismatch" not in flags:
            flags.append("emotion_mismatch")
        j["flags"] = flags
    c["emotion_label"] = label
    c["secondary_emotion"] = _clean_emotion_label(j.get("secondary_emotion"))
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
    # Keep the pre-judge measurements. A re-judge must start from these, not from the
    # already judge-blended factors, or the judge is folded in again on every pass.
    raw = c.get("raw_features") or dict(c.get("argo_features") or {})
    c["raw_features"] = dict(raw)
    c["argo_features"] = dict(raw)
    _apply_judge(c, j)
    # A funny sports clip is still a comedy cut. Without this, the sports profile
    # (event 2.4x, visual 1.9x) buries a team-radio punchline under engine noise.
    profile = "comedy" if (content_type or "").lower() == "sports" and c.get("emotion_label") == "funny" else content_type
    w = _weights(profile)
    f = c["argo_features"]
    blend = sum(w.get(k, 0.0) * f.get(k, 0.0) for k in w)
    wsum = sum(w.values()) or 1.0
    blend = max(0.0, min(1.0, blend / wsum))
    # The story engines' 30..99 calibration is kept for comparability, but a gated
    # candidate is multiplied by the same non-compensatory gate the score is built on.
    passed, gate_reasons = _gate(c, j)
    base_score = 30.0 + 69.0 * (blend ** 1.12)
    score = base_score
    steps = []

    def add(name, value):
        nonlocal score
        if abs(value) > 1e-9:
            score += value
            steps.append({"op": "add", "name": name, "value": round(value, 6)})

    def mul(name, value):
        nonlocal score
        if abs(value - 1.0) > 1e-9:
            score *= value
            steps.append({"op": "mul", "name": name, "value": round(value, 6)})

    def cap(name, value):
        nonlocal score
        if score > value:
            score = value
            steps.append({"op": "cap", "name": name, "value": round(value, 6)})

    if f.get("event", 0.0) >= 0.7:
        add("measured peak event", 3.5)
    # A 55-second "funny" radio clip is usually three unrelated exchanges stitched
    # together. Keep comedy focused; the same material scores better at 15-35s.
    dur = max(0.0, c["end"] - c["start"])
    if c.get("emotion_label") == "funny" and dur > 42.0:
        add("long comedy window", -min(9.0, 0.45 * (dur - 42.0)))
    if (content_type or "").lower() == "sports":
        # A sports highlight without the measured event is an interview, not a
        # highlight. Reward the roar/cut-density coverage and push a quiet talking
        # segment out of the podium instead of letting it win on coherence alone.
        add("sports event coverage", 8.0 * f.get("event", 0.0))
        add("sports visual coverage", 4.0 * f.get("visual", 0.0))
        add("sports action language", 10.0 * f.get("action", 0.0))
        if f.get("event", 0.0) < 0.20 and f.get("visual", 0.0) < 0.20:
            add("quiet sports window", -12.0)
        if f.get("action", 0.0) < 0.10:
            add("no action language", -6.0)
    flags = set(c.get("flags") or [])
    fatal = flags & FATAL_FLAGS
    if fatal:
        add("fatal flags", -min(17.0, 3.4 * len(fatal)))
    if flags & WARNING_FLAGS:
        add("warning flags", -min(7.0, 1.2 * len(flags & WARNING_FLAGS)))
    if not passed:
        mul("gate failed", 0.72)
    if j.get("ends_abrupt") or "ends_before_payoff" in flags:
        cap("dead ending", 54.0)
    if not j.get("alone", True) or "not_standalone" in flags:
        cap("not standalone", 47.0)
    if _num(j, "retention_3s", 5) <= 3.0:
        cap("weak 3s retention", 58.0)
    if _num(j, "retention_end", 5) <= 3.0:
        cap("weak end retention", 52.0)
    c["score"] = int(max(1.0, min(99.0, round(score))))
    c["score_trace"] = {
        "formula": "30 + 69 * blend^1.12, then the listed adjustments",
        "blend": round(blend, 4),
        "weights": {k: round(float(w.get(k, 0.0)), 3) for k in w},
        "factors": {k: round(float(f.get(k, 0.0)), 4) for k in w},
        "contributions": {k: round(float(w.get(k, 0.0) * f.get(k, 0.0)) / wsum, 4)
                          for k in w},
        "base": round(base_score, 6),
        "steps": steps,
        "gate": {"passed": passed, "reasons": gate_reasons},
        "judge": {"offline": bool(j.get("_offline")),
                  "emotion_label": c.get("emotion_label"),
                  "coherence": _num(j, "coherence"),
                  "payoff": _num(j, "payoff"),
                  "retention_3s": _num(j, "retention_3s"),
                  "retention_end": _num(j, "retention_end")},
        "final": c["score"],
    }
    c["score_trace"]["reproducible"] = verify_score(c)
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
    c["argon"]["emotion_label"] = c.get("emotion_label") or "informative"
    if c.get("secondary_emotion"):
        c["argon"]["secondary_emotion"] = c["secondary_emotion"]
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


def verify_score(c):
    """Recompute a clip's score from its own trace. This is the anti-fake check:
    if the displayed number cannot be reproduced from the recorded factors, weights,
    gate and adjustments, the trace is invalid."""
    t = c.get("score_trace") or {}
    try:
        weights = t.get("weights") or {}
        factors = t.get("factors") or {}
        if not weights or not factors:
            return False
        wsum = sum(float(v) for v in weights.values()) or 1.0
        blend = sum(float(weights.get(k, 0.0)) * float(factors.get(k, 0.0))
                    for k in weights) / wsum
        derived = 30.0 + 69.0 * (max(0.0, min(1.0, blend)) ** 1.12)
        if abs(derived - float(t["base"])) > 0.02:
            return False
        score = float(t["base"])
        for step in t.get("steps") or []:
            op, value = step.get("op"), float(step.get("value", 0.0))
            if op == "add":
                score += value
            elif op == "mul":
                score *= value
            elif op == "cap":
                score = min(score, value)
            else:
                return False
        final = int(max(1.0, min(99.0, round(score))))
        return final == int(c.get("score"))
    except (KeyError, TypeError, ValueError):
        return False


def audit_clips(clips):
    """Recompute every displayed score from its trace. Used by the API and tests."""
    out = []
    for i, c in enumerate(clips or []):
        t = c.get("score_trace") or {}
        out.append({
            "index": i,
            "score": c.get("score"),
            "trace_final": t.get("final"),
            "reproducible": verify_score(c),
            "qc": c.get("qc"),
            "emotion": c.get("emotion_label"),
            "tier": c.get("tier"),
        })
    return out


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
    sents = _sentence_rows(segments)
    if not sents:
        return False
    moved = False
    starts = [s["start"] for s in sents]
    ends = [s["end"] for s in sents]
    before = (c["start"], c["end"])

    # 0) A dangling conjunction or a two-word fragment: prefer the previous
    #    sentence (it supplies the missing context), else the next full sentence.
    issue = (c.get("text_stats") or {}).get("opening_issue")
    if issue in ("dangling", "fragment"):
        prev = [s for s in starts if s < c["start"] and c["start"] - s <= 10.0]
        nxt = [s for s in starts if s > c["start"] and s - c["start"] <= 8.0]
        if prev and c["end"] - max(prev) <= MAX_S:
            c["start"] = max(prev)
            moved = True
        elif nxt and c["end"] - nxt[0] >= MIN_S:
            c["start"] = nxt[0]
            moved = True

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
                  if c["start"] <= s["start"] <= c["start"] + 7.0
                  and s["pull"] >= 0.6]
        if sparks and c["end"] - sparks[0]["start"] >= MIN_S:
            c["start"] = sparks[0]["start"]
            moved = True

    # 3) Dead ending: extend to the NEXT sentence end, then to a near laugh if one
    #    is there. Taking the furthest end inside 18s used to swallow three extra
    #    sentences and overshoot the payoff; the nearest end is the smallest fix.
    if flags & {"ends_before_payoff", "no_payoff", "weak_ending", "list_incomplete"} \
            or j.get("ends_abrupt") or j.get("payoff", 5) < 5:
        later = [e for e in ends if e > c["end"] and e <= c["end"] + 18.0]
        if later:
            c["end"] = min(duration, later[0])
            moved = True
        for lstart, lend, _peak in (laughs or []):
            if c["end"] - 0.5 <= float(lstart) <= c["end"] + 8.0 \
                    and float(lend) > c["end"] and float(lend) - c["start"] <= MAX_S:
                c["end"] = min(duration, float(lend) + 0.3)
                c["laugh_ending"] = True
                moved = True
                break

    # 4) Too long: trim the front to the LONGEST window the band allows. Keeping the
    #    payoff means keeping the end; the old code trimmed to the 10s minimum and
    #    threw away the setup the payoff depends on.
    if flags & {"too_long"} or c["end"] - c["start"] > MAX_S:
        keep = [s for s in starts
                if c["end"] - MAX_S <= s <= c["end"] - MIN_S]
        if keep:
            c["start"] = keep[0]
            moved = True

    if not moved:
        return False
    _enforce_window(c, segments, duration, reject_hype=True)
    if c.get("_drop"):
        # The only legal version of this repair would open on a greeting. Keep the
        # original (already validated) window instead of deleting a measured candidate.
        c["start"], c["end"] = before
        c.pop("_drop", None)
        return False
    return (c["start"], c["end"]) != before


def _needs_repair(c):
    """A candidate earns a repair pass when it failed the gate, carries a fatal flag,
    or names a defect the deterministic repairs can actually fix."""
    if not (c.get("gate") or {}).get("passed", True):
        return True
    flags = set(c.get("flags") or [])
    if flags & (FATAL_FLAGS | REPAIRABLE_FLAGS):
        return True
    j = c.get("judge") or {}
    return bool(j.get("ends_abrupt") or not j.get("alone", True))


def _repair_pool(pool, segments, duration, laughs, scenes, energy, moments,
                 content_type, motion):
    """Repair up to MAX_REPAIR failing candidates, then re-measure and re-judge them.
    The highest-potential failures are repaired first. Repairs are deterministic, so
    they run without a brain too; the re-judge is then the honest offline one."""
    broken = sorted([c for c in pool if _needs_repair(c)],
                    key=lambda c: -(c.get("score") or 0))
    if not broken:
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
    return (c.get("qc") == "verified"
            or c["measured"].get("tail_laugh", 0.0) >= 0.25
            or c["argo_features"].get("boundary", 0.0) >= 0.65)


def _temporal_iou(a, b):
    """How much two windows are the same span of the source. A shared ending with a
    different start is often the same payoff cut twice; a shared start with a different
    ending can be a genuinely different edit, so the union is the honest denominator."""
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(1e-6, max(a["end"], b["end"]) - min(a["start"], b["start"]))
    return inter / union


def _contained(a, b):
    """Is one window essentially a sub-clip of the other? A 14s cut inside a 56s
    cut of the same overtake is not a second highlight."""
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    shortest = max(1e-6, min(a["end"] - a["start"], b["end"] - b["start"]))
    return inter / shortest > 0.65


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
    # Quality over a fixed count. A "usable" clip with measured defects is not a
    # highlight; return fewer strong cuts rather than pad the podium with one.
    passing = [c for c in candidates
               if c.get("tier") in ("viral", "strong") and _ends_well(c)]
    # Spread grows with the source, but not without bound. 8% of a three-hour podcast
    # is eight minutes, which would refuse two honest beats a minute apart and leave a
    # one-clip podium. Cap the floor at 60s of separation.
    spread = min(120.0, max(14.0, 0.08 * duration))
    min_gap = min(60.0, max(8.0, spread * 0.55))
    picked = []
    for c in passing:
        if len(picked) >= count:
            break
        if c in picked or c.get("tier") == "reject":
            continue
        if any(abs(c["start"] - p["start"]) < min_gap for p in picked):
            continue
        if any(abs(c["end"] - p["end"]) < 2.0 for p in picked):
            continue
        if any(_temporal_iou(c, p) > 0.45 for p in picked):
            continue
        if any(_contained(c, p) for p in picked):
            continue
        if any(_similarity(c, p, segments, spread) > 0.78 for p in picked):
            continue
        # MMR: a high score can still lose to a different beat. The penalty is
        # bounded so quality remains the dominant term. A small emotion-diversity
        # bonus keeps the podium from being three versions of the same laugh when
        # a different emotional beat is nearly as strong.
        same_emotion = sum(1 for p in picked
                           if p.get("emotion_label") == c.get("emotion_label"))
        new_emotion = bool(picked) and same_emotion == 0
        val = (c["score"] / 100.0 - 0.16 * max(
            [_similarity(c, p, segments, spread) for p in picked] or [0.0])
            - 0.03 * same_emotion + (0.025 if new_emotion else 0.0))
        c["_mmr"] = round(val, 4)
        picked.append(c)
    # If the strict spread leaves the podium short, keep it short. Filling the third
    # slot with a usable-but-flawed clip is how a "top 3" becomes a "top 2 plus filler".
    if not picked:
        # A usable cut (score 60-74, gate passed) is a real result even if it did not
        # reach the "strong" band; keep the strongest one as a one-clip podium.
        honest = [c for c in candidates if c.get("tier") != "reject"]
        if honest:
            picked = [honest[0]]
        elif all((c.get("judge") or {}).get("_offline") for c in candidates):
            # A measured-only run has no judge that could reject anything. Returning
            # the strongest measured window (labelled reject/unverified) is honest and
            # useful. With a real judge, a gate-rejected cut must never be presented
            # as a highlight: the pipeline reports the empty podium instead.
            picked = [candidates[0]]
    for c in picked:
        c["selected"] = True
    return picked


# ---------------------------------------------------------------- public entry

def _measured_fallback(duration, count, energy, laughs, moments, scenes, motion):
    """No transcript: still return measured, scored windows instead of bare spans.

    A release build without an STT key used to render an even window with score=None,
    no emotion and no trace. That looked broken. The audio/visual measurements are
    still real, so use them and label the result as measured-only.
    """
    wins = V._even_windows(duration, count)
    cands = []
    for w in wins:
        c = dict(w)
        try:
            measure_candidate(c, [], energy, laughs, moments or [], scenes, motion)
            score_candidate(c, _offline_judgement(c), "other")
        except Exception:
            c.setdefault("score", 1)
            c.setdefault("tier", "reject")
            c.setdefault("qc", "unverified")
            c.setdefault("factors", {})
            c.setdefault("argon", {})
            c.setdefault("flags", [])
            c.setdefault("gate", {"passed": False, "reasons": ["no transcript"]})
        c["title"] = c.get("title") or "Measured highlight"
        c["hook"] = c.get("hook") or ""
        c["reason"] = "no transcript; measured audio/visual only"
        c["verdict"] = "measured only - no transcript or judge"
        c["qc"] = "unverified"
        cands.append(c)
    return cands, cands, "argon-measured", "other"


def rank(segments, duration, count=3, energy=None, laughs=None, scenes=None,
         cinema_marks=None, motion=None):
    """ARGON's full pass. Same return contract as virality.rank / apex.rank:
    (picked_moments, candidate_pool, picker, content_type)."""
    count = max(1, min(8, int(count or 3)))
    if not segments:
        return _measured_fallback(duration, count, energy, laughs, [],
                                  scenes, motion)

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
        return _measured_fallback(duration, count, energy, laughs, moments,
                                  scenes, motion)
    cands.sort(key=lambda c: -(
        0.32 * c["argo_features"]["hook"]
        + 0.24 * c["argo_features"]["payoff"]
        + 0.16 * c["argo_features"]["event"]
        + 0.10 * c["argo_features"]["visual"]
        + 0.08 * c["argo_features"]["emotion"]
        + 0.06 * c["argo_features"]["shareability"]
        + 0.04 * c["argo_features"]["self_sufficient"]))
    # The deterministic pre-score is a cheap shortlist, not a veto. An editor
    # proposal or a measured peak that sits outside the top N must still reach the
    # judge: those are exactly the moments a pure lexical score misses (an overtake,
    # a goal, a reveal). Keep the shortlist bounded.
    pool = list(cands[:MAX_JUDGE])
    # Coverage, not just lexical rank. A 68-minute interview can have all of its
    # highest pre-scores in the first two minutes; without one candidate per time
    # slice the judge never sees the rest of the episode and the podium cannot
    # cover it. Add the best measured candidate from each slice.
    slices = 6 if duration >= 2400 else 4 if duration >= 900 else 3
    for i in range(slices):
        lo, hi = duration * i / slices, duration * (i + 1) / slices
        inside = [c for c in cands if lo <= c["start"] < hi]
        if not inside:
            continue
        best = max(inside, key=_pre_score)
        if best not in pool and len(pool) < MAX_JUDGE + slices:
            pool.append(best)
    def _force(kind, n):
        return sorted([c for c in cands if c.get("anchor_kind") == kind],
                      key=lambda c: -_pre_score(c))[:n]
    forced = _force("editor", 3) + _force("context", 3) + _force("peak", 3)
    for c in forced:
        if c not in pool and len(pool) < MAX_JUDGE + slices + 6:
            pool.append(c)
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


def rejudge_clips(clips, segments, content_type="other"):
    """Re-judge already-rendered ARGON clips with the ARGON judge and re-score them.
    The legacy virality.rejudge path expects candidate measurements and can leave the
    tier stale; this keeps gate, score and tier on the same judge. Returns verified."""
    if not clips or not has_brain():
        return 0
    pool = []
    for clip in clips:
        c = dict(clip)
        feats = {}
        raw = clip.get("raw_features") or {}
        if raw:
            for k, v in raw.items():
                if k in FEATURES and isinstance(v, (int, float)):
                    feats[k] = max(0.0, min(1.0, float(v)))
        else:
            for source in (clip.get("factors") or {}, clip.get("argon") or {}):
                for k, v in source.items():
                    if k in FEATURES and isinstance(v, (int, float)):
                        feats[k] = max(0.0, min(1.0, float(v) / 100.0))
        c["raw_features"] = dict(feats)
        c["argo_features"] = dict(feats)
        c["hook_speed"] = float(clip.get("hook_speed")
                                or (clip.get("argon") or {}).get("hook_speed", 0) / 100.0)
        c["measured"] = dict(clip.get("measured") or {})
        c["emotion_label"] = clip.get("emotion_label") or ""
        c["emotion_scores"] = dict(clip.get("emotion_scores") or {})
        c["emotion"] = dict(clip.get("emotion") or {})
        if not c["emotion"] and c["emotion_scores"]:
            c["emotion"] = {"intensity": max(c["emotion_scores"].values())}
        c["comedy_context"] = bool(clip.get("comedy_context"))
        c["flags"] = list(clip.get("flags") or [])
        c["text_stats"] = {
            "wps": 0.0,
            "starts_clean": feats.get("opening", 0.0) >= 0.5,
            "ends_final": feats.get("boundary", 0.0) >= 0.5,
            "scenes": 0,
            "context_dependency": feats.get("context_dependency", 0.0),
            "list_incomplete": 0.0,
            "boundary": feats.get("boundary", 0.0),
            "opening": feats.get("opening", 0.0),
        }
        # Prefer the measurements stored with the rendered clip. Older clips have none;
        # for them list_incomplete is unknown (0.0), not the failure_risk value.
        if isinstance(clip.get("text_stats"), dict):
            c["text_stats"].update(
                {k: v for k, v in clip["text_stats"].items()
                 if k in c["text_stats"]
                 and isinstance(v, (int, float, bool, str))})
        pool.append(c)
    judgments = _judge_batch(pool, segments, content_type)
    verified = 0
    for i, c in enumerate(pool):
        score_candidate(c, judgments.get(i) or _offline_judgement(c), content_type)
        clip = clips[i]
        for key in ("score", "tier", "qc", "verdict", "reason", "factors",
                    "argon", "flags", "gate", "emotion_label",
                    "secondary_emotion", "emotion_scores", "comedy_context",
                    "score_trace", "raw_features", "hook_speed", "text_stats"):
            if key in c:
                clip[key] = c[key]
        if clip.get("qc") == "verified":
            verified += 1
    return verified


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
