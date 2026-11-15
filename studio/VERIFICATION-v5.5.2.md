# Verification - ClipBlitz Studio 5.5.2

Two small defects found by the Raj test, plus the honest 3-clip result.

## Local model discovery on first Connect

The one-time `.env` import created a local provider with the built-in model id
`qwen2.5:3b`. This machine's Ollama only has `clipblitz-local:latest`, so the imported
provider answered **HTTP 404** on every call. The import now asks the local
`/models` endpoint once and prefers an installed model (a `clipblitz` match first,
then the configured id, then the first model). A machine without a local runtime
still imports nothing.

Test: `providers: importing a local runtime picks an installed model` (29 provider
tests).

## A measured-only reject is labelled "measured"

The no-key path can return its strongest measured window when every candidate failed
the measured gate (there is no judge to reject it). The badge said **reject** next to
the honest **unverified** badge. The clip card now shows **measured** for that case;
the gate reasons remain in the verdict. Quality-first selection is unchanged: a real
judge can still empty the podium, and the app does not pad three slots.

## Raj Shamani, real YouTube link (505 s)

Source: `https://www.youtube.com/watch?v=T4kl7p48qV0` ("The 5 Daily Habits That Add
14 Years To Your Life | Raj Shamani"). yt-dlp downloaded 43.9 MB + English and Hindi
captions. The app chose the richer Hindi source transcript.

| Path | Result |
|---|---|
| No provider, captions only | done, 10 candidates, **1 measured** window (gate: payoff), labelled unverified; no 3-clip padding |
| Groq + Gemini, captions | done in **265.9 s**, 11 provider calls (Groq 429 four times, Gemini carried 8), **1 verified** clip `231.7-303.2 s`, score 61, 1080×1920, 71.5 s, title **"How to Stop Constant Worrying"** |
| Local Ollama (`clipblitz-local`) | editor/judge timed out at the 90 s cap; final judge emptied the podium; **0 clips** |

The cloud run is the quality result. The app returned the one clip that passed the
gate instead of inventing two more. A longer podcast with several self-contained
stories is the source for a three-clip run; the 505 s single-story video is not.

## Tests

- Providers **29**, captions **16**, everything else unchanged.
- Studio: **817 passed, 0 failed**; repo checkout: **833 passed, 0 failed, 1 skipped**.

## Still not done

- Public one-click YouTube posting (needs an owner-verified OAuth client and quota).
- A bundled local STT model (the caption path covers YouTube links; local uploads
  without a provider still use the heuristic transcript).
- A fresh long TV/Raj three-clip benchmark; the engine is unchanged from 5.4.4.
