# ClipBlitz Studio v5.7.3 — live A/V sync, captions, quality

## Root causes found in real clips

### 1. Audio was 4.6 seconds ahead of the picture

A downloaded HLS section had **video starting at PTS 6.05s and audio at 1.40s**.
The renderer reset each stream independently with `setpts` / `asetpts`, so the
audio (and every STT caption) ran **4.65 seconds ahead** of the streamer's face
and the gameplay. That is the latency that made the Kai Cenat clip unwatchable.

Fix: `ffmpeg_tools.av_start_times()` measures both starts; `cut_clip()` trims both
streams at the **same PTS** (`max(video_start, audio_start)`) before resetting.
STT words are shifted onto the video clock by the same amount.

Verified on Kai's clip by cross-correlating the rendered audio against the source
at the video start: **best lag = 0.000s, correlation 0.995**.

### 2. The old quality bug was real

`--force-keyframes-at-cuts` was making yt-dlp re-encode HLS sections as
**mpeg2video** (1920x1080, ~4.4 Mbps, visibly blurry). It also made the old
9:16 crop upscale 1080 -> 1440.

Fix:
- removed `--force-keyframes-at-cuts`; new sections are H.264 or AV1;
- old mpeg2 section files are rejected and re-downloaded;
- gameplay is a native-height 1080x1080 crop (11% wide fill, not 33% vertical
  upscale), on a blurred background;
- `medium`/CRF19 replaced by `fast`/CRF19 for reasonable render time while
  keeping the high-profile, yuv420p, 160 kbps output.

### 3. The packaged facecam detector was blind

OpenCV was bundled, but its **Haar cascade XML files were not**, so
`facecam_box()` silently returned None in the installed app. That is why the
streamer disappeared even after the facecam code shipped.

Fix: `ClipBlitzServer.spec` now collects `cv2/data/*.xml`. A test render of the
installed build shows the face card on top of the gameplay.

Face detection also samples at 960px instead of 480px and scores faces near the
frame edge, so a small corner webcam wins over a larger character face in the
game. A frame-filling talking-head scene is not mistaken for a corner webcam.

### 4. Captions

- STT is now shifted to the video clock (same 4.65s correction).
- Default local Whisper model changed from **tiny** to **base**; the installed
  `.env` has `CB_WHISPER_MODEL=base`.
- Live captions group **5 words**, do not split on every punctuation mark, and
  hold each event for at least 0.18s. Repeated "Nope. Nope. Nope." is one stable
  line instead of a flicker of six one-word events.
- Caption margin is 300px, above YouTube's bottom UI.

### 5. YouTube said "clips are not going"

Actual API response captured from the account:

```json
{"error":{"code":400,"message":"The user has exceeded the number of videos they may upload.","errors":[{"reason":"uploadLimitExceeded"}]}}
```

This is YouTube's **account upload limit**, not the app and not the API quota.
The app now stores the reason, marks the day, and shows:

`platform_daily_limit — YouTube's account upload limit is already used today.
The clip is saved locally. Wait for YouTube to reset it ... or verify the channel
at youtube.com/verify, then use Post now.`

It no longer retries every render or releases the slot into a misleading "HTTP
Error 400: Bad Request".

## Verified

- Full suite: **all 19 scripts pass** (test_marketplace fixed to 77).
- Installed app `/api/health`: **5.7.3**, `stt: local`, `youtube_ready: true`,
  `live.enabled: true`.
- Kai Cenat clip re-rendered: **1080x1920, facecam layout, 40.33s video /
  38.95s audio, 0.000s audio lag**.
- Kai captions: grouped 5-word events, no one-word flicker.
- Clip file:
  `C:\Users\AUSU\AppData\Roaming\ClipBlitz Studio\clips\live_VZqAPdUvqnQ_s1.mp4`

## What cannot be fixed retrospectively

The clips already uploaded to YouTube before this build keep the old audio lead
and old compression. YouTube does not allow editing the video file in place.
They have to be deleted or replaced by a new upload after the daily upload limit
resets (or after channel verification). New renders from 5.7.3 onward are fixed.

## Late pass: real facecam detection and reel polish

The Haar-only detector still missed a small, downward-looking corner webcam
(Ray's `s10`), and sometimes selected a giant in-game character instead (Kai's
`s18`). The renderer now uses:

- **YuNet** (`face_detection_yunet_2023mar.onnx`, 228 KB) bundled with the app;
- Haar as a second opinion;
- an extra scan of the left/right side bands;
- clustering across sampled frames, with a corner cluster preferred over a
  centre game-face cluster.

Measured results on real sections:

- Ray `s10`: webcam `(x=0.062, y=0.660, w=0.18, h=0.22)` — bottom-left, correct;
- Kai `s18`: webcam `(x=0.008, y=0.398, w=0.18, h=0.249)` — corner, not the giant
  game manager;
- Kai `s37`: webcam `(x=0.001, y=0.403, w=0.18, h=0.220)`.

Reel layout changes:

- face card enlarged to 560x310 and the source view bar + chat strip cropped out;
- game panel crops the bottom 12% so a stream's own burned-in subtitles do not
  print twice under our captions;
- bottom caption band is darker and cleaner;
- live captions use the new **Reel Clean** style (Arial 70, 3px outline, no pop);
- titles now strip truncated emoji tails and reject repetitive chat spam;
- chat polling sleeps 0.75–3.0s instead of 2–15s.

Verified frames: `final2-s2.jpg`, `s6-prof.jpg`, `q2-top10.jpg`; all 19 test
scripts pass on the final source.
