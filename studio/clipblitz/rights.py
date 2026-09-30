"""Copyright safety: know your rights, see the risk before you publish, keep the receipt.

WHAT THIS IS NOT. Nothing here makes somebody else's video "safe from a copyright
strike". A content-matching system matches the work itself - the audio waveform and
the frames - so no crop, caption, speed change or re-encode removes the match. A
button that promised otherwise would be a claim-evasion tool, and this studio does
not ship one.

WHAT THIS IS. Three honest things that actually reduce the risk of a *claim* on work
you have the right to use, and that put you in a defensible position when one lands:

  1. CLAIM-RISK REPORT   measured, timestamped flags: third-party-looking audio
                         (sustained non-speech spans, i.e. a music bed or a channel
                         theme), a source downloaded from somewhere you may not own,
                         a missing or expired licence, and clips that carry fewer
                         transformative elements than the rest of the set.
  2. LICENCE RECORD      who granted you what, with a reference and an expiry date,
                         stored on the job next to your rights answer.
  3. EDIT RECEIPT        a written manifest of the work this studio actually did to
                         each cut - the windows, engine, burned-in captions, reframe,
                         grade, J-cut - with hashes of the source and each render.

Every flag traces to a measurement this pipeline already took. Nothing is estimated,
nothing is scored out of thin air, and no flag is a legal verdict: a claim is a
platform decision and a fair-use call is the owner's, which is exactly what the
rights gate already says.
"""

import hashlib
import json
import os
import time

from .config import CONFIG

# A span with no transcript at all is not interesting by itself - room tone is silent.
# It matters when it is LONG and still LOUD, which is what a music bed looks like.
MIN_GAP_S = 12.0          # ignore anything shorter than a breath between sentences
LOUD_FLOOR = 0.45         # sustained normalised energy over the span (0..1)

LICENCE_KINDS = {
    "licensed": "A licence or written permission from the rights holder",
    "own": "You own the master and the publishing",
    "public_domain": "Public domain",
    "cc": "Creative Commons (state the variant in the notes)",
    "permission": "Verbal/written go-ahead from the creator",
}

LEVELS = {"low": "No measured risk flags on this job.",
          "review": "Review the flags below before you publish.",
          "high": "Do not publish until you clear the flags below."}


def _mmss(seconds):
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        return "0:00"
    return f"{s // 60}:{s % 60:02d}"


def speech_gaps(segments, duration):
    """The spans with no transcript inside the video. Pure arithmetic on the real
    transcript timeline - no extra ffmpeg pass, no guessing.

    segments is None when the caller only has a light copy of the job (the job endpoint
    strips the transcript for polling). That is NOT the same as a video with no speech:
    with no transcript to compare against, every second would look like a gap and this
    would invent a music-bed flag out of missing data. So a missing transcript measures
    nothing, and the caller records that it measured nothing.
    """
    if segments is None:
        return []
    spans, cursor = [], 0.0
    for s in sorted(segments or [], key=lambda x: x.get("start") or 0.0):
        a, b = s.get("start") or 0.0, s.get("end") or 0.0
        if a - cursor >= MIN_GAP_S:
            spans.append((round(cursor, 1), round(a, 1)))
        cursor = max(cursor, b)
    if duration and duration - cursor >= MIN_GAP_S:
        spans.append((round(cursor, 1), round(duration, 1)))
    return spans


def loud_spans(job):
    """Non-speech spans that are also LOUD: the shape of a music bed, a theme tune or
    an intro sting. Reads the normalised waveform the pipeline already stored (600
    buckets across the video) - a real measurement of the audio, not a fingerprint
    and not a claim about what the track is.

    Needs BOTH the waveform and the transcript: with either missing it returns nothing
    rather than guessing (see speech_gaps)."""
    wave = job.get("waveform") or []
    duration = job.get("duration") or 0.0
    if len(wave) < 8 or not duration:
        return []
    step = duration / len(wave)
    out = []
    for a, b in speech_gaps(job.get("segments"), duration):
        lo = max(0, int(a / step))
        hi = min(len(wave), max(lo + 1, int(b / step)))
        vals = [v for v in wave[lo:hi] if isinstance(v, (int, float))]
        if not vals:
            continue
        level = sum(vals) / len(vals)
        if level >= LOUD_FLOOR and max(vals) >= LOUD_FLOOR:
            out.append({"start": round(a, 1), "end": round(b, 1),
                        "level": round(level, 2), "seconds": round(b - a, 1)})
    return out


def source_flags(job):
    """Flags that come from where the video came from, not from the pixels."""
    src = job.get("source") or {}
    kind = src.get("kind") or ""
    flags = []
    if kind in ("youtube", "url"):
        who = src.get("uploader") or src.get("channel") or ""
        label = src.get("title") or src.get("url") or ""
        flags.append({
            "kind": "source", "at": None,
            "text": ("Downloaded from " + ("YouTube" if kind == "youtube" else "a URL")
                     + (f" ({who})" if who else "") + f": {label[:90]}. "
                     "Cutting material you did not make needs permission, a licence, "
                     "or a genuine transformative purpose - and the platform decides "
                     "the last one."),
        })
    elif not src.get("label") and not job.get("src_name"):
        flags.append({"kind": "source", "at": None,
                      "text": "The source of this video was not recorded on the job."})
    return flags


def _expired(iso):
    if not iso:
        return False
    try:
        t = time.strptime(str(iso)[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return time.mktime(t) < time.time()


def licence_flags(job):
    """The licence record: absent, unknown kind, or expired."""
    lic = job.get("licence")
    answer = job.get("rights_ok")
    flags = []
    if answer == "own":
        return flags          # your own footage needs no licence record
    if not lic:
        if answer:
            flags.append({"kind": "licence", "at": None,
                          "text": "You answered the rights gate but recorded no licence. "
                                  "Add who granted it and a reference - a claim is argued "
                                  "with paperwork, not with memory."})
        return flags
    if lic.get("kind") and lic["kind"] not in LICENCE_KINDS:
        flags.append({"kind": "licence", "at": None,
                      "text": f"Unknown licence kind '{lic['kind']}'. Use one of: "
                              + ", ".join(sorted(LICENCE_KINDS))})
    if _expired(lic.get("expires")):
        flags.append({"kind": "licence", "at": lic.get("expires"),
                      "text": f"The licence expired on {lic.get('expires')} - renew it or "
                              "stop publishing new cuts from this source."})
    if not lic.get("holder") and not lic.get("reference"):
        flags.append({"kind": "licence", "at": None,
                      "text": "The licence record names no holder and carries no reference."})
    return flags


def transformative_flags(job):
    """Per clip: how many real transformative layers the render applied. Fewer layers
    is not an offence - it just means there is less of your own work to point at."""
    clips = job.get("clips") or []
    if not clips:
        return []
    thin = [(i + 1, len(c.get("transformative") or [])) for i, c in enumerate(clips)]
    thin = [t for t in thin if t[1] < 2]
    if not thin:
        return []
    which = ", ".join(f"clip {n} ({k} layers)" for n, k in thin)
    return [{"kind": "transformative", "at": None,
             "text": f"{which} carry the fewest transformative elements (no burned-in "
                     "captions or no grade). Captions and a real reframe are your own "
                     "work on top of the source."}]


def risk_report(job):
    """The whole measured picture for one job. Deterministic, offline, and cheap:
    everything comes from data the pipeline already stored on the job."""
    if not job:
        return {"level": "review", "headline": LEVELS["review"], "flags": [],
                "checks": [], "licence": None, "rights_ok": None}
    if not job.get("rights_ok"):
        flags = [{"kind": "rights", "at": None,
                  "text": "No rights answer on this job yet. Answer the rights gate "
                          "before anything is published."}]
    else:
        flags = []
    flags += source_flags(job)
    for span in loud_spans(job):
        flags.append({
            "kind": "audio", "at": span["start"],
            "text": f"{_mmss(span['start'])}-{_mmss(span['end'])}: {span['seconds']:.0f}s of "
                    "sustained non-speech audio, the shape of a music bed, theme or intro "
                    "sting. If you do not own that track or hold a licence for it, it is "
                    "the most likely thing in this cut to be claimed - replace it, or keep "
                    f"the licence reference on the job (level {span['level']}).",
        })
    flags += licence_flags(job)
    flags += transformative_flags(job)

    measured_audio = job.get("segments") is not None and bool(job.get("waveform"))
    checks = [
        {"id": "rights", "ok": bool(job.get("rights_ok")),
         "label": "Rights answer recorded on the job",
         "detail": job.get("rights_ok") or "unanswered"},
        {"id": "transcript", "ok": measured_audio,
         "label": "The transcript and waveform were available for the audio check",
         "detail": "measured" if measured_audio else
                   "not on this copy of the job - the audio layer was not measured"},
        {"id": "source", "ok": not (job.get("source") or {}).get("kind") in ("url", "youtube"),
         "label": "Source is a local file you brought to the studio",
         "detail": (job.get("source") or {}).get("kind") or "upload"},
        {"id": "audio", "ok": not loud_spans(job),
         "label": "No sustained non-speech audio outside your transcript",
         "detail": f"{len(loud_spans(job))} span(s)"},
        {"id": "licence", "ok": bool(job.get("rights_ok") == "own" or job.get("licence")),
         "label": "Licence record present (not needed when the footage is yours)",
         "detail": (job.get("licence") or {}).get("kind") or "none"},
        {"id": "receipt", "ok": bool(job.get("clips")),
         "label": "Edit receipt can be written from the rendered clips",
         "detail": f"{len(job.get('clips') or [])} clip(s)"},
    ]
    level = "high" if any(f["kind"] == "rights" for f in flags) else (
        "review" if flags else "low")
    headline = LEVELS[level]
    if not measured_audio:
        headline += (" The audio layer was not measured on this copy of the job, so no "
                     "claim is made about music or other third-party audio.")
    return {
        "level": level,
        "headline": headline,
        "flags": flags,
        "checks": checks,
        "measured": {"audio": measured_audio},
        "rights_ok": job.get("rights_ok"),
        "rights_note": _rights_note(),
        "licence": job.get("licence"),
        "licence_kinds": LICENCE_KINDS,
        "note": ("These are measurements, not legal advice. A claim is decided by the "
                 "platform, and whether a use is fair is the owner's call."),
    }


def _rights_note():
    from .pipeline import RIGHTS_NOTE
    return RIGHTS_NOTE


def set_licence(job, payload):
    """Store the licence record on the job. Rejects junk instead of storing it."""
    if not isinstance(payload, dict):
        return False, "licence must be an object"
    kind = (payload.get("kind") or "").strip()
    if kind and kind not in LICENCE_KINDS:
        return False, "kind must be one of: " + ", ".join(sorted(LICENCE_KINDS))
    # a fresh job carries licence=None, so setdefault() is not enough
    record = job.get("licence")
    if not isinstance(record, dict):
        record = {}
        job["licence"] = record
    count = 0
    for field in ("holder", "reference", "expires", "territory", "notes"):
        value = payload.get(field)
        if value is None:
            continue
        record[field] = str(value).strip()[:300]
        count += 1
    if kind:
        record["kind"] = kind
        count += 1
    if not count:
        job["licence"] = job.get("licence") or None
        return False, "no licence fields given"
    record["at"] = time.time()
    return True, None


def _sha256(path):
    """Streamed so a large source video never has to fit in memory."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def receipt(job, hash_source=True):
    """The edit receipt: what this studio did to this source, in writing.

    Every field is a fact taken from the job - the windows it cut, the engine that
    rendered each one, the transformative layers that render actually applied, and
    where each output file is. Hashes are optional because hashing a long source
    video takes real time.
    """
    if not job:
        return None
    src_path = job.get("src")
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    out = {
        "receipt": "ClipBlitz Studio edit receipt",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "job": job.get("id"),
        "job_name": job.get("name"),
        "engine": job.get("engine_id"),
        "content_type": job.get("content_type"),
        "transcription": job.get("mode"),
        "source": dict(job.get("source") or {}),
        "source_file": job.get("src_name"),
        "source_duration": round(float(job.get("duration") or 0.0), 2),
        "source_sha256": _sha256(src_path) if (hash_source and src_path
                                              and os.path.isfile(src_path)) else None,
        "rights_answer": job.get("rights_ok"),
        "rights_note": _rights_note(),
        "licence": job.get("licence"),
        "clips": [],
        "transformative_work": sorted({layer for c in (job.get("clips") or [])
                                       for layer in (c.get("transformative") or [])}),
        "note": ("This receipt records the work applied to the source and the rendering "
                 "parameters used. It is evidence about what this studio did - it is not "
                 "a licence, and it does not make a use fair or free of claims."),
    }
    for i, c in enumerate(job.get("clips") or []):
        name = os.path.basename((c.get("file") or "").split("?")[0])
        path = os.path.join(clips_dir, name) if name else ""
        out["clips"].append({
            "index": i + 1,
            "title": c.get("title"),
            "window": {"start": c.get("start"), "end": c.get("end"),
                       "duration": c.get("duration")},
            "engine": c.get("engine_id"),
            "engine_name": c.get("engine"),
            "score": c.get("score"),
            "factors": c.get("factors"),
            "verdict": c.get("verdict"),
            "transformative_work": c.get("transformative") or [],
            "file": c.get("file"),
            "sha256": _sha256(path) if (hash_source and path
                                        and os.path.isfile(path)) else None,
        })
    return out


def receipt_dir():
    d = os.path.join(CONFIG["data_dir"], "receipts")
    os.makedirs(d, exist_ok=True)
    return d


def receipt_path(job_id):
    return os.path.join(receipt_dir(), f"{job_id}.json")


def write_receipt(job, hash_source=True):
    """Persist the receipt so it survives the job being trimmed out of jobs.json."""
    data = receipt(job, hash_source=hash_source)
    if not data or not data.get("job"):
        return None
    path = receipt_path(data["job"])
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        return None
    return path
