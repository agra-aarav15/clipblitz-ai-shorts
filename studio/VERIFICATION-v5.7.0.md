# ClipBlitz Studio v5.7.0 — Live Chat Radar verification

This is the evidence for the live-stream path added in 5.7.0. It is deliberately
separate from the three-video ARGON proof in `VERIFICATION-v5.6.1.md`, which remains
the evidence for the normal long-video engine.

## What was tested

| Area | Result |
|---|---|
| YouTube live chat (public continuation) | **68–69 messages** persisted from Lofi Girl `4t4AQ15yj1M`; polling continued while the app watched |
| Twitch live chat (anonymous IRC) | **377 messages** persisted from `hasanabi` while live; display names, tags and timestamps parsed |
| Twitch DVR section | **36.6 s** downloaded while the channel was still live; no full-stream recording |
| Finished-stream YouTube replay | **4,497 messages** from `ArAxjdWSvk8` (Agenda-Free TV, 3,607 s) |
| Spike detection | **2 spikes** remembered from the 4,497-message chat with the default rules |
| Section download | `70.0–115.0 s` downloaded from the finished broadcast; the whole VOD was not fetched |
| Vertical render | **45.0 s, 1080×1920, audio present**, 10 MB, with a thumbnail |
| Restart / resume | Lofi session persisted at **67 messages**; after killing the server and starting it again the log said `live radar resumed 1 session(s)`, the status stayed `watching`, and the count advanced to **69** |
| Auto-post gate | With `auto_post=true` and rights false the clip is marked `waiting_for_rights`; with rights true but no OAuth it is `not_connected`. No upload was attempted in this run |
| Offline tests | `python scripts/test_live.py` → **42 passed, 0 failed** |
| Full offline suite | `test_argon` 123, `test_engines` 29 (+1 skipped), `test_learning` 28, `test_agent` 82, `test_trainer` 64, `test_rights` 62, `test_scout` 57, `test_clipbench` 44, `test_daily` 69, `test_social` 45, `test_quality` 35, `test_captions` 18, `test_titles` 5, `test_live` 42, `test_providers` 29 — **732 passed, 0 failed** (plus the separate marketplace suite: 94 passed) |

## Commands used

```bash
cd studio
CB_DATA=/tmp/cblive4 CB_LIVE_DEBUG=1 python run.py 4401
# POST /api/live/start with ArAxjdWSvk8
# then poll GET /api/live/ArAxjdWSvk8 until status=done
```

The debug log showed the continuation advancing:

```
[live] replay batch 1 actions=101 msgs=88 added=88 next=True
[live] replay batch 2 actions=48 msgs=44 added=44 next=True
[live] replay batch 3 actions=44 msgs=38 added=38 next=True
```

Two real bugs were found and fixed during this test:

1. **Replay actions were wrapped in `replayChatItemAction`.** The parser originally
   looked only at `addChatItemAction` and returned no messages. It now unwraps the
   wrapper and uses the exact `videoOffsetTimeMsec` of each replay action.
2. **The replay loop never advanced `cont = nxt`.** It fetched the first page 200
   times and reported 88 messages. It now advances the continuation (and stops if a
   token ever repeats).

A third real bug appeared in the packaged path: `yt-dlp` was given
`--ffmpeg-location ""` when ffmpeg was found on `PATH`, so the section download failed
with `m3u8 download detected but ffmpeg could not be found`. The downloader now
resolves the real ffmpeg path with `shutil.which` before passing the directory. The
same fix is applied to caption downloads.

## What this does not prove

- **Not a live spike render on a busy chat.** The busy-chat proof is the finished
  YouTube replay; the Twitch run proved chat capture and DVR section download, but its
  chat did not produce a detected spike during the sample. The low-chat and post-first
  schedulers are covered by offline unit tests.
- **Twitch starts from the live DVR.** No full-stream recording is kept. A spike that
  falls outside the DVR window, or a Twitch stream that ends before a quiet-policy
  spike is rendered, cannot be recovered. Post-first is the Twitch default for that
  reason.
- **No real YouTube upload.** OAuth is not connected on this machine, so the upload
  path was exercised only through its error gates. The Connect flow and the upload
  call are the existing 5.6.x social path, tested by `test_social.py`.
- **No physical macOS or Linux runtime check in this pass.** Those packages are built
  and self-tested in GitHub Actions; they are not run on physical hardware here.
- **Replay is not guaranteed.** YouTube can withhold the replay after a stream ends;
  the session records `replay_error` and the UI says the chat was unavailable. Twitch
  has no replay path in this build.
- **DVR retention is not guaranteed.** A spike older than the stream's DVR window can
  fail to download. The session records the failure instead of silently dropping it.
- **The clips in this document were not published.** The rights gate was left closed
  and no channel was created.
