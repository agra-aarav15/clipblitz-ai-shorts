## Live Chat Radar: YouTube + Twitch, post-first if you want it

`v5.7.0` adds a live-stream path to the cutting desk.

- **Watch a live chat without an API key.** YouTube uses its public web continuation;
  Twitch uses anonymous IRC. Messages, spike windows and clips are stored under
  `data/live/<video-id>/`, so closing the app does not lose the session.
- **Spikes are judged against the stream's own median.** A five-second bucket is a
  spike when it clears `max(4, median × 2.5)`. The clip window starts **25 s before**
  the burst and ends **15 s after** it, because the reaction happens before the typing.
- **Post first, or wait for quiet chat.** Post first cuts the live DVR as soon as the
  window ends. Quiet chat renders one spike per 45 s only when recent chat is below
  35% of that spike's rate. Twitch defaults to post-first; YouTube defaults to quiet.
- **Twitch uses the live DVR, not a full recording.** No multi-gigabyte file is left
  behind. The trade-off is real: a spike older than DVR, or a Twitch stream that ends
  before a quiet render, cannot be recovered.
- **YouTube replay is used when available.** A finished YouTube stream can be read
  from chat replay even if the app was off. Twitch has no replay path here.
- **Auto-post is rights-gated.** Connect your own YouTube OAuth client, tick the rights
  box, and finished clips upload through the official Data API. Until then the clip
  says `waiting_for_rights` or `not_connected`; no shared token ships in the binary.
- **Channel setup kit** (`CHANNEL-SETUP.md`) and launch assets in `docs/channel/`.
  The assistant still cannot create the channel or complete Google consent for you.

### Verified on real streams

- YouTube `ArAxjdWSvk8`: **4,497 persisted messages**, **2 spikes**, a **45.0 s
  1080×1920 clip with audio** from the `70.0–115.0 s` window; resume after restart.
- Twitch `hasanabi`: **377 messages** captured anonymously and a **36.6 s DVR
  section** downloaded while live.
- Offline: `test_live.py` **42 passed**; full suite **732 passed, 0 failed**;
  marketplace **94 passed**.

### Desktop downloads

Windows x64 setup/portable, macOS arm64/x64 DMG+ZIP, Linux AppImage+deb, plus
`electron-checksums.txt`. Builds are unsigned: SmartScreen/Gatekeeper warnings are
expected until certificates are supplied.

### Honest limits

Public chat endpoints can change; stream owners can disable chat; DVR retention is
platform-controlled; Twitch has no replay in this build; auto-post covers YouTube only;
TikTok/Instagram/Facebook/X remain assisted one-click packages. The app cannot make a
channel, grant rights, or guarantee a clip is first, viral or non-infringing.
