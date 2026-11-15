# ClipBlitz Studio v5.6.1 — three real videos, measured end to end

This is the report behind the three-video claim. The engine was the **5.6.1** source
tree on Windows 11 (8 cores, 15.9 GB RAM, bundled ffmpeg 9.0.1 and yt-dlp). The three
files were downloaded once from their public YouTube URLs, then every run below used
the **local mp4** and the **source captions** so re-downloads could not flatter the
numbers. No API key is printed or stored in this report; the configured free-tier
providers were Groq and Gemini, with a local Ollama endpoint as the last fallback.

The command was the same for all three:

```
CB_DATA=data/verify-561 CB_DAILY=off python scripts/verify_media.py   --video data/verify-560/uploads/techwiser.mp4 --label techwiser   --video data/verify-560/uploads/f1.mp4 --label f1   --video data/verify-560/uploads/mrbeast.mp4 --label mrbeast   --data data/verify-561 --top-n 3 --json data/verify-561/report.json
```

## Results

| Video | Length | Wall time | Caption blocks | Candidates (gate-failed) | Final clips | Best clip | Score | Verdict |
|---|---:|---:|---:|---:|---:|---|---:|---|
| TechWiser — *The AI Bubble Has Burst!!!* (`ao15po7On_I`) | 818.5 s (13:39) | 402.2 s | 223 | 10 (8) | **1** | 9.8–29.8 s, 19.98 s | 74 | usable · verified · suspense |
| F1 Race Bulletin — *Why NO F1 Driver Can Drive Like Max Verstappen* (`ruGEIN53kPY`) | 560.4 s (9:20) | 714.1 s | 129 | 10 (8) | **1** | 289.9–333.7 s, 43.87 s | 87 | strong · verified · suspense |
| MrBeast — *$250,000 Hunger Games In Real Life* (`q6fgVVmdpgY`) | 2037.2 s (33:57) | 1474.0 s | 1114 | 10 (7) | **1** | 1306.7–1363.4 s, 56.67 s | 76 | strong · verified · inspiring |

Every final file is **1080×1920, H.264/AAC, with audio**, and every job finished in
`captions+argon-editor` mode:

```
data/verify-561/clips/86aa10b0_1.mp4   5.9 MB  19.98 s
data/verify-561/clips/6d76c2b7_1.mp4    21 MB  43.87 s
data/verify-561/clips/aea3dbcb_1.mp4    22 MB  56.67 s
```

The raw record, including every stage timestamp and provider note, is
`data/verify-561/report.json` and the server-side `data/verify-561/jobs.json`.

## What was actually measured

- **Captions, not speech-to-text.** The download included the English caption track.
  TechWiser read **223** blocks, F1 **129**, MrBeast **1,114**. No STT API was used.
- **The five measured layers** ran on the real media: active picture area, audio energy,
  acoustic laughter, camera cuts/peaks, and burned-in source-caption detection. They are
  the slow part of the wall time and the reason the numbers are not synthetic.
- **ARGON's editor and judge** saw the local transcript. On TechWiser it returned one
  tight 20-second market-drama cut. On F1 it rendered two candidates and the final QC
  judge kept one (the other was rejected). On MrBeast it mined ten candidates, the
  non-compensatory gate rejected seven, and one self-contained story survived.
- **No padding.** Three videos, three verified clips. The engine is allowed to return
  fewer than `--top-n`; the old builds' three-clip fillers are exactly what ARGON was
  built to stop.
- **The caption-language fix is visible.** Before 5.6.1, MrBeast's job picked an Urdu
  translated track because it had more words than the English source track. The judge
  read the translation and returned an empty podium. 5.6.1 reads the source language
  from the download sidecar, prefers an original English track, and only then the
  richest track. The MrBeast run above is the same video after that fix, with an English
  title and an English transcript.

## Provider reality (not hidden)

The logs show the free tiers doing what free tiers do:

```
provider calls: techwiser 7 (groq)
  groq   HTTP 429 ×2
  gemini HTTP 429 ×2
  local  TimeoutError ×2
provider calls: f1 9 (groq)
  groq   EmptyAnswer ×1, HTTP 429 ×4
  gemini HTTP 429 ×1
  local  TimeoutError ×1
provider calls: mrbeast 8 (groq)
  groq   HTTP 429 ×2
  gemini HTTP 429 ×2
  local  TimeoutError ×2
```

The run did not fail when a provider was throttled: it fell over to the next provider,
then to the measured-only path when no editor answered. That is why the fallback title
for F1 and MrBeast is a cleaned transcript line rather than a hand-written headline.
It is also why the wall time is slower than the media length on the 34-minute video:
386 s of audio-energy analysis, 497 s of acoustic laughter detection, 683 s of peak and
camera-cut detection, 967 s of source-caption checking, then 190 s of AI and 260 s of
rendering. A paid key removes the 429s, not the measurement cost.

## 5.6.2 title cleanup

5.6.1's fallback metadata kept the raw caption line, including `>>` speaker arrows,
`[music]` tags and half sentences. 5.6.2 sanitises **fallback and AI-returned** titles:
speaker arrows and music/applause tags are removed, repeated adjacent words collapse,
dangling glue words are trimmed, and the result is cut at a word boundary under 95
characters. It never invents a claim; it only stops a transcript line from looking like
a transcript line. The rendered pixels are unchanged, so the three videos above were
not re-rendered for this cosmetic fix.

Examples from the exact fallback lines:

| Raw | 5.6.2 |
|---|---|
| `Run wide, [music] crash, and have to start over. Confidence goes. You ` | `Run wide, crash, and have to start over. Confidence goes.` |
| `>> Day two, made it through the night, top six. Still got our our main` | `Day two, made it through the night, top six. Still got our main` |

Tests: `python scripts/test_titles.py` → 5 passed; full studio suite → **824 passed,
0 failed** (18 caption tests included).

## What this does not prove

- It does not prove every 34-minute video yields three clips. It proves this one yielded
  one strong, verified clip and did not pretend the other nine candidates were podium
  material.
- It does not prove one-click YouTube upload. That still needs a Google Cloud project
  owned by the user, a Desktop OAuth client, the `youtube.upload` scope and its quota.
- It does not prove signed installers. Windows SmartScreen and macOS Gatekeeper will
  warn until a code-signing certificate is supplied; the builds are wired for it.
- It does not prove the same wall time on a slower laptop. The measurement layers scale
  with cores; the free-tier 429s are external.

## Desktop shell (v5.6.3)

The engine report above is 5.6.1. The shell was verified separately after the caption
and title fixes, on the exact zip attached to the v5.6.3 release:

- **CI, four OS jobs, packaged app:** Windows x64, Linux x64, macOS x64 and macOS arm64
  each ran the real bundled backend and printed
  `electron self-test: health ok, page ok, port …` in run `43722389967`.
- **Windows portable, run here:** `ClipBlitzStudio.exe` from
  `ClipBlitzStudio-5.6.3-win-x64.zip` answered `/api/health` with
  `"version": "5.6.3"` in **7.3 s** on a warm run, opened the window titled
  **“ClipBlitz Studio — Cutting Desk”**, and stopped the backend when the app was
  killed (health went down). The cold first run of the same engine took **59 s** on
  this machine, which is why 5.6.3 waits four minutes instead of 60 seconds.
- **Resources in the package:** `resources/backend/ClipBlitzStudio-server.exe`,
  `resources/backend/bin/ffmpeg`, `ffprobe` and `yt-dlp.exe`, plus the web studio,
  plugin and logo. No Python, Node or WebView2 is needed on the target.
- **Not verified here:** a physical Mac or Linux machine (only the CI jobs), a signed
  Windows/macOS installer (the builds are unsigned), and a real Google OAuth upload
  (it needs the user's own Cloud project and verified `youtube.upload` scope).
