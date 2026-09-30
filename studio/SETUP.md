# SETUP — ClipBlitz Studio

One app, two engines: **ProX v5** (story-first, judged cuts) and **B2 Pro X** (shot-boundary
cuts, film grade, J-cut audio), or **Both at once** — one analysis pass, both cuts side by side.

---

## Fresh PC in three steps

1. **Install Python** — https://www.python.org/downloads/ (any 3.10+). On Windows 10/11 you can
   skip this entirely: double-clicking `START.bat` installs Python for you, silently.
2. **Unzip this folder anywhere** (for example `C:\ClipBlitzStudio`). No admin rights needed.
   `bin\` already carries ffmpeg and yt-dlp — nothing else is downloaded, ever.
   (Cloned from GitHub instead of the release zip? The repo does not carry the binaries;
   run `scripts/fetch-tools.ps1` once — or on macOS/Linux `bash scripts/fetch-tools.sh`.)
3. **Double-click `START.bat`.** A window opens, prints the local address and your phone
   address, and the studio is live.

```
ClipBlitz Studio v4.1.0 (engines: ProX v5 / B2 Pro X / Both) → http://localhost:4300
  your phone (same Wi-Fi)  http://192.168.31.103:4300
```

Optional overrides (environment variables): `CB_PORT` (default 4300), `CB_ENGINE`
(default `b2`), `CB_DATA` (data directory), `CB_FFMPEG_DIR`, `CB_TOP_N`.

---

## Use it from your phone

1. Phone and PC on the **same Wi-Fi**.
2. Open the printed address — `http://192.168.31.103:4300` — in the phone's browser.
   (The studio also prints it any time: the **Connect** screen has a *Phone and network* card
   with a copy button.)
3. First launch, Windows may ask to allow Python through the firewall — choose **Private
   networks**.
4. Use the browser's **Add to Home Screen** to keep it one tap away. Honest note: a LAN
   address is not HTTPS, so the browser treats it as a shortcut rather than an installable
   app. The shortcut works everywhere; there is nothing to install from a store.

**Who renders what:** the machine running the studio does all rendering. A phone used as the
controller does none — that is why there is no hardware tension on the phone. If the *host*
machine is too weak, the studio measures it (cores, memory, ffmpeg) and says so before any job
starts: "This device can't render clips. Use your laptop or PC to render them." The Connect
screen shows the measured numbers under **This machine**.

---

## Run the engine ON an Android phone (optional, Termux)

The whole app is pure Python plus ffmpeg, so the phone itself can be the host:

```
pkg install python ffmpeg
cd clipblitz-studio && bash start.sh
```

Then open `http://localhost:4300` on the phone. Rendering happens on the phone's own silicon,
so expect slow encodes; if the device is genuinely too weak, the studio tells you up front and
you fall back to the PC.

---

## YouTube auto-post (one-time, ~15 minutes)

Full click-by-click: **SETUP-YOUTUBE.md**. Short version: create a Google Cloud project, enable
YouTube Data API v3, create an OAuth client, paste the ID + secret in the studio's Connect
screen, and add this redirect URI in Google Cloud **for this app's port**:

```
http://localhost:4300/oauth/youtube/callback
```

Keys live only in this machine's `.env`. They are never printed, never committed, and never
leave the machine except to their own provider during a test call.

---

## Copyright and strikes — read this once

Clipping is only safe when you have the right to publish what you cut.

- **Your own long videos are always safe.** That is the primary use case: point the studio
  at a stream, podcast or vlog you made and it cuts shorts out of it. Nothing to clear.
- **Someone else's material needs a licence or genuine fair use.** If it is not yours, either
  the rights holder gave you permission, or your clip is a transformative use — real
  commentary, reaction, criticism or teaching, published for that purpose. A thin edit is not
  a transformation.
- **Content ID finds unlicensed re-uploads no matter how they are edited.** Mirroring,
  pitch-shifting, speed changes or filters do not hide a match, and trying to evade matching
  is what gets channels terminated. This studio deliberately does none of that and never will.
- **The studio asks once per job.** Before the first automatic upload it asks whether the
  material is your own, licensed, or a transformative fair-use edit, and stores your answer on
  the job. The clip file is never withheld, so posting it by hand stays entirely your call.
- **You can see where a clip came from.** A job started from a YouTube link shows the uploader
  channel and video id on every clip card, and flags it when that is not the channel you
  connected for posting.

This is information and consent, not a detector. The studio cannot tell you whether a use is
fair, and it will not pretend that it can.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "This device can't render clips" | The host is below the thresholds (2 cores / 2.5 GB) or ffmpeg is missing. Use a stronger machine, or install ffmpeg. |
| Phone cannot open the address | Same Wi-Fi? Firewall allowed for Private networks? Use the address from the Connect screen, not a typed guess. |
| Port already in use | `set CB_PORT=4301` (or any free port) before starting, or close the old instance. |
| Videos fail with an unreadable-file error | The download is incomplete (missing MP4 index). Re-download the video. |
