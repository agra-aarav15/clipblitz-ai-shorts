# Verification - ClipBlitz Studio 5.5.0

5.5.0 changes how the app is set up and how it opens. The clipping engine is the
same ARGON build from 5.4.4; the tests below cover the new provider store, the
YouTube-caption path, the native window and the installer.

## What changed

### One Add Provider popup

- The fixed Groq / Gemini / Cerebras / OpenRouter / Together / OpenAI / Pollinations
  key grid is gone from Connect.
- **Providers** is now a list with one **Add provider** button. The popup has:
  name, base URL, API key (optional), exact model ID, context window, max output
  tokens, temperature, custom headers (JSON), **Use for speech-to-text** with its
  model ID, **Find models**, **Test connection**, save/delete/clear key.
- Entries live in `data/providers.json` (owner-only where the OS supports it), are
  ordered by the list, and are masked in every API response. The first time Connect
  is opened, the existing `.env` providers are imported once so no key is lost.
- If every provider is removed, the app runs in measured-only mode; it does not
  silently fall back to a leftover `.env` key.
- A provider marked for speech-to-text is the transcription target. This is how a
  user can point the app at Groq, OpenAI, or any compatible `/audio/transcriptions`
  endpoint without code changes.
- The Connect screen still has a separate **Publishing** card for the optional
  YouTube OAuth client; it is not part of the provider list.

### YouTube captions before speech-to-text

- `yt-dlp` now downloads manual and automatic captions (`json3`, VTT, SRT) with the
  video.
- `ingest.captions_for()` parses json3 word offsets (or distributes words inside
  VTT/SRT cues), builds the same segment/word shape the caption renderer uses, and
  is tried **before** any speech-to-text call.
- A thin or missing caption file falls back to STT. Local uploads are unchanged.
- This is the path that makes "install, paste a YouTube link, get clips" work
  without a Groq/Gemini key: no transcription request is made when the source has
  captions.

### Native desktop window

- One PyInstaller bundle now contains two EXEs:
  - `ClipBlitzStudio.exe` — a native WebView2 window (no console, no browser tab).
  - `ClipBlitzStudio-server.exe` — the server, MCP and CLI surface (console).
- The window starts the same local server in a background thread, opens the studio,
  and exits with the window. If the port is already serving ClipBlitz, it opens the
  existing instance. If WebView2 is unavailable it says so and falls back to the
  browser.
- `--self-test [port]` starts the bundled server, checks `/api/health` and the HTML,
  and exits. CI uses it to prove the window app's server and assets work without a
  desktop session; the visual window is a manual check.
- The agent plugin's `.mcp.windows.json` now points at
  `ClipBlitzStudio-server.exe --mcp`, so the windowless MCP path is preserved.

### Installer

- `ClipBlitzStudio-5.5.0-setup.exe` is built in GitHub Actions (Inno Setup), per-user,
  no admin prompt, Start Menu + optional desktop shortcut, uninstaller, bundled
  CPython/ffmpeg/yt-dlp/web/plugin, and it launches the window app.
- The workflow installs it into an empty folder, starts the installed server, checks
  `/api/health` (bundled ffmpeg), runs the installed window app's `--self-test`,
  uninstalls, and verifies the EXE is gone.

### PeakCut research

PeakCut (`haziqahmedqasmi/PeakCut`, MIT) was read as a source reference. We adopted
ideas, not code wholesale: transcript-first ingest, a single provider form with model
discovery, prompt-injection defenses for untrusted transcripts, token accounting, and
a cheaper one-pass proposal path is planned. ARGON's measured gate/repair/MMR remains
the engine; PeakCut's simpler AI-score selection was not adopted.

## Tests

```
test_argon           123 passed, 0 failed
test_captions         13 passed, 0 failed
test_providers        28 passed, 0 failed
test_engines          30 passed, 0 failed, 0 skipped
test_agent            82 passed, 0 failed
test_learning         28 passed, 0 failed
test_trainer          64 passed, 0 failed
test_rights           62 passed, 0 failed
test_scout            57 passed, 0 failed
test_clipbench        44 passed, 0 failed
test_daily            69 passed, 0 failed
test_social           45 passed, 0 failed
test_quality          35 passed, 0 failed
test_marketplace      77 passed, 0 failed
test_emotion          26 passed, 0 failed
test_reframe          17 passed, 0 failed
test_connect          13 passed, 0 failed
```

**813 passed, 0 failed.**

New coverage:
- `test_providers`: no-store/import-once, masking, advanced fields, key keep/clear,
  validation, order, enabled/disabled, empty store = offline, STT selection,
  Find Models and Test against a local OpenAI-compatible stub, UI contract.
- `test_captions`: json3 word offsets, VTT cues, sidecar discovery, thin-caption
  fallback, pipeline wiring, yt-dlp flags.
- `test_marketplace`: the plugin's Windows MCP command is the console EXE.

## Not done / honest limits

- **No Gemini Chat proxy.** The consumer Gemini web chat is not an API; proxying it
  would violate Google's terms, break on auth/CAPTCHA changes, and put one account
  behind every user. The app uses API keys (or no AI), not a chat proxy.
- **YouTube posting is not one-click for the public yet.** "Continue with Google"
  needs an OAuth client. For every user to click it, the app owner must create and
  verify a Google client with the YouTube upload scope, and the shared project's
  quota (~6 uploads/day at 10k units) is a hard limit until Google grants more.
  The current per-user OAuth and assisted-upload flows remain. This is not hidden.
- **Real-media runs were not repeated for 5.5.0.** The 5.4.4 real-media results
  remain valid for the unchanged ARGON engine. The YouTube-caption path is covered by
  parsers and a sidecar test, but a fresh link→clips run needs an owner-supplied URL
  and provider quota; it is the next run.
- **The desktop window is not visually exercised in CI.** `--self-test` proves the
  bundled server and page; the WebView2 window itself needs a manual launch.
- WebView2 runtime is required for the window; Windows 11 and current Windows 10 have
  it. The fallback is the browser, with a message.
- The installer is unsigned; Windows SmartScreen may ask for confirmation.
