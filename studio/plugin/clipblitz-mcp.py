#!/usr/bin/env python3
"""Launcher for the ClipBlitz MCP server, so an agent host needs no PYTHONPATH setup.

The plugin ships inside the Studio checkout, so the engine is one folder up. If the
plugin is copied somewhere else, point CB_ROOT at the studio folder and this launcher
will use that instead.

stdout is the JSON-RPC channel: this script prints nothing itself.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CB_ROOT") or os.path.dirname(HERE)

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

from clipblitz.agent import mcp_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(mcp_main())
