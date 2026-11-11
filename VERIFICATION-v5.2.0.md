# Verification - ClipBlitz Studio 5.2.0

This release makes ARGON the only product engine, adds a multi-provider AI pool, and
cuts long-video processing time. No competitor code was copied.

## One engine

- The Studio UI has one engine button: ARGON.
- `/api/health` returns `engines: [argon]` and `default_engine: argon`.
- `server._engine`, `pipeline.new_job` and `pipeline._variant` map every legacy request
  (`prox`, `b2`, `apex`, `both`) to ARGON. Old jobs still load.
- The agent/MCP engine enum is `["argon"]`.
- ProX/B2/APEX/Both source remains only as frozen reference code for old-job replay; it is
  not selectable.

## Provider pool

`clipblitz/brains.py` now builds an ordered pool:

| Provider | Access |
|---|---|
| Groq | `CB_AI_KEY` or comma-separated `CB_GROQ_KEYS` |
| Gemini | `CB_GEMINI_KEY` or `CB_GEMINI_KEYS` |
| Cerebras | `CB_CEREBRAS_KEY` |
| OpenRouter | `CB_OPENROUTER_KEY` + free model |
| Together | `CB_TOGETHER_KEY` |
| OpenAI | `CB_OPENAI_KEY` |
| Pollinations | **no key**, free fallback |
| Local | any OpenAI-compatible server, e.g. Ollama at `CB_LOCAL_BASE` |

`CB_AI_ORDER` sets priority. A 429/5xx/network failure puts that provider on cooldown so
parallel editor chunks do not all wait on the same exhausted key. `CB_AI_TIMEOUT` defaults
to 120s. Keys are never included in health or logs; `brains_status()` returns names/models
only.

Pollinations was tested directly and returned a valid chat completion. It is a fallback,
not a promise of permanent uptime; a local Ollama server is the permanent/free option.

## Speed

- **Transcript cache** is keyed by the original source file, not the per-job temp wav.
  A re-run on the same 68-minute episode skips all transcription API calls.
- **Parallel editor chunks** (`CB_EDITOR_WORKERS=3`, bounded 1-4): six independent chunks
  run concurrently.
- Sam Altman interview (68 minutes), same machine:
  - before: **2931s** (48.8 min)
  - after: **1583s** (26.4 min)
  - **46% faster**
- F1 reaction video (12 minutes): ~10 minutes end-to-end.

## Selection quality

- The judge pool now guarantees one candidate from each time slice (3, 4 or 6 slices by
  duration). A long interview can no longer put every judged candidate in its first two
  minutes.
- The podium admits only `viral`/`strong` cuts. A `usable` clip with measured defects is no
  longer used to fill the third slot; returning two strong cuts is preferred to two strong
  plus one weak.
- The tail search reaches 5.5s to finish a sentence and find a real pause, still clamped
  before the next word. F1 measured tails: 0.77s, 0.80s, 0.49s; measured-laugh tail 1.15s.
- Fresh 68-minute job `9c2cedef` produced three verified cuts (86, 66, 85) spanning
  106s, 3268s and 25s. The 66 was `usable` with `low_energy`/`slow_open`; the new
  strong-only podium would keep the 86 and 85, not the filler.
- A later run (`06bd0a7b`) exposed a stale-tier bug: the legacy re-judge updated scores
  but not tiers, leaving 55/58 as "strong". ARGON now re-judges with its own gate/score,
  updates the tier, and drops a rejected clip when a better one survives. Old jobs are
  normalized on load.

## Tests

```
test_argon           80 passed, 0 failed
test_engines         29 passed, 0 failed, 1 skipped
test_learning        28 passed, 0 failed
test_agent           82 passed, 0 failed
test_trainer         64 passed, 0 failed
test_rights          62 passed, 0 failed
test_scout           57 passed, 0 failed
test_clipbench       44 passed, 0 failed
test_daily           69 passed, 0 failed
test_social          45 passed, 0 failed
test_quality         35 passed, 0 failed
test_marketplace     94 passed, 0 failed
```

**689 passed, 0 failed, 1 skipped.**

New tests: one-engine mapping, provider pool/order/multi-key/no-key-leak, transcript cache,
opening/ending boundary, visible tail, coverage-aware scoring.

## Honest limits

- No blind A/B against OpusClip was run. This release is a measured improvement, not a
  proven win.
- Pollinations/OpenRouter/Groq/Gemini free tiers are rate-limited. A local model is the
  only permanent/free option; the app supports it but does not bundle a multi-GB model.
- Filler-word removal, multi-range stitching, speaker diarization and live clipping are still
  not shipped.
