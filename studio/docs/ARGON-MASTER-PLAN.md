# ARGON - master plan, model routing, and handoff brief

Status: **implemented in this workspace** as `clipstudio/clipblitz/argon.py`, wired into the
pipeline, server, agent/MCP, learning store and UI as the new default engine (`engine_id:
"argon"`). Old engines remain available as regression fallbacks. This file is the design record
and the copy-paste brief for another model.

> Note on the supplied screenshot: the image content arrived badly corrupted/repeated and did
> not contain a readable algorithm, reference link, or source. The only legible idea was the
> model routing hint ("Gemini 4 Argon wins clipping logic", "Claude Opus 5.5 wins pipeline
> architecture"). ARGON below is therefore an original clean-room design built from public
> research, first-principles editorial rules, and this repository's own measured pipeline. No
> proprietary code was copied or decompiled.

---

## 1. What ARGON replaces

| Old engine | Strength | Blind spot | ARGON answer |
|---|---|---|---|
| ProX v5 | Complete story arcs | Slow lead-ins; one draft per story; payoff-only scoring | Multi-scale windows, cold-open compaction, hook + story + payoff in one score |
| B2 Pro X | Cinematic shot timing and grade | Can cut through logic just to land on a shot | Shot snapping only when it preserves the sentence edge; meaning wins |
| APEX | Scroll-stopping hooks | Clickbait hooks with no payoff | Backward-chained payoff search + non-compensatory ending gate |

ARGON does not blend three outputs after the fact. It generates one candidate graph from every
signal and selects with one objective.

---

## 2. The algorithm

### 2.1 Perception

Deterministic inputs already produced by the studio:

- word-level transcript (sentence/segment boundaries)
- audio loudness curve (`ffmpeg` loudness profile)
- acoustic laughter regions
- shot boundaries (`ffmpeg select=gt(scene,...)`)
- per-second motion (`tblend=difference` + `signalstats` YAVG)

Optional LLM: story mapping, exact-transcript retention judging, adversarial flagging.

### 2.2 Anchor graph

Four orthogonal seeds, unioned and de-duplicated:

1. **Spoken sparks** - questions, hard numbers, contrarian claims, challenge lines, contrast
   pivots, stakes. Hype/greeting material is banned before it can seed anything.
2. **Story arcs** - the existing story pass when a brain is available; deterministic
   peak-anchored stories when it is not.
3. **Measured peaks** - audio roar + camera-cut density + transcript heat.
4. **Cinematic beats** - high-motion points that also sit on a real shot boundary.

### 2.3 Multi-scale windows

Each anchor is expanded into sentence-aligned starts and ends across the length ladder
`12, 16, 22, 30, 42, 58s`, bounded to `10-75s`. The bounds are then enforced:

- start on a real sentence start;
- never start on filler (`um`, `so`, `like`, `yeah`, `and`, ...);
- end on a sentence end, and ride through a nearby laugh when one exists;
- snap to a shot boundary only within 1.8s and only if the sentence edge survives;
- drop a window entirely if the only way to reach minimum length is through filler.

This is why the old failure mode ("the clip I wanted was 12 seconds later") disappears: the
engine evaluates the alternative windows instead of committing to one draft.

### 2.3b Editor pass

When a brain is configured, one editor call per transcript chunk proposes exact windows and
story arcs with title, hook, payoff, kind and confidence. The proposal enters the candidate
graph at higher priority than a generic multi-scale window, is snapped to sentence edges, and
is still measured and judged like every other candidate. The LLM never gets to skip the gate.

### 2.4 Features

The six learning-compatible factors stay stable: `hook`, `story`, `payoff`, `energy`, `pacing`,
`event`.

ARGON adds and exposes: `emotion`, `novelty`, `visual`, `self_sufficient`, `loop`, `clarity`,
`shareability`, `open_loop`, `context_dependency`, `failure_risk`, plus `hook_speed`.

Highlights:

- **hook** = spoken pull + first-seconds energy + question marker.
- **payoff** = tail laughter + final punctuation + resolution lexicon + judge payoff.
- **story** = clean edges + low filler + duration fit + list completeness (a "three rules"
  clip must contain the three rules).
- **self_sufficient** = clean opener + complete ending + enough words + low deictic risk.
- **context_dependency** = unresolved opening pronouns, back-references ("as I mentioned"),
  and visual deictics ("look at this chart", "on screen").
- **failure_risk** = incomplete list + context dependency + unfinished ending.

### 2.5 Judge + adversarial gate

The LLM sees the **exact final transcript** and the measured signals. It returns:

`alone`, `starts_abrupt`, `ends_abrupt`, `coherence`, `hook`, `payoff`, `emotion`,
`shareability`, `rewatch`, `clarity`, `retention_3s`, `retention_end`, concrete `flags`, and a
one-line `verdict`.

The judge never picks a timestamp. It can only approve, reject, or name a defect.

A **non-compensatory gate** then rejects a clip when any of these is true:

- `self_sufficiency < 0.40`
- `payoff < 0.38`
- `failure_risk > 0.62`
- a fatal flag is present
- the judge says it is not standalone or ends abruptly

A great hook cannot save a dead ending.

### 2.6 Repair loop

Before rejecting a high-potential clip, the engine applies the smallest deterministic fix:

1. **Left shift** for a dangling opening (previous sentence start, max 10s).
2. **Hook promotion** for a slow/weak start (next strong spark inside the first 7s).
3. **Right shift** for a premature ending (next sentence end, then a nearby laugh, max 18s).
4. **Front trim** for a too-long window (keep the payoff).

The repaired window is re-measured and re-judged once. There is no unbounded repair loop.

### 2.7 Score, tiers, selection

The score is `30 + 69 * blend^1.12`, with a measured-peak bonus, flag penalties, hard caps for a
dead ending / context dependency, and a `0.72` multiplier when the gate fails. Tiers:

- `reject` (< 60, or failed gate, or fatal flag)
- `usable` (60-74)
- `strong` (75-87)
- `viral` (88-99, zero fatal flags)

Selection is MMR with:

- verified/no-dead-ending first;
- temporal spread;
- temporal IoU rejection (the same payoff cut twice is not two clips);
- lexical duplicate-beat rejection;
- a relaxed second pass that still refuses duplicates.

A short honest podium is preferred to three cuts of the same joke.

---

## 3. Files changed

| File | Change |
|---|---|
| `clipblitz/argon.py` | The new engine (anchors, windows, features, judge, gate, repair, MMR) |
| `clipblitz/pipeline.py` | Imports/registers ARGON; runs cinema map for it; renders `argon` variants; custom cuts use ARGON measurement; clip payload carries `tier`, `gate`, `flags`, `argon` |
| `clipblitz/server.py` | `/api/health` lists ARGON first and makes it the default; engine validation; banner |
| `clipblitz/agent.py` | `DEFAULT_ENGINE = "argon"`; MCP/CLI engine enum and description |
| `clipblitz/config.py` | `CB_ENGINE` default is `argon` |
| `clipblitz/learning.py` | ARGON has its own learning profile name |
| `web/index.html`, `web/app.js` | ARGON selector default; fallbacks; hero copy |
| `scripts/test_argon.py` | 61 offline checks: windows, features, gate, judge, repair, diversity, determinism, pipeline contract |
| `README.md`, `SETUP.md`, `plugin/`, manifests | Version 5.0.0; ARGON is the documented default; legacy engines remain |

The old ProX/B2/APEX paths are preserved for byte-fidelity tests and as fallbacks. Nothing in
`rights.py` changed: the agent still cannot publish, judge for the owner, or clear rights.

---

## 4. Model routing (what each model is actually good for)

| Work | Model | Why |
|---|---|---|
| Editorial logic, retention rubric, failure-mode taxonomy, judge prompt | **Gemini 4 Argon** | Strongest multimodal/editorial reasoning in this catalog; produced the four-channel seed and 13-feature spec that informed this implementation |
| Architecture, integration review, risk audit, final code review | **Claude Opus 5.5** | Best at whole-system contracts and catching silent integration breakage; use `effort: high` |
| Adversarial red-team, test design, "how would this fail?" | **GPT-6.1 Sol / GPT-6 Astra** | Independent reviewer; do not let it also write the implementation it reviews |
| Long transcript/story mapping and chapterization | **Kimi K3 or GLM 5.3** | Long-context reading; keep timestamps anchored to sentence IDs |
| Fast implementation, UI wiring, mechanical refactors | **Claude Sonnet 5 / Fable 5.1** | Cheap and fast once the contract is fixed |
| Orchestration, deterministic Python, tests, evidence | **DeepSeek V4.1 Flash (this thread)** | The current implementation owner |
| Shipped-app reverse engineering, if a user supplies a binary/APK and owns the rights | **REA MCP** (`morluto/rea`) | Evidence-based artifact analysis; never a license to copy proprietary source |

Rule: one model writes, a different model reviews. Never let the same model both invent the
metric and certify it.

---

## 5. Copy-paste brief for another model

Give the block below to the reviewing/continuing model. Replace the bracketed path only if the
checkout moved.

```text
You are the independent architecture and editorial reviewer for the ClipBlitz Studio ARGON
engine. Work inside f:/Clipblitz/clipstudio. Read the actual files; do not assume.

Files that matter:
- clipblitz/argon.py            (the new unified engine)
- clipblitz/pipeline.py         (job orchestration and engine branching)
- clipblitz/virality.py         (shared measurement/judge helpers ARGON reuses)
- clipblitz/server.py           (engine validation, /api/health, default)
- clipblitz/agent.py            (MCP/CLI surface; default engine)
- clipblitz/learning.py         (six-factor learning store and per-engine profile)
- scripts/test_argon.py         (61 offline checks)
- scripts/test_engines.py       (ProX/B2 fidelity regression)
- README.md, SETUP.md           (docs may lag the code)

Context:
ARGON replaces ProX v5 (story-first), B2 Pro X (cinema-first) and APEX (hook-first) with one
engine: a four-channel anchor graph (spoken sparks, story arcs, measured peaks, cinematic beats),
multi-scale sentence-aligned windows (10-75s), 16 deterministic features, an exact-transcript
retention judge, a non-compensatory gate, a deterministic repair loop, and MMR diversity.
It is now the default engine. Old engines remain as regression fallbacks.

Hard constraints:
- Pure Python standard library + bundled ffmpeg. No pip, npm, CDN, or build step.
- No emojis. No invented scores or telemetry. Offline runs must never say "verified".
- The LLM never invents raw timestamps; it rates a final window or names a defect.
- A great hook must not compensate for a dead ending or a context-dependent opening.
- Rights behavior must not change: no publish tool, no evasion, rights gate stays human.
- Keep the six existing learning factor names: hook, story, payoff, energy, pacing, event.
- Do not break ProX/B2 byte-fidelity tests.

Your job:
1. Read argon.py end to end and list every real defect: wrong math, unsafe assumptions,
   duplicated logic, places where a judge failure could silently become a pass, places where
   an offline run could claim a verdict, and places where the gate can be bypassed.
2. Check the pipeline wiring: a new "argon" job must run one analysis pass, one cinema map,
   render exactly top_n ARGON clips, store the engine id/name, and expose tier/gate/flags/argon
   on the clip. Find every place that still hardcodes b2 or a three-engine assumption.
3. Check the tests: identify what is not covered (long video, silent video, no transcript, no
   brain, judge rate-limit, short tail, duplicate beats, list truncation, dangling pronoun).
   Propose exact new test cases, not vague advice.
4. Run the offline suites and report the real numbers:
   python scripts/test_argon.py
   python scripts/test_engines.py
   python scripts/test_agent.py
   python scripts/test_learning.py
   python scripts/test_trainer.py
   python scripts/test_rights.py
   python scripts/test_scout.py
   python scripts/test_clipbench.py
   python scripts/test_daily.py
   python scripts/test_social.py
   python scripts/test_quality.py
   python scripts/test_marketplace.py
5. Produce a prioritized patch list: P0 correctness, P1 clip quality, P2 polish. For each item
   give the file, function, the failure it causes, and the smallest fix. Do not rewrite the
   engine wholesale; preserve working behavior and tests.

Do not claim a result you did not run. Distinguish observed evidence from inference. If a
reference is missing, say it is missing instead of inventing it. Do not copy proprietary code.
Return: findings, evidence, patch list, and unresolved questions.
```

---

## 6. Verification already run

| Check | Result |
|---|---|
| `python scripts/test_argon.py` | 61 passed, 0 failed |
| `python scripts/test_engines.py` | 30 passed, 0 failed |
| `python scripts/test_agent.py` | 75 passed, 0 failed |
| `python scripts/test_learning.py` | 28 passed, 0 failed |
| `python scripts/test_trainer.py` | 64 passed, 0 failed |
| `python scripts/test_rights.py` | 62 passed, 0 failed |
| `python scripts/test_scout.py` | 57 passed, 0 failed |
| `python scripts/test_clipbench.py` | 44 passed, 0 failed |
| `python scripts/test_daily.py` | 69 passed, 0 failed |
| `python scripts/test_social.py` | 45 passed, 0 failed |
| `python scripts/test_quality.py` | 35 passed, 0 failed |
| `python scripts/test_marketplace.py` | 77 passed, 0 failed |
| Real demo job through `/api/demo?engine=argon` | done; 2 ARGON clips, 1080x1920 (24.9s / 46.3s); the overlap rule was tightened after this run |
| `/api/health` | `default_engine: argon`; engines: argon, prox, b2, apex, both |

The demo job ran in a throwaway `CB_DATA` directory so no owner data was touched.

---

## 7. Recent hardening (after the first 5.0.0 verification)

- Scene marks are normalised from floats, `(time, score)` tuples and stored dicts, so a B2
  cinema map can no longer crash ARGON with `float(tuple)`.
- Source-caption detection: eight low-res frames, conservative outlined-text band test; when a
  burned-in caption band is found, the new captions move to the top instead of double-printing.
- Caption events are clamped so two ASS events can never overlap.
- Edge silence is trimmed for ARGON (head pre-roll protected, tail protected when laughter says
  the reaction is the payoff).
- Auto face crop is optional via OpenCV; without OpenCV the renderer uses a centre crop.
- ARGON no longer pays for a second motion-map pass; it reuses the scene cuts already measured
  for peak mining.
- The blur-pad background is blurred at quarter resolution, and ARGON drops the expensive
  vignette. A 10s ARGON render fell from ~30s to ~11s on this laptop; a full demo job fell from
  538s to 174s.
- The dark interface remains the default; the Cutting Desk light theme is a toggle.

## 8. Known limits (do not paper over)

- "Beat every company in everything" is not a measurable claim. ARGON is a stronger, more
  honest engine, but clip quality still depends on the source, the transcript, and the judge.
- The judge is an LLM; it can be wrong. The engine exposes its exact ratings and flags so a
  human can disagree with it.
- There is no true face tracking, speaker diarization, or audio source separation yet. The
  visual layer uses scene cuts and motion; the audio layer uses loudness and laughter.
  Those are the next real upgrades, not something to claim today.
- REA can analyze a shipped artifact only when the user supplies it and owns the rights. It
  does not make copying another product's proprietary implementation acceptable.
