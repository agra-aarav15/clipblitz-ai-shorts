<p align="center">
  <img src="assets/logo.png" width="112" alt="ClipBlitz Studio" />
</p>

# ClipBlitz Studio

**Two AI clipping engines in one window.** Drop one long video; choose **ProX v5**, **B2 Pro X**,
or **Both** — and get vertical shorts with real edits, honest scores and animated captions.
Runs on any fresh PC and on your phone over Wi-Fi. Pure Python standard library, self-hosted
fonts, no build step, no CDN, no tracking.

- **ProX v5** — the story-first engine: segments the episode into stories, drafts the tightest
  cut inside each, lands every ending on the payoff, then a strict QC judge reads the exact
  final clip and scores it. Verified cuts are badged; anything else says "unverified".
- **B2 Pro X** — the cinematic engine on the same spine: cuts land on real shot boundaries,
  payoffs land on the shot that carries them, a film grade (S-curve, vignette) is applied, and
  the sound leads the cut (J-cut) so the incoming clip pulls you in.
- **Both** — one analysis pass, two cuts per moment, side by side. Same story, same judge
  verdict and score; the cut timing and the grade differ. Compare and pick.

![Studio with the engine selector](docs/shots/01-studio.png)

## Run it

Windows: double-click **`START.bat`** (installs Python silently if the machine has none).
macOS / Linux / Termux: `bash start.sh`. Full guide: **[SETUP.md](SETUP.md)**.

```
ClipBlitz Studio v4.0.0 (engines: ProX v5 / B2 Pro X / Both) → http://localhost:4300
  your phone (same Wi-Fi)  http://192.168.31.103:4300
```

The startup lines above are the whole install: ffmpeg and yt-dlp ship in `bin\`, the UI and
fonts are served locally, and your API keys live only in this machine's `.env`.

![Comparison mode — both engines, side by side](docs/shots/03-compare.png)

## What is honest here

- Every score comes from the QC judge reading the exact final cut plus measured audio
  (laughter, energy, pacing). Factor breakdowns are on every card.
- The hardware readout is measured, not invented: cores, memory and an ffmpeg check run on the
  host. A device that cannot render says so **before** any job starts — "This device can't
  render clips. Use your laptop or PC to render them." — instead of crashing mid-render.
- A phone used as the controller renders nothing; the studio host does. That is why the phone
  experience has no hardware tension. Running the engine *on* an Android phone is supported
  via Termux (`bash start.sh`) and the same hardware check applies there.

## Rights, on purpose

Before the first automatic upload from a job, the Clips screen asks the one question that
actually matters: is this your own content, licensed, or a transformative fair-use edit? Your
answer is stored on the job and the post waits for it. The clip file is never withheld, so
posting by hand stays the owner's call. A job started from a YouTube link also shows the
uploader channel and video id on every clip card and flags it when that is not the channel you
connected.

There is deliberately no evasion here: no pitch shift, speed change, mirror or fingerprint
trick. Content ID finds unlicensed re-uploads anyway, and hiding from it is what gets channels
terminated. See the **Copyright and strikes** section in [SETUP.md](SETUP.md).

## What I've learned (local, honest)

Every clip you post, re-render from the Candidate Lab or hand-cut on the Transcript screen is
one logged choice. From **10 choices** on, the ranking weights drift toward what you actually
keep — laugh endings, question hooks, your clip-length band — by at most **10% per factor**.
Below that threshold nothing moves, so a fresh install ranks exactly like the shipped engine.
The Connect screen shows the real counts, shares and median behind it, with a Reset button.
The store is a local `data/learning.json`; nothing is uploaded and there is no cloud training.

![Connect screen with the phone and machine cards](docs/shots/04-connect.png)

## The two engines, technically

One codebase, branched per job — B2 Pro X is a strict superset of ProX v5:

| | ProX v5 | B2 Pro X |
|---|---|---|
| Cut boundaries | story + edge rules (sentence starts, laugh endings) | the same, snapped to measured shot boundaries and re-timed to scene grammar |
| Look | clean 1080x1920 blur-pad | S-curve grade, vignette, optional grain |
| Sound | fade in/out | J-cut: audio leads the picture by 0.35s |
| Extra passes | — | scene map + motion map (cached per video) |

`both` runs the analysis once and renders each moment twice — the ProX cut from the
pre-cinema bounds, the B2 cut from the cinema-snapped bounds.

## Layout

```
run.py            one entry point, port 4300 (CLI arg > CB_PORT > default)
START.bat         one-click Windows launcher (auto-installs Python if missing)
start.sh          macOS / Linux / Termux launcher
clipblitz/        the engine package (pipeline, virality, cinema, ffmpeg_tools, server, ...)
web/              the single-file UI (vanilla HTML/CSS/JS, self-hosted fonts, PWA manifest)
bin/              bundled ffmpeg + yt-dlp — nothing is ever downloaded at runtime
data/             jobs.json + clips + uploads (created on first run; never commit it)
SETUP.md          fresh PC, phone, Termux, YouTube OAuth
```

Ports on this machine: Studio **4300**, classic ClipBlitz 4301, B2 Pro X 4302 (they can run
side by side; each is self-contained).

## Verify it yourself

Health, capability and LAN endpoints (the server is stdlib `ThreadingHTTPServer`):

```
curl http://localhost:4300/api/health      # engines, measured hardware, brains
curl http://localhost:4300/api/lan         # the phone address
```

Or press **Demo video** in the Studio — a generated test video runs the full pipeline
(transcribe, mine, judge, render) with whichever engine you selected.

The engine split and the learning loop have their own offline test scripts (stdlib only, no
network, no ffmpeg):

```
python scripts/test_engines.py    # prox-only == legacy ProX v5, b2-only untouched, both honest
python scripts/test_learning.py   # weights inert below 10 choices, +/-10% cap, rights gate holds
```

## License

MIT.
