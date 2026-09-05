"""Assemble part 2: transcript/connect/powerup + compose web/index.html."""
import json
import os
import re

EXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stitch_export', 'extracted')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')


def rd(n):
    return open(os.path.join(EXT, n), encoding='utf-8').read()


def content(name):
    h = rd(name + '.html')
    h = re.sub(r'<aside[\s\S]*?</aside>', '', h)
    h = re.sub(r'<header[\s\S]*?</header>', '', h)
    h = re.sub(r'<main[^>]*>', '', h)
    h = h.replace('</main>', '')
    h = re.sub(r'<!-- STITCH_SHADER_START[\s\S]*?STITCH_SHADER_END[^>]*-->', '', h)
    h = re.sub(
        r'<div class="absolute inset-0 w-full h-full pointer-events-none opacity-30"[^>]*>\s*<canvas[^>]*/?>\s*</div>',
        '', h)
    W = '<div class="pl-[312px] min-h-screen relative z-10">'
    if W in h:
        h = h.replace(W, '', 1)
        i = h.rstrip().rfind('</div>')
        h = h[:i] + h[i + 6:]
    m = re.search(r'<div class="flex flex-col w-full[^"]*">', h)
    if m:
        h = h[:m.start()] + h[m.end():]
        i = h.rstrip().rfind('</div>')
        h = h[:i] + h[i + 6:]
    return h.strip()


def fix_depth(h):
    depth = 0
    for m in re.finditer(r'<div\b|</div>', h):
        depth += 1 if m.group(0).startswith('<div') else -1
    return h + '\n</div>' * depth if depth > 0 else h


def depth_of(h):
    d = 0
    for m in re.finditer(r'<div\b|</div>', h):
        d += 1 if m.group(0).startswith('<div') else -1
    return d

# ---------------------------------------------------------------- TRANSCRIPT
tr = content('06_transcript')
tr = tr.replace('<span class="font-label-caps text-label-caps uppercase text-on-surface-variant/60 rounded-full px-3.5 py-1.5 bg-white/[0.03] backdrop-blur-md">\n            334 blocks · 14:26\n          </span>',
                '<span id="transcript-count" class="font-label-caps text-label-caps uppercase text-on-surface-variant/60 rounded-full px-3.5 py-1.5 bg-white/[0.03] backdrop-blur-md">—</span>')
tr = tr.replace('<span class="font-label-caps text-label-caps uppercase text-primary bg-white/10 rounded-full px-3 py-1.5 flex items-center gap-1.5">\n<span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>\n            Acoustic Sync v5\n          </span>',
                '<span class="font-label-caps text-label-caps uppercase text-primary bg-white/10 rounded-full px-3 py-1.5 flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span><span id="transcript-stt">Acoustic Sync</span></span>')
tr = re.sub(r'<button class="flex items-center gap-1\.5 px-3\.5 py-1\.5 rounded-full bg-white/\[0\.04\] text-on-surface text-body-sm font-body-sm hover:bg-white/\[0\.08\] transition-all">\s*<span class="material-symbols-outlined text-body-sm">filter_alt</span>\s*<span>Peaks Only</span>\s*</button>',
            '<button id="transcript-peaks" class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/[0.04] text-on-surface text-body-sm font-body-sm hover:bg-white/[0.08] transition-all"><span class="material-symbols-outlined text-body-sm">filter_alt</span><span>Peaks only</span></button>', tr)
tr = re.sub(r'<button class="flex items-center gap-1\.5 px-3\.5 py-1\.5 rounded-full bg-white/\[0\.04\] text-on-surface text-body-sm font-body-sm hover:bg-white/\[0\.08\] transition-all">\s*<span class="material-symbols-outlined text-body-sm">download</span>\s*<span>Export \.SRT</span>\s*</button>',
            '<button id="transcript-srt" class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/[0.04] text-on-surface text-body-sm font-body-sm hover:bg-white/[0.08] transition-all"><span class="material-symbols-outlined text-body-sm">download</span><span>Export .SRT</span></button>', tr)
# blocks container -> mount (content between container open and the footer bar)
m = re.search(r'(<div class="flex flex-col gap-2 overflow-y-auto max-h-\[580px\] pr-2 scroll-smooth select-text" id="transcript-container">)[\s\S]*?(<div class="pt-3 flex items-center justify-between bg-white/\[0\.02\] rounded-xl px-4 py-2 mt-1">)', tr)
tr = tr[:m.start()] + m.group(1) + '\n<!-- BLOCKS_MOUNT -->\n</div>\n' + m.group(2) + tr[m.end():]
tr = tr.replace('<span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-primary"></span> 4 Flagged Clips</span>',
                '<span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-primary"></span> <span id="transcript-flagged">0</span> flagged clips</span>')
# waveform box: id, mounts inside (bounded, no truncation)
tr = tr.replace('<div class="relative h-32 w-full bg-surface-container-lowest rounded-xl overflow-hidden p-2 flex items-center justify-between gap-1 shadow-inner">',
                '<div id="wave-box" class="relative h-32 w-full bg-surface-container-lowest rounded-xl overflow-hidden p-2 flex items-center justify-between gap-1 shadow-inner">', 1)
# playhead -> live
tr = tr.replace('<div class="absolute left-[54%] top-0 bottom-0 w-px bg-primary shadow-[0_0_12px_rgba(255,255,255,1)] z-20 pointer-events-none">',
                '<div id="wave-playhead" style="left:0%" class="absolute top-0 bottom-0 w-px bg-primary shadow-[0_0_12px_rgba(255,255,255,1)] z-20 pointer-events-none transition-all duration-300">', 1)
# mock markers -> single live markers layer
_m1 = '<div class="absolute left-[35%] top-1 bottom-1 w-px bg-white/30 z-10 pointer-events-none"></div>'
_m2 = '<div class="absolute left-[78%] top-1 bottom-1 w-px bg-white/30 z-10 pointer-events-none"></div>'
_m3 = '<div class="absolute left-[88%] top-1 bottom-1 w-px bg-white/30 z-10 pointer-events-none"></div>'
_mk = '<div class="absolute inset-x-0 h-px bg-white/10 top-1/2 -translate-y-1/2 pointer-events-none"></div>'
for _mx in (_m1, _m2, _m3):
    tr = tr.replace(_mx, '', 1)
tr = tr.replace(_mk, _mk + '<div id="wave-markers" class="absolute inset-0 pointer-events-none"></div>', 1)
# wave ruler -> live
tr = tr.replace('<div class="flex items-center justify-between text-on-surface-variant/50 font-data-mono text-[10px]">',
                '<div id="wave-ruler" class="flex items-center justify-between text-on-surface-variant/50 font-data-mono text-[10px]">', 1)
# wave spec pill -> live spec
tr = tr.replace('<span class="font-data-mono text-data-mono text-primary bg-white/10 px-2 py-0.5 rounded-full">',
                '<span id="wave-spec" class="font-data-mono text-data-mono text-primary bg-white/10 px-2 py-0.5 rounded-full">', 1)
tr = tr.replace('48 kHz · 24-bit', '— kHz · mono', 1)
# wrap the mock bars so app.js can address them (display:contents keeps flex layout)
_box = '<div id="wave-box" class="relative h-32 w-full bg-surface-container-lowest rounded-xl overflow-hidden p-2 flex items-center justify-between gap-1 shadow-inner">'
_bi = tr.find(_box)
assert _bi != -1, 'wave box missing'
_seg_start = _bi + len(_box)
_d = 1; _j = -1
import re as _re
for _m in _re.finditer(r'<div\b[^>]*>|</div>', tr[_seg_start:]):
    _d += 1 if _m.group(0).startswith('<div') else -1
    if _d == 0:
        _j = _seg_start + _m.end()
        break
assert _j != -1, 'wave box close missing'
_seg = tr[_seg_start:_j]
_i1 = _seg.find('<div class="w-1.5 h-')
assert _i1 != -1 and _seg.rstrip().endswith('</div>'), 'bars segment unexpected'
_bars = _seg[_i1:].rstrip()
_bars = _bars[:-len('</div>')]  # drop the box-closing tag from the segment tail
tr = tr[:_seg_start] + _seg[:_i1] + '<div id="wave-bars" class="contents">' + _bars + '</div></div>' + tr[_j:]
# custom cut button after Peaks only
tr = tr.replace('<span>Peaks only</span></button>',
                '<span>Peaks only</span></button><button id="transcript-custom" class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/[0.04] text-on-surface text-body-sm font-body-sm hover:bg-white/[0.08] transition-all"><span class="material-symbols-outlined text-body-sm">content_cut</span><span>Custom cut</span></button>', 1)
# sync chip -> live
tr = tr.replace('<span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-white/30"></span> 99.2% Sync Lock</span>',
                '<span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-white/30"></span> <span id="transcript-sync">99.2% sync lock</span></span>', 1)

# right panel keyframe card ids
tr = tr.replace('<h4 class="font-headline-sm text-headline-sm text-primary font-medium mt-1 leading-snug">\n                  The Turn 5 Decider\n                </h4>',
                '<h4 class="font-headline-sm text-headline-sm text-primary font-medium mt-1 leading-snug" id="wave-title">—</h4>')
tr = tr.replace('<p class="font-body-sm text-body-sm text-on-surface-variant line-clamp-2 mt-0.5">\n                  Decisive overtake inside lane under heavy braking. Peak audio volume &amp; commentator excitation spike.\n                </p>',
                '<p class="font-body-sm text-body-sm text-on-surface-variant line-clamp-2 mt-0.5" id="wave-desc">—</p>')
tr = tr.replace('<span class="absolute font-data-mono text-[11px] font-semibold text-primary">81</span>',
                '<span class="absolute font-data-mono text-[11px] font-semibold text-primary" id="wave-score">—</span>', 1)
tr = tr.replace('<span class="font-data-mono text-data-mono text-primary font-medium">Top 2% of video span</span>',
                '<span class="font-data-mono text-data-mono text-primary font-medium" id="wave-metric">—</span>')
tr = tr.replace('<div class="absolute left-[54%] top-0 bottom-0 w-px bg-primary shadow-[0_0_12px_rgba(255,255,255,1)] z-20 pointer-events-none">',
                '<div id="wave-playhead" style="left:0%" class="absolute top-0 bottom-0 w-px bg-primary shadow-[0_0_12px_rgba(255,255,255,1)] z-20 pointer-events-none transition-all duration-300">')
tr = re.sub(r'<div class="absolute left-\[35%\] top-1 bottom-1 w-px bg-white/30 z-10 pointer-events-none"></div>\s*'
            r'<div class="absolute left-\[78%\] top-1 bottom-1 w-px bg-white/30 z-10 pointer-events-none"></div>\s*'
            r'<div class="absolute left-\[88%\] top-1 bottom-1 w-px bg-white/30 z-10 pointer-events-none"></div>',
            '<!-- WAVE_MARKERS_MOUNT -->', tr)
tr = tr.replace('<span class="text-primary font-semibold">09:57 (NOW)</span>', '<span id="wave-now" class="text-primary font-semibold">—</span>')
tr = tr.replace('<span class="font-data-mono text-data-mono text-on-surface-variant/70">\n            Precision: Frame 17,910\n          </span>',
                '<span class="font-data-mono text-data-mono text-on-surface-variant/70" id="transcript-precision">—</span>')

# ---------------------------------------------------------------- CONNECT
co = content('07_connect')
co = co.replace('<span class="font-data-mono text-data-mono text-primary font-medium tracking-tight">NODE_0x7F_PROX</span>',
                '<span class="font-data-mono text-data-mono text-primary font-medium tracking-tight" id="co-node">NODE_PROX</span>')
co = re.sub(r'<span class="font-label-caps text-label-caps uppercase tracking-\[0\.12em\] text-on-surface-variant bg-surface-container-lowest/80 px-3\.5 py-1\.5 rounded-full">\s*Not connected\s*</span>',
            '<span id="yt-status" class="font-label-caps text-label-caps uppercase tracking-[0.12em] text-on-surface-variant bg-surface-container-lowest/80 px-3.5 py-1.5 rounded-full">checking…</span>', co)
co = co.replace('id="connect-yt-btn"', 'id="yt-connect"')
# checklist -> mount (keep footnote after)
m = re.search(r'(<div class="flex flex-col gap-3 py-4 bg-surface-container-lowest/60 rounded-DEFAULT p-4">)[\s\S]*?(<!-- Footnote Alert Box -->)', co)
co = co[:m.start()] + m.group(1)[:-1] + ' id="yt-check">' + '\n<!-- YT_CHECK_MOUNT -->\n</div>\n</div>\n' + m.group(2) + co[m.end():]
# footnote: real guidance instead of mock 403 help
co = co.replace('<span class=\"font-body-sm text-body-sm text-on-surface-variant font-medium\">Google error 403 org_internal?</span>',
                '<span class=\"font-body-sm text-body-sm text-on-surface-variant font-medium\">Keys hot-reload - no restarts, ever.</span>', 1)
co = co.replace('Set to <span class=\"text-primary font-medium\">External</span> + add your current email as test user.',
                'Paste Groq / Gemini / YouTube keys in the AI Keys column - each is tested live and stored in clipblitz/.env.', 1)
# diagnose + redirect row, inserted before the footnote box (no close-count changes)
co = co.replace('<!-- Footnote Alert Box -->',
'''<div class="relative z-10 mt-3 flex flex-wrap items-center gap-2 font-data-mono text-data-mono">
<button id="yt-diagnose" class="px-3 py-1.5 rounded-full bg-surface-container-highest/60 hover:bg-surface-bright text-on-surface transition-all">Diagnose</button>
<button id="yt-redirect-copy" class="px-3 py-1.5 rounded-full bg-surface-container-highest/60 hover:bg-surface-bright text-on-surface transition-all">Copy redirect URI</button>
<span id="yt-redirect" class="text-on-surface-variant/70 truncate max-w-[300px]"></span>
</div>
<div id="yt-diag" class="relative z-10 mt-3" hidden></div>
<!-- Footnote Alert Box -->''', 1)
# relocation LAST: move the AI-keys card into the twin grid as the second column
# the Stitch mock leaves the AI-keys card OUTSIDE the twin grid — relocate it in as the second column
_gi = co.find('<div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">')
if _gi != -1:
    _start = _gi + len('<div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">')
    _d = 1; _grid_close = -1
    for _t in re.finditer(r'<div\b[^>]*>|</div>', co[_start:]):
        _d += 1 if _t.group(0).startswith('<div') else -1
        if _d == 0:
            _grid_close = _start + _t.start(); break
    _mrc = re.search(r'<!-- RIGHT COLUMN: AI Keys & Brain Runtime -->\s*<div\b[^>]*>', co)
    if _grid_close != -1 and _mrc and _mrc.start() > _grid_close:
        _d2 = 1; _card_close = -1
        for _t in re.finditer(r'<div\b[^>]*>|</div>', co[_mrc.end():]):
            _d2 += 1 if _t.group(0).startswith('<div') else -1
            if _d2 == 0:
                _card_close = _mrc.end() + _t.end(); break
        if _card_close != -1:
            _seg = co[_mrc.start():_card_close]
            co = co[:_mrc.start()] + co[_card_close:]
            co = co[:_grid_close] + _seg + co[_grid_close:]
# Groq key row: working input + chip id + button data-key
co = re.sub(r'<input class="w-full bg-surface-container px-4 py-2\.5 rounded-full font-data-mono text-data-mono text-on-surface tracking-wider focus:outline-none select-all" readonly="" type="password" value="gsk_99x8291048bcae912"/>',
            '<input id="key-groq" class="w-full bg-surface-container px-4 py-2.5 rounded-full font-data-mono text-data-mono text-on-surface tracking-wider focus:outline-none select-all" type="password" placeholder="gsk_••••••••" autocomplete="off" spellcheck="false"/>', co)
co = re.sub(r'(<div class="flex items-center gap-1\.5 px-2\.5 py-0\.5 rounded-full bg-surface-container-highest text-primary font-data-mono text-data-mono">\s*<span class="w-1\.5 h-1\.5 rounded-full bg-primary animate-pulse"></span>\s*<span>)SAVED · ONLINE(</span>)',
            r'<div id="keychip-groq" class="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-surface-container-highest text-primary font-data-mono text-data-mono"><span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span><span>\1</span>', co)
# the visibility button references the input via previousElementSibling - keep; then Test&Save button after groq input:
co = re.sub(r'<button class="px-5 py-2\.5 rounded-full bg-primary text-on-primary font-body-sm text-body-sm font-semibold tracking-wider uppercase hover:bg-white/90 active:scale-95 transition-all shadow-md">\s*Test &amp; Save\s*</button>',
            '<button data-key="groq" class="px-5 py-2.5 rounded-full bg-primary text-on-primary font-body-sm text-body-sm font-semibold tracking-wider uppercase hover:bg-white/90 active:scale-95 transition-all shadow-md">Test &amp; Save</button>', co, 1)
# Gemini key row
co = re.sub(r'<input class="w-full bg-surface-container px-4 py-2\.5 rounded-full font-data-mono text-data-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none select-all" placeholder="Paste AIzaSy\.\.\." type="text"/>',
            '<input id="key-gemini" class="w-full bg-surface-container px-4 py-2.5 rounded-full font-data-mono text-data-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none select-all" placeholder="Paste AIzaSy… or AQ…" type="password" autocomplete="off" spellcheck="false"/>', co)
co = re.sub(r'(<div class="flex items-center gap-1\.5 px-2\.5 py-0\.5 rounded-full bg-surface-container text-on-surface-variant/70 font-data-mono text-data-mono">\s*<span class="material-symbols-outlined text-\[12px\]">radio_button_unchecked</span>\s*<span>)EMPTY(</span>)',
            r'<div id="keychip-gemini" class="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-surface-container text-on-surface-variant/70 font-data-mono text-data-mono"><span class="material-symbols-outlined text-[12px]">radio_button_unchecked</span><span>\1</span>', co)
co = re.sub(r'<button class="px-5 py-2\.5 rounded-full bg-surface-container-highest hover:bg-primary hover:text-on-primary text-primary font-body-sm text-body-sm font-semibold tracking-wider uppercase active:scale-95 transition-all">\s*Test &amp; Save\s*</button>',
            '<button data-key="gemini" class="px-5 py-2.5 rounded-full bg-surface-container-highest hover:bg-primary hover:text-on-primary text-primary font-body-sm text-body-sm font-semibold tracking-wider uppercase active:scale-95 transition-all">Test &amp; Save</button>', co, 1)
# YouTube OAuth key block: insert before the STT select chip
co = co.replace('<!-- Select Chip for STT Model -->',
                '''<!-- Key 3: YouTube Data API -->
<div class="flex flex-col gap-2.5 mb-5 p-4 rounded-DEFAULT bg-surface-container-lowest/70">
<div class="flex items-center justify-between">
<div class="flex items-center gap-2">
<span class="font-body-sm text-body-sm font-medium text-primary">YouTube Data API</span>
<span class="font-data-mono text-data-mono text-on-surface-variant">(OAuth client · Desktop app)</span>
</div>
<div id="keychip-youtube" class="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-surface-container text-on-surface-variant/70 font-data-mono text-data-mono">
<span class="material-symbols-outlined text-[12px]">radio_button_unchecked</span>
<span>EMPTY</span>
</div>
</div>
<div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-1">
<input id="key-yt-id" class="w-full bg-surface-container px-4 py-2.5 rounded-full font-data-mono text-data-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none select-all" placeholder="…apps.googleusercontent.com" type="password" autocomplete="off" spellcheck="false"/>
<input id="key-yt-secret" class="w-full bg-surface-container px-4 py-2.5 rounded-full font-data-mono text-data-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none select-all" placeholder="GOCSPX-••••••••" type="password" autocomplete="off" spellcheck="false"/>
</div>
<div class="flex justify-end mt-1">
<button data-key="youtube" class="px-5 py-2.5 rounded-full bg-surface-container-highest hover:bg-primary hover:text-on-primary text-primary font-body-sm text-body-sm font-semibold tracking-wider uppercase active:scale-95 transition-all">Test &amp; Save</button>
</div>
</div>
<!-- Select Chip for STT Model -->''')
co = co.replace('<span class="font-data-mono text-data-mono text-on-surface font-medium">STT model: whisper-large-v3-turbo</span>',
                '<span class="font-data-mono text-data-mono text-on-surface font-medium" id="stt-model-label">STT model: —</span>')
# diagnostics chips ids
co = co.replace('<span class="font-medium text-primary">ffmpeg</span>\n<span class="text-primary">✓</span>\n<span class="text-on-surface-variant/50 text-[10px]">v6.1.1</span>',
                '<span class="font-medium text-primary">ffmpeg</span><span class="text-primary">✓</span><span class="text-on-surface-variant/50 text-[10px]" id="diag-ffmpeg">✓</span>')
co = co.replace('<span class="font-medium text-primary">yt-dlp</span>\n<span class="text-primary">✓</span>\n<span class="text-on-surface-variant/50 text-[10px]">2024.12</span>',
                '<span class="font-medium text-primary">yt-dlp</span><span class="text-primary">✓</span><span class="text-on-surface-variant/50 text-[10px]" id="diag-ytdlp">✓</span>')
co = re.sub(r'<span class="font-medium text-primary">judge groq</span>\s*<span class="text-primary">✓</span>\s*<span class="text-on-surface-variant/50 text-\[10px\]">240 tps</span>',
            '<span class="font-medium text-primary">judge</span><span class="text-primary">✓</span><span class="text-on-surface-variant/50 text-[10px]" id="diag-judge">—</span>', co)
co = re.sub(r'<span class="font-medium text-primary">quota 74% left</span>',
            '<span class="font-medium text-primary" id="diag-quota">quota —</span>', co)
co = co.replace('id="refresh-diagnostics-btn"', 'id="diag-refresh"')

# ---------------------------------------------------------------- POWERUP (screen)
pu = content('01_power_up')
pu = re.sub(r'\s*value="gsk_9238f0923e80f823a09e8023f82093e"', '', pu)
pu = re.sub(r'\s*value="AIzaSyC09a80e8f0a9sd8f09as8df098as0"', '', pu)
pu = pu.replace('id="groq-key"', 'id="pu-groq"').replace('id="gemini-key"', 'id="pu-gemini"')
pu = re.sub(r'onclick="toggleKeyVis\([^"]*\)"\s*', '', pu)
pu = re.sub(r'onclick="triggerTest\(this, \'[^\']*\'\)"\s*', '', pu)
pu = pu.replace('<button\n class="shrink-0 bg-primary', '<button data-key="groq" class="shrink-0 bg-primary')
pu = re.sub(r'<button class="shrink-0 bg-primary([^"]*)">\s*<span>TEST &amp; SAVE</span>\s*</button>',
            lambda m: '<button data-key="groq" class="shrink-0 bg-primary%s"><span>TEST &amp; SAVE</span></button>' % m.group(1), pu, count=0)
# give each of the three TEST & SAVE buttons a data-key in document order
keys = ['groq', 'gemini', 'youtube']
def _addkey(m):
    return '<button data-key="%s" class="%s">' % (keys[_addkey.i], m.group(1)) if True else m.group(0)
_addkey.i = 0
def addkey(m):
    k = keys[_addkey.i] if _addkey.i < len(keys) else 'x'
    _addkey.i += 1
    return '<button data-key="%s" class="%s">' % (k, m.group(1))
pu = re.sub(r'<button class="(shrink-0 bg-primary[^"]*|shrink-0 bg-primary text-on-primary[^"]*)">\s*<span>TEST &amp; SAVE</span>', addkey, pu)
# the youtube card inputs get ids
pu = pu.replace('placeholder="••••••••••••.apps.googleusercontent.com"', 'id="pu-yt-id" placeholder="••••••••••••.apps.googleusercontent.com"')
pu = pu.replace('placeholder="GOCSPX-••••••••"', 'id="pu-yt-secret" placeholder="GOCSPX-••••••••"')
pu = re.sub(r'<button class="w-full sm:w-auto bg-primary text-on-primary font-headline-sm text-body-md font-semibold px-10 py-3\.5 rounded-full hover:bg-primary-container hover:scale-\[1\.02\] active:scale-\[0\.98\] transition-all duration-200 shadow-xl mb-3 flex items-center justify-center gap-2" id="master-save-btn" onclick="runMasterCalibration\(this\)" type="button">',
            '<button class="w-full sm:w-auto bg-primary text-on-primary font-headline-sm text-body-md font-semibold px-10 py-3.5 rounded-full hover:bg-primary-container hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 shadow-xl mb-3 flex items-center justify-center gap-2" id="pu-master" type="button">', pu)
pu = pu.replace('<a class="font-body-sm text-body-sm text-on-surface-variant hover:text-primary transition duration-150 mb-8 inline-flex items-center gap-1" href="#" onclick="event.preventDefault(); alert(\'Continuing in localized offline mode (Whisper Turbo + ffmpeg only).\');">',
                '<a class="font-body-sm text-body-sm text-on-surface-variant hover:text-primary transition duration-150 mb-8 inline-flex items-center gap-1 cursor-pointer" id="pu-offline">')
pu = pu.replace('<span class="text-on-surface-variant">STT whisper-large-v3-turbo</span>',
                '<span class="text-on-surface-variant" id="pu-stt">STT —</span>')

# ---------------------------------------------------------------- COMPOSE
head = rd('_head.html')
head = re.sub(r'<script src="https://cdn\.tailwindcss\.com"></script>', '', head)
head = re.sub(r'<script id="tailwind-config">[\s\S]*?</script>', '', head)
head = head.replace('</head>',
                    '<link href="/tailwind.css" rel="stylesheet"/>\n<script src="/gsap.min.js" defer></script>\n<link href="/styles.css" rel="stylesheet"/>\n</head>')
head = head.replace('<title>', '<title>ClipBlitz — ProX Editor · AI Clipping Studio</title><!--')  # noop guard
shader = rd('_shader.html')
aside = rd('_aside.html')
header = rd('_header.html')
header = header.replace('<span class="font-label-caps text-label-caps uppercase text-white/40 tracking-widest">Engine Online</span>',
                        '<span class="font-label-caps text-label-caps uppercase text-white/40 tracking-widest" id="engine-status">Engine Online</span>')

parts = {
    'powerup': pu, 'studio': st_html if (st_html := open(os.path.join(EXT, 'asm_st.html'), encoding='utf-8').read()) else '',
    'processing': open(os.path.join(EXT, 'asm_pr.html'), encoding='utf-8').read(),
    'clips': open(os.path.join(EXT, 'asm_cl.html'), encoding='utf-8').read(),
    'candidates': open(os.path.join(EXT, 'asm_ca.html'), encoding='utf-8').read(),
    'transcript': tr, 'connect': co,
}
sections = ''
for name, html in parts.items():
    html = fix_depth(html)
    sections += '\n<!-- ============ SCREEN: %s ============ -->\n<section class="screen" id="screen-%s" hidden>\n%s\n</section>\n' % (name.upper(), name, html)

body_open = '<body class="bg-[#050505] font-body-md text-body-md text-on-surface min-h-screen relative selection:bg-primary selection:text-on-primary">'
index = ('<!DOCTYPE html>\n<html class="dark" lang="en">' +
         head.replace('<!DOCTYPE html>\n\n<html class="dark" lang="en">', '').replace('<html class="dark" lang="en">', '') +
         '\n' + body_open + '\n' + shader + '\n' + aside + '\n' +
         '<div class="pl-[312px] min-h-screen relative z-10">' + header +
         '<main class="w-full pt-28 pr-8 pb-8 pl-0 min-h-screen relative z-10">' +
         '<div class="flex flex-col w-full">' + sections +
         '</div>\n</main>\n</div>\n<div id="toasts" class="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 items-end"></div>\n<script src="/app.js"></script>\n</body>\n</html>')

open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8', newline='\n').write(index)
print('index.html written:', len(index), 'chars')
for n, h in parts.items():
    print(n, 'depth after fix:', depth_of(fix_depth(h)))
