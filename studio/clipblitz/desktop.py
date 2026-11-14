"""The native desktop window.

The studio is a local web app. This module gives it a real window (WebView2 on
Windows, WebKit on macOS/Linux) instead of a console plus a browser tab: it starts
the same server in a background thread and points a pywebview window at it.

The packaged distribution has two EXEs from one bundle:
  ClipBlitzStudio.exe          this window (no console)
  ClipBlitzStudio-server.exe   the server / MCP / CLI surface (console)

If WebView2 is not available, the window is skipped with a clear message and the
studio opens in the default browser, so the app still works.
"""

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


class _Sink:
    """PyInstaller's windowed EXE has no stdout/stderr. The server prints a banner;
    without this, that print would raise inside the server thread."""

    def write(self, data):
        return len(data) if data else 0

    def flush(self):
        pass


def _silence_null_streams():
    if sys.stdout is None:
        sys.stdout = _Sink()
    if sys.stderr is None:
        sys.stderr = _Sink()


def _health(port, timeout=0.6):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _busy(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _pick_port(preferred=4300):
    """The studio's usual port, then the next few, then any free port."""
    for port in (preferred, preferred + 1, preferred + 2, preferred + 10):
        if not _busy(port) or _health(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(port):
    from .server import serve
    try:
        serve(port)
    except SystemExit:
        pass
    except Exception as exc:  # a windowed process has no console to show this in
        _message("ClipBlitz Studio", f"The local server could not start:\n\n{exc}")


def _wait_ready(port, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _health(port):
            return True
        time.sleep(0.35)
    return False


def _message(title, text):
    """A native message box; the windowed EXE has no console for a traceback."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(text), str(title), 0x40)
    except Exception:
        try:
            print(f"{title}: {text}", file=sys.stderr)
        except Exception:
            pass


def _parse(argv):
    args = [a for a in (argv if argv is not None else sys.argv[1:]) if a]
    self_test = "--self-test" in args
    browser = "--browser" in args
    port = None
    for a in args:
        if a.isdigit():
            port = int(a)
            break
    return self_test, browser, port


def main(argv=None):
    _silence_null_streams()
    self_test, browser, port = _parse(argv)
    port = port or _pick_port(4300)
    already = _health(port)
    if not already:
        threading.Thread(target=_serve, args=(port,), daemon=True).start()
        if not _wait_ready(port):
            _message("ClipBlitz Studio", "The local server did not start. Run "
                     "ClipBlitzStudio-server.exe 4300 to see the error.")
            return 1
    url = f"http://127.0.0.1:{port}"
    if self_test:
        # CI proof that the app entry, bundled server and web assets work without a
        # GUI session. The window itself is a manual check.
        try:
            with urllib.request.urlopen(url + "/", timeout=5) as r:
                ok = r.status == 200 and b"ClipBlitz" in r.read(4096)
        except Exception:
            ok = False
        print(f"desktop self-test: health ok, page {'ok' if ok else 'missing'}, port {port}")
        return 0 if ok else 1
    if browser:
        webbrowser.open(url)
        return 0
    try:
        import webview
    except Exception as exc:
        _message("ClipBlitz Studio", f"The desktop window is unavailable ({exc}).\n"
                 "Opening the studio in your browser instead.")
        webbrowser.open(url)
        # keep this process (and the server thread) alive until the user closes it
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    try:
        webview.create_window(
            "ClipBlitz Studio", url, width=1440, height=900, min_size=(1040, 680),
            background_color="#050505", text_select=True,
        )
        webview.start()
    except Exception as exc:
        _message("ClipBlitz Studio", f"The desktop window could not start:\n\n{exc}\n\n"
                 "Opening the studio in your browser instead.")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
