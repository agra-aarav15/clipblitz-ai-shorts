"""B2 Pro X — cinema layer.

What makes this engine different from the ProX v5 spine it inherits:

1. SCENE MAP      ffmpeg scene-change detection gives real shot boundaries, so cuts can land
                  on cinema cuts instead of only sentence edges.
2. MOTION MAP     per-second frame-difference energy, so the engine knows where the picture is
                  actually moving (an overtake, a punch, a reveal) rather than only where the
                  audio is loud.
3. CINEMA SNAP    a cut whose edge sits near a shot boundary is pulled onto it (within a
                  tolerance), so clips start on a new shot and end on a shot change — the
                  "edited" feel — while the sentence rules still protect the meaning.
4. SCENE GRAMMAR  when a story contains an establishing/wide beat before the peak, the cut is
                  re-timed to open on it and land its payoff on the peak shot.
5. CINEMATIC FINISH  grade + vignette + optional grain, J/L-cut audio lead, ducking, and a
                  multi-ratio export (9:16 / 1:1 / 16:9).

Everything here is deterministic measurement. No AI is involved in this module.
"""

import json
import os
import subprocess

from .config import ffmpeg, ffprobe


def _run(args, timeout=600):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except Exception as e:  # pragma: no cover - defensive
        return 1, "", str(e)


# ---------------------------------------------------------------- scene map

def scene_map(src, threshold=0.30, max_seconds=7200):
    """Return shot boundaries as [(time, score), ...] using ffmpeg scene detection.

    threshold 0.30 is a good cinematic default: it catches hard cuts without firing on
    fast motion inside a single shot. Returns [] when detection is unavailable.
    """
    args = [ffmpeg(), "-hide_banner", "-nostats", "-i", src,
            "-filter:v", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-"]
    code, out, err = _run(args, timeout=max_seconds)
    marks = []
    for line in err.splitlines():
        if "pts_time:" not in line:
            continue
        try:
            t = float(line.split("pts_time:")[1].split()[0])
        except (IndexError, ValueError):
            continue
        score = 0.0
        if "scene_score=" in line:
            try:
                score = float(line.split("scene_score=")[1].split()[0])
            except (IndexError, ValueError):
                score = 0.0
        marks.append((round(t, 2), round(score, 3)))
    # de-duplicate near-identical marks (detection can double-report a cut)
    clean = []
    for t, s in marks:
        if not clean or t - clean[-1][0] > 0.35:
            clean.append((t, s))
    return clean


def load_scene_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [(float(a), float(b)) for a, b in data]
    except Exception:
        return []


def save_scene_cache(path, marks):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([[t, s] for t, s in marks], f)
    except OSError:
        pass


# ---------------------------------------------------------------- motion map

def motion_map(src, start=0.0, end=None, step=0.5):
    """Per-sample frame-difference energy: [(time, 0..1), ...].

    Uses ffmpeg's `signalstats` YAVG on the difference between consecutive frames, which is a
    cheap, reliable proxy for "how much is happening on screen". Normalised to 0..1.
    """
    args = [ffmpeg(), "-hide_banner", "-nostats"]
    if start:
        args += ["-ss", f"{start:.2f}"]
    if end:
        args += ["-t", f"{max(0.1, end - start):.2f}"]
    args += ["-i", src, "-vf", f"fps=1/{step},tblend=all_mode=difference,signalstats,"
                               "metadata=print:key=lavfi.signalstats.YAVG",
             "-f", "null", "-"]
    code, out, err = _run(args, timeout=900)
    vals = []
    for line in err.splitlines():
        if "YAVG=" in line:
            try:
                vals.append(float(line.split("YAVG=")[1].strip()))
            except (IndexError, ValueError):
                continue
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return [(round(start + i * step, 2), round((v - lo) / span, 3)) for i, v in enumerate(vals)]


def motion_at(series, t, window=1.0):
    """Normalised motion energy in [t-window, t+window]."""
    vals = [v for ts, v in series if t - window <= ts <= t + window]
    return max(vals) if vals else 0.0


def peak_shot(series, a, b):
    """Time of the highest-motion moment inside [a,b] (the shot that carries the payoff)."""
    hits = [(v, ts) for ts, v in series if a <= ts <= b]
    if not hits:
        return None
    return max(hits)[1]


# ---------------------------------------------------------------- cinema snap

def cinema_snap(start, end, marks, segments, duration, tol=1.6, min_len=12.0, max_len=70.0):
    """Pull cut edges onto nearby shot boundaries without breaking meaning.

    A start edge may move forward to the next shot boundary only if it does not cross the
    beginning of the current sentence (that would cut a thought). An end edge may move onto a
    boundary within tol, or slightly past it, so the clip ends on a cut.
    """
    if not marks:
        return start, end
    times = [t for t, _ in marks]

    def near(t):
        best, bestd = None, 1e9
        for m in times:
            d = abs(m - t)
            if d < bestd:
                best, bestd = m, d
        return (best, bestd) if bestd <= tol else (None, bestd)

    def sentence_start_after(t):
        for s in segments or []:
            if s.get("start", 0) >= t - 0.05:
                return s.get("start")
        return None

    ns, ne = start, end
    m, _ = near(start)
    if m is not None and m > start:
        guard = sentence_start_after(start)
        # never jump past the start of the sentence we are opening on
        if guard is None or m <= guard + 0.35:
            ns = m
    m, _ = near(end)
    if m is not None and m > end:
        ne = m
    elif m is not None and m <= end and end - m <= tol:
        ne = m

    if not (min_len <= ne - ns <= max_len):
        return start, end
    return round(ns, 2), round(ne, 2)


# ---------------------------------------------------------------- scene grammar

def scene_grammar(start, end, series, marks, segments):
    """Re-time a cut to the scene grammar: open on the establishing beat when the story has
    one, land the payoff on the peak shot.

    Returns (start, end, note). Deterministic; falls back to the input when it cannot improve.
    """
    if not series:
        return start, end, ""
    pk = peak_shot(series, start, end)
    if pk is None:
        return start, end, ""

    note = []
    # land the payoff on the peak: if the peak is near the tail, extend just past it
    if pk >= end - 3.0:
        ne = min(end + 2.5, pk + 2.0)
        if ne > end:
            end_new = ne
            note.append("extended onto the peak shot")
        else:
            end_new = end
    else:
        end_new = end

    # open on the establishing beat: if a shot boundary sits a little before the current start
    # and motion there is calm (a wide/establishing shot), open there instead
    start_new = start
    if marks:
        before = [t for t, _ in marks if start - 4.0 <= t < start - 0.4]
        if before:
            cand = max(before)
            if motion_at(series, cand) < motion_at(series, start):
                start_new = cand
                note.append("opened on the establishing shot")

    if not (12.0 <= end_new - start_new <= 70.0):
        return start, end, ""
    return round(start_new, 2), round(end_new, 2), ", ".join(note)


# ---------------------------------------------------------------- cinematic finish

# A restrained film look: gentle S-curve contrast, slight lift in the blacks, mild desaturation
# of the highlights, and a soft vignette. Tuned to read as "graded", not "filtered".
GRADE = ("eq=contrast=1.08:brightness=-0.012:saturation=0.94:gamma=0.98,"
         "curves=r='0/0.015 0.5/0.52 1/0.985':g='0/0.015 0.5/0.52 1/0.985':"
         "b='0/0.02 0.5/0.515 1/0.975',"
         "vignette=PI/4.6")

GRAIN = ("noise=alls=6:allf=t+u")


def cinematic_filters(grade=True, grain=False, vignette=True):
    """Human-readable filter chain for the cinematic finish (minus the vignette if asked)."""
    parts = []
    if grade:
        parts.append(GRADE if vignette else GRADE.replace(",vignette=PI/4.6", ""))
    if grain:
        parts.append(GRAIN)
    return ",".join(parts)


RATIOS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}


def ratio_size(ratio, base_w=1080):
    w, h = RATIOS.get(ratio, RATIOS["9:16"])
    if base_w != w:
        f = base_w / w
        w, h = int(w * f), int(h * f)
        w -= w % 2
        h -= h % 2
    return w, h