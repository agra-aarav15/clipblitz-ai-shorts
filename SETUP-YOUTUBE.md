# SETUP-YOUTUBE.md — connect YouTube auto-upload to ClipBlitz (one-time, ~15 minutes)

Do this once. After it, every clip ClipBlitz renders can upload itself — with title,
description and hashtags — completely automatically.

## 1. Create the Google Cloud project
1. Go to https://console.cloud.google.com/ and sign in
2. Top bar → project dropdown → **New project** → name it `clipblitz` → Create

## 2. Enable the YouTube API
1. Menu ☰ → **APIs & Services → Library**
2. Search **YouTube Data API v3** → **Enable**

## 3. Configure the consent screen
1. **APIs & Services → OAuth consent screen**
2. User type **External** → Create
3. App name `ClipBlitz`, your email → Save
4. **Audience → Test users → + Add users** → add your own Gmail (this lets YOU upload while the app is unverified)

## 4. Create the OAuth credentials
1. **APIs & Services → Credentials → + Create credentials → OAuth client ID**
2. Application type: **Web application**
3. **Authorized redirect URIs → add exactly:**
   `http://localhost:4301/oauth/youtube/callback`
4. Create → copy the **Client ID** and **Client secret**

## 5. Paste them into ClipBlitz
Open `E:\clipping\clipblitz\.env` and fill:
```
CB_YT_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
CB_YT_CLIENT_SECRET=GOCSPX-xxxxxxxx
```
Restart ClipBlitz (close the window, run `python run.py` again).

## 6. Connect
ClipBlitz → **Connect & Post** tab → **Connect YouTube** → sign in with the Google account
that owns your channel → allow "Upload videos".
The tab says "✅ YouTube connected!" — done. The status chip shows your channel name.

## Notes
- Test-mode quota: ~6 uploads/day (YouTube's default 10,000 units ÷ 1,600 per upload).
  To lift it later: publish the OAuth app (verification) or request more quota.
- Videos upload with the privacy you pick in the Studio (Public / Unlisted / Private).
- Your token lives only in `data/social/youtube.json` on your machine (gitignored).
