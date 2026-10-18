# ClipBlitz Studio v4.3.0 — verification report

Written 2026-10-18 after the release was published, from measurements re-run at that moment.
Nothing in this file is carried over from an earlier version's report. Repository:
<https://github.com/agra-aarav15/clipblitz-ai-shorts>, release
<https://github.com/agra-aarav15/clipblitz-ai-shorts/releases/tag/v4.3.0>, CI run
`39146980874` (all four jobs green).

## What 4.3.0 adds

1. **YouTube, three real causes fixed.** The redirect URI is always the one for the port the
   window is on (4300 / 4301 / 4302 are all documented now, previously only 4301). A refresh
   token Google has expired or revoked — the ~7-day rule while the OAuth app is in Testing —
   is recorded on the token, named on the Connect screen with the fix, and
   `youtube_connected()` stops claiming a dead token is a connection. Consent carries a
   single-use, ten-minute `state` that is verified before any token is stored.
2. **Captions that can be read.** Chunking now breaks on the width that actually fits a
   1080-wide frame and on pauses over 0.6 s — the docstring promised the pause rule and the
   code never implemented it.
3. **A podium that cannot repeat itself.** The duplicate test reads what a clip *says*, not
   only its auto-title, so one beat cannot fill the podium twice under two titles.
4. **A version that cannot drift.** The release workflow used to name the product version in
   ten places and said 4.2.0 while the app said 4.3.0. It now reads `APP_VERSION` from
   `studio/clipblitz/config.py`; the marketplace check proves no version is written down.

## Local measurements (this machine, F: trees)

| Suite | Result |
|---|---|
| `scripts/test_engines.py` | 19 passed, 0 failed, 0 skipped |
| `scripts/test_learning.py` | 28 passed, 0 failed |
| `scripts/test_agent.py` | 71 passed, 0 failed |
| `scripts/test_rights.py` | 62 passed, 0 failed |
| `scripts/test_clipbench.py` | 44 passed, 0 failed |
| `scripts/test_daily.py` | 69 passed, 0 failed |
| `scripts/test_scout.py` | 57 passed, 0 failed |
| `scripts/test_trainer.py` | 64 passed, 0 failed |
| `scripts/test_marketplace.py` | 77 passed, 0 failed here / 94 where the workflow sits next to the checkout |
| `scripts/test_social.py` *(new)* | 45 passed, 0 failed |
| `scripts/test_quality.py` *(new)* | 35 passed, 0 failed |
| `scripts/verify_studio.py` | 30 passed, 0 failed; frozen trees untouched (clipblitz 137 / b2prox 81 files) |
| `scripts/verify_studio.py --render` | 33 passed, 0 failed — real encode, prox `YAVG 28.36` vs graded b2 `YAVG 18.15` |

The three `test_daily` checks that start a cut refuse to run in a checkout with **no bundled
ffmpeg** — that is the engine's own capability gate doing its job, and the CI job fetches
ffmpeg before running the suites (69/0 there).

## The podium board (new)

`scripts/bench_episode.py` scores the podium on a real stored episode — offline,
deterministic, no LLM, no network:

```
episode      F1_excerpt_12min.mp4  (upload, 264 segments, 720.7s, 3 measured peaks)
podium       3/3 filled   avg score 75.3
opens well   33% of picks
same beat    worst written overlap 0.08  (picks 1-2)  OK
spread       closest picks 163.3s apart
hype in podium 0
```

That board is the recorded baseline (`data/bench_episode.json`), and
`--synthetic --gate` runs in CI: it fails if the podium shrinks or if two picks are the same
beat. The laughter-based ending metric is reported as *not measurable on this fixture* rather
than guessed, because stored jobs keep their waveform but not their laughter regions.

## The published artifacts, verified after upload

Downloaded back from the release and checked here, not taken on trust:

| Asset | sha256 | Size | Checks |
|---|---|---|---|
| `ClipBlitzStudio-4.3.0-windows.zip` | `b99bd8abb43c09ececba0b66cd5c817f860a0097e0d3bb9db01adda7fe556d8d` | 150,212,739 | 137 members; **0** forbidden (no `.env`, no `data/`, no caches, no db); 9 plugin files; `ClipBlitzStudio.exe` + bundled `ffmpeg.exe` + `yt-dlp.exe` present; `SETUP-YOUTUBE.md` now ships with the bundle |
| `ClipBlitzStudio.apk` | `5ba88977af6bca240a800df06ece75b1775494f8b8813d5f5757f882ce745e0f` | 34,680 | signed APK, published by CI |
| `checksums.txt` | — | 186 | `sha256sum -c checksums.txt` → **OK / OK** |

The **published** EXE was unpacked and run here: `--tools` lists 11 tools; `--mcp` answers
`initialize` as `clipblitz-studio 4.3.0`; booting it on port 4321 reports
`ClipBlitz Studio 4.3.0` with engines `prox`, `b2`, `both`.

## Boundaries this release does not claim

- **No tool here makes someone else's work immune to a copyright claim.** `rights.py`
  measures, warns and keeps paperwork; a content-matching system matches the work itself.
- **The classic 4301 / 4302 trees are frozen** and byte-identical — 4.3.0 ships from
  `studio/` only, and the YouTube fix was deliberately not back-ported into them.
- **The Android standalone (on-device engine) is still a milestone build**: it publishes a CI
  artifact and never touches the release.
- **ClipMax** (the hosted multi-tenant product) is a separate repository; its M1 security
  layer, engine adapter and live end-to-end render are recorded there.
- The CI digests change on every push that rebuilds assets. `checksums.txt` is generated after
  the uploads and is the live authority; this table is a snapshot of v4.3.0 as published.