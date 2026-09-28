"""Prove the staged engine boots and answers, using the same bootstrap the phone uses.

CI has no Android device, so this runs the staged source on the build machine through
android_bootstrap.start() -- the exact function MainActivity calls -- and then asks the
engine's own server for /api/health. It is not a substitute for running on a phone, and it
does not claim to be: it proves the staged tree is complete and importable, which is the
failure mode that would otherwise only show up as a blank screen on a device.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STAGED = os.path.join(HERE, "app", "src", "main", "python")
ANDROID_PY = os.path.join(HERE, "app", "src", "android-python")
PORT = int(os.environ.get("CB_SMOKE_PORT", "4391"))


def main():
    for path in (STAGED, ANDROID_PY):
        if not os.path.isdir(path):
            print("FAIL  missing source set: %s (run sync-python.py first)" % path)
            return 1
        sys.path.insert(0, path)

    problems = []

    # The import check runs in a child process, so importing the engine here cannot
    # change the import order we are about to test below.
    modules = ["clipblitz.config", "clipblitz.server", "clipblitz.virality", "clipblitz.pipeline",
               "clipblitz.learning", "clipblitz.cinema", "clipblitz.captions", "clipblitz.ffmpeg_tools",
               "clipblitz.hardware", "clipblitz.ingest", "clipblitz.social", "clipblitz.stt",
               "clipblitz.brains", "clipblitz.keys"]
    code = "import sys; [__import__(m) for m in %r]; print('ok')" % (modules,)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([STAGED, ANDROID_PY]))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        problems.append("the engine did not import cleanly:\n%s" % (proc.stderr.strip()[-1200:],))
    else:
        print("PASS  all %d engine modules import under CPython %d.%d, stdlib only"
              % (len(modules), sys.version_info.major, sys.version_info.minor))
    if problems:
        for p in problems:
            print("FAIL  %s" % p)
        return 1

    # Boot it exactly the way the activity does: start() first, nothing imported before it.
    workdir = tempfile.mkdtemp(prefix="clipblitz-smoke-")
    import android_bootstrap
    data_dir = android_bootstrap.start(PORT, workdir)
    expected = os.path.join(workdir, "data")
    print("PASS  android_bootstrap.start() booted the engine")
    if os.path.normcase(os.path.abspath(data_dir)) != os.path.normcase(os.path.abspath(expected)):
        print("FAIL  the engine was pointed at %s, not %s" % (data_dir, expected))
        return 1
    if not os.path.isdir(data_dir):
        print("FAIL  the engine's data dir was not created")
        return 1
    print("PASS  the engine writes to %s" % data_dir)
    # The engine must agree, not just the bootstrap: this is what a job write would use.
    from clipblitz.config import CONFIG
    if os.path.normcase(os.path.abspath(CONFIG["data_dir"])) != os.path.normcase(os.path.abspath(expected)):
        print("FAIL  clipblitz.config still points at %s" % CONFIG["data_dir"])
        return 1
    print("PASS  clipblitz.config agrees (CB_DATA took effect)")

    # The first health call builds the hardware profile, which can take a while on a slow
    # machine, so give each attempt room and count the seconds rather than the errors.
    body, last = None, None
    for _ in range(45):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % PORT, timeout=20) as r:
                if r.status == 200:
                    body = r.read().decode("utf-8")
                    break
                last = "HTTP %s" % r.status
        except (urllib.error.URLError, OSError) as exc:
            last = exc
        time.sleep(1)
    if body is None:
        print("FAIL  /api/health never answered on port %d (%s)" % (PORT, last))
        return 1

    health = json.loads(body)
    print("PASS  GET /api/health -> %s %s" % (health.get("name"), health.get("version")))
    print("      engines: %s" % ", ".join(e["id"] for e in health.get("engines", [])))
    print("      rights : %s" % ", ".join(r["id"] for r in health.get("rights", [])))

    report = android_bootstrap.engine_report()
    print("      engine_report: %s" % json.dumps(report))
    for key, value in (("name", health.get("name")), ("version", health.get("version"))):
        if not value:
            print("FAIL  /api/health is missing %s" % key)
            return 1

    print("\nstaged engine boots and serves: %s" % os.path.relpath(STAGED, HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
