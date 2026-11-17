# GTA VI CLIPS INDIA — setup, 6-clip runbook, and the honest money math

Your channel already exists:

- **Name:** GTA VI CLIPS INDIA
- **Handle:** `@gta6_clips_official_justforfun`
- **Joined:** 16 Nov 2026

This file is the exact setup I would do on that channel. I cannot click inside your
Google account; everything that needs your login is marked **[YOU]**.

Two files are ready for the channel:

- `docs/channel/gta6-india/avatar-1080.png`
- `docs/channel/gta6-india/banner-2560x1440.png`

They are original artwork with text, not Rockstar's logo or screenshots. The current
avatar in your screenshot is official GTA VI artwork. Replace it. Using official art
on a fan channel is a copyright/trademark risk and it makes the channel look official
when it is not.

---

## 0. Read this before you upload anything

There are three separate problems, and only one of them is technical:

1. **The app can make 6 clips.** That part is built.
2. **YouTube may not monetise six re-uploaded stream clips a day.** Reused content is
   a monetisation problem even when the upload succeeds.
3. **The streamer owns the footage.** Without permission, a clip can be claimed,
   muted, blocked, or struck. A strike can end the channel before the first ₹100.

The honest fastest path is:

**your own gameplay + your own commentary**, or **a streamer who has explicitly given
you permission**, and **fewer, better clips**. Six a day is technically possible; it is
not the thing I would do in week one.

---

## 1. Fix the channel identity first (10 minutes) **[YOU]**

### Name and handle

"official" in the handle is the one thing I would remove. You are not official, and
impersonation is a separate policy risk. A fan channel is fine; pretending to be the
brand is not.

In **YouTube Studio → Customization → Basic info**:

- **Name:** `GTA VI CLIPS INDIA` is okay as a fan name if the banner says **Unofficial**.
  If you want a safer long-term name: `Clip Desk India`, `GTA Clip Desk`, or
  `GTA VI Clip Desk`.
- **Handle:** change `@gta6_clips_official_justforfun` to something without "official":
  `@gta6clipsindia`, `@gta6clips.india`, `@gta6clipsdaily`, `@gta6clipdesk`.
  Handles can be changed, subject to availability and YouTube's change limit. Pick one
  and keep it.
- **Disclaimer in the description** (must be visible, not hidden):
  ``

Do not use the GTA VI logo, the official key art, or the "VI" logo as your avatar.
Text-only is the version that survives.

### Avatar and banner **[YOU]**

**Customization → Branding:**

- Upload `docs/channel/gta6-india/avatar-1080.png`.
- Upload `docs/channel/gta6-india/banner-2560x1440.png`.
- Check the banner on phone: YouTube crops it. The title and the "Unofficial" line must
  survive the phone crop.

### Description **[YOU]**

```text
```

If you do **not** have permission for a clip, do not write "used with permission" for
that clip. Put the credit and permission note in the video description instead.

### Links and contact **[YOU]**

**Customization → Basic info → Links:** add the ClipBlitz GitHub or your Instagram
only if it is real. Do not add a dead link. Add a business email you actually check.

---

## 2. Tell YouTube who this is for (the settings you asked about)

YouTube does **not** give you an organic "show this to 18–24-year-old Indian gamers"
box. The algorithm learns from who clicks and watches. What you can actually set:

### Channel settings **[YOU]**

**YouTube Studio → Settings → Channel → Basic info:**

- **Country of residence:** India.
- **Keywords:** .
  Keywords are a small signal; do not stuff unrelated games.
- **Contact info:** your email.

**Settings → Channel → Advanced settings:**

- **Audience:** **No, this channel is not made for kids.** GTA VI is mature content.
  Do not mark it "made for kids" to get more reach; that is a compliance problem.
- **Age restriction:** do not try to dodge it. If a clip is violent/graphic, YouTube
  may age-restrict it. That is normal for GTA; it lowers reach and ads. Choose clips
  that are funny/skillful rather than graphic.
- **Channel URL / handle:** as above.

### Upload defaults **[YOU]**

**Settings → Upload defaults:**

- **Visibility:** **Private** or **Unlisted** for the first month. Never Public on the
  first automated run.
- **Category:** Gaming.
- **Video language:** Hindi or English — pick the language you actually speak/write.
  Add captions if you can.
- **Title template:** leave blank. Do not auto-prefix every title with the channel name.
- **Description template:**

```text
[One line of context]

Source: [creator/channel] — [own gameplay / used with permission].
Unofficial GTA VI fan channel. No affiliation with Rockstar Games.

#GTA6 #GTAVI #Gaming #Shorts
```

- **Comments:** **Hold potentially inappropriate comments for review.** GTA chats get
  spicy; this protects the channel.
- **License:** Standard YouTube License unless you have a reason to use Creative
  Commons.

### What "audience" means in practice

- Make **Hindi + English** titles/descriptions if your audience is Indian.
- Put the **hook in the first 2 seconds** and the **context in the title**, not in a
  long intro.
- Post around **7–11 p.m. IST**, when Indian gaming viewers are active; confirm with
  your own analytics after two weeks. Do not assume; measure.
- Use **Shorts** for reach and **one longer compilation** per week for watch time.
- If you later pay for promotion, **Google Ads** is where you can choose audience
  (India, gaming, 18–34). Organic YouTube has no such targeting box. Do not pay for
  ads before the clips retain viewers.

---

## 3. Rights: the part that decides whether this works

You have three legitimate sources:

1. **Your own GTA VI gameplay.** Best. Record on your console/PC, add your own
   commentary. Rockstar generally allows gameplay videos; check Rockstar's current
   fan-content policy.
2. **A streamer who explicitly permits clipping.** Many streamers have a `!clips`
   command, a Discord permission, or a clip policy. Ask in writing. Keep the reply.
   Credit them in the description and pinned comment.
3. **Transformative commentary/analysis.** A clip with your own reaction, analysis,
   editing and context can be fair use in some countries, but **fair use is a legal
   defence, not a YouTube button**, and it does not guarantee monetisation. Do not
   rely on it for six uploads a day.

What not to do:

- Do not download a streamer's VOD and upload six raw clips with auto titles.
- Do not remove watermarks or logos.
- Do not use "official" in the handle while using their footage.
- Do not use copyrighted music; mute it or replace it with the YouTube Audio Library.
- Do not buy subscribers/views; that is a policy violation and can end the channel.

**Reused content:** YouTube's monetisation review looks for significant original
commentary, critique, analysis or educational value. Six raw stream clips a day is
exactly the pattern that gets denied. If you want to monetise, add your voice and a
reason to watch **your** version: reaction, tactical breakdown, "what just happened",
or a compilation with a thesis.

The app clips **source footage**. It does not add a voiceover. That is the gap you must
fill if you are using someone else's stream.

---

## 4. Install and connect ClipBlitz v5.7.0 **[YOU]**

Download the Windows x64 setup from:

`https://github.com/agra-aarav15/clipblitz-ai-shorts/releases/tag/v5.7.0`

File: `ClipBlitzStudio-5.7.0-win-x64-setup.exe`

- It is unsigned, so SmartScreen may warn once: **More info → Run anyway**. Only do
  this for the file from that release page.
- Data lives in `%APPDATA%\ClipBlitz Studio`. Clips, chat logs and OAuth token stay on
  your PC.
- Check free disk space. Six clips a day is small, but recordings/chat logs and old
  renders add up. The app data drive on your PC is low; delete old clips weekly.

### Connect YouTube (one time)

1. Go to `https://console.cloud.google.com/` and create/select a project.
2. **APIs & Services → Library → YouTube Data API v3 → Enable.**
3. **OAuth consent screen:** External. Add your Google account under **Test users**.
4. **Credentials → Create credentials → OAuth client ID → Desktop app.** Copy the
   client ID and secret.
5. In ClipBlitz: **Connect → YouTube**, paste the ID and secret, **Test & save**.
6. Copy the **redirect URI** shown by the app into the OAuth client's **Authorized
   redirect URIs**. It is usually
   `http://localhost:4300/oauth/youtube/callback`; use the exact string on screen.
7. Press **Connect YouTube** and approve the upload scope **with the channel account**.
8. While the OAuth app is in **Testing**, Google expires the refresh token about every
   seven days. Re-connect, or publish the app.

**Quota:** an upload costs about 1,600 units of the default 10,000/day. Six uploads =
9,600 units, leaving almost nothing for other API calls. Use **5** automated uploads,
or upload the sixth manually in YouTube Studio. If you need more, request a quota
increase in Google Cloud; do not create multiple projects to dodge the limit.

---

## 5. The exact 6-clip live setup

In ClipBlitz → **Live**:

| Setting | Value |
|---|---|
| URL | `https://www.twitch.tv/<creator-with-permission>` or a YouTube live URL |
| Before spike | **25** seconds |
| After spike | **15** seconds |
| Max clips | **6** (use 5 if you also use other API calls) |
| YouTube privacy | **Private** for the first week, then **Unlisted** |
| When a spike ends | **Post first** for a launch stream; **Wait for quiet chat** if CPU matters |
| Auto-post | **On**, only after OAuth is connected |
| Rights box | **On only after you have permission** |

Then press **Start watching before the stream begins**. Keep the app open.

**PC settings:**

- Windows → Power & sleep → **Sleep: Never** while the watcher runs. A sleeping PC
  misses the moment.
- Keep the charger connected.
- Do not close the lid.
- Leave the app running; it resumes persisted sessions after a restart, but Twitch has
  no chat replay, so a shutdown during a Twitch stream loses the missed chat.

**What "six clips" means:** the app ranks spikes, keeps the top six windows, downloads
only those sections, renders 1080×1920 with audio, and (if enabled) uploads them. It
does **not** guarantee six interesting clips. A quiet stream may produce zero. That is
honest, not a bug.

### Do not publish all six at once

Even with six files, a brand-new channel publishing six near-identical clips in ten
minutes looks like spam. Do this instead:

- Auto-upload as **Private**.
- Review each clip: first 2 seconds, context, audio, no slurs, no copyright music.
- Publish **2 per day** at 8 p.m. and 10 p.m. IST, or schedule them in YouTube Studio.
- Keep the other four for the next days. Six clips should cover **three days**, not one
  hour.

If the app uploads as Private, schedule them in **YouTube Studio → Content → Schedule**.
Do not switch a private upload to Public until you have watched it once with sound.

---

## 6. Six clip slots (fill these after watching the stream)

These are **slots**, not invented events. Watch the stream/clip before you publish.

| # | Slot | Title formula | Thumbnail (3 words max) | Why it works |
|---|---|---|---|---|
| 1 | First minute | `The first 10 seconds of GTA VI` | `FIRST 10` | Launch curiosity; only if the footage is yours/permitted |
| 2 | Chase / wanted | `This chase went wrong in 8 seconds` | `WANTED` | Complete thought, fast payoff |
| 3 | Funny NPC | `This NPC stole the whole stream` | `NPC GOLD` | Self-contained humour |
| 4 | Graphics | `The one frame everyone will screenshot` | `LOOK AT THIS` | Visual payoff; no spoiler |
| 5 | Skill | `He did not see that coming` | `NO WAY` | Reaction; keep it non-graphic |
| 6 | Chat spike | `The chat lost it at this moment` | `CHAT LOST IT` | Uses the live-radar proof |

Rules for each:

- 15–60 seconds. Cut the dead air at the start.
- First line confirms the title. Do not open with "hey guys".
- Captions on; mute copyrighted music.
- Credit the creator and permission in the description.
- Pinned comment: `Source: [creator]. Clipped with permission.`
- If you added commentary, say so in the title/description; that is the transformative
  part.

### Description template

```text
[One line: what happens and why it matters.]

Source: [creator] — [own gameplay / used with permission].
Follow the creator: [link]
Unofficial GTA VI fan channel. Not affiliated with Rockstar Games.

#GTA6 #GTAVI #Gaming #Shorts
```

### Tags (10–15, disambiguation only)

`GTA 6`, `GTA VI`, `GTA 6 clips`, `GTA 6 shorts`, `GTA 6 India`, `GTA VI gameplay`,
`gaming clips`, `Twitch clips`, `live stream clips`, `GTA 6 launch`, `GTA 6 reaction`.

Tags are weak. The title, first two description lines and the first two seconds matter
more.

---

## 7. The first-week schedule

| Day | What to publish | Why |
|---|---|---|
| Day 1 | 2 clips (Private → review → Public 8 p.m./10 p.m.) | Test the pipeline without spam |
| Day 2 | 2 clips; check retention | Keep the best, delete/rework the weak |
| Day 3 | 1 clip + 1 Short cut from the best | Start a series |
| Day 4 | 2 clips; reply to every comment | Comments teach the next clip |
| Day 5 | 1 compilation (3–5 clips + your commentary) | Longer watch time |
| Day 6 | 2 clips; test a Hindi title on one | Learn the audience language |
| Day 7 | Review analytics; keep one format; plan next week | One fix, not twenty |

Do not post 42 clips in week one. YouTube needs a reason to recommend the channel; a
consistent, improving series is that reason.

---

## 8. The money math (read this before you expect ₹1,000)

**YouTube Partner Program (ads):** as of 2026, the usual threshold is **1,000
subscribers + 4,000 valid public watch hours in 12 months**, or **10 million valid
public Shorts views in 90 days**. Check YouTube's current eligibility page for your
country before you plan around it.

**Fan funding at 500 subscribers:** YouTube has a lower tier in some countries for
channel memberships, Supers and Shopping (typically 500 subscribers, 3 public uploads
in 90 days, and 3,000 watch hours or 3 million Shorts views). Availability varies;
check your Studio.

**Shorts ad revenue** is shared through the Shorts pool and depends on music licensing,
viewer country and advertiser demand. India short-form RPM is generally low compared
with long-form. ₹100–₹1,000 is a **milestone after monetisation and meaningful views**,
not a first-night result. Anyone who promises it is selling you something.

**Faster non-ad money (still not guaranteed):**

- Affiliate links for games/gear you actually use (disclose).
- A sponsor for a series once you have a consistent audience.
- Channel memberships/Supers after the 500-sub tier.
- Selling an editing/clipping service — often more reliable than ad revenue at the
  start.

**What not to do:** buy views/subs, reuse six clips a day with no commentary, use
copyrighted music, or promise "first clip" you cannot prove. Those are the fastest ways
to lose the channel.

**A realistic first goal:** 30 days, 20–30 reviewed clips, 100 subscribers, and one
format that retains. Money is a later milestone. Your parents will be prouder of a
channel that survives than one that gets struck in week one.

---

## 9. Permission message you can copy

Send this in the streamer's Discord, business email, or chat (not as spam):

```text
Hi [name], I run a small GTA VI clips channel for Indian viewers. I would like to cut
2–3 short moments from your stream, credit you in the title/description and pin your
channel link. I will not re-upload the full VOD, and I will remove anything you ask me
to remove. Is that okay? If you have clip rules, please point me to them.
```

Keep the reply. If they say no, do not use the footage. A "yes" in a public chat is
better than nothing; a DM/email is better still.

## 10. Checklist

- [ ] Replace official GTA art with `docs/channel/gta6-india/...` **[YOU]**
- [ ] Remove "official" from the handle **[YOU]**
- [ ] Set channel country India, keywords, contact email **[YOU]**
- [ ] Set audience: **not made for kids** **[YOU]**
- [ ] Set upload defaults: Private, Gaming, comments held **[YOU]**
- [ ] Get written permission from the streamer, or use your own gameplay
- [ ] Connect YouTube OAuth; test with one Private upload
- [ ] Set Live: 25 / 15 / 6 clips / Post first / Private / rights on
- [ ] Disable sleep; keep PC on; start before the stream
- [ ] Review the first 6 clips; publish 2/day, not 6 at once
- [ ] Add credit, permission, disclaimer, captions
- [ ] Check retention after 48 hours; change one thing
- [ ] Do not buy engagement; do not upload unpermitted footage

---

## 11. What I can do next

I can:

- generate six title/thumbnail/description packages once you send the six clips or their
  transcripts;
- review the channel page text and banner for policy/readability;
- make a 30-day calendar for your actual niche;
- help you write a permission message to a streamer;
- audit retention once you have exports.

I cannot:

- create the channel or click Google consent for you;
- grant rights to someone else's stream;
- guarantee monetisation or ₹100–₹1,000;
- make six raw re-uploads eligible for the Partner Program.

**Ship it, or change it?** Send me the first stream you have permission to clip, and I
will build the six packages around the actual moments instead of placeholders.
