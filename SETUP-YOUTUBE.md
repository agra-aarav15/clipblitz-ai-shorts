# SETUP-YOUTUBE.md — connect YouTube auto-upload to ClipBlitz (one-time, ~15 minutes)

Do this once. After it, every clip ClipBlitz renders can upload itself — with title, description
and hashtags — automatically.

**You will not edit any file by hand.** Every value goes into the Connect screen inside the app, and
the app tests each one live. Keys hot-reload, so **there is never a restart step**.

---

## 1. Create the Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in with the Google account that owns your
   YouTube channel.
2. Top bar → project dropdown → **New project** → name it `clipblitz` → **Create**.

## 2. Enable the YouTube API

1. Menu (☰) → **APIs & Services → Library**.
2. Search **YouTube Data API v3** → **Enable**.

*(In ClipBlitz you can click **Enable YouTube Data API** on the Connect screen to jump straight to
this page.)*

## 3. Configure the consent screen

1. **APIs & Services → OAuth consent screen** (Google now calls this **Google Auth Platform**).
2. User type: **External** → **Create**.
3. App name `ClipBlitz`, your email → **Save**.
4. **Audience → Test users → + Add users** → add your own Gmail address. This is what lets *you*
   upload while the app is still unverified — and it is the fix for the most common error
   (`org_internal`, see Troubleshooting).

## 4. Create the OAuth credentials

1. **APIs & Services → Credentials → + Create credentials → OAuth client ID**.
2. Application type: **Desktop app** *(recommended — the ClipBlitz wizard assumes this)*.
   **Web application** also works if you prefer it — see the note below.
3. **Authorized redirect URIs → add exactly:**

   ```
   http://localhost:4301/oauth/youtube/callback
   ```

   Copy it from the Connect screen's **copy** button so it cannot drift.

4. **Create** → copy the **Client ID** (`...apps.googleusercontent.com`) and **Client secret**
   (`GOCSPX-...`).

> **Desktop app vs Web application — which one?**
> - **Desktop app** (recommended): simplest, no redirect-URI requirement in some flows. ClipBlitz
>   still uses the URI above, so add it if Google shows the field.
> - **Web application**: requires the redirect URI above to be registered — this is the flow most
>   Google tutorials describe.
> Either is accepted. Do not pick *TV* or *Restricted* — uploads will fail with
> `youtubeSignupRequired`.
>
> Note: if you use a port other than 4301 (via `CB_PORT`), the redirect URI must match it exactly.

## 5. Paste them into ClipBlitz (inside the app)

1. Open ClipBlitz → **Connect** screen.
2. Find the **API keys** card → **YouTube Data API** row.
3. Paste the **Client ID** and **Client secret**, then press **Test & save**.
   The chip turns to *saved* and the app stores them — **no file editing, no restart**.
   (Equivalent if you prefer a file: put `CB_YT_CLIENT_ID=` and `CB_YT_CLIENT_SECRET=` in `.env`
   — the app reads it live either way.)

## 6. Connect

1. Still on the Connect screen, press **Connect YouTube**.
2. Sign in with the account that owns your channel → allow **Upload videos**.
3. The status chip shows your channel name and the readiness checklist turns green — done.

If anything is off, press **Diagnose**: it prints a five-step chain (keys present → redirect URI
registered → consent completed → token works → upload quota) and tells you exactly which step is
missing and how to fix it.

## Notes

- **Quota:** the free tier allows roughly **6 uploads/day** (YouTube's default 10,000 units ÷ 1,600
  per upload). To lift it, publish the OAuth app (Google verification) or request more quota.
- Videos upload with the privacy chosen in the Studio (Public / Unlisted / Private).
- Your token lives only in `data/social/youtube.json` on your machine (gitignored). It never leaves
  your computer except to talk to Google.
- ClipBlitz does not delete or modify anything on your channel — it only uploads new videos.

---

## Troubleshooting — the errors you can actually hit

**Error 403: `org_internal`** (on Google's consent page)
Your OAuth consent screen audience is **Internal** (organisation-only).
1. Google Cloud → **APIs & Services → OAuth consent screen** (a.k.a.**Google Auth Platform**).
2. **Audience** tab → User type: **External** → save.
3. **Audience → Test users → + Add users** → add your own Gmail address.
4. Press **Connect** again. No restart is needed.

**Error 400: `redirect_uri_mismatch`**
The registered redirect URI does not match.
Fix: **Credentials** → your OAuth client → **Authorized redirect URIs** → add exactly
`http://localhost:4301/oauth/youtube/callback` (use the Connect screen's **copy** button).
If you changed the port, register the matching URI instead.

**`access_denied` / “This app isn't verified”**
You are signed in with an address that is not listed as a test user. Add it in
**Audience → Test users**, then press Connect again.

**`youtubeSignupRequired`**
The project does not have **YouTube Data API v3** enabled, or the Google account has no YouTube
channel. Enable the API (step 2) and make sure you are signing in with the channel owner.

**Other gotchas**

- Client type must be **Desktop app** or **Web application** — never TV/Restricted.
- The consent code is single-use and expires in about 10 minutes. If it fails, press Connect again
  rather than reusing an old browser tab.
- If a clip posts to the wrong channel, sign out in Google and reconnect with the right account.

---

Related: [BEGINNER-GUIDE.md](BEGINNER-GUIDE.md) · [README.md](README.md)