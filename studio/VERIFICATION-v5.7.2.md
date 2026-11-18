# ClipBlitz Studio v5.7.2 — facecam layout, captions, attribution, multi-stream

## What changed

- **Facecam band on top** — live clips detect the streamer's webcam corner and
  render a 520×320 face band above a 1080×1440 gameplay crop. The old 9:16
  centre crop removed the face entirely.
- **Captions actually appear** — two real bugs fixed:
  - the downloaded section starts at a non-zero PTS, so the caption clock was
    offset; every render now resets PTS with `setpts=PTS-STARTPTS`;
  - live clips with no subtitle track now use the local/API transcriber
    (`_stt_words`), with STT times correctly treated as relative to the section.
- **Captions above the Shorts UI** — live captions use a 430 px bottom margin,
  not the old 300 px that sat under YouTube's controls.
- **Quality** — live renders now use `libx264 -preset medium -crf 19`,
  `high` profile, `yuv420p`, 160 kbps audio, and Lanczos scaling.
- **Attribution** — every auto-post description includes:
  - `Source: <creator> — <channel URL>`
  - `Full stream: <video URL>`
  - chat-spike context, credit and an honest fan-clip/no-affiliation note.
- **Hashtags** — GTA clips get `#GTA6 #GTAVI #GTA6Clips #GTA6Shorts
  #GTA6India #Gaming #GamingShorts #Streamer #Shorts #Viral`; other games get a
  generic gaming set.
- **2–3 streams at once** — the Live URL field accepts up to three URLs, one per
  line. Each session keeps its own channel, chat, spikes and clips.
- **Shared upload budget** — auto-post reserves an atomic daily slot (default 6).
  With three streams the UI splits that to two clips each; the backend refuses a
  seventh automatic upload with a clear `daily_limit` status instead of hitting
  a YouTube quota error.
- **Channel URL** — YouTube/Twitch probes now store the creator's channel URL,
  so attribution is a real link, not just a display name.

## Verified

- **868 tests passed, 0 failed** across all 19 test scripts.
- Packaged backend `/api/health`: version **5.7.2**, `stt: local`,
  `youtube_ready: true`, `live.enabled: true`.
- Facecam test render: 1080×1920, face band at top, gameplay below, STT captions
  visible above the bottom edge.
- Electron self-test: **health ok, page ok**.
- Installed Windows build at
  `E:\clipping\Clipblitz\ClipBlitzStudio`; desktop/Start Menu shortcuts point
  there.

## Honest limits

- Attribution and the facecam layout **do not grant permission**. A streamer can
  still claim or strike a re-upload. The rights checkbox is not a legal shield.
- YouTube's API quota is about six uploads per day; the budget enforces that
  instead of silently failing.
- The local Whisper model is downloaded on first use; the first clip with no
  subtitle track will take longer.
- If no face is detected, the render falls back to the normal vertical crop
  rather than inventing a webcam box.
