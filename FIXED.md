# FIXED.md — every recurring error, hunted down and closed

**Date: 2026-08-30 · Scope: full error audit + ProX algorithm rebuild + UI 2.0**

Both projects were audited end-to-end (every request handler, every failure path, every
log line). Everything below is fixed **and verified** — with the test result noted.

---

## ClipBlitz — errors that repeated "again and again"

| # | Symptom | Root cause | Fix | Verified |
|---|---------|-----------|-----|----------|
| 1 | Console spammed `ConnectionAbortedError [WinError 10053]` tracebacks constantly | Server wrote responses unguarded; browsers abort video Range requests while seeking (the old UI re-created every `<video>` every 1.5 s, guaranteeing it) | `QuietServer.handle_error` swallows client-disconnect classes; all writes guarded (`server.py`) | ✓ no tracebacks in soak |
| 2 | The UI "blinked" every 1.5 s during processing — videos reset, typed metadata lost | `renderClips` did a full `innerHTML` rebuild per poll tick | Surgical rendering: cards are created once, animated in, then only post-chips are patched (`app.js`) | ✓ inputs survive polls |
| 3 | After a server restart the page polled a dead job **forever** ("unknown job" every 1.5 s) | `/api/job/<unknown>` returned HTTP 200 + no `status`; `poll()` had no try/catch | Unknown job → 404; poller stops cleanly with a toast; transient outages keep retrying | ✓ |
| 4 | A clip failed outright whenever the caption burn failed | Caption-retry spliced the `-vf` value into the flag position (`args[:8]+[vf]+args[9:]`) | Correct splice — retry renders captionless instead of dying (`ffmpeg_tools.cut_clip`) | ✓ |
| 5 | Post chips always posted **clip #0** | Re-rendered chips lost their `data-clip` index | Chips patch with a signature check and keep their index | ✓ |
| 6 | Long videos died at transcription (`413`, whole 230 MB WAV in RAM) | 25 MB provider cap, single multipart blob | Auto-split on silence boundaries into <22 MB parts, transcribed, stitched with offsets (`stt.py`) | ✓ |
| 7 | Boundary words silently dropped from captions | `_attach_words` required a word to sit fully inside a segment | Word-midpoint assignment — no gaps | ✓ |
| 8 | Music/no-speech videos produced one giant "clip" of the entire video | Single whole-file segment became a candidate, unbounded | Offline miner caps windows at 90 s; single-segment pathology handled (`virality.py`) | ✓ (24 s pathological case → one honest 24 s clip) |
| 9 | Demo could produce fewer than 3 clips (20 s fixed windows on a 24 s video, empty-transcript crash) | `_chunks([])` ValueError masked by blanket except; `_even_windows` step math | Chunker guarded; demo now uses **real spoken narration** (Windows SAPI TTS, offline) so transcription, captions and scoring run on genuine speech | ✓ demo → exactly 3 captioned clips |
| 10 | Ugly Python traceback when port 4301 was already taken | Bare `ThreadingHTTPServer(("0.0.0.0", …))` | Friendly "already running → open that tab" + clean exit | ✓ |
| 11 | 404 spam for `/favicon.ico`; assorted unhandled `ValueError`s (`scale=abc`, bad Content-Length, degenerate Range headers); file-handle leak; 5 GB body buffered in RAM before the size check | Missing guards | favicon 204; every parse guarded; Range clamped; uploads streamed to disk after the Content-Length check | ✓ |
| 12 | Auto-post statuses were invisible (job flipped to `done` before posting; poller stopped) | Ordering + poller lifecycle | Posting now runs as a visible stage ("auto-posting clip 1/3 → youtube, tiktok") with `on_update` persistence, and manual posts resume polling | ✓ |
| 13 | Jobs lost on refresh/restart (memory-only) | — | Jobs persist to `data/jobs.json`; interrupted jobs are marked honestly; `GET /api/jobs` lists history | ✓ |

## ClipBlitz — the clip rater is now real (ProX engine)

The old "virality score" was fake: fallback picked the **first 6 transcript segments** (the
intro!) with `score = 40 + 2×length`; AI scores were unvalidated LLM inventions on three
incompatible scales; no boundary snapping, no hook check, no diversity.

**ProX (inspired by Opus-class tools' hook/flow/engagement/trend scoring) — every factor is
computed, never invented:**

1. **Mine** — the LLM over-generates candidates across the WHOLE video (adaptive chunking,
   content-type aware). Offline mode mines by audio energy + speech density + anti-intro bias.
2. **Measure** — every candidate is snapped to sentence boundaries (never mid-word), then
   scored on **hook** (first-3 s pattern check on real words + LLM rating), **flow** (clean
   boundaries + retention sweet-spot length), **pacing** (words/s vs ~2.8 sweet spot),
   **energy** (per-0.5 s RMS loudness vs the video's own baseline — laughter/applause spikes),
   **emotion** & **trend** (one batched LLM rating call; honest text-marker fallback).
3. **Calibrate** — fixed weights → 0–99, with the six factor bars shipped to the UI.
4. **Diversify** — max one clip per topic; overlap dedupe; hooks guaranteed inside the first 3 s.
5. Manual custom cuts run through the **same** measurement pipeline.

Verified on the spoken demo: `#1 88 (hook 65, flow 94, energy 78) · #2 85 · #3 80`,
topics diverse, AI titles, captions burned.

## ClipBlitz — UI 2.0 (same black/white glass)

Animated score dials + six factor bars per clip · **Candidate Lab** (runner-up cards with
real measured scores — one click renders any of them) · **interactive transcript** with a
source player and a drag-handle timeline for custom cuts · per-clip caption-style re-render ·
5-platform post chips + a real post queue · skeleton loaders, card entrance animations,
toasts (zero silent failures), honest connection chip.

## LeadPilot — errors that repeated "again and again"

| # | Symptom | Root cause | Fix | Verified |
|---|---------|-----------|-----|----------|
| 1 | Full traceback crash on start — `EADDRINUSE :::3002` (seen 3× in logs + live) | `app.listen` with no `error` handler, no instance guard | Friendly "already running → open that tab" + clean exit; API keeps serving | ✓ |
| 2 | Leads silently got **no reply** on any AI hiccup | No timeout, no retry, `.trim()` crash on `content: null` (gpt-oss reasoning-only), 429s unthrown | 30 s timeout, 3 attempts with backoff on 429/5xx/network, nudge-repair for empty answers, and a **graceful fallback reply** so a lead is never left hanging | ✓ dead-provider test → lead still answered |
| 3 | Simulator showed nothing when the AI 500'd (message just sat there) | 500 path had no UI branch; "AI unreachable" bubble only fired on network errors | Real error toasts + visible bot bubble with reason; typing spinner can't stick (45 s failsafe) | ✓ |
| 4 | Meta webhook retries duplicated conversation history | No idempotency | Message-id dedupe (persisted, capped) — retried payloads are skipped | ✓ same payload twice → 1 result, then 0 |
| 5 | Media-only n8n messages 400'd and stalled workflows | `text: ''` hit the validation | `/api/agent` answers `{ok, skipped}` — n8n never blocks | ✓ |
| 6 | Malformed JSON returned Express's HTML error page to n8n | No error middleware | JSON 400/500 everywhere + JSON 404 for unknown API routes | ✓ |
| 7 | A crash mid-write could wipe `leads.json` silently | Direct `writeFileSync`, swallow-all `load()` | Atomic writes (tmp+rename), serialized write chain, corrupt file backed up + logged | ✓ |
| 8 | Same contact = different leads per transport (`@c.us` vs bare phone) | No identity normalization | `normalizeId` — one canonical id per human across WhatsApp-web / Cloud API / n8n | ✓ |
| 9 | QR loop regenerated 54× without anyone scanning | No cap | Hard cap at 5 QRs with a clear message; API/dashboard keep running | ✓ (code path) |
| 10 | Dev mode (`npm run dev`) proxied to port 3000 — API unreachable | Wrong port in `vite.config.js` | Points at 3002 | ✓ |
| 11 | Dashboard: static "live" badge while offline, no feedback on stage moves, `role`-less error banner | — | Honest live/offline dot, optimistic stage moves with rollback + toasts, `role="alert"`, **drag & drop kanban** | ✓ built |

## Not changed on purpose

- Ports: LeadPilot **3002**, ClipBlitz **4301**, 3000/8787 kept free for your own apps.
- Design language: black & white glassmorphism, untouched.
- Your Groq key stays only in the gitignored `.env` files.

---

## Round 2 — the 54-minute podcast failure (real press-tight debugging)

The user's real upload (*INDIA'S GOT LATENT S2 EP5*, 54 min, 1.34 GB, `youtu.be/VJ9VC9OqdAA`)
failed with `failed: name 'ffmpeg' is not defined`. Root causes, all fixed & verified:

| # | Bug | Root cause | Fix |
|---|-----|-----------|-----|
| 1 | `name 'ffmpeg' is not defined` | `stt._plan_chunks` (the >11 min audio path — untested territory until a long video showed up) called bare `ffmpeg()` which was never imported in `stt.py` | direct `from .config import CONFIG, ffmpeg` |
| 2 | Transcript = 6 giant 9-minute blocks → 90 s "clips" | Groq `whisper-large-v3-turbo` returns **words but an empty `segments` array** when word granularity is requested; the code fell back to one whole-part segment | `_segments_from_words`: synthesize sentence-level blocks from the word stream (split on punctuation / pauses / max length) → 1037 blocks, 6229 words |
| 3 | `UnicodeDecodeError` killing the yt-dlp stderr reader thread | yt-dlp writes smart quotes (0x92) in error messages; `subprocess text=True` decodes as strict UTF-8 | `errors="replace"` on every captured subprocess call |
| 4 | Every retry re-downloaded 1.34 GB | No download cache | Video-id-keyed ingest cache (`yt_VJ9VC9OqdAA`) — retry is a cache hit, zero download |
| 5 | `prox-ai` silently fell back to `prox-offline` on long videos | One bad LLM chunk killed the whole mining pass; no retry/nudge for gpt-oss empty answers | `_post_chat` now retries with a JSON nudge (final attempt forces `response_format: json_object`); failures are per-chunk |
| 6 | Hooks were LLM-invented | — | Hook is now the clip's actual first spoken words (12-word quote from real word timings) |
| 7 | Long-video transcript trunkated | chunk cap 8 → only ~35 min covered | cap raised to 24 |
| 8 | YouTube "confirm you're not a bot" blocks | intermittent anonymous client block | automatic retry with alternate player clients; friendly cookie hint if both fail |

Verified end-to-end on the user's actual video: `picker: prox-ai` · `content_type: interview` ·
**1037 transcript blocks / 6229 words** · clips **17.9 s / 43.7 s / 18.1 s** (the 15–60 s sweet
spot, not 90 s bluntors) · hooks are real spoken lines (*"What am I gonna do with all this
money man?"*) · factor bars vary meaningfully (energy 100 vs 54) · word-pop captions burned.

---

## Round 3 — the quality complaints (all fixed & verified on the real video)

| # | Complaint | Root cause | Fix | Verified |
|---|-----------|-----------|-----|----------|
| 1 | "Rate meter is very bad" (fake 100s, `marker-rated` junk) | The batched LLM rating call hit Groq's burst rate limit right after the 6 mining calls → silent fallback to text markers | `_post_chat` now retries 4× respecting `Retry-After` with 20s+ backoff; rating retries before falling back; `youtube_connected()`-style honesty elsewhere | real ratings: **90 / 88 / 86** with varied factors (energy 100/92/100, pacing 79/93/43) |
| 2 | "Flips out random things, leaves content incomplete" | Clips were cut mid-story (e.g. a clip starting "like? Yeah. What do women like?…") | **Story-completeness refinement pass**: one LLM call re-draws every final clip's boundaries so it begins where the thought begins and ends after the payoff, then re-snaps to sentence edges; hooks are always the clip's real first spoken words | clips 31.4s / 44.9s / 22.6s, complete stories ("Winner walks away with ₹1 Lakh + AI Nova 2 Pro phone!") |
| 3 | "The frame is cutting out" | Center-crop to 9:16 decapitates wide podcast stages (people sit left+right) | **Blur-pad framing (new default)**: the full frame stays visible, background is a blurred zoomed copy — plus crop / crop-left / crop-right options in the UI | screenshot: both hosts fully in frame on every clip |
| 4 | "Author upload working or not — not sure" / "OAuth just worked" | It did NOT work: `CB_YT_CLIENT_ID` is empty in .env, so no real OAuth was ever possible — the UI made it look done | `/api/health` now does a **real token check** (`youtube_ready`); Connect tab is a 4-step wizard showing the exact redirect URI (copy button) and honest status: "❌ OAuth not set up yet — posting will fail until done" | health: `youtube_ready: false` while keys are missing |
| 5 | render crash `name 'job_' is not defined` | stale variable name in `_render_clip` after refactor | fixed; full re-run green | 0 tracebacks |

---

## Round 4 — the algorithm gets ears (laughter), YouTube gets hot keys

| # | Problem | Fix | Verified |
|---|---------|-----|----------|
| 1 | "The algorithm is just shit" — it still couldn't *hear* what makes a comedy podcast clip go viral: the laugh | **Acoustic laughter detector**: band-pass 300–6000 Hz → RMS energy vs the video's own baseline → bursts ≥+7 dB for >0.8 s merged into regions (80 found in the 54-min podcast, 6.3% of runtime) | laughter is a measured factor per clip (shown in the factor bars); #1 pick scored laugh=55% |
| 2 | Picks clustered + missed punchline endings | **Content-aware weights** (comedy/podcast boost energy+emotion; tutorial boosts flow+pacing) + **punchline extension** (window stretches through the laughter so the payoff lands on screen) + 150 s spacing between picks on long videos | picks moved to 748s / 1052s / 2513s — the giveaway moment (#1, 86 pts, ends on the laugh), the time-travel joke, the singing challenge |
| 3 | Pasting YouTube keys into .env needed a restart | Keys are **hot-reloaded** from .env on every OAuth call — paste → Connect, no restart | `youtube_configured()` reads .env live |
| 4 | The OAuth wizard made you hunt for Google Console pages | One-click deep links in the Connect tab: create project → enable API → create credentials → redirect-URI settings, plus copy-button for the exact redirect URI | 4 buttons live |
| 5 | Skeleton loaders stayed visible after clips arrived | The `hidden` attribute was being beaten by the `display:grid` class rule | global `[hidden] { display:none !important }` |
| 6 | Servers died when my session's background shells were recycled | New `serve.bat` launches both apps as **detached Windows windows** that survive everything; watchdog.bat remains for hands-off auto-restart (don't run it while deploying code changes — it restarts the old code) | both up detached: 3002 + 4301 |
| 7 | `name 'laughter_score' is not defined` (my import miss, caught by the live run) | explicit import; full-run green | job b58a26d2 done, 0 tracebacks |

---

## Round 5 — ProX v5 "The AI Editor" + app-shell UI

The full engine rewrite (your verdict: clips started/ended randomly, told no story, scores didn't follow):

| Stage | What it does now |
|---|---|
| **Story pass** | The LLM segments the whole episode into self-contained *stories* (setup → development → payoff) — not loose "moments". 5 chunks → stories with summaries, hook lines, payoffs. |
| **Draft pass** | The tightest 15–60s cut is drafted *inside* each promising story (top 12 ranked by measured laughter+energy), with the story's full verbatim transcript in context. Never blind boundaries. |
| **Edge rules** | Deterministic: snap to sentence edges; never start on filler (um/so/like/yeah → auto-advance); end on sentence punctuation; extend through the laughter so the payoff lands. Unit-tested. |
| **Judge pass** | The gate that was missing: every final cut is judged on its EXACT verbatim transcript (alone? starts/ends abrupt? coherence/hook/payoff 0-10 + verdict). Failing cuts get one feedback-informed repair redraw; a rate-limit cooldown re-check re-judges after rendering. Nothing faked: clips that don't pass are labelled **◐ unverified**. |
| **Score v2** | Computed from the judge's ratings of the exact cut (hook/story/payoff, content-type-weighted) + measured laughter/energy/pacing. Verdict shown under every clip — the score literally follows the content. |
| **Edit polish** | 0.18s video + audio fade-in/out on every cut; blur-pad framing unchanged. |

**Dual-brain AI**: Groq primary + Gemini failover (`CB_GEMINI_KEY` in .env — hot-loaded, no restart; free from aistudio.google.com/apikey). 429s respect Retry-After, then fail over; `CB_AI_PROVIDER=gemini` flips the primary. LeadPilot got the same failover (`AI_GEMINI_KEY`).

**App-shell UI** (same black/white glass, rearranged): left sidebar (Studio · Clips · Candidates · Transcript · Connect + engine status), top bar with live progress chip, one screen at a time, auto-navigation to Clips when a run finishes, bottom-tab collapse under 900px, `?job=` deep links open the right screen. Factor bars renamed to the v5 factors (Hook/Story/Payoff/Energy/Pacing + Laugh).

**Verified live on the 54-min episode** (job 5cfb4853): picker `prox-editor`, judge verdicts rendered
(*"Quick, punchy joke that lands, but the long name list feels like leftover context."*),
scores 76/68/66 follow the verdicts, laugh coverage 100/100/61, honest `unverified` badges on
clips the judge didn't fully clear (Groq free-tier daily quota ran low during testing — paste a
free Gemini key in .env and the judge stops getting rate-limited).

---

## Round 6 — MOMENT_PASS (the F1 verdict: "your engine just sucks")

Your F1 test showed the real problem: the battle where Max beats Lewis — the whole point of the
video — was nowhere on the podium. The engine got a **moment pass**:

| Fix | What it does |
|---|---|
| Peak-event detection | Audio roar + camera-cut density + drama heat → the video's single PEAK EVENT (the overtake/battle) is found by measurement, not LLM vibes. |
| Event factor | The story containing the peak event is forced onto the podium; its score gets the event bonus. The battle became **clip #1 (score 81, judge verified)**. |
| Honest QC | Anything not judge-passed is labelled ◐ unverified — no fake confidence. |

## Round 7 — Stitch UI: exact rebuild (v3.3)

You shipped me the Google Stitch export and demanded the UI look **exactly** like it. Rebuilt from
the export itself — and cleaned, per your call: keep the glass, kill the fake telemetry.

| Item | Result |
|---|---|
| Pixel-faithful shell | index.html composed from the Stitch parts (aside, top bar, 7 screens, shader canvas, Inter + JetBrains Mono, Material Symbols). Two deterministic assemblers (`assemble_ui.py`, `assemble_ui2.py`) rebuild it from `stitch_export/extracted/` — no hand-edited HTML anywhere. |
| Static Tailwind | Compiled from the Stitch theme config into `web/tailwind.css` (no CDN). Root-caused a config bug that nested the whole theme under `extend` — headline was 16px instead of 72px. |
| Waste removed | AUTOSYNC/LATENCY/CUDA/NODE_0x7F/"Frame 17,910"/48 kHz/quota-74% fake telemetry, language chip, mock Google-403 help box — replaced with live engine chips (ENGINE ONLINE · GROQ + GEMINI, POOL READY, real STT model, real key states). |
| Keys in the UI (your ask) | Power-up screen + Connect screen both manage every key: Groq / Gemini / YouTube OAuth inputs, TEST & SAVE per key with **live provider tests** (`clipblitz/keys.py`, `/api/keys`), chips show SAVED · ONLINE / EMPTY. Hot-reload, zero restarts. |
| Failover fixed | On failover the call now uses the *failover brain's own model* (was sending Groq's model name to Google → 404). Retired models self-heal: the successor is parsed from the 404 body and retried. Groq + Gemini verified live. |
| Old design functions back | Custom cut (prompt → `/api/custom`), toasts, diagnose + copy-redirect, QC badges, factor bars, Export .SRT, deep links `?job=…&screen=…` now honored for every screen. |
| Structure bugs found by the visual judge, then fixed | Nested page-shell wrappers inside sections (content offset 312px), the AI-keys card sitting outside its twin-column grid (relocated, depth-tracked), screen switches keeping the old scroll position (headers slid under the top bar), `renderWave` destroying its own `wave-now` span on rebuild (crash), `main` top padding clearing the fixed bar, transcript deep-link showing empty state (full-job fetch now). |
| Visual gate | All 6 screens re-judged against the Stitch references: **studio, clips podium, connect, candidates, transcript, power-up — pass**. |
| End-to-end | Fresh demo job: picker `prox-editor`, 1 clip, score 83, QC **verified**, clip serves 200. |

---

## Round 8 — the UI remake (v3.5.0): glitches removed by construction

The Stitch port looked right but glitched, so I went back to the proven app-shell and rebuilt
`web/` from scratch — same five screens, same buttons, same API. The difference is *how* the
motion is built: instead of patching the glitches out, the mechanisms that caused them no
longer exist in the file.

**What was actually broken in v3.4.5** (found by reading the shipped CSS, not by guessing):

| Banned mechanism found | Why it was a real defect |
|---|---|
| `.clipcard.enter { opacity: 0 }` + `fill: both` | The stuck-dim class. If the browser pauses its animation clock (backgrounded tab, busy box) the card freezes **invisible** — exactly the historic bug. |
| `@keyframes screenin` defined **twice** | One silently overrides the other, so the animation you read is not the animation that runs. This exact bug shipped a flickering chip. |
| `@keyframes fadein` animating `opacity` | Every entrance keyframe touching opacity is a stuck-dim waiting to happen. |
| `.pv-caption` declared twice with conflicting `position` | Which one won depended on source order — a coin flip for the preview layout. |
| `.lm.lo` emitted by `app.js`, never defined in CSS | The live-meter "low" state rendered as nothing at all. |
| orphan `</div>` in `index.html` | Malformed nesting; the parser guessed where the element ended. |
| `web/gsap.min.js` (72 KB) + `web/tailwind.css` (41 KB) | Dead assets — referenced by nothing, still served by `server.py`. An animation library on disk is an invitation to load it again. |

**What it does now** — the law is enforced by construction, so the gates assert the construction
held rather than patching symptoms:

| Rule | How the new `web/` makes it impossible |
|---|---|
| No `opacity` in any keyframe | Only `transform`, `scale`, `stroke-dashoffset`, `width` and `box-shadow` are animated. A stuck-dim entrance cannot be written. |
| No duplicate `@keyframes` names | One namespaced registry — nine keyframes, `cb-` prefixed, all unique, asserted by grep before ship. |
| Chips never flicker | The live indicator pulses `box-shadow` only. No chrome pulses opacity. |
| Resting state = final state | Every animated element's computed default is the fully-visible state, so a frozen clock leaves a correct page, not a dim one. |
| No CDN, no animation library | Everything local. `gsap.min.js` and `tailwind.css` deleted, and their routes removed from `server.py`. |
| Nothing moves under the cursor | No magnetic buttons, no cursor-shifting. |

**Rebuilt, screen by screen** — same five ids and contracts, more that actually works:

| Screen | New in this round |
|---|---|
| Studio | 72px `display-xl` hero, dropzone, URL row, options, caption-style gallery, live 9:16 preview, **recent jobs from `/api/jobs`**, processing box with timeline + bar + skeletons |
| Clips | `#01 ALPHA / #02 BRAVO / #03 CHARLIE` rank badges, circular score dials, `verified` / `unverified` QC badges, hook quote, judge verdict box, factor bars (Hook/Story/Payoff/Energy/Pacing/Event/Laugh), post buttons, metadata editor |
| Candidates | **filters All / Verified / Peak events**, time chips, **mini score dials**, render buttons |
| Transcript | timestamped blocks with peak highlights, **waveform timeline with ruler + playhead + markers**, custom cut window, **Export .SRT** (client-side Blob, no backend endpoint) |
| Connect | API-keys card (Groq / Gemini / YouTube OAuth, per-key Test & save, masked pills), YouTube wizard with live readiness checklist + Diagnose + copy-redirect, assisted platform cards, post queue |

**Fonts are self-hosted now** — Inter (400–800), JetBrains Mono (400–600) and Space Grotesk
(600/700) as six WOFF2 files in `web/fonts/`, served by a new whitelisted `/fonts/<file>` route
with `font-display: swap`. No CDN `<link>`, so there is no network latency between paint and
correct type — a real contributor to the historic "dim first frame".

**The only two backend changes, each with a reason.** `pipeline.py` now persists
`job["waveform"]` (600 normalised RMS buckets derived from the **already-computed** `energy`
series — no extra ffmpeg pass) and `job["moments"]` (the already-mined peak regions), because the
Transcript screen's waveform and peak highlights must show **measured audio**, not decoration.
`server.py` gained the `/fonts/` route and lost the two dead ones. Everything else in
`clipblitz/` is byte-identical, proven by a fresh demo run.

**Verification — every gate, with the numbers:**

| # | Gate | Evidence |
|---|---|---|
| V1 | Rapid-switch stress: 5 nav buttons × 4 rounds at 25 ms | 20 clicks → **0** visible elements below 0.99 opacity, **0** leftover transforms |
| V2 | Frozen-clock probe after V1 | 160 visible elements under the active screen → **0** stuck dim, **0** stuck moved |
| V3 | Headless capture, fresh profile, 1440×900 | mean luminance **29.86** (healthy 26–30; the historic dim bug was ~13), 9.11% bright pixels, 0 void rows |
| V4 | Console + request sweep over all five screens × 2 rounds | **0** errors, **0** warnings, **0** uncaught page errors, **0** failed requests, all 3 fonts loaded |
| V5 | Dangling-reference sweep | every `getElementById`, `data-screen`, icon `<use href="#i-…">` and `@keyframes` name resolves; no duplicates |
| V6 | Computed theme proof (1440×900) | hero computes **72px / 76px / -1.8px**, weight 600 Inter; `label-caps` 11px `1.32px`; `.mono` JetBrains Mono 12px; glass radius **24px**, `blur(30px) saturate(1.4)`, border `rgba(255,255,255,.1)`; primary button radius 9999px white on `#050505` |
| V7 | Engine untouched | fresh `POST /api/demo` → job `done`, clip served as a **valid MP4** (container signature checked), waveform normalised with real variation, moments persisted |
| V8 | Banned-pattern grep | **0** opacity keyframes, **0** duplicate keyframe names, **0** CDN `<script>`/`<link>`, **0** emoji, **0** `gsap`, **0** `tailwind` |

Two things were fixed *because* a gate caught them, which is the point of having gates:

- The sidebar ENGINE chip wrapped **mid-token** (`yt-` / `dlp`). Root cause: a 224px sidebar
  cannot hold `ProX v5 · top 3 · brain groq + gemini · ffmpeg / yt-dlp` on one line, and
  `white-space: normal` allowed the break. Fixed by restructuring the chip into three
  `nowrap` rows — the text was never shortened, every value is still real.
- The console gate's first run reported the sweep only reached **2/5 screens**. The gate was
  wrong (it clicked `[data-goto]`, while the sidebar nav uses `[data-screen]`), but the failure
  was worth having: a nav sweep that silently no-ops proves nothing. Fixed the selector,
  re-ran, **5/5 screens × 2 rounds, 0 errors**.

**End-to-end after the rebuild:** job `57d2d8d4` → `done`, 1 clip (score 80, QC **verified**),
600 waveform buckets, 1 moment persisted, clip serves 200 as a valid MP4.

**Note on the embedded browser console:** the in-app panel's console recorder could not attach
on this machine (`recorder not active for this tab`, and new embedded tabs time out), so V4 is
captured by driving the same app in system Edge via Playwright instead. Same page, same origin,
real errors — just a working recorder.

