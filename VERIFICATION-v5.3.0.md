# Verification - ClipBlitz Studio 5.3.0

5.3.0 fixes the emotion and reaction defects found while testing real clips. The
specific failure: a suspense scene with an acoustic sting was treated as laughter
because the old acoustic detector called any energy burst above the video baseline
a laugh. That raised the payoff and made a tense scene look like comedy.

## What changed

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
test_argon           80 passed, 0 failed
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

**715 passed, 0 failed, 1 skipped.**

## Release

- Windows: `ClipBlitzStudio-5.3.0-windows.zip`
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
