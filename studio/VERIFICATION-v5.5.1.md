# Verification - ClipBlitz Studio 5.5.1

5.5.1 is a one-bug fix found by testing the **real** URL path, not a test double.

## The bug

`yt-dlp` was asked for manual and automatic captions. YouTube answered one language
with **HTTP 429** (Too Many Requests) *after* the video itself had downloaded. Without
`--ignore-errors`, yt-dlp exited non-zero, `ingest._ytdlp()` treated that as a failed
download, and the whole job died at 1%:

```
error  download failed
Download failed: ERROR: Unable to download video subtitles for 'en': HTTP Error 429
```

Captions are optional. A caption failure must never throw away a good video.

## The fix

- `--ignore-errors` on the yt-dlp call.
- If a video file exists after the attempt, return it even when the exit code is
  non-zero; a truncated file fails the pipeline's probe with its own message.
- A genuine download with no video still raises `Download failed`.
- Tests added: caption 429 keeps a >1 MB video; no video still raises; the flag is
  present. `scripts/test_captions.py`: **16 passed**.

## Real URL test (no speech-to-text key, no AI key)

Source: `https://www.youtube.com/watch?v=zsPDT8Adczw` (Mexico GP, 274.6 s), downloaded
by the app's own yt-dlp call with `--ignore-errors`.

- Download: 177 MB 1080p in 155.6 s; `en-orig.json3` captions landed despite the 429.
- Captions: 22 blocks / 230 words parsed.
- Pipeline (empty provider store, `CB_DATA` throwaway): **done in 71.25 s**,
  `captions+argon-measured`, **0 provider calls**.
- Candidates: 10, 6 failed the measured gate; 1 final clip.
- Render: **1080x1920, 15.87 s, audio present, next to a Hindi transcript**.
- Honest note: 1 strong clip on this short, single-incident source is a quality
  outcome, not a three-clip promise. Longer TV/Raj sources are the three-clip tests.

## Native window test (published 5.5.0 bundle, same desktop code)

- Unzipped the release to F:, launched `ClipBlitzStudio.exe 4318`.
- Process stayed alive; `MainWindowTitle = "ClipBlitz Studio"`.
- `/api/health` returned 200; one `msedgewebview2.exe` child was running.
- This proves the window, WebView2 and bundled server start together. It is the manual
  check CI's `--self-test` cannot do.

## Suite

- Captions **16**, providers **28**, ARGON **123**, all other suites unchanged.
- Studio: **816 passed, 0 failed** (was 813 + 3).
- Repo checkout: **832 passed, 0 failed, 1 skipped**.

## Not done

- No fresh long Raj/TV three-clip benchmark in this pass. The engine is unchanged from
  5.4.4; the new caption/download path is what 5.5.1 fixes and verifies.
- YouTube posting still needs an owner-verified OAuth client; no public one-click.
