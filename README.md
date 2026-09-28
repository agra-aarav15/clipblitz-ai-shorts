# ClipBlitz — AI Video Clipping Studio

<p align="center">
  <img src="docs/shots/01-studio.png" width="900" alt="ClipBlitz Studio — One window, two engines" />
</p>

<p align="center">
  <b>One long video in. The clips that matter out.</b><br />
  Your own OpusClip — self-hosted, zero watermark, zero monthly fees, honest scores.
</p>

<p align="center">
  <a href="https://github.com/agra-aarav15/clipblitz-ai-shorts/releases/tag/v4.0.0"><b>Download v4.0.0 Release</b></a> ·
  <a href="studio/SETUP.md"><b>Setup &amp; Phone Guide</b></a> ·
  <a href="BEGINNER-GUIDE.md"><b>Absolute Beginner Guide</b></a> ·
  <a href="SETUP-YOUTUBE.md"><b>YouTube Auto-Post</b></a>
</p>

---

## What is this

ClipBlitz is an AI-powered video editor that turns podcasts, interviews, gaming sessions, and long YouTube videos into viral, vertical shorts ready for YouTube Shorts, TikTok, and Instagram Reels.

Unlike tools that blindly split videos every 30 seconds, ClipBlitz thinks like a professional human editor:

1. **Story pass** — segments the episode into complete, self-contained stories (setup, build-up, punchline/payoff).
2. **Draft pass** — drafts the tightest 15-60s cut inside each story, prioritizing regions with audience laughter and vocal energy.
3. **Deterministic edge rules** — snaps starts to sentence boundaries (no "um", "so", or mid-word starts) and rides endings through audience reactions.
4. **Strict QC judge** — an independent LLM pass reads the exact final transcript of the cut and issues a pass/fail verdict (`verified` vs `unverified`).
5. **Traceable score v2** — computed strictly from the judge's ratings and acoustic factors (energy, laughter, pacing). No fake numbers.

---

## Two engines in one window (ClipBlitz Studio v4.0.0)

With **v4.0.0**, you get both flagship engines in a single interface with side-by-side comparison:

| Engine | How it cuts | Look & Feel | Audio |
|---|---|---|---|
| **ProX v5** | Story-first + sentence snap + QC judge | Clean 1080x1920 vertical blur-pad | 0.18s fade in/out |
| **B2 Pro X** | Shot-boundary snap + scene grammar | Cinematic film grade (S-curve + vignette) | J-cut: audio leads picture by 0.35s |
| **Both** | **One analysis pass, two cuts side by side** | Compare both grades and timings | Pick your favorite cut |

<p align="center">
  <img src="docs/shots/03-compare.png" width="850" alt="Both engines side by side in the comparison view" />
</p>

---

## Works on any fresh PC — and on your phone

<p align="center">
  <img src="docs/shots/05-mobile-studio.png" width="280" alt="ClipBlitz Studio on mobile" />
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/shots/04-connect.png" width="560" alt="Connect screen with phone address and hardware capability" />
</p>

- **One-click fresh-PC install:** `START.bat` checks for Python and installs it silently if missing. Bundled `ffmpeg` and `yt-dlp` ship inside the release zip — nothing else is downloaded.
- **Use it from your phone:** Open the printed `http://192.168.x.x:4300` address in your mobile browser. The computer does all the heavy video rendering; your phone controls the studio and previews the clips. Add to Home Screen for a native app feel.
- **Hardware-aware protection:** The host machine is measured (CPU cores, RAM, ffmpeg). Weak devices are told immediately: *"This device can't render clips. Use your laptop or PC to render them."* — avoiding mid-render crashes.

---

## Rights Guardrails — post what you have the right to post

ClipBlitz makes the safe path the easy path and makes a risky post loud. It never touches
content matching: there is no pitch shift, speed change, mirror or fingerprint trick anywhere in
the code, because those are circumvention — Content ID finds unlicensed re-uploads anyway, and
trying to dodge it is what gets channels terminated.

- **One-time rights gate.** Before the first automatic upload from a job, the Clips screen asks
  whether the material is your own, licensed, or a transformative fair-use edit, with an honest
  note on each. The answer is stored on the job and shown on it. Auto-post waits for it; the clip
  file is never withheld, so posting by hand stays the owner's call.
- **Source awareness.** A job started from a YouTube link records the uploader channel and video
  id (from the yt-dlp metadata the download already fetched) and shows them on every clip card,
  flagging the clip when that is not the channel you connected for posting.
- **Transformative-edit badge.** Rendered clips list the layers the render actually applied —
  captions burned into the picture, vertical reframing, the film grade, the J-cut — as one line,
  so a fair-use claim is anchored to something real and verifiable.

Clipping **your own** long videos is always safe and is the primary use case. Other people's
material needs a licence or genuine fair use. Full text: **Copyright and strikes** in
[studio/SETUP.md](studio/SETUP.md).

## A learning loop that stays on your machine

Every choice on a finished clip — posted, re-rendered from the Candidate Lab, hand-cut on the
Transcript timeline — is logged to a local `data/learning.json`. From **10 choices** on, the
ranking weights drift toward the endings, hooks and clip lengths this owner keeps, capped at
**10% per factor** and fully deterministic. Below the threshold nothing moves, so a fresh install
ranks exactly like the shipped engine. The Connect screen shows the real counts, shares and
median behind the profile, with a Reset button. No cloud, no external service, no extra scope on
the YouTube OAuth consent (`youtube.upload` cannot read Analytics, so view/retention feedback is
intentionally not pulled rather than silently widening what the app is allowed to do).

---

## Quickstart

### Option A: Ready-to-run release (recommended)
1. Download **`ClipBlitzStudio-4.0.0.zip`** from [Releases](https://github.com/agra-aarav15/clipblitz-ai-shorts/releases/tag/v4.0.0).
2. Unzip the folder anywhere.
3. Double-click **`START.bat`** (Windows) or run `bash start.sh` (macOS / Linux / Termux).
4. Open `http://localhost:4300` in your browser.

### Option B: Clone from source
```bash
git clone https://github.com/agra-aarav15/clipblitz-ai-shorts.git
cd clipblitz-ai-shorts/studio

# Fetch the bundled ffmpeg + yt-dlp (one time)
powershell -ExecutionPolicy Bypass -File scripts\fetch-tools.ps1   # Windows
bash scripts/fetch-tools.sh                                        # macOS / Linux

# Run the studio
python run.py                                                      # -> http://localhost:4300
```

Paste your free Groq key ([console.groq.com/keys](https://console.groq.com/keys)) into the **API keys** card, drop a video or paste a YouTube URL, and press **Edit my video**. No keys? Press **Demo video** for a generated end-to-end test run.

---

## Project Layout

```
studio/                 # Flagship ClipBlitz Studio (port 4300) — both engines, phone-ready
  run.py                # Studio server entry point
  START.bat             # One-click Windows launcher (silent Python install)
  start.sh              # macOS / Linux / Termux launcher
  clipblitz/            # Unified engine (pipeline, virality, cinema, hardware, server)
  web/                  # Obsidian Keynote UI (monochrome glass, PWA manifest, self-hosted fonts)
  android/              # Android WebView companion app source
  SETUP.md              # Complete guide for fresh PCs, phones, and Termux
clipblitz/              # Classic ClipBlitz v3.5 (ProX v5 engine only, port 4301)
b2prox/                 # Classic B2 Pro X (Cinematic engine only, port 4302)
docs/shots/             # Unaltered, real screenshots of every screen
BEGINNER-GUIDE.md       # Zero-terminal guide for non-developers
SETUP-YOUTUBE.md        # YouTube Data API v3 OAuth walkthrough
```

---

## Technology

- **Backend:** Pure Python 3 standard library `ThreadingHTTPServer`. Zero pip packages required to run from source.
- **Frontend:** Pure HTML5, CSS3, vanilla JavaScript. Zero build steps, zero npm, zero external CDNs.
- **Typography:** Self-hosted `Inter`, `JetBrains Mono`, and `Space Grotesk` woff2 fonts.
- **Video:** Bundled `ffmpeg 9.0.1` and `yt-dlp`. Blur-pad 9:16 framing, ASS word-pop subtitle animations.
- **AI Dual-Brain:** Groq (`openai/gpt-oss-120b` or `llama-3.3-70b`) as primary brain + Google Gemini (`gemini-2.0-flash`) as automatic failover.

---

## License

MIT License. Free to use, modify, and self-host for personal and commercial projects.
