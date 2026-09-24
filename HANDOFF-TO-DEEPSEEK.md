# HANDOFF — ClipBlitz (v3.4.5) → you (DeepSeek), then B2 Pro X

You are taking over a working, verified product from a previous AI engineer. Everything below is
true as of the handoff. Read it fully before touching anything. The owner (referred to as "the
owner") is a solo founder who works fast, wants proof instead of claims, and hates glitches.

---

## 1. WHAT CLIPBLITZ IS

ClipBlitz is a local web app that turns a long video (YouTube URL or dropped MP4) into vertical
9:16 shorts, automatically, with an AI editor pipeline:

probe → extract audio → audience-laughter detection → **peak-moment mining (MOMENT_PASS)** →
transcribe (Groq/Gemini Whisper) → **story segmentation** → **draft cuts inside stories** →
deterministic edge rules → **judge pass** (per-clip verdict + repair loop) → score v2 → render
with wordpop captions → metadata (title/description/hashtags) → optional auto-post to YouTube/
TikTok/Instagram/Facebook/X (assisted).

The owner's core demand since day one: **clips must not be random**. Every clip must start on a
real sentence (never mid-thought, never on filler), end on a payoff (punctuation or laughter),
belong to a complete story, be judge-verified, and the podium must tell the whole arc of the video.

**The F1 acceptance test** (the owner's real test video, an F1 "that night in Abu Dhabi" film): the
Max-vs-Lewis battle where Max wins MUST be clip #1. Older engines failed this; MOMENT_PASS fixed it.

---

## 2. CURRENT STATE — WHERE EVERYTHING LIVES (Windows)

| Thing | Path |
|---|---|
| App (working copy) | `E:\clipping\clipblitz` |
| Python package | `E:\clipping\clipblitz\clipblitz\` (server.py, pipeline.py, virality.py, brains.py, keys.py, config.py, ingest.py, …) |
| Frontend | `E:\clipping\clipblitz\web\` (index.html, app.js, styles.css) |
| Secrets | `E:\clipping\clipblitz\.env` (never commit, never zip) |
| Git clone used to push | `E:\repo-clipblitz` → https://github.com/agra-aarav15/clipblitz-ai-shorts |
| Launcher | `E:\clipping\serve.bat` → detached window, `python -u run.py`, port **4301** |
| Watchdog (optional) | `E:\clipping\watchdog.bat` (restarts ClipBlitz if it dies) |
| Runtime data | `E:\clipping\clipblitz\data\` (jobs.json, uploads, clips) |

Live endpoints: `http://localhost:4301` (UI) · `GET /api/health` (version, ffmpeg, ytdlp, brains)
· `POST /api/demo` (creates a generated test video job — takes 2–4 min, the standard e2e test)
· `GET /api/job/<id>[?light=1]` · `POST /api/keys` (save+live-test Groq/Gemini/YouTube keys)
· `GET /api/social/youtube/diagnose`.

Deep links: `?job=<id>&screen=studio|clips|lab|transcript|connect`.

Current version: **v3.4.5** (server.py `"version"`), releases v3.1.0 … v3.4.5 exist on GitHub with
zip assets. `gh` CLI is authenticated on this machine.

**Keys are already configured and live** (Groq primary + Gemini failover, tested green). The owner
manages keys from the UI (Connect screen → API keys card → per-key "Test & save" with live provider
tests, hot-reload, no restart; saving is idempotent — `.env` stays byte-identical).

---

## 3. ENGINE REQUIREMENTS (the owner's words, distilled)

1. **No random clips, no random starts.** Snap to sentence edges; never begin on filler
   (um/so/like/yeah → advance); end on sentence punctuation or a detected laugh; extend through
   the laugh so the payoff lands.
2. **Every clip is a complete story** (setup → development → payoff), drafted inside an LLM
   story segment with the full verbatim transcript in context.
3. **The peak event must win.** MOMENT_PASS measures audio roar + camera-cut density + drama heat
   and anchors stories/drafts/scoring to it. In the final pick, the event factor is proportional
   (`+ 8 × event`), not a threshold step.
4. **Every cut is judged** on its exact verbatim transcript (alone? starts/ends abrupt? coherence/
   hook/payoff 0–10 + verdict). Failures get a deterministic ending fix and one repair redraw,
   then honest demotion. Podium gate: only ending-verified cuts (or measured tail-laugh) fill the
   podium; everything else is labelled unverified in the Lab. "The owner would rather see 1 great
   clip than 3 random ones."
5. **Scores follow the content** — computed from the judge's ratings of the exact cut + measured
   audio factors, never from loose excerpts.
6. **Podium shape**: one cut per story (diversity), ≥12% of duration apart (spread), no
   near-duplicate titles (Jaccard > 0.6 rejected), strong opening lines get a small ordering
   tiebreak (hook-open: question / curiosity opener / leading number, read from the transcript).
7. **Edit polish**: 0.18s audio+video fades at both edges, blur-pad 9:16 framing, wordpop
   captions, +1s "landing pad" after the final word, reaction post-roll for weak tails.
8. **Dual-brain failover**: Groq primary, Gemini failover; failover uses the failover brain's own
   model name; retired models self-heal by parsing the successor from the 404 body.
9. Everything above is verified on real runs (jobs `e54d3c0e` F1, `5cfb4853` 54-min podcast, plus
   demo jobs). Any engine change must be re-verified with a fresh `POST /api/demo` e2e.

---

## 4. UI — THE FULL DESIGN BRIEF (this is the part the owner cares about most)

The owner has been through several UI iterations and is explicit. Read carefully:

### 4a. The look they love ("Google Stitch — Obsidian Keynote")
- Pure black canvas `#050505`; depth comes from light, not color.
- Monochrome liquid glass: panels at `background: rgba(255,255,255,.04)`, `backdrop-filter:
  blur(~24px)`, 24px radius, hairline `1px rgba(255,255,255,.1)` borders, specular top rim.
- A silver/white aurora light field behind the glass (soft radial gradients — see the glitch rules
  below for how it must be implemented).
- Typography: Inter (body/display) + JetBrains Mono / IBM Plex Mono (every measurement: timecodes,
  chips, scores). Huge white headlines (72px display scale), uppercase letterspaced micro-labels
  (11px, `tracking-widest`).
- Material Symbols-style monochrome icons or an equivalent inline SVG icon set.

### 4b. The owner's hard rules (from this chat, verbatim intent)
- **"I want the look of the UI to be exact"** to the Stitch design — but **"it must be workable"**.
  A previous Stitch-port shipped glitchy and the owner rejected it and asked for the proven classic
  shell back. The current shipped shell (v3.4.x) is the one they accept: left glass sidebar
  (Studio · Clips · Candidates · Transcript · Connect), top bar, one screen at a time.
- **No emojis. Zero. Anywhere.** All icons are inline SVG strokes (the shipped set: film, filmstrip,
  layers, document, link, bolt, scissors, play, cloud, plug, key, search, note, camera, repeat,
  broadcast, tape, scales, bulb, save, list-check, warning, x, check) plus a **premium SVG logo
  mark** (gradient bolt in a glass badge) + `ClipBlitz` wordmark in Space Grotesk.
- **"Most immersive UI"** — the owner wants cinematic depth and tasteful motion (aurora drift,
  cursor halo, staggered card reveals, hover sheen). It must FEEL premium and alive.
- **Workable over decorative**: every button must do something real. No fake telemetry — a previous
  version showed fake AUTOSYNC/LATENCY/CUDA/NODE_0x7F/"Frame 17,910"/48 kHz/quota-74% readouts and
  the owner rejected them. Show real data or show nothing.
- **Keys only in the UI** — the owner does not want to edit `.env` by hand: Connect screen carries
  the API-keys card (Groq / Gemini / YouTube OAuth inputs, per-key Test & save, masked status
  pills, live "groq + gemini online" chip).
- Screens: **Studio** (URL input / dropzone, Make clips, options, caption-style gallery, recent
  jobs, live 9:16 caption preview), **Clips** (the podium: rank badges #01 ALPHA…, circular score
  dials, verified/unverified QC badges, hook quote, judge verdict box, factor bars Hook/Story/
  Payoff/Energy/Pacing, Post buttons, metadata editor), **Candidates** (runner-up cuts with
  filters All/Verified/Peak events, time chips, mini dials, Render buttons), **Transcript**
  (timestamped blocks with peak highlights, waveform timeline with ruler + playhead + markers,
  custom cut window, Export .SRT), **Connect** (API keys card + YouTube auto-post wizard with live
  readiness checklist + Diagnose + copy-redirect, assisted platform cards).

### 4c. THE GLITCH RULES — these are the law. A UI that violates them WILL be rejected.
Two documented glitch classes nearly cost the owner the product:
1. **Stuck-dim**: any element animated with `opacity: 0` as its start (with `fill: both`) can freeze
   invisible when the browser pauses its animation clock (backgrounded tab, busy system). **Ban.**
   All entrance animations must be **transform- or scale-only**. Every animated element's resting
   state must be the fully-visible state.
2. **Flicker**: infinite opacity animations on chrome (e.g. a status chip pulsing to 0.68 opacity
   forever) read as a glitch. **Ban.** Chips stay steady; a `box-shadow` glow pulse on a "live"
   indicator is acceptable, opacity pulses are not.
Also banned because they caused real defects: animation libraries loaded from a CDN (ship JS
locally or not at all), cursor-shifting "magnetic" buttons (elements must not move under the
cursor), CSS entrance keyframes that touch opacity, and any `@keyframes` with same name defined
twice (one silently overrides the other — that exact bug shipped a flickering chip).

### 4d. Mandatory verification for ANY UI change (the owner demands proof)
- **Rapid-switch stress test**: click all 5 nav buttons 3–4 rounds (20–30 ms apart), then assert
  zero visible elements below 0.99 opacity and zero leftover transforms.
- **Frozen-clock probe**: after the stress test, query computed opacity of every visible element
  under the active screen — nothing may be stuck.
- **Headless capture**: `msedge --headless --disable-gpu --user-data-dir=<fresh> --window-size=
  1440,900 --virtual-time-budget=15000 --screenshot=out.png URL` (fresh profile each run, one at a
  time), then check the mean luminance of the PNG (healthy ≈ 26–30; the historic dim bug ≈ 13).
  Also look at the PNG yourself.
- **Console**: zero JS errors; **sweep** for dangling ids/listeners/`data-goto`/icon `<use>` refs
  before shipping.
- Never claim a UI fix without these.

---

## 5. JOB ONE — REMAKE THE UI AGAIN, to this brief

The owner's words: *"remake the UI again with all the criteria I have given you in this chat"* and
*"make the best UI"* — meaning: the **Stitch Obsidian Keynote premium look** (§4a), the
**workable-classic structure** (§4b), the **immersive motion** (§4b) and the **glitch rules**
(§4c), verified by §4d. Keep the backend byte-identical while doing UI work — the UI must be
rebuildable from `web/` alone, and any engine file that must change needs an explicit reason and
re-verification.

Practical notes: the current `web/index.html` is one file with an SVG icon sprite + logo mark; the
screens are `<section class="screen" id="screen-…" hidden>`; the styles live in `web/styles.css`
(single file, no Tailwind build in the shipped shell — a Tailwind route existed before and caused
a build-config bug; if you reintroduce a build step, prove the theme compiles: headline must compute
72px, not 16px). GSAP is NOT loaded — do not bring it back (it was removed as a glitch source).

---

## 6. JOB TWO — FINALIZE THE GITHUB BEGINNER GUIDE and COMPLETE THE PROJECT

The owner wants a **GitHub beginner guide** finished: a genuinely step-by-step document for an
absolute beginner to install and run ClipBlitz (and to understand the repo).

Create / finalize:
- `README.md` — what it is, screenshots, the 60-second quickstart (Windows + macOS/Linux), the
  feature tour, the engine explanation in plain language, links to the other docs.
- `GUIDE.md` (or `BEGINNER-GUIDE.md`) — **assume the reader has never used GitHub or a terminal**:
  install Python + ffmpeg (per-OS, with exact commands and what "PATH" means), make a free Groq
  key, a free Gemini key (optional failover), optionally YouTube OAuth (Google Cloud project → enable
  YouTube Data API → OAuth client type Desktop → paste ID/secret **in the app's Connect screen** →
  add the exact redirect URI → Connect), how to run (`run.py`, or the provided launchers), how to
  use each screen, troubleshooting (port busy, ffmpeg missing, yt-dlp missing, consent screen
  `org_internal` → set Audience to External + add yourself as test user, quota), FAQ, glossary.
- `SETUP-YOUTUBE.md` already exists — cross-link it, don't duplicate.
- Keep the release flow: commit → tag → `gh release create` with a zip asset built WITHOUT `.env`
  and without `data/` (there is a proven recipe: exclude these, verify the archive contains no
  `.env`, attach with `gh release upload`).
- "Complete the project" means: docs finalized, UI remade and verified, B2 Pro X started and
  documented, repo clean, releases tagged, and a short `FIXED.md`-style changelog entry per version
  (the repo already contains `FIXED.md` with the full history — append to it, in the same voice).

---

## 7. JOB THREE — THE NEW VERSION: **B2 Pro X** (separate folder, new place, new engine)

The owner wants a **completely new version, in a new folder, in a new place**, with a new
**"B2 Pro X" engine** that "cuts clips like cinematic and edits it like I had told you in the chat".

Build it as its own project (new repo is fine; a new folder OUTSIDE `E:\clipping\clipblitz` is
required — do not fork the code in place). Reuse ClipBlitz's proven pipeline as the *foundation*
(copy, then evolve — the story/judge/edge-rule/MOMENT_PASS logic is battle-tested), but the engine
must be a genuine step up. "Cinematic" per everything the owner has demanded in this chat means:

- **Cut on cinema boundaries, not just sentences**: snap to shot/scene boundaries (ffmpeg scene
  detection) and camera-cut density; prefer cutting on motion peaks and beat changes.
- **Story-first assembly**: keep the story→draft→judge spine, but let the B2 pass re-time cuts to
  the scene grammar (open on a wide/establishing beat if the story has one, land the payoff on the
  peak shot).
- **Cinematic finish**: cinematic grade/contrast curve, subtle vignette, film grain option,
  letterbox-to-9:16 adaptive framing with subject-aware tracking (or at minimum motion-aware
  blur-pad), J/L-cut style audio leads (audio starts before the picture on the incoming cut),
  sound polish (ducking, soft whoosh on cuts), caption animation timed to speech onsets, a hook
  text overlay in the first 1.5 s, an optional end card, and multi-ratio export (9:16 + 1:1 + 16:9).
- **The same honesty rules**: judge-verified QC, ending gate, no random starts, scores follow
  content, real telemetry only in the UI.
- Give it its own launcher on a free port (do not collide with 4301), its own README, and its own
  verification script. Name the engine "B2 Pro X" in the UI and in `/api/health`.

Deliver it with the same proof discipline: a demo e2e run, screenshots, and a release.

---

## 8. WORKING STYLE WITH THIS OWNER (important)

- They are direct and get frustrated by regressions. **Never claim "fixed" without running the
  verification** in §4d and pasting the evidence (numbers, probe output).
- Fix the root cause, not the symptom. Every "glitch" in this project's history traced back to a
  concrete mechanism (CSS keyframes fighting, opacity-0 start states, duplicate keyframe names,
  CDN latency). Find the mechanism, then fix it, then prove it.
- Autonomous execution is expected: when the task is clear, do the work; don't ask permission for
  reversible steps. Ask only for genuinely destructive or scope-changing decisions.
- When you finish a version: commit, push, tag, `gh release create` with a zip asset (no `.env`,
  no `data/`), and write the changelog in `FIXED.md`'s established voice (concrete, honest,
  "what was broken → what it does now").
- Secrets: never print, commit, or zip `.env`. Keys are managed from the app UI.
- Do not use the computer-use tool (it errors on this machine). Browser automation via the
  provided in-app browser is fine.

---

## 9. CHEAT SHEET

```bat
:: start the app (detached, port 4301)
E:\clipping\serve.bat

:: health
curl http://localhost:4301/api/health

:: end-to-end test (2–4 min): starts a generated demo video job
curl -X POST http://localhost:4301/api/demo

:: save + live-test a key (what the UI does)
curl -X POST http://localhost:4301/api/keys -H "Content-Type: application/json" -d "{\"groq\":\"gsk_…\"}"

:: screenshot recipe (fresh profile each run, one at a time)
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless --disable-gpu ^
  --user-data-dir=%TEMP%\edge_shot1 --window-size=1440,900 --virtual-time-budget=15000 ^
  --screenshot=out.png "http://localhost:4301/?v=1"
```

Repo: `https://github.com/agra-aarav15/clipblitz-ai-shorts` (push from `E:\repo-clipblitz`).
Working copies are synced by copying `web/` and `clipblitz/` into the clone; verify parity with
`cmp` on the key files before committing.

---

## 10. YOUR FIRST THREE ACTIONS

1. Start the app, hit `/api/health`, open the UI, click through all 5 screens, run the §4d
   verification yourself so you know the baseline is real.
2. Read `FIXED.md` in the repo — the entire engineering history is there, in the owner's voice.
3. Then: (a) remake the UI to §4, (b) finalize the beginner guide to §6, (c) build B2 Pro X to §7 —
   each with proof, each committed, each released.

Welcome. The owner expects excellence and evidence, in that order.
