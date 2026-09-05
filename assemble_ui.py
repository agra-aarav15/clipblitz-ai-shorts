"""Assemble the new web/index.html from the Stitch export parts + dynamic mounts."""
import re
import os

EXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stitch_export', 'extracted')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')


def rd(n):
    return open(os.path.join(EXT, n), encoding='utf-8').read()


def content(name):
    """Strip aside/header/main wrappers, return inner screen content."""
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


def balance_ok(html):
    """Rough div open/close balance check (self-closing and voids ignored)."""
    opens = len(re.findall(r'<div\b', html))
    closes = len(re.findall(r'</div>', html))
    return opens == closes, opens, closes

# ---------------------------------------------------------------- STUDIO
st = content('02_studio')
st = re.sub(
    r'<div class="grid grid-cols-1 md:grid-cols-3 gap-4 w-full">[\s\S]*$',
    '<div class="grid grid-cols-1 md:grid-cols-3 gap-4 w-full" id="recent-jobs">'
    '<!-- JOBS_MOUNT --></div>\n</div>\n</div>\n</div>', st)
st = st.replace('<span class="text-primary">3 READY</span>',
                '<span class="text-primary" id="pipeline-ready">— READY</span>')
st = st.replace('</div>\n</div>\n<!-- Option Chips Interactive Bar -->',
                '<input type="file" id="file" class="hidden" accept="video/*" />\n</div>\n<!-- Option Chips Interactive Bar -->')
st = re.sub(r'<input(?! id=)([^>]*?)placeholder="Paste a YouTube link', r'<input id="url-input" placeholder="Paste a YouTube link', st, count=1)
st = st.replace('cursor-pointer group"', 'cursor-pointer group" id="dropzone"', 1)
st = st.replace('shadow-[0_0_25px_rgba(255,255,255,0.3)] flex items-center gap-2.5 cursor-pointer shrink-0"',
                'shadow-[0_0_25px_rgba(255,255,255,0.3)] flex items-center gap-2.5 cursor-pointer shrink-0" id="make-clips-btn"', 1)
for label, key in [("Clips", "clips"), ("Captions", "captions"), ("Framing", "framing"), ("Language", "lang")]:
    st = st.replace('<div class="relative group/chip">', '<div class="relative" data-chip="%s">' % key, 1)
st = re.sub(r'(<div class="relative" data-chip="(clips|captions|framing|lang)">\s*<button[^>]*)>',
            r'\1 data-chip-btn="\2">', st)

# ---------------------------------------------------------------- PROCESSING
pr = content('03_processing')
pr = pr.replace('<div class="flex flex-col gap-2.5 flex-1 justify-center">',
                '<div class="flex flex-col gap-2.5 flex-1 justify-center" id="proc-stages">', 1)
pr = pr.replace('<circle class="transition-all duration-1000 ease-out"',
                '<circle id="progress-circle" class="transition-all duration-1000 ease-out"', 1)
pr = pr.replace('JOB_ID: TX-9021-AD', 'JOB_ID: <span id="proc-job-id">—</span>')
pr = pr.replace('CUDA 12.4 · 84 TFLOPS', 'LOCAL PIPELINE · 0 CLOUD')
pr = pr.replace('67%</span>', ' id="proc-pct">0%</span>', 1)
pr = pr.replace('<span class="font-display-xl text-display-xl font-semibold tracking-[-0.03em] text-primary select-none" id="proc-pct">0%</span>',
                '<span class="font-display-xl text-display-xl font-semibold tracking-[-0.03em] text-primary select-none" id="proc-pct">0%</span>')
pr = pr.replace('>That Night in Abu Dhabi — F1 Short Film</h2>', ' id="proc-name">—</h2>')
pr = pr.replace('<p class="font-body-sm text-body-sm text-white/50 mt-1">started 2 min ago · 14:26 source file</p>',
                '<p class="font-body-sm text-body-sm text-white/50 mt-1" id="proc-sub">waiting…</p>')
pr = re.sub(r'<div class="mt-4 flex items-center gap-2 text-white/30 font-data-mono text-data-mono">[\s\S]*?</div>\n</div>\n<!-- Right Column',
            '<div class="mt-4 flex items-center gap-2 text-white/30 font-data-mono text-data-mono" id="proc-meta"></div>\n</div>\n<!-- Right Column', pr)
pr = re.sub(r'<!-- Stage 1 -->[\s\S]*?QUEUED</span>\n</div>\n</div>\n</div>\n</div>\n<!-- Bottom Micro Visualizer -->',
            '<!-- STAGES_MOUNT -->\n</div>\n</div>\n<!-- Bottom Micro Visualizer -->', pr)
pr = pr.replace('<span class="font-data-mono text-data-mono text-white/30">STAGE 6 OF 8</span>',
                '<span class="font-data-mono text-data-mono text-white/30" id="proc-stage-n">STAGE — OF 8</span>')
pr = pr.replace('<span>ENGINE: GROQ-LLAMA3-70B · GEMINI-1.5-PRO</span>', '<span id="proc-engine">ENGINE: —</span>')
pr = pr.replace('<span class="truncate">Rendering clip 2/3 · wordpop captions · blur-pad 9:16</span>',
                '<span class="truncate" id="proc-pill">—</span>')
pr = re.sub(r'<!-- Preview Stage Snippet Bento Tray -->\n<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2">[\s\S]*$',
            '<!-- Preview Stage Snippet Bento Tray -->\n<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2" id="proc-tray">'
            '<!-- TRAY_MOUNT --></div>\n</div>\n</div>', pr)

# ---------------------------------------------------------------- CLIPS
cl = content('04_clips_podium')
cl = cl.replace('<span class="font-data-mono text-data-mono text-on-surface-variant/40">3 OF 24 PASS QC</span>',
                '<span class="font-data-mono text-data-mono text-on-surface-variant/40" id="clips-qc">—</span>')
cl = re.sub(r'(<h1 class="font-headline-lg text-headline-lg font-semibold text-primary tracking-\[-0\.02em\] leading-tight">)[\s\S]*?(</h1>)',
            r'\1Clips — <span id="clips-jobname">select a job</span>\2', cl)
cl = cl.replace('<span>brain groq+gemini</span>', '<span id="clips-brain">brain —</span>')
cl = re.sub(r'<section class="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">[\s\S]*?</section>\n<!-- Bottom Stage Telemetry Bar -->',
            '<section class="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch" id="clips">'
            '<!-- CARDS_MOUNT --></section>\n<!-- Bottom Stage Telemetry Bar -->', cl)
cl = cl.replace('<span>MODELS: LLAMA-3.3-70B · GEMINI-1.5-FLASH</span>', '<span id="clips-models">MODELS: —</span>')
cl = cl.replace('<span>AUTOSYNC IDLE</span>', '<span id="tele-engine">ENGINE READY</span>', 1)
cl = cl.replace('<span>LATENCY: 42ms</span>', '<span id="tele-job">NO JOB LOADED</span>', 1)
cl = re.sub(r'<button class="px-4 py-1\.5 rounded-full bg-white/\[0\.05\] hover:bg-white/10 text-on-surface transition-colors">\s*Export Manifest\s*</button>',
            '<button class="px-4 py-1.5 rounded-full bg-white/[0.05] hover:bg-white/10 text-on-surface transition-colors" id="clips-export">Export manifest</button>', cl)
cl = re.sub(r'<button class="px-4 py-1\.5 rounded-full bg-white/\[0\.05\] hover:bg-white/10 text-on-surface transition-colors flex items-center gap-1">\s*<span class="material-symbols-outlined text-\[14px\]">share</span>\s*<span>Batch Dispatch</span>\s*</button>',
            '<button class="px-4 py-1.5 rounded-full bg-white/[0.05] hover:bg-white/10 text-on-surface transition-colors flex items-center gap-1" id="clips-batch">'
            '<span class="material-symbols-outlined text-[14px]">share</span><span>Batch dispatch</span></button>', cl)

# ---------------------------------------------------------------- CANDIDATES
ca = content('05_candidates')
ca = re.sub(r'<button class="bg-primary text-on-primary font-headline-sm text-\[12px\] leading-tight px-4 py-1\.5 rounded-full shadow-\[0_0_20px_rgba\(255,255,255,0\.3\)\] transition-all">\s*All\s*</button>',
            '<button data-filter="all" class="bg-primary text-on-primary font-headline-sm text-[12px] leading-tight px-4 py-1.5 rounded-full shadow-[0_0_20px_rgba(255,255,255,0.3)] transition-all">All</button>', ca)
ca = re.sub(r'<button class="bg-white/\[0\.04\] hover:bg-white/\[0\.08\] text-on-surface font-body-sm text-body-sm px-4 py-1\.5 rounded-full transition-all">\s*Verified\s*</button>',
            '<button data-filter="verified" class="bg-white/[0.04] hover:bg-white/[0.08] text-on-surface font-body-sm text-body-sm px-4 py-1.5 rounded-full transition-all">Verified</button>', ca)
ca = re.sub(r'<button class="bg-white/\[0\.04\] hover:bg-white/\[0\.08\] text-on-surface font-body-sm text-body-sm px-4 py-1\.5 rounded-full transition-all">\s*Peak events\s*</button>',
            '<button data-filter="peak" class="bg-white/[0.04] hover:bg-white/[0.08] text-on-surface font-body-sm text-body-sm px-4 py-1.5 rounded-full transition-all">Peak events</button>', ca)
ca = re.sub(r'<div class="flex flex-col gap-2\.5">\n<!-- Row 1 -->[\s\S]*?<!-- Candidate Pipeline Floor Diagnostics -->',
            '<div class="flex flex-col gap-2.5" id="cands"><!-- CANDS_MOUNT --></div>\n<!-- Candidate Pipeline Floor Diagnostics -->', ca)
ca = re.sub(r'<button class="bg-white/\[0\.05\] hover:bg-white/\[0\.1\] text-primary px-3 py-1 rounded-full text-\[10px\] font-semibold tracking-widest transition-all">\s*RENDER ALL \(5\)\s*</button>',
            '<button id="cands-render-all" class="bg-white/[0.05] hover:bg-white/[0.1] text-primary px-3 py-1 rounded-full text-[10px] font-semibold tracking-widest transition-all">RENDER ALL</button>', ca)
ca = ca.replace('<span>ESTIMATED QUEUE DELAY: 2.1s</span>', '<span id="cands-queue">POOL READY</span>', 1)
ca = re.sub(r'<span class="font-data-mono text-data-mono text-on-surface-variant/60 hidden sm:inline-block">\s*PROX-LAB::POOL_06\s*</span>',
            '<span class="font-data-mono text-data-mono text-on-surface-variant/60 hidden sm:inline-block" id="cands-pool">PROX-LAB::POOL</span>', ca)

for n, h in [('st', st), ('pr', pr), ('cl', cl), ('ca', ca)]:
    ok = balance_ok(h)
    open(os.path.join(EXT, 'asm_%s.html' % n), 'w', encoding='utf-8').write(h)
    print(n, len(h), 'div-balance:', ok)
print('part 1 done')
