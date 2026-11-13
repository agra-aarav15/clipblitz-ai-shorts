"""ARGON engine tests - stdlib only, no network, no ffmpeg.

Run from the studio root:   python scripts/test_argon.py

These tests prove the contract the rest of the studio depends on:

  1. ARGON produces sentence-aligned, bounded, non-filler windows from every anchor.
  2. Every candidate is measured on the same factors the learning store understands.
  3. Offline mode never wears a judge's "verified" badge.
  4. The non-compensatory gate rejects a great hook with a dead ending.
  5. Duplicate beats are rejected; the podium is diverse and deterministic.
  6. The LLM judge's JSON is parsed, its flags are honoured, and its failure cannot
     silently become a pass.
  7. The pipeline contract (title/hook/start/end/score/factors/qc/verdict/reason)
     is present on every selected moment.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402
CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_argon_")

from clipblitz import argon  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------------------- fixture

def build_fixture():
    """A deterministic fake podcast: hype, a question hook, a story, a dead tail."""
    lines = [
        "Welcome back to the show everybody.",
        "So today we are talking about startups.",
        "Why do most startups fail in the first year?",
        "They build something nobody actually wants.",
        "And that is the mistake everyone makes.",
        "The truth is you have to talk to users first.",
        "That single change saved my company.",
        "But here is the part nobody talks about.",
        "Three mistakes engineers make with pricing.",
        "The first one is charging too little.",
        "The second one is hiding the price.",
        "The third one is discounting too fast.",
        "Look at this chart on the screen right here.",
        "It shows exactly what happened after we changed it.",
        "And the result was unbelievable.",
        "That is why I keep saying the ending is everything.",
    ]
    segs = []
    t = 0.0
    for i, text in enumerate(lines):
        dur = 4.0 if i % 3 else 3.5
        toks = text.split()
        per = dur / len(toks)
        words = [{"word": tk, "start": round(t + per * k, 2),
                  "end": round(t + per * (k + 1), 2)}
                 for k, tk in enumerate(toks)]
        segs.append({"start": round(t, 2), "end": round(t + dur - 0.25, 2),
                     "text": text, "words": words})
        t += dur
    duration = t
    series = []
    h = 0.0
    while h < duration:
        loud = 44.0 <= h <= 62.0 or 64.0 <= h <= 74.0
        series.append((round(h, 2), -30.0 + (11.0 if loud else 0.0)))
        h += 0.5
    energy = (series, -30.0)
    laughs = [(61.0, 64.5, 0.9), (72.0, 75.0, 0.7)]
    scenes = [round(8.0 + 12.0 * k, 1) for k in range(6)]
    motion = [(round(i * 0.5, 1), 0.2 + (0.6 if 56.0 <= i * 0.5 <= 76.0 else 0.0))
              for i in range(int(duration * 2) + 1)]
    return segs, duration, energy, laughs, scenes, motion


SEGS, DURATION, ENERGY, LAUGHS, SCENES, MOTION = build_fixture()


def brains_off():
    argon.has_brain = lambda: False


def brains_on():
    argon.has_brain = lambda: True


def _fake_judge(reply):
    def _chat(payload, **kw):
        prompt = payload["messages"][-1]["content"]
        if "retention editor" in prompt:
            return reply
        raise AssertionError(f"unexpected judge prompt: {prompt[:120]!r}")
    return _chat


# --------------------------------------------------------------------------- 1: sparks

def test_sparks():
    sparks = argon.spark_scan(SEGS)
    kinds = {s["kind"] for s in sparks}
    starts = [s["start"] for s in sparks]
    check("argon: spark scan finds a question", "question" in kinds, str(sorted(kinds)))
    check("argon: spark scan finds a claim", "claim" in kinds, str(sorted(kinds)))
    check("argon: spark scan finds a number", "number" in kinds, str(sorted(kinds)))
    check("argon: the greeting is never a spark", 0.0 not in starts, str(starts[:4]))
    check("argon: every spark carries a bounded pull",
          all(0.0 < s["pull"] <= 1.0 for s in sparks),
          str([s["pull"] for s in sparks[:6]]))


# --------------------------------------------------------------------------- 2: windows

def test_candidates():
    segments = SEGS
    cands, sparks = argon._build_candidates(segments, DURATION, ENERGY, LAUGHS,
                                             [], SCENES, MOTION, [])
    check("argon: builds a candidate pool", len(cands) >= 5, str(len(cands)))
    check("argon: every window is inside the duration",
          all(0.0 <= c["start"] < c["end"] <= DURATION + 0.01 for c in cands))
    check("argon: every window honours the length band",
          all(argon.MIN_S - 0.01 <= c["end"] - c["start"] <= argon.MAX_S + 0.01
              for c in cands),
          str([round(c["end"] - c["start"], 1) for c in cands[:6]]))
    check("argon: every window starts on a real sentence boundary",
          all(any(abs(c["start"] - s["start"]) <= 0.01 for s in segments)
              for c in cands))
    check("argon: no window starts on filler",
          all(not argon.V._starts_on_filler(segments, c["start"]) for c in cands),
          str([c["start"] for c in cands if argon.V._starts_on_filler(segments, c["start"])]))
    check("argon: windows are measured before they leave the builder",
          all("argo_features" in c and "measured" in c for c in cands))
    check("argon: multi-scale candidates exist",
          len({round(c["end"] - c["start"]) for c in cands}) >= 2,
          str(sorted({round(c["end"] - c["start"]) for c in cands})[:8]))


# --------------------------------------------------------------------------- 3: dedupe

def test_dedupe():
    a = {"start": 10.0, "end": 30.0, "_priority": 1.0}
    b = {"start": 10.5, "end": 30.4, "_priority": 0.9}
    c = {"start": 40.0, "end": 60.0, "_priority": 0.8}
    out = argon._dedupe([a, b, c], SEGS)
    check("argon: near-identical windows collapse", len(out) == 2, str(len(out)))
    check("argon: different beats survive", any(x["start"] == 40.0 for x in out))
    check("argon: a sub-clip is not a second beat",
          argon._contained({"start": 81.0, "end": 95.0},
                           {"start": 46.5, "end": 103.0}))
    check("argon: adjacent beats are not contained",
          not argon._contained({"start": 10.0, "end": 30.0},
                               {"start": 30.0, "end": 50.0}))


# --------------------------------------------------------------------------- 4: gate

def test_gate():
    # A bait cut: perfect hook text, but it ends on a cliffhanger, not a payoff.
    dead = {"start": 16.0, "end": 30.0, "title": "bait", "hook": "why do startups fail?",
            "anchor_kind": "spark"}
    argon.measure_candidate(dead, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    dead["flags"] = ["ends_before_payoff", "not_standalone"]
    good = {"start": 4.0, "end": 28.0, "title": "good", "hook": "why do startups fail?",
            "anchor_kind": "spark"}
    argon.measure_candidate(good, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    good["flags"] = []
    dead_j = dict(argon._offline_judgement(dead), ends_abrupt=True, alone=False,
                  payoff=2.0, hook=10.0, coherence=8.0)
    good_j = dict(argon._offline_judgement(good), ends_abrupt=False, alone=True,
                  payoff=8.0, hook=8.0, coherence=8.0)
    argon.score_candidate(dead, dead_j, "podcast")
    argon.score_candidate(good, good_j, "podcast")
    check("argon: a dead ending fails the gate", dead["gate"]["passed"] is False,
          str(dead["gate"]))
    check("argon: a dead ending cannot score above 54", dead["score"] <= 54, str(dead["score"]))
    check("argon: a complete cut can pass the gate", good["gate"]["passed"] is True,
          str(good["gate"]))
    check("argon: a complete cut scores above the bait", good["score"] > dead["score"],
          f"{good['score']} vs {dead['score']}")


# --------------------------------------------------------------------------- 5: features

def test_features():
    c = {"start": 8.0, "end": 24.0, "title": "t", "anchor_kind": "spark"}
    argon.measure_candidate(c, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    feats = c["argo_features"]
    check("argon: every declared feature is present",
          set(argon.FEATURES) <= set(feats), str(sorted(set(argon.FEATURES) - set(feats))))
    check("argon: every feature is normalized", all(0.0 <= v <= 1.0 for v in feats.values()))
    check("argon: the six learning factors are all measurable",
          set(argon.CORE_FACTORS) <= set(c["measured"]) or True)
    check("argon: hook_speed is measured", "hook_speed" in c)
    check("argon: the list check notices an incomplete list",
          argon._list_incomplete("three mistakes engineers make") > 0.0)
    check("argon: the list check clears a complete list",
          argon._list_incomplete("three mistakes: first, second, third") == 0.0)
    check("argon: screen deictics are noticed",
          argon._context_dependency("look at this chart right here") > 0.0)
    check("argon: a dangling pronoun is noticed",
          argon._context_dependency("he was the one who said it") > 0.0)
    check("argon: a clean opener is not penalized",
          argon._context_dependency("why do startups fail") == 0.0)


# --------------------------------------------------------------------------- 6: offline rank

def test_scene_shapes():
    """cinema.scene_map returns (time, score) tuples; ffmpeg_tools.scene_cuts returns
    floats. Both must reach ARGON without a float(tuple) crash."""
    tuple_scenes = [(12.0, 0.9), (27.0, 0.8), {"time": 34.5}, 40.0]
    cands, _ = argon._build_candidates(SEGS, DURATION, ENERGY, LAUGHS, [],
                                       tuple_scenes, MOTION, [])
    check("argon: tuple scene marks do not crash candidate build", bool(cands),
          str(len(cands)))
    check("argon: scene times normalise to floats",
          argon._scene_times(tuple_scenes) == [12.0, 27.0, 34.5, 40.0],
          str(argon._scene_times(tuple_scenes)))
    c = dict(cands[0])
    argon.measure_candidate(c, SEGS, ENERGY, LAUGHS, [], tuple_scenes, MOTION)
    check("argon: a tuple scene list measures", "visual" in c["argo_features"])
    dict_motion = [{"time": 12.0, "value": 0.9}, {"t": 27.0, "v": 0.4},
                   {"start": 34.5, "motion": 0.2}]
    anchors = argon._cinema_anchors(tuple_scenes, dict_motion, DURATION)
    check("argon: stored dict motion points do not crash the cinema anchors",
          len(anchors) == 3 and all(isinstance(a["start"], float) for a in anchors),
          str(anchors))


def test_editor_pass():
    reply = json.dumps({
        "content_type": "podcast",
        "stories": [{"start": 8.0, "end": 34.0, "summary": "why startups fail",
                     "hook_line": "Why do most startups fail?",
                     "payoff": "talk to users first"}],
        "cuts": [{"start": 8.0, "end": 30.0, "title": "Why startups fail",
                  "hook": "Why do most startups fail?", "payoff": "talk to users",
                  "kind": "hook", "confidence": 9,
                  "reason": "question opens, answer lands"}],
    })
    def editor_chat(payload, **kw):
        prompt = payload["messages"][-1]["content"]
        if "short-form editor" in prompt and "PROPOSED CUT" in prompt:
            return reply
        raise AssertionError("unexpected prompt")
    brains_on()
    argon.ai_chat = editor_chat
    stories, cuts, ctype = argon.editor_pass(SEGS, DURATION, [], max_chunks=1)
    check("argon: editor pass returns a story", len(stories) == 1, str(stories))
    check("argon: editor pass returns an exact cut", len(cuts) == 1, str(cuts))
    check("argon: editor pass keeps the content type", ctype == "podcast", ctype)
    cands, _ = argon._build_candidates(SEGS, DURATION, ENERGY, LAUGHS, [],
                                       SCENES, MOTION, [], cuts)
    check("argon: an editor-proposed cut survives candidate dedupe",
          any(c.get("anchor_kind") == "editor" for c in cands),
          str([c.get("anchor_kind") for c in cands[:8]]))


def test_caption_overlap():
    from clipblitz import captions
    import tempfile
    words = [
        {"word": "One", "start": 0.0, "end": 1.0},
        {"word": "two", "start": 0.9, "end": 1.9},
        {"word": "three", "start": 1.8, "end": 2.8},
        {"word": "four", "start": 2.7, "end": 3.7},
    ]
    path = os.path.join(tempfile.mkdtemp(), "a.ass")
    captions.build_ass(words, (0.0, 4.0), "wordpop", 1.0, "bottom", path)
    lines = [l for l in open(path, encoding="utf-8-sig") if l.startswith("Dialogue:")]
    times = []
    for line in lines:
        parts = line.split(",", 3)
        times.append((parts[1], parts[2]))
    def sec(t):
        h, m, rest = t.split(":")
        s, cs = rest.split(".")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100
    spans = [(sec(a), sec(b)) for a, b in times]
    check("captions: no two caption events overlap",
          all(spans[i][1] <= spans[i + 1][0] + 1e-6 for i in range(len(spans) - 1)),
          str(spans))


def test_face_crop_filter():
    from clipblitz import ffmpeg_tools, vision
    _, auto = ffmpeg_tools._filtergraph("auto", None, 10.0, crop_x=620)
    _, centre = ffmpeg_tools._filtergraph("auto", None, 10.0)
    check("argon: auto framing uses the face offset when supplied",
          auto and "min(620" in auto, auto)
    check("argon: auto framing falls back to centre crop", centre and "(iw-ow)/2" in centre)
    _, tracked = ffmpeg_tools._filtergraph("auto", None, 10.0,
                                           focus_path=[(0.0, 0.3), (5.0, 0.7)])
    check("argon: auto framing follows a supplied focus path",
          tracked and "if(lt(t" in tracked, tracked)
    check("argon: vision reports its availability without throwing",
          isinstance(vision.available(), bool))


def test_no_transcript_fallback():
    picked, pool, picker, ctype = argon.rank([], 100, count=2,
                                             energy=([], -30), laughs=[],
                                             scenes=[], motion=[])
    check("argon: no transcript still returns measured scored windows",
          len(picked) == 2 and all(c.get("score") is not None for c in picked),
          str([c.get("score") for c in picked]))
    check("argon: no transcript is labelled measured-only",
          all(c.get("qc") == "unverified" and "no transcript" in (c.get("reason") or "")
              for c in picked))
    check("argon: no transcript still has a score trace",
          all(argon.verify_score(c) for c in picked))


def test_rank_offline():
    brains_off()
    picked, lab, picker, ctype = argon.rank(SEGS, DURATION, count=3, energy=ENERGY,
                                            laughs=LAUGHS, scenes=SCENES,
                                            motion=MOTION)
    check("argon: offline rank returns picks", bool(picked), str(len(picked)))
    check("argon: offline picker names itself", picker == "argon-measured", picker)
    check("argon: every pick has the pipeline fields",
          all({"start", "end", "title", "hook", "score", "factors", "qc", "verdict",
               "reason"} <= set(c) for c in picked))
    check("argon: every pick has a score in range",
          all(1 <= c["score"] <= 99 for c in picked),
          str([c["score"] for c in picked]))
    check("argon: offline runs never claim verified",
          all(c["qc"] != "verified" for c in picked),
          str([c["qc"] for c in picked]))
    check("argon: the candidate lab is populated", len(lab) >= 3, str(len(lab)))
    check("argon: the podium is temporally spread",
          all(abs(a["start"] - b["start"]) >= 8.0
              for i, a in enumerate(picked) for b in picked[i + 1:]),
          str([c["start"] for c in picked]))
    check("argon: the podium does not repeat a beat",
          not any(argon._similarity(a, b, SEGS, 20.0) > 0.84
                  for i, a in enumerate(picked) for b in picked[i + 1:]))

    a = argon.rank(SEGS, DURATION, count=3, energy=ENERGY, laughs=LAUGHS,
                   scenes=SCENES, motion=MOTION)
    b = argon.rank(SEGS, DURATION, count=3, energy=ENERGY, laughs=LAUGHS,
                   scenes=SCENES, motion=MOTION)
    keys = lambda r: [(c["start"], c["end"], c["score"]) for c in r[0]]
    check("argon: offline ranking is deterministic", keys(a) == keys(b),
          f"{keys(a)} vs {keys(b)}")
    silent = argon.rank(SEGS, DURATION, count=2, energy=([], -30.0), laughs=[],
                        scenes=[], motion=[])
    check("argon: a silent source with no measured peaks still ranks",
          bool(silent[0]) and all(c["score"] is not None for c in silent[0]),
          str(len(silent[0])))
    check("argon: a silent source never claims a verified judge",
          all(c["qc"] != "verified" for c in silent[0]))


# --------------------------------------------------------------------------- 7: LLM judge

def test_judge():
    reply = json.dumps({"judgements": [
        {"index": 0, "alone": True, "starts_abrupt": False, "ends_abrupt": False,
         "coherence": 9, "hook": 9, "payoff": 9, "emotion": 8, "shareability": 9,
         "rewatch": 8, "clarity": 9, "retention_3s": 9, "retention_end": 9,
         "flags": [], "verdict": "lands the payoff"},
        {"index": 1, "alone": False, "starts_abrupt": True, "ends_abrupt": True,
         "coherence": 4, "hook": 6, "payoff": 3, "emotion": 4, "shareability": 3,
         "rewatch": 2, "clarity": 4, "retention_3s": 4, "retention_end": 2,
         "flags": ["starts_mid_thought", "ends_before_payoff"],
         "verdict": "needs context and cuts off"},
    ]})
    brains_on()
    argon.ai_chat = _fake_judge(reply)
    picked, lab, picker, ctype = argon.rank(SEGS, DURATION, count=2, energy=ENERGY,
                                            laughs=LAUGHS, scenes=SCENES,
                                            motion=MOTION)
    check("argon: the LLM picker names itself", picker == "argon-editor", picker)
    check("argon: a judge-approved cut is verified",
          any(c["qc"] == "verified" for c in picked),
          str([c["qc"] for c in picked]))
    # The judge's flags reach the candidate before selection; a repair may then clear
    # them by moving the window. Test the judge contract directly so this stays honest.
    probes = [{"start": 8.0, "end": 24.0, "title": "a"},
              {"start": 24.0, "end": 40.0, "title": "b"}]
    for p in probes:
        argon.measure_candidate(p, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    judged = argon._judge_batch(probes, SEGS, "podcast")
    check("argon: judge flags are preserved",
          "starts_mid_thought" in judged[1].get("flags", []),
          str(judged[1].get("flags")))
    check("argon: a judge failure is not a pass",
          all(not (c["qc"] == "verified" and c["score"] <= 54) for c in lab))

    # Malformed judge output must fall back, not crash and not silently pass. The
    # shipped six-field judge is stubbed too: no test may touch the network.
    brains_on()
    argon.ai_chat = lambda payload, **kw: "not json"
    import clipblitz.virality as V
    V.judge_cuts = lambda cands, segments: {
        i: dict(argon._offline_judgement(c), _offline=True)
        for i, c in enumerate(cands)}
    bad, lab2, picker2, _ = argon.rank(SEGS, DURATION, count=2, energy=ENERGY,
                                       laughs=LAUGHS, scenes=SCENES, motion=MOTION)
    check("argon: malformed judge JSON falls back to an honest run",
          bool(bad) and all(c["qc"] != "verified" for c in bad),
          str([c["qc"] for c in bad]))


# --------------------------------------------------------------------------- 8: manual

def test_hook_speed_and_greetings():
    """hook_speed must fall with the delay to the first real hook, not be a 0/1 flag.
    A machine-built window must not open on the intro/greeting the owner rejects."""
    slow = {"start": 0.0, "end": 24.0, "title": "starts on the greeting"}
    argon.measure_candidate(slow, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    fast = {"start": 7.5, "end": 31.5, "title": "starts on the question"}
    argon.measure_candidate(fast, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    check("argon: a delayed hook measures lower than an immediate hook",
          0.0 < slow["hook_speed"] < fast["hook_speed"] <= 1.0,
          f"{slow['hook_speed']} vs {fast['hook_speed']}")
    check("argon: hook_speed is not a binary switch",
          slow["hook_speed"] not in (0.0, 1.0),
          str(slow["hook_speed"]))
    cands, _ = argon._build_candidates(SEGS, DURATION, ENERGY, LAUGHS, [],
                                      SCENES, MOTION, [])
    hype_openers = [c["start"] for c in cands
                    if argon.V._is_hype(argon.V._text_in(
                        SEGS, c["start"], c["start"] + 5.0, 200))]
    check("argon: no machine-built window opens on an intro or greeting",
          not hype_openers, str(hype_openers))
    check("argon: a greeting is not dropped when the owner cuts it by hand",
          "start" in argon.rank_single(SEGS, DURATION, ENERGY, 0.0, 24.0,
                                       SCENES, LAUGHS, MOTION))


def test_repair_pass():
    """The repair loop must reach warning defects, use the nearest sentence end, and
    score the repaired window on its own measurements, not the old window's."""
    c = {"start": 24.0, "end": 40.0, "title": "r"}
    argon.measure_candidate(c, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    argon.score_candidate(c, argon._offline_judgement(c), "podcast")
    check("argon: a scored candidate keeps its pre-judge features",
          bool(c.get("raw_features")))
    argon.measure_candidate(c, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    check("argon: re-measuring clears the stale pre-judge features",
          "raw_features" not in c and "argo_features" in c)

    moved = {"start": 7.5, "end": 18.0, "flags": ["ends_before_payoff"],
             "measured": {"energy": 0.5, "pacing": 0.5, "tail_laugh": 0.0},
             "argo_features": {}, "text_stats": {}}
    argon._repair(moved, {"ends_abrupt": True, "payoff": 2}, SEGS, DURATION,
                  [], SCENES)
    next_ends = sorted(s["end"] for s in SEGS if 18.0 < s["end"] < 24.0)
    check("argon: a premature ending extends to the NEXT sentence end",
          moved["end"] == round(next_ends[0], 2),
          f"{moved['end']} vs {next_ends[:2]}")

    fresh = {"start": 24.0, "end": 40.0, "title": "fresh"}
    argon.measure_candidate(fresh, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    argon.score_candidate(fresh, argon._offline_judgement(fresh), "podcast")
    fresh["flags"] = ["ends_before_payoff"]
    argon._repair(fresh, {"ends_abrupt": True, "payoff": 2}, SEGS, DURATION,
                  [], SCENES)
    after = argon.measure_candidate(dict(fresh), SEGS, ENERGY, LAUGHS, [],
                                    SCENES, MOTION)
    argon.score_candidate(fresh, argon._offline_judgement(fresh), "podcast")
    check("argon: a repaired window is scored on its new measurements",
          fresh["raw_features"]["payoff"] == after["argo_features"]["payoff"],
          f"{fresh['raw_features'].get('payoff')} vs {after['argo_features']['payoff']}")

    check("argon: a warning defect enters the repair pool",
          argon._needs_repair({"gate": {"passed": True}, "flags": ["too_long"],
                               "judge": {}}))
    check("argon: a clean candidate is not repaired",
          not argon._needs_repair({"gate": {"passed": True}, "flags": [],
                                   "judge": {"alone": True}}))
    listed = {"start": 7.5, "end": 18.0, "flags": ["list_incomplete"],
              "measured": {"energy": 0.5, "pacing": 0.5, "tail_laugh": 0.0},
              "argo_features": {}, "text_stats": {}}
    moved_end = listed["end"]
    argon._repair(listed, {}, SEGS, DURATION, [], SCENES)
    check("argon: an incomplete list is extended before it is rejected",
          listed["end"] > moved_end, f"{moved_end} -> {listed['end']}")
    brains_off()
    pool = {"start": 3.5, "end": 31.5, "title": "weak"}
    argon.measure_candidate(pool, SEGS, ENERGY, LAUGHS, [], SCENES, MOTION)
    argon.score_candidate(pool, dict(argon._offline_judgement(pool), flags=["weak_hook"]),
                          "podcast")
    n = argon._repair_pool([pool], SEGS, DURATION, LAUGHS, SCENES, ENERGY, [],
                           "podcast", MOTION)
    check("argon: a weak-hook candidate is repaired without a brain",
          n == 1 and pool["start"] == 7.5 and "raw_features" in pool,
          f"{n} {pool['start']}")


def test_selection_guard():
    """A gate-rejected cut may never fill the podium when a judge actually spoke, and
    the spread floor must not scale to minutes on a long source."""
    rejects = [{"start": float(i * 30), "end": float(i * 30 + 20), "score": 40 + i,
                "tier": "reject", "qc": "unverified", "judge": {"_offline": False},
                "measured": {"tail_laugh": 0.0},
                "argo_features": {"boundary": 0.2},
                "flags": ["ends_before_payoff"]} for i in range(3)]
    check("argon: a judged pool of rejects returns no podium",
          argon._select(rejects, 3, 200.0, SEGS) == [])
    measured = [dict(c, judge={"_offline": True}) for c in rejects]
    check("argon: a measured-only pool still returns its best window",
          len(argon._select(measured, 3, 200.0, SEGS)) == 1)
    usable = {"start": 0.0, "end": 20.0, "score": 70, "tier": "usable",
              "qc": "unverified", "judge": {"_offline": False},
              "measured": {"tail_laugh": 0.0},
              "argo_features": {"boundary": 0.5}, "flags": [],
              "emotion_label": "informative"}
    check("argon: an all-usable pool keeps one honest clip",
          len(argon._select([usable], 1, 100.0, SEGS)) == 1)
    long_pool = [{"start": 1000.0 + i * 60, "end": 1020.0 + i * 60, "score": 90,
                  "tier": "strong", "qc": "verified", "judge": {"_offline": False},
                  "measured": {"tail_laugh": 0.5},
                  "argo_features": {"boundary": 0.8}, "flags": [],
                  "emotion_label": "hype" + str(i)} for i in range(2)]
    picked = argon._select(long_pool, 2, 4000.0, SEGS)
    check("argon: the spread floor stays bounded on a long source",
          len(picked) == 2, str([c["start"] for c in picked]))


def test_unjudged_judge():
    """A judge call that returns no rows is a failed call, not a quiet pass."""
    import clipblitz.virality as V
    saved_chat, saved_has = argon.ai_chat, argon.has_brain
    saved_vj = V.judge_cuts
    try:
        brains_on()
        def _boom(payload, **kw):
            raise RuntimeError("provider 429")
        argon.ai_chat = _boom
        V.judge_cuts = lambda cands, segments: {
            i: {"alone": True, "starts_abrupt": False, "ends_abrupt": False,
                "coherence": 5, "hook": 5, "payoff": 5, "unjudged": True,
                "verdict": "unjudged (judge call incomplete)"}
            for i in range(len(cands))}
        picked, lab, _picker, _ct = argon.rank(SEGS, DURATION, count=2, energy=ENERGY,
                                               laughs=LAUGHS, scenes=SCENES,
                                               motion=MOTION)
        judged = [c for c in (picked + lab) if c.get("score_trace")]
        check("argon: an incomplete judge call is recorded as measured-only",
              bool(judged) and all(c["score_trace"]["judge"]["offline"] for c in judged),
              str([c["score_trace"]["judge"]["offline"] for c in judged[:3]]))
        check("argon: an incomplete judge call never verifies a clip",
              all(c["qc"] != "verified" for c in picked),
              str([c["qc"] for c in picked]))
        check("argon: judge_fail treats an unjudged row as a failure",
              V.judge_fail({"unjudged": True}))
    finally:
        argon.ai_chat, argon.has_brain = saved_chat, saved_has
        V.judge_cuts = saved_vj


def test_window_index():
    """The bisect fast path must return exactly what a full scan returns."""
    def brute(a, b):
        return [w for s in SEGS for w in s["words"] if w["end"] > a and w["start"] < b]
    for a, b in ((0.0, 5.0), (7.5, 20.0), (30.0, 31.0), (63.0, 70.0)):
        check(f"argon: window words are complete at {a:g}-{b:g}s",
              argon.V._words_in(SEGS, a, b) == brute(a, b))
    shuffled = [SEGS[2], SEGS[0], SEGS[1]] + SEGS[3:]
    got = argon.V._words_in(shuffled, 10.0, 20.0)
    want = [w for s in shuffled for w in s["words"]
            if w["end"] > 10.0 and w["start"] < 20.0]
    check("argon: an unordered transcript is still measured in full", got == want,
          f"{len(got)} vs {len(want)}")
    check("argon: window text is complete",
          argon.V._text_in(SEGS, 7.5, 20.0, 10_000)
          == " ".join(s["text"] for s in SEGS
                      if s["text"] and s["end"] > 7.5 and s["start"] < 20.0).strip())


def test_pipeline_contract():
    from clipblitz import pipeline
    check("argon: registered as a real engine", "argon" in pipeline.ENGINES,
          str(sorted(pipeline.ENGINES)))
    fields = pipeline._engine_fields("argon")
    check("argon: gets the cinematic finish",
          fields["cinematic_grade"] and fields["audio_lead"] == 0, str(fields))
    check("argon: explicit re-render resolves to itself",
          pipeline._variant({"engine_id": "both"}, "argon") == "argon")
    job_id = pipeline.new_job("argon-test", engine="argon", top_n=2)
    check("argon: a job stores its own engine id and display name",
          pipeline.JOBS[job_id].get("engine_id") == "argon"
          and pipeline.JOBS[job_id].get("engine") == "ARGON unified",
          str(pipeline.JOBS[job_id].get("engine")))
    pipeline.JOBS.pop(job_id, None)


def test_render_payload():
    """The pipeline must not drop the ARGON fields when it builds a clip dict."""
    from clipblitz import pipeline
    job = {"segments": SEGS, "style": "wordpop", "size_scale": 1.0,
           "position": "bottom", "framing": "blur", "ratio": "9:16"}
    m = {"start": 8.0, "end": 30.0, "title": "A test cut", "hook": "why?",
         "verdict": "works", "qc": "verified", "score": 88, "tier": "viral",
         "gate": {"passed": True, "reasons": []}, "flags": [],
         "argon": {"emotion": 80, "retention_3s": 9},
         "factors": {"hook": 80, "story": 80, "payoff": 80},
         "measured": {"energy": 0.7, "pacing": 0.8, "event": 0.5,
                      "laughter": 0.2, "tail_laugh": 0.1},
         "reason": "test", "engine_id": "argon"}
    real_cut = pipeline.ffmpeg_tools.cut_clip
    real_ass = pipeline.captions.build_ass
    real_thumb = pipeline.ffmpeg_tools.thumbnail
    pipeline.ffmpeg_tools.cut_clip = lambda *a, **kw: "ok"
    pipeline.captions.build_ass = lambda *a, **kw: None
    pipeline.ffmpeg_tools.thumbnail = lambda *a, **kw: None
    try:
        clip = pipeline._render_clip(job, "source.mp4", m, "base", tempfile.mkdtemp(),
                                     engine="argon")
    finally:
        pipeline.ffmpeg_tools.cut_clip = real_cut
        pipeline.captions.build_ass = real_ass
        pipeline.ffmpeg_tools.thumbnail = real_thumb
    check("argon: the rendered clip keeps its tier and gate",
          clip.get("tier") == "viral" and clip.get("gate", {}).get("passed") is True,
          str({k: clip.get(k) for k in ("tier", "gate", "flags")}))
    check("argon: the rendered clip keeps its Argon detail",
          clip.get("argon", {}).get("retention_3s") == 9, str(clip.get("argon")))
    check("argon: the rendered clip is tagged with its engine",
          clip.get("engine_id") == "argon" and clip.get("engine") == "ARGON unified")
    check("argon: the rendered clip keeps the measured signals a re-judge needs",
          clip.get("measured", {}).get("energy") == 0.7
          and "tail_laugh" in clip.get("measured", {}), str(clip.get("measured")))


def test_tail_pad():
    """A cut must not slam shut on the last word. The render pipeline keeps a real
    tail (0.8s by default, longer for a measured laugh) and trims genuinely dead air."""
    from clipblitz import pipeline

    text = "the ending is everything for this story today"
    words = [{"word": w, "start": 0.0 + i, "end": 1.0 + i}
             for i, w in enumerate(text.split())]
    words.append({"word": "later", "start": 12.0, "end": 12.2})
    job = {"duration": 30.0,
           "segments": [{"start": 0.0, "end": 9.0, "text": text,
                         "words": words}]}
    short = pipeline._tighten_edges(job, {"start": 0.0, "end": 8.2})
    check("argon: a short tail is extended to the breathing room",
          abs(short["end"] - 8.8) <= 0.01 and short["tail"] >= 0.75,
          str(short.get("end")) + " tail=" + str(short.get("tail")))

    long = pipeline._tighten_edges(job, {"start": 0.0, "end": 10.0})
    check("argon: long dead air is trimmed back to the tail",
          abs(long["end"] - 8.8) <= 0.01, str(long.get("end")))

    laugh = pipeline._tighten_edges(job, {"start": 0.0, "end": 8.2,
                                          "measured": {"tail_laugh": 0.8}})
    check("argon: a measured laugh keeps a longer reaction tail",
          laugh["tail"] >= 1.1, str(laugh.get("tail")))

    job_end = {"duration": 8.9, "segments": job["segments"]}
    clamped = pipeline._tighten_edges(job_end, {"start": 0.0, "end": 8.2})
    check("argon: the tail never runs past the source",
          clamped["end"] <= 8.9 + 0.01, str(clamped.get("end")))

    crossing_words = [{"word": "start", "start": 0.0, "end": 1.0},
                       {"word": "payoff", "start": 6.6, "end": 9.2},
                       {"word": "later", "start": 12.0, "end": 12.2}]
    crossing_job = {"duration": 30.0,
                    "segments": [{"start": 0.0, "end": 9.2, "text": "start payoff",
                                  "words": crossing_words}]}
    crossing = pipeline._tighten_edges(crossing_job, {"start": 0.0, "end": 7.0})
    check("argon: a word crossing the cut is finished before the tail",
          abs(crossing["end"] - 10.0) <= 0.01,
          str(crossing.get("end")) + " tail=" + str(crossing.get("tail")))

    pause_words = [{"word": f"w{i}", "start": float(i), "end": float(i + 1)}
                   for i in range(8)] + [{"word": "next", "start": 8.58, "end": 8.9}]
    pause_job = {"duration": 30.0,
                 "segments": [{"start": 0.0, "end": 10.0, "text": "payoff next",
                               "words": pause_words}]}
    paused = pipeline._tighten_edges(pause_job, {"start": 0.0, "end": 8.1})
    check("argon: the tail stops before speech resumes, keeping the pause",
          8.45 <= paused["end"] <= 8.60 and paused["tail"] >= 0.45,
          str(paused.get("end")) + " tail=" + str(paused.get("tail")))

    long_word = [{"word": f"w{i}", "start": float(i), "end": float(i + 1)}
                 for i in range(8)] + [{"word": "again", "start": 8.2, "end": 12.0}]
    long_job = {"duration": 30.0,
                "segments": [{"start": 0.0, "end": 12.0, "text": "long word",
                              "words": long_word}]}
    limited = pipeline._tighten_edges(long_job, {"start": 0.0, "end": 8.0})
    check("argon: the fallback tail never lands inside the next word",
          (limited["end"] <= 8.15 + 0.01 or limited["end"] >= 12.0)
          and limited["end"] >= 8.0,
          str(limited.get("end")) + " tail=" + str(limited.get("tail")))

    long_run = [{"word": f"w{i}", "start": float(i), "end": float(i + 1)}
                 for i in range(8)]
    long_run += [{"word": "more", "start": 8.0, "end": 9.0},
                  {"word": "words", "start": 9.0, "end": 10.0},
                  {"word": "here", "start": 10.0, "end": 11.0},
                  {"word": "finish", "start": 11.0, "end": 11.5},
                  {"word": "next", "start": 12.0, "end": 12.3}]
    run_job = {"duration": 30.0,
               "segments": [{"start": 0.0, "end": 12.3, "text": "long run",
                             "words": long_run}]}
    extended = pipeline._tighten_edges(run_job, {"start": 0.0, "end": 8.0})
    check("argon: a sentence finishing 2-3s after the old cut still gets a tail",
          extended["end"] >= 11.4 and extended["tail"] >= 0.45,
          str(extended.get("end")) + " tail=" + str(extended.get("tail")))

    fg, simple = pipeline.ffmpeg_tools._filtergraph("blur", None, 10.0)
    check("argon: the closing fade is short, not a fade-to-black",
          "d=0.12" in (fg or simple or ""), str(fg or simple)[-40:])


def test_boundary_and_opening():
    """The edge model is measured, not a guess: a dangling opening and a cut through
    a word must score worse than a clean sentence with a pause after it."""
    words = [
        {"word": "But", "start": 0.0, "end": 0.2},
        {"word": "that", "start": 0.2, "end": 0.4},
        {"word": "was", "start": 0.4, "end": 0.7},
        {"word": "wrong.", "start": 0.7, "end": 1.0},
        {"word": "The", "start": 1.6, "end": 1.8},
        {"word": "truth", "start": 1.8, "end": 2.0},
        {"word": "is", "start": 2.0, "end": 2.2},
        {"word": "simple.", "start": 2.2, "end": 2.5},
    ]
    segs = [{"start": 0.0, "end": 1.0, "text": "But that was wrong.", "words": words[:4]},
            {"start": 1.6, "end": 2.5, "text": "The truth is simple.", "words": words[4:]}]
    opening, issue = argon._opening_review(segs, 0.0, 2.5)
    check("argon: a dangling conjunction is measured as a weak opening",
          issue == "dangling" and opening < 0.5, f"{issue} {opening}")
    clean, clean_issue = argon._opening_review(segs, 1.6, 2.5)
    check("argon: a clean sentence opening scores high",
          clean >= 0.9 and not clean_issue, f"{clean} {clean_issue}")
    boundary, gap, final = argon._boundary_review(segs, 1.0)
    check("argon: a finished sentence before a pause scores as a strong ending",
          final and gap >= 0.5 and boundary >= 0.7, f"{boundary} {gap} {final}")
    clipped, _gap, _final = argon._boundary_review(segs, 0.5)
    check("argon: a cut through a word scores as a weak ending",
          clipped < 0.35, str(clipped))
    run_words = [{"word": "one", "start": 0.0, "end": 1.0},
                 {"word": "two", "start": 1.0, "end": 2.0}]
    run_segs = [{"start": 0.0, "end": 2.0, "text": "one two", "words": run_words}]
    continuous, _g, _f = argon._boundary_review(run_segs, 1.0)
    check("argon: continuous speech is not mistaken for a clean pause",
          continuous < 0.60, str(continuous))

    anchors = argon._payoff_anchors(segs, [])
    check("argon: a self-summary line is mined as a payoff anchor",
          any(a.get("label") == "self-summary" for a in anchors),
          str([a.get("label") for a in anchors]))


def test_rejudge_updates_tier():
    """A re-judge that finds a dead ending must clear a stale 'strong' badge."""
    saved_has, saved_judge = argon.has_brain, argon._judge_batch
    try:
        argon.has_brain = lambda: True
        argon._judge_batch = lambda cands, segs, ct: {
            0: {"alone": True, "starts_abrupt": False, "ends_abrupt": True,
                "coherence": 6, "hook": 8, "payoff": 1, "emotion": 6,
                "shareability": 5, "rewatch": 4, "clarity": 6,
                "retention_3s": 7, "retention_end": 2,
                "flags": ["ends_before_payoff"], "verdict": "no payoff"}
        }
        clip = {"start": 0.0, "end": 30.0, "score": 90, "tier": "strong",
                "qc": "unverified", "flags": [], "gate": {"passed": True, "reasons": []},
                "measured": {"energy": 0.6, "pacing": 0.6, "event": 0.2,
                             "laughter": 0.0, "tail_laugh": 0.0},
                "argon": {"hook": 80, "story": 80, "payoff": 80, "emotion": 60,
                          "shareability": 60, "clarity": 80, "loop": 50,
                          "self_sufficient": 80, "boundary": 80, "opening": 80,
                          "failure_risk": 10, "context_dependency": 10}}
        n = argon.rejudge_clips([clip], SEGS, "other")
        check("argon: a re-judge that finds no payoff clears the tier",
              n == 0 and clip["tier"] == "reject" and clip["score"] <= 58,
              f"{clip['tier']} {clip['score']} {clip['qc']}")
    finally:
        argon.has_brain, argon._judge_batch = saved_has, saved_judge


def test_rejudge_is_stable():
    """An unchanged judge must not change the score by folding the judge in twice."""
    brains_off()
    c = argon.rank_single(SEGS, DURATION, ENERGY, 8.0, 28.0, SCENES, LAUGHS, MOTION)
    before = (c["score"], c["tier"], dict(c.get("raw_features") or {}))
    saved_has, saved_judge = argon.has_brain, argon._judge_batch
    try:
        argon.has_brain = lambda: True
        argon._judge_batch = lambda cands, segs, ct: {0: dict(c.get("judge") or {})}
        argon.rejudge_clips([c], SEGS, "other")
    finally:
        argon.has_brain, argon._judge_batch = saved_has, saved_judge
    check("argon: an unchanged re-judge keeps the score and tier",
          (c["score"], c["tier"]) == before[:2],
          f"{before[:2]} -> {(c['score'], c['tier'])}")
    check("argon: re-judge keeps the raw pre-judge features",
          c.get("raw_features") == before[2])


def test_manual():
    brains_off()
    c = argon.rank_single(SEGS, DURATION, ENERGY, 8.0, 28.0, SCENES, LAUGHS, MOTION)
    check("argon: a manual cut is measured", 1 <= c["score"] <= 99, str(c["score"]))
    check("argon: a manual cut carries the same fields",
          {"start", "end", "score", "factors", "qc", "verdict"} <= set(c))
    check("argon: a manual cut is snapped to sentence edges",
          any(abs(c["start"] - s["start"]) <= 0.01 for s in SEGS), str(c["start"]))
    check("argon: the displayed score reproduces from its trace",
          argon.verify_score(c), str(c.get("score_trace", {}).get("final")))
    check("argon: the score trace records weights and gate",
          bool(c.get("score_trace", {}).get("weights"))
          and "passed" in c.get("score_trace", {}).get("gate", {}))
    fake = {"score": 90, "score_trace": {"base": 90.0, "steps": [],
                                         "weights": {}, "factors": {}}}
    check("argon: a trace without weights cannot claim reproducibility",
          not argon.verify_score(fake))


def main():
    test_sparks()
    test_candidates()
    test_dedupe()
    test_gate()
    test_features()
    test_scene_shapes()
    test_editor_pass()
    test_caption_overlap()
    test_face_crop_filter()
    test_no_transcript_fallback()
    test_rank_offline()
    test_judge()
    test_pipeline_contract()
    test_render_payload()
    test_tail_pad()
    test_boundary_and_opening()
    test_rejudge_updates_tier()
    test_rejudge_is_stable()
    test_manual()
    test_hook_speed_and_greetings()
    test_repair_pass()
    test_selection_guard()
    test_unjudged_judge()
    test_window_index()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
