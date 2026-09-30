---
description: Cut vertical clips out of a video with the ClipBlitz engine
argument-hint: <video path or URL> [number of clips]
allowed-tools: mcp__clipblitz__cut_clips, mcp__clipblitz__job_status, mcp__clipblitz__job_clips, mcp__clipblitz__risk_report
---

# Cut clips

Arguments: `$ARGUMENTS`

Cut clips out of that video with the `cut_clips` tool.

- If the user did not say how many, use 3.
- Pass `clips` as the number the user asked for (1-8).
- Pass `engine` only if the user named one: `b2` (film grade, cuts on shot boundaries),
  `prox` (the same edit without the cinema layer), or `both` (one analysis pass, two
  renders of every cut). Default `b2`.
- Pass `rights` only when the user has already stated their rights in this
  conversation. Never infer it from the fact that they own the file, and never pick
  an answer to make the call succeed.
- The tool waits for the render. If it returns before the clips are ready, poll
  `job_status` with the job id until it is `done`.

When it finishes, report every clip as: file path, title, score, engine, and the
window (`start` -> `end`). Give the reason each one was picked in the tool's own
terms — the score comes from the judge's ratings of that exact cut plus measured
audio factors, so do not re-explain it with guesses about the content.

Then report the clips in the order the tool ranked them, and mention any flag from
the `risk` block in plain language.

Two things you must not do:

1. Never call `risk_report` results "copyright-free", "safe from strikes" or
   "uncopyrighted". The report lists measured risk flags and the owner's rights
   answer; a claim is decided by the platform, not by this tool.
2. Never post, upload or publish anything. This plugin only edits. The rights gate
   and the publish buttons live in the studio, and they are answered by a human.
