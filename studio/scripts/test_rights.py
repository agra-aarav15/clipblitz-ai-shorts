"""Clearance-gate tests for ClipBlitz Studio - stdlib only, offline, no ffmpeg.

Run from the studio root:   python scripts/test_rights.py

What is proven:

  1. TWO MODES, ONE DEFAULT. Advisory (the shipped default) keeps v4.1.0 behavior -
     the report measures, publishing asks first, a render is never held. Strict - the
     rights.mode toggle - holds imported media before it renders and before it
     publishes; with the lab off (CB_LAB=0) the gate can never be strict.
  2. THE SOURCE REGISTRY RECORDS PROVENANCE. Every import is written to
     data/sources.json (kind, file/URL, size, quick identity, the jobs it fed),
     deduplicated by fingerprint; nothing is written when the lab is off.
  3. THE OVERRIDE IS BY HAND AND DEMANDS A REASON. An unanswered strict job stays
     blocked through any amount of reading; set_override() with a real written reason
     is the only other way through, and it is stored on the job for the certificate.
  4. THE HOLD IS REAL AND RESUMABLE. start() on an unanswered strict job renders
     nothing at all until resume_render() runs after the answer; the demo the studio
     generates itself is never held.
  5. THE CERTIFICATE RE-CHECKS AGAINST THE FILES. One artifact carries the risk
     report, the licence, the receipt and the sha256 of the source and every render,
     plus its own digest; the standalone scripts/verify_certificate.py passes on it,
     and fails when a single byte of a file or of the certificate changes.
  6. THE SAME BEHAVIOR OVER HTTP. /api/gate, /api/post, /api/job/<id>/override,
     /api/job/<id>/certificate and /api/job/<id>/risk answer correctly over one
     keep-alive connection against a real server thread.

Every store lives in a throwaway temp data dir, so this never touches real data.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_rights_")

from clipblitz import agent, pipeline, rights  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def wait_for(pred, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(payload)
    return path


def upload_job(name="gate.mp4", **kw):
    """A real job record with an upload source, without running the pipeline."""
    jid = pipeline.new_job(name, source={"kind": "upload", "label": name}, **kw)
    return jid, pipeline.JOBS[jid]


def test_modes():
    CONFIG["lab"], CONFIG["rights_mode"] = True, "advisory"
    check("gate: the shipped default is advisory", rights.gate_mode() == "advisory")
    check("gate: advisory never holds an unanswered render",
          rights.render_hold({"id": "x", "source": {"kind": "upload"}}) == (False, None))
    CONFIG["rights_mode"] = "strict"
    check("gate: rights.mode=strict is honoured", rights.gate_mode() == "strict")
    CONFIG["rights_mode"] = " Strict "
    check("gate: the mode is case- and whitespace-insensitive",
          rights.gate_mode() == "strict")
    CONFIG["rights_mode"] = "nonsense"
    check("gate: an unknown mode falls back to advisory", rights.gate_mode() == "advisory")
    CONFIG["rights_mode"] = "strict"
    CONFIG["lab"] = False
    check("gate: CB_LAB=0 removes the gate entirely (advisory, never strict)",
          rights.gate_mode() == "advisory" and rights.enabled() is False)
    CONFIG["lab"], CONFIG["rights_mode"] = True, "advisory"


def test_registry():
    src = write(os.path.join(CONFIG["data_dir"], "imports", "first.mp4"), b"a" * 4096)
    jid, job = upload_job("first.mp4")
    entry = rights.remember_source(job, path=src)
    check("registry: an import is recorded with its file, size and quick identity",
          entry and entry["kind"] == "upload" and entry["file"] == "first.mp4"
          and entry["size"] == 4096 and len(entry["quick_sha256"]) == 32
          and entry["jobs"] == [jid], str(entry)[:120])
    check("registry: it lands in data/sources.json",
          os.path.isfile(os.path.join(CONFIG["data_dir"], "sources.json")))
    check("registry: the fingerprint rides on the job for the certificate",
          job.get("source_fp") == entry["fingerprint"])

    jid2, job2 = upload_job("first.mp4")
    again = rights.remember_source(job2, path=src)
    check("registry: a re-import deduplicates to the same entry",
          again["fingerprint"] == entry["fingerprint"]
          and len(rights.sources(99)) == 1
          and again["jobs"] == [jid, jid2], str(again["jobs"]))

    ujob = {"id": "jurl", "source": {"kind": "youtube", "url": "https://youtu.be/abc",
                                     "uploader": "A Channel", "title": "A Talk"}}
    uentry = rights.remember_source(ujob, url="https://youtu.be/abc")
    check("registry: a URL import records where it came from",
          uentry and uentry["kind"] == "youtube" and uentry["url"].endswith("abc")
          and uentry["uploader"] == "A Channel")
    before = len(rights.sources(99))
    djid = pipeline.new_job("demo_source.mp4", demo=True,
                            source={"kind": "demo", "label": "generated demo clip"})
    check("registry: the studio's own demo is not an import",
          rights.remember_source(pipeline.JOBS[djid]) is None
          and len(rights.sources(99)) == before)
    CONFIG["lab"] = False
    check("registry: CB_LAB=0 records nothing",
          rights.remember_source({"id": "joff", "source": {"kind": "upload"}},
                                 path=src) is None)
    CONFIG["lab"] = True


def test_gate_decisions():
    CONFIG["rights_mode"] = "strict"
    _jid, job = upload_job("held.mp4")
    held, why = rights.render_hold(job)
    check("strict: an unanswered import is held before it renders",
          held is True and "strict clearance gate" in why)
    check("strict: reading the gate never clears anything by itself",
          job.get("rights_ok") is None and not job.get("rights_override")
          and rights.render_hold(job)[0] is True and rights.cleared(job) is False)
    job["rights_ok"] = "own"
    check("strict: the owner's answer releases the hold",
          rights.render_hold(job) == (False, None) and rights.cleared(job) is True)

    _jid2, job2 = upload_job("held2.mp4")
    ok, err = rights.set_override(job2, "short")
    check("override: a stub reason is rejected", ok is False and "at least" in err)
    ok, err = rights.set_override(job2, "I have written permission on file", by="owner")
    check("override: a written reason is stored with who and when",
          ok and job2["rights_override"]["reason"].startswith("I have written")
          and job2["rights_override"]["by"] == "owner"
          and job2["rights_override"]["at_iso"], str(job2["rights_override"])[:80])
    check("override: it releases the hold and reads as the basis",
          rights.render_hold(job2) == (False, None)
          and rights.gate_state(job2)["basis"] == "override")

    blocked, why = rights.publish_block(job2)
    check("strict publish: an override is the manual way through",
          blocked is False and why is None)
    _jid3, job3 = upload_job("held3.mp4")
    blocked, why = rights.publish_block(job3)
    check("strict publish: nothing posts unanswered and un-overridden",
          blocked is True and "strict clearance gate" in why
          and rights.publish_block(job3)[0] is True)   # still true on a re-read
    job3["rights_ok"] = "fair_use"
    check("strict publish: an answered job publishes",
          rights.publish_block(job3) == (False, None))

    CONFIG["rights_mode"] = "advisory"
    _jid4, job4 = upload_job("advisory.mp4")
    check("advisory publish: the v4.1.0 rule is unchanged",
          rights.publish_block(job4)[1] == "Confirm your rights for this job first.")
    job4["rights_ok"] = "own"
    check("advisory publish: answering still releases it",
          rights.publish_block(job4) == (False, None))

    _jid5, job5 = upload_job("demo.mp4", demo=True)
    CONFIG["rights_mode"] = "strict"
    check("strict: the studio's own demo is never held",
          rights.render_hold(job5) == (False, None) and rights.external(job5) is False)

    report = rights.risk_report(job3)
    check("risk report: it carries the gate state for the UI",
          report["gate"]["mode"] == "strict" and report["gate"]["cleared"] is True
          and report["gate"]["basis"] == "rights_answer")
    CONFIG["lab"] = False
    check("lab off: the report is exactly the v4.1.0 payload (no gate key)",
          "gate" not in rights.risk_report(job3))
    CONFIG["lab"] = True
    CONFIG["rights_mode"] = "advisory"


def test_hold_and_resume():
    saved, pipeline.process = pipeline.process, _stub_process
    try:
        src = write(os.path.join(CONFIG["data_dir"], "uploads", "hold.mp4"), b"v" * 2048)
        CONFIG["rights_mode"] = "strict"
        jid, job = upload_job("hold.mp4")
        pipeline.start(jid, src)
        check("hold: a strict unanswered job renders nothing at all",
              job.get("rights_hold") is True and job["status"] == "queued"
              and not job["clips"] and "strict clearance gate" in job["stage"])
        pipeline.set_rights(job, "own")
        check("hold: the answer alone does not start it (resume is explicit)",
              job["status"] == "queued")
        check("hold: resume_render starts it once cleared",
              pipeline.resume_render(jid) is True
              and wait_for(lambda: pipeline.JOBS[jid]["status"] == "done"))
        check("hold: the flag is gone after the resume",
              pipeline.JOBS[jid].get("rights_hold") in (False, None))

        jid2, job2 = upload_job("answered.mp4")
        pipeline.set_rights(job2, "own")
        pipeline.start(jid2, src)
        check("strict: a job answered up front renders immediately",
              wait_for(lambda: pipeline.JOBS[jid2]["status"] == "done"))

        pid = pipeline.new_job("demo.mp4", demo=True,
                               source={"kind": "demo", "label": "demo"})
        pipeline.start(pid, src)
        check("strict: the demo renders without any rights answer",
              wait_for(lambda: pipeline.JOBS[pid]["status"] == "done"))

        CONFIG["rights_mode"] = "advisory"
        aid, ajob = upload_job("advisory.mp4")
        pipeline.start(aid, src)
        check("advisory: an unanswered job renders as it always did",
              wait_for(lambda: pipeline.JOBS[aid]["status"] == "done")
              and not ajob.get("rights_hold"))
        check("hold: resume_render refuses a job that was never held",
              pipeline.resume_render(aid) is False)
    finally:
        pipeline.process = saved
        CONFIG["rights_mode"] = "advisory"


def test_autopost_gate():
    saved, pipeline.social.post_clip = pipeline.social.post_clip, _stub_post
    posted.clear()
    try:
        _jid, job = upload_job("autopost.mp4")
        job.update(status="done", clips=[{"file": "/clips/x.mp4"}], rights_pending=True)
        check("autopost: nothing resumes while the gate is unanswered",
              pipeline.resume_autopost(job["id"]) is False and posted == [])
        rights.set_override(job, "permission on file, proceeding deliberately")
        check("autopost: a written override resumes the held post",
              pipeline.resume_autopost(job["id"]) is True
              and wait_for(lambda: posted, 3.0) and not job["rights_pending"])
    finally:
        pipeline.social.post_clip = saved


posted = []


def _stub_post(job, i, targets, on_update=None, wait=False):
    posted.append((job.get("id"), i, list(targets)))


def _stub_process(job_id, src_path):
    pipeline._set(pipeline.JOBS[job_id], status="done", stage="stubbed run", progress=100)


def _cert_job():
    """A finished job with real files on disk: source plus one rendered clip."""
    src = write(os.path.join(CONFIG["data_dir"], "uploads", "cert_src.mp4"), b"source" * 500)
    clip = write(os.path.join(CONFIG["data_dir"], "clips", "cert_1.mp4"), b"clip" * 700)
    jid, job = upload_job("cert.mp4")
    job.update(src=src, src_name="cert_src.mp4", status="done", duration=120.0,
               rights_ok="own", engine_id="b2", mode="heuristic+offline",
               licence={"kind": "own", "holder": "the owner"},
               clips=[{"file": f"/clips/{os.path.basename(clip)}", "title": "Cert clip",
                       "start": 10.0, "end": 44.0, "duration": 34.0, "engine_id": "b2",
                       "engine": "B2 Pro X", "score": 82, "factors": {},
                       "transformative": ["captions burned into the picture",
                                          "vertical reframing"]}])
    rights.remember_source(job, path=src)
    pipeline.save()
    return jid, job, src, clip


def test_certificate():
    CONFIG["lab"] = True
    jid, job, src, clip = _cert_job()
    cert = rights.certificate(job)
    check("certificate: it carries the marker, the gate, the risk and the receipt",
          cert and cert["certificate"].startswith("ClipBlitz Studio")
          and cert["gate"]["mode"] in ("advisory", "strict")
          and cert["risk"]["level"] in ("low", "review", "high")
          and cert["receipt"]["job"] == jid and cert["licence"]["kind"] == "own")
    roles = [(f["role"], f["sha256"] and len(f["sha256"])) for f in cert["files"]]
    check("certificate: it names the source and every render with real sha256 hashes",
          roles == [("source", 64), ("clip", 64)], str(roles))
    check("certificate: the source record rides in from the registry",
          (cert["source_record"] or {}).get("file") == "cert_src.mp4")
    recomputed = rights._digest(cert)
    check("certificate: its own digest recomputes over every other field",
          cert["digest"]["value"] == recomputed and len(recomputed) == 64)
    check("certificate: it says what it proves and what it does not",
          "does_not_prove" in cert["verification"]
          and "claim" in cert["verification"]["does_not_prove"])

    path = rights.write_certificate(job, data=cert)
    check("certificate: it is written to data/certificates", path and os.path.isfile(path))

    def verify():
        return subprocess.run(
            [sys.executable, os.path.join(STUDIO, "scripts", "verify_certificate.py"),
             path, "--root", CONFIG["data_dir"], "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)

    res = verify()
    out = json.loads(res.stdout)
    check("certificate: the standalone verifier passes against the files",
          res.returncode == 0 and out["passed"] is True
          and len(out["checks"]) >= 6, f"rc={res.returncode}")

    doc = json.load(open(path, encoding="utf-8"))
    doc["job_name"] = "tampered"                       # a single edited field...
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    res = verify()
    check("certificate: editing one field of the document fails the digest check",
          res.returncode == 1, f"rc={res.returncode}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(cert, f, indent=2)
    with open(clip, "ab") as f:
        f.write(b"tampered")                          # ...or one byte of a file
    res = verify()
    failed = [c["check"] for c in json.loads(res.stdout)["checks"] if not c["ok"]]
    check("certificate: changing a clip byte after the fact fails the file check",
          res.returncode == 1 and any("clip" in name for name in failed), str(failed))

    CONFIG["lab"] = False
    check("certificate: CB_LAB=0 produces none at all",
          rights.certificate(job) is None and rights.write_certificate(job) is None)
    CONFIG["lab"] = True


def test_api():
    import http.client
    import threading
    from clipblitz import server as studio_server

    CONFIG["rights_mode"] = "strict"
    jid, job, src, clip = _cert_job()
    # unanswered on purpose: the refusal is what this test is about. And a stub on the
    # poster, so a gated-out path can never reach a real network even by mistake.
    job.update(rights_ok=None, rights_override=None)
    pipeline.save()
    saved_post, pipeline.social.post_clip = pipeline.social.post_clip, _stub_post
    posted.clear()
    httpd = studio_server.QuietServer(("127.0.0.1", 0), studio_server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)

        def req(method, path, payload=None):
            body = json.dumps(payload).encode() if payload is not None else None
            headers = {"Content-Type": "application/json"} if body else {}
            conn.request(method, path, body=body, headers=headers)
            res = conn.getresponse()
            return res.status, json.loads(res.read() or b"{}")

        status, gate = req("GET", "/api/gate")
        check("api: /api/gate reports the strict mode and the shipped options",
              status == 200 and gate["mode"] == "strict" and gate["enabled"] is True
              and len(gate["rights"]) == 3, f"{status}")
        status, risk = req("GET", f"/api/job/{jid}/risk")
        check("api: the risk report carries the gate block",
              status == 200 and risk["gate"]["mode"] == "strict")

        status, res = req("POST", "/api/post",
                          {"job_id": jid, "index": 0, "platforms": ["youtube"]})
        check("api: posting an unanswered strict job is refused with the gate state",
              status == 409 and res.get("rights_required")
              and res["gate"]["mode"] == "strict", f"{status}")
        status, res = req("POST", f"/api/job/{jid}/override", {"reason": "no"})
        check("api: an override without a real reason is refused",
              status == 400 and "at least" in res["error"], f"{status}")
        status, res = req("POST", f"/api/job/{jid}/override",
                          {"reason": "written permission from the rights holder"})
        check("api: a written override is recorded and reported",
              status == 200 and res["override"]["reason"].startswith("written")
              and res["gate"]["basis"] == "override", f"{status}")
        blocked, _why = rights.publish_block(pipeline.JOBS[jid])
        check("api: the recorded override is what releases the publish path",
              blocked is False)
        status, res = req("GET", f"/api/job/{jid}/certificate")
        check("api: the certificate endpoint writes and returns the artifact",
              status == 200 and res["written_to"] and len(res["certificate"]["digest"]["value"]) == 64,
              f"{status}")
        check("api: the written certificate is on disk",
              os.path.isfile(res["written_to"]))
        CONFIG["lab"] = False
        status, health = req("GET", "/api/health")
        check("lab off: the health payload has no gate key (v4.1.0 exactly)",
              status == 200 and "gate" not in health, f"{status}")
        status, _res = req("GET", f"/api/job/{jid}/certificate")
        check("lab off: the certificate endpoint refuses cleanly", status == 409)
        CONFIG["lab"] = True
        status, res = req("GET", "/api/job/nope/certificate")
        check("api: an unknown job is a clean 404", status == 404)
    finally:
        pipeline.social.post_clip = saved_post
        httpd.shutdown()
        httpd.server_close()
        CONFIG["rights_mode"] = "advisory"


def test_tool_and_cli():
    CONFIG["lab"] = True
    jid, job, src, clip = _cert_job()
    payload, is_err = agent.call_tool("clearance_certificate", {"job": jid})
    check("mcp: the clearance_certificate tool writes and returns the artifact",
          is_err is False and payload["written_to"]
          and payload["certificate"]["job"] == jid
          and len(payload["certificate"]["digest"]["value"]) == 64)
    payload, is_err = agent.call_tool("clearance_certificate", {"job": "nope"})
    check("mcp: an unknown job is isError, not a crash", is_err is True)
    CONFIG["lab"] = False
    payload, is_err = agent.call_tool("clearance_certificate", {"job": jid})
    check("mcp: with the lab off the tool reports it instead of failing",
          is_err is False and payload.get("enabled") is False)
    CONFIG["lab"] = True

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = agent.main(["certificate", jid, "--json"])
    out = json.loads(buf.getvalue())
    check("cli: 'certificate' prints the written artifact as JSON",
          rc == 0 and out["written_to"] and out["certificate"]["job"] == jid)


def main():
    test_modes()
    test_registry()
    test_gate_decisions()
    test_hold_and_resume()
    test_autopost_gate()
    test_certificate()
    test_api()
    test_tool_and_cli()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
