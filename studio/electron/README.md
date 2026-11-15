# ClipBlitz Studio — Electron desktop shell

This folder is the native shell. It does not contain the cutting engine; it starts the
bundled Python backend and shows the existing studio in Electron's Chromium.

```
Electron (main.js)
  └─ picks a local port, starts backend/ClipBlitzStudio-server
      └─ waits for /api/health
          └─ BrowserWindow → http://127.0.0.1:<port>/
```

The packaged app never opens a terminal and never opens your default browser for the
studio. The only external browser use is Google's OAuth consent, by design: Google
blocks embedded webviews for sign-in.

## What ships

| OS | Installer | Backend |
|---|---|---|
| Windows x64 | `ClipBlitzStudio-5.6.3-win-x64-setup.exe` (NSIS), `.zip` portable | `resources/backend/ClipBlitzStudio-server.exe` |
| macOS x64 / arm64 | `.dmg` and `.zip` | `Contents/Resources/backend/ClipBlitzStudio-server` |
| Linux x64 | `.AppImage` and `.deb` | `resources/backend/ClipBlitzStudio-server` |

Every package carries its own Python runtime, ffmpeg, ffprobe, yt-dlp, web UI, plugin
and the brand assets. A fresh machine needs no Python, no Node, no ffmpeg, no Ollama.

## Develop

From `studio/` (Python source) run the backend yourself, then start Electron against
it:

```bash
python run.py 4300
cd electron
npm install
CB_BACKEND= npm start          # dev: Electron spawns `python run.py` automatically
```

For a **built backend** without the full installer:

```bash
CB_BACKEND="$PWD/backend/ClipBlitzStudio-server" npx electron . --self-test
```

`--self-test` starts the backend, checks `/api/health` and the page, prints one line,
and exits. It opens no window, which is what CI uses.

## Build (only in CI)

The build is deliberately not done on the owner's C: drive. The `electron` workflow
builds the backend with PyInstaller on each OS, stages `web/`, `assets/`, `plugin/`,
downloads static ffmpeg/ffprobe/yt-dlp for that platform, then runs electron-builder.

```bash
npm ci
npm run icons
npm run prepare-backend
npm run dist -- --win --x64        # or --mac --arm64 / --linux --x64
```

## Signing (important on fresh machines)

- **Windows:** the installer is unsigned. SmartScreen shows "Unknown publisher";
  choose *More info → Run anyway*. A commercial release should use an EV/OV code
  signing certificate.
- **macOS:** unsigned apps are blocked by Gatekeeper. For a real public release you
  need an Apple Developer ID, hardened runtime, notarization and stapling. The CI
  artifact is an unsigned developer build; on a fresh Mac the user must allow it in
  System Settings → Privacy & Security. This is an OS security rule, not a ClipBlitz
  bug. Linux AppImage needs `chmod +x` (or the `.deb`).
- The app is ad-hoc/unsigned until certificates are configured; do not distribute it
  as a signed product before that.

## Data and privacy

`CB_DATA` is set to Electron's `userData` folder:

- Windows: `%APPDATA%\ClipBlitz Studio`
- macOS: `~/Library/Application Support/ClipBlitz Studio`
- Linux: `~/.config/ClipBlitz Studio`

Clips, jobs, provider keys, the YouTube token and `backend.log` live there. The app
bundle is read-only on macOS; nothing is written inside it.

## YouTube OAuth

Use a Google Cloud **Desktop app** OAuth client with the YouTube Data API v3 enabled.
Register this exact redirect URI (the app prefers port 4300):

```
http://localhost:4300/oauth/youtube/callback
```

Paste the client ID and secret into **Connect → Publishing**, press Save, then
Connect. The system browser opens Google's consent page; the backend receives the
loopback callback. No browser cookies are read, no web-chat scraping, no shared
refresh token. Until Google verifies the app, add test users in the OAuth consent
screen; the 10,000 units/day project quota is shared by every install using that
client (roughly six uploads/day).

## Not included

- A Gemini web-chat proxy. It is not an API, it breaks whenever Google changes auth,
  and it is built to evade terms and bans. Use the Gemini API or Vertex AI with the
  project you own, or a local model.
- Code signing certificates. Bring your own; the build supports them through the
  standard electron-builder environment variables.
