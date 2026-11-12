"""Emotion and reaction tests - stdlib only, no network, no ffmpeg.

Run from the studio root:   python scripts/test_emotion.py

The failure these tests lock down is specific: an acoustic energy burst is not a
laugh. A suspense scene with a sting used to be measured as laughter, which then
raised its payoff and made it look like comedy. The transcript now decides whether
a reaction is comedy; the acoustic signal is kept separately as "reaction".
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402
CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_emotion_")

from clipblitz import argon  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def segments_from(lines, wps=2.4):
    """Build sentence segments with word timings, starting at t=0."""
    segs = []
    t = 0.0
    for line in lines:
        words = []
        for w in line.split():
            words.append({"word": w, "start": t, "end": t + 1.0 / wps})
            t += 1.0 / wps
        segs.append({"start": words[0]["start"] if words else t,
                     "end": words[-1]["end"] if words else t,
                     "text": line, "words": words})
        t += 0.45
    return segs


SUSPENSE_LINES = [
    "The detective opened the door.",
    "The secret was hidden behind the wall.",
    "He heard a noise and suddenly the phone rang.",
    "Who did it?",
]
FUNNY_LINES = [
    "He told a joke about his terrible cooking.",
    "The punchline was hilarious.",
    "Everyone laughed and I cracked up.",
]
EMOTION_TEXT = {
    "funny": "That joke was hilarious and the punchline made everyone laugh.",
    "suspense": "The detective found a clue and the secret was hidden behind the door.",
    "shock": "Out of nowhere the car exploded and nobody expected it.",
    "emotional": "He cried about his father and the pain of losing him.",
    "inspiring": "She never gave up on her dream and finally made it against all odds.",
    "angry": "I was furious and it was unfair that he betrayed me.",
    "wholesome": "A kind stranger helped her and she was grateful.",
    "hype": "What an overtake, unreal speed and a huge win.",
    "informative": "Here is why the study matters and what the data means.",
    "awkward": "There was a long silence and it was awkward and embarrassing.",
}


def measure(lines, laughs=None, start=0.0):
    segs = segments_from(lines)
    end = segs[-1]["end"]
    c = {"start": start, "end": end}
    out = argon.measure_candidate(c, segs, [], laughs or [], [], scenes=[], motion=[])
    return out, segs, end


def test_labels():
    for want, text in EMOTION_TEXT.items():
        got = argon._emotion_profile(text, {"reaction": 1.0})["label"]
        check(f"emotion: {want} text is labelled {want}", got == want, got)


def test_aliases():
    check("emotion: judge alias 'tense' maps to suspense",
          argon._clean_emotion_label("tense") == "suspense")
    check("emotion: unknown judge label is not invented",
          argon._clean_emotion_label("melancholy-ish") == "")


def test_suspense_burst_is_not_laughter():
    quiet, _, _ = measure(SUSPENSE_LINES)
    loud, _, end = measure(SUSPENSE_LINES, [(0.0, 999.0, 12.0)])
    check("emotion: suspense scene is labelled suspense",
          loud["emotion_label"] == "suspense", loud["emotion_label"])
    check("emotion: a suspense sting is kept as reaction",
          loud["measured"].get("reaction", 0) > 0.5,
          str(loud["measured"].get("reaction")))
    check("emotion: a suspense sting is not laughter",
          loud["measured"].get("laughter", 0) == 0,
          str(loud["measured"].get("laughter")))
    check("emotion: a suspense sting does not inflate energy",
          abs(loud["measured"]["energy"] - quiet["measured"]["energy"]) < 1e-9,
          f"{quiet['measured']['energy']} vs {loud['measured']['energy']}")
    check("emotion: a suspense sting does not inflate the payoff",
          loud["argo_features"]["payoff"] <= quiet["argo_features"]["payoff"] + 1e-9,
          f"{quiet['argo_features']['payoff']} vs {loud['argo_features']['payoff']}")


def test_comedy_burst_is_laughter():
    quiet, _, _ = measure(FUNNY_LINES)
    loud, _, _ = measure(FUNNY_LINES, [(0.0, 999.0, 12.0)])
    check("emotion: a joke is labelled funny", loud["emotion_label"] == "funny",
          loud["emotion_label"])
    check("emotion: a joke with a real laugh keeps laughter",
          loud["measured"].get("laughter", 0) > 0.5,
          str(loud["measured"].get("laughter")))
    check("emotion: a joke's laughter raises energy",
          loud["measured"]["energy"] > quiet["measured"]["energy"],
          f"{quiet['measured']['energy']} vs {loud['measured']['energy']}")


def test_judge_label():
    c, segs, _ = measure(SUSPENSE_LINES)
    argon._apply_judge(c, {"emotion_label": "suspense", "emotion": 9,
                           "coherence": 9, "hook": 8, "payoff": 8,
                           "shareability": 7, "clarity": 8, "rewatch": 7,
                           "flags": [], "alone": True})
    check("emotion: judge can label a suspense cut suspense",
          c["emotion_label"] == "suspense", c["emotion_label"])


def test_judge_mismatch_is_corrected():
    c, segs, _ = measure(SUSPENSE_LINES, [(0.0, 999.0, 12.0)])
    argon._apply_judge(c, {"emotion_label": "funny", "emotion": 9,
                           "coherence": 9, "hook": 8, "payoff": 8,
                           "shareability": 7, "clarity": 8, "rewatch": 7,
                           "flags": [], "alone": True})
    check("emotion: judge calling suspense funny is corrected",
          c["emotion_label"] == "suspense", c["emotion_label"])
    check("emotion: correction is recorded as a flag",
          "emotion_mismatch" in (c.get("flags") or []), str(c.get("flags")))


def test_anchors_cover_emotions():
    lines = [EMOTION_TEXT[k] for k in
             ("funny", "suspense", "shock", "emotional", "inspiring", "angry")]
    segs = segments_from(lines)
    anchors = argon._emotion_anchors(segs)
    labels = {a.get("emotion_label") for a in anchors}
    check("emotion: anchors include every present emotional beat",
          {"funny", "suspense", "shock", "emotional", "inspiring", "angry"} <= labels,
          str(sorted(labels)))


def test_selection_diversifies():
    segs = segments_from([
        "The detective found a secret behind the door.",
        "He told a hilarious joke and everyone laughed.",
        "She never gave up on her dream and made it.",
    ])
    pool = []
    for i, (label, score) in enumerate((("funny", 92), ("suspense", 89),
                                        ("funny", 88))):
        pool.append({
            "start": i * 300.0, "end": i * 300.0 + 30.0,
            "score": score, "tier": "strong", "qc": "verified",
            "emotion_label": label,
            "measured": {"tail_laugh": 0, "laughter": 0},
            "argo_features": {"boundary": 0.9},
            "flags": [], "gate": {"passed": True},
        })
    # The middle suspense cut must not lose to a third funny cut just because the
    # funny one is one point stronger after MMR.
    picked = argon._select(pool, 2, 600.0, segs)
    labels = [p["emotion_label"] for p in picked]
    check("emotion: podium prefers a second emotion over another laugh",
          "suspense" in labels and len(labels) == 2, str(labels))


def test_offline_label():
    c, _, _ = measure(SUSPENSE_LINES)
    j = argon._offline_judgement(c)
    check("emotion: offline judgement carries the measured label",
          j.get("emotion_label") == "suspense", str(j.get("emotion_label")))


def main():
    test_labels()
    test_aliases()
    test_suspense_burst_is_not_laughter()
    test_comedy_burst_is_laughter()
    test_judge_label()
    test_judge_mismatch_is_corrected()
    test_anchors_cover_emotions()
    test_selection_diversifies()
    test_offline_label()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
