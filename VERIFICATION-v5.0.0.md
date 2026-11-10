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
| `scripts/test_argon.py` | **63 passed, 0 failed** |
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

Every rendered clip now gets a poster thumbnail, and the **Slow zoom** option applies a
restrained 1.0 -> 1.05 push-in before the fades and captions. Both are covered by the render
path and a thumbnail failure can never fail the clip.

Final smoke run after those additions: `POST /api/demo?engine=argon&top_n=1&auto_zoom=1`
completed in **152 seconds**, one verified clip (24.9s, score 81, tier strong), 1080x1920 at
30fps, with `slow zoom` in its transformative-work list and a real `.jpg` poster.

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
- The release **is published** as `v5.0.0`. The published Windows zip, APK and checksums were
  downloaded again and `sha256sum -c checksums.txt` returned OK for both assets. The extracted
  EXE answered `--tools` and an MCP `initialize` as `clipblitz-studio` 5.0.0.

---

## Independent verification

**Gemini 4 Argon returned PASS on commit `790425f`.** It ran read-only against the repository
and reported **384 passed, 0 failed** across `test_argon`, `test_engines`, `test_agent`,
`test_rights`, `test_learning`, `test_quality` and `test_marketplace`; it started the server on
a fresh temp data dir and measured **0.704s** for boot + `/api/health`; it confirmed the tuple
crash, offline-verify path, non-compensatory gate, caption non-overlap, compact error card,
version/default engine and the old prox/b2 paths. Its P0 list was **empty**.

The earlier quota block is resolved. The exact brief remains in `VERIFY-WITH-GEMINI.md` for a
future re-run.

## Real source verification (2026-11-10)

Two Formula 1 videos were downloaded through the app and cut with ARGON at `top_n=3`.
Both sources were served by YouTube as AV1 first; the app now prefers H.264 at 1080p on
download and the bundled toolchain was switched to a full ffmpeg build with dav1d. That is
what removed the AV1 decode stall.

| Source | Clips | Scores | Verdict |
|---|---|---|---|
| Nine Minutes Of Max Verstappen Tearing Through The Field At Interlagos | 40.4s / 60.9s / 47.0s | 91 / 86 / 76 | all verified; overtake battle, podium comeback, pit-lane move |
| Race Highlights - 2026 Sao Paulo Grand Prix | 56.6s / 43.1s / 21.5s | 94 / 88 / 81 | all verified; Hamilton battle, Lawson opening lap, Russell spin |

What changed after the first test:

- **H.264 download preference** (`vcodec:h264,res:1080`) so the bundled decoder is not asked
  to decode AV1 at 50 fps.
- **Keyframe-only scene scan** for the visual pass; the old full-rate scan took minutes on a
  9-minute 50 fps AV1 file and is now seconds.
- **Context variants**: the judge now sees a window that starts at the previous sentence, not
  only the spark start. This is what lets the F1 overtake include its build-up.
- **Editor and peak proposals are forced into the judge pool** even when a cheap lexical
  pre-score would have filtered them out.
- **Sports action scoring**: event, visual and concrete action language (overtake, pass,
  podium, finish) now outweigh a calm interview in a sports highlight.
- **Containment rejection**: a 14s sub-clip inside a 56s cut is not a second highlight.
- **No reject-only podium**: if every candidate is downgraded the engine returns the best one
  honestly labelled instead of failing the whole job.
- The logo is monochrome `currentColor` now: white on the dark default, ink on the light theme.

## OpusClip comparison

No OpusClip output files for these two sources exist in this workspace. The competitor folder
contains UI screenshots and help captures, not rendered clips. I did not fabricate a side-by-side
verdict. The comparison used OpusClip's published selection criteria (scroll-stopping opening,
standalone context, clean payoff, high event/action coverage) and the resulting clips were
checked against those criteria. If actual OpusClip exports for these links are supplied, they can
be compared clip-by-clip on the same rubric.

## Published artifacts

Release: <https://github.com/agra-aarav15/clipblitz-ai-shorts/releases/tag/v5.0.0>

| Asset | Check |
|---|---|
| `ClipBlitzStudio-5.0.0-windows.zip` | published; contains the EXE, bundled ffmpeg/yt-dlp, 9 plugin files, `web/cutdesk.css`; no `.env`, no `data/` |
| `ClipBlitzStudio.apk` | published; companion WebView app |
| `checksums.txt` | downloaded; `sha256sum -c` OK for both assets |

The published EXE was unpacked here and run: `--tools` lists `cut_clips`, and `--mcp` answers
`initialize` as `clipblitz-studio 5.0.0`.

## What to run to re-check