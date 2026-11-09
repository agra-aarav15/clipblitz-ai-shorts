# Verify ClipBlitz Studio v5.0.0 with Gemini

**Status: PASS.** Gemini 4 Argon verified commit `790425f` read-only on 2026-11-09: 384 tests
passed, 0 failed, health 0.704s, no P0 issues. Keep this brief for a future re-run.

Paste the brief below into Gemini 4 Argon (or another Gemini model) with access to this
checkout. The verifier must work read-only. Expected checkout: `f:/Clipblitz/repo-clipblitz`
at commit `0a52ebd` (or later, if the commit is superseded).

```text
You are the independent verifier for ClipBlitz Studio v5.0.0, specifically the new ARGON
engine. Try to falsify the implementation, not to praise it. Work read-only inside
f:/Clipblitz/repo-clipblitz. Do not modify files, do not commit, do not push. Do not use
network services except localhost.

Read first:
- studio/docs/ARGON-MASTER-PLAN.md
- studio/clipblitz/argon.py
- studio/clipblitz/pipeline.py
- studio/clipblitz/virality.py (shared helpers)
- studio/clipblitz/server.py
- studio/clipblitz/agent.py
- studio/clipblitz/learning.py
- studio/scripts/test_argon.py
studio/clipblitz/vision.py
studio/web/cutdesk.css
- studio/scripts/test_engines.py
- VERIFICATION-v5.0.0.md
- README.md and studio/README.md / studio/SETUP.md for version consistency

Run from studio/ and report exact counts:
  python scripts/test_argon.py
  python scripts/test_engines.py
  python scripts/test_learning.py
  python scripts/test_agent.py
  python scripts/test_trainer.py
  python scripts/test_rights.py
  python scripts/test_scout.py
  python scripts/test_clipbench.py
  python scripts/test_daily.py
  python scripts/test_social.py
  python scripts/test_quality.py
  python scripts/test_marketplace.py
  python scripts/bench_episode.py --synthetic --gate

Start the server on a free port with CB_DATA pointing at a fresh temp directory and
CB_DAILY=off. Verify:
- /api/health reports version 5.0.0, default_engine argon, engines [argon, prox, b2, apex, both]
- /api/lan works
- python -m clipblitz.agent tools lists 11 tools and the cut_clips engine enum includes argon
- the banner matches APP_VERSION
Stop the server afterward.

Audit studio/clipblitz/argon.py for P0 defects:
1. Can an offline run (no judge) ever be marked verified?
2. Can a judge exception or malformed JSON become a pass?
3. Can the non-compensatory gate be bypassed by a high hook, an incomplete list, or a
   context-dependent opening?
4. Can a window leave the duration band, start on filler, start mid-sentence, or end
   mid-sentence?
5. Can two selected clips be the same beat (shared ending, high temporal overlap, duplicate
   vocabulary)?
6. What happens on a short video, a silent video, an empty transcript, a one-sentence video,
   a very long transcript, and a rate-limited judge?
7. Are score/factor ranges and the required clip fields (engine_id/name, tier, gate, flags,
   argon, factors, reason, verdict) always present?
8. Is the result deterministic with the same inputs and no judge?

Audit the wiring:
- a new argon job runs one analysis pass, one cinema map, and renders only ARGON variants
- the old prox/b2 paths are not changed by the new branch
- version 5.0.0 is consistent across config, health, MCP, plugin manifest, marketplace
  metadata and docs
- CI runs test_argon and the packaged EXE still lists 11 tools

Check VERIFICATION-v5.0.0.md for overstatement. It must not claim a blind OpusClip A/B was
run or that ARGON is proven to beat every company.

Rules:
- Distinguish observed evidence from inference. Quote command output and file:line.
- Do not invent results. If you cannot run something, say so.
- Do not fix anything. Return a prioritized patch list: P0 correctness, P1 clip quality,
  P2 polish. For each: file, function/line, failure it causes, smallest fix.
- End with PASS / PASS WITH P0 ISSUES / FAIL and the evidence behind it.
```
