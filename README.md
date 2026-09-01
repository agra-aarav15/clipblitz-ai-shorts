# ✂️ ClipBlitz — AI Shorts Factory

> **Long video in → top 3 viral clips out.** Paste a YouTube link or drop a file: the engine
> segments the episode into *stories*, drafts the tightest cut inside each one, lands every ending
> on the audience's laughter, then a strict **QC judge** scores the exact final clip — with its
> verdict shown on every card. Reframed 9:16 with blur-pad framing (nobody gets cut off), animated
> word-by-word captions, AI-written titles/descriptions/hashtags, and automatic YouTube posting.

Your own OpusClip — self-hosted, no watermarks, no per-minute fees, honest scores.

**Version:** v3.1 · Engine: **ProX v5 "The AI Editor"** · Status: ✅ verified end-to-end on a real 54-minute episode

---

## Quickstart (5 minutes)

```bash
# 1. binaries (one-time): ffmpeg + yt-dlp into bin/
bash scripts/fetch-tools.sh          # Windows Git Bash; or download manually into clipblitz/bin/

# 2. config
cp .env.example .env                 # add a free Groq key from console.groq.com

# 3. run
python run.py                        # → http://localhost:4301
```

Open the **Studio** screen → paste a YouTube link (or drop a file) → pick a caption style →
**Edit my video**. Clips land in the **Clips** screen with scores, verdicts and captions.

## The ProX v5 editor pipeline

```
video ─▶ audio ─▶ Whisper word-level transcription (auto-chunked for long videos)
              ─▶ acoustic laughter detection (80 regions found in a 54-min podcast)
    ┌─────────┴──────────────────────────────────────────────┐
    │ 1. STORY PASS    LLM segments the episode into         │
    │                  self-contained stories                │
    │ 2. DRAFT PASS    tightest 15-60s cut drafted INSIDE    │
    │                  each promising story (full context)   │
    │ 3. EDGE RULES    snap to sentences · no filler starts  │
    │                  · end on punctuation · ride the laugh │
    │ 4. JUDGE PASS    the exact final clip is judged:       │
    │                  alone? abrupt edges? coherence 0-10   │
    │                  → one repair redraw, then demotion    │
    │ 5. SCORE v2      judge ratings of the exact cut +      │
    │                  measured laughter/energy/pacing       │
    └─────────┬──────────────────────────────────────────────┘
              └─▶ render 9:16 (blur-pad) + captions + metadata + auto-post
```

Every clip card shows its **factor bars** (Hook / Story / Payoff / Energy / Pacing / Laugh) and
the **judge's verdict line** — the score literally follows the content, nothing is invented.
Clips that don't fully pass the judge are honestly labelled `◐ unverified`.

## Screens (app shell)

- **Studio** — upload / YouTube URL, caption-style live preview, framing (blur-pad / crop), processing timeline
- **Clips** — top-3 podium: score dials, factor bars, judge verdicts, metadata editors, post chips
- **Candidates** — every runner-up with its measured score; one click renders any of them
- **Transcript** — click a line to jump; drag the handles to cut your own clip (same engine, same honesty)
- **Connect** — YouTube OAuth with a **live 5-step diagnostic** of the whole auto-post chain

## Social automation

- **YouTube — fully automatic**: one-time OAuth (in-app 4-step wizard with deep links into each
  Google Cloud page + copy-ready redirect URI + live diagnostics). Uploads fire by themselves with
  metadata + #Shorts. Free quota ≈ 6 uploads/day.
- **TikTok / Instagram / Facebook / X — assisted one-click**: caption package auto-copied, upload
  page opened. Full-auto arrives with a platform dev app or a posting-API key (`CB_POST_KEY`).

## Dual-brain AI (no more rate-limit walls)

Groq (free) is the primary brain; add a free Gemini key (`CB_GEMINI_KEY` in `.env`,
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)) and every engine call that gets
throttled instantly fails over — keys hot-reload, no restart. `CB_AI_PROVIDER=gemini` flips the order.

## Zero-framework core

The server is **pure Python stdlib** (no FastAPI/Flask) + bundled ffmpeg + yt-dlp + Whisper API.
The UI is vanilla HTML/CSS/JS. Deploy the Dockerfile anywhere.

## Docs

- [SETUP-YOUTUBE.md](SETUP-YOUTUBE.md) — the 4-step OAuth wizard, click by click
- [FIXED.md](FIXED.md) — the honest changelog: 5 rounds, ~40 recurring errors hunted and closed
- [.env.example](.env.example) — every knob documented

## Smoke test

```bash
python scripts/smoke.py   # offline e2e: demo video → stories → cut → captions → ALL GREEN
```
