#!/usr/bin/env python3
"""Offline tests for the live-chat spike radar.

No network and no ffmpeg: these cover the parts that must not regress while a stream
is running — URL parsing, chat message normalisation (including YouTube's replay
wrapper), spike windows, persistence of the tiny chat shape, and the rights gate
before an automatic upload.
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clipblitz import live  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def msgs(n=240, burst=None):
    """One message every 2 s for n buckets; `burst` is (first_bucket, last_bucket, per_s)."""
    rows = []
    for i in range(n):
        count = 1
        if burst and burst[0] <= i <= burst[1]:
            count = int(burst[2] * 5)
        for j in range(count):
            rows.append({
                "id": f"{i}-{j}", "t": i * 5.0 + j * 0.05, "wall": 1000 + i * 5.0,
                "author": f"@u{j}", "text": f"message {i}",
            })
    return rows


def test_canonical():
    cases = [
        ("https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk"),
        ("https://youtu.be/abcdefghijk?t=12", "abcdefghijk"),
        ("https://www.youtube.com/live/abcdefghijk", "abcdefghijk"),
        ("abcdefghijk", "abcdefghijk"),
        ("not a video", ""),
    ]
    for raw, want in cases:
        got = live.video_id(live.canonical(raw))
        check(f"video_id(canonical({raw!r}))", got == want, f"got {got!r}")
    check("video_id accepts a bare id", live.video_id("abcdefghijk") == "abcdefghijk")
    check("canonical always returns a watch URL",
          live.canonical("abcdefghijk") == "https://www.youtube.com/watch?v=abcdefghijk")


def test_twitch_urls():
    check("twitch URL is detected",
          live.platform_of("https://www.twitch.tv/hasanabi") == "twitch")
    check("twitch login is lower-cased", live.twitch_login("https://m.twitch.tv/HasanAbi") == "hasanabi")
    check("twitch session id is prefixed", live.session_id("https://twitch.tv/hasanabi") == "tw_hasanabi")
    check("twitch VOD paths are rejected", live.twitch_login("https://twitch.tv/videos/123") == "")
    check("youtube is still the default", live.platform_of("https://youtu.be/abcdefghijk") == "youtube")


def test_twitch_chat_line():
    line = ("@badge-info=;display-name=SomeUser;id=abc-123;tmi-sent-ts=1794879489123 "
            ":someuser!someuser@someuser.tmi.twitch.tv PRIVMSG #hasanabi :LETSGO :D")
    got = live._twitch_parse(line, 1794879000.0)
    check("twitch line is parsed", got is not None)
    if got:
        check("twitch timestamp becomes a stream offset", abs(got["t"] - 489.123) < 0.01,
              str(got["t"]))
        check("twitch author keeps display name", got["author"] == "@SomeUser", got["author"])
        check("twitch text keeps colons", got["text"] == "LETSGO :D", got["text"])
        check("twitch id is the tag id", got["id"] == "abc-123", got["id"])
    check("a non-chat line is ignored", live._twitch_parse("PING :tmi.twitch.tv") is None)


def test_spikes():
    rows = msgs(240, burst=(40, 44, 12))
    got = live.detect_spikes(rows, before=25, after=15, max_clips=6)
    check("one burst becomes one spike", len(got) == 1, str(len(got)))
    if got:
        s = got[0]
        check("spike starts before the burst", s["start"] <= 40 * 5 - 25 + 0.1,
              f"start={s['start']}")
        check("spike ends after the burst", s["end"] >= 44 * 5 + 15 - 0.1,
              f"end={s['end']}")
        check("spike has a stable key", bool(s.get("key")))
        check("spike records people, not only messages", s["authors"] >= 1)
        check("spike keeps a few chat lines", isinstance(s.get("top"), list))
    flat = live.detect_spikes(msgs(80), before=25, after=15)
    check("flat chat has no spike", flat == [], str(flat))
    quiet = live.detect_spikes(msgs(60, burst=(20, 22, 0.6)), before=25, after=15)
    check("a small blip does not become a clip", len(quiet) == 0, str(quiet))
    many = live.detect_spikes(msgs(400, burst=(40, 44, 20)), before=25, after=15, max_clips=1)
    check("max_clips is respected", len(many) <= 1, str(len(many)))


def test_replay_wrapper():
    action = {
        "replayChatItemAction": {
            "videoOffsetTimeMsec": "38615",
            "actions": [{
                "addChatItemAction": {
                    "item": {
                        "liveChatTextMessageRenderer": {
                            "id": "replay-1",
                            "timestampUsec": "1794876898.5",
                            "authorName": {"simpleText": "@viewer"},
                            "message": {"runs": [{"text": "hello "}, {"text": "room"}]},
                        }
                    }
                }
            }],
        }
    }
    got = live._message(action, {"video_id": "x", "stream_start": 1794876860})
    check("replay wrapper is unwrapped", got is not None)
    if got:
        check("replay offset is the message time", abs(got["t"] - 38.615) < 0.01,
              str(got["t"]))
        check("replay text is joined", got["text"] == "hello room", got["text"])
        check("replay author is kept", got["author"] == "@viewer", got["author"])


def test_live_absolute_time():
    action = {
        "addChatItemAction": {
            "item": {
                "liveChatTextMessageRenderer": {
                    "id": "live-1",
                    "timestampUsec": "1794876898500000",
                    "authorName": {"simpleText": "@live"},
                    "message": {"simpleText": "live now"},
                }
            }
        }
    }
    s = {"video_id": "x", "stream_start": 1794876860}
    got = live._message(action, s)
    check("live absolute time loses the stream start", got and abs(got["t"] - 38.5) < 0.01,
          str(got and got["t"]))
    check("live wall clock is the timestamp", got and abs(got["wall"] - 1794876898.5) < 0.01)


def test_stream_clock():
    s = {"last_message": 100.0, "last_message_wall": time.time() - 10.0}
    now = live._stream_now(s)
    check("stream clock advances while chat is quiet", now and 105 <= now <= 120, str(now))
    s = {"stream_start": time.time() - 30.0}
    now = live._stream_now(s)
    check("stream clock can use the recorded start", now and 29 <= now <= 32, str(now))


def test_auto_post_gate():
    old_connected = live.social.youtube_connected
    try:
        live.social.youtube_connected = lambda: False
        clip = {}
        s = {"auto_post": True, "rights_ok": False}
        live._auto_post(s, clip)
        state = clip.get("post", {}).get("youtube", {})
        check("auto-post waits for rights", state.get("status") == "waiting_for_rights",
              str(state))
        with tempfile.TemporaryDirectory() as d:
            old_data = live.CONFIG.get("data_dir")
            live.CONFIG["data_dir"] = d
            os.makedirs(os.path.join(d, "clips"), exist_ok=True)
            with open(os.path.join(d, "clips", "live_x.mp4"), "wb") as f:
                f.write(b"x")
            try:
                clip2 = {"file": "/clips/live_x.mp4"}
                live._auto_post({"auto_post": True, "rights_ok": True}, clip2)
                state2 = clip2.get("post", {}).get("youtube", {})
                check("auto-post reports missing OAuth instead of failing",
                      state2.get("status") == "not_connected", str(state2))
            finally:
                live.CONFIG["data_dir"] = old_data
        clip3 = {}
        live._auto_post({"auto_post": False, "rights_ok": True}, clip3)
        check("auto-post off writes nothing", clip3 == {}, str(clip3))
    finally:
        live.social.youtube_connected = old_connected


def test_instant_policy():
    """Post-first must render even while chat is still at the burst."""
    import tempfile
    old_data = live.CONFIG.get("data_dir")
    old = {name: getattr(live, name) for name in
           ("_download_subtitles", "_words", "_download_section", "_render_section", "_auto_post")}
    try:
        with tempfile.TemporaryDirectory() as d:
            live.CONFIG["data_dir"] = d
            os.makedirs(os.path.join(d, "live", "fakevid1234"), exist_ok=True)
            s = {"video_id": "fakevid1234", "url": "https://example", "status": "watching",
                 "before": 25, "after": 15, "max_clips": 6, "spikes": [], "clips": [],
                 "last_message": 1499.0, "last_message_wall": time.time(),
                 "last_render": 0, "last_spike_scan": 0, "message_count": 0,
                 "render_policy": "instant", "stage": "", "progress": 0}
            live._SESSIONS["fakevid1234"] = s
            with open(live._chat_path("fakevid1234"), "w", encoding="utf-8") as f:
                for i in range(300):
                    n = 20 if 40 <= i < 45 else 1
                    for j in range(n):
                        f.write(json.dumps({"id": f"{i}-{j}", "t": i * 5.0 + j * .1,
                                            "wall": 1000 + i * 5.0, "author": f"u{j}",
                                            "text": "burst" if n > 1 else "quiet"}) + "\n")
            live._download_subtitles = lambda _s: None
            live._words = lambda _s: []
            live._download_section = lambda _s, _sp: ("/tmp/fake.mp4", 45.0)
            live._render_section = lambda _s, sp, _sec, dur, _w: {
                "file": "/clips/fake.mp4", "title": "t", "description": "d", "hashtags": [],
                "start": sp["start"], "end": sp["end"], "spike_key": sp["key"],
                "messages": sp["messages"], "duration": dur}
            live._auto_post = lambda _s, _c: None
            live._maybe_render_live(s)
            check("post-first renders while chat is hot", len(s["clips"]) == 1,
                  f"clips={len(s['clips'])}")
    finally:
        live.CONFIG["data_dir"] = old_data
        for name, fn in old.items():
            setattr(live, name, fn)


def test_persistence_shape():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "session.json")
        s = {"video_id": "abcdefghijk", "status": "watching", "message_count": 2,
             "spikes": [{"id": "s1"}], "clips": []}
        live._atomic_json(path, s)
        got = live._read_json(path, {})
        check("session JSON round-trips", got.get("video_id") == "abcdefghijk")
        check("session keeps spikes", got.get("spikes") == [{"id": "s1"}])
        bad = os.path.join(d, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        check("a broken session file does not raise", live._read_json(bad, {}) == {})


def main():
    test_canonical()
    test_twitch_urls()
    test_twitch_chat_line()
    test_spikes()
    test_replay_wrapper()
    test_live_absolute_time()
    test_stream_clock()
    test_auto_post_gate()
    test_instant_policy()
    test_persistence_shape()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
