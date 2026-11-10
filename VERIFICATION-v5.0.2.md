# Verification - ClipBlitz Studio 5.0.2

Patch release: fixes one edge case in the 5.0.1 ending logic. No other behavior changed.

## The bug

The 5.0.1 fallback for continuous commentary used `cut = last + 0.30` when the
next word was longer than the 1.2s search window. If that word started within 0.30s of
`last`, the fallback landed inside it. Example: last word ends 8.0, next word starts 8.2
and runs to 12.0; the cut at 8.3 sliced the word.

Found by an independent read-only review with **GLM 5.3 Flash (high thinking)**, which
traced the tests by hand because plan mode blocked execution. The repro and the smallest
fix were both provided by that review.

## The fix

`clipblitz/pipeline.py`:

- the fallback tail is clamped to `next_word_start - 0.05`, never past `last`;
- the search limit now ends the walk regardless of whether the last in-window word ended
  before the old cut, so a long next sentence cannot be swallowed;
- the pause threshold is 0.50s, so a cut always keeps at least 0.45s of real pause.

A regression test (`argon: the fallback tail never lands inside the next word`) covers the
8.0 / 8.2 / 12.0 repro.

## Measured tails (unchanged from 5.0.1)

| Job | Clip | Old tail (5.0.0) | New tail |
|---|---|---|---|
| `a657a491` | 1 | 0.29s | **0.80s** |
| `a657a491` | 2 | 0.35s | **0.80s** |
| `a657a491` | 3 | 0.35s | **0.80s** |
| `9e7859a2` | 1 | 0.35s | **0.53s** |
| `9e7859a2` | 2 | 0.30s | **0.30s** (continuous commentary) |
| `9e7859a2` | 3 | 0.36s | **0.80s** |

Fresh end-to-end job `b19f4431` (top_n=2, one qualifying clip) rendered 22.9s of picture
with the last caption at 21.73s and a **1.15s** tail after a measured laugh. It was
correctly marked `unverified` because the judge call did not return a pass.

## Test count

```
test_argon           71 passed, 0 failed
test_engines         29 passed, 0 failed, 1 skipped
test_learning        28 passed, 0 failed
test_agent           75 passed, 0 failed
test_trainer         64 passed, 0 failed
test_rights          62 passed, 0 failed
test_scout           57 passed, 0 failed
test_clipbench       44 passed, 0 failed
test_daily           69 passed, 0 failed
test_social          45 passed, 0 failed
test_quality         35 passed, 0 failed
test_marketplace     94 passed, 0 failed
```

673 passed, 0 failed, 1 skipped.

## Release assets

CI builds `ClipBlitzStudio-5.0.2-windows.zip` and `ClipBlitzStudio.apk`, publishes them to
the `v5.0.2` tag, downloads the zip back and compares hashes. The EXE smoke test checks
`/api/health`, the bundled full ffmpeg with `libdav1d`, and the 11 MCP tools.
