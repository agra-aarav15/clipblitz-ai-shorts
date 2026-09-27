#!/usr/bin/env python3
"""ClipBlitz entry point — python run.py [port]"""

import sys

# A fresh Windows console is often cp1252, not UTF-8: without this, any print
# containing a unicode arrow would crash the server before it binds.
print("Starting ClipBlitz Studio ...", flush=True)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

from clipblitz.config import CONFIG
from clipblitz.server import serve

if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else CONFIG["port"])
