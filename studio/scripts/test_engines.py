"""Engine fidelity tests for ClipBlitz Studio - stdlib only, no network, no ffmpeg.

Run from the studio root:   python scripts/test_engines.py

The honest definition of the engine split, and what this proves:

  1. prox-only  = the legacy ProX v5 engine, exactly. With the cinema layer off the ProX
     variant IS the fully polished ProX window (laugh-riding included), and it matches the
     frozen ProX v5 tree's own rank() window for window when that tree is available.
  2. b2-only    = today's B2 window. The ProX track is a set of throwaway dicts that can
     never move a B2 window, a factor or a score.
  3. both       = the ProX variant is the same edit as the B2 cut WITHOUT the cinema
     timing (identical snapping, laugh-riding, judge-repair and post-roll), and the two
     variants are still genuinely different cuts - two real cuts, not one cut twice.

Env: CB_LEGACY_TREE=<path to the frozen ProX v5 tree>, default ../clipping/clipblitz
relative to the studio root (skipped with a note when that tree is not present).
"""

import importlib
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
DEFAULT_LEGACY = os.path.join(os.path.dirname(STUDIO), "clipping", "clipblitz")

sys.path.insert(0, STUDIO)

# This test is about engine fidelity, not about the owner's taste. Point the data dir at
# a throwaway so the learning loop has zero events and the ranking weights are the plain
# base profile in every run (including the frozen-tree comparison).
from clipblitz.config import CONFIG  # noqa: E402
CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_engines_")

from clipblitz import virality as V  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def skip(name, detail):
    RESULTS.append((name, None, detail))
    print(f"[SKIP] {name}  - {detail}")


# --------------------------------------------------------------------------- source

def build_source(duration=200.0, step=4.0):
    """A deterministic fake episode.

    Sentence-timed transcript, two loud energy plateaus, shot boundaries every 25s, and
    laughter bursts placed right after the endings the offline engine actually picks -
    so the laugh-riding edge rule is genuinely exercised instead of being decorative.
    """
    global LAUGHS
    segments, t, i = [], 0.0, 0
    while t < duration - step:
        end = round(t + step - 0.4, 2)
        text = f"Line {i} ends here."
        toks = text.split()
        per = (end - t) / len(toks)
        words = [{"word": tk, "start": round(t + per * k, 2), "end": round(t + per * (k + 1), 2)}
                 for k, tk in enumerate(toks)]
        segments.append({"start": round(t, 2), "end": end, "text": text, "words": words})
        t += step
        i += 1
    series, h = [], 0.0
    while h < duration:
        loud = 40.0 <= h <= 70.0 or 140.0 <= h <= 160.0
        series.append((round(h, 2), -30.0 + (12.0 if loud else 0.0)))
        h += 0.5
    energy = (series, -30.0)
    scenes = [round(20.0 + 25.0 * k, 1) for k in range(7)]

    # where the offline engine lands before any laughter is considered
    dry_moments = V.mine_moments(segments, duration, energy, [], scenes)
    dry = V.stories_offline(segments, duration, energy, [], moments=dry_moments)
    ends = []
    for st in dry[:2]:
        c = {"start": st["start"], "end": st["end"]}
        V.snap(c, segments, duration)
        ends.append(c["end"])
    LAUGHS = [(round(e - 1.0, 2), round(e + 3.5, 2), 0.9) for e in ends]
    return segments, duration, energy, LAUGHS, scenes


LAUGHS = []


# --------------------------------------------------------------------------- helpers

def brains_off():
    import clipblitz.brains as B
    B.brains = lambda: []


def brains_on():
    import clipblitz.brains as B
    B.brains = lambda: [{"name": "fake"}]


def fake_ai(responses):
    """Deterministic stand-in for the dual-brain chat: pick a canned reply by marker."""
    def _chat(payload, **kw):
        prompt = payload["messages"][-1]["content"]
        for marker, reply in responses:
            if marker in prompt:
                return reply
        raise AssertionError(f"unexpected ai_chat prompt: {prompt[:160]!r}")
    return _chat


def run_rank(src, cinema=None, motion=None, ai=None, prox_window=None):
    """Run rank() with a controlled setup and restore the module afterwards."""
    segments, duration, energy, laughs, scenes = src
    brains_off()
    saved_chat, saved_prox = V.ai_chat, V._prox_window
    if ai is not None:
        brains_on()
        V.ai_chat = fake_ai(ai)
    if prox_window is not None:
        V._prox_window = prox_window
    try:
        picked, cands, picker, ctype = V.rank(segments, duration, count=3, energy=energy,
                                              laughs=laughs, scenes=scenes,
                                              cinema_marks=cinema, motion=motion)
    finally:
        V.ai_chat, V._prox_window = saved_chat, saved_prox
    return picked, cands, picker, ctype


def legacy_module():
    """Import the frozen ProX v5 package under an alias (read-only, never writes)."""
    root = os.environ.get("CB_LEGACY_TREE") or DEFAULT_LEGACY
    pkg = os.path.join(root, "clipblitz")
    if not os.path.isdir(pkg):
        return None, root
    spec = importlib.util.spec_from_file_location(
        "legacy_prox", os.path.join(pkg, "__init__.py"), submodule_search_locations=[pkg])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["legacy_prox"] = mod
    spec.loader.exec_module(mod)
    return importlib.import_module("legacy_prox.virality"), root


def bounds(rows):
    return [(round(float(c["start"]), 2), round(float(c["end"]), 2)) for c in rows]


def raw_bounds(rows):
    return [(round(float(c["raw_start"]), 2), round(float(c["raw_end"]), 2)) for c in rows]


def by_key(rows):
    """Candidates come back in score order; key them by the draft's own story anchor,
    which is decided deterministically and is identical in every run for one input."""
    out = {}
    for c in rows:
        out.setdefault((round(float(c.get("story_start", c["start"])), 2),
                        c.get("title", "")), c)
    return out


def cinema_stub():
    """Deterministic stand-in for the measured cinema passes: the B2 cut moves by
    (-1.5, +2.5) relative to the pre-cinema window."""
    import clipblitz.cinema as C
    saved = (C.cinema_snap, C.scene_grammar)
    C.cinema_snap = lambda a, b, marks, seg, dur: (round(a - 1.5, 2), round(b + 2.5, 2))
    C.scene_grammar = lambda a, b, motion, marks, seg: (a, b, "test")
    return saved


def cinema_unstub(saved):
    import clipblitz.cinema as C
    C.cinema_snap, C.scene_grammar = saved


CINEMA_MARKS = [10.0 + 20.0 * k for k in range(10)]
CINEMA_MOTION = [0.5] * 200


# --------------------------------------------------------------- 1 + 3: prox / both

def test_prox_and_both():
    src = build_source()
    segments, duration, energy, laughs, scenes = src

    # (a) cinema layer OFF - exactly what the frozen ProX v5 engine runs.
    picked, cands, _, _ = run_rank(src)
    check("source: the offline engine produced picks to test", len(picked) >= 2, str(len(picked)))
    moved = [c for c in picked if c.get("laugh_ending")]
    check("prox: the non-cinema polish runs (a picked cut rode the laugh out)",
          bool(moved), f"{len(moved)}/{len(picked)} picked cuts extended")
    check("prox: every picked cut renders the same window the judge scored",
          all(c["raw_start"] == c["start"] and c["raw_end"] == c["end"] for c in picked),
          str([(c["raw_start"], c["raw_end"], c["start"], c["end"]) for c in picked[:3]]))

    # (b) cross-check against the frozen ProX v5 tree itself.
    legacy, root = legacy_module()
    if legacy is None:
        skip("prox == legacy ProX v5 (frozen tree)", f"no frozen tree at {root}")
    else:
        sys.modules["legacy_prox.brains"].brains = lambda: []
        saved_lchat = legacy.ai_chat
        legacy.ai_chat = lambda payload, **kw: (_ for _ in ()).throw(RuntimeError("offline"))
        try:
            l_picked, _, _, _ = legacy.rank(segments, duration, count=3,
                                            energy=energy, laughs=laughs, scenes=scenes)
        finally:
            legacy.ai_chat = saved_lchat
        check("prox == legacy ProX v5 (frozen tree)",
              bounds(picked) == bounds(l_picked),
              f"studio {bounds(picked)[:3]} vs legacy {bounds(l_picked)[:3]}")

    # (c) cinema ON: the B2 window moves, the ProX variant must not.
    saved = cinema_stub()
    try:
        c_picked, c_cands, _, _ = run_rank(src, cinema=CINEMA_MARKS, motion=CINEMA_MOTION)
    finally:
        cinema_unstub(saved)

    prox_run = by_key(picked)
    both_run = by_key(c_cands)
    shared = [k for k in both_run if k in prox_run]
    check("both: the two engine runs share candidates to compare", len(shared) >= 2,
          str(len(shared)))
    check("both: ProX variant == the same edit with the cinema layer off",
          all(raw_bounds([both_run[k]]) == bounds([prox_run[k]]) for k in shared),
          str([(raw_bounds([both_run[k]])[0], bounds([prox_run[k]])[0]) for k in shared[:3]]))
    check("both: the B2 cut uses the cinema-snapped bounds",
          all(both_run[k]["start"] == round(both_run[k]["raw_start"] - 1.5, 2) for k in shared),
          str([(both_run[k]["raw_start"], both_run[k]["start"]) for k in shared[:3]]))
    check("both: the ProX variant keeps its own (laugh-ridden) ending",
          any(both_run[k]["raw_end"] != round(both_run[k]["end"] - 2.5, 2) for k in shared),
          str([(both_run[k]["raw_end"], both_run[k]["end"]) for k in shared[:3]]))
    check("both: the two variants are genuinely different cuts",
          any(bounds([both_run[k]]) != raw_bounds([both_run[k]]) for k in shared))


# --------------------------------------------------------------------------- 2: b2

def test_b2_fidelity():
    """The ProX track must be invisible to the B2 engine: same windows, same factors,
    same scores, whether or not it is computed at all."""
    src = build_source()

    def no_prox_track(*a, **kw):
        """Neuter the whole ProX track: raw_start/raw_end keep the pre-cinema value and
        none of the mirrors run. The B2 engine must not notice."""
        return None

    saved = cinema_stub()
    try:
        a_picked, a_cands, _, _ = run_rank(src, cinema=CINEMA_MARKS, motion=CINEMA_MOTION)
        b_picked, b_cands, _, _ = run_rank(src, cinema=CINEMA_MARKS, motion=CINEMA_MOTION,
                                           prox_window=no_prox_track)
    finally:
        cinema_unstub(saved)

    check("b2: identical picked windows with and without the ProX track",
          bounds(a_picked) == bounds(b_picked), f"{bounds(a_picked)} vs {bounds(b_picked)}")
    check("b2: identical scores with and without the ProX track",
          [c["score"] for c in a_picked] == [c["score"] for c in b_picked])
    check("b2: identical factor breakdowns with and without the ProX track",
          [c["factors"] for c in a_picked] == [c["factors"] for c in b_picked])
    check("b2: b2-only renders c['start']/c['end'] (the cinema bounds)",
          all(c["start"] == round(c["raw_start"] - 1.5, 2) for c in a_cands))
    check("b2: the ProX track really was doing work (bounds differ when it is stubbed)",
          raw_bounds(a_cands) != raw_bounds(b_cands),
          f"{raw_bounds(a_cands)[:2]} vs {raw_bounds(b_cands)[:2]}")


# --------------------------------------------------------- 4: repair + post-roll

def test_judge_repair_and_post_roll():
    """With the judge/repair/post-roll passes active, the ProX variant must move with
    them, while the B2 windows stay byte-identical."""
    src = build_source()
    segments, duration, energy, laughs, scenes = src

    base_picked, _, _, _ = run_rank(src)
    story = {"start": round(base_picked[0]["start"], 2), "end": round(base_picked[0]["end"], 2),
             "summary": "The one story of the episode",
             "hook_line": "A strong opening line", "payoff": "It lands on the pay-off"}
    cut = {"index": 0, "start": round(story["start"] + 2, 2), "end": round(story["end"] - 6, 2),
           "title": "Story one", "hook_line": "A strong opening line"}
    ai = [
        ('"stories"', json.dumps({"content_type": "comedy", "stories": [story]})),
        ('"cuts"', json.dumps({"cuts": [cut]})),
        ('"alone"', json.dumps({"judgements": [{
            "index": 0, "alone": True, "starts_abrupt": False, "ends_abrupt": True,
            "coherence": 8, "hook": 7, "payoff": 2, "verdict": "stops before the pay-off"}]})),
        ("judge complaint:", json.dumps({"start": round(story["start"] + 1, 2),
                                         "end": round(story["end"] - 1, 2)})),
    ]

    def no_prox_track(*a, **kw):
        return None

    saved = cinema_stub()
    try:
        a_picked, a_cands, _, _ = run_rank(src, cinema=CINEMA_MARKS, motion=CINEMA_MOTION, ai=ai)
        b_picked, b_cands, _, _ = run_rank(src, cinema=CINEMA_MARKS, motion=CINEMA_MOTION, ai=ai,
                                           prox_window=no_prox_track)
    finally:
        cinema_unstub(saved)

    check("repair: the run produced a judged, repaired cut",
          bool(a_cands) and any(c.get("repaired") for c in a_cands),
          str([(c.get("repaired"), c.get("laugh_ending"), c.get("post_rolled")) for c in a_cands]))
    check("repair: the ProX variant moves with the judge-repair / laugh polish",
          raw_bounds(a_cands) != raw_bounds(b_cands),
          f"{raw_bounds(a_cands)[:2]} vs {raw_bounds(b_cands)[:2]}")
    check("repair: B2 windows identical with and without the ProX track",
          bounds(a_picked) == bounds(b_picked), f"{bounds(a_picked)} vs {bounds(b_picked)}")
    check("repair: B2 scores identical with and without the ProX track",
          [c["score"] for c in a_picked] == [c["score"] for c in b_picked])
    no_cinema, _, _, _ = run_rank(src, ai=ai)          # the same AI run, cinema layer off
    check("repair: ProX variant == the same edit with the cinema layer off",
          sorted(raw_bounds(a_cands)) == sorted(bounds(no_cinema)),
          f"{sorted(raw_bounds(a_cands))} vs {sorted(bounds(no_cinema))}")


def main():
    if V._weights("comedy") != dict(V.WEIGHT_PROFILES["comedy"]):
        print("NOTE: learning is active on the real data dir; this run uses a temp one")
    test_prox_and_both()
    test_b2_fidelity()
    test_judge_repair_and_post_roll()
    fails = [r for r in RESULTS if r[1] is False]
    skips = [r for r in RESULTS if r[1] is None]
    print(f"\n{len(RESULTS) - len(fails) - len(skips)} passed, {len(fails)} failed, "
          f"{len(skips)} skipped")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
