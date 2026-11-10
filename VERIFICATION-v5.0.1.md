# Verification - ClipBlitz Studio 5.0.1

> Superseded by `VERIFICATION-v5.0.2.md`: GLM 5.3 Flash found a fallback-tail edge case that could
> land 0.1s inside a long next word. 5.0.2 fixes it.

Patch release: the ARGON ending fix. No new engine, no new dependency, no cloud call.

## What changed

`pipeline._tighten_edges` used to trim the tail to `last_word + 0.45` only when the old
window had more than 1.2s of silence, and otherwise left whatever the selector gave it.
The rendered F1 clips ended 0.29-0.36s after the last caption. The new code:

1. finds the last word that starts before the old cut, including a word that crosses it;
2. walks forward until speech actually pauses, capped at 1.2s, finishing the current word;
3. cuts inside that pause with a target of **0.8s** (`CB_TAIL_PAD`, clamped 0.4-1.5) and
   **1.15s** after a measured laugh;
4. if the transcript simply ends, keeps the full tail;
5. if commentary is continuous with no usable pause, keeps a 0.30s tail rather than chop
   the next syllable;
6. clamps to the source duration;
7. shortens the closing video fade from 0.22s to 0.12s so the fade does not eat the tail.

## Measured result

On the same two F1 jobs used for 5.0.0:

| Job | Clip | Old tail | New tail |
|---|---|---|---|
| `a657a491` | 1 | 0.29s | **0.80s** |
| `a657a491` | 2 | 0.35s | **0.80s** |
| `a657a491` | 3 | 0.35s | **0.80s** |
| `9e7859a2` | 1 | 0.35s | **0.53s** |
| `9e7859a2` | 2 | 0.30s | **0.30s** (continuous commentary, no pause) |
| `9e7859a2` | 3 | 0.36s | **0.80s** |

Five of six cuts now have 0.5-0.8s of real room. The sixth is wall-to-wall race
commentary; adding a longer tail would have meant cutting the next word, so it keeps an
honest 0.3s instead of a claimed 0.8s.

Rendered proof: `a657a491_1.mp4` is 42.0s of picture with the last caption at 41.2s;
`9e7859a2_1.mp4` is 57.1s with the last caption at 56.54s.

## Test count

```
test_argon           70 passed, 0 failed
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

672 passed, 0 failed, 1 skipped.

## Independent model review

No independent PASS is claimed for this patch. The available child providers failed:
Claude (Fable 5.1, Sonnet 5, Haiku 4.5) returned repeated API errors, and DeepAI's
child task runner timed out on `pi --version`. The earlier Gemini PASS covers commit
`4d7a495` (5.0.0), not this tail change. The local suites and the rendered tails above
are the evidence for 5.0.1.

## Release assets

CI builds `ClipBlitzStudio-5.0.1-windows.zip` and `ClipBlitzStudio.apk`, uploads both
to the `v5.0.1` tag, downloads the published zip back, and compares hashes. The EXE
smoke test checks `/api/health`, the bundled full ffmpeg with `libdav1d`, and the 11
MCP tools.
