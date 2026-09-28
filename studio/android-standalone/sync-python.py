"""Stage the real engine into the standalone app's Python source set.

The Android app bundles the same clipblitz package the desktop runs -- there is no fork and
no second copy in git. This script is the only thing that puts the engine where Chaquopy
expects it, it is idempotent, and it refuses to finish if the result is not something the
engine could actually import.

    python sync-python.py            stage, then verify what was staged
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)                       # studio/
DEST = os.path.join(HERE, "app", "src", "main", "python")

PACKAGES = [("clipblitz", ".py")]                    # the engine itself
DATA = ["web"]                                       # the UI the engine serves
SKIP_DIRS = {"__pycache__", "data", ".git"}
SKIP_EXT = {".pyc", ".pyo", ".log", ".tmp"}

# Without these the app is not an app: the engine's entry module and its static UI.
REQUIRED = ["clipblitz/__init__.py", "clipblitz/server.py", "clipblitz/virality.py",
            "clipblitz/config.py", "clipblitz/pipeline.py", "web/index.html", "web/app.js"]


def copy_tree(src_root, dest_root):
    kept = 0
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            if name == ".env" or name.startswith(".env."):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, src_root)
            out = os.path.join(dest_root, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(full, out)
            kept += 1
    return kept


def main():
    if not os.path.isdir(os.path.join(STUDIO, "clipblitz")):
        print("cannot find the engine at %s" % os.path.join(STUDIO, "clipblitz"))
        return 1

    if os.path.isdir(DEST):
        shutil.rmtree(DEST)
    os.makedirs(DEST)

    staged = 0
    for name, _ext in PACKAGES:
        src = os.path.join(STUDIO, name)
        if not os.path.isdir(src):
            print("missing engine package: %s" % src)
            return 1
        staged += copy_tree(src, os.path.join(DEST, name))
    for name in DATA:
        src = os.path.join(STUDIO, name)
        if not os.path.isdir(src):
            print("missing data directory: %s" % src)
            return 1
        staged += copy_tree(src, os.path.join(DEST, name))

    missing = [r for r in REQUIRED if not os.path.isfile(os.path.join(DEST, r.replace("/", os.sep)))]
    if missing:
        print("staged tree is incomplete, missing: %s" % ", ".join(missing))
        return 1

    # A leak here would put secrets or a dev database inside a shipped APK.
    leaks = []
    for dirpath, _dirnames, filenames in os.walk(DEST):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), DEST).replace("\\", "/")
            if name == ".env" or name.startswith(".env.") or rel.startswith("data/") \
                    or name.endswith((".pyc", ".log")) or "_cap.bat" == name:
                leaks.append(rel)
    if leaks:
        print("refusing to stage: %s" % ", ".join(leaks[:5]))
        return 1

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _dn, fn in os.walk(DEST) for f in fn)
    engine = sum(1 for dp, _dn, fn in os.walk(os.path.join(DEST, "clipblitz"))
                 for f in fn if f.endswith(".py"))
    print("staged %d files (%.2f MB) into %s" % (staged, total / 1048576.0, DEST))
    print("  engine modules : %d .py files" % engine)
    print("  web assets     : %d files" % sum(1 for dp, _dn, fn in os.walk(os.path.join(DEST, "web")) for f in fn))
    print("  no .env, no data/, no caches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
