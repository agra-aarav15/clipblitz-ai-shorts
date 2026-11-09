# ClipBlitz Studio v5.0.0 - verification report

Written 2026-11-08 from measurements run in this workspace. Nothing below is carried over
from an older report.

Repository: <https://github.com/agra-aarav15/clipblitz-ai-shorts>
Engine default: **ARGON** (`engine_id: "argon"`)

---

## What 5.0.0 adds

1. **ARGON, one unified engine.** A four-channel anchor graph (spoken sparks, story arcs,
   measured peaks, cinematic beats), multi-scale sentence-aligned windows (10-75s), 16
   measured features, an exact-transcript retention judge, a non-compensatory gate, a
   deterministic repair loop, and MMR diversity. It replaces the three selection strategies
   as the default; ProX v5, B2 Pro X, APEX and Both remain as fallbacks/comparisons.
2. **A judge that names the defect.** Hook, payoff, emotion, shareability, rewatch, clarity,
   retention-at-3s, retention-to-end, and concrete flags. The judge never invents a timestamp;
   it rates the exact final window or asks for a deterministic repair.
3. **A gate that cannot be bought with a hook.** Self-sufficiency < 0.40, payoff < 0.38,
   failure risk > 0.62, a fatal flag, or a judge-confirmed dead ending rejects the clip even
   when the opening is excellent.
4. **Clip payload keeps the evidence.** Rendered clips now carry `tier`, `gate`, `flags` and
   the full `argon` breakdown, not only the six learning factors.
5. **Version 5.0.0 is one number.** The app, health payload, MCP serverInfo, plugin manifest
   and marketplace metadata all read the same version.

---

## Local measurements (this machine)

Run from `repo-clipblitz/studio` unless marked otherwise.

| Suite | Result |
|---|---|
| `scripts/test_argon.py` | **61 passed, 0 failed** |
| `scripts/test_engines.py` | 29 passed, 0 failed, 1 skipped |
| `scripts/test_learning.py` | 28 passed, 0 failed |
| `scripts/test_agent.py` | 75 passed, 0 failed |
| `scripts/test_trainer.py` | 64 passed, 0 failed |
| `scripts/test_rights.py` | 62 passed, 0 failed |
| `scripts/test_scout.py` | 57 passed, 0 failed |
| `scripts/test_clipbench.py` | 44 passed, 0 failed |
| `scripts/test_daily.py` | 69 passed, 0 failed |
| `scripts/test_social.py` | 45 passed, 0 failed |
| `scripts/test_quality.py` | 35 passed, 0 failed |
| `scripts/test_marketplace.py` | 94 passed, 0 failed (repo root) |
| `scripts/test_marketplace.py` | 77 passed, 0 failed (studio-only tree) |

The one `test_engines` skip is the byte-fidelity comparison against the frozen ProX v5 tree:
the checkout used for this run does not have that tree next to it. In `clipstudio` (where the
frozen tree exists) the same suite is **30 passed, 0 failed, 0 skipped**.

---

## Health and agent surface

```
ClipBlitz Studio 5.0.0
default_engine: argon
engines: argon, prox, b2, apex, both
```

`python -m clipblitz.agent tools` lists the same **11 tools** and the `cut_clips` engine enum
contains `prox, b2, apex, argon, both`.

---

## Real end-to-end ARGON run

Executed through `POST /api/demo?engine=argon&top_n=2&style=wordpop` against a throwaway
`CB_DATA` directory, so no owner data was touched.

| Field | Result |
|---|---|
| Job | `1ccdc1a0` |
| Status | done |
| Engine | ARGON unified |
| Picker | `api+argon-editor` |
| Rendered clips | 2 |
| Dimensions | 1080x1920 both |
| Durations | 24.9s, 46.3s |
| QC | both `verified` |
| Tier | both `strong` |
| Score | both 82 |
| Retention | 9/10 -> 8/10 and 8/10 -> 8/10 |
| Judge flags | none |

A final demo run after the editor pass, caption-band detection, cheap blur and no-vignette
ARGON finish completed in **168 seconds** (down from 538 seconds on the same machine) with two
verified clips: 24.6s / score 81 and 18.9s / score 77.

A previously failing 73.6s clip at 50 fps was re-rendered through the custom-cut path after
capping output to 30 fps; it completed in roughly four minutes and produced a valid 73.6s file.
The old failure was a render timeout, not a missing file or a bad filter.

Server startup and `/api/health` were also importing `faster_whisper` (and therefore torch)
when no API key was configured, and importing OpenCV at module load. Both are now presence
checks / lazy imports; health answers in about two seconds on the same machine.

The job card had a class collision: the top-bar `.jobbox` flex rule was also applied to the
progress panel, so the job title and the raw ffmpeg command were squeezed into two columns and
wrapped into a wall of text. The top bar now uses `.topjob`; the progress panel is a normal
block. Errors show a one-line reason and a **Show details** button, never a raw command by
default.

The overlap/diversity rule was tightened after this run (a shared ending within 2s and a
temporal IoU above 0.45 now count as the same beat), so a future run on a short source may
return fewer, more distinct clips. That is intentional: a shorter honest podium beats three
cuts of the same payoff.

---

## What is verified vs what is not

**Verified**

- The engine runs offline with no API key, deterministically, and never claims a judge
  verdict it did not receive.
- The gate rejects a high-hook/dead-ending candidate in the offline test suite.
- Duplicate-beat rejection, temporal spread and MMR selection are covered by tests.
- The pipeline stores the ARGON engine id/name and preserves `tier`, `gate`, `flags` and
  `argon` on rendered clips.
- The old ProX/B2 fidelity tests still pass; the ARGON branch did not change their paths.
- Rights behavior is unchanged: no publish tool, no clearance evasion, human gate only.
- The agent/MCP surface still has 11 tools and no publish tool.

**Not claimed**

- **No blind A/B against OpusClip has been run.** The claim "beats every company" is not
  proven and is not repeated here. It needs real source videos, blind judges, and retention
  or preference data. ARGON is structurally stronger and fully tested; that is a different
  statement.
- The judge is an LLM. It can be wrong. Its ratings, flags and gate decision are exposed so a
  human can disagree with them.
- There is no face tracking, speaker diarization or audio source separation yet. The visual
  layer uses shot cuts and motion; the audio layer uses loudness and laughter.
- No proprietary code was copied or decompiled. The supplied screenshot was unreadable and
  contained no usable algorithm or reference. ARGON is a clean-room design built from public
  research, first-principles editorial rules, and this repository's measured pipeline.
- The release is **not published** by this report. The repository working tree is ready for
  review; tagging and uploading are separate, reviewed steps.

---

## Independent verification

The Gemini 4 Argon review was launched twice against commit `2fb553c`. Both calls were
refused by the provider with `403 theos_insufficient` (account quota; the response named a
refresh time of `2026-11-09T04:29:50+00:00`). **No Gemini verdict exists yet.** The exact
read-only review brief is in `VERIFY-WITH-GEMINI.md`; paste that file into Gemini when the
quota is available. The local evidence above stands on its own until then.

## What to run to re-check

```
cd studio
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

python run.py 4396
curl http://127.0.0.1:4396/api/health
python -m clipblitz.agent tools
```
