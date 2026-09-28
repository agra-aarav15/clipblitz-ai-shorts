"""Read the built APK back and check it really contains CPython and the whole engine.

A green Gradle build only means Gradle was happy. This opens the artifact and looks for the
things that make the app standalone: a native Python for each ABI, Chaquopy's bundles, and
the engine's own modules inside them. It makes no assumption about Chaquopy's file naming --
it opens every bundle it finds and reports what is inside.

    python verify_apk.py app/build/outputs/apk/debug/app-debug.apk
"""

import io
import os
import sys
import zipfile

# Modules that must be inside the shipped app, by name as they appear in the bundle.
ENGINE = ["clipblitz/server", "clipblitz/config", "clipblitz/virality", "clipblitz/pipeline",
          "clipblitz/learning", "clipblitz/cinema", "clipblitz/captions"]
UI = ["web/index.html", "web/app.js", "web/styles.css"]


def main(argv):
    if len(argv) != 1:
        print("usage: verify_apk.py <path-to-apk>")
        return 2
    path = argv[0]
    if not os.path.isfile(path):
        print("FAIL  no APK at %s" % path)
        return 1

    apk = zipfile.ZipFile(path)
    names = apk.namelist()
    size = os.path.getsize(path)
    print("APK %s (%.2f MB, %d entries)" % (path, size / 1048576.0, len(names)))
    problems = []

    libs = sorted(n for n in names if n.startswith("lib/") and n.endswith(".so"))
    abis = sorted({n.split("/")[1] for n in libs})
    print("\nnative libraries, by ABI:")
    for abi in abis:
        mine = [n for n in libs if n.split("/")[1] == abi]
        print("  %-12s %d .so files, %.1f MB uncompressed"
              % (abi, len(mine), sum(apk.getinfo(n).file_size for n in mine) / 1048576.0))
    if not libs:
        problems.append("no native libraries: CPython is not in this APK")
    for wanted in ("arm64-v8a", "x86_64"):
        if wanted not in abis:
            problems.append("no %s libraries" % wanted)

    bundles = sorted(n for n in names if n.startswith("assets/chaquopy/"))
    print("\nchaquopy bundles:")
    for n in bundles:
        print("  %-44s %8.2f MB" % (n, apk.getinfo(n).file_size / 1048576.0))
    if not bundles:
        problems.append("no assets/chaquopy/: the Python code is not bundled")

    # Open every bundle and see what is actually inside.
    found, readable = set(), 0
    for n in bundles:
        blob = apk.read(n)
        inner = None
        try:
            inner = zipfile.ZipFile(io.BytesIO(blob))
            readable += 1
            for entry in inner.namelist():
                found.add(entry.replace("\\", "/"))
        except zipfile.BadZipFile:
            # stdlib bundles are Chaquopy's own format; fall back to a byte scan so a
            # naming guess of mine can never turn into a false failure.
            if b"clipblitz" in blob or b"clipblitz" in blob.replace(b"\x00", b""):
                found.add("(raw scan of %s mentioned clipblitz)" % n)

    print("\nbundles read as zip archives: %d; entries listed: %d" % (readable, len(found)))
    engine_hits = [m for m in ENGINE
                   if any(e.startswith(m) or m in e for e in found)]
    ui_hits = [u for u in UI if any(e == u or e.endswith(u) for e in found)]
    print("  engine modules found : %d of %d" % (len(engine_hits), len(ENGINE)))
    for m in engine_hits:
        print("     %s" % m)
    print("  web assets found     : %d of %d" % (len(ui_hits), len(UI)))
    for u in ui_hits:
        print("     %s" % u)
    missing = [m for m in ENGINE if m not in engine_hits]
    if missing:
        problems.append("engine modules missing from the APK: %s" % ", ".join(missing))
    if len(ui_hits) < len(UI):
        problems.append("the studio UI is missing from the APK")

    leaks = [n for n in names
             if n.endswith(".env") or "/data/" in n or n.endswith((".pyc.source", "boot.log"))]
    if leaks:
        problems.append("unexpected files inside the APK: %s" % ", ".join(leaks[:4]))

    manifest = apk.read("AndroidManifest.xml")
    for needle in (b"clipblitz", b"standalone"):
        if needle not in manifest:
            problems.append("AndroidManifest.xml does not mention %s" % needle.decode())

    print("")
    if problems:
        for p in problems:
            print("FAIL  %s" % p)
        return 1
    print("PASS  CPython, the engine and the studio UI are all inside the APK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
