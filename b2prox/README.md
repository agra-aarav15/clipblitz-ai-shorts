# B2 Pro X — cinematic clip engine

**Long video in → cinematic shorts out.** This is the next-generation engine: it inherits
ClipBlitz's battle-tested editorial spine (peak-moment mining, story segmentation, drafted cuts,
deterministic edge rules, judge pass with repair, honest scoring, dual-brain failover) and adds a
**cinema layer** on top that makes the cuts and the finish feel edited rather than extracted.

**Version:** 1.0.0-b2 · **Engine:** B2 Pro X · **Port:** 4302 · **UI:** the same Obsidian Keynote shell

---

## What the cinema layer adds

| Layer | What it does | How it is measured |
|---|---|---|
| **Scene map** | Real shot boundaries, so cuts can land on an edit instead of an arbitrary stop | `ffmpeg select=gt(scene,0.30),showinfo` — verified to detect cuts at exactly 3.0 / 6.0 / 9.0 s on a control clip |
| **Motion map** | Per-second on-screen energy, so the engine knows where the picture moves (an overtake, a punch, a reveal) — not only where the audio is loud | `tblend=difference,signalstats` YAVG, normalised 0–1 |
| **Cinema snap** | A cut edge within 1.6 s of a shot boundary is pulled onto it, so clips start on a new shot and end on a shot change — while still never crossing a sentence start | `cinema.cinema_snap()` |
| **Scene grammar** | The cut is re-timed to open on the establishing/wide beat when the story has one, and to land its payoff on the peak shot (highest measured motion inside the cut) | `cinema.scene_grammar()` |
| **Cinematic finish** | A restrained film grade — S-curve contrast, slight black lift, mild highlight desaturation, soft vignette (and optional grain) | `cinema.cinematic_filters()`, applied in the render chain |
| **J/L-cut audio lead** | On the incoming cut the audio is already running as the picture appears, so cuts feel carried rather than chopped | `audio_lead` (default 0.35 s) in `ffmpeg_tools.cut_clip()` |
| **Multi-ratio export** | 9:16 (default), 1:1, 16:9 | `cinema.RATIOS` |

Everything in the cinema layer is **deterministic measurement** — no AI is involved in timing or
grading. The AI is used where it was always used: understanding the story and judging the cut.

---

## The full pipeline

```
video ─▶ audio ─▶ loudness profile + acoustic laughter detection
      ─▶ transcription (Groq / Gemini whisper, auto-chunked)
      ─▶ PEAK MOMENT mining (audio roar + camera cuts + drama heat)
      ─▶ B2 CINEMA MAP (shot boundaries + per-second motion)          <- new
    ┌───┴───────────────────────────────────────────────────────┐
    │ 1. STORY PASS     self-contained stories across the video │
    │ 2. DRAFT PASS     tightest 15-60s cut inside each story   │
    │ 3. EDGE RULES     sentences · no filler · ride the laugh  │
    │ 4. B2 CINEMA PASS snap edges to shots, land on the peak   │  <- new
    │ 5. JUDGE PASS     does the finished cut stand alone?      │
    │                   → one repair redraw, then demotion      │
    │ 6. SCORE v2       judge ratings + measured factors        │
    └───┬───────────────────────────────────────────────────────┘
        └─▶ cinematic grade + vignette + J-cut lead + captions + 9:16
```

## Honesty rules (unchanged and non-negotiable)

- No random starts: sentence edges, never filler.
- Endings must land (punctuation or laughter) or the clip is demoted.
- Every cut is judged on its **exact** transcript; the verdict is shown on the card.
- Clips that do not pass are labelled **unverified**, never dressed up.
- Scores follow content. No invented telemetry in the UI.

## Running it

```bat
python run.py          :: → http://localhost:4302
```

Keys are managed in the app (Connect screen → API keys → Test & save). No file editing.

Verify the whole thing in one command:

```bat
python scripts/verify_b2.py
```

It checks: health + engine name, the cinema module, scene detection on a generated control clip
(must find the cuts), a live demo end-to-end run, and the rendered output's specs (1080×1920, audio
present, graded frames).

## Layout

```
b2prox/
  run.py
  clipblitz/           server + pipeline + engine
    cinema.py          <- the B2 cinema layer (scene map, motion map, snap, grammar, grade)
    virality.py        story/draft/judge/score + the cinema pass
    pipeline.py        orchestration + B2 cinema measurement
    ffmpeg_tools.py    cut + reframe + grade + J-cut
  web/                 the Obsidian Keynote UI (self-hosted fonts, no CDN, no animation library)
  docs/shots/          verified screenshots
  scripts/verify_b2.py the end-to-end verification
  data/                your clips, uploads, job history
```

Inherited from ClipBlitz: the whole editorial spine and the UI shell. New in B2 Pro X: `cinema.py`
and every integration point marked *new* above.

## Relationship to ClipBlitz

ClipBlitz (port 4301) remains the stable, documented product. B2 Pro X (port 4302) is the cinematic
evolution — same honesty model, sharper cuts, graded finish, multi-ratio output. They are separate
projects with separate data folders and can run side by side.

## License

See the repository. Clips you make are yours; respect the rights of the videos you process.