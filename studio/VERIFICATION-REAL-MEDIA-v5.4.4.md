# Real-media verification - ClipBlitz Studio 5.4.4

This is the local-media counterpart to the offline suites: four real videos through
the whole product (ffmpeg, speech-to-text, editor, ARGON judge, render), on this
machine, with the bundled ffmpeg and the providers configured in `.env`.

It is also where the 5.4.4 correctness pass met reality. Several real defects only
appeared on actual footage; they are listed first because they changed the release.

Machine: Windows, Python 3.12.7, 8 cores / 16 GB, bundled ffmpeg 9.0.1.
Providers during the runs: Groq `openai/gpt-oss-120b`, Gemini `gemini-3.6-flash`,
a local OpenAI-compatible server `clipblitz-local`, and the no-key Pollinations
fallback.

Sources (all owner-supplied uploads already used by the earlier emotion benchmark):

| Label | Source | Duration | Format |
|---|---|---:|---|
| TV suspense | Alfred Hitchcock Presents, "revenge" episode | 706.3s | AV1 1280x720, 25 fps, pillarboxed (active 972x720) |
| Raj habits | Raj Shamani interview (English) | 293.0s | portrait-heavy podcast frame, dark set |
| F1 radio | F1 team-radio compilation | 513.8s | AV1 1280x720, 50 fps |
| Raj spy | Raj Shamani undercover story | 370.7s | interview |

The harness is `scripts/verify_media.py`. It creates jobs in a throwaway data
directory, records wall time per stage, counts provider calls, probes every render
(1080x1920, duration, audio), verifies every score trace, and can ask named models
the ARGON judge question on the exact same clip (`--crosscheck groq,gemini`).

---

## 1. Defects found on real footage (fixed in 5.4.4)

### 1.1 A relative `CB_DATA` broke every render

With `CB_DATA=data/verify-media-544`, ffmpeg ran with `cwd=<clips dir>` and an
output path that was *also* relative, so it tried to write
`clips/data/verify-media-544/clips/x.mp4`. The demo failed with
`Error opening output ... No such file or directory`. `CONFIG["data_dir"]` is now
always absolute. The harness uses a relative default, so this was a real CLI bug,
not only a test artifact.

### 1.2 The TV source is pillarboxed, and the focus crop included the black bar

`cropdetect` on all four samples reported `crop=972:720:150:0` inside a 1280x720
frame: 150px black on the left, 158px on the right. The 9:16 focus crop is 405px
wide, so a subject near the picture edge produced a portrait frame with a black
column (verified visually at 182.7s). Fix: measure the active picture rectangle once
per source, cache it, and clamp the per-frame crop path inside it.

A dark studio background is also "black" to `cropdetect`. On the Raj Shamani set it
reported a 36% left band and a 20% top band; cropping that would delete the subject.
The detector now accepts only a **centred pillarbox or letterbox** (one axis,
near-symmetric), and returns full-frame otherwise. A synthetic test proves the clamp
keeps the leftmost 8px of the output out of the bar.

### 1.3 AV1 scene detection decoded every frame

The F1 source is 50 fps AV1. The bundled decoder ignored `-skip_frame nokey`; the
scene pass consumed **892 CPU-seconds** and held the job at 17% for over 15 minutes.
(ffprobe shows only 133 keyframes.) For AV1/VP9, `scene_cuts` now reads the real
keyframe timestamps from the container: **133 marks in 1.87s**. Other codecs keep
the scene-diff scan, now capped at 240s with the keyframe marks as the fallback.
Keyframes are a proxy, not exact scene detection; this is recorded as a limit.

### 1.4 A TCP-ready local model could stall a job for minutes

`clipblitz-local` answers `/v1/models` in 0.5s but took **29.9s** for a one-line
reply. On a rate-limited run every editor chunk and judge batch tried it, and one
Raj job took **697s**. Local calls now have a 45s cap (`CB_LOCAL_TIMEOUT`) and a
5-minute cooldown after a failure. The same Raj job fell to **332s** (and later
runs were limited by the other providers, not by local).

### 1.5 Clips ended on outros and end cards

- The first Raj run produced a verified clip ending on
  "Thank you so much for watching this clip. For more such valuable information clips,
  subscribe to Rajshamani Clips Channel."
- The first TV run produced a verified clip ending on the show's
  "Hitchcock Presents / The End" card.
Both were approved by the judge. Machine-built windows now trim trailing
outro/CTA/end-card sentences (`V._is_hype` plus an exact `OUTRO_EXACT` check that
also catches "The End" as the final clause of a multi-sentence STT segment).
A hand cut keeps its chosen outro.

### 1.6 A suspense scene was labelled "hype" because of the word "yes"

The measured emotion table gave the TV window hype 11 hits ("yes" x11) and suspense
1 hit, so the card said hype before any model saw it. The generic cues ("yes",
"kind", "thank", "care", "support", "together", "come on") were removed, and the
suspense vocabulary gained the actual crime/thriller words (`killed`, `murder`,
`beaten`, `police`, `detective`, `lieutenant`, `gun`, `knife`, `scream`, ...). The
same window now measures **suspense**, and a judge that says "hype"/"wholesome" on a
transcript with real suspense evidence and no hype evidence is overruled with an
`emotion_mismatch` flag.

The two TV clips below were rendered immediately before this cue fix, so their stored
emotion field still says "hype"; the pixels are unaffected and the deterministic
label for that exact text is now suspense. The next run writes the corrected label.

### 1.7 Pollinations now fails hard instead of retrying

The shared no-key fallback returned 400/402 on every call. It is now cooled down for
30 minutes on those codes instead of being retried for each chunk.

### 1.8 The judge provider is recorded

`score_trace.judge` now carries `provider` and `model` (thread-local record from the
provider layer), so a verified clip can be traced to the model that verified it.
This is what made the model-disagreement findings below possible.

---

## 2. Final runs

### TV suspense (706s)

`data/verify-media-544/tv-final.json` - warm scene/active/STT caches.

| Clip | Window | Length | Score | Tier | QC | Render |
|---|---|---:|---:|---|---|---|
| 1 | 187.7-208.6s | 20.9s | 78 | strong | **verified** (local) | 1080x1920, 30 fps, audio |
| 2 | 242.8-268.8s | 26.0s | 77 | strong | unverified (judge call incomplete) | 1080x1920, 30 fps, audio |

- No clip ends on the end card; the active-area clamp removed the black column.
- Stage totals: probe 1.0s, active area 4.0s, audio 6.0s, energy 18.1s, laughter
  15.5s, peak/scene 33.6s, caption band 4.7s, transcription 15.7s, ARGON 179.2s,
  metadata 0.8s, render 132.1s, QC 58.4s -> **468.9s**.
- Provider calls that succeeded: 2 (Groq 1, local 1). The rest were 429/403/timeout.

Earlier runs of the same source gave **0 clips** (final judge rejected all) and
**1 clip ending on the end card**. That variance is real and is a model/provider
result, not a deterministic engine result.

### Raj Shamani habits (293s)

`data/verify-media-544/raj-final.json` - warm caches, providers exhausted.

| Clip | Window | Length | Score | Tier | QC | Render |
|---|---|---:|---:|---|---|---|
| 1 | 145.8-190.9s | 45.1s | 78 | strong | unverified | 1080x1920, audio |
| 2 | 235.6-275.5s | 39.8s | 75 | strong | unverified | 1080x1920, audio |

Clip 2 is the useful one: it ends on "And I don't need anybody to, because I can
rescue myself. I can change. The only person who's truly stopping me is me." The
previous run's version of this window ended on the channel subscription plug; the
outro trim removed 17.5s of CTA and the clip is still 39.8s. Its opening is still
weak ("now what because you can waste...").

All 10 candidates passed the gate this time; both selected clips were scored without
a judge because every provider failed. They are honestly labelled unverified.

Stage totals: probe 1.0s, active 2.8s, audio 16.4s, energy 12.3s, laughter 8.4s,
peak/scene 15.5s, caption 1.2s, transcription 7.2s, ARGON 185.1s, metadata 1.4s,
render 189.9s, QC 69.5s -> **512.5s**.

### F1 radio (514s)

`verify-report.json` - 0 clips. 10 candidates, 9 failed the gate, the final judge
rejected the remaining cut. This reproduces the 5.4.3 negative result: the source is
a fast-cut compilation, and the windows are not self-contained. Wall 468.2s, of
which the old AV1 scene pass was over 15 minutes in an earlier run (now 1.8s).

### Raj spy (371s)

`verify-report.json` - 0 clips. 10 candidates, 7 failed the gate; the final judge
rejected the rendered cut. 5 of the 6 successful provider calls in this run went to
Pollinations (the weak free fallback) because Groq/Gemini were rate-limited; it is
not evidence that the source has no usable moment. Wall 553.2s.

---

## 3. Model verification (the judge layer)

The cross-check asks each named model the same ARGON judge question on the exact
final transcript. Where a call succeeded:

| Clip | Groq gpt-oss-120b | Gemini 3.6-flash |
|---|---|---|
| TV 187.7-208.6 (first run) | awkward, hook 2 / payoff 2 / coherence 3, flags: starts_mid_thought, ends_before_payoff, not_standalone, slow_open, weak_hook, weak_ending, confusing_context | suspense, hook 7 / payoff 7 / coherence 6, flag: confusing_context |
| TV 648.3-696.6 (end-card run) | funny, hook 7 / payoff 6 / coherence 6, no flags | 429, no answer |
| Raj 235.6-293.0 (CTA-ending run) | inspiring, hook 5 / payoff 6 / coherence 7, flags: starts_mid_thought, weak_hook | inspiring, hook 7 / payoff 5 / coherence 7, flag: weak_ending (channel subscription) |

What this shows, without spin:

- **The models disagree materially.** The same TV window is a 2/10 failure to Groq
  and a 7/10 suspense cut to Gemini. Groq also approved the end-card clip that the
  product now trims. The final judge's identity can flip a podium.
- **The judge is not deterministic.** The Raj clip was first verified with
  `weak_hook`, then the same provider later flagged `starts_mid_thought` and
  `weak_hook` on the same window.
- **Quota is part of the result.** The final TV and Raj runs could not complete the
  cross-check: Groq returned HTTP 403 (Cloudflare 1010), Gemini 429, Pollinations
  402, and local timed out on most calls. The clips are marked unverified because
  that is true, not because the engine decided to be modest.
- The trace now names the provider/model, so a verified badge can be audited:
  the verified TV clip was judged by `clipblitz-local`.

This is exactly the model-routing warning in `docs/ARGON-MASTER-PLAN.md`: one model
writes, a different model reviews, and the same model must not both invent the metric
and certify it. The product records the disagreement instead of averaging it away.

---

## 4. Speed

Measured wall-clock on this machine, no invented numbers.

| Item | Before | After |
|---|---:|---:|
| AV1 F1 scene pass (133 keyframes) | 892 CPU-seconds / >15 min stall | 1.87s (keyframe marks) |
| TV scene pass, cold | 174s | 23s (peak stage, keyframe path) |
| Raj habits job with a slow local model | 697s | 332s (local cap + cooldown) |
| Synthetic 10-min offline rank (5.4.4 engine) | 31.3s | 3.2s (cached rows + bisect) |
| Synthetic 90-min offline rank (5.4.4 engine) | did not finish in 300s | 11.5s |

The LLM stage is still the wall-clock owner when providers are slow or limited:
TV spent 179s in ARGON ranking and 58s in the QC re-judge; Raj spent 185s + 70s.
Rendering two clips took 132s (TV) and 190s (Raj) - 2-5x realtime for a 21-45s clip
because the focus path runs face detection on eight frames and the canvas is
1080x1920. This is the next speed target, not something to hide.

Deterministic stages (probe, audio, energy, laughter, scene, transcription from
cache, render) are stable; the variance is provider latency and quota.

---

## 5. Honest limits

- The free tiers were exhausted during this benchmark. Groq 403/429, Gemini 429,
  Pollinations 402, local ~30s per call. Any result above that is `unverified` was
  produced without a working judge, and is labelled that way.
- No claim that these are the best possible clips. The TV verified clip is a
  suspense scene; the Raj clip 2 has a strong payoff but a weak opening; the F1
  source genuinely lacks self-contained windows.
- Keyframe timestamps are a proxy for AV1 scene detection, not exact scene diffs.
- The pillarbox clamp only accepts a centred pillarbox/letterbox. An asymmetric
  inset or a dark set is deliberately left uncropped.
- The emotion cue table still contains some benchmark-derived tokens. The biggest
  false positive found here ("yes") was removed; a larger re-measurement is still
  needed.
- The two TV clips carry a stale "hype" label from before the cue fix. The window's
  deterministic label is now suspense; no re-render was done to keep the evidence
  honest about which build produced the pixels.
- No blind A/B against a commercial clipper.

## 6. Reproduce

```bash
# offline contract
python scripts/test_argon.py        # 123 passed
python scripts/test_reframe.py      # 17 passed, includes a real pillarbox render
python scripts/test_emotion.py      # 26 passed

# real media (needs keys; writes only to the given dir)
python scripts/verify_media.py \
  --video "data/uploads/1794442544_tv_suspense_revenge2.mp4" --label tv \
  --video "data/uploads/1794444361_raj_shamani_habits_local.mp4" --label raj \
  --video "data/uploads/1794442991_f1_funny_radio3.mp4" --label f1 \
  --video "data/uploads/1794402407_raj_shamani_spy.mp4" --label spy \
  --data "data/verify-media-544" --top-n 3 --crosscheck groq,gemini
```

Reports: `data/verify-media-544/verify-report.json`, `tv-final.json`,
`raj-final.json`. Rendered files: `data/verify-media-544/clips/`.
