# ClipBlitz channel setup kit

This is the part I cannot do for you: Google requires **your** signed-in account to
create the channel, accept the YouTube Terms, and complete OAuth consent. Everything
below is prepared so those steps take minutes, not an afternoon.

The Instagram reel you sent makes the strategic point better than a feature list: in a
live moment, the clipper that waits for the VOD has already lost. The channel should
sell **the first usable clip**, not "another AI editor".

The launch-week plan generated from the two reels and the actual MIT `youtube-agent-skill`
tools is in **[CHANNEL-LAUNCH-PLAN.md](CHANNEL-LAUNCH-PLAN.md)**; the editable calendar
is `channel-kit/calendar.csv`.

Prepared assets:

- `docs/channel/avatar-1080.png` — square avatar (YouTube crops it to a circle)
- `docs/channel/banner-2560x1440.png` — channel banner (title-safe centre)

---

## 1. Create the channel (5 minutes)

1. Sign in at <https://www.youtube.com> with the Google account that should own the
   channel. Turn on 2-Step Verification first; YouTube may ask for it.
2. Open <https://www.youtube.com/create_channel>.
3. Choose **Use my name** for a personal channel or **Use a business name** for a Brand
   Account. A Brand Account is better if you may add an editor later.
4. Name: `ClipBlitz` (or `ClipBlitz Studio`). Handle suggestions:
   `@clipblitz`, `@clipblitzstudio`, `@clipblitzhq`, `@clipblitz.live`.
   Handles must be unique; the channel name itself does not have to be.
5. Upload `avatar-1080.png` and `banner-2560x1440.png`.
6. Paste the description below. Replace the URL only if you have a real one.

### Description

```text
Long video in. The clips that matter out.

ClipBlitz is a self-hosted clipping desk: it measures a spoken clip's opening and
ending, judges the exact cut, and refuses to publish filler. Live mode watches a
YouTube or Twitch chat, remembers the moment a room erupts, and cuts the reaction
window — post-first for launch streams, or during quiet chat when CPU matters.

Built and tested on real streams. No watermark. No monthly fee. No fake "viral" score.

The tool lives here: https://github.com/agra-aarav15/clipblitz-ai-shorts
```

Do **not** write "first clip every time" or "guaranteed viral". The honest claim is
faster than waiting for a VOD, not faster than every other person on earth.

---

## 2. Channel defaults (5 minutes)

In **YouTube Studio → Settings**:

- **Channel → Basic info:** add the description, contact email, and country.
- **Upload defaults → Basic info:** title template blank, description:
  `Full source: [link]\n\nClipped with ClipBlitz.` Add `#Shorts` only when the video is
  actually vertical and under three minutes.
- **Upload defaults → Advanced:** comments on, license Standard YouTube License
  unless you own the source and want Creative Commons.
- **Permissions:** do not add managers until you trust them.
- **Community:** set a default comment filter; live chat clips attract reaction spam.

### First three uploads (use footage you own)

1. **"I built a live clipper that doesn't wait for the VOD"** — 20–35 s screen capture:
   chat spike → clip appears → upload. Hook in the first two seconds.
2. **"The 25 seconds before the spike"** — show why the window starts before the burst.
3. **"One long video, one honest clip"** — the ARGON measured path, no overclaiming.

The three verified clips already in `studio/VERIFICATION-v5.6.1.md` are from other
creators' videos. **Do not upload them to your channel.** They are test fixtures, not
assets you own. Use your own recording, a licensed clip, or explicit permission.

---

## 3. Connect YouTube auto-post (15 minutes, one time)

The app never ships a shared OAuth secret. You create your own client:

1. Open <https://console.cloud.google.com/> and create/select the project you own.
2. **APIs & Services → Library → YouTube Data API v3 → Enable.**
3. **OAuth consent screen:** External, Testing is fine for your own channel. Add your
   Google account under **Test users**. Fill the app name and support email.
4. **Credentials → Create credentials → OAuth client ID → Desktop app** (or Web
   application). Copy the client ID and secret.
5. In ClipBlitz open **Connect → YouTube**, paste the ID and secret, press **Test &
   save**.
6. Copy the **redirect URI** shown by the app into the OAuth client's **Authorized
   redirect URIs**. It is usually
   `http://localhost:4300/oauth/youtube/callback`; if the app chose another port, use
   the exact string on screen.
7. Press **Connect YouTube** and approve the YouTube upload scope with the channel
   account.

While the OAuth app is in **Testing**, Google expires the refresh token after about
seven days. Re-consent with **Connect YouTube**, or publish the app in Google Cloud.
The app says this in plain language when it happens.

Quota is real: the YouTube Data API gives 10,000 units/day by default; an upload costs
about 1,600, so roughly six uploads/day. Batch your posts; do not promise "unlimited".

---

## 4. The launch-stream play (the reel's idea, made honest)

For a launch stream (for example a major game release):

1. **Before the stream:** confirm you have permission to clip and post the streamer's
   content. If you do not, clip your own reaction or your own stream instead.
2. Connect YouTube once, tick **I own this stream, or I have permission**, and choose
   **Post first** in the Live tab.
3. Start the watcher on the channel **before** the stream goes live. The Twitch path
   waits for the channel, then joins the anonymous chat and reads the live DVR.
4. Watch the first card. A spike window is 25 s before + 15 s after the burst; the clip
   renders as soon as the window ends and uploads if the rights box and OAuth are set.
5. Keep the default **Unlisted** privacy for the first launch. Review the clip, then
   publish. "First" is worth nothing if the clip is wrong or infringing.
6. Do not run ten channels from one machine. One watcher already decodes and renders;
   ten will melt the CPU and trip platform limits.

**Twitch caveat:** this build uses Twitch's live DVR, not a full local recording. If a
spike is older than the DVR window, or the stream ends before a quiet-policy render,
the clip cannot be recovered. That is why Post first is the Twitch default. Twitch
also has no chat replay in this build; if the app was off, there is nothing to score.

---

## 5. A 20-second channel trailer script

Use this as a structure, not a word-for-word copy of the reel:

| Time | Picture | Words |
|---|---|---|
| 0–2 s | Fast cut: chat exploding, then a finished vertical clip | "Every clipper waits for the VOD." |
| 2–4 s | The clip posts; timestamp counter | "By then, the moment is already old." |
| 4–9 s | Screen: Live tab, spike card, 25 s before / 15 s after | "This watches the chat. It remembers the 25 seconds *before* the room reacts." |
| 9–14 s | Clip renders and lands in the channel | "Post first. Or wait for quiet chat so your CPU survives." |
| 14–18 s | Honest limits on screen | "Your own OAuth. Your own rights. No shared token." |
| 18–20 s | Logo + GitHub URL | "ClipBlitz. Long video in. The clips that matter out." |

Do not use a copyrighted song, a streamer's face, or gameplay you do not have rights to
in the trailer. Screen-record your own app and your own source.

---

## 6. What still needs you

- The Google login and channel creation.
- The OAuth consent click.
- The rights decision for every stream.
- The first upload review. The app can post automatically; it cannot take
  responsibility for content you do not own.
