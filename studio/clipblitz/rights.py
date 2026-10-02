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

GATE_MODES = ("advisory", "strict")
SOURCE_VERSION = 1
MAX_SOURCES = 200         # registry entries kept (oldest dropped first)
OVERRIDE_MIN = 8          # a written override reason has to actually say something
OVERRIDE_MAX = 300
CERT_VERSION = 1


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
    out = {
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
    if enabled():
        # the clearance gate rides in the same report the UI already reads. With the
        # lab off there is no gate key at all: exactly the v4.1.0 payload.
        out["gate"] = gate_state(job)
    return out


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


# ------------------------------------------------------------------ clearance gate
#
# The honest inverse of "make everything uncopyrighted". Advisory (the shipped
# default) keeps the v4.1.0 behavior: the report measures, the publish path asks
# before anything leaves the machine, and a render is never held. Strict - the
# rights.mode toggle - additionally holds IMPORTED media before it renders: nothing
# renders or publishes until the owner has answered the rights question or recorded an
# override with a written reason. Nothing here is ever cleared automatically, and
# nothing fingerprints, pitches, speeds or re-encodes a source to dodge matching.


def enabled():
    """The clearance layer lives behind the same master switch as the rest of the lab.
    CB_LAB=0 removes it entirely: advisory behavior, no registry, no overrides, no
    certificate - the studio behaves exactly like v4.1.0."""
    return bool(CONFIG.get("lab", True))


def gate_mode():
    """advisory (shipped default) or strict. Anything unrecognised stays advisory, and
    with the lab off the gate can never be strict."""
    if not enabled():
        return "advisory"
    mode = str(CONFIG.get("rights_mode", "advisory") or "").strip().lower()
    return "strict" if mode == "strict" else "advisory"


def _sources_path():
    return os.path.join(CONFIG["data_dir"], "sources.json")


def _read_sources():
    try:
        data = json.load(open(_sources_path(), encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sources"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"version": SOURCE_VERSION, "sources": []}


def _write_sources(data):
    try:
        os.makedirs(CONFIG["data_dir"], exist_ok=True)
        tmp = _sources_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, _sources_path())
        return True
    except OSError:
        return False


def _quick_hash(path):
    """Fast identity for a media file: size plus its first and last 256 KiB. Labelled
    as quick on purpose - it is how the registry recognises a re-import, not evidence
    (the certificate carries the full sha256)."""
    try:
        size = os.path.getsize(path)
        h = hashlib.sha256()
        h.update(str(size).encode())
        with open(path, "rb") as f:
            h.update(f.read(1 << 18))
            if size > (1 << 18):
                f.seek(max(0, size - (1 << 18)))
                h.update(f.read(1 << 18))
        return h.hexdigest()[:32]
    except OSError:
        return ""


def remember_source(job, path=None, url=None):
    """Record where this import came from, in data/sources.json. Provenance the
    certificate can quote, written once per import and deduplicated by fingerprint; a
    no-op when the lab is off (v4.1.0 keeps no registry)."""
    if not enabled() or not job:
        return None
    src = dict(job.get("source") or {})
    kind = src.get("kind") or ("url" if url else "upload")
    if kind == "demo":
        return None                  # the studio generated the demo itself; nothing imported
    path = path or job.get("src") or ""
    url = url or src.get("url") or ""
    size = os.path.getsize(path) if path and os.path.isfile(path) else None
    quick = _quick_hash(path) if path else ""
    raw = (f"url:{url.strip()}" if url else
           f"file:{quick}:{size}:{os.path.basename(path)}")
    fp = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]
    now = time.time()
    data = _read_sources()
    entry = next((s for s in data["sources"] if s.get("fingerprint") == fp), None)
    if entry is None:
        entry = {"fingerprint": fp, "kind": kind, "first_seen": now,
                 "jobs": [], "file": os.path.basename(path) if path else "",
                 "size": size, "quick_sha256": quick,
                 "quick_note": ("quick identity (size + head/tail), not a full hash - "
                                "the clearance certificate carries the full sha256")}
        for key in ("url", "video_id", "uploader", "channel", "title", "label"):
            if src.get(key):
                entry[key] = src[key]
        data["sources"].append(entry)
        del data["sources"][:-MAX_SOURCES]     # keep the newest MAX_SOURCES entries
    entry["last_seen"] = now
    if job.get("id") and job["id"] not in entry["jobs"]:
        entry["jobs"].append(job["id"])
        entry["jobs"] = entry["jobs"][-20:]
    _write_sources(data)
    job["source_fp"] = fp
    return entry


def sources(limit=50):
    """The registry, newest first. Pure read."""
    try:
        rows = _read_sources()["sources"]
    except Exception:
        return []
    return list(reversed(rows[-max(1, int(limit)):]))


def source_entry(job):
    fp = (job or {}).get("source_fp")
    if not fp:
        return None
    return next((s for s in _read_sources()["sources"]
                 if s.get("fingerprint") == fp), None)


def external(job):
    """Media the studio did not make itself. The generated demo is the only source
    the studio produces, so everything else has an owner to answer for."""
    if not job:
        return False
    if job.get("demo"):
        return False
    return ((job.get("source") or {}).get("kind") or "upload") != "demo"


def _override(job):
    record = (job or {}).get("rights_override")
    return record if isinstance(record, dict) and record.get("reason") else None


def cleared(job):
    """An answer on the job, or a hand-written override. Never anything else."""
    return bool(job and (job.get("rights_ok") or _override(job)))


def set_override(job, reason, by=""):
    """Record the owner's own decision to proceed without clearing. This is the only
    path past a strict gate that is not an answer, it demands a written reason, and the
    record rides in the certificate. Nothing is ever cleared automatically."""
    if not enabled():
        return False, "the clearance layer is off (CB_LAB=0)"
    if not job:
        return False, "unknown job"
    text = str(reason or "").strip()
    if len(text) < OVERRIDE_MIN:
        return False, (f"the override reason must say why you are proceeding "
                       f"(at least {OVERRIDE_MIN} characters)")
    job["rights_override"] = {"reason": text[:OVERRIDE_MAX],
                              "by": str(by or "").strip()[:60] or None,
                              "at": time.time(),
                              "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return True, None


def render_hold(job):
    """(held, why) - strict mode holds imported media BEFORE it renders until the
    owner has answered or recorded an override. Advisory never holds; neither does the
    demo the studio generates itself."""
    if gate_mode() != "strict" or not external(job) or cleared(job):
        return False, None
    return True, ("strict clearance gate - this source is held before rendering until "
                  "you answer the rights question or record an override on the Clips "
                  "screen")


def publish_block(job):
    """(blocked, why) on every publish path, in both modes. Advisory keeps the v4.1.0
    rule (the rights answer comes first); strict additionally refuses to publish a job
    whose measured report says high while nothing has been cleared by hand."""
    if not job:
        return True, "unknown job"
    if job.get("rights_ok"):
        if gate_mode() == "strict" and risk_report(job).get("level") == "high":
            return True, ("strict clearance gate - the risk report on this job is high; "
                          "clear it or record an override before publishing")
        return False, None
    if _override(job):
        return False, None
    if gate_mode() == "strict":
        return True, ("strict clearance gate - answer the rights question or record an "
                      "override with a reason before this clip can be published")
    return True, "Confirm your rights for this job first."


def gate_state(job):
    """The gate as the UI and the certificate show it: the mode, what is holding this
    job, and the override if one was recorded. Pure read."""
    if not job:
        return None
    held, why = render_hold(job)
    ov = _override(job)
    return {
        "enabled": enabled(),
        "mode": gate_mode(),
        "external": external(job),
        "answered": job.get("rights_ok"),
        "cleared": cleared(job),
        "basis": ("rights_answer" if job.get("rights_ok") else
                  ("override" if ov else "none")),
        "held": bool(job.get("rights_hold")),
        "blocked": held,
        "reason": why,
        "override": ov,
    }


def gate_overview():
    """The whole clearance layer in one read, for /api/gate and the UI."""
    from .pipeline import RIGHTS, RIGHTS_NOTE
    return {
        "enabled": enabled(),
        "mode": gate_mode(),
        "modes": {"advisory": "Records the measured risk and asks before publishing. "
                              "Renders are never held.",
                  "strict": "Also holds imported media before rendering: nothing "
                            "renders or publishes until the rights question is "
                            "answered or an override with a written reason is recorded."},
        "rights": RIGHTS,
        "rights_note": RIGHTS_NOTE,
        "sources": len(_read_sources()["sources"]) if enabled() else 0,
        "override_min_chars": OVERRIDE_MIN,
        "note": ("The gate records what the owner decides. It never clears anything by "
                 "itself, and it does not and will not try to evade content matching."),
    }


# ------------------------------------------------------------------- certificate

def certificate(job):
    """One artifact a third party can hold: the risk report, the licence record, the
    edit receipt and the sha256 of the source and every render, bundled with a digest
    of itself. Re-checkable against the files alone (scripts/verify_certificate.py) -
    it proves what this studio measured and which bytes it produced, nothing more."""
    if not enabled() or not job:
        return None
    rep = receipt(job, hash_source=True)      # one hashing pass, reused below
    clips_dir = os.path.join(CONFIG["data_dir"], "clips")
    src_path = job.get("src") or ""
    files = [{
        "role": "source", "name": rep.get("source_file") or None,
        "path": src_path or None,
        "exists": bool(src_path and os.path.isfile(src_path)),
        "size": os.path.getsize(src_path) if src_path and os.path.isfile(src_path) else None,
        "sha256": rep.get("source_sha256"),
    }]
    for i, c in enumerate(rep.get("clips") or []):
        name = os.path.basename((c.get("file") or "").split("?")[0])
        path = os.path.join(clips_dir, name) if name else ""
        files.append({
            "role": "clip", "index": i + 1, "name": name or None,
            "path": path or None,
            "exists": bool(path and os.path.isfile(path)),
            "size": os.path.getsize(path) if path and os.path.isfile(path) else None,
            "sha256": c.get("sha256"),
        })
    payload = {
        "certificate": "ClipBlitz Studio clearance certificate",
        "format": CERT_VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "job": job.get("id"), "job_name": job.get("name"),
        "engine": job.get("engine_id"),
        "gate": gate_state(job),
        "source_record": source_entry(job),
        "rights_answer": job.get("rights_ok"),
        "licence": job.get("licence"),
        "risk": risk_report(job),
        "receipt": rep,
        "files": files,
        "verification": {
            "digest_algorithm": "sha256",
            "digest_over": ("every other field of this certificate, serialised as JSON "
                             "with sorted keys and compact separators"),
            "re_check": ("python scripts/verify_certificate.py <this file> --root "
                         "<folder holding the files>"),
            "proves": ("the studio measured these files at this moment, the listed "
                       "bytes match these sha256 digests, and this certificate is "
                       "unaltered"),
            "does_not_prove": ("that a use is licensed, fair or claim-proof. A claim "
                               "is decided by the platform; a fair-use call is the "
                               "owner's."),
        },
    }
    payload["digest"] = {"algorithm": "sha256", "value": _digest(payload)}
    return payload


def _digest(payload):
    """The certificate's own sha256: every field except the digest itself, JSON sorted
    and compact. scripts/verify_certificate.py recomputes exactly this."""
    body = {k: v for k, v in payload.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def certificate_dir():
    d = os.path.join(CONFIG["data_dir"], "certificates")
    os.makedirs(d, exist_ok=True)
    return d


def certificate_path(job_id):
    return os.path.join(certificate_dir(), f"{job_id}.json")


def write_certificate(job, data=None):
    """Persist the certificate so the owner can hand it to anyone."""
    data = data or certificate(job)
    if not data or not data.get("job"):
        return None
    path = certificate_path(data["job"])
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        return None
    return path
