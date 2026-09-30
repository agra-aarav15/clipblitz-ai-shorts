---
name: cut-clips
description: Cut vertical shorts out of a long video (a local file, a YouTube URL or a direct media link) using the local ClipBlitz Studio engine. Use when the user hands over a video, a recording, a podcast episode, a livestream VOD or a YouTube link and asks for clips, shorts, highlights, "cut 3 clips", "make me some tiktoks from this", or similar.
---

# Cutting clips with ClipBlitz

`cut_clips` runs the real ClipBlitz engine locally and returns finished vertical
`.mp4` files (1080x1920 with burned-in captions), not suggestions or timestamps.

## How to call it

    cut_clips(video="/abs/path/episode.mp4", clips=4)

- `video` — a path or an `http(s)` URL. A URL is fetched with the bundled yt-dlp.
- `clips` — how many to cut, 1-8. The default is 3; ask the user if it matters and
  they did not say.
- `engine` — `b2` (default), `prox`, or `both`.
- `rights` — only when the user has stated their rights out loud.

A job takes about as long as the video is long, and longer on a slow machine. The
tool waits; if it returns a job id instead, poll `job_status` every 30-60 seconds.

## What you get back

Each clip carries a title, a spoken hook line, a score, its window in seconds, the
`transformative_work` the render applied, and the absolute path to the `.mp4`.
`verdict`, `reason`, `factors` and the `risk` block are the engine's own honest
output — quote them, do not invent anything past them.

## The two things that are not negotiable

- **Rights.** Anything the user did not make needs permission, a licence, or a
  genuine transformative purpose. If a source looks third-party, say so and ask.
  Do not fill in the `rights` field to get past anything.
- **No claim immunity.** `risk_report` lists measured flags (third-party-looking
  music spans, where the source came from, missing licence, thin transformative
  work). It never means "safe from a copyright strike", and it must never be
  described that way to the user.

## Reporting back

Give the user, per clip: the file path, title, window, score and the reason. Mention
the risk flags that apply. Then stop — publishing is a human decision made in the
studio, and this plugin has no publish tools on purpose.
