# Verification - ClipBlitz Studio 5.1.0

Minor release: ARGON now measures the opening and the ending of a clip instead of
trusting sentence punctuation alone. No competitor code was copied.

## Competitor study

Read the four supplied repositories and installed the REA skill at
`C:/Users/AUSU/.agents/skills/reverse-engineer-anything`.

| Repository | License | What was available | What was adopted |
|---|---|---|---|
| SupoClip | AGPL-3.0 | Full source | **Ideas only**, independently implemented: boundary strength, opening review, self-summary anchors, word-exact next-word guard |
| AutoShorts | MIT | Full source | Nothing: it generates videos from a topic, it is not a long-video clip selector |
| LiveShive | Release-only | README + installer | Nothing: no source; feature gaps recorded (live clipping, screen+face, Hinglish, music ducking, GPU tiers) |
| ClipShlip | Release-only | README only | Nothing |
| REA | MIT | Skill + MCP/CLI | Skill installed; its own rule says skip REA for complete source repos, so no binary decompilation was performed |

No AGPL code, prompts or schemas were copied. The full note is
`studio/docs/COMPETITOR-NOTES.md`.

## Algorithm change

`clipblitz/argon.py`:

- `_boundary_review` measures the ending from the last word, the next word and the gap
  between them. A cut through a word returns 0.15; a continuous next word is not a pause;
  a finished sentence with 0.45s+ of room scores 0.70-1.0.
- `_opening_review` labels a dangling conjunction, a two-word fragment, a mid-sentence
  start and a filler start. The score uses it; `_repair` can move the start to the
  previous sentence (for dangling) or the next complete sentence (for a fragment).
- `_payoff_anchors` now mines self-summary lines ("the point is", "the result was",
  "what I learned") alongside laughter, resolution lines and measured peaks.
- `boundary` and `opening` are part of the measured feature set, the score blend,
  `failure_risk`, the judge payload and the clip card detail.

The hard boundary gate was deliberately **not** added: a source segment can end a few
milliseconds inside the last word and the renderer's tail repair finishes it. Hard
rejection there would throw away good cuts. Boundary lowers the score; the existing
non-compensatory gate and judge still decide.

## Test count

```
test_argon           77 passed, 0 failed
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

**679 passed, 0 failed, 1 skipped.**

New tests: dangling opening, clean opening, strong ending, cut through a word,
continuous speech is not a pause, self-summary anchor. The earlier tail tests remain.

## End-to-end run

Job `62d36549`, video 1, `top_n=1`, ARGON 5.1.0:

- 49.1s clip, 383.9-432.9
- measured boundary 0.78, opening 1.0
- rendered file 49.43s, last caption 48.27s -> **0.83s picture tail**
- score 84, tier strong
- QC **unverified**: the judge was rate-limited and the honest offline path ran, so the
  job did not claim a verified badge

This is the correct behavior, not a failure: offline measurement cannot become a judge
pass.

## Independent model review

GLM 5.3 Flash returned **PASS** on the 5.0.2 tail-clamp code. For 5.1.0 the DeepAI child
provider returned `fetch failed` / "Pi CLI timed out" on every attempt, and Claude
returned repeated API errors. No independent PASS is claimed for 5.1.0. The local suite
and the end-to-end run above are the evidence.

## Release assets

CI builds `ClipBlitzStudio-5.1.0-windows.zip` and `ClipBlitzStudio.apk`, publishes them
to `v5.1.0`, downloads the zip back and compares hashes. The EXE smoke test checks
`/api/health`, the bundled full ffmpeg with `libdav1d`, and the 11 MCP tools.
