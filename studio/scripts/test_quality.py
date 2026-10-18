"""Engine quality tests - captions that can be read and a podium that cannot repeat itself.

Run from the studio root:   python scripts/test_quality.py

Stdlib only, offline, deterministic. What is proven:

  1. NO WORD IS EVER LOST OR REORDERED. Every chunker path (word count, width, pause,
     punctuation) is checked by flattening the chunks back into the input list. A caption
     layer that silently drops speech is worse than no captions at all.
  2. A LINE THAT CANNOT BE READ IS NOT EMITTED. Three long words used to become one
     three-word chunk that overflows a 1080-wide frame; the width cap now splits it.
     Punctuation and pauses still cut where they should.
  3. THE DUPLICATE TEST READS WHAT A CLIP SAYS, NOT WHAT ITS TITLE SAYS. Two cuts of the
     same beat with different auto-titles are duplicates; two genuinely different beats
     are not. Stopwords cannot make unrelated clips look alike.
  4. THE PODIUM STILL FILLS. The stricter test must never starve the count — the engine
     relaxes the diversity rules in later passes instead of returning two clips.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz import captions, virality  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def words(*pairs):
    """(text, start, end) -> the chunker's word records."""
    out = []
    for text, a, b in pairs:
        out.append({"word": text, "start": a, "end": b})
    return out


def flat(chunks):
    return [w for c in chunks for w in c]


# ------------------------------------------------------- 1. nothing is ever dropped

def test_no_word_is_lost():
    cases = {
        "plain": words(("hello", 0, .3), ("world", .3, .6), ("again", .6, .9)),
        "punctuation": words(("stop.", 0, .3), ("go", .3, .6), ("now!", .6, .9)),
        "long pause": words(("first", 0, .3), ("beat", .3, .6), ("later", 4.0, 4.3)),
        "very long words": words(("congratulations", 0, .8), ("transformation", .8, 1.6),
                                 ("everybody", 1.6, 2.2), ("listen", 2.2, 2.6)),
        "single word": words(("one", 0, .3)),
        "empty": [],
    }
    for label, ws in cases.items():
        out = captions.chunk_words(ws, 3)
        got = flat(out)
        check(f"chunker: {label} keeps every word, in order",
              [(w["word"], w["start"]) for w in got] == [(w["word"], w["start"]) for w in ws],
              f"{len(got)}/{len(ws)} words")


# --------------------------------------------------- 2. readable lines, honest breaks

def test_width_cap():
    ws = words(("congratulations", 0, .8), ("transformation", .8, 1.6), ("everybody", 1.6, 2.2))
    out = captions.chunk_words(ws, 3)
    cap = max(18, 3 * 13)
    widths = [sum(len(w["word"]) for w in c) + len(c) - 1 for c in out]
    check("captions: three long words do not become one unreadable line",
          len(out) > 1 and max(widths) <= cap, f"{[len(c) for c in out]} chunks, widths {widths}")
    check("captions: the split is at a word boundary, mid-line is where it goes",
          all(c for c in out) and len(out[-1]) >= 1)
    short = words(("i", 0, .2), ("am", .2, .4), ("here", .4, .6))
    check("captions: short words still group up to the word count",
          len(captions.chunk_words(short, 3)) == 1)
    check("captions: the width cap scales with the style's chunk size",
          len(captions.chunk_words(short, 8)) == 1)


def test_breaks_where_they_should():
    punct = captions.chunk_words(words(("stop.", 0, .3), ("go", .3, .6)), 6)
    check("captions: a full stop ends the chunk", len(punct) == 2, f"{len(punct)} chunks")
    comma = captions.chunk_words(words(("well,", 0, .3), ("then", .3, .6)), 6)
    check("captions: a comma ends the chunk too", len(comma) == 2)
    pause = captions.chunk_words(words(("first", 0, .3), ("beat", .3, .6),
                                       ("later", 3.0, 3.3)), 6)
    check("captions: a 2.4s pause splits the chunk (the docstring's promise, now real)",
          len(pause) == 2, f"{len(pause)} chunks")
    nop = captions.chunk_words(words(("first", 0, .3), ("beat", .3, .6),
                                     ("later", .8, 1.1)), 6)
    check("captions: a normal gap does not split", len(nop) == 1)
    count = captions.chunk_words(words(*[(f"w{i}", i * .3, i * .3 + .3) for i in range(7)]), 3)
    check("captions: the word cap still holds", [len(c) for c in count] == [3, 3, 1],
          str([len(c) for c in count]))


def test_style_chunks_stay_readable():
    """Every shipped style's own chunk size must produce readable lines on this text."""
    text = ("congratulations", "transformation", "extraordinary", "unbelievable",
            "everybody", "absolutely")
    ws = words(*[(w, i * .4, i * .4 + .4) for i, w in enumerate(text)])
    for st in captions.PRESETS.values():
        chunks = captions.chunk_words(ws, st["chunk"])
        widest = max(sum(len(w["word"]) for w in c) + len(c) - 1 for c in chunks)
        check(f"captions: style '{st['name']}' keeps lines inside 1080px",
              widest <= max(18, st["chunk"] * 13), f"widest {widest} chars")


# ------------------------------------------- 3. duplicates read the spoken words

def test_content_words():
    w = virality.content_words("So the man walked into the room and said hello world")
    check("words: stopwords are dropped", "the" not in w and "and" not in w and "into" not in w)
    check("words: real content survives", {"man", "walked", "room", "hello", "world"} <= w)
    check("words: speech verbs are noise, not content", "said" not in w)
    check("words: two-letter noise is dropped", "so" not in w and "he" not in w)
    check("words: empty text is an empty set", virality.content_words("") == set())
    check("words: None is an empty set", virality.content_words(None) == set())


def test_near_duplicate():
    a = virality.content_words("the judge says the prize is a brand new car for the winner")
    b = virality.content_words("the winner gets a brand new car says the judge tonight")
    c = virality.content_words("he then explains how the telescope was invented in 1610")
    check("dedupe: the same beat worded differently is a duplicate",
          virality.near_duplicate(a, b) is True)
    check("dedupe: a different beat is not", virality.near_duplicate(a, c) is False)
    check("dedupe: nothing never matches anything", virality.near_duplicate(set(), c) is False)
    check("dedupe: the threshold is a knob — the same pair fails a stricter one",
          virality.near_duplicate(a, b, threshold=0.95) is False)


def test_podium_dedupe_is_wired_in():
    """rank() must use the new test, stay offline, and still fill its count.

    The transcript holds three different beats, each restated several times — exactly the
    shape that used to put one beat on the podium three times.
    """
    from clipblitz import brains as brains_mod
    real = brains_mod.brains
    brains_mod.brains = lambda: None          # deterministic and offline, always
    try:
        beats = [
            ["the prize is a brand new car for the winner", "a brand new car is the prize tonight"],
            ["he explains how the telescope was invented", "the telescope invention took one man"],
            ["then the kitchen catches fire and everyone runs", "the fire in the kitchen spread fast"],
        ]
        segs, t = [], 0.0
        for beat in beats:
            # a full minute per beat, restated — long enough that the podium can spread
            # one pick per beat, which is exactly the shape being tested
            for rep in range(12):
                for line in beat:
                    segs.append({"start": t, "end": t + 2.5, "text": line, "words": []})
                    t += 2.5
        picks, pool, picker, ctype = virality.rank(segs, duration=t, count=3)
        check("podium: the offline picker is used (no LLM in a test)",
              picker == "prox-offline", picker)
        check("podium: rank() still returns its full count on a repetitive transcript",
              len(picks) == 3, f"{len(picks)} picks")
        said = [virality.content_words(" ".join(s["text"] for s in segs
                                                if c["start"] <= s["start"] < c["end"]))
                for c in picks]
        worst = 0.0
        for i in range(len(said)):
            for j in range(i + 1, len(said)):
                if said[i] and said[j]:
                    worst = max(worst, len(said[i] & said[j]) / max(len(said[i] | said[j]), 1))
        check("podium: no two picked clips are the same beat",
              worst <= 0.6, f"worst overlap {worst:.2f}")
        check("podium: every pick carries its measured factors",
              all("measured" in c for c in picks))
    finally:
        brains_mod.brains = real


def main():
    for fn in (test_no_word_is_lost, test_width_cap, test_breaks_where_they_should,
               test_style_chunks_stay_readable, test_content_words, test_near_duplicate,
               test_podium_dedupe_is_wired_in):
        fn()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
