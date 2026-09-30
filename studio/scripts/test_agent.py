"""Agent plugin, copyright safety and learning-v2 tests — stdlib only, offline.

Run from the studio root:   python scripts/test_agent.py

Nothing here renders a video or needs ffmpeg: the pipeline is stubbed where a real
render would be, and every assertion is about the parts an agent actually touches.

What is proven:

  1. THE MCP FRAME IS CLEAN. stdout carries exactly one JSON-RPC object per request
     and nothing else (any engine print goes to stderr), notifications get no reply,
     unknown methods get a JSON-RPC error, and a failing tool returns isError data
     instead of killing the server.
  2. THE TOOL SURFACE IS HONEST. Every tool declares a schema; cut_clips refuses an
     invented rights answer and a missing video; and there is no publish/post tool
     at all.
  3. COPYRIGHT SAFETY MEASURES, IT DOES NOT PROMISE. The risk report flags sustained
     non-speech audio, an unrecorded licence and an unanswered rights gate, a licence
     record round-trips and rejects junk, and the edit receipt names the real windows,
     engine and transformative work.
  4. BOTH ENGINES CAN LEARN SEPARATELY. Past its own threshold an engine's kept cuts
     pull that engine's weights away from the shared profile, by at most 5%, and the
     global cap of 10% still holds.
  5. ONE ENTRY POINT REACHES THE AGENT. run.py --tools and run.py --mcp are the same
     doors as python -m clipblitz.agent, and the studio banner never lands on stdout
     where the JSON belongs - which is what lets the packaged EXE serve the plugin.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz.config import CONFIG  # noqa: E402

CONFIG["data_dir"] = tempfile.mkdtemp(prefix="cbs_agent_")

from clipblitz import agent, learning, pipeline, rights, virality  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------- 1. MCP framing

def test_mcp_handshake():
    init = agent.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": agent.MCP_PROTOCOL}})
    check("mcp: initialize answers with the protocol version and a server name",
          init["result"]["protocolVersion"] == agent.MCP_PROTOCOL
          and init["result"]["serverInfo"]["name"] == "clipblitz-studio",
          str(init["result"]["serverInfo"]))
    check("mcp: a notification is never answered",
          agent.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None)
    check("mcp: ping is answered",
          agent.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {})
    err = agent.handle({"jsonrpc": "2.0", "id": 3, "method": "nope/nothing"})
    check("mcp: an unknown method is a JSON-RPC error, not a crash",
          err["error"]["code"] == -32601, str(err["error"]))


def test_tool_surface():
    tools = agent.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    check("tools: the six tools are declared",
          names == {"cut_clips", "job_status", "job_clips", "risk_report",
                    "edit_receipt", "learning_state"}, str(sorted(names)))
    check("tools: every tool has a description and a JSON schema",
          all(t.get("description") and isinstance(t.get("inputSchema"), dict)
              and "properties" in t["inputSchema"] for t in tools))
    check("tools: cut_clips requires a video and caps the clip count",
          agent.CUT_SCHEMA["required"] == ["video"]
          and agent.CUT_SCHEMA["properties"]["clips"]["maximum"] == agent.MAX_CLIPS)
    check("tools: there is no publish, post or upload tool",
          not any(k in n for n in names for k in ("post", "publish", "upload", "deploy")))


def test_tool_calls_are_data_not_crashes():
    res = agent.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                        "params": {"name": "risk_report", "arguments": {"job": "nope"}}})
    check("tools: an unknown job comes back as isError, not an exception",
          res["result"].get("isError") is True)
    payload = json.loads(res["result"]["content"][0]["text"])
    check("tools: the error body is readable JSON", "error" in payload, str(payload))

    res = agent.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                        "params": {"name": "cut_clips", "arguments": {}}})
    payload = json.loads(res["result"]["content"][0]["text"])
    check("tools: cut_clips without a video fails before starting anything",
          res["result"].get("isError") is True and "video is required" in payload["error"])

    res = agent.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": "cut_clips",
                                   "arguments": {"video": "x.mp4", "rights": "whatever"}}})
    payload = json.loads(res["result"]["content"][0]["text"])
    check("tools: an invented rights answer is refused",
          res["result"].get("isError") is True and "rights must be one of" in payload["error"])

    res = agent.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                        "params": {"name": "nope"}})
    check("tools: an unknown tool name is a tool error",
          res["result"].get("isError") is True)


def test_stdio_framing():
    """The whole point of the stdio transport: one JSON object per line, no prints."""
    inp = io.StringIO("\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        "not json at all",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        "",
    ]) + "\n")
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        agent.mcp_main(stream_in=inp, stream_out=out)
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    parsed = []
    ok = True
    for ln in lines:
        try:
            parsed.append(json.loads(ln))
        except ValueError:
            ok = False
    check("stdio: every stdout line is one complete JSON-RPC object", ok and len(lines) == 2,
          f"{len(lines)} line(s)")
    check("stdio: the two requests were answered in order",
          [p.get("id") for p in parsed] == [1, 2] and not parsed[0].get("error"))
    check("stdio: the unparseable line was reported on stderr, not stdout",
          "non-JSON" in err.getvalue())
    check("stdio: nothing leaked into stdout but the replies",
          "".join(lines).count("jsonrpc") == 2)


# ------------------------------------------------------------------- 2. the CLI

def test_cli():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = agent.main(["tools"])
    tools = json.loads(buf.getvalue())
    check("cli: 'tools' prints the schemas as JSON",
          rc == 0 and len(tools) == 6 and tools[0]["name"] == "cut_clips")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        agent.main(["learned", "--json"])
    prof = json.loads(buf.getvalue())
    check("cli: 'learned' prints the real learning profile",
          "events" in prof and "per_engine" in prof)

    res = agent.cut("definitely-not-here.mp4")
    check("cli: cut reports a missing video instead of starting a job",
          res["ok"] is False and "no such video" in res["error"], str(res.get("error")))

    captured = {}

    def fake_local(video, clips, engine, style, answer):
        captured.update(video=video, clips=clips, engine=engine, answer=answer)
        return "stubjob"

    real = agent._local_start
    agent._local_start = fake_local
    try:
        agent.start("/tmp/some.mp4", clips=99, engine="nonsense", answer="own", local=True)
    finally:
        agent._local_start = real
    check("cli: the clip count is clamped and the engine falls back to a real one",
          captured.get("clips") == agent.MAX_CLIPS and captured.get("engine") == "b2",
          str(captured))


def test_run_entry_point():
    """run.py is the only entry point, and the packaged Windows EXE is run.py itself. So
    the agent front door has to be reachable there, and the studio banner must never
    reach stdout in that mode: an agent host is parsing stdout as JSON."""
    import subprocess

    def run(*args, stdin=""):
        return subprocess.run(
            [sys.executable, os.path.join(STUDIO, "run.py"), *args],
            input=stdin, capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=STUDIO, timeout=180,
            env=dict(os.environ, CB_DATA=CONFIG["data_dir"]))

    res = run("--tools")
    tools = json.loads(res.stdout)
    check("entry: run.py --tools prints the tool schemas and exits clean",
          res.returncode == 0 and {t["name"] for t in tools} == {t["name"] for t in agent.TOOLS},
          f"rc={res.returncode}")
    check("entry: the studio banner never leaks into the agent modes",
          "Starting ClipBlitz Studio" not in res.stdout
          and res.stdout.lstrip().startswith("[") and "Starting" not in res.stderr,
          res.stdout[:40])

    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": agent.MCP_PROTOCOL}})
    res = run("--mcp", stdin=init + "\n")
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    reply = json.loads(lines[0]) if lines else {}
    check("entry: run.py --mcp answers initialize over real stdio",
          res.returncode == 0 and len(lines) == 1
          and reply.get("result", {}).get("serverInfo", {}).get("name") == "clipblitz-studio",
          f"{len(lines)} line(s), rc={res.returncode}")
    plain = run("tools")
    check("entry: the same doors work spelled without the dashes",
          plain.returncode == 0 and "cut_clips" in plain.stdout, f"rc={plain.returncode}")


# --------------------------------------------------------- 3. copyright safety

def _job_with_music_bed():
    """A real-shaped job: 60s in, a 20s gap in the transcript with loud audio (the
    shape of a music bed), downloaded from a URL, no rights answer yet."""
    return {
        "id": "safety1", "name": "ep.mp4", "duration": 120.0,
        "engine_id": "b2", "source": {"kind": "youtube", "uploader": "someone-else",
                                      "title": "An episode I did not make"},
        "segments": [{"start": 0.0, "end": 40.0, "text": "talking"},
                     {"start": 60.0, "end": 120.0, "text": "more talking"}],
        "waveform": ([0.1] * 200) + ([0.9] * 100) + ([0.1] * 300),
        "clips": [{"transformative": ["captions burned into the picture",
                                      "vertical reframing with a blur pad"],
                   "start": 0.0, "end": 30.0, "duration": 30.0, "score": 71,
                   "engine_id": "b2", "engine": "B2 Pro X", "title": "A cut",
                   "file": "/clips/none.mp4", "factors": {"payoff": 80}}],
        "rights_ok": None, "licence": None,
    }


def test_risk_report():
    job = _job_with_music_bed()
    report = rights.risk_report(job)
    kinds = {f["kind"] for f in report["flags"]}
    check("safety: an unanswered rights gate is the top flag",
          report["level"] == "high" and "rights" in kinds, str(report["level"]))
    check("safety: the third-party-looking audio span is flagged with a timestamp",
          "audio" in kinds and any(f["at"] == 40.0 for f in report["flags"]))
    check("safety: a source downloaded from elsewhere is flagged with the uploader",
          any(f["kind"] == "source" and "someone-else" in f["text"] for f in report["flags"]))
    check("safety: the report never promises immunity",
          "not" in report["note"].lower() and "legal advice" in report["note"])
    clean = {"id": "x", "rights_ok": "own", "src_name": "mine.mp4",
             "source": {"kind": "upload", "label": "mine.mp4"},
             "clips": [{"transformative": ["a", "b"]}]}
    check("safety: a clean job reports level low, with nothing invented",
          rights.risk_report(clean)["level"] == "low"
          and rights.risk_report(clean)["flags"] == [])

    job["rights_ok"] = "own"
    report = rights.risk_report(job)
    check("safety: answering the gate clears the rights flag",
          not any(f["kind"] == "rights" for f in report["flags"]))

    quiet = dict(job, waveform=[0.05] * 600)
    check("safety: a quiet gap is not called a music bed",
          not any(f["kind"] == "audio" for f in rights.risk_report(quiet)["flags"]))


def test_missing_transcript_never_invents_a_flag():
    """The bug this pins: the job endpoint strips `segments` from its light copy, and a
    risk report built from it used to treat every second as a gap - reporting a
    music-bed flag that was purely missing data. False telemetry is worse than no
    telemetry, so a missing transcript must measure nothing and say that it did."""
    loud = [0.9] * 600
    full = {"id": "t1", "duration": 300.0, "rights_ok": "own", "waveform": loud,
            "segments": [{"start": 0.0, "end": 300.0, "text": "talking the whole way"}],
            "source": {"kind": "upload", "label": "x.mp4"}, "src_name": "x.mp4",
            "clips": [{"transformative": ["a", "b"]}]}
    light = {k: v for k, v in full.items() if k != "segments"}
    check("safety: a full job with no silent stretch reports no audio flag",
          not any(f["kind"] == "audio" for f in rights.risk_report(full)["flags"]))
    r = rights.risk_report(light)
    check("safety: a light job never invents an audio flag from a missing transcript",
          not any(f["kind"] == "audio" for f in r["flags"]))
    check("safety: it says the audio layer was not measured instead",
          r["measured"]["audio"] is False
          and any(c["id"] == "transcript" and c["ok"] is False for c in r["checks"])
          and "not measured" in r["headline"], str(r["headline"][:80]))
    check("safety: speech_gaps measures nothing without a transcript",
          rights.speech_gaps(None, 300.0) == []
          and rights.speech_gaps([], 300.0) == [(0.0, 300.0)])
    silent_video = dict(full, segments=[])
    check("safety: a genuinely speechless, loud video IS flagged",
          any(f["kind"] == "audio" for f in rights.risk_report(silent_video)["flags"]))
    asked = []
    st = agent.Studio()
    st._call = lambda path, **kw: asked.append(path) or {"id": "t1", "segments": []}
    st.job_full("t1")
    check("agent: job_full fetches the job without ?light=1", asked == ["/api/job/t1"], str(asked))


def test_licence_record():
    job = _job_with_music_bed()
    job["rights_ok"] = "licensed"
    ok, err = rights.set_licence(job, {"kind": "nonsense"})
    check("licence: an unknown kind is rejected", ok is False and "kind must be one of" in err)
    ok, err = rights.set_licence(job, {"holder": "Label", "reference": "AGR-991",
                                       "expires": "2030-01-01", "kind": "licensed"})
    check("licence: a real record is stored on the job",
          ok and job["licence"]["reference"] == "AGR-991")
    check("licence: a valid record clears the licence flag",
          not any(f["kind"] == "licence" for f in rights.risk_report(job)["flags"]))
    job["licence"]["expires"] = "2001-01-01"
    check("licence: an expired licence is flagged",
          any(f["kind"] == "licence" and "expired" in f["text"]
              for f in rights.risk_report(job)["flags"]))


def test_edit_receipt():
    job = _job_with_music_bed()
    job["src"] = None
    data = rights.receipt(job)
    check("receipt: it names the job, the engine and the rights answer",
          data["job"] == "safety1" and data["engine"] == "b2" and "rights_answer" in data)
    check("receipt: each clip carries its real window and transformative work",
          data["clips"][0]["window"]["start"] == 0.0
          and len(data["clips"][0]["transformative_work"]) == 2)
    check("receipt: it says what it is not (no licence, no fairness verdict)",
          "not a licence" in data["note"])
    path = rights.write_receipt(job)
    check("receipt: it is written to disk and parses back",
          path and os.path.isfile(path)
          and json.load(open(path, encoding="utf-8"))["job"] == "safety1", str(path))


# ------------------------------------------------------ 4. learning v2 layers

CLIP = {"engine_id": "b2", "score": 80, "duration": 40.0, "laugh_ending": False,
        "hook": "A plain opening line", "title": "A clip"}


def seed(n, engine="b2", laugh=False, **kw):
    for _ in range(n):
        learning.log("post", dict(CLIP, engine_id=engine, laugh_ending=laugh, **kw),
                     {"engine_id": engine})


def test_recency_and_caps():
    now = time.time()
    check("learning: today's choice weighs 1.0", learning._recency({"t": now}, now) == 1.0)
    check("learning: one half-life old weighs about 0.5",
          abs(learning._recency({"t": now - learning.HALF_LIFE_DAYS * 86400}, now) - 0.5) < 1e-6)
    check("learning: recency never grows (a future stamp is still 1.0)",
          learning._recency({"t": now + 86400}, now) <= 1.0)

    learning.reset()
    seed(12, laugh=True)
    adj = learning.adjustment()
    check("learning: every multiplier stays inside the global +/-10% cap",
          adj and all(1 - learning.MAX_DELTA <= v <= 1 + learning.MAX_DELTA
                      for v in adj.values()), str(adj))
    check("learning: the store is versioned now",
          learning.profile()["version"] == learning.STORE_VERSION == 2)


def test_factor_over_index():
    learning.reset()
    job = {"engine_id": "b2",
           "candidates": [{"factors": {"payoff": 60, "hook": 50}},
                          {"factors": {"payoff": 55, "hook": 50}}]}
    for _ in range(3):
        learning.log("post", dict(CLIP, factors={"payoff": 82, "hook": 50}), job)
    check("learning: the factor layer stays inert below its own threshold",
          learning.factor_bias(learning._load()["events"])[0] == {})
    for _ in range(learning.MIN_POOL_EVENTS):
        learning.log("post", dict(CLIP, factors={"payoff": 82, "hook": 50}), job)
    bias, evidence = learning.factor_bias(learning._load()["events"])
    check("learning: keeping a cut that beats its pool on payoff is measured",
          evidence.get("payoff", 0) >= learning.MIN_FACTOR_DELTA, str(evidence))
    check("learning: the factor layer is capped at its own slice",
          bias["payoff"] - 1 <= learning.MAX_FACTOR_DELTA + 1e-9)
    adj = learning.adjustment()
    check("learning: the factor layer actually moved the payoff weight",
          adj["payoff"] > 0.94, f"payoff {adj.get('payoff')}")
    prof = learning.profile()
    check("learning: the profile explains itself with real numbers",
          any("payoff" in w for w in prof["why"]) and prof["factor_choices"] >= 8)


def test_per_engine_refinement():
    learning.reset()
    seed(learning.MIN_ENGINE_EVENTS - 1, engine="b2", laugh=False)
    check("learning: an engine one choice short of its threshold gets no refinement",
          learning.engine_refinement(learning._load()["events"], "b2", time.time()) == {})
    check("learning: an engine with no choices at all gets none either",
          learning.engine_refinement(learning._load()["events"], "prox", time.time()) == {})

    learning.reset()
    seed(20, engine="prox", laugh=True)          # this owner keeps laughs on ProX
    seed(learning.MIN_ENGINE_EVENTS, engine="b2", laugh=False)
    events = learning._load()["events"]
    check("learning: b2 is past its threshold and does get one",
          bool(learning.engine_refinement(events, "b2", time.time())),
          str(learning.engine_refinement(events, "b2", time.time())))
    ref = learning.engine_refinement(events, "b2", time.time())
    check("learning: the engine refinement is capped at 5%",
          all(abs(v - 1) <= learning.MAX_ENGINE_DELTA + 1e-9 for v in ref.values()), str(ref))
    prox, b2 = learning.adjustment("prox"), learning.adjustment("b2")
    check("learning: the two engines now diverge on payoff",
          b2["payoff"] < prox["payoff"], f"b2 {b2['payoff']} vs prox {prox['payoff']}")
    check("learning: the global cap still holds after the engine layer",
          all(1 - learning.MAX_DELTA <= v <= 1 + learning.MAX_DELTA
              for v in list(b2.values()) + list(prox.values())))
    check("learning: engine-specific weights reach the ranking",
          virality._weights("comedy", "b2")["payoff"]
          < virality._weights("comedy", "prox")["payoff"])
    check("learning: a shared run (engine=None) stays on the global profile",
          virality._weights("comedy")["payoff"] > virality._weights("comedy", "b2")["payoff"])
    prof = learning.profile()
    check("learning: the profile reports both engines and what each still needs",
          set(prof["per_engine"]) == {"prox", "b2"}
          and prof["per_engine"]["b2"]["active"] is True
          and prof["per_engine"]["prox"]["remaining"] == 0, str(prof["engine_min_events"]))


def test_routing_never_races_the_studio():
    """A studio keeps data/jobs.json in memory and rewrites the whole file, so a second
    process that writes jobs by itself gets its job dropped on the studio's next save.
    The router must therefore never fall back to in-process editing while a studio is
    listening - it has to say so instead."""
    real_open, real_local, real_cls = agent.port_open, agent._local_start, agent.Studio

    class FakeStudio:
        def __init__(self, port=None, timeout=6):
            self.port = port or 4300
            self.base_url = f"http://127.0.0.1:{self.port}"

        def health(self):
            return None

    started = []
    agent._local_start = lambda *a, **k: started.append(k) or "stubjob"
    try:
        agent.port_open = lambda port, timeout=1.0: False
        job_id, where = agent.start("x.mp4", local=False)
        check("routing: with nothing listening the engine runs in this process",
              where == "local" and job_id == "stubjob" and len(started) == 1)

        agent.port_open = lambda port, timeout=1.0: True
        agent.Studio = FakeStudio
        try:
            agent.start("x.mp4")
            ok, detail = False, "no error was raised"
        except RuntimeError as e:
            ok, detail = "did not answer" in str(e), str(e)[:70]
        check("routing: a listening studio that will not answer is an error, not a silent "
              "second writer", ok, detail)
        check("routing: the escape hatch is explicit",
              agent.start("x.mp4", local=True)[1] == "local")
        # a real file this time, or cut() would legitimately stop at "no such video"
        res = agent.cut(__file__, local=False)
        check("routing: the failure reaches the agent as data, not a traceback",
              res.get("ok") is False and "did not answer" in (res.get("error") or ""),
              str(res.get("error"))[:70])
    finally:
        agent.port_open, agent._local_start, agent.Studio = real_open, real_local, real_cls


def test_agent_job_summary_shape():
    job = {"id": "j1", "status": "done", "stage": "done", "progress": 100,
           "engine_id": "both", "engine": "Both engines", "top_n": 4,
           "clips": [{"file": "/clips/a.mp4", "title": "T", "score": 88, "start": 10.0,
                      "end": 44.0, "duration": 34.0, "engine_id": "b2",
                      "transformative": ["x", "y"]}],
           "candidates": [{}], "rights_ok": "own"}
    out = agent.job_summary(job, base_url="http://127.0.0.1:4300")
    check("agent: the clip summary gives an agent a path, a url and the honest fields",
          out["clips"][0]["file"].endswith("a.mp4")
          and out["clips"][0]["url"] == "http://127.0.0.1:4300/clips/a.mp4"
          and out["clips"][0]["score"] == 88 and out["clips"][0]["engine"] == "b2")
    check("agent: it never claims a clip was published",
          "post" not in out["clips"][0] and out["rights"] == "own")


def main():
    test_mcp_handshake()
    test_tool_surface()
    test_tool_calls_are_data_not_crashes()
    test_stdio_framing()
    test_cli()
    test_run_entry_point()
    test_risk_report()
    test_missing_transcript_never_invents_a_flag()
    test_licence_record()
    test_edit_receipt()
    test_recency_and_caps()
    test_factor_over_index()
    test_per_engine_refinement()
    test_routing_never_races_the_studio()
    test_agent_job_summary_shape()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
