# ClipBlitz Studio — agent plugin

Give a coding agent a video and a number, and get finished vertical clips back.

    "Here's episode-142.mp4 — cut me four clips."

The plugin drives the same stdlib engine that ships in the Studio app: no cloud, no
API key, no upload. Clips land in `<studio>/data/clips/` as 1080x1920 `.mp4` files
with burned-in captions, and every clip comes back with its title, hook, score and
the measured reason it was picked.

## Install

**Claude Code.** The plugin folder is meant to be loaded as a local plugin:

    claude plugin marketplace add <path-to-this-repo>      # if you publish a marketplace entry
    claude --plugin-dir E:\clipstudio\plugin

Once loaded you get:

- the `clipblitz` MCP server (tools below),
- `/cut <video> [how many]`,
- the `cut-clips` skill, so the agent reaches for the tool when a user just hands
  over a video without naming it.

The launcher (`clipblitz-mcp.py`, next to this file) finds the engine one folder up.
If you copied this folder out of the checkout, set `CB_ROOT` to the studio folder.

**Any other agent runtime.** The CLI is the same code path:

    python -m clipblitz.agent cut episode.mp4 --clips 4 --json
    python -m clipblitz.agent tools                 # the MCP tool schemas as JSON
    python -m clipblitz.agent mcp                   # the MCP server on stdio

Point a generic MCP client at `python <studio>\plugin\clipblitz-mcp.py`.

**The Windows bundle, on a machine with no Python.** `ClipBlitzStudio-4.1.0-windows.zip`
ships this folder next to `ClipBlitzStudio.exe`, and the EXE answers the same MCP server
itself, because the EXE is the same entry point:

    "command": "<bundle>\\ClipBlitzStudio.exe", "args": ["--mcp"]

Copy `plugin\.mcp.windows.json` into your MCP client's config and replace `<bundle>` with the
folder you unzipped; `ClipBlitzStudio.exe --tools` prints the schemas. Everything else - the
routing to a running studio, the learning store next to the app - behaves identically.

## Tools

| Tool | What it does |
| --- | --- |
| `cut_clips` | Cuts N clips from a file or URL, waits, returns the rendered files. |
| `job_status` | Stage and progress of a running job. |
| `job_clips` | The clips of a finished job. |
| `risk_report` | Measured copyright-safety flags for a job. |
| `edit_receipt` | Writes the edit manifest (windows, engine, transformative work, sha256). |
| `learning_state` | What each engine has learned from this owner's kept cuts. |
| `train_model` | Fits the local taste model from the owner's real choices and reports the gate decision. |

Where the work runs: if a Studio server is listening on `127.0.0.1:4300`, the job
goes through its API (one writer for `data/jobs.json`). Otherwise the identical
pipeline runs in the agent's own process. Either way the local learning store is
the same file the app uses, so an agent's use trains the same two engines.

## Two rules the plugin does not bend

1. **It only edits.** There is no publish, post or upload tool. The rights gate and
   the publish buttons stay in the studio, in front of a human.
2. **It does not make anything uncopyrighted.** `risk_report` measures real things —
   third-party-looking music spans, where the source came from, a missing or expired
   licence, clips that carry fewer transformative layers — and stores the owner's
   rights answer next to the edit receipt. A content-matching system matches the work
   itself, so no tool here can promise immunity from a claim, and none will claim to.
