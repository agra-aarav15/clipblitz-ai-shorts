"""One bundle, two EXEs.

PyInstaller builds this same entry point twice. The executable name decides the mode:

    ClipBlitzStudio.exe          the native window (windowed, no console)
    ClipBlitzStudio-server.exe   the server, MCP and CLI (console)

That keeps the agent plugin (`--mcp`) and a power-user server on the console EXE while
the normal app is a clean desktop window.
"""

import os
import sys


def main():
    name = os.path.basename(sys.executable).lower()
    if "server" in name:
        import run
        return run.main()
    from clipblitz.desktop import main as desktop_main
    return desktop_main()


if __name__ == "__main__":
    sys.exit(main())
