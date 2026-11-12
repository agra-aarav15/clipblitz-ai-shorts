# Verification - ClipBlitz Studio 5.4.3

5.4.3 fixes the release-build failure where a source with no transcript produced a
clip with score=None, no emotion and no trace. It also makes the focus fallback track
a side-on subject instead of centre-cropping them out, and makes the Connect provider
list visible at the top of the screen with cache-busted assets.

## Fixes in 5.4.3

- No transcript: ARGON now returns measured, scored windows with a score trace and an
  honest `unverified` badge instead of bare spans with `score=None`.
- Focus fallback: when no face is detected, the crop chooses the 9:16 window with the
  most edge detail (ignoring caption bands), so a side-on subject is not cut out.
- Connect: a provider status grid is shown above the fields, and app.js/styles are
  cache-busted with `?v=5.4.3`.
- The release EXE was re-tested with a landscape source and no STT key.

## Review fixes in 5.4.2

- Re-judge now starts from `raw_features` saved before the judge was folded in, so an
  unchanged verdict cannot raise a score by blending the judge twice. `hook_speed` is
  preserved across re-judge.
- `_judge_batch` uses `.get()` for measured energy/laughter, so a stored clip without
  those keys cannot silently abort the QC re-check.
- `keys.save` drops later duplicate variable lines, so a stale duplicate cannot win.
- A rejected save returns HTTP 400 instead of a success toast.
- `CB_LOCAL_KEY` is configurable in Connect.
- The focus fallback uses `(iw-ow)/2`, correct for tall sources.

## Review fixes in 5.4.1

- `auto` framing now uses the supplied focus path instead of silently centre-cropping.
- `crop`, `crop-left`, `crop-right` and `auto` use the same min() guard as focus, so
  tall/portrait sources render instead of failing.
- The audio-lead path is disabled. It delayed audio without delaying picture; the
  J-cut claim and layer were removed.
- `verify_score` re-derives the base from the recorded weights and factors, and
  rejects a trace with no weights. Base/steps are stored at 6 decimals.
- The Connect masking test now checks the real masked status rows, not the static
  provider descriptors.
- An invalid `CB_AI_ORDER` is rejected before it is written.
- A saved key can be cleared from Connect.
- `focus_path` no longer advertises an unused target_ratio.

## What changed in 5.4.0

- **Focus crop is the default.** A landscape source is cropped to a full-height 9:16
  frame that follows the largest face. The path is median-smoothed and clamped; the
  output is a real 1080x1920 file, not a blurred landscape plate. Blur-pad remains an
  explicit option.
- **The simple-filter path now maps video.** The old `-vf` branch mapped only audio,
  so a crop could produce an audio-only file. It now maps `0:v:0` and `0:a?`.
- **Score provenance.** Every clip stores `score_trace`: formula, blend, weights,
  factor contributions, gate, judge state and every adjustment. `verify_score()`
  recomputes the displayed number; `GET /api/job/<id>/audit` returns the result.
- **Connect is complete.** Groq, Gemini, Cerebras, OpenRouter, Together, OpenAI,
  Pollinations, local base/model and provider order are all editable and testable.
  The UI is generated from the same provider list the engine uses.
- **No fake fallback score.** A missing score is no longer silently rendered as 50.

## What changed in 5.3.0

- **Reaction is not laughter.** Acoustic bursts are stored as `reaction`; `laughter`
  and `tail_laugh` are only set when the transcript contains comedy evidence. A
  suspense sting raises neither payoff nor energy.
- **One emotion taxonomy.** `funny`, `suspense`, `shock`, `emotional`, `inspiring`,
  `angry`, `wholesome`, `hype`, `informative`, `awkward`. Every selected clip carries
  a dominant label; the judge must return one; the card shows it.
- **Judge disagreement is handled.** A judge that calls a suspense transcript funny
  is overruled by the transcript and the cut is flagged `emotion_mismatch`. A weak
  judge that defaults a fast exchange to `awkward`/`informative` is overruled when
  the transcript has strong explicit cues.
- **Hindi/Urdu cues.** The first Raj Shamani test was a Hindi transcript and the
  English-only cue table produced an empty emotion map. Devanagari and Urdu cues were
  added, with whole-token matching so `तुम्हारी` does not match `हार` (loss).
- **Emotion anchors.** Each present emotion gets a candidate seed, instead of only
  laughs and high-energy peaks.
- **Funny sports clips use the comedy profile.** A team-radio punchline is no longer
  buried under the sports event weight.
- **Small judge batches.** Free providers choke on a 14-candidate, 40k-character
  prompt; the judge now runs 3-candidate batches and merges the results.
- **Local permanent provider.** An OpenAI-compatible local server (Ollama) is now
  probed before the no-key shared fallback. This was tested live with a local
  3B-class model: judge calls completed in ~4s after load.
- **No rejected podium.** If the final judge rejects every rendered cut, the job
  returns no clips and says why instead of showing rejects as strong.

## Emotion benchmark

| Source | Job | Clips | Labels | Scores | Note |
|---|---|---:|---|---|---|
| F1 funny team radio | `8549c5ea` | 3 rendered, final judge rejected all | funny/awkward candidates | - | The compilation cuts mid-exchange; the engine refuses to call the rejected cuts strong. |
| Alfred Hitchcock suspense | `b675e364` | 2 | suspense, suspense | 78, 76 | One verified by the local judge; no laugh label. |
| Raj Shamani habits | `896363e3` | 3 | suspense, suspense, inspiring | 82, 77, 80 | One verified by the local judge; three different beats from one channel. |
| Raj Shamani undercover | `d7c513de` | 1 | suspense | 79 | Suspense card, not comedy. |

The F1 compilation is the honest negative result: its windows are not self-contained,
and the final judge rejects them. That is better than the old behavior, which would
have shown three high-scoring clips with wrong emotion labels.

## Tests

```
test_emotion         26 passed, 0 failed
test_reframe         13 passed, 0 failed
test_connect         13 passed, 0 failed
test_argon           89 passed, 0 failed
test_engines         29 passed, 0 failed, 1 skipped
test_learning        28 passed, 0 failed
test_agent           82 passed, 0 failed
test_trainer         64 passed, 0 failed
test_rights          62 passed, 0 failed
test_scout           57 passed, 0 failed
test_clipbench       44 passed, 0 failed
test_daily           69 passed, 0 failed
test_social          45 passed, 0 failed
test_quality         35 passed, 0 failed
test_marketplace     94 passed, 0 failed
```

**750 passed, 0 failed, 1 skipped.**

## Release

- Windows: `ClipBlitzStudio-5.4.3-windows.zip`
- Android: `ClipBlitzStudio.apk`
- Checksums: `checksums.txt`, verified with `sha256sum -c`.

## Honest limits

- The F1 compilation test did not produce three strong clips. The source is a
  fast-cut compilation; the final judge is allowed to reject it.
- Free hosted tiers are rate-limited. The permanent option is a local model; the
  app detects it but does not bundle a multi-GB model.
- No blind A/B against OpusClip has been run. No "beats OpusClip" claim is made.
- The local 3B judge is weaker than a frontier model. It is used for the permanent
  free path; the app still prefers configured cloud providers when they work.
