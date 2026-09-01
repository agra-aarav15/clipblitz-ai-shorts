"""Speech-to-text: OpenAI-compatible API, local faster-whisper, or offline heuristic.

v4: long videos are automatically split into <24 MB WAV parts (on silence boundaries),
transcribed piece by piece and stitched back with time offsets — so the API's 25 MB
upload cap can't kill a 1-hour podcast anymore. Transient provider errors (429/5xx)
are retried with backoff. Every segment may carry word-level timings
[{word, start, end}] which the caption engine uses for word-by-word animation.
"""

import json
import os
import re
import time
import uuid
import urllib.error
import urllib.request

from . import ffmpeg_tools
from .config import CONFIG, ffmpeg

# 16 kHz mono 16-bit WAV = 32 000 bytes/sec; providers cap uploads at 25 MB.
MAX_PART_SECS = 700  # ~22.4 MB per part, safely under the cap


def _multipart(wav, model, word_granularity):
    boundary = uuid.uuid4().hex
    with open(wav, "rb") as f:
        audio = f.read()
    parts = [
        ("model", model),
        ("response_format", "verbose_json"),
    ]
    if word_granularity:
        parts.append(("timestamp_granularities[]", "word"))
    body = b""
    for k, v in parts:
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"audio.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode() + audio + \
            f"\r\n--{boundary}--\r\n".encode()
    return body, boundary


def _post(url, body, boundary):
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "ClipBlitz/0.2",
        **({"Authorization": f"Bearer {CONFIG['ai_key']}"} if CONFIG["ai_key"] else {}),
    })
    last = None
    for attempt in range(3):  # 429/5xx/network → backoff retries, then give up cleanly
        try:
            with urllib.request.urlopen(req, timeout=900) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 413, 422):
                raise  # provider won't take this request as-is — let caller adapt
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        time.sleep(3 + attempt * 5)
    raise RuntimeError(f"transcription service unreachable after retries: {last}")


def _attach_words(segments, words):
    """Slice the global word list into its segments — a word belongs to the segment
    whose span covers its midpoint (boundary words are never dropped)."""
    if not words:
        return segments
    for seg in segments:
        seg["words"] = []
    for w in words:
        token = w["word"].strip()
        if not token:
            continue
        mid = (w["start"] + w["end"]) / 2
        for seg in segments:
            if seg["start"] - 0.05 <= mid <= seg["end"] + 0.05:
                seg["words"].append({"word": token, "start": w["start"], "end": w["end"]})
                break
    return segments


def _segments_from_words(words, max_gap=1.2, max_len=9.0):
    """When the provider returns word timings but no segments (Groq whisper-large-v3-turbo
    with word granularity does exactly this), group the word stream into sentence-ish
    blocks: split on sentence punctuation, big pauses, or a max block length."""
    segs, cur, cur_start = [], [], None
    for w in words:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        if cur and (w["start"] - cur[-1]["end"] > max_gap
                    or cur[-1]["start"] - cur_start > max_len
                    or re.search(r"[.!?…]$", cur[-1]["word"])):
            segs.append({"start": cur_start, "end": cur[-1]["end"],
                         "text": " ".join(x["word"].strip() for x in cur), "words": list(cur)})
            cur, cur_start = [], None
        if not cur:
            cur_start = w["start"]
        cur.append(w)
    if cur:
        segs.append({"start": cur_start, "end": cur[-1]["end"],
                     "text": " ".join(x["word"].strip() for x in cur), "words": list(cur)})
    return segs


def _api_one(wav):
    """One provider call for one (already size-safe) wav file."""
    url = f"{CONFIG['ai_base'].rstrip('/')}/audio/transcriptions"

    def call(word_granularity):
        body, boundary = _multipart(wav, CONFIG["stt_model"], word_granularity)
        return _post(url, body, boundary)

    try:
        data = call(True)          # word timings if the provider supports them
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            raise
        data = call(False)         # provider rejected word granularity — retry plain

    words = [w for w in (data.get("words") or []) if (w.get("word") or "").strip()
             and w.get("end", 0) > w.get("start", 0)]
    segments = data.get("segments") or []
    if segments:
        out = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
               for s in segments if s.get("text", "").strip()]
        return _attach_words(out, words)
    if words:
        return _segments_from_words(words)   # Groq word-mode: words but no segments
    if data.get("text"):
        return [{"start": 0.0, "end": ffmpeg_tools.duration_of(wav),
                 "text": data["text"], "words": []}]
    return []


def _plan_chunks(wav, total):
    """Split a long wav into <MAX_PART_SECS parts, cutting at silence midpoints."""
    silences = []
    proc = ffmpeg_tools.run([ffmpeg(), "-i", wav, "-af", "silencedetect=noise=-30dB:d=0.5",
                             "-f", "null", "-"], timeout=600)
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    silences = list(zip(starts, ends))

    chunks, cursor = [], 0.0
    while total - cursor > MAX_PART_SECS:
        target = cursor + MAX_PART_SECS * 0.85
        cut = None
        for s, e in silences:  # nearest silence midpoint around the target
            mid = (s + e) / 2
            if cut is None or abs(mid - target) < abs(cut - target):
                cut = mid
        if cut is None or cut <= cursor + 60:
            cut = cursor + MAX_PART_SECS  # no usable silence — hard split
        chunks.append((cursor, cut))
        cursor = cut
    chunks.append((cursor, total))
    return chunks


def transcribe_api(wav):
    total = ffmpeg_tools.duration_of(wav)
    if total <= MAX_PART_SECS:
        return _api_one(wav)

    # long video → split on silence, transcribe parts, stitch with offsets
    tmp_dir = os.path.dirname(wav)
    base = os.path.splitext(os.path.basename(wav))[0]
    segments = []
    for i, (start, end) in enumerate(_plan_chunks(wav, total)):
        part = os.path.join(tmp_dir, f"{base}_part{i}.wav")
        ffmpeg_tools.run([ffmpeg(), "-y", "-ss", f"{start:.2f}", "-i", wav,
                          "-t", f"{end - start:.2f}", "-c", "copy", part], timeout=600)
        try:
            for seg in _api_one(part):
                seg["start"] += start
                seg["end"] += start
                for w in seg.get("words", []):
                    w["start"] += start
                    w["end"] += start
                segments.append(seg)
        finally:
            try:
                os.remove(part)
            except OSError:
                pass
    return segments


def transcribe_local(wav):
    from faster_whisper import WhisperModel
    model = WhisperModel(CONFIG["whisper_model"], device="cpu", compute_type="int8")
    segments_iter, _info = model.transcribe(wav, word_timestamps=True)
    out = []
    for s in segments_iter:
        seg = {"start": s.start, "end": s.end, "text": s.text.strip(),
               "words": [{"word": w.word.strip(), "start": w.start, "end": w.end}
                         for w in (s.words or []) if w.word.strip()]}
        if seg["text"]:
            out.append(seg)
    return out


def transcribe_heuristic(wav):
    """No transcription engine available — speech blocks without words (captions fall back)."""
    return [{"start": s["start"], "end": s["end"], "text": "", "words": []}
            for s in ffmpeg_tools.speech_segments(wav)]


def transcribe(wav, mode):
    if mode == "api":
        return transcribe_api(wav)
    if mode == "local":
        return transcribe_local(wav)
    return transcribe_heuristic(wav)
