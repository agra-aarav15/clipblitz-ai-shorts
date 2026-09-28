"""Learning loop + rights gate tests for ClipBlitz Studio - stdlib only, offline.

Run from the studio root:   python scripts/test_learning.py

Proves the two new safety properties the feature promises:

  1. LEARNING IS INERT UNTIL IT IS EARNED. With fewer than 10 logged choices the
     ranking weights are exactly the base profile, so a fresh install behaves
     byte-for-byte like the shipped engine. Once the threshold is crossed each
     factor moves by at most +/-10%, deterministically, and Reset puts it back.
  2. THE RIGHTS GATE HOLDS THE POST. An unanswered job cannot post, an unknown
     answer is rejected, and nothing is posted until the owner answers.

The store lives in a throwaway temp data dir, so this never touches real data.
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_learn_")

import clipblitz.social as social        # noqa: E402
from clipblitz import learning, pipeline, virality  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def clip(**kw):
    base = {"engine_id": "b2", "score": 80, "duration": 40.0,
            "laugh_ending": False, "hook": "A plain opening line", "title": "A clip"}
    base.update(kw)
    return base


def seed(n, **kw):
    for i in range(n):
        learning.log("post", clip(**kw), {"engine_id": "b2", "rights_ok": "own"})


# --------------------------------------------------------------------- learning

def test_learning_inert_below_threshold():
    learning.reset()
    base = virality._weights("comedy")
    check("learning: no events -> no adjustment", learning.adjustment() == {})
    check("learning: no events -> weights are the untouched base profile",
          virality._weights("comedy") == base)
    seed(learning.MIN_EVENTS - 1, laugh_ending=True)
    check("learning: one event short of the threshold is still inert",
          learning.adjustment() == {} and virality._weights("comedy") == base,
          f"{learning.MIN_EVENTS - 1} events")


def test_learning_nudges_and_caps():
    seed(1, laugh_ending=True)                       # now exactly MIN_EVENTS
    adj = learning.adjustment()
    check("learning: the threshold crosses and an adjustment appears", bool(adj), str(adj))
    nudged = virality._weights("comedy")
    base = virality.WEIGHT_PROFILES["comedy"]
    worst = max(abs(nudged[k] / base[k] - 1.0) for k in base if base[k])
    check("learning: never more than +/-10% on a single factor", worst <= 1e-9 + 0.10,
          f"worst {worst:.3f}")
    check("learning: payoff rises for an owner who keeps laugh endings",
          nudged["payoff"] > base["payoff"],
          f"payoff {base['payoff']} -> {round(nudged['payoff'], 4)}")
    check("learning: the hook factor falls when no kept cut opens on a question",
          nudged["hook"] < base["hook"],
          f"hook {base['hook']} -> {round(nudged['hook'], 4)}")
    check("learning: deterministic (same store, same answer)",
          virality._weights("comedy") == nudged)
    p = learning.profile()
    check("learning: the profile reports real counts",
          p["events"] == learning.MIN_EVENTS
          and p["laugh_ending"]["count"] == learning.MIN_EVENTS
          and p["active"] is True, str(p["events"]))


def test_learning_question_hooks_and_reset():
    learning.reset()
    seed(6, hook="How does this land?")
    seed(6, hook="Plain opener here")
    p = learning.profile()
    check("learning: question hooks are counted from the clip's own opening",
          p["question_hook"]["count"] == 6 and p["events"] == 12, str(p["question_hook"]))
    check("learning: hook factor is nudged for question openers",
          learning.adjustment().get("hook", 1.0) > 1.0, str(learning.adjustment()))
    learning.reset()
    check("learning: reset empties the store and the weights", learning.profile()["events"] == 0
          and learning.adjustment() == {})
    check("learning: the store lives in the data dir only",
          os.path.dirname(learning._file()) == CONFIG["data_dir"])


# ------------------------------------------------------------------ rights gate

def test_rights_gate(tmp_calls):
    job = {"id": "gate1", "clips": [clip(), clip()], "auto_post": True, "engine_id": "b2",
           "rights_ok": None, "rights_pending": True, "privacy": "public"}
    pipeline.JOBS["gate1"] = job
    check("rights: an unknown answer is rejected",
          pipeline.set_rights(job, "because-i-said-so") is False and not job["rights_ok"])
    check("rights: nothing posts while the job waits (no rights, no post)",
          pipeline.resume_autopost("gate1") is False and not tmp_calls)
    check("rights: the three honest answers are accepted",
          pipeline.RIGHTS_IDS == {"own", "licensed", "fair_use"},
          str(sorted(pipeline.RIGHTS_IDS)))
    check("rights: every option carries a note the UI can show",
          all(r.get("note") for r in pipeline.RIGHTS))
    check("rights: the gate is consent, not evasion",
          "evade" in pipeline.RIGHTS_NOTE and "Content ID" in pipeline.RIGHTS_NOTE)
    pipeline.set_rights(job, "own")
    check("rights: answering stores it on the job", job["rights_ok"] == "own")
    check("rights: answering resumes the held auto-post",
          pipeline.resume_autopost("gate1") is True)
    for _ in range(50):
        if not job["rights_pending"] and tmp_calls:
            break
        time.sleep(0.1)
    check("rights: the resumed post actually ran, once per clip",
          len(tmp_calls) == 2, str(tmp_calls))


def test_post_gate_is_learned():
    learning.reset()
    pipeline.JOBS["gate2"] = {"id": "gate2", "clips": [clip()], "auto_post": False,
                              "engine_id": "b2", "rights_ok": None, "rights_pending": False}
    learning.log("post", clip(laugh_ending=True), pipeline.JOBS["gate2"])
    p = learning.profile()
    check("learning: a manual post is logged as one real choice",
          p["events"] == 1 and p["kinds"].get("post") == 1, str(p["kinds"]))


def main():
    calls = []
    social.post_clip = lambda job, i, targets, on_update=None, wait=False: calls.append((i, targets))
    social.youtube_connected = lambda: False
    test_learning_inert_below_threshold()
    test_learning_nudges_and_caps()
    test_learning_question_hooks_and_reset()
    test_rights_gate(calls)
    test_post_gate_is_learned()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
