#!/usr/bin/env python3
"""ClipBlitz entry point — python run.py [port]"""

import sys

from clipblitz.config import CONFIG
from clipblitz.server import serve

if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else CONFIG["port"])
