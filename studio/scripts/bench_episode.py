"""Episode bench - the board every engine change has to beat.

Run from the studio root:

    python scripts/bench_episode.py                  # score the largest stored episode
    python scripts/bench_episode.py --job 3          # score a specific job (id or index)
    python scripts/bench_episode.py --synthetic      # no data needed; CI-safe
    python scripts/bench_episode.py --save-baseline  # record this board as the bar
    python scripts/bench_episode.py --check          # exit 1 if the board regressed

Why this exists: "the engine got better" is a claim, and claims need a number. The
podium is the product, so the board measures the podium itself on a real episode -
how many picks it fills, whether they are the same beat twice, how far apart they sit,
and how many of them open on something that grabs. The deterministic layer runs here
(no LLM, no network), so the same transcript always produces the same board and a
before/after comparison means something.

What it deliberately does NOT do: invent numbers it cannot measure. A stored job keeps
its transcript, its waveform and its peak moments but not the laughter regions, so the
ending measurement is reported as "not measurable on this fixture" rather than guessed.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402
from clipblitz import brains as brains_mod  # noqa: E402
from clipblitz import virality  # noqa: E402

STORE = os.path.join(CONFIG["data_dir"], "bench_episode.json")
RUNS_KEPT = 60
REGRESSION = {"picks": 0, "overlap": 0.10, "hook": 0.10, "score": 3.0}


# ------------------------------------------------------------------ the fixture

def load_jobs():
    path = os.path.join(CONFIG["data_dir"], "jobs.json")
    try:
        raw = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return raw if isinstance(raw, list) else list(raw.values())


def pick_job(jobs, which=None):
    usable = [j for j in jobs if j.get("segments")]
    if not usable:
        return None
    usable.sort(key=lambda j: -len(j["segments"]))
    if which is None:
        return usable[0]
    for j in usable:
        if str(j.get("id")) == str(which):
            return j
    try:
        return usable[int(which)]
    except (ValueError, IndexError):
        return None


def energy_from_waveform(wave, duration):
    """The stored waveform is a normalised amplitude trace, not the engine's (t, dB)
    series. Rebuild the series it would have measured, and label it as a rebuild."""
    if not wave or duration <= 0:
        return None
    step = duration / float(len(wave))
    series = [(i * step, float(v)) for i, v in enumerate(wave)]
    return series, sum(float(v) for v in wave) / len(wave)


def synthetic_episode():
    """Three clear beats, each restated for a minute - no data directory needed.

    Two different restatements per beat, like real speech: a single repeated line makes
    every cut in a beat a duplicate of the others, which is the engine behaving
    correctly and the fixture being wrong.
    """
    beats = [["the prize is a brand new car for the winner",
              "a brand new car is the prize tonight"],
             ["he explains how the telescope was invented",
              "the telescope invention took one man"],
             ["then the kitchen catches fire and everyone runs",
              "the fire in the kitchen spread fast"]]
    segs, t = [], 0.0
    for beat in beats:
        for rep in range(12):
            for line in beat:
                segs.append({"start": t, "end": t + 2.5, "text": line, "words": []})
                t += 2.5
    return {"id": "synthetic", "name": "synthetic three-beat episode",
            "segments": segs, "duration": t, "moments": [], "waveform": [],
            "laughs": 0, "source": {"kind": "synthetic"}}


# ------------------------------------------------------------------ the board

def hook_open(segments, start, seconds=6.0):
    """Deterministic hook read: does the cut open on a question, a number or a curiosity
    opener? Mirrors the engine's own podium tiebreak, measured the same way."""
    text = " ".join((s.get("text") or "") for s in segments
                    if start <= s.get("start", 0) < start + seconds).strip()
    if not text:
        return False
    low = text.lower()
    if "?" in text[:80]:
        return True
    if any(low.startswith(w) for w in ("how ", "why ", "what ", "when ", "who ", "which ",
                                       "did ", "can ", "will ", "is ", "are ")):
        return True
    return any(ch.isdigit() for ch in text[:24])


def worst_overlap(segments, picks):
    said = [virality.content_words(" ".join((s.get("text") or "") for s in segments
                                            if c["start"] <= s.get("start", 0) < c["end"]))
            for c in picks]
    worst, pair = 0.0, ""
    for i in range(len(said)):
        for j in range(i + 1, len(said)):
            if said[i] and said[j]:
                r = len(said[i] & said[j]) / max(len(said[i] | said[j]), 1)
                if r > worst:
                    worst, pair = r, f"{i + 1}-{j + 1}"
    return worst, pair


def run_board(job, ai=False, count=3):
    segments = job.get("segments") or []
    duration = float(job.get("duration") or (segments[-1]["end"] if segments else 0))
    energy = energy_from_waveform(job.get("waveform") or [], duration)
    laughs = job.get("laughs") if isinstance(job.get("laughs"), list) else []
    moments = [m for m in (job.get("moments") or []) if isinstance(m, dict)]

    real = brains_mod.brains
    if not ai:
        brains_mod.brains = lambda: None        # deterministic, offline, no tokens spent
    t0 = time.time()
    try:
        picks, pool, picker, ctype = virality.rank(
            segments, duration, count=count, energy=energy, laughs=laughs)
    finally:
        brains_mod.brains = real

    worst, pair = worst_overlap(segments, picks)
    # picks come back ordered by how good they are, not by time — spread is a timeline
    # fact, so sort the starts before measuring the gaps between them
    starts = sorted(c["start"] for c in picks)
    gaps = sorted(starts[i + 1] - starts[i] for i in range(len(starts) - 1))
    hype = sum(1 for c in picks if virality._is_hype(c.get("summary") or c.get("title") or ""))
    board = {
        "episode": job.get("name") or job.get("id") or "?",
        "job_id": job.get("id"),
        "source_kind": (job.get("source") or {}).get("kind", "?"),
        "picker": picker,
        "ai": bool(ai),
        "segments": len(segments),
        "duration_s": round(duration, 1),
        "moments": len(moments),
        "filled": len(picks),
        "wanted": count,
        "pool": len(pool),
        "avg_score": round(sum(c.get("score", 0) for c in picks) / len(picks), 1) if picks else 0.0,
        "hook_open_rate": round(sum(1 for c in picks if hook_open(segments, c["start"])) / len(picks), 2) if picks else 0.0,
        "worst_overlap": round(worst, 2),
        "overlap_pair": pair,
        "min_gap_s": round(gaps[0], 1) if gaps else 0.0,
        "hype_in_podium": hype,
        "ending_measurable": bool(laughs),
        "seconds": round(time.time() - t0, 2),
    }
    return board


def print_board(b):
    print(f"episode      {b['episode']}  ({b['source_kind']}, {b['segments']} segments, "
          f"{b['duration_s']}s, {b['moments']} measured peaks)")
    print(f"picker       {b['picker']}{'' if b['ai'] else '   (offline, deterministic)'}")
    print(f"podium       {b['filled']}/{b['wanted']} filled   avg score {b['avg_score']}")
    print(f"opens well   {int(b['hook_open_rate'] * 100)}% of picks")
    print(f"same beat    worst written overlap {b['worst_overlap']}"
          + (f"  (picks {b['overlap_pair']})" if b['overlap_pair'] else "  (no pair)")
          + ("  OK" if b['worst_overlap'] <= 0.6 else "  REPEAT"))
    print(f"spread       closest picks {b['min_gap_s']}s apart")
    print(f"hype in podium {b['hype_in_podium']}")
    print(f"endings      {'measured' if b['ending_measurable'] else 'not measurable on this fixture (no laughter regions stored)'}")
    print(f"ran in       {b['seconds']}s")


# ------------------------------------------------------------------ the history

def read_store():
    try:
        d = json.load(open(STORE, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_store(d):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def compare(now, base):
    """A regression is the podium getting worse on the numbers that matter."""
    bad = []
    if now["filled"] < base["filled"]:
        bad.append(f"podium shrank: {now['filled']} picks, was {base['filled']}")
    if now["worst_overlap"] > base["worst_overlap"] + REGRESSION["overlap"]:
        bad.append(f"repeated beats: overlap {now['worst_overlap']}, was {base['worst_overlap']}")
    if now["hook_open_rate"] < base["hook_open_rate"] - REGRESSION["hook"]:
        bad.append(f"weaker openings: {now['hook_open_rate']}, was {base['hook_open_rate']}")
    if now["avg_score"] < base["avg_score"] - REGRESSION["score"]:
        bad.append(f"lower scores: {now['avg_score']}, was {base['avg_score']}")
    return bad


def main():
    ap = argparse.ArgumentParser(description="Score the podium on a real episode.")
    ap.add_argument("--job", help="job id or index from data/jobs.json")
    ap.add_argument("--synthetic", action="store_true", help="use the built-in episode")
    ap.add_argument("--ai", action="store_true", help="run the real editor (needs keys; not deterministic)")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--gate", action="store_true",
                    help="fail on an unacceptable board (no baseline needed): podium not "
                         "filled, or two picks that are the same beat")
    args = ap.parse_args()

    if args.synthetic:
        job = synthetic_episode()
    else:
        job = pick_job(load_jobs(), args.job)
        if job is None:
            print("no stored episode with a transcript found - using the synthetic one")
            job = synthetic_episode()

    board = run_board(job, ai=args.ai, count=args.count)
    print_board(board)

    store = read_store()
    if args.save_baseline:
        store["baseline"] = board
        print("\nsaved as the baseline this engine must not fall below")
    runs = store.get("runs") or []
    runs.append(board)
    store["runs"] = runs[-RUNS_KEPT:]
    write_store(store)

    if args.check:
        base = store.get("baseline")
        if not base:
            print("\nno baseline recorded yet - run with --save-baseline after a good board")
            return 0
        bad = compare(board, base)
        if bad:
            print("\nREGRESSION against the baseline:")
            for b in bad:
                print(f"  - {b}")
            return 1
        print("\nno regression against the baseline")

    if args.gate:
        bad = []
        if board["filled"] < board["wanted"]:
            bad.append(f"the podium filled {board['filled']} of {board['wanted']}")
        if board["worst_overlap"] > 0.6:
            bad.append(f"two picks are the same beat (overlap {board['worst_overlap']})")
        if bad:
            print("\nTHE BOARD FAILED:")
            for b in bad:
                print(f"  - {b}")
            return 1
        print("\nthe board is acceptable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
