"""Read the built APK back and check it really is a standalone studio.

A green Gradle build only means Gradle was happy. This opens the artifact and proves the
things that make the app stand on its own:

  * CPython for every ABI the app claims to support,
  * Chaquopy's bundles, with the engine's own modules inside them,
  * the studio's web assets, so the UI can actually be served from the device,
  * a manifest that boots Python at startup and launches the activity,
  * the launcher icon wired to the same mipmap the companion app uses.

Nothing here assumes Chaquopy's file names: it opens every bundle it finds and reports what
is inside, and it parses the binary manifest rather than scanning it for byte strings.

    python verify_apk.py app/build/outputs/apk/debug/app-debug.apk
"""

import io
import os
import struct
import sys
import zipfile

ENGINE = ["clipblitz/server", "clipblitz/config", "clipblitz/virality", "clipblitz/pipeline",
          "clipblitz/learning", "clipblitz/cinema", "clipblitz/captions"]
UI = ["web/index.html", "web/app.js", "web/styles.css"]
PY_APPLICATION = "com.chaquo.python.android.PyApplication"


# ----------------------------------------------------------------- binary XML

def string_pool(buf, off):
    """Decode a ResStringPool, UTF-8 or UTF-16 as its flags say."""
    _typ, hsz, _size = struct.unpack_from("<HHI", buf, off)
    count, _styles, flags, strstart, _ss = struct.unpack_from("<IIIII", buf, off + 8)
    offs = struct.unpack_from("<%dI" % count, buf, off + hsz)
    base, utf8, out = off + strstart, bool(flags & 0x100), []
    for o in offs:
        p = base + o
        if utf8:
            n = buf[p]
            p += 1
            n2 = buf[p]
            p += 1
            if n & 0x80:
                n = ((n & 0x7F) << 8) | n2
            out.append(buf[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", buf, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p)[0]
                p += 2
            out.append(buf[p:p + n * 2].decode("utf-16le", "replace"))
    return out


def chunks(buf, start, end):
    o = start
    while o + 8 <= end:
        typ, hsz, size = struct.unpack_from("<HHI", buf, o)
        if size == 0:
            break
        yield o, typ, hsz, size
        o += size


def read_manifest(buf):
    """Return [(element name, [(attr name, dataType, dataValue)])] from binary XML."""
    strings, elements = [], []
    for off, typ, _hsz, _size in chunks(buf, 8, len(buf)):
        if typ == 0x0001:
            strings = string_pool(buf, off)
        elif typ == 0x0102:                                    # START_ELEMENT
            _ns, name, astart, asize, acount = struct.unpack_from("<IIHHH", buf, off + 16)
            attrs, a = [], off + 16 + astart
            for _ in range(acount):
                # ns(4) name(4) raw(4) | size(2) res0(1) type(1) data(4)
                _ans, aname, _araw, _vsize, _vres0, vtype, vdata = struct.unpack_from(
                    "<IIIHBBI", buf, a)
                attrs.append((strings[aname], vtype, vdata))
                a += asize
            elements.append((strings[name], attrs))
    return elements


def resolve_resource(arsc, rid):
    """Follow a resource reference to the entry's name, e.g. 0x7f030000 -> ic_launcher."""
    _t, tbl_hsz, _s = struct.unpack_from("<HHI", arsc, 0)
    key_pool, typemap = [], {}
    for o, typ, hsz, size in chunks(arsc, tbl_hsz, len(arsc)):
        if typ != 0x0200:                                      # RES_TABLE_PACKAGE_TYPE
            continue
        _tstr, _lpub, kstr, _lkey = struct.unpack_from("<IIII", arsc, o + 12 + 256)
        key_pool = string_pool(arsc, o + kstr)
        for co, ctyp, chsz, _csize in chunks(arsc, o + hsz, o + size):
            if ctyp == 0x0201:                                 # RES_TABLE_TYPE_TYPE
                typemap.setdefault(arsc[co + 8], []).append((co, chsz))
    tid, idx = (rid >> 16) & 0xFF, rid & 0xFFFF
    if tid not in typemap:
        return None
    co, chsz = typemap[tid][0]
    _count, entries_start = struct.unpack_from("<II", arsc, co + 12)   # offset table at headerSize
    eoff = struct.unpack_from("<I", arsc, co + chsz + idx * 4)[0]
    _esize, _eflags, key = struct.unpack_from("<HHI", arsc, co + entries_start + eoff)
    return key_pool[key]


# ----------------------------------------------------------------- checks

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
    print("APK %s (%.2f MB, %d entries)"
          % (path, os.path.getsize(path) / 1048576.0, len(names)))
    problems = []

    # 1. native Python, per ABI
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
    if not bundles:
        problems.append("no assets/chaquopy/: the Python code is not bundled")
    total = sum(apk.getinfo(n).file_size for n in bundles) / 1048576.0
    print("\nchaquopy bundles: %d entries, %.1f MB uncompressed" % (len(bundles), total))
    for n in bundles:
        if n.endswith((".imy", ".zip", "build.json")):
            print("  %-46s %7.2f MB" % (n.split("assets/chaquopy/", 1)[1],
                                        apk.getinfo(n).file_size / 1048576.0))

    # 2. what is actually inside the bundles
    found, as_zip = set(), 0
    for n in bundles:
        blob = apk.read(n)
        try:
            inner = zipfile.ZipFile(io.BytesIO(blob))
            as_zip += 1
            found.update(e.replace("\\", "/") for e in inner.namelist())
        except zipfile.BadZipFile:
            if b"clipblitz" in blob:
                found.add("(byte scan of %s saw clipblitz)" % n)
    engine_hits = [m for m in ENGINE if any(e.startswith(m) or m in e for e in found)]
    ui_hits = [u for u in UI if any(e == u or e.endswith(u) for e in found)]
    print("\nreadable as zip: %d of %d bundles, %d entries listed" % (as_zip, len(bundles), len(found)))
    print("  engine modules : %d of %d" % (len(engine_hits), len(ENGINE)))
    print("  web assets     : %d of %d" % (len(ui_hits), len(UI)))
    missing = [m for m in ENGINE if m not in engine_hits]
    if missing:
        problems.append("engine modules missing from the APK: %s" % ", ".join(missing))
    if len(ui_hits) < len(UI):
        problems.append("the studio UI is missing from the APK, so the phone could not serve it")

    # 3. the manifest, parsed rather than scanned
    manifest = apk.read("AndroidManifest.xml")
    elements = read_manifest(manifest)
    app = [a for n, a in elements if n == "application"]
    print("\nbinary manifest: %d elements" % len(elements))
    if not app:
        problems.append("no <application> in the manifest")
    else:
        app_attrs = {k: (t, v) for k, t, v in app[0]}
        declared = next((v for k, (t, v) in app_attrs.items()
                         if k == "name" and t == 0x03), None)
        label_pool = None
        print("  application name: %s" % declared)
        if declared != PY_APPLICATION:
            problems.append("the manifest does not start Python at app launch "
                            "(application name is %r, expected %r)" % (declared, PY_APPLICATION))
        icons = {k: v for k, (t, v) in app_attrs.items() if k in ("icon", "roundIcon") and t == 0x01}
        try:
            arsc = apk.read("resources.arsc")
            for key, rid in icons.items():
                resolved = resolve_resource(arsc, rid)
                print("  %-9s 0x%08x -> %s" % (key, rid, resolved))
                if key == "icon" and resolved != "ic_launcher":
                    problems.append("launcher icon resolves to %r, expected ic_launcher" % resolved)
                if key == "roundIcon" and resolved != "ic_launcher_round":
                    problems.append("round icon resolves to %r, expected ic_launcher_round" % resolved)
            if not icons:
                problems.append("the manifest declares no launcher icon")
        except KeyError:
            problems.append("no resources.arsc to resolve the icon through")
    activities = [n for n, _a in elements if n == "activity"]
    print("  activities: %s" % activities)
    if not activities:
        problems.append("the manifest declares no activity")

    # 4. hygiene: nothing private inside the APK
    leaks = [n for n in names
             if n.endswith(".env") or "/data/" in n or n.endswith(("boot.log", ".pyo"))]
    if leaks:
        problems.append("unexpected files inside the APK: %s" % ", ".join(leaks[:4]))

    print("")
    if problems:
        for p in problems:
            print("FAIL  %s" % p)
        return 1
    print("PASS  CPython, the engine, the studio UI and the wiring are all inside the APK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
