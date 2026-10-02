#!/usr/bin/env python3
"""ClipBlitz entry point - one script, three faces.

    python run.py [port]     the studio server itself (default port 4300)
    python run.py --tools    the MCP tool schemas as JSON, then exit
    python run.py --mcp      the MCP server on stdio - what the agent plugin launches
    python run.py --train    one fit of the local taste model, then exit

The packaged Windows EXE is this very script, so `ClipBlitzStudio.exe --mcp` is the
plugin with no Python installed. The two agent modes own stdout (an agent host reads
JSON there), which is why they are answered before the server banner is printed.
"""

import json
import sys

ARG = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
AGENT_MODES = {"--tools": "tools", "tools": "tools", "--mcp": "mcp", "mcp": "mcp"}
TRAIN_MODES = ("--train", "train")


def utf8_console():
    """A fresh Windows console is often cp1252, not UTF-8: without this, any print
    containing a unicode arrow would crash the process before it does its job."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main():
    if ARG in AGENT_MODES:
        # stdout is the JSON-RPC channel here, so no banner: it would corrupt the frame.
        utf8_console()
        from clipblitz.agent import main as agent_main
        return agent_main([AGENT_MODES[ARG]])
    if ARG in TRAIN_MODES:
        # one explicit fit; JSON on stdout, no banner, same payload as POST /api/train
        utf8_console()
        from clipblitz import trainer
        print(json.dumps(trainer.run_fit(reason="cli"), indent=2, ensure_ascii=False))
        return 0
    print("Starting ClipBlitz Studio ...", flush=True)
    utf8_console()
    from clipblitz.config import CONFIG
    from clipblitz.server import serve
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else CONFIG["port"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
