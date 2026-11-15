"""Source-caption tests - stdlib, no network, no ffmpeg.

Run from the studio root:   python scripts/test_captions.py

The link -> clips path must not depend on a speech-to-text key when YouTube already
publishes captions. These tests lock down the json3 and VTT parsers, the segment
shape ARGON receives, and the thin-caption fallback.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
sys.path.insert(0, STUDIO)

from clipblitz import ingest  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


JSON3 = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 2200, "segs": [
            {"utf8": "Why do ", "tOffsetMs": 0},
            {"utf8": "most ", "tOffsetMs": 500},
            {"utf8": "startups ", "tOffsetMs": 900},
            {"utf8": "fail?", "tOffsetMs": 1400},
        ]},
        {"tStartMs": 2400, "dDurationMs": 2400, "segs": [
            {"utf8": "They build ", "tOffsetMs": 0},
            {"utf8": "something ", "tOffsetMs": 600},
            {"utf8": "nobody ", "tOffsetMs": 1200},
            {"utf8": "wants.", "tOffsetMs": 1800},
        ]},
        {"tStartMs": 5200, "dDurationMs": 2600, "segs": [
            {"utf8": "The truth is ", "tOffsetMs": 0},
            {"utf8": "you have to ", "tOffsetMs": 700},
            {"utf8": "talk to ", "tOffsetMs": 1400},
            {"utf8": "users first.", "tOffsetMs": 2000},
        ]},
        {"tStartMs": 8200, "dDurationMs": 2400, "segs": [
            {"utf8": "That single ", "tOffsetMs": 0},
            {"utf8": "change ", "tOffsetMs": 600},
            {"utf8": "saved ", "tOffsetMs": 1100},
            {"utf8": "my company.", "tOffsetMs": 1600},
        ]},
        {"tStartMs": 11000, "dDurationMs": 2200, "segs": [
            {"utf8": "Three mistakes ", "tOffsetMs": 0},
            {"utf8": "engineers ", "tOffsetMs": 700},
            {"utf8": "make ", "tOffsetMs": 1200},
            {"utf8": "with pricing.", "tOffsetMs": 1600},
        ]},
        {"tStartMs": 13600, "dDurationMs": 2400, "segs": [
            {"utf8": "The first one ", "tOffsetMs": 0},
            {"utf8": "is charging ", "tOffsetMs": 700},
            {"utf8": "too ", "tOffsetMs": 1300},
            {"utf8": "little.", "tOffsetMs": 1600},
        ]},
    ]
}

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
Why do most startups fail?

00:00:02.400 --> 00:00:04.800
They build something nobody wants.

00:00:05.200 --> 00:00:07.800
The truth is you have to talk to users first.

00:00:08.200 --> 00:00:10.600
That single change saved my company.

00:00:11.000 --> 00:00:13.200
Three mistakes engineers make with pricing.

00:00:13.600 --> 00:00:16.000
The first one is charging too little.
"""


def test_json3():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "clip.en.json3")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(JSON3, f)
        words = ingest.parse_json3(path)
    check("captions: json3 yields word timings", len(words) == 24, str(len(words)))
    check("captions: word text is clean", words[0]["word"] == "Why do", str(words[0]))
    check("captions: a word starts relative to its event",
          words[3]["start"] == 1.4, str(words[3]))
    check("captions: every word has a positive duration",
          all(w["end"] > w["start"] for w in words))
    check("captions: words stay inside their event",
          words[2]["end"] <= 2.4, str(words[2]))


def test_vtt():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "clip.en.vtt")
        open(path, "w", encoding="utf-8").write(VTT)
        words = ingest.parse_vtt(path)
    check("captions: VTT yields the spoken words", len(words) == 39, str(len(words)))
    check("captions: VTT words carry the cue window",
          words[0]["start"] == 0.0 and words[-1]["end"] == 16.0,
          f"{words[0]} .. {words[-1]}")


def test_captions_for():
    with tempfile.TemporaryDirectory() as d:
        video = os.path.join(d, "yt_demo_123_demo.mp4")
        open(video, "wb").write(b"")
        with open(os.path.join(d, "yt_demo_123_demo.en.json3"), "w", encoding="utf-8") as f:
            json.dump(JSON3, f)
        segments = ingest.captions_for(video)
        check("captions: a downloaded source is transcribed from its sidecar",
              len(segments) >= 3, str(len(segments)))
        check("captions: segments keep word-level data",
              all(s.get("words") for s in segments), str(segments[:1]))
        check("captions: segment text is coherent",
              segments[0]["text"].startswith("Why do"), segments[0]["text"])
        # Thin captions must not replace a real transcript.
        thin = os.path.join(d, "yt_thin_456_thin.mp4")
        open(thin, "wb").write(b"")
        with open(os.path.join(d, "yt_thin_456_thin.en.vtt"), "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi.\n")
        check("captions: a nearly empty caption file falls back to STT",
              ingest.captions_for(thin) == [])


def test_caption_language():
    """A larger translated track must not beat the source-language track."""
    with tempfile.TemporaryDirectory() as d:
        video = os.path.join(d, "yt_demo_lang.mp4")
        open(video, "wb").write(b"")
        with open(os.path.join(d, "yt_demo_lang.en.json3"), "w", encoding="utf-8") as f:
            json.dump(JSON3, f)
        bigger = {"events": []}
        for k in range(8):
            for e in JSON3["events"]:
                e2 = json.loads(json.dumps(e))
                e2["tStartMs"] = e["tStartMs"] + k * 20000
                bigger["events"].append(e2)
        with open(os.path.join(d, "yt_demo_lang.ur-pt.json3"), "w", encoding="utf-8") as f:
            json.dump(bigger, f)
        segments = ingest.captions_for(video)
        check("captions: the source language beats a larger translation",
              segments and segments[0]["text"].startswith("Why do"), segments[0]["text"] if segments else "")
        os.remove(os.path.join(d, "yt_demo_lang.en.json3"))
        segments = ingest.captions_for(video)
        check("captions: a non-English source still gets its own track",
              segments and segments[0]["text"].startswith("Why do"), segments[0]["text"] if segments else "")


def test_download_resilience():
    """A 429 on one caption language is common. It must not throw away a video that
    already downloaded; without --ignore-errors yt-dlp exits and the job dies."""
    import subprocess as sp
    from unittest import mock

    def fake_run(cmd, **kw):
        out = cmd[cmd.index("-o") + 1]
        video = out.replace("%(title).60s", "Demo").replace("%(ext)s", "mp4")
        class P:
            returncode = 1
            stdout = ""
            stderr = "ERROR: Unable to download video subtitles for 'en': HTTP Error 429"
        if getattr(fake_run, "make_video", True):
            with open(video, "wb") as f:
                f.write(b"0" * (1024 * 1024 + 1))
        return P()

    with tempfile.TemporaryDirectory() as d:
        with mock.patch.object(ingest.subprocess, "run", side_effect=fake_run):
            got = ingest._ytdlp("https://www.youtube.com/watch?v=abc123", d)
            check("captions: a caption 429 keeps the downloaded video",
                  got.endswith(".mp4") and os.path.getsize(got) > 1024 * 1024, got)
            fake_run.make_video = False
            try:
                ingest._ytdlp("https://www.youtube.com/watch?v=abc123", d + "2")
                ok = False
            except RuntimeError as e:
                ok = "Download failed" in str(e)
            check("captions: a real download failure still raises", ok)
    check("captions: yt-dlp is told not to abort on a subtitle 429",
          "--ignore-errors" in open(os.path.join(STUDIO, "clipblitz", "ingest.py"),
                                    encoding="utf-8").read())


def test_pipeline_wiring():
    src = open(os.path.join(STUDIO, "clipblitz", "pipeline.py"), encoding="utf-8").read()
    dl = open(os.path.join(STUDIO, "clipblitz", "ingest.py"), encoding="utf-8").read()
    check("captions: the pipeline tries source captions before STT",
          "captions_for(src_path)" in src and "mode = \"captions\"" in src)
    check("captions: yt-dlp downloads auto captions",
          "--write-auto-subs" in dl and "--sub-format" in dl)


def main():
    test_json3()
    test_vtt()
    test_captions_for()
    test_caption_language()
    test_download_resilience()
    test_pipeline_wiring()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
