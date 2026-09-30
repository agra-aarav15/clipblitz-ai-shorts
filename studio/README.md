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
ClipBlitz Studio v4.1.0 (engines: ProX v5 / B2 Pro X / Both) → http://localhost:4300
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

## Copyright safety, measured

`GET /api/job/<id>/risk` returns what can honestly be measured about a job before it goes
anywhere: sustained non-speech audio outside your transcript (the shape of a music bed, theme
or intro sting, with its timestamps), a source downloaded from somewhere you may not own (with
the uploader yt-dlp reported), a missing or expired licence, an unanswered rights gate, and any
clip that carries fewer transformative layers than the rest of the set. Every flag is a
measurement taken from data the pipeline already produced, and none of it is a legal verdict.

`POST /api/job/<id>/licence` stores the licence record next to your rights answer — who granted
it, a reference, an expiry date — because a claim is argued with paperwork, not memory.

`GET /api/job/<id>/receipt` writes the edit receipt: the exact window of every cut, the engine
that rendered it, the transformative work that render actually applied (burned-in captions, the
reframe, the grade, the J-cut), and sha256 hashes of the source and each output file.

What none of it does is make somebody else's video uncopyrighted. A content-matching system
matches the work itself, so no crop, caption or re-encode removes the match, and this studio
will not ship a button that pretends otherwise.

![The Clips screen with the copyright-safety panel: level, measured flags, licence record and edit receipt](docs/shots/02-clips.png)

## What I've learned (local, honest)

Every clip you post, re-render from the Candidate Lab or hand-cut on the Transcript screen is
one logged choice. Three layers learn from those choices, each with its own evidence bar:

| Layer | Needs | Moves |
|---|---|---|
| Global taste | 10 choices | payoff/hook/pacing/story, up to 10% per factor |
| Per engine | 15 choices **on that engine** | that engine only, up to 5% more, so B2 and ProX can drift apart into what each does best for you |
| Factor over-index | 8 choices that carried a candidate pool | the measured factor your kept cuts beat their own pool on, up to 6% |

Older choices count for less (half as much after 45 days), so the engine follows your taste
instead of being haunted by your first week. Below a threshold nothing moves, so a fresh install
ranks exactly like the shipped engine, and a `both`-engines run always scores on the shared
profile because one analysis pass has exactly one ranking. The Connect screen shows the real
counts, shares, medians and the plain-language *why* behind every multiplier in effect, with a
Reset button. The store is a local `data/learning.json`; nothing is uploaded and there is no
cloud training.

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
clipblitz/        the engine package (pipeline, virality, cinema, rights, agent, server, ...)
web/              the single-file UI (vanilla HTML/CSS/JS, self-hosted fonts, PWA manifest)
plugin/           the agent plugin: MCP server, /cut command, skill (see plugin/README.md)
bin/              bundled ffmpeg + yt-dlp — nothing is ever downloaded at runtime
data/             jobs.json + clips + uploads (created on first run; never commit it)
SETUP.md          fresh PC, phone, Termux, YouTube OAuth
```

Ports on this machine: Studio **4300**, classic ClipBlitz 4301, B2 Pro X 4302 (they can run
side by side; each is self-contained).

## The other two screens

![Candidate lab — every runner-up, measured and judged](docs/shots/07-lab.png)

![Transcript timeline — waveform, markers, and the window you cut](docs/shots/08-transcript.png)

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
python scripts/test_agent.py      # MCP framing, tool honesty, risk/licence/receipt, both engines learn apart
```

## Use it from an agent

`plugin/` is a plugin for a coding agent: hand it a video and a number and it cuts the clips.

```
python -m clipblitz.agent cut episode.mp4 --clips 4 --json    # one shot, prints JSON
python -m clipblitz.agent risk <job_id>                       # what to check before publishing
python -m clipblitz.agent receipt <job_id>                    # write and show the edit receipt
python -m clipblitz.agent mcp                                 # the MCP server itself, on stdio
```

The MCP server exposes `cut_clips`, `job_status`, `job_clips`, `risk_report`, `edit_receipt` and
`learning_state`. If a Studio is listening on 127.0.0.1 it creates the job through its own HTTP
API (one writer for `data/jobs.json`); if not, the identical pipeline runs in-process. There is
no publish tool, on purpose: editing is the plugin's job and publishing stays a human decision.

The ready-to-run Windows release carries `plugin/` next to the EXE, and the EXE is the same
entry point, so no Python is needed for the agent path either:

```
ClipBlitzStudio.exe --mcp      # the MCP server on stdio, exactly like the python one
ClipBlitzStudio.exe --tools    # the tool schemas as JSON
```

## License

MIT.
