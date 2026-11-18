# ClipBlitz Studio v5.7.1 — OAuth reliability fix

This patch fixes the four failures that made a successful Google consent look broken.

## Fixed

1. **OAuth callback showed `{"error": "not found"}`** — the success/error page was passed
   to the static-file opener as bytes. It is now sent as an HTML response.
2. **Consent asked for upload only** — it now asks for
   `youtube.upload` + `youtube.readonly`, so the channel name and the live diagnostic work.
3. **`unauthorized_client` was not treated as a re-consent** — the saved token now moves
   to the honest “reconnect” state instead of claiming to be connected forever.
4. **Upload-only tokens were reported as broken** — the diagnostic now checks the token
   itself; a token that can upload is ready even when channel-name read is unavailable.
5. **Health and UI disagreed with the token** — `youtube_ready` means the upload token is
   present, and the UI uses the server's redirect URI instead of the WebView origin.

## Verified

- **839 tests passed, 0 failed** across all 19 `scripts/test_*.py` files.
- Packaged `ClipBlitzStudio-server.exe` reports **5.7.1** and `/api/health` is green.
- The callback endpoint returns **HTTP 200 text/html** instead of 404.
- A real **private** upload succeeded through the saved OAuth token:
  `https://www.youtube.com/shorts/tC4yxK9KFQo`.
- Electron self-test: `health ok, page ok, port 53383`.
- Windows x64 installer and portable zip built; app installed at
  `E:\clipping\Clipblitz\ClipBlitzStudio`.

## Honest note

The existing token was granted before this patch, so it is upload-only. Uploads work.
The channel name appears after one reconnect, because the new consent requests
`youtube.readonly`. This is cosmetic and does not block auto-posting.

Windows artifacts:

- `ClipBlitzStudio-5.7.1-win-x64-setup.exe`
- `ClipBlitzStudio-5.7.1-win-x64.zip`
