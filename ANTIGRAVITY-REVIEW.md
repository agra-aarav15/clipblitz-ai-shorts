# ANTIGRAVITY-REVIEW.md — independent critique wanted

**Context for the reviewer (Gemini / Antigravity):** ClipBlitz is a self-hosted OpusClip-style
tool. The engine (ProX v5) is in `clipblitz/virality.py` (~700 lines, pure Python, prompts at
the top). The user's feedback after watching real renders on a 54-min comedy podcast
(*INDIA'S GOT LATENT S2 EP5*) is the ground truth this engine must satisfy.

## The user's taste (learned from real renders — treat as requirements)

1. **The ending decides everything.** Their favourite clip "started random but ended just fine".
   Their two most-hated clips were high-scoring until the ending felt dead ("prize announcement",
   "sponsor hype with no payoff"). Payoff must dominate; a dead ending must be disqualified.
2. **Intros/hype are the worst clips.** "Welcome / make some noise / sponsor shoutout" material
   must never reach the podium (now banned via HYPE_MARKERS at mining + draft).
3. **Short snippets feel random.** Minimum cut length was raised to 20s (prompt) / 18s (hard gate).
4. **Honest scores over flattery.** The QC judge rates the *exact verbatim* of each final cut;
   failures are labelled `◐ unverified` with the critique shown on the card.

## What changed in response (already coded, unit-tested)

- Weights rebalanced: payoff 0.38, story 0.22, energy 0.16, pacing 0.14, hook 0.10
- `measure()` now computes **tail_laugh** (laughter in the last 8s + 1.5s); it folds into payoff
- `judge_fail()`: cold opens allowed; fails on dead ending, coherence < 7, or payoff < 5
- `score_v2()`: dead ending caps score at 55; not-standalone caps at 45
- `rank()` podium gate: only judge-passed cuts or measured tail_laugh ≥ 0.25 fill the podium
- Repair loop: dead endings first get the deterministic fix (extend through the next laugh),
  only then an LLM redraw

## Review request

Read `clipblitz/virality.py` end to end and critique **as a short-form editor**, not as a coder:

1. Are there viral-clip signals we still don't measure that matter for comedy podcasts?
   (We have: laughter regions, tail laughter, RMS energy vs baseline, words/sec pacing,
   sentence-boundary snapping, LLM hook/coherence/payoff ratings.)
2. Is the payoff-dominant weighting (0.38 payoff / 0.10 hook) right, or is there a better shape?
3. The judge sees only text, never video/audio. Which failure modes does that hide, and what
   cheap measurement would catch them?
4. Any prompt improvements for STORY_PROMPT / DRAFT_PROMPT / JUDGE_PROMPT (they're inline at the
   top of the file) — specifically to find *complete arcs with strong endings*?
5. Sanity-check the pipeline order: mine stories → shortlist by laugh+energy → draft cuts →
   snap → extend through laugh → measure → judge → repair → re-judge → podium gate.

Be blunt. Point at specific functions/prompts. The user re-runs the same episode after every
change and judges the output by hand, so measurable improvements matter more than theory.
