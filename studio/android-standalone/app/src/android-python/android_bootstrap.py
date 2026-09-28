"""Android-only glue: start the studio engine on the phone itself.

Nothing in here belongs on the desktop. The engine is unaware of Android; this module
exists to give it the two things Android refuses to guess at:

  * a writable data directory. The engine defaults to <root>/data, and the code bundled
    inside an APK is read-only, so CB_DATA has to be set before clipblitz.config is
    imported -- config reads it at import time.
  * a thread to serve on. The engine's serve() blocks, so it runs off the UI thread while
    the activity waits for /api/health to answer.
"""

import os
import threading

SERVER_THREAD = None


def start(port, files_dir):
    """Boot the engine's own HTTP server on `port`, writing to `files_dir`.

    Returns the directory the engine will use, so the caller can show it.
    """
    global SERVER_THREAD

    data_dir = os.path.join(files_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    os.environ["CB_DATA"] = data_dir

    # clipblitz.config snapshots CB_DATA at import time, so it is imported here rather
    # than at module load. Belt and braces for the case where something already imported
    # it (a probe, a test, a future caller): make the value authoritative either way.
    import clipblitz.config as config_module
    config_module.CONFIG["data_dir"] = data_dir

    from clipblitz.server import serve

    if SERVER_THREAD is None or not SERVER_THREAD.is_alive():
        SERVER_THREAD = threading.Thread(target=serve, args=(port,), name="clipblitz", daemon=True)
        SERVER_THREAD.start()
    else:
        config_module.CONFIG["data_dir"] = data_dir
    return data_dir


def engine_report():
    """A small honest summary of what the on-device engine can see."""
    from clipblitz import hardware
    from clipblitz.server import ffmpeg_available, stt_mode
    from clipblitz.config import CONFIG

    hw = hardware.profile()
    return {
        "ffmpeg": ffmpeg_available(),
        "stt": stt_mode(),
        "ai_key": bool(CONFIG.get("ai_key")),
        "data_dir": CONFIG.get("data_dir"),
        "render_capable": hw.get("render_capable"),
        "reason": hw.get("reason"),
    }
