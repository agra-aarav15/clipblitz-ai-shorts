# ClipBlitz — the complete beginner guide

**Never used a terminal? Never used GitHub? This guide is for you.**

By the end you will have ClipBlitz running on your own computer and you will have made your first
short clip from a long video. Follow it top to bottom. Every command is copy-paste ready. Nothing
is assumed except that you can open a folder and follow links.

If a step fails, jump to [Troubleshooting](#troubleshooting) — every error a beginner hits here has
a known fix.

**Time needed:** about 20 minutes the first time (most of it waiting on downloads).

---

## Contents

1. [What ClipBlitz is (in one minute)](#1-what-clipblitz-is-in-one-minute)
2. [Words you will see](#2-words-you-will-see)
3. [Get the files](#3-get-the-files)
4. [Install Python](#4-install-python)
5. [Install the two helper tools](#5-install-the-two-helper-tools-the-easy-way)
6. [Get a free AI key](#6-get-a-free-ai-key)
7. [Start ClipBlitz](#7-start-clipblitz)
8. [Make your first clip](#8-make-your-first-clip)
9. [The five screens explained](#9-the-five-screens-explained)
10. [Optional: post to YouTube automatically](#10-optional-post-to-youtube-automatically)
11. [Troubleshooting](#troubleshooting)
12. [FAQ](#faq)
13. [Word list](#word-list)

---

## 1. What ClipBlitz is (in one minute)

You give it a long video. It gives you short vertical clips (the kind you see on YouTube Shorts,
TikTok and Instagram Reels). It cuts them itself, writes the captions, writes the title and
hashtags, and it can even upload them for you.

It runs **on your computer**. Your videos are not uploaded to anyone's server. There is no
subscription and no watermark.

The clever part is that it does not cut randomly. It reads the transcript, finds the *stories* in
the video, cuts each clip so it starts on a real sentence and ends on a payoff, and then a second
pass (the "judge") checks whether the finished clip actually makes sense on its own. Clips that
fail are labelled honestly instead of being shown as if they were good.

---

## 2. Words you will see

| Word | What it means in plain English |
|---|---|
| **Terminal** (also *console*, *command prompt*, *shell*) | A window where you type commands instead of clicking. You will open it once or twice. |
| **Command** | A line of text you paste into the terminal and run with Enter. |
| **Folder / directory** | The same thing. A place where files live. |
| **PATH** | The list of folders your computer searches when you type a command's name. If a program is "not on PATH", typing its name does nothing — that is why this project ships its own copies of tools instead. |
| **GitHub** | A website where code lives. You will download a *release* from it (a ready-made zip). |
| **Repo** (repository) | One project's folder on GitHub. |
| **Zip** | A single file containing many files, compressed. Windows and macOS can both open one by double-clicking. |
| **API key** | A long password-like string that lets the app talk to an AI service. Free to make. |
| **ffmpeg** | The tool that actually cuts and renders video. ClipBlitz uses it but you never type its name. |
| **yt-dlp** | The tool that downloads a video from YouTube when you paste a link. |
| **Port** | A numbered door on your computer. ClipBlitz uses door 4301. `localhost:4301` means "my own computer, door 4301". |

---

## 3. Get the files

### Option A — download the release (easiest, no GitHub account)

1. Open <https://github.com/agra-aarav15/clipblitz-ai-shorts/releases>
2. Find the newest release at the top (for example *ClipBlitz v3.5.0*).
3. Under **Assets**, click the file ending in **`.zip`** (for example `ClipBlitz-v3.5.0.zip`).
4. It downloads. **Right-click it → Extract All** (Windows) or **double-click it** (macOS).
5. Move the extracted folder somewhere simple, for example `C:\ClipBlitz` (Windows) or
   `~/ClipBlitz` (macOS/Linux).

Avoid spaces and special characters in the path — `C:\ClipBlitz` is perfect, `C:\My Stuff\New
folder (2)\` will cause avoidable pain.

### Option B — with Git (if you want to update later with one command)

Only if you already have Git. In a terminal:

```bash
git clone https://github.com/agra-aarav15/clipblitz-ai-shorts.git
cd clipblitz-ai-shorts
```

> Later, `git pull` inside that folder updates you to the newest version.

---

## 4. Install Python

ClipBlitz needs **Python 3.10 or newer**.

### Windows

1. Go to <https://www.python.org/downloads/> and click the big yellow **Download Python** button.
2. Run the installer.
3. **IMPORTANT:** on the very first screen, tick the box at the bottom that says
   **“Add python.exe to PATH”**. If you miss this, typing `python` later will fail.
4. Click **Install Now**, wait, then **Close**.

### macOS

1. Go to <https://www.python.org/downloads/> and download the macOS installer.
2. Run it and click through (Continue → Continue → Install).

Or, if you have Homebrew: `brew install python`.

### Linux

```bash
sudo apt update && sudo apt install python3 python3-pip     # Debian / Ubuntu
sudo dnf install python3 python3-pip                        # Fedora
```

### Check it worked

Open a terminal **in the ClipBlitz folder** and type:

```bash
python --version
```

You should see something like `Python 3.12.4`. On macOS/Linux you may need `python3 --version`
instead — if `python` is not recognised but `python3` works, use `python3` everywhere below.

**How to open a terminal in the ClipBlitz folder:**

- **Windows:** open the folder in File Explorer, click the address bar, type `cmd`, press Enter.
- **macOS:** right-click the folder in Finder → *Services* → *New Terminal at Folder*.
- **Linux:** most file managers have "Open Terminal Here" on right-click.

---

## 5. Install the two helper tools (the easy way)

ClipBlitz needs **ffmpeg** (cuts video) and **yt-dlp** (downloads from YouTube). You do **not**
need to put them on PATH — the app looks in its own `bin/` folder first, and this project ships
scripts that fetch them there.

### Windows (PowerShell)

In the ClipBlitz folder, open a terminal and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\fetch-tools.ps1
```

It downloads ffmpeg (about 80 MB) and yt-dlp, unpacks them into `bin\`, and then verifies both.

### macOS / Linux (or Windows Git Bash)

```bash
bash scripts/fetch-tools.sh
```

On macOS the script uses Homebrew if you have it; otherwise it prints the two manual links.

### If the script cannot download for you

Download these by hand and place them exactly as shown:

| Tool | Where to get it | Where to put it |
|---|---|---|
| ffmpeg (Windows) | <https://www.gyan.dev/ffmpeg/builds/> → *ffmpeg-release-essentials.zip* | Extract into the ClipBlitz `bin\` folder. You must end up with `bin\ffmpeg-7.x\bin\ffmpeg.exe` |
| ffmpeg (macOS) | <https://evermeet.cx/ffmpeg/> or `brew install ffmpeg` | `bin/ffmpeg-7/bin/ffmpeg` |
| ffmpeg (Linux) | <https://johnvansickle.com/ffmpeg/> (static build) | Extract into `bin/`, rename the folder to `ffmpeg-linux` |
| yt-dlp (Windows) | <https://github.com/yt-dlp/yt-dlp/releases> → `yt-dlp.exe` | `bin\yt-dlp.exe` |
| yt-dlp (macOS/Linux) | same page → `yt-dlp_macos` or `yt-dlp` | `bin/yt-dlp` then `chmod +x bin/yt-dlp` |

The folder name for ffmpeg only needs to **start with** `ffmpeg` — the app searches for
`bin/ffmpeg*/bin/ffmpeg(.exe)`.

**You can verify at any time:** start the app (step 7) and look at the bottom-left of the sidebar —
it shows `ffmpeg` and `yt-dlp` with a tick or a cross. Two ticks means you are ready.

---

## 6. Get a free AI key

ClipBlitz uses an AI service to understand the video. **Groq** is free and fast, and it is the one
you need.

1. Go to <https://console.groq.com/keys>
2. Sign in (Google/GitHub login works).
3. Click **Create API Key**, give it any name, and copy the key. It starts with `gsk_`.
4. Keep it somewhere safe for a moment — you will paste it into the app itself, not into a file.

**Optional second key (Gemini).** If Groq ever hits its free daily limit, ClipBlitz can
automatically fail over to Google's Gemini. Get a free key at
<https://aistudio.google.com/apikey> (it looks like `AIzaSy...` or `AQ.Ab8...`). You can add it
later; everything works with just Groq.

> **You do not edit any file by hand.** The app has a key screen. That is step 7.

---

## 7. Start ClipBlitz

In the ClipBlitz folder, in your terminal:

```bash
python run.py
```

You will see a few lines, ending with something like:

```
ClipBlitz on http://localhost:4301
```

Leave that window open — that is the app running. Now open your browser and go to:

**<http://localhost:4301>**

### First run: paste your keys

The first screen is **Connect**. There is an **API keys** card:

1. Paste your Groq key into the **Groq — primary brain** box.
2. Click **Test & save**. It calls Groq live and tells you immediately if the key works.
3. Optional: paste the Gemini key and **Test & save** it too.

The little pill next to the card should now read **groq + gemini online** (or just `groq`).
Keys are saved to a `.env` file and reload instantly — **there is no restart step, ever**.

To stop the app later: click the terminal window and press **Ctrl + C**.

---

## 8. Make your first clip

1. Click **Studio** in the left sidebar.
2. Either paste a YouTube link into the box, or **drag an MP4 file onto the drop area**. If you
   have no video handy, click **Demo (generated test video)** — ClipBlitz generates one so you can
   try the whole pipeline immediately.
3. Optionally pick a **caption style** in the gallery (the 9:16 preview on the right shows what
   each looks like) and change framing.
4. Click **Edit my video**.

Now watch the **processing timeline**. It moves through: reading the video → extracting audio →
detecting laughter → finding peak moments → transcribing → finding stories → drafting cuts →
judging → rendering. A short video takes a couple of minutes; a long podcast can take longer,
because transcription is the slow part.

When it finishes, ClipBlitz **jumps to the Clips screen by itself**.

---

## 9. The five screens explained

### Studio
Where you start a job: YouTube link or dropped file, caption style, framing, and the recent-jobs
list. The right-hand panel is a live preview of the current caption style.

### Clips — the podium
Your finished clips, best first, each numbered (`#01 ALPHA`, `#02 BRAVO`, …). On every card:

- the **score dial** (0–100),
- a **QC badge** — `verified` means the judge read the finished clip and it stands on its own;
  `unverified` means it did not fully pass and is shown honestly instead of being hidden,
- the **hook line** (the quote that made it worth cutting),
- the **judge's verdict** — a plain-English sentence about that exact clip,
- **factor bars**: Hook, Story, Payoff, Energy, Pacing, Event, Laugh.

Below each clip: **Post** buttons (YouTube / TikTok / Instagram / Facebook / X) and an editor for
the title, description and hashtags. Edit, click Save, then post.

### Candidates — the runner-ups (the lab)
Every cut the engine considered but did not put on the podium, with its measured score. Use the
filters **All / Verified / Peak events** to narrow the list, and click **Render** on any row to
make that clip too — same engine, same honesty.

### Transcript
The full transcript with timestamps. Lines that belong to a real clip are highlighted. Click any
line to jump there. On the right is the **waveform timeline** with markers where the peak moments
are. Drag the two handles to select your own window and click **Cut this window** to render a clip
from exactly that range. **Export .SRT** downloads the subtitles for the whole video.

### Connect
Everything about keys and posting:

- the **API keys** card (Groq, Gemini, YouTube),
- the **YouTube auto-post** wizard with a live readiness checklist — it tells you which of the
  four setup steps is still missing, and **Diagnose** explains any Google error in plain words,
- assisted cards for TikTok / Instagram / Facebook / X,
- the **post queue**.

---

## 10. Optional: post to YouTube automatically

Skip this unless you want clips uploaded for you. Full step-by-step is in
**[SETUP-YOUTUBE.md](SETUP-YOUTUBE.md)**; the short version:

1. In Google Cloud, create a free project.
2. Enable **YouTube Data API v3**.
3. Create an **OAuth client ID** of type **Desktop app**. (The Connect screen's buttons deep-link
   you straight to each page.)
4. Paste the **client ID** and **client secret** into the Connect screen's **YouTube Data API**
   fields and click **Test & save** — no file editing, no restart.
5. Still in Google Cloud, add the app's **redirect URI** (the Connect screen shows the exact
   string and has a **copy** button) to your OAuth client's *Authorized redirect URIs*.
6. If Google says your app is in testing, open the OAuth consent screen → **Audience** → set it to
   **External** and add your own Google address as a **test user**.
7. Back in ClipBlitz, press **Connect YouTube** and finish Google's consent window once.

After that, the Connect screen's checklist turns green and clips can be posted from the Clips
screen. Free Google quota allows roughly six uploads a day.

---

## Troubleshooting

### “python is not recognized” / “command not found: python”
Python is either not installed or was not added to PATH.
- Windows: re-run the Python installer → *Modify* → tick **Add python.exe to PATH**.
- macOS/Linux: try `python3` instead of `python`.
- Still stuck? Reopen the terminal — PATH changes only apply to new terminals.

### The page will not open / “localhost refused to connect”
- Is the terminal with `python run.py` still open and showing no errors? If it closed, the app
  stopped.
- Wait ten seconds after starting — first boot is slower.
- Check the address is exactly `http://localhost:4301` (not `https`, not a different port).

### “port 4301 is already in use”
Something else (or an older ClipBlitz) is on that door. Find and close it, or use another port:

```bash
# Windows
netstat -ano | findstr :4301        # note the PID in the last column, then:
taskkill /F /PID <that-number>

# macOS / Linux
lsof -i :4301                       # note the PID, then:
kill <that-number>
```

Or change the door: create a file named `.env` in the ClipBlitz folder containing
`CB_PORT=4399`, save, and start again — then use `http://localhost:4399`.

### The sidebar shows a cross next to `ffmpeg` or `yt-dlp`
The tools are missing. Re-run the fetch script (step 5) and look at the verification lines it
prints. If a download is blocked by your network, use the manual table in step 5.

### “yt-dlp failed” or YouTube refuses the download
- Update yt-dlp — YouTube changes often and yt-dlp adapts. Re-run `scripts/fetch-tools.ps1`
  (Windows) or `bash scripts/fetch-tools.sh --force`.
- Try a different video; some are region-locked or age-restricted.
- A very long video can fail on a weak connection — download the MP4 yourself and drop it on the
  Studio drop area instead.

### Transcription fails or the job errors at “transcribing”
That step uses your Groq key.
- Open **Connect → API keys**, paste the key again and press **Test & save**; it will tell you if
  the key is dead.
- If Groq says you are rate-limited, wait, or add a free Gemini key as failover.
- If it says the model was retired, ClipBlitz self-heals by moving to the replacement — retry once.

### The clip I wanted is not on the podium
Look in **Candidates** — runner-ups live there with a **Render** button. The podium is deliberately
strict: only clips whose ending genuinely lands get promoted. You can also use **Transcript →
drag the handles → Cut this window** to cut exactly what you want.

### YouTube says `org_internal` or “access blocked”
Your OAuth consent screen is restricted to your organisation.
Fix: Google Cloud → **OAuth consent screen** → **Audience** → set **External**, then add your own
Google address as a **test user**. Press **Diagnose** in ClipBlitz's Connect screen for the same
advice in context.

### YouTube upload fails with “quota exceeded”
Google's free daily upload allowance is used up (about six uploads). Wait until it resets
(midnight Pacific time), or post the clip by hand — the file is on your disk and the caption
package is one click away on the Clips screen.

### Where are my clips and my data?
Everything lives in the `data/` folder inside ClipBlitz: finished clips in `data/clips/`, uploaded
originals in `data/uploads/`, job history in `data/jobs.json`. Deleting a job's clips there is
safe. Nothing is sent anywhere except the transcription/AI calls you configured.

---

## FAQ

**Do I need a paid account anywhere?**
No. Groq's free tier is enough to run the engine. Everything else (ffmpeg, yt-dlp, ClipBlitz) is
free and local.

**Do I need to edit `.env` by hand?**
No. Every key is managed in the app's Connect screen. `.env.example` exists only to document the
optional knobs (port, data folder, model overrides).

**Does it work offline?**
Partly. Without an AI key the engine falls back to measured audio heuristics (no story pass, no
judge), so clips still render but the "understands the story" quality comes from the AI.

**Can I process a video longer than an hour?**
Yes. Transcription is chunked automatically. Expect it to take a while — the app shows progress the
whole time.

**How many clips does it make?**
Top 3 by default, plus every runner-up in Candidates which you can render individually. Set
`CB_TOP_N` in `.env` to change the podium size.

**Can I use my own caption style?**
The gallery has the built-in styles (Word Pop, Bold Gold, Minimal White, Karaoke Gold, Neon Shake,
Classic Box). The Studio screen's preview shows each one.

**Is my video uploaded anywhere?**
Only the audio is sent to your chosen AI service for transcription. The video itself never leaves
your computer.

**It made a clip that starts mid-sentence — is that a bug?**
It should not happen: the engine snaps to sentence edges and refuses filler starts. If you see one,
note the job and clip number — that is exactly the kind of report that improves the engine.

---

## Word list

**Clip** — one short vertical video, usually 15–60 seconds.
**Job** — one run of the pipeline on one video. Has an id, shown in the URL as `?job=...`.
**Podium** — the top clips in the Clips screen.
**Candidate / runner-up** — a cut the engine considered but did not promote.
**QC / verified** — the judge read the finished clip's transcript and it stands on its own.
**Peak moment** — where the video's audio and camera energy spike (the goal, the punchline, the
reveal). Clips that contain one are preferred.
**Story** — a self-contained arc in the video (setup → development → payoff) that a clip is built
from.
**Blur-pad** — the framing mode that fits a wide video into 9:16 by blurring the background instead
of cropping people out.
**SRT** — the standard subtitle file format.
**Deep link** — a URL that opens a specific screen, e.g. `http://localhost:4301/?screen=connect`.

---

**Still stuck?** Open an issue on
[GitHub](https://github.com/agra-aarav15/clipblitz-ai-shorts/issues) describing what you ran and
what you saw. Include the last few lines from the terminal window — that usually contains the
answer.

Back to the [README](README.md).