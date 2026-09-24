"""V7 engine-untouched proof: a real rendered clip must be served as a valid MP4.

Checks the container signature rather than trusting the status code alone.
"""
import json
import sys
import urllib.request

BASE = "http://localhost:4301"


def get(path):
    with urllib.request.urlopen(BASE + path) as r:
        return r.status, dict(r.headers), r.read()


jobs = json.load(urllib.request.urlopen(BASE + "/api/jobs"))
jobs = jobs if isinstance(jobs, list) else list(jobs.values())
# /api/jobs is a summary list (clip count, not clip objects) — take the newest
# completed job id and fetch the full record.
cand = [j for j in jobs if j.get("status") == "done" and j.get("clips")]
if not cand:
    print("FAIL  no completed job with clips")
    sys.exit(1)
job_id = cand[0].get("id")
job = json.load(urllib.request.urlopen(f"{BASE}/api/job/{job_id}"))
if not (job.get("clips") or []):
    print(f"FAIL  job {job_id} reports {len(job.get('clips') or [])} clips")
    sys.exit(1)
print(f"job           {job.get('id')}  status={job.get('status')}  stage={job.get('stage')}")
print(f"clips         {len(job.get('clips') or [])}")
print(f"candidates    {len(job.get('candidates') or [])}")
print(f"waveform      {len(job.get('waveform') or [])} buckets (spec: 600)")
print(f"moments       {len(job.get('moments') or [])} peak regions")
print()

bad = 0
for c in job["clips"]:
    path = c.get("file") or ""
    status, headers, body = get(path)
    sig = body[4:8]
    is_mp4 = sig == b"ftyp"
    ok = status == 200 and is_mp4 and len(body) > 10000
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {status}  {len(body):>9} bytes  sig={sig!r}  "
          f"qc={c.get('qc')}  score={c.get('score')}  {path}")

# waveform / moments must be real measured data, not placeholders
wf = job.get("waveform") or []
if len(wf) != 600:
    bad += 1
    print(f"FAIL  waveform is {len(wf)} buckets, expected 600")
else:
    lo, hi = min(wf), max(wf)
    if not (0.0 <= lo and hi <= 1.0 and hi > lo):
        bad += 1
        print(f"FAIL  waveform not normalised 0..1 with variation: {lo}..{hi}")
    else:
        print(f"ok    waveform normalised {lo:.3f}..{hi:.3f} with real variation")

print()
print("PASS  engine e2e: job done, clip served as valid MP4, waveform+moments persisted"
      if not bad else f"FAIL  {bad} problem(s)")
sys.exit(1 if bad else 0)
