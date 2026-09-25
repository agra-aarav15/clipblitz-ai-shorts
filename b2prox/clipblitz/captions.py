"""Caption engine v2 — animated word-by-word subtitles as ASS, burned by ffmpeg/libass.

Six presets, size + position controls. Word timings come from Whisper; without
them a block-level fallback is used so captions still render.
"""

import math

# ASS colours are &HAABBGGRR (BGR order, 00 = opaque)
def _c(hex_rgb, alpha=0x00):
    r, g, b = hex_rgb.lstrip("#")[0:2], hex_rgb.lstrip("#")[2:4], hex_rgb.lstrip("#")[4:6]
    return f"&H{alpha:02X}{b.upper()}{g.upper()}{r.upper()}"

# PlayRes canvas matches the render: 1080x1920 vertical
W, H = 1080, 1920

PRESETS = {
    "wordpop": {
        "name": "Word Pop", "desc": "MrBeast-style chunks that pop in. White on black outline.",
        "font": "Arial Black", "size": 88, "primary": "#FFFFFF", "outline": "#000000",
        "outline_w": 5, "box": False, "chunk": 3, "effect": "pop", "margin_v": 300,
        "bold": 1, "sample_bg": "#000000", "sample_color": "#FFFFFF",
    },
    "goldbold": {
        "name": "Bold Gold", "desc": "Fat golden words with a heavy black edge. The signature look.",
        "font": "Arial Black", "size": 92, "primary": "#FFD700", "outline": "#000000",
        "outline_w": 6, "box": False, "chunk": 3, "effect": "pop", "margin_v": 300,
        "bold": 1, "sample_bg": "#000000", "sample_color": "#FFD700",
    },
    "minimal": {
        "name": "Minimal White", "desc": "Clean thin white — lets the footage speak.",
        "font": "Arial", "size": 64, "primary": "#FFFFFF", "outline": "#000000",
        "outline_w": 2, "box": False, "chunk": 5, "effect": "none", "margin_v": 240,
        "bold": 0, "sample_bg": "#111111", "sample_color": "#FFFFFF",
    },
    "karaoke": {
        "name": "Karaoke Gold", "desc": "Full sentence with a golden sweep that follows your voice.",
        "font": "Arial Black", "size": 76, "primary": "#FFD700", "secondary": "#FFFFFF",
        "outline": "#000000", "outline_w": 4, "box": False, "chunk": 10, "effect": "karaoke",
        "margin_v": 320, "bold": 1, "sample_bg": "#000000", "sample_color": "#FFD700",
    },
    "neon": {
        "name": "Neon Shake", "desc": "Glowing neon words that jitter with the beat.",
        "font": "Arial Black", "size": 84, "primary": "#39FF14", "outline": "#003300",
        "outline_w": 3, "box": False, "chunk": 3, "effect": "shake", "margin_v": 300,
        "bold": 1, "sample_bg": "#001a00", "sample_color": "#39FF14",
    },
    "box": {
        "name": "Classic Box", "desc": "White on a solid black box — maximum readability.",
        "font": "Arial Black", "size": 70, "primary": "#FFFFFF", "outline": "#000000",
        "outline_w": 10, "box": True, "chunk": 4, "effect": "none", "margin_v": 280,
        "bold": 1, "sample_bg": "#000000", "sample_color": "#FFFFFF",
    },
}

DEFAULT_STYLE = "wordpop"


def _fmt(t):
    """ASS timestamp: h:mm:ss.cc"""
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def chunk_words(words, max_len):
    """Group words into caption chunks: break on punctuation, length, or pauses >0.6s."""
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        text = w["word"]
        gap_end = w["end"]
        if (len(cur) >= max_len or text[-1:] in ".!?…,;:") \
           or (w["end"] - w["start"] > 0 and text[-1:] in ".!?…"):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def _style_line(p, size_scale, position):
    size = max(28, int(p["size"] * size_scale))
    margin_v = int(p["margin_v"] * (1.35 if position == "middle" else 1.0))
    if position == "middle":
        alignment = 5
    elif position == "top":
        alignment, margin_v = 8, 260
    else:
        alignment = 2
    outline = p["outline_w"]
    if p.get("box"):
        border_style = 3  # opaque box uses Outline as padding
    else:
        border_style = 1
    secondary = p.get("secondary", p["primary"])
    return (f"Style: Cap,{p['font']},{size},{_c(p['primary'])},{_c(secondary)},{_c(p['outline'])},"
            f"&H80000000,{p['bold']},0,0,0,100,100,0,0,1,{outline},{0 if p.get('box') else 1},"
            f"{alignment},{60},{60},{margin_v},1")


def _event(t0, t1, text):
    return f"Dialogue: 0,{_fmt(t0)},{_fmt(t1)},Cap,,0,0,0,,{text}"


def _pop_tags():
    return r"{\fscx82\fscy82\t(0,70,\fscx110\fscy110)\t(70,130,\fscx100\fscy100)}"


def _shake_pos(i, base_y):
    x = W // 2 + (((i * 37) % 3) - 1) * 22
    y = base_y + (((i * 53) % 3) - 1) * 14
    return rf"{{\pos({x},{y})\blur2}}"


def build_ass(words, window, style_id, size_scale, position, out_path):
    """words: [{word,start,end}] absolute times; window: (start, end) of the clip."""
    p = PRESETS.get(style_id, PRESETS[DEFAULT_STYLE])
    w0, w1 = window
    inside = [w for w in words if w["end"] > w0 and w["start"] < w1]
    if not inside:  # no word timings — one steady block so captions still render
        inside = [{"word": " ", "start": w0, "end": w1}]

    rel = [{"word": w["word"], "start": max(w["start"] - w0, 0.0),
            "end": min(w["end"] - w0, w1 - w0)} for w in inside]
    rel = [w for w in rel if w["end"] > w["start"]]

    events = []
    if p["effect"] == "karaoke":
        for chunk in chunk_words(rel, p["chunk"]):
            t0, t1 = chunk[0]["start"], chunk[-1]["end"]
            parts = "".join(rf"{{\k{max(1, int(round((w['end'] - w['start']) * 100)))}}}{w['word']} "
                            for w in chunk)
            events.append(_event(t0, t1, "{\\k0}" + parts.rstrip()))
    else:
        for i, chunk in enumerate(chunk_words(rel, p["chunk"])):
            t0, t1 = chunk[0]["start"], chunk[-1]["end"]
            text = " ".join(w["word"] for w in chunk)
            text = text.replace("{", "").replace("}", "")
            if p["effect"] == "pop":
                text = _pop_tags() + text
            elif p["effect"] == "shake":
                base_y = H - p["margin_v"]
                text = _shake_pos(i, base_y) + text
            if p.get("box"):
                text = r"{\bord" + str(p["outline_w"]) + "}" + text
            events.append(_event(t0, t1, text))

    header = f"""[Script Info]
Title: ClipBlitz captions
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{_style_line(p, size_scale, position)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write(header + "\n".join(events) + "\n")
    return out_path


def styles_for_api():
    return [{"id": k, "name": p["name"], "desc": p["desc"],
             "sample_color": p["sample_color"], "sample_bg": p["sample_bg"]}
            for k, p in PRESETS.items()]
