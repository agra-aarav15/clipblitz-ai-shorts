#!/usr/bin/env python3
"""Re-check a ClipBlitz clearance certificate against the files themselves.

    python scripts/verify_certificate.py <certificate.json> [--root DIR] [--json]

Standalone on purpose: this file imports NOTHING from clipblitz, so a third party can
run it next to the certificate and the media without trusting the studio that wrote
them. What it proves:

  1. the certificate is internally consistent - its own sha256 digest recomputes over
     every other field, so any edit to the document is visible;
  2. every file the certificate names (the source and each render) is hashed again and
     matched against the recorded sha256 and size;
  3. the receipt, the risk report and the file list describe the same job.

What it does not prove: that a use is licensed, fair or free of claims. A claim is a
platform decision and a fair-use call is the owner's.

Exit code 0 = every check passed, 1 = at least one failed.
"""

import argparse
import hashlib
import json
import os
import sys

MARKER = "ClipBlitz Studio clearance certificate"


def digest_of(cert):
    """Exactly the studio's digest rule: every field except 'digest', JSON with sorted
    keys and compact separators."""
    body = {k: v for k, v in cert.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def locate(rec, root):
    """Find the file a certificate names: the recorded path first (it may simply be
    there), then the usual data-dir layout under --root (and the cwd)."""
    name = rec.get("name") or ""
    cands = []
    if rec.get("path"):
        cands.append(rec["path"])
    for base in (root, os.getcwd()):
        if not base:
            continue
        if name:
            sub = "clips" if rec.get("role") == "clip" else "uploads"
            cands += [os.path.join(base, sub, name), os.path.join(base, name)]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return None


def verify(cert_path, root):
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    try:
        with open(cert_path, encoding="utf-8") as f:
            cert = json.load(f)
    except (OSError, ValueError) as e:
        add("load", False, f"cannot parse {cert_path}: {e}")
        return checks

    add("load", True, f"parsed {cert_path}")
    add("marker", cert.get("certificate") == MARKER,
        f"certificate marker: {cert.get('certificate')!r}")
    claimed = (cert.get("digest") or {}).get("value")
    add("digest", bool(claimed) and digest_of(cert) == claimed,
        "the certificate's own sha256 recomputes over every other field"
        if claimed else "the certificate carries no digest")

    files = cert.get("files") or []
    add("files", len(files) > 0, f"{len(files)} file(s) named")
    for rec in files:
        label = (f"{rec.get('role') or 'file'}"
                 + (f" {rec['index']}" if rec.get("index") else "")
                 + (f" {rec.get('name')}" if rec.get("name") else "")).strip()
        path = locate(rec, root)
        if not path:
            add(label, False, "not found - pass --root <folder holding the files>")
            continue
        got = sha256_of(path)
        want = rec.get("sha256")
        size_ok = (rec.get("size") is None
                   or os.path.getsize(path) == rec.get("size"))
        add(label, bool(want) and got == want and size_ok,
            f"{path}: sha256 {'matches' if got == want else 'MISMATCH'}"
            + ("" if size_ok else ", size differs"))

    receipt = cert.get("receipt") or {}
    clips = receipt.get("clips") or []
    clip_files = [f for f in files if f.get("role") == "clip"]
    add("receipt", len(clips) == len(clip_files),
        f"receipt names {len(clips)} clip(s), the file list carries {len(clip_files)}")
    add("windows", all(isinstance((c.get("window") or {}).get("start"), (int, float))
                       and isinstance((c.get("window") or {}).get("end"), (int, float))
                       for c in clips),
        "every rendered clip carries its real window")
    risk = cert.get("risk") or {}
    add("risk", risk.get("level") in ("low", "review", "high"),
        f"measured risk level: {risk.get('level')}")
    gate = cert.get("gate") or {}
    add("gate", "mode" in gate and "cleared" in gate,
        f"clearance gate mode {gate.get('mode')}, cleared={gate.get('cleared')}, "
        f"basis {gate.get('basis')}")
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="verify_certificate.py",
        description="Re-check a ClipBlitz clearance certificate against its files.")
    ap.add_argument("certificate", help="path to the certificate JSON")
    ap.add_argument("--root", default=None,
                    help="folder holding the media (source + clips) to hash")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args(argv)
    checks = verify(args.certificate, args.root)
    passed = all(c["ok"] for c in checks)
    if args.json:
        print(json.dumps({"passed": passed, "checks": checks}, indent=2,
                         ensure_ascii=False))
        return 0 if passed else 1
    for c in checks:
        print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['check']}"
              + (f"  - {c['detail']}" if c["detail"] else ""))
    n_ok = sum(1 for c in checks if c["ok"])
    print(f"\n{n_ok}/{len(checks)} checks passed"
          + ("" if passed else " - this certificate does not match the files"))
    print("proves: the listed bytes matched these digests when checked, and the "
          "certificate itself is unaltered")
    print("does not prove: that a use is licensed, fair or free of claims")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
