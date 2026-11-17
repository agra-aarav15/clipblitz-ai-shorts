# ClipBlitz launch week — a real plan from the two reels

I watched both reels and opened the bundle you sent. The bundle is a **pointer pack**,
not a working stack: its zip contains `README.md`, `instructions.txt` and
`aistorehub.json`; it tells you to clone `yt-dlp`, `youtube-transcript-api`,
MoneyPrinterTurbo, `AI-Youtube-Shorts-Generator`, `claude-youtube` and
`youtube-agent-skill`. The useful part is the MIT-licensed
[`youtube-agent-skill`](https://github.com/Jakeschincariol/youtube-agent-skill): its
hook scorer, title/thumbnail linter, week planner, SEO rules and Shorts rules are real
Python and markdown, not a landing page.

This plan uses those tools directly on ClipBlitz's real evidence. It is a **launch
plan**, not a promise of virality and not a claim that a channel can run itself.

## The one fix (yt-audit)

**Publish one anchor a week.** The channel does not need seven uploads; it needs one
video worth watching, one cheap follow-up, and three Shorts cut from the anchor. A
channel that posts daily for a week and disappears is worse than one that ships one
honest anchor every week.

The second fix is packaging: **the first 15 seconds must confirm the title**. The most
common leak is a hook that introduces the channel instead of paying off the click.

## Positioning

**ClipBlitz — the live clipping desk.** Long video in; the moment the room reacts out.
Not "another AI editor". The differentiator is the part the reels both point at:

> The clip is not the spike. The clip starts **25 seconds before** the spike, and the
> first usable version is rendered while the moment is still current.

Audience: streamers, editors, and small channel operators who already clip, but lose
the moment waiting for a VOD. Promise: a measured window, a vertical file, an optional
post — with a rights gate. Never promise "first every time"; that is not knowable.

---

## Week 1 calendar (Nov 18–24, 2026)

One anchor, one cheap follow-up, three Shorts. Five uploads, not seven. Times are
placeholders: use **your own YouTube Studio analytics** for the best slot; do not
assume Tuesday at 18:00.

| Day | Format | Working title | The one-sentence promise | Already exists? |
|---|---|---|---|---|
| Tue 18 | Short | The clip starts 25 seconds before the spike | Show the window, not just the burst | Yes — app UI recording |
| Wed 19 | **Anchor** | You're clipping the spike. Start 25 seconds earlier. | A complete live-clipping workflow, with the exact window and settings | Script below |
| Thu 20 | Cheap | 4,497 messages showed me where the clip was | The chat log is the edit decision list | Real fixture: `ArAxjdWSvk8` |
| Fri 21 | Short | One setting decides if you post first or last | Post-first vs quiet-chat rendering | App setting |
| Sat 22 | Short | Why your Twitch clip disappeared | Twitch DVR is not a recording; here is the limit | Real DVR test |
| Sun 23 | Cheap / optional | Stop downloading the whole stream | Section download from the live DVR | `yt-dlp --download-sections` |

**If the week goes wrong, drop first:** the optional Sunday upload. **Never drop:** the
anchor and its three Shorts. That is the whole week.

### Why these days

- Tuesday Short seeds the idea before the anchor.
- Wednesday anchor is the one you spend real time on.
- Thursday cheap reuses the anchor's strongest fact (4,497 messages).
- Friday/Saturday Shorts are cut **from the anchor**, not written from scratch.
- Sunday is optional; a missed Sunday is not a failed week.

---

## Anchor script (Wednesday)

**Runtime target:** 4–5 minutes at ~150 words per minute. Do not pad to 8.

**Title:** `You're clipping the spike. Start 25 seconds earlier.` — 52 chars,
**98/100** with the skill's `title.py`.

**Thumbnail words:** `BEFORE THE BURST` — three words, no title duplication.
Background: your own Live tab, a visible spike card, a 25 s arrow. Palette `#050505`,
`#ff5a1f`, white. At feed size the three words must survive; no face required.

**Hook — winner from `hookscore.py`:**

> You are clipping the spike. The clip starts 25 seconds before it.

- Score: **57 / 100, WORKABLE** (the scorer is deliberately harsh; it is a reason to
  look again, not a prophecy).
- Formula: **The Mistake** — “You are clipping…” names the error.
- Failure to avoid: do not answer the curiosity in the same sentence. Let the next
  line carry the turn.

**Beat sheet** (mark what is on screen, not just what is said):

| Time | Spoken | On screen |
|---|---|---|
| 0:00–0:12 | “You are clipping the spike. The clip starts 25 seconds before it.” | Split: spike card, then the earlier frame; 25 s counter |
| 0:12–0:30 | “A spike is not one message. It is the room accelerating above its own median. Here is the actual burst.” | 5-second buckets, median line, threshold; no face |
| 0:30–0:55 | “The reaction starts before the typing. So the window is burst start minus 25, burst end plus 15.” | Window drags left; start/end labels |
| 0:55–1:30 | “On a real 60-minute stream, 4,497 messages produced this 45-second clip.” | Real fixture numbers; clip plays with audio |
| 1:30–2:20 | “There are two render policies. Post first cuts the live DVR immediately. Quiet chat waits until the last 20 seconds is below 35% of that spike's rate.” | Toggle between policies; CPU meter |
| 2:20–3:00 | “Twitch has no replay for the part you missed, and its DVR ends with the broadcast. That is why post-first is the Twitch default.” | Twitch card; DVR boundary |
| 3:00–3:40 | “The part nobody says: you need the rights. Tick the box, connect your own OAuth, choose unlisted for the first launch.” | Rights checkbox; Connect screen |
| 3:40–4:10 | “This is the clip it made. This is the description it wrote. This is the upload.” | Final clip, metadata, published/unlisted |
| 4:10–4:25 | “The build is in the repo. Connect your own channel. Ship one anchor this week.” | One CTA only |

**The turn** at 0:12 is mandatory: say what the video will do, then do it. No channel
intro, no “before we get started”, no subscribe pitch in the first 45 seconds.

**Payoff** at 4:10: show the actual file, dimensions and audio. Do not claim a result
you did not show.

**Close:** one ask. Do not ask for subscribe + comment + like + Discord in the same
breath.

---

## The cheap follow-up (Thursday)

**Title:** `4,497 messages showed me where the clip was` — 43 chars, **98/100**.

**Thumbnail words:** `ROOM KNEW` (three words, no title duplication).

**Hook options (from the 21 formulas):**

1. “4,497 messages. One 45-second clip. Here is the window.” — 43, WEAK; use only if
   the first two seconds show the number on screen.
2. “I found one clip in 4,497 messages. The window was 40 seconds.” — 42, WEAK.
3. “The chat knew before I did.” — short, curiosity, but no number; pair with a
   large `4,497` on screen.

**Shape:** 2–3 minutes. Show the chat log, the median, the one spike, the window, and
the final clip. This is a **data teardown**, not a tutorial. The anchor already taught
the workflow; this proves it on a real log.

**Two description lines (above the fold):**

```text
4,497 live-chat messages, one 45-second clip. This is the exact window the chat chose.
The source is a public news stream used as a test fixture; no upload was made.
```

**Three search queries this should win:**

- `how to find viral moments in live chat`
- `youtube live chat clip timestamp`
- `clip a live stream without watching the vod`

The title and first two description lines contain **live-chat**, **clip** and
**messages**; that is the query test.

---

## The three Shorts (cut from the anchor, not written separately)

Each gets a **new first line** because the anchor's line assumes context.

| Short | New first line | On-screen first two seconds | Loop |
|---|---|---|---|
| The 25-second window | “Your clip starts after the reaction.” | `25s EARLIER` | Last line: “the burst is the proof, not the start” → first line answers |
| Post first vs quiet chat | “One setting decides if you post first or last.” | `CPU OR SPEED` | Last line: “pick the trade-off” → first line asks which |
| Twitch DVR | “Why your Twitch clip disappeared.” | `DVR CLOCK` | Last line: “the DVR is not a recording” → first line asks why |

**Short rules used:** 20–55 seconds; opens on a complete thought; has a turn; ends on a
line; vertical framing note — the spike card and the 25 s counter must both survive a
9:16 crop.

---

## Thumbnail briefs (make these yourself; do not use footage you do not own)

All thumbnails are 1280×720, readable at 320×180.

| Video | Background | Three words | Accent | What must survive at feed size |
|---|---|---|---|---|
| Anchor | Your own Live tab, dark, one orange spike line | BEFORE THE BURST | 25 s arrow | The words and the arrow; not the tiny chat |
| Cheap | Your own chat log, numbers large | ROOM KNEW | `4,497` in white | The number and the three words |
| Short 1 | A frame from your own clip, face optional | 25s EARLIER | Orange bracket | The bracket and the number |
| Short 2 | Split screen: two render policies | CPU OR SPEED | Green/orange | The two-word contrast |
| Short 3 | DVR timeline with a cut line | DVR CLOCK | Red end-cap | The cut line |

Do not put the title on the thumbnail. The thumbnail says what the title does **not**.

---

## SEO package for the anchor

**First two lines:**

```text
Your clip starts 25 seconds before the spike. Here is the exact live-chat window,
the two render policies, and the rights gate before anything is posted.
```

**Tags (disambiguation only, 10–15):**
`live clipping`, `twitch clips`, `youtube live chat`, `clip live stream`,
`stream highlights`, `vertical clips`, `shorts`, `clipblitz`, `yt-dlp`,
`live stream editing`, `post first`, `content repurposing`.

Tags are a weak signal. Do not stuff unrelated game names.

**Description tail:**

```text
The 4,497-message fixture is a public news stream used for testing. No third-party
clip was uploaded. If you clip someone else's stream, get permission first.

ClipBlitz is self-hosted. Connect your own YouTube OAuth client; there is no shared
token in the build.
```

**Queries to win:**

- `clip twitch stream live`
- `how to clip youtube live stream`
- `live stream clip automation`
- `clip before the moment`

---

## GTA 6 launch appendix (only if that is your niche)

The reel's GTA 6 angle is a **timing** angle, not a licence. If you make GTA 6
content:

- Use **your own gameplay/commentary**, or a streamer's clip with **explicit
  permission**. Reposting launch-night streams without permission is a copyright and
  platform problem, not a growth hack.
- Do not say “first clip” unless you can prove it. Say “the clip is ready while the
  moment is current.”
- A launch-week series that respects rights:

| Day | Idea | Why it fits |
|---|---|---|
| Launch eve | “The 25 seconds before a launch stream explodes” | Teaches the window with your own UI |
| Launch day | “I clipped my own launch stream without watching the VOD” | Own footage; proves post-first |
| +1 | “What 4,497 chat messages look like at launch” | Data teardown; no gameplay repost |
| +2 | “Why Twitch DVR is not a recording” | Honest limitation; useful |
| +3 | “One setting for post-first vs quiet chat” | Product education |

If you do not have rights to the game/stream, make the series about **the tool**, not
the game. That is the version that survives a takedown.

---

## What the 11 skills did here

| Skill | Used for |
|---|---|
| `yt-script` | Five hooks, scored; picked the winner; beat sheet with on-screen marks |
| `yt-package` | Title + thumbnail as one pair; 98/100 and 80/100; no duplication |
| `yt-plan` | One anchor + one cheap + three Shorts; drop the optional Sunday |
| `yt-seo` | Two-line snippet, query test, 10–15 disambiguation tags |
| `yt-shorts` | Three Shorts with new first lines and loop points |
| `yt-audit` | One fix: one anchor per week, first 15 s confirms the title |
| `yt-viral` | Not run: it needs public niche data; do not invent outliers |
| `yt-retention` | Not run: needs your retention export; do not invent a curve |
| `yt-edit` | Not run: use it on the anchor transcript after recording |
| `yt-comment` | Not run: use it on the first 50 comments, then reply in your voice |
| `yt-chapters` | Not run: add chapters only when the anchor is over 8 minutes |

**Nothing here publishes.** These skills write; you publish. That is also true of the
ClipBlitz auto-post: it uploads only after you connect OAuth and tick the rights box.

---

## Launch checklist

- [ ] Create the channel and handle; upload `docs/channel/avatar-1080.png` and
      `docs/channel/banner-2560x1440.png`.
- [ ] Paste the description from `CHANNEL-SETUP.md`.
- [ ] Record the anchor with your own screen and your own source.
- [ ] Make the five thumbnails from the briefs; check at 320×180.
- [ ] Connect YouTube OAuth; keep the first upload **Unlisted**.
- [ ] Publish the Tuesday Short, then the Wednesday anchor, then the cheap follow-up.
- [ ] Cut the three Shorts from the anchor; new first line, loop point, vertical crop.
- [ ] Read the first 50 comments; one reply pattern, not fifty.
- [ ] After 7 days, export retention and run `yt-retention`; change one thing.

**Ship it, or change it?** If you want, send me the channel URL and the first three
retention exports; I will run the audit on real numbers instead of placeholders.
