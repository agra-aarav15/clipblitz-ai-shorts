"""Headless backend entry for the Electron bundle.

The desktop shell starts this process, waits for /api/health and loads the same web
studio in an Electron window. It deliberately does not import pywebview: Electron is
the window on every OS.
"""

import sys


def main():
    from run import main as run_main
    return run_main()


if __name__ == "__main__":
    sys.exit(main())
