"""ClipBlitz as an agent tool: hand it a video, ask for N clips, get files back.

Any coding agent equipped with this can be told "here is a video, cut me four
clips" and get real vertical files with titles, hooks, scores and the measured
reasoning behind each one - no studio window, no manual export step.

Two front doors onto the SAME engine that ships in the app:

    python -m clipblitz.agent cut video.mp4 --clips 4           # one shot, prints JSON
    python -m clipblitz.agent mcp                               # MCP server on stdio

The MCP door is what an agent runtime (Claude Code and friends) holds open. It
speaks JSON-RPC 2.0 over stdin/stdout, one compact JSON object per line, and
exposes the tools in TOOLS below.

Where the work actually runs: if a ClipBlitz Studio server is already listening on
127.0.0.1 (the usual case for an owner who has the studio open) the job is created
through its own HTTP API, because the studio owns data/jobs.json and one writer is
one truth. If no studio answers, the exact same pipeline runs in-process. Both
paths land clips in <data>/clips and both feed the same local learning store, so an
agent's choices train the same engines you use by hand.

Nothing here ever posts, uploads or publishes anything. Editing is the job; the
rights gate and the publish buttons stay in the studio, in front of a human.
"""

import argparse
import contextlib
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from . import clipbench, learning, pipeline, rights, scout, trainer
from .config import CONFIG, APP_VERSION

VERSION = APP_VERSION
DEFAULT_CLIPS = 3
MAX_CLIPS = 8
MCP_PROTOCOL = "2024-11-05"
ENGINES = ("prox", "b2", "both")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")

TERMINAL = ("done", "error")


def log(msg):
    """Diagnostics go to stderr only: stdout belongs to the JSON-RPC stream."""
    print(f"[clipblitz] {msg}", file=sys.stderr, flush=True)


def is_url(s):
    return str(s or "").lower().startswith(("http://", "https://"))


def port_open(port, timeout=1.0):
    """Is something listening? A plain TCP connect, so it is instant.

    This is the routing decision, deliberately NOT a /api/health call: health measures
    the hardware and probes ffmpeg/yt-dlp, which takes seconds on a cold server, and a
    slow probe must never be mistaken for "no studio here".
    """
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def clip_path(name):
    """Absolute path of a rendered clip from the /clips/<file> URL the job stores."""
    base = os.path.basename((name or "").split("?")[0])
    return os.path.join(CONFIG["data_dir"], "clips", base) if base else None


def _public_clip(c, index, base_url=None):
    name = os.path.basename((c.get("file") or "").split("?")[0])
    path = clip_path(name) if name else None
    return {
        "index": index,
        "title": c.get("title"),
        "hook": c.get("hook"),
        "score": c.get("score"),
        "engine": c.get("engine_id"),
        "engine_name": c.get("engine"),
        "start": c.get("start"), "end": c.get("end"), "duration": c.get("duration"),
        "factors": c.get("factors") or {},
        "verdict": c.get("verdict"),
        "reason": c.get("reason"),
        "transformative_work": c.get("transformative") or [],
        "file": path,
        "exists": bool(path and os.path.isfile(path)),
        "url": (f"{base_url}/clips/{name}" if base_url and name else None),
    }


# --------------------------------------------------------------- the studio API

class Studio:
    """The running studio's own HTTP API, when there is one.

    Every method returns None instead of raising when no studio answers, so callers
    can fall back to running the pipeline in-process without try/except litter.
    """

    def __init__(self, port=None, timeout=6):
        self.port = int(port or CONFIG["port"])
        self.timeout = timeout
        self.base_url = f"http://127.0.0.1:{self.port}"

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def _call(self, path, data=None, method=None, headers=None, timeout=None):
        url = self.base + path
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        return json.load(urllib.request.urlopen(req, timeout=timeout or self.timeout))

    def health(self):
        # generous on purpose: the first /api/health of a session measures hardware and
        # probes ffmpeg + yt-dlp and can take several seconds on a cold start
        try:
            return self._call("/api/health", timeout=15)
        except (OSError, ValueError, urllib.error.URLError):
            return None

    def upload(self, path, name, engine, top_n, style):
        size = os.path.getsize(path)
        qs = urllib.parse.urlencode({"name": name, "engine": engine, "top_n": top_n,
                                     "style": style or ""})
        with open(path, "rb") as f:      # streamed: a long video never sits in memory
            return self._call("/api/upload?" + qs, data=f, method="POST",
                              headers={"Content-Length": str(size),
                                       "Content-Type": "application/octet-stream"},
                              timeout=3600)

    def from_url(self, url, engine, top_n, style):
        qs = urllib.parse.urlencode({"url": url, "engine": engine, "top_n": top_n,
                                     "style": style or ""})
        return self._call("/api/from_url?" + qs, data=b"", method="POST")

    def set_rights(self, job_id, answer):
        body = json.dumps({"answer": answer}).encode("utf-8")
        try:
            return self._call(f"/api/job/{job_id}/rights", data=body, method="POST",
                              headers={"Content-Type": "application/json"})
        except Exception:
            return None

    def job(self, job_id, light=True):
        try:
            return self._call(f"/api/job/{job_id}" + ("?light=1" if light else ""))
        except Exception:
            return None

    def job_full(self, job_id):
        """The whole job, transcript and waveform included.

        Polling uses ?light=1 (segments are the bulk of a job), but the copyright-safety
        report measures the audio against the transcript, so the final read is the full
        one. A light job must never be fed to risk_report: with no transcript loaded every
        second looks like a gap, which would invent a music-bed flag out of missing data.
        """
        return self.job(job_id, light=False)

    def train(self):
        """Fit the taste model through the studio that owns the store, so one writer
        stays one truth. Returns None when the studio will not answer."""
        try:
            return self._call("/api/train", data=b"{}", method="POST",
                              headers={"Content-Type": "application/json"})
        except Exception:
            return None

    def scout_search(self, query, limit=10):
        """Metadata-only discovery through the studio. A refused search (502 carries
        the real reason) comes back as its payload rather than a second attempt."""
        body = json.dumps({"query": query, "limit": limit}).encode("utf-8")
        try:
            return self._call("/api/scout/search", data=body, method="POST",
                              headers={"Content-Type": "application/json"},
                              timeout=240)
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8", "replace"))
            except (ValueError, OSError):
                return None
        except Exception:
            return None

    def scout_queue(self):
        try:
            return self._call("/api/scout")
        except Exception:
            return None

    def clipbench(self, run=False):
        """The last board, or a fresh one. The scoring pass stays in the studio that
        owns the stores; a refused run comes back as its payload, never as a guess."""
        if run:
            try:
                return self._call("/api/clipbench", data=b"{}", method="POST",
                                  headers={"Content-Type": "application/json"},
                                  timeout=240)
            except urllib.error.HTTPError as e:
                try:
                    return json.loads(e.read().decode("utf-8", "replace"))
                except (ValueError, OSError):
                    return None
            except Exception:
                return None
        try:
            return self._call("/api/clipbench")
        except Exception:
            return None


# ------------------------------------------------------------------- start + wait

def start(video, clips=DEFAULT_CLIPS, engine="b2", style=None, answer=None, port=None,
          local=False):
    """Create the job. Returns (job_id, where_it_runs: "studio"|"local").

    Routing rule: if a studio is listening on the port, the job goes through it.
    A studio keeps data/jobs.json in memory and rewrites the whole file, so a second
    process that writes jobs on its own would have its job dropped by the studio's
    next save - a lost job that only shows up later as "where did my clips go".
    So: no listener means run in-process; a listener that will not answer the API is
    an error the caller can see (with local=True as the deliberate override).
    """
    clips = max(1, min(int(clips or DEFAULT_CLIPS), MAX_CLIPS))
    engine = engine if engine in ENGINES else "b2"
    st = Studio(port)
    if not local and port_open(st.port):
        health = st.health()
        if not health:
            raise RuntimeError(
                f"a ClipBlitz Studio is listening on port {st.port} but did not answer "
                "/api/health (it may be mid-render, or wedged). Retry, or run with "
                "local=True to cut in this process instead - that risks the studio's "
                "next save dropping this job from jobs.json.")
        if is_url(video):
            res = st.from_url(video, engine, clips, style)
        else:
            path = os.path.abspath(video)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"no such video: {path}")
            res = st.upload(path, os.path.basename(path), engine, clips, style)
        job_id = (res or {}).get("job_id")
        if not job_id:
            raise RuntimeError(f"the studio refused the job: {res}")
        if answer:
            st.set_rights(job_id, answer)
        log(f"studio {health.get('version')} accepted the job; it owns this render")
        return job_id, "studio"
    return _local_start(video, clips, engine, style, answer), "local"


def _local_start(video, clips, engine, style, answer):
    """The same pipeline, in this process. Used when no studio is listening."""
    if is_url(video):
        job_id = pipeline.new_job(video[:60], style=style, top_n=clips, engine=engine,
                                  source={"kind": "url", "url": video})
        if answer:
            pipeline.set_rights(pipeline.JOBS[job_id], answer)
        pipeline.start_from_url(job_id, video)
        return job_id
    path = os.path.abspath(video)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no such video: {path}")
    job_id = pipeline.new_job(os.path.basename(path), style=style, top_n=clips,
                              engine=engine,
                              source={"kind": "upload", "label": os.path.basename(path)})
    if answer:
        pipeline.set_rights(pipeline.JOBS[job_id], answer)
    pipeline.start(job_id, path)
    return job_id


def wait(job_id, seconds=1800, port=None, poll=2.0):
    """Block until the job is done or failed. Returns the job dict, or the last
    snapshot seen when the wait times out (with its status still queued/running)."""
    st = Studio(port)
    deadline = time.time() + max(5.0, float(seconds))
    info = None
    while time.time() < deadline:
        info = st.job(job_id) or pipeline.JOBS.get(job_id)
        if not info:
            return {"id": job_id, "status": "error", "error": "unknown job"}
        if info.get("rights_hold"):
            break          # the strict clearance gate is holding this render by design:
                           # waiting would sit here for the whole timeout with no progress
        if info.get("status") in TERMINAL:
            # one full read at the end: the terminal report (and the risk report built
            # from it) needs the transcript, which the polling copy does not carry
            return st.job_full(job_id) or info
        time.sleep(poll)
    return info or {"id": job_id, "status": "error", "error": "no job info"}


def job_summary(job, base_url=None):
    clips = job.get("clips") or []
    return {
        "job": job.get("id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "progress": job.get("progress"),
        "engine": job.get("engine_id"),
        "engine_name": job.get("engine"),
        "content_type": job.get("content_type"),
        "duration": job.get("duration"),
        "source": job.get("source"),
        "rights": job.get("rights_ok"),
        "top_n": job.get("top_n"),
        "candidates": len(job.get("candidates") or []),
        "receipt": job.get("receipt"),
        "error": job.get("error"),
        "clips": [_public_clip(c, i + 1, base_url) for i, c in enumerate(clips)],
    }


def cut(video, clips=DEFAULT_CLIPS, engine="b2", style=None, answer=None, seconds=1800,
        port=None, base_url=None, local=False):
    """The whole job an agent actually wants: start it, wait, report the files."""
    if not (is_url(video) or os.path.isfile(os.path.abspath(str(video)))):
        return {"ok": False, "error": f"no such video: {video}"}
    try:
        job_id, where = start(video, clips, engine, style, answer, port, local=local)
    except (RuntimeError, FileNotFoundError, urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": str(e)[:400]}
    st = Studio(port)
    base_url = base_url or (st.base_url if where == "studio" else None)
    job = wait(job_id, seconds, port)
    out = job_summary(job, base_url)
    out["ok"] = job.get("status") == "done" and bool(out["clips"])
    out["ran"] = where
    out["risk"] = rights.risk_report(job)
    if job.get("rights_hold"):
        # the strict clearance gate refused to render. An agent must never answer the
        # rights question for the owner, so this is a clean stop with the way forward.
        out["ok"] = False
        out["held"] = True
        out["error"] = ("the strict clearance gate is holding this source before it "
                        "renders - answer the rights question (or record an override) "
                        "in the studio's Clips screen, then re-run")
    elif not out["ok"] and not out.get("error"):
        out["error"] = ("timed out before the clips were ready" if job.get("status")
                        not in TERMINAL else job.get("error"))
    return out


# ------------------------------------------------------------------- MCP surface

CUT_SCHEMA = {
    "type": "object",
    "properties": {
        "video": {"type": "string",
                  "description": "Absolute/relative path to a local video file, or an "
                                 "http(s) URL (YouTube via yt-dlp, or a direct media link)."},
        "clips": {"type": "integer", "minimum": 1, "maximum": MAX_CLIPS,
                  "description": f"How many clips to cut (default {DEFAULT_CLIPS})."},
        "engine": {"type": "string", "enum": list(ENGINES),
                   "description": "prox, b2, or both. Default b2."},
        "style": {"type": "string", "description": "Caption style id (optional)."},
        "rights": {"type": "string", "enum": sorted(pipeline.RIGHTS_IDS),
                   "description": "Record the rights answer for this source, when the "
                                  "user has already told you. Never guess it."},
        "wait_seconds": {"type": "integer", "default": 1800,
                         "description": "How long to wait for the render before "
                                        "returning the job id to poll instead."},
        "local": {"type": "boolean", "default": False,
                  "description": ("Cut in this process instead of a running studio. Only "
                                  "correct when the studio is known to be stale; a live "
                                  "studio can otherwise drop this job when it saves.")},
    },
    "required": ["video"],
}

JOB_SCHEMA = {"type": "object", "properties": {"job": {"type": "string"}}, "required": ["job"]}

TOOLS = [
    {"name": "cut_clips",
     "description": ("Cut N vertical shorts out of one long video with the ClipBlitz "
                     "engine, and return the rendered .mp4 files with titles, hooks, "
                     "scores and the measured reason each was picked. Ends the render "
                     "when it completes; if it is still running, returns the job id."),
     "inputSchema": CUT_SCHEMA},
    {"name": "job_status",
     "description": "Status and stage of a job started earlier (poll a long render with this).",
     "inputSchema": JOB_SCHEMA},
    {"name": "job_clips",
     "description": "The clips a finished job produced, with file paths and honest scores.",
     "inputSchema": JOB_SCHEMA},
    {"name": "risk_report",
     "description": ("Copyright-safety measurements for a job: third-party-looking audio "
                     "spans, where the source came from, whether a licence is recorded, "
                     "and which clips carry the fewest transformative layers. This is not "
                     "claim immunity and must not be reported as such."),
     "inputSchema": JOB_SCHEMA},
    {"name": "edit_receipt",
     "description": ("The written edit receipt for a job: exact windows, engine, the "
                     "transformative work applied, and sha256 hashes of the source and "
                     "each render."),
     "inputSchema": JOB_SCHEMA},
    {"name": "learning_state",
     "description": ("What the two engines have learned from this owner's kept cuts so "
                     "far, per engine, including how many more choices each engine needs "
                     "before it starts adapting."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "train_model",
     "description": ("Fit or refresh the local taste model from this install's own "
                     "judge history and the user's real choices, and report the gate "
                     "decision - it activates only when a held-out slice of real choices "
                     "says it ranks kept cuts above the candidates they beat. Local, "
                     "deterministic, stdlib only; it never touches the render engines."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "clearance_certificate",
     "description": ("Write and return the clearance certificate for a job: the risk "
                     "report, the licence record, the edit receipt and the sha256 of the "
                     "source and every render, bundled with a digest of itself so a "
                     "third party can re-check it against the files themselves. It is "
                     "not a licence and it cannot make a use safe or claim-proof."),
     "inputSchema": JOB_SCHEMA},
    {"name": "scout_search",
     "description": ("Metadata-only discovery for a niche: titles, channels, view "
                     "counts and durations (nothing is downloaded). The scout ranks "
                     "what it finds with measured features and the owner's own judged "
                     "history. Making a proposal stays the owner's decision, in the "
                     "studio."),
     "inputSchema": {"type": "object",
                     "properties": {
                         "query": {"type": "string",
                                   "description": "the niche to search for"},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 20,
                                   "default": 10}},
                     "required": ["query"]}},
    {"name": "scout_queue",
     "description": ("The scout queue as the owner sees it: ranked proposals with their "
                     "measured features, the trend read from the metadata, and the clip "
                     "head-to-heads waiting for a human call. An agent never judges."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "clipbench",
     "description": ("The ClipBench scoreboard: every ranking claim this studio makes - "
                     "the shipped baselines, the taste model, the scout model and a "
                     "fixed one-shot weight set that never learns - scored on the same "
                     "chronologically held-out pairs, where a tie is not a win. Reading "
                     "it scores nothing and changes nothing; {\"run\": true} writes one "
                     "board and one log line. It is allowed to report that a model "
                     "lost."),
     "inputSchema": {"type": "object",
                     "properties": {
                         "run": {"type": "boolean", "default": False,
                                 "description": ("score the stores now instead of "
                                                 "returning the last board")}}}},
]


def _job_or_error(job_id):
    """The local snapshot first (it is the full job, transcript included), then the
    studio's own record - fetched in full, because the risk report needs the transcript."""
    job = pipeline.JOBS.get(job_id)
    if job is None:
        st = Studio()
        job = st.job_full(job_id) if port_open(st.port) else None
    return job


def call_tool(name, args):
    """Run one tool. Returns (payload, is_error)."""
    args = args or {}
    if name == "cut_clips":
        video = args.get("video")
        if not video:
            return {"error": "video is required (a file path or an http(s) URL)"}, True
        answer = args.get("rights")
        if answer and answer not in pipeline.RIGHTS_IDS:
            return {"error": f"rights must be one of {sorted(pipeline.RIGHTS_IDS)}"}, True
        res = cut(video, clips=args.get("clips", DEFAULT_CLIPS),
                  engine=args.get("engine", "b2"), style=args.get("style"),
                  answer=answer, seconds=args.get("wait_seconds", 1800),
                  local=bool(args.get("local")))
        return res, not res.get("ok")
    if name in ("job_status", "job_clips"):
        job = _job_or_error(args.get("job", ""))
        if not job:
            return {"error": "unknown job"}, True
        out = job_summary(job)
        if name == "job_status":
            out.pop("clips", None)
        return out, False
    if name == "risk_report":
        job = _job_or_error(args.get("job", ""))
        if not job:
            return {"error": "unknown job"}, True
        return rights.risk_report(job), False
    if name == "edit_receipt":
        job = _job_or_error(args.get("job", ""))
        if not job:
            return {"error": "unknown job"}, True
        path = rights.write_receipt(job)
        data = rights.receipt(job)
        return {"written_to": path, "receipt": data}, False
    if name == "clearance_certificate":
        job = _job_or_error(args.get("job", ""))
        if not job:
            return {"error": "unknown job"}, True
        if not rights.enabled():
            return {"enabled": False,
                    "reason": "the clearance layer is off (CB_LAB=0)"}, False
        data = rights.certificate(job)
        return {"written_to": rights.write_certificate(job, data=data),
                "certificate": data}, False
    if name == "scout_search":
        query = str(args.get("query") or "").strip()
        if not query:
            return {"error": "query is required (the niche to search for)"}, True
        st = Studio()
        res = st.scout_search(query, args.get("limit") or 10) if port_open(st.port) else None
        if res is None:
            res = scout.search(query, args.get("limit") or 10)
        return res, bool(res.get("error"))
    if name == "scout_queue":
        st = Studio()
        res = st.scout_queue() if port_open(st.port) else None
        if res is None:
            res = scout.queue()
        return res, False
    if name == "clipbench":
        st = Studio()
        want = bool(args.get("run"))
        res = st.clipbench(run=want) if port_open(st.port) else None
        if res is None:
            res = clipbench.run(reason="mcp") if want else clipbench.state()
        return res, False
    if name == "learning_state":
        return learning.profile(), False
    if name == "train_model":
        st = Studio()
        res = st.train() if port_open(st.port) else None
        if res is not None:
            return res, False
        # no studio answering: the same fit, in this process, against the same store
        return trainer.run_fit(reason="mcp"), False
    return {"error": f"unknown tool: {name}"}, True


def _result(mid, payload):
    return {"jsonrpc": "2.0", "id": mid,
            "result": {"content": [{"type": "text",
                                    "text": json.dumps(payload, ensure_ascii=False)}]}}


def handle(msg):
    """One JSON-RPC message in, one response out (None for notifications)."""
    if not isinstance(msg, dict):
        return None
    method, mid = msg.get("method"), msg.get("id")
    if mid is None and method:                     # notification: never answer
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": MCP_PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "clipblitz-studio", "version": VERSION}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        if not name:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": "params.name is required"}}
        try:
            payload, is_err = call_tool(name, params.get("arguments") or {})
        except Exception as e:                     # a tool fault is data, not a crash
            payload, is_err = {"error": f"{type(e).__name__}: {e}"}, True
        res = _result(mid, payload)
        if is_err:
            res["result"]["isError"] = True
        return res
    if method in ("resources/list", "prompts/list"):
        key = method.split("/")[0]
        return {"jsonrpc": "2.0", "id": mid, "result": {key: []}}
    if method is None:
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def mcp_main(stream_in=None, stream_out=None):
    """stdio loop. One JSON object per line; nothing else ever touches stdout."""
    inp = stream_in or sys.stdin
    out = stream_out or sys.stdout
    log(f"MCP server up (ClipBlitz {VERSION}, studio port {CONFIG['port']})")
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            log("ignored a non-JSON line on stdin")
            continue
        # any engine print() must not corrupt the frame: send it to stderr
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            resp = handle(msg)
        spilled = buf.getvalue().strip()
        if spilled:
            log(spilled[:2000])
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()
    return 0


# ------------------------------------------------------------------------- CLI

def _print(obj, as_json):
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
        return
    if isinstance(obj, dict) and obj.get("clips") is not None and obj.get("ok") is not None:
        print(f"job {obj['job']}  {obj['status']}  ({obj.get('ran')} engine run)")
        for c in obj["clips"]:
            print(f"  {c['index']}. {c['title']}")
            print(f"     {c['start']}s -> {c['end']}s ({c['duration']}s), "
                  f"{c['engine_name']}, score {c['score']}")
            print(f"     {c['file']}")
            if c.get("hook"):
                print(f"     hook: {c['hook']}")
        risk = obj.get("risk") or {}
        if risk.get("flags"):
            print(f"  copyright safety ({risk['level']}):")
            for f in risk["flags"]:
                print(f"     - {f['text']}")
        return
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m clipblitz.agent",
        description="ClipBlitz Studio as an agent tool: video in, vertical clips out.")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("cut", help="cut N clips out of a video")
    c.add_argument("video", help="video file path or http(s) URL")
    c.add_argument("--clips", type=int, default=DEFAULT_CLIPS)
    c.add_argument("--engine", default="b2", choices=list(ENGINES))
    c.add_argument("--style", default=None)
    c.add_argument("--rights", default=None, choices=sorted(pipeline.RIGHTS_IDS))
    c.add_argument("--wait", type=int, default=1800, help="seconds to wait for the render")
    c.add_argument("--local", action="store_true",
                   help="cut in this process even if a studio is listening")
    c.add_argument("--json", action="store_true")

    s = sub.add_parser("status", help="job status")
    s.add_argument("job")
    s.add_argument("--json", action="store_true")

    jc = sub.add_parser("clips", help="the clips of a finished job")
    jc.add_argument("job")
    jc.add_argument("--json", action="store_true")

    r = sub.add_parser("risk", help="copyright-safety report for a job")
    r.add_argument("job")
    r.add_argument("--json", action="store_true")

    rc = sub.add_parser("receipt", help="write and show the edit receipt")
    rc.add_argument("job")
    rc.add_argument("--json", action="store_true")

    cc = sub.add_parser("certificate", help="write and show the clearance certificate")
    cc.add_argument("job")
    cc.add_argument("--json", action="store_true")

    lp = sub.add_parser("learned", help="what the engines have learned so far")
    lp.add_argument("--json", action="store_true")

    sc = sub.add_parser("scout", help="metadata-only discovery for a niche (nothing downloads)")
    sc.add_argument("query")
    sc.add_argument("--limit", type=int, default=10)
    sc.add_argument("--json", action="store_true")

    cb = sub.add_parser("clipbench", help="the scoreboard: every ranking claim on held-out pairs")
    cb.add_argument("--run", action="store_true",
                    help="score a fresh board now (default: the last board)")
    cb.add_argument("--json", action="store_true")

    sub.add_parser("mcp", help="run the MCP server on stdio")
    sub.add_parser("tools", help="print the MCP tool definitions as JSON")

    args = ap.parse_args(argv)
    cmd = args.cmd or "cut"
    if cmd == "mcp":
        return mcp_main()
    if cmd == "tools":
        print(json.dumps(TOOLS, indent=2, ensure_ascii=False))
        return 0
    if cmd == "learned":
        _print(learning.profile(), args.json)
        return 0
    if cmd == "scout":
        res = scout.search(args.query, args.limit)
        _print(res, args.json)
        return 0 if not res.get("error") else 1
    if cmd == "clipbench":
        if not clipbench.enabled():
            print(json.dumps({"enabled": False,
                              "reason": "the scoreboard is off (CB_CLIPBENCH=off or CB_LAB=0)"}))
            return 1
        res = clipbench.run(reason="cli") if args.run else clipbench.state()
        _print(res, args.json)
        return 0
    if cmd in ("status", "clips"):
        job = _job_or_error(args.job)
        if not job:
            print(json.dumps({"error": "unknown job"}))
            return 1
        out = job_summary(job)
        if cmd == "status":
            out.pop("clips", None)
        _print(out, args.json)
        return 0
    if cmd == "risk":
        job = _job_or_error(args.job)
        if not job:
            print(json.dumps({"error": "unknown job"}))
            return 1
        _print(rights.risk_report(job), args.json)
        return 0
    if cmd == "receipt":
        job = _job_or_error(args.job)
        if not job:
            print(json.dumps({"error": "unknown job"}))
            return 1
        path = rights.write_receipt(job)
        _print({"written_to": path, "receipt": rights.receipt(job)}, args.json)
        return 0
    if cmd == "certificate":
        job = _job_or_error(args.job)
        if not job:
            print(json.dumps({"error": "unknown job"}))
            return 1
        data = rights.certificate(job)
        if not data:
            print(json.dumps({"enabled": False,
                              "reason": "the clearance layer is off (CB_LAB=0)"}))
            return 1
        _print({"written_to": rights.write_certificate(job, data=data),
                "certificate": data}, args.json)
        return 0
    # cut
    video = args.video
    if not is_url(video) and not os.path.isfile(os.path.abspath(video)):
        if not re.search(r"\.\w{2,4}$", str(video or "")):
            print(json.dumps({"ok": False, "error": f"no such video: {video}"}))
            return 1
    res = cut(video, clips=args.clips, engine=args.engine, style=args.style,
              answer=args.rights, seconds=args.wait, local=args.local)
    _print(res, args.json or True)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
