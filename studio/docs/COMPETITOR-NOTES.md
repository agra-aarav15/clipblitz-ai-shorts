# Competitor study - what was adopted and what was not

Read-only study of the four supplied repositories plus the REA skill. No competitor
source code was copied into ClipBlitz. The licenses are different, so the study
extracted behavior and wrote independent implementations.

## SupoClip - AGPL-3.0

Source: `FujiwaraChoki/supoclip`, inspected at `backend/src/workflows/` and
`backend/src/media/`.

Adopted as **ideas**, independently implemented in `clipblitz/argon.py`:

- **Boundary strength**: a cut after a sentence or speaker change is stronger than a
  mid-sentence pause, which is stronger than a forced cut. ARGON now measures the
  ending from the last word, the next word and the gap between them.
- **Opening review**: a dangling conjunction ("But the main reason...") or a two-word
  fragment ("No. No?") is a weak start even when the words are energetic. ARGON now
  labels the opening and can repair it to the previous sentence or the next full one.
- **Self-summary anchors**: lines such as "the point is", "the result was" and
  "what I learned" are payoff-shaped. ARGON now mines them as candidates.
- **Word-exact cuts and next-word guard**: a cut must finish the word it starts in and
  never enter the next word. This is the same behavior the 5.0.2 tail fix implements.

Not copied: SupoClip's AGPL code, prompts, planner schemas, database model, caption
templates and rendering pipeline. No line-for-line port exists.

Not adopted in this release: outline-driven chapters/recap/trailer workflows, filler
word removal, pause compression, multi-range stitching and face/speaker reframing.
Those are larger product surfaces, not ranking tweaks.

## AutoShorts - MIT

Source: `alamshafil/auto-shorts`.

This is a **generator** (topic script -> TTS/images/templates), not a long-video clip
selector. It has no hook/payoff mining, no transcript boundary model and no source
highlight ranking to learn from. Its rendering abstractions are not compatible with
ClipBlitz's ffmpeg pipeline, so nothing was adopted. The repository is archived by its
author.

## LiveShive and ClipShlip - release builds only

Sources: `Ai-Haris/LiveShive-Releases`, `Ai-Haris/ClipShlip-Releases`.

Both repositories contain only a README and media; LiveShive ships a Windows installer.
There is no source code and no algorithm to inspect. The README features were recorded
as product gaps, not copied:

- live stream clipping while the stream is still running
- screen + face stacked layout
- Hinglish (Roman Hindi/Urdu) captions
- music bed with ducking under speech
- loud-reaction / clutch / headshot moment detection
- hardware-tier setup and GPU rendering

None of these are in this release. Implementing them would require a live ingest path,
a new layout renderer, transliteration and a music mixer; calling them "done" without
that would be false.

## REA - MIT

Source: `morluto/rea`. The skill was installed at
`C:/Users/AUSU/.agents/skills/reverse-engineer-anything` (SKILL.md plus references).

REA's own routing rule says to use it for shipped binaries, packages or runtime
evidence, and to skip it for ordinary analysis of a complete source repository. SupoClip
and AutoShorts are complete source repositories, so they were read with normal source
tools. The two Haris repositories have no source; their installer was not decompiled or
copied. That keeps the study on the right side of both the licenses and the product
boundary.

## What this means for the algorithm

The useful import is not a line of competitor code. It is the missing **edge model**:
a clip is a unit of speech with a real opening and a real ending, not an arbitrary
timestamp pair. ARGON 5.1 scores both edges, repairs a weak opening, and finishes a
word before the tail. That is the part the earlier engine treated too loosely.
