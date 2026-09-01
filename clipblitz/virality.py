"""ProX v5 — The AI Editor.

Not a scorer bolted onto timestamps: an editor's workflow.

  1. STORY PASS    the whole episode is segmented into self-contained stories
  2. DRAFT PASS    the tightest 15-60s cut is drafted INSIDE each promising story,
                   with the full story transcript in context (never blind boundaries)
  3. EDGE RULES    deterministic polish: snap to sentence edges, never start on filler,
                   end on punctuation or laughter, extend through the laugh
  4. JUDGE PASS    every FINAL cut is judged on its exact verbatim transcript:
                   alone? starts/ends abruptly? coherence/hook/payoff 0-10.
                   Failing cuts get ONE feedback-informed redraw, then demotion.
  5. SCORE v2      computed from the judge's ratings of the exact final cut +
                   measured audio factors (laughter, energy, pacing). The score
                   literally follows the content, and every clip shows its verdict.

Dual-brain: every call runs on the primary provider and fails over to the secondary
(Gemini) on rate limits / errors / empty answers. Every number traces to a measurement
or a judgement of the actual cut.
"""

import json
import math
import os
import re
import urllib.request

from .config import CONFIG
from .brains import ai_chat  # dual-brain chat with failover
from .ffmpeg_tools import laughter_score  # measured audience-laughter scoring

WEIGHTS = {"hook": 0.26, "story": 0.26, "payoff": 0.18, "energy": 0.16, "pacing": 0.14}
WEIGHT_PROFILES = {
    "comedy":    {"hook": 0.24, "story": 0.22, "payoff": 0.16, "energy": 0.22, "pacing": 0.16},
    "podcast":   {"hook": 0.24, "story": 0.24, "payoff": 0.16, "energy": 0.20, "pacing": 0.16},
    "interview": {"hook": 0.24, "story": 0.24, "payoff": 0.16, "energy": 0.20, "pacing": 0.16},
    "speech":    {"hook": 0.26, "story": 0.26, "payoff": 0.18, "energy": 0.16, "pacing": 0.14},
    "tutorial":  {"hook": 0.24, "story": 0.30, "payoff": 0.16, "energy": 0.12, "pacing": 0.18},
    "vlog":      {"hook": 0.26, "story": 0.22, "payoff": 0.16, "energy": 0.20, "pacing": 0.16},
}


def _weights(content_type):
    return WEIGHT_PROFILES.get((content_type or "").lower(), WEIGHTS)


STORY_PROMPT = """You are a long-form video editor watching a {content_hint} video via its transcript.
Below is a timestamped transcript CHUNK ({chunk_no}/{chunks}) of a {duration:.0f}s video.

Segment THIS CHUNK into self-contained STORIES: a moment with a beginning, a development,
and an ending — a joke and its laugh, a question and its answer, a claim and its payoff.
Stories must NOT overlap and must cover the interesting parts of the chunk. Prefer moments
with emotion, tension, punchlines, laughs, surprises. 10-120s each.

Transcript chunk:
{transcript}

Return ONLY compact JSON, no markdown:
{{"content_type": "podcast|tutorial|vlog|interview|speech|comedy|other",
"stories": [{{"start": 12.5, "end": 48.0, "summary": "one line: what happens",
"hook_line": "the spoken line that should open the short, <= 12 words",
"payoff": "one line: how it lands/ends"}}]}}
"""

DRAFT_PROMPT = """You are a short-form editor. Below are stories from one video (JSON: each has a
verbatim transcript with per-sentence timestamps, a summary, and how it pays off).

For EACH story draft the tightest possible vertical-short cut:
- 15-60 seconds, cutting INSIDE the story only
- start exactly where the hook thought begins (never mid-answer, never on filler like "um/so/like/yeah")
- end right after the payoff (or right where the reaction/laugh peaks)
- prefer cutting slow warm-up lines; keep the exchange that carries the story

Stories:
{stories}

Return ONLY compact JSON, no markdown:
{{"cuts": [{{"index": 0, "start": 100.5, "end": 138.0, "title": "6-word viral title",
"hook_line": "spoken opening line, <= 12 words"}}]}}
"""

JUDGE_PROMPT = """You are the strict QC judge for finished vertical shorts. For EACH clip below you
get the EXACT transcript the viewer will see — nothing else. Judge it as a standalone short.

Clips:
{clips}

For each clip return:
- "alone": can this exact text be understood with NO other context? (true/false)
- "starts_abrupt": does it open mid-thought / answering an unheard question? (true/false)
- "ends_abrupt": does it stop before the thought or payoff completes? (true/false)
- "coherence": 0-10 as a standalone story
- "hook": 0-10 for the first ~2 lines stopping a scroll
- "payoff": 0-10 for the ending landing
- "verdict": one short line for the creator (what makes it work / what hurts it)

Return ONLY compact JSON, no markdown:
{{"judgements": [{{"index": 0, "alone": true, "starts_abrupt": false, "ends_abrupt": false,
"coherence": 8, "hook": 7, "payoff": 8, "verdict": "..."}}]}}
"""

REPAIR_PROMPT = """You are a short-form editor. This cut FAILED the QC judge:
clip window: {start:.1f}s → {end:.1f}s
judge complaint: {complaint}

Here is the verbatim transcript around the clip (timestamps per sentence):
{context}

Re-draw the window so the complaint is fixed: {start:.1f}s and {end:.1f}s are hints, you may
move each by up to ~25s in either direction. Keep 15-60s. Start where the thought starts,
end after the payoff.

Return ONLY compact JSON, no markdown:
{{"start": 98.0, "end": 141.5}}
"""


# ---------------------------------------------------------------- transcript helpers

def _parse_json(text):
    raw = re.search(r"\{[\s\S]*\}", text)
    if not raw:
        raise ValueError("no JSON object in model output")
    return json.loads(raw.group(0))


def _as_list(x):
    """Models sometimes return {"stories": {...}} or a bare list — coerce to a list."""
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return list(x.values())
    return []


def _as_float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _transcript(segments):
    return "\n".join(f"[{s['start']:.0f}-{s['end']:.0f}] {s['text']}" for s in segments)


def _words_in(segments, a, b):
    out = []
    for s in segments:
        for w in s.get("words", []):
            if w["end"] > a and w["start"] < b:
                out.append(w)
    return out


def _text_in(segments, a, b, cap=450):
    parts = [s["text"] for s in segments if s.get("text") and s["end"] > a and s["start"] < b]
    return " ".join(parts).strip()[:cap]


def _chunks(segments, max_chars=8500, max_chunks=24):
    if not segments:
        return []
    lines = [(s, f"[{s['start']:.0f}-{s['end']:.0f}] {s['text']}") for s in segments]
    total = sum(len(t) for _, t in lines)
    n = max(1, min(max_chunks, -(-total // max_chars)))
    per = -(-len(lines) // n)
    return [[seg for seg, _ in lines[i:i + per]] for i in range(0, len(lines), per)]


def _sentences(segments, a=None, b=None):
    """Verbatim sentence list [{start,end,text}] inside [a,b] (segment-level timing)."""
    out = []
    for s in segments:
        if not s.get("text") or s["end"] <= s["start"]:
            continue
        if a is not None and (s["end"] <= a or s["start"] >= b):
            continue
        out.append({"start": s["start"], "end": s["end"], "text": s["text"].strip()})
    return out


# ---------------------------------------------------------------- 1. story pass

def segment_stories(segments, duration):
    """LLM segments the whole episode into self-contained stories (chunked, merged)."""
    stories, votes = [], {}
    chunks = _chunks(segments)
    for i, chunk in enumerate(chunks):
        prompt = STORY_PROMPT.format(
            content_hint="long-form" if len(chunks) > 1 else "short-form",
            chunk_no=i + 1, chunks=len(chunks), duration=duration,
            transcript=_transcript(chunk)[:8500],
        )
        try:
            data = _parse_json(ai_chat({
                "model": CONFIG["ai_model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            }))
        except Exception:
            continue
        ct = data.get("content_type")
        if ct:
            votes[ct] = votes.get(ct, 0) + 1
        for st in _as_list(data.get("stories")):
            if not isinstance(st, dict):
                continue
            a = _as_float(st.get("start"))
            b = _as_float(st.get("end"))
            if a is None or b is None:
                continue
            a, b = max(0.0, a), min(duration, b)
            if 8 <= b - a <= 130:
                stories.append({
                    "start": a, "end": b,
                    "summary": (st.get("summary") or "")[:120],
                    "hook_line": (st.get("hook_line") or "")[:120],
                    "payoff": (st.get("payoff") or "")[:120],
                })
    content_type = max(votes, key=votes.get) if votes else "other"
    return stories, content_type


def stories_offline(segments, duration, energy, laughs, want=14):
    """No LLM: sentence-aligned windows ranked by measured laughter+energy."""
    series, mean_db = energy if energy else ([], -30.0)
    sents = [s for s in segments if (s.get("text") or s.get("words")) and s["end"] > s["start"]]
    if not sents:
        return []
    out, i = [], 0
    while i < len(sents):
        a = sents[i]["start"]
        j = i
        while j < len(sents) - 1 and sents[j]["end"] - a < 30:
            j += 1
        b = max(sents[j]["end"], a + 12)
        b = min(b, a + 90, duration)
        if b - a >= 10:
            laugh = laughter_score(laughs or [], a, b)
            vals = [db for t, db in series if a <= t <= b]
            energy_f = 1.0 / (1.0 + math.exp(-((sum(vals) / len(vals)) - mean_db) / 3.0)) if vals else 0.45
            out.append({"start": a, "end": b,
                        "summary": _text_in(segments, a, b, 90),
                        "hook_line": " ".join(w["word"] for w in _words_in(segments, a, a + 4)[:10]),
                        "payoff": "",
                        "_signal": 0.6 * laugh + 0.4 * energy_f})
        i = j + 1
    out.sort(key=lambda s: -s["_signal"])
    picked = []
    for st in out:
        if all(abs(st["start"] - p["start"]) > 90 for p in picked):
            picked.append(st)
        if len(picked) >= want:
            break
    for st in picked:
        st.pop("_signal", None)
    return picked


# ---------------------------------------------------------------- edge rules

FILLER_STARTS = {"um", "uh", "so", "and", "but", "like", "yeah", "okay", "ok", "well",
                 "basically", "anyway", "actually", "right", "exactly", "true"}


def _starts_on_filler(segments, a):
    words = [w["word"].strip(".,!?…").lower() for w in _words_in(segments, a, a + 3.5)][:3]
    if not words:
        text = (_text_in(segments, a, a + 4, 60) or "").lower()
        words = text.split()[:3]
    return any(w in FILLER_STARTS for w in words)


def snap(candidate, segments, duration, pad=3.0):
    """Snap start/end to sentence edges; skip filler openings; end on punctuation.
    No clip ever opens with 'um' or stops mid-word."""
    bounds = [(s["start"], s["end"], (s.get("text") or "").strip()) for s in segments
              if s.get("text") and s["end"] > s["start"]]
    if not bounds:
        candidate["start"], candidate["end"] = round(candidate["start"], 2), round(candidate["end"], 2)
        return candidate

    starts_all = [b[0] for b in bounds]
    ends_all = [b[1] for b in bounds]

    # START: nearest sentence start; if it's filler, advance to the next real one
    start = min(starts_all, key=lambda s: abs(s - candidate["start"]))
    if _starts_on_filler(segments, start):
        after = [s for s in starts_all if start + 0.2 <= s <= start + 14]
        if after and not _starts_on_filler(segments, after[0]):
            start = after[0]

    # END: nearest sentence end; if the tail doesn't look finished, take the next finished one
    end = min(ends_all, key=lambda e: abs(e - candidate["end"]))
    tail = _text_in(segments, end - 6, end + 0.5, 80)
    if tail and not re.search(r"[.!?…]\s*$", tail):
        finished = [e for s, e, t in bounds if end < e <= end + 8 and re.search(r"[.!?…]\s*$", t)]
        if finished:
            end = finished[0]
    end = min(duration, max(end, start + 10))
    if end - start > 90:
        ok = [e for s, e, t in bounds if start + 15 <= e <= start + 90]
        end = max(ok) if ok else start + 90
    candidate["start"], candidate["end"] = round(max(0.0, start), 2), round(end, 2)
    return candidate


def extend_through_laughter(cands, laughs, duration, segments, pad=2.0, max_ext=12.0):
    """Land the ending ON the laugh: stretch through the burst, then re-snap."""
    if not laughs:
        return
    for c in cands:
        best = None
        for s, e, _peak in laughs:
            if c["end"] - 1.0 <= s <= c["end"] + pad and e > c["end"]:
                if best is None or e > best[1]:
                    best = (s, e)
        if best:
            new_end = min(duration, best[1] + 0.3, c["end"] + max_ext)
            if new_end - c["start"] <= 90 and new_end > c["end"]:
                c["end"] = round(new_end, 2)
                c["laugh_ending"] = True
                snap(c, segments, duration)


# ---------------------------------------------------------------- 2. draft pass

def draft_cuts(stories, segments, laughs, energy, content_type, duration):
    """Pre-rank stories by measured signal, then batched LLM calls drafting the
    tightest cut inside each — with the full story transcript in context."""
    series, mean_db = energy if energy else ([], -30.0)
    for st in stories:
        laugh = laughter_score(laughs or [], st["start"], st["end"])
        vals = [db for t, db in series if st["start"] <= t <= st["end"]]
        energy_f = 1.0 / (1.0 + math.exp(-((sum(vals) / len(vals)) - mean_db) / 3.0)) if vals else 0.45
        st["_signal"] = 0.45 * laugh + 0.55 * energy_f
    stories.sort(key=lambda s: -s["_signal"])
    shortlist = []
    for st in stories:  # keep spread: min 90s apart
        if all(abs(st["start"] - p["start"]) > 90 for p in shortlist):
            shortlist.append(st)
        if len(shortlist) >= 12:
            break

    cuts = []
    for bi in range(0, len(shortlist), 4):
        batch = shortlist[bi:bi + 4]
        payload = []
        for k, st in enumerate(batch):
            sents = _sentences(segments, st["start"], st["end"])
            payload.append({
                "index": k, "summary": st["summary"], "payoff": st["payoff"],
                "hook_line": st["hook_line"],
                "transcript": "\n".join(f"[{s['start']:.1f}] {s['text']}" for s in sents)[:1800],
            })
        try:
            data = _parse_json(ai_chat({
                "model": CONFIG["ai_model"],
                "messages": [{"role": "user", "content": DRAFT_PROMPT.format(
                    stories=json.dumps(payload, ensure_ascii=False))}],
                "temperature": 0.3,
            }))
        except Exception:
            continue
        for c in _as_list(data.get("cuts")):
            if not isinstance(c, dict):
                continue
            k = int(c.get("index", -1) if _as_float(c.get("index")) is not None else -1)
            if not 0 <= k < len(batch):
                continue
            st = batch[k]
            a = _as_float(c.get("start"))
            b = _as_float(c.get("end"))
            if a is None or b is None:
                continue
            a = max(a, max(st["start"] - 20, 0.0))
            b = min(b, min(st["end"] + 20, duration))
            if not (8 <= b - a <= 95):
                continue
            cuts.append({"start": a, "end": b,
                         "title": (c.get("title") or st["summary"])[:80],
                         "hook": (c.get("hook_line") or st["hook_line"])[:120],
                         "story_summary": st["summary"]})
    return cuts


# ---------------------------------------------------------------- measuring

def _energy_in(series, mean_db, a, b):
    vals = [db for t, db in series if a <= t <= b]
    if not vals or mean_db <= -89:
        return 0.45
    delta = (sum(vals) / len(vals)) - mean_db
    f = 1.0 / (1.0 + math.exp(-delta / 3.0))
    if vals and (max(vals) - mean_db) > 8:
        f = min(1.0, f + 0.15)
    return f


def _pacing(segments, a, b):
    n = len(_words_in(segments, a, b))
    if not n:
        return 0.4
    wps = n / max(1.0, b - a)
    return math.exp(-((wps - 2.8) ** 2) / (2 * 0.9 ** 2))


def measure(cands, segments, energy, laughs):
    """Deterministic factors per cut (no AI): energy (laugh-boosted), pacing, laughter."""
    series, mean_db = energy if energy else ([], -30.0)
    for c in cands:
        if not isinstance(c, dict):
            continue
        a, b = c["start"], c["end"]
        laugh = laughter_score(laughs or [], a, b) if laughs else 0.0
        energy_f = _energy_in(series, mean_db, a, b)
        if laughs:
            energy_f = min(1.0, 0.35 * energy_f + 0.65 * laugh)
        c["laugh"] = laugh
        c["measured"] = {"energy": energy_f, "pacing": _pacing(segments, a, b), "laughter": laugh}
    return cands


# ---------------------------------------------------------------- 4. judge pass

def _clip_verbatim(segments, a, b, cap=900):
    return _text_in(segments, a, b, cap)


def judge_cuts(cands, segments):
    """The QC gate: judges the EXACT verbatim text of each final cut.
    Returns {index: judgement}. Raises on total failure (caller falls back honestly)."""
    payload = [{"index": i, "title": c.get("title", ""),
                "verbatim": _clip_verbatim(segments, c["start"], c["end"])}
               for i, c in enumerate(cands)]
    data = _parse_json(ai_chat({
        "model": CONFIG["ai_model"],
        "messages": [{"role": "user", "content": JUDGE_PROMPT.format(
            clips=json.dumps(payload, ensure_ascii=False))}],
        "temperature": 0.2,
    }))
    out = {}
    for j in _as_list(data.get("judgements")):
        if not isinstance(j, dict):
            continue
        i = int(j.get("index", -1) if _as_float(j.get("index")) is not None else -1)
        if 0 <= i < len(cands):
            out[i] = j
    for i in range(len(cands)):
        out.setdefault(i, {"alone": True, "starts_abrupt": False, "ends_abrupt": False,
                           "coherence": 5, "hook": 5, "payoff": 5,
                           "verdict": "unjudged (judge call incomplete)"})
    return out


def judge_fail(j):
    if not isinstance(j, dict):
        return True
    return (not j.get("alone", True)) or bool(j.get("starts_abrupt")) or bool(j.get("ends_abrupt")) \
        or int(j.get("coherence", 0) if isinstance(j.get("coherence"), (int, float)) else 0) < 7


def repair_cut(cand, complaint, segments, duration):
    """One feedback-informed redraw of a failing window."""
    sents = _sentences(segments, max(0.0, cand["start"] - 30), cand["end"] + 30)
    try:
        data = _parse_json(ai_chat({
            "model": CONFIG["ai_model"],
            "messages": [{"role": "user", "content": REPAIR_PROMPT.format(
                start=cand["start"], end=cand["end"], complaint=complaint[:220],
                context="\n".join(f"[{s['start']:.1f}] {s['text']}" for s in sents)[:2400])}],
            "temperature": 0.3,
        }))
        a, b = float(data["start"]), float(data["end"])
    except Exception:
        return False
    if 8 <= b - a <= 95 and a >= 0 and b <= duration + 1:
        cand["start"], cand["end"] = max(0.0, a), min(duration, b)
        cand["repaired"] = True
        return True
    return False


# ---------------------------------------------------------------- 5. score v2

def _verdict_reason(j, c):
    def _n(x):
        return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0
    bits = []
    if c.get("laugh", 0) > 0.25:
        bits.append("real laughter on the payoff")
    if _n(j.get("coherence")) >= 8:
        bits.append("stands fully alone")
    if _n(j.get("hook")) >= 8:
        bits.append("scroll-stopping opening")
    if not bits:
        bits.append((j.get("verdict") or "balanced clip").rstrip("."))
    dur = c["end"] - c["start"]
    return f"{bits[0].capitalize()}{(', ' + bits[1]) if len(bits) > 1 else ''} — {dur:.0f}s"


def score_v2(cand, j, content_type):
    """Score from the judge's ratings of the exact cut + measured factors."""

    def _score10(x, default=5):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return max(0, min(10, float(x)))
        return default

    w = _weights(content_type)
    factors = {
        "hook": max(0.0, min(1.0, _score10(j.get("hook")) / 10.0)),
        "story": max(0.0, min(1.0, _score10(j.get("coherence")) / 10.0)),
        "payoff": max(0.0, min(1.0, _score10(j.get("payoff")) / 10.0)),
        "energy": cand["measured"]["energy"],
        "pacing": cand["measured"]["pacing"],
    }
    blend = sum(w[k] * v for k, v in factors.items())
    score = int(round(30 + 69 * (blend ** 1.15)))
    cand["factors"] = {k: int(round(v * 100)) for k, v in factors.items()}
    cand["factors"]["laughter"] = int(round(cand["measured"]["laughter"] * 100))
    cand["score"] = max(1, min(99, score))
    cand["verdict"] = (j.get("verdict") or "").strip()[:160]
    cand["qc"] = "verified" if not judge_fail(j) else "unverified"
    cand["reason"] = _verdict_reason(j, cand)
    return cand


_OFFLINE_J = {"alone": True, "coherence": 6, "hook": 6, "payoff": 6,
              "verdict": "offline mode — measured factors only, no QC judge"}


# ---------------------------------------------------------------- pipeline entry

def rejudge(clips, segments, content_type):
    """Second-chance QC: re-judge rendered clips (e.g. after a rate-limit cooldown)
    and refresh their scores/verdicts. Windows are untouched. Returns # verified."""
    if not clips:
        return 0
    judgements = judge_cuts(clips, segments)
    verified = 0
    for i, c in enumerate(clips):
        j = judgements.get(i) or dict(_OFFLINE_J, verdict="judge unavailable — measured factors only")
        score_v2(c, j, content_type)
        if c.get("qc") == "verified":
            verified += 1
    return verified


def rank(segments, duration, count=3, energy=None, laughs=None):
    """Full ProX v5 pass. Returns (final_moments, all_candidates, picker, content_type)."""
    ai_ok = bool(CONFIG["ai_key"])
    content_type, picker = "other", "prox-offline"

    # 1) stories
    stories = []
    if ai_ok:
        try:
            stories, content_type = segment_stories(segments, duration)
            picker = "prox-editor"
        except Exception:
            stories = []
    if not stories:
        stories = stories_offline(segments, duration, energy, laughs)
    if not stories:
        return _even_windows(duration, count), [], "prox-windows", content_type

    # 2) draft + edge rules + measurement
    if ai_ok:
        cands = draft_cuts(stories, segments, laughs, energy, content_type, duration)
    else:
        cands = [{"start": s["start"], "end": s["end"], "title": s["summary"][:70],
                  "hook": s["hook_line"], "story_summary": s["summary"]} for s in stories]
    if not cands:
        return _even_windows(duration, count), [], "prox-windows", content_type
    for c in cands:
        snap(c, segments, duration)
    extend_through_laughter(cands, laughs, duration, segments)
    measure(cands, segments, energy, laughs)
    cands.sort(key=lambda c: -(0.5 * c["measured"]["laughter"] + 0.3 * c["measured"]["energy"]
                               + 0.2 * c["measured"]["pacing"]))

    # 3) judge the strongest, with repair loop + honest demotion
    top_pool = cands[:max(count + 2, 5)]
    judgements = {}
    if ai_ok:
        try:
            judgements = judge_cuts(top_pool, segments)
        except Exception:
            judgements = {}
        for i, c in enumerate(top_pool):
            if not isinstance(c, dict):
                continue
            j = judgements.get(i)
            if j and judge_fail(j):
                complaint = j.get("verdict") or (
                    "starts mid-thought" if j.get("starts_abrupt") else "ends before the payoff") if isinstance(j, dict) else "failed judgement"
                if repair_cut(c, complaint, segments, duration):
                    snap(c, segments, duration)
                    extend_through_laughter([c], laughs, duration, segments)
                    measure(c, segments, energy, laughs)
        try:  # re-judge (windows may have moved)
            judgements = judge_cuts(top_pool, segments)
        except Exception:
            pass
        for i, c in enumerate(top_pool):
            if not isinstance(c, dict):
                continue
            j = judgements.get(i) or dict(_OFFLINE_J, verdict="judge unavailable — measured factors only")
            score_v2(c, j, content_type)
        top_pool = [c for c in top_pool if isinstance(c, dict)]
        top_pool.sort(key=lambda c: -c["score"])
    else:
        top_pool = [c for c in top_pool if isinstance(c, dict)]
        for c in top_pool:
            score_v2(c, _OFFLINE_J, content_type)
        top_pool.sort(key=lambda c: -c["score"])

    # final pick: judge-passed cuts first, spaced across the episode
    passing = [c for c in top_pool if c.get("qc") == "verified"]
    rest = [c for c in top_pool if c.get("qc") != "verified"]
    picked = []
    for c in passing + rest:
        if len(picked) >= count:
            break
        if all(abs(c["start"] - p["start"]) > 60 for p in picked):
            picked.append(c)
    for c in passing + rest:
        if len(picked) >= count:
            break
        if c not in picked:
            picked.append(c)
    for c in picked:
        c["selected"] = True
    return picked, top_pool[:10], picker, content_type


def _even_windows(duration, count=3, length=22):
    windows, start = [], 0.0
    step = max(length, duration / max(count, 1))
    while start < duration - 3 and len(windows) < count:
        end = min(start + length, duration)
        windows.append({"start": round(start, 1), "end": round(end, 1),
                        "title": f"Highlight {len(windows) + 1}", "hook": "",
                        "reason": "no usable transcript — evenly spaced window"})
        start = end
    return windows


def rank_single(segments, duration, energy, start, end):
    """Manual custom cut — measured honestly; judged when a key exists."""
    cand = {"start": float(start), "end": float(end), "title": "Custom cut",
            "hook": "", "reason": "your manual selection"}
    snap(cand, segments, duration)
    measure([cand], segments, energy, None)
    if CONFIG["ai_key"]:
        try:
            j = judge_cuts([cand], segments)[0]
            score_v2(cand, j, "custom")
            return cand
        except Exception:
            pass
    score_v2(cand, dict(_OFFLINE_J, verdict="manual cut — measured factors only"), "custom")
    return cand


# ---------------------------------------------------------------- metadata

def generate_metadata(clips, segments):
    META_PROMPT = """For each clip below, write the social media metadata for a vertical short.

Clips (JSON with the exact verbatim the viewer will see):
{clips}

Return ONLY compact JSON, no markdown. For each clip, matching by index:
{{"clips": [{{"index": 0, "title": "viral YouTube title, under 90 chars",
"description": "1-2 sentence caption for the post",
"hashtags": ["#shorts", "#viral", "#topic1", "#topic2"]}}]}}
"""
    payload_clips = [{"index": i, "title": c.get("title", ""), "hook": c.get("hook", ""),
                      "verbatim": _clip_verbatim(segments, c["start"], c["end"], 600)}
                     for i, c in enumerate(clips)]
    if CONFIG["ai_key"]:
        try:
            out = _as_list(_parse_json(ai_chat({
                "model": CONFIG["ai_model"],
                "messages": [{"role": "user", "content": META_PROMPT.format(
                    clips=json.dumps(payload_clips, ensure_ascii=False))}],
                "temperature": 0.6,
            })).get("clips"))
            meta = {}
            for c in out:
                if not isinstance(c, dict) or _as_float(c.get("index")) is None:
                    continue
                tags = [t if t.startswith("#") else "#" + t for t in _as_list(c.get("hashtags"))][:8]
                meta[int(_as_float(c["index"]))] = {
                    "title": (c.get("title") or "").strip()[:95],
                    "description": (c.get("description") or "").strip(),
                    "hashtags": tags,
                }
            for i in range(len(clips)):
                meta.setdefault(i, fallback_metadata([clips[i]])[0])
            return meta
        except Exception:
            pass
    return fallback_metadata(clips)


def fallback_metadata(clips):
    meta = {}
    for i, c in enumerate(clips):
        words = re.findall(r"[A-Za-z\u0600-\u06FF\u0900-\u097F]+", c.get("title", "clip"))
        meta[i] = {
            "title": c.get("title", f"Highlight {i + 1}")[:95],
            "description": c.get("reason", "") or c.get("story_summary", ""),
            "hashtags": ["#shorts", "#viral", "#reels"] + ["#" + w.lower() for w in words[:3]],
        }
    return meta
