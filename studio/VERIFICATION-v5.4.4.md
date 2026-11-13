# Verification - ClipBlitz Studio 5.4.4

5.4.4 is a correctness and performance pass on ARGON, not a feature release. It fixes
three ways a clip could be scored or selected on numbers that were not true, two
ways the repair loop could not do its job, and a quadratic path that made a
90-minute source spend minutes before the judge was even called.

No UI, rights, provider or publishing behavior changed. Nothing is published by a
test, and no test touches the network or a real provider.

## Fixed in 5.4.4

### P0 - a clip could be scored on the wrong measurements

- Repair moved a window, re-measured it, and then `score_candidate` silently reused
  the saved **pre-judge features from the old window** (`raw_features` wins when it
  exists). A repaired clip was therefore judged on one transcript and scored on
  another. `measure_candidate` now clears the saved pre-judge state, so a repaired
  window is scored on its own factors. The stable-rejudge behavior from 5.4.2 is
  unchanged: `rejudge_clips` still restores the saved raw features on purpose.

### P0 - a gate-rejected cut could fill the podium

- When no candidate reached `strong`, `_select` returned `candidates[0]` even when
  that cut had failed the non-compensatory gate. With a real judge that is a
  rejected clip presented as the result. Rules now:
  - a usable cut (gate passed, 60-74) can still be a one-clip podium;
  - a **measured-only** run (no judge) returns its best window, honestly labelled
    reject/unverified, so a no-key install still produces a clip;
  - when a judge actually spoke and every cut failed the gate, the podium is empty
    and the pipeline reports an empty result instead of a fake highlight.

### P0 - an incomplete judge call was treated as a judge opinion

- If the ARGON judge call failed and the shipped six-field judge returned no rows,
  its defaults (`coherence 5`, `payoff 5`) came back without an offline marker.
  `score_trace.judge.offline` was `False` and the gate could pass on measurements
  alone. `virality.judge_cuts` now marks those rows `unjudged`, `judge_fail` fails
  them, and ARGON replaces them with the honest measured-only judgement.

### P1 - `hook_speed` could only ever be 0 or 1

- It scanned one synthetic "sentence" that began at the cut start, so the delay was
  always zero whenever it fired. It now measures the real sentences in the first ten
  seconds. A question four seconds into the cut scores lower than one that opens the
  cut, which is the whole point of the factor.

### P1 - the repair loop could not reach half its own repairs

- The pool only admitted fatal flags, `ends_abrupt` and `not alone`. Steps 2 (slow
  hook) and 4 (too long) require warning flags, so they were effectively dead code.
  `_needs_repair` now admits repairable warning defects, and repairs run without a
  brain too (the re-judge is then the honest offline one).
- A premature ending extended to the **furthest** sentence end within 18 seconds,
  swallowing several sentences and overshooting the payoff. It now extends to the
  nearest next end, then to a measured laugh.
- A too-long window was trimmed to the 10-second minimum, throwing away the setup the
  payoff depends on. It is now trimmed to the longest window the 75-second band
  allows.
- A repair that could only be legal by opening on an intro/greeting now restores the
  original validated window instead of marking a live candidate `_drop`.

### P1 - intro and greeting windows could still be built

- Sparks were hype-filtered, but payoff/peak/story anchors could expand to a window
  that opened on "Welcome back to the show". Machine-built and machine-repaired
  windows now skip a hype opening or are dropped; a manual cut (`rank_single`) keeps
  the exact window the owner dragged.

### P1 - the podium spread grew without bound on long sources

- The minimum start gap was `max(8s, 8% of duration)`: eight minutes on a three-hour
  podcast, which would refuse two honest beats a minute apart. It is now capped at
  60 seconds (spread capped at 120).

### P1 - candidate building was quadratic in transcript length

- `_starts_on_filler` and every window text/word lookup walked the whole transcript.
  Measured with `cProfile` on this machine, a synthetic 10-minute transcript spent
  21.2 of its 31.3 seconds inside `_starts_on_filler`; a synthetic 90-minute one did
  not finish within 300 seconds. Window queries now bisect a cached segment index,
  and ARGON caches the sentence/word rows for the transcript it is measuring.
  Emotion cue counting now tokenizes once per candidate instead of running a regex
  per cue.
  - 10-minute synthetic, offline: **31.3s -> 3.2s**
  - 90-minute synthetic, offline: **>300s (timed out) -> 11.5s**
  These are synthetic transcripts, not a claim about every source; ffmpeg and the
  judge calls are not part of that number.

### P2

- `_cinema_anchors` accepts dict motion points as well as `(time, value)` tuples.
- `virality._words_in` / `_text_in` keep a one-entry segment index and fall back to a
  full scan when the transcript is not monotonic.
- A rendered clip now stores `text_stats`, and a re-judge uses it instead of
  mislabelling `failure_risk` as `list_incomplete`.
- `daily.py` and `pipeline.process` no longer default a missing engine id to `b2`
  (new jobs are ARGON; old jobs with a stored id still replay as stored).
- `scripts/test_social.py` no longer crashes on a cp1252 Windows console when a
  provider message contains a non-ASCII arrow.

## New checks

`scripts/test_argon.py` grew from 89 to 118 checks. The new ones cover exactly the
defects above: stale pre-judge features, nearest-sentence repair, warning-flag
repairs without a brain, hype openers, bounded spread, unjudged judge rows, a
silent source with no measured peaks, an unordered transcript, and the bisect window
index against a brute-force scan. `scripts/test_emotion.py` still passes after the
token-counting change.

## Offline test results

Run from `clipstudio/` on Windows, Python 3.12.7, no network, no provider keys used:

```
test_argon           118 passed, 0 failed
test_engines          30 passed, 0 failed, 0 skipped
test_agent            82 passed, 0 failed
test_learning         28 passed, 0 failed
test_trainer          64 passed, 0 failed
test_rights           62 passed, 0 failed
test_scout            57 passed, 0 failed
test_clipbench        44 passed, 0 failed
test_daily            69 passed, 0 failed
test_social           45 passed, 0 failed
test_quality          35 passed, 0 failed
test_marketplace      77 passed, 0 failed
test_emotion          26 passed, 0 failed
test_reframe          13 passed, 0 failed
test_connect          13 passed, 0 failed
```

**763 passed, 0 failed.**

`test_marketplace` reports 77 in the `clipstudio/` checkout and 94 in the
`repo-clipblitz/studio` checkout, because the repository checkout sits next to a
`.claude-plugin/marketplace.json` and therefore runs 17 extra manifest checks. Both
were run; both pass. `test_engines` reports 30 passed / 0 skipped in `clipstudio/`
and 29 passed / 1 skipped in `repo-clipblitz/studio/`: the frozen ProX tree it
compares against only sits next to the first checkout (the skip is explicit, not a
pass). The full repository-checkout run is 779 passed, 0 failed, 1 skipped.

## Not run in 5.4.4

- No live provider, judge or render job was run for this verification. The changes
  are all deterministic and covered offline; a render/LLM benchmark would need the
  owner's keys and is not claimed here.
- No blind A/B against a commercial clipper. No "beats X" claim is made.
- The emotion cue list still contains some tokens that came from observed test
  transcripts. It was left unchanged because removing them without a re-run of the
  owner's benchmark would change quality on sources that were not measured here.
  This is an open quality question, not a hidden fix.

## Release

- Version: 5.4.4 (`APP_VERSION`, plugin manifest, cache-busted web assets).
- Windows/Android bundles are built by the existing release step; this checkout was
  not packaged here.
