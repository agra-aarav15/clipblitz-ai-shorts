/* ClipBlitz — ProX v5 studio (Stitch "Obsidian Keynote" build)
   All endpoints identical to v3.1; markup now emits the exact Stitch design system. */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- screen router (sidebar pills) ---------- */
const ACTIVE_PILL = ['bg-primary', 'text-on-primary', 'font-semibold', 'shadow-[0_0_20px_rgba(255,255,255,0.35)]'];
const IDLE_PILL = ['text-on-surface-variant'];
let currentScreen = 'studio';

function showScreen(name) {
  document.querySelectorAll('.screen').forEach((s) => { s.hidden = s.id !== 'screen-' + name; });
  document.querySelectorAll('aside nav a').forEach((a) => {
    const active = a.dataset.path === name;
    a.classList.toggle('bg-primary', active);
    a.classList.toggle('text-on-primary', active);
    a.classList.toggle('font-semibold', active);
    a.classList.toggle('text-on-surface-variant', !active);
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  currentScreen = name;
  window.scrollTo(0, 0);
  const sec = $('screen-' + name);
  if (sec && !matchMedia('(prefers-reduced-motion: reduce)').matches && !new URLSearchParams(location.search).has('nomotion')) {
    sec.style.opacity = '0';
    sec.style.transform = 'translateY(10px)';
    sec.style.transition = 'none';
    requestAnimationFrame(() => {
      sec.style.transition = 'opacity .4s ease, transform .4s ease';
      sec.style.opacity = '1';
      sec.style.transform = 'none';
    });
  }
  if (name === 'clips') renderClips();
  if (name === 'candidates') renderCandidates();
  if (name === 'transcript') renderTranscript();
}
document.querySelectorAll('aside nav a').forEach((a) =>
  a.addEventListener('click', (e) => { e.preventDefault(); showScreen(a.dataset.path); }));

/* ---------- toasts (Stitch glass pills) ---------- */
function toast(msg, err = false) {
  const t = document.createElement('div');
  t.className = 'pointer-events-auto max-w-sm rounded-full bg-surface-container-high/90 backdrop-blur-xl border border-white/10 px-5 py-2.5 font-body-sm text-body-sm ' +
    (err ? 'text-red-300' : 'text-on-surface') + ' shadow-[0_10px_30px_rgba(0,0,0,0.6)] opacity-0 translate-y-2 transition-all duration-300';
  t.textContent = msg;
  $('toasts').appendChild(t);
  requestAnimationFrame(() => t.classList.remove('opacity-0', 'translate-y-2'));
  setTimeout(() => { t.classList.add('opacity-0', 'translate-y-2'); setTimeout(() => t.remove(), 350); }, 4200);
}

/* ---------- tiny helpers ---------- */
const fmtTime = (s) => { s = Math.max(0, Math.round(s || 0)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const ago = (ts) => { const d = (Date.now() / 1000 - (ts || 0)); if (d < 90) return 'just now'; if (d < 3600) return `${Math.round(d / 60)}m ago`; if (d < 86400) return `${Math.round(d / 3600)}h ago`; return `${Math.round(d / 86400)}d ago`; };
async function api(path, opts) { const r = await fetch(path, opts); const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || r.statusText); return d; }
const C = 2 * Math.PI * 14; // score dial circumference (r=14, matches Stitch svg)

function dial(score, dim = false) {
  const off = (C * (1 - Math.min(100, Math.max(0, score)) / 100)).toFixed(1);
  const stroke = dim ? 'text-primary/70 drop-shadow-[0_0_6px_rgba(255,255,255,0.4)]' : 'text-primary drop-shadow-[0_0_6px_rgba(255,255,255,0.8)]';
  return `<svg class="w-9 h-9 -rotate-90" viewbox="0 0 36 36">
    <circle class="text-white/10" cx="18" cy="18" fill="none" r="14" stroke="currentColor" stroke-width="2"></circle>
    <circle class="${stroke}" cx="18" cy="18" fill="none" r="14" stroke="currentColor" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${off}" stroke-linecap="round" stroke-width="2.5"></circle>
  </svg>
  <span class="absolute font-data-mono text-data-mono font-bold ${dim ? 'text-primary/90' : 'text-primary'}" data-count="${score}">0</span>`;
}
function animateDial(el) {
  const num = el.querySelector('[data-count]');
  const ring = el.querySelector('circle[stroke-dasharray]:not([class*="text-white/10"])');
  const target = parseInt(num?.dataset.count || '0', 10);
  const off0 = C, off1 = C * (1 - target / 100);
  const t0 = performance.now();
  const tick = (t) => {
    const k = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - k, 3);
    if (num) num.textContent = Math.round(target * e);
    if (ring) ring.setAttribute('stroke-dashoffset', (off0 + (off1 - off0) * e).toFixed(1));
    if (k < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
const FACTOR_LABEL = { hook: 'HOOK', story: 'STORY', payoff: 'PAYOFF', energy: 'ENERGY', pacing: 'PACING', event: 'EVENT' };

/* ---------- studio: option chips (glass popovers) ---------- */
const chosen = { top_n: 3, style: 'wordpop', framing: 'blur' };
let STYLES = [];
function closePopovers() { document.querySelectorAll('.chip-pop').forEach((p) => p.remove()); }
document.addEventListener('click', (e) => { if (!e.target.closest('[data-chip]')) closePopovers(); });
document.querySelectorAll('[data-chip-btn]').forEach((btn) => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const kind = btn.dataset.chipBtn;
    const existing = btn.parentElement.querySelector('.chip-pop');
    closePopovers();
    if (existing) return;
    const opts = kind === 'clips' ? [1, 2, 3, 4, 5].map((n) => ({ v: n, label: String(n) }))
      : kind === 'captions' ? STYLES.map((s) => ({ v: s.id, label: s.name }))
        : kind === 'framing' ? [{ v: 'blur', label: 'blur-pad 9:16' }, { v: 'crop', label: 'crop center' }, { v: 'crop-left', label: 'crop left' }, { v: 'crop-right', label: 'crop right' }]
          : [{ v: 'auto', label: 'auto' }];
    const key = kind === 'clips' ? 'top_n' : kind === 'captions' ? 'style' : 'framing';
    const pop = document.createElement('div');
    pop.className = 'chip-pop absolute bottom-full mb-2 left-0 z-50 min-w-[180px] rounded-2xl bg-surface-container-high/95 backdrop-blur-2xl border border-white/10 shadow-[0_20px_50px_rgba(0,0,0,0.8)] p-1.5';
    pop.innerHTML = opts.map((o) => `<button data-v="${esc(o.v)}" class="w-full text-left px-4 py-2 rounded-xl font-body-sm text-body-sm ${String(o.v) === String(chosen[key]) ? 'bg-primary text-on-primary font-semibold' : 'text-on-surface-variant hover:bg-white/[0.06] hover:text-on-surface'} transition-all">${esc(o.label)}</button>`).join('');
    btn.parentElement.appendChild(pop);
    pop.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      chosen[key] = kind === 'clips' ? parseInt(b.dataset.v, 10) : b.dataset.v;
      const val = btn.querySelector('.text-primary.font-medium');
      if (val) val.textContent = kind === 'captions' ? (STYLES.find((s) => s.id === chosen.style)?.name || chosen.style) : kind === 'framing' ? ({ blur: 'blur-pad 9:16', crop: 'crop center', 'crop-left': 'crop left', 'crop-right': 'crop right' }[chosen.framing]) : String(chosen[key]);
      closePopovers();
    }));
  });
});

/* ---------- studio: URL + upload ---------- */
$('make-clips-btn').addEventListener('click', () => {
  const url = $('url-input').value.trim();
  if (!url) { $('url-input').focus(); toast('Paste a YouTube link first — or drop an MP4.', true); return; }
  const btn = $('make-clips-btn');
  btn.disabled = true;
  btn.innerHTML = '<span>ANALYZING…</span><span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span>';
  api(`/api/from_url?url=${encodeURIComponent(url)}&style=${chosen.style}&framing=${chosen.framing}&top_n=${chosen.top_n}`, { method: 'POST' })
    .then((d) => { watch(d.job_id, url); toast('Engine engaged — watch the edit bay.'); })
    .catch((e) => { toast('Could not start: ' + e.message, true); resetMakeBtn(); });
});
function resetMakeBtn() {
  const btn = $('make-clips-btn');
  btn.disabled = false;
  btn.innerHTML = '<span>MAKE CLIPS</span><span class="material-symbols-outlined text-[18px]">bolt</span>';
}
const dz = $('dropzone');
dz.addEventListener('click', () => $('file').click());
dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('bg-white/[0.08]', 'scale-[1.01]'); });
dz.addEventListener('dragleave', () => dz.classList.remove('bg-white/[0.08]', 'scale-[1.01]'));
dz.addEventListener('drop', (e) => {
  e.preventDefault(); dz.classList.remove('bg-white/[0.08]', 'scale-[1.01]');
  if (e.dataTransfer.files[0]) { $('file').files = e.dataTransfer.files; uploadFile(e.dataTransfer.files[0]); }
});
$('file').addEventListener('change', () => { if ($('file').files[0]) uploadFile($('file').files[0]); });
function uploadFile(f) {
  if (f.size > 2 * 1024 ** 3) { toast('Over the 2 GB limit.', true); return; }
  toast(`Ingesting ${f.name} (${(f.size / 1048576).toFixed(0)} MB)…`);
  fetch(`/api/upload?name=${encodeURIComponent(f.name)}&style=${chosen.style}&framing=${chosen.framing}&top_n=${chosen.top_n}`,
    { method: 'POST', body: f })
    .then((r) => r.json())
    .then((d) => { if (d.error) throw new Error(d.error); watch(d.job_id, f.name); })
    .catch((e) => toast('Upload failed: ' + e.message, true));
}

/* ---------- job watching → processing screen ---------- */
const STAGES = [
  { key: 'probe', label: "Reading the audio's energy profile" },
  { key: 'extract', label: 'Isolating the audio track' },
  { key: 'laughter', label: 'Detecting audience laughter' },
  { key: 'moments', label: 'Finding peak moments (audio + camera cuts)' },
  { key: 'transcribe', label: 'Transcribing — whisper-large-v3-turbo' },
  { key: 'story', label: 'ProX story pass' },
  { key: 'judge', label: 'Judge QC' },
  { key: 'render', label: 'Rendering 9:16 clips' },
  { key: 'meta', label: 'Metadata & finishing' },
];
function stageIndex(job) {
  const s = (job.stage || '').toLowerCase();
  if (job.status === 'done') return STAGES.length - 1;
  if (s.includes('render')) return 6;
  if (s.includes('transcrib')) return 4;
  if (s.includes('prox') || s.includes('mining')) return 5;
  if (s.includes('peak')) return 3;
  if (s.includes('laughter')) return 2;
  if (s.includes('energy') || s.includes('probe')) return 0;
  if (s.includes('extract')) return 1;
  if (s.includes('title') || s.includes('qc') || s.includes('judge')) return 5.5;
  return 0;
}
let pollTimer = null;
function watch(jobId, name) {
  if (pollTimer) clearInterval(pollTimer);
  showScreen('processing');
  $('proc-job-id').textContent = jobId;
  $('proc-name').textContent = name || jobId;
  const tick = () => api(`/api/job/${jobId}?light=1`).then((job) => {
    renderProcessing(job);
    if (job.status === 'done') { clearInterval(pollTimer); pollTimer = null; onJobDone(job); resetMakeBtn(); }
    if (job.status === 'error') { clearInterval(pollTimer); pollTimer = null; toast('Job failed: ' + (job.error || 'unknown'), true); showScreen('studio'); resetMakeBtn(); }
  }).catch(() => {});
  tick();
  pollTimer = setInterval(tick, 1600);
}
function renderProcessing(job) {
  const pct = Math.max(0, Math.min(100, job.progress || 0));
  $('proc-pct').textContent = `${Math.round(pct)}%`;
  const ring = $('progress-circle');
  if (ring) ring.setAttribute('stroke-dashoffset', (722.56 * (1 - pct / 100)).toFixed(2));
  $('proc-sub').textContent = job.src_name ? `${job.src_name}` : 'working…';
  $('proc-meta').innerHTML = `<span>${new Date((job.created || 0) * 1000).toLocaleTimeString()}</span><span>·</span><span>${job.duration ? fmtTime(job.duration) + ' source' : 'probing…'}</span><span>·</span><span>${(job.brains || ['groq']).join(' + ')}</span>`;
  const idx = stageIndex(job);
  const rows = STAGES.map((st, i) => {
    if (i < idx) return `<div class="flex items-center gap-3 px-3 py-1.5 rounded-lg transition-colors hover:bg-white/[0.02]"><span class="text-white/60 font-medium text-body-sm">✓</span><span class="text-white/70 font-body-sm text-body-sm">${esc(st.label)}</span><span class="ml-auto font-data-mono text-data-mono text-white/20">DONE</span></div>`;
    if (i === idx) return `<div class="relative flex items-center justify-between px-4 py-2.5 rounded-xl bg-white/[0.08] shadow-[inset_0_0_24px_rgba(255,255,255,0.08),0_10px_30px_rgba(0,0,0,0.5)]"><div class="flex items-center gap-3"><span class="text-primary font-semibold text-body-sm animate-pulse">▶</span><span class="text-primary font-semibold font-body-sm text-body-sm tracking-wide">${esc(job.stage || st.label)}</span></div><div class="flex items-center gap-2"><span class="w-1.5 h-1.5 rounded-full bg-primary animate-ping"></span><span class="font-data-mono text-data-mono text-primary/80 font-medium">IN PROGRESS</span></div></div>`;
    return `<div class="flex items-center gap-3 px-3 py-1.5 rounded-lg opacity-40"><span class="text-white/30 font-medium text-body-sm">○</span><span class="text-white/30 font-body-sm text-body-sm">${esc(st.label)}</span><span class="ml-auto font-data-mono text-data-mono text-white/20">QUEUED</span></div>`;
  });
  $('proc-stages').innerHTML = rows.join('');
  $('proc-stage-n').textContent = `STAGE ${Math.min(STAGES.length, Math.floor(idx) + 1)} OF ${STAGES.length}`;
  $('proc-pill').textContent = job.stage || '—';
  $('proc-engine').textContent = 'ENGINE: ' + ((job.brains || ['groq']).join(' · ').toUpperCase()) + ' · PROX v5';
  // live clip tray
  if ((job.clips || []).length) {
    $('proc-tray').innerHTML = job.clips.map((c, i) => `
      <div class="bg-white/[0.03] backdrop-blur-xl rounded-2xl p-4 flex items-center gap-4">
        <div class="w-16 h-16 rounded-xl bg-surface-container-high overflow-hidden shrink-0 relative">
          <video class="w-full h-full object-cover grayscale brightness-90" src="${esc(c.file)}" preload="metadata" muted></video>
          <div class="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent"></div>
          <span class="absolute bottom-1 right-1 font-data-mono text-[10px] text-white/80">${fmtTime(c.start)}</span>
        </div>
        <div class="flex flex-col min-w-0">
          <span class="font-label-caps text-label-caps text-white/40 uppercase">Clip Candidate 0${i + 1}</span>
          <span class="font-body-sm text-body-sm text-white font-medium truncate">${esc(c.title)}</span>
          <span class="font-data-mono text-data-mono text-white/40">Score: ${c.score}</span>
        </div>
      </div>`).join('');
  }
}
function onJobDone(job) {
  currentJob = job;
  renderClips(); renderCandidates(); renderTranscript(); renderRecentJobs();
  showScreen('clips');
  toast(`Done — ${job.clips.length} clips on the podium.`);
}

/* ---------- studio: recent jobs rail ---------- */
function renderRecentJobs() {
  api('/api/jobs').then((jobs) => {
    const done = jobs.filter((j) => j.status === 'done' && j.clips > 0).slice(0, 3);
    $('pipeline-ready').textContent = `${jobs.length} JOBS`;
    $('recent-jobs').innerHTML = done.length ? done.map((j) => `
      <div class="bg-white/[0.03] backdrop-blur-2xl rounded-[22px] p-4 flex items-center justify-between hover:bg-white/[0.06] transition-all duration-300 group cursor-pointer shadow-lg" data-job="${esc(j.id)}">
        <div class="flex items-center gap-3.5 min-w-0">
          <div class="w-11 h-16 rounded-[10px] overflow-hidden relative bg-surface-container-lowest shrink-0 shadow-inner flex items-center justify-center">
            <span class="material-symbols-outlined text-white/30 text-[20px]">movie</span>
            <span class="absolute bottom-1 right-1 font-data-mono text-[9px] text-primary/90 leading-none">9:16</span>
          </div>
          <div class="flex flex-col min-w-0">
            <span class="font-headline-sm text-[15px] font-semibold text-primary truncate">${esc(j.name || j.id)}</span>
            <div class="flex items-center gap-2 mt-1">
              <span class="font-data-mono text-data-mono text-on-surface-variant/60">${j.clips} clips</span>
              <span class="w-1 h-1 rounded-full bg-white/20"></span>
              <span class="font-data-mono text-data-mono text-on-surface-variant/40">${ago(j.created)}</span>
            </div>
          </div>
        </div>
        <div class="relative w-12 h-12 flex items-center justify-center shrink-0 ml-2">${j.top_score ? dial(j.top_score) : '<span class="material-symbols-outlined text-white/30">drafts</span>'}</div>
      </div>`).join('')
      : `<div class="col-span-3 rounded-[22px] bg-white/[0.02] border border-dashed border-white/10 p-8 text-center font-body-sm text-body-sm text-on-surface-variant/50">No finished jobs yet — make your first clips above.</div>`;
    $('recent-jobs').querySelectorAll('[data-job]').forEach((card) =>
      card.addEventListener('click', () => openJob(card.dataset.job)));
    done.forEach((j) => { const d = $('recent-jobs').querySelector(`[data-job="${j.id}"] [data-count]`); if (d) animateDial(d.closest('.relative')); });
  }).catch(() => {});
}
document.addEventListener('click', (e) => {
  const card = e.target.closest('[data-job]');
  if (card) openJob(card.dataset.job);
});
function openJob(id, screen) {
  api(`/api/job/${id}`).then((job) => {
    if (job.status === 'done' && (job.clips || []).length) {
      currentJob = job; renderClips(); renderCandidates(); renderTranscript();
      showScreen(screen || 'clips');
    }
    else if (job.status === 'error') toast('That job failed — re-run it from Studio.', true);
    else watch(id, job.name);
  }).catch((e) => toast('Could not open job: ' + (e && e.message ? e.message : e), true));
}

/* ---------- clips podium ---------- */
let currentJob = null;
const RANK_LABEL = ['ALPHA', 'BETA', 'GAMMA', 'DELTA', 'EPSILON', 'ZETA'];
function factorBars(f, dim) {
  const cls = dim ? 'text-on-surface-variant/40' : 'text-on-surface-variant/50';
  const num = dim ? 'text-primary/70' : 'text-primary';
  const fill = dim ? 'from-white/40 to-primary/80' : 'from-white/60 to-primary';
  return Object.keys(FACTOR_LABEL).map((k) => {
    const v = (f || {})[k] ?? 0;
    return `<div class="flex flex-col gap-1">
      <div class="flex justify-between items-center font-label-caps text-label-caps uppercase ${cls}"><span>${FACTOR_LABEL[k]}</span><span class="font-data-mono text-data-mono ${num} font-medium">${v}</span></div>
      <div class="h-1 w-full bg-white/10 rounded-full overflow-hidden"><div class="h-full bg-gradient-to-r ${fill} rounded-full" style="width:${v}%"></div></div>
    </div>`;
  }).join('');
}
function renderClips() {
  const host = $('clips');
  if (!currentJob || !(currentJob.clips || []).length) {
    host.innerHTML = `<div class="col-span-3 rounded-[24px] bg-white/[0.02] border border-dashed border-white/10 p-12 text-center">
      <span class="material-symbols-outlined text-white/25 text-[40px]">theaters</span>
      <p class="font-body-md text-body-md text-on-surface-variant/60 mt-3">No clips on the podium yet — run a job in the Studio or open one from Recent jobs.</p></div>`;
    $('clips-qc').textContent = '—';
    return;
  }
  const job = currentJob;
  $('clips-jobname').textContent = job.name || job.id;
  $('clips-qc').textContent = `${job.clips.filter((c) => c.qc === 'verified').length} OF ${job.clips.length} PASS QC`;
  $('clips-brain').textContent = `brain ${(job.brains || ['groq']).join('+')}`;
  $('clips-models').textContent = `PROX v5 · ${(job.content_type || 'auto').toUpperCase()}`;
  $('tele-engine').textContent = `ENGINE ${(job.brains || ['groq']).join('+').toUpperCase()}`;
  $('tele-job').textContent = `${job.name || job.id} · ${job.clips.length} CLIPS · ${fmtTime(job.duration || 0)}`;
  host.innerHTML = job.clips.map((c, i) => {
    const dim = c.qc !== 'verified';
    const qc = c.qc === 'verified'
      ? `<span class="inline-flex items-center gap-1.5 bg-white/10 text-primary font-label-caps text-label-caps uppercase px-3 py-1 rounded-full shadow-sm"><span class="material-symbols-outlined text-[12px] text-primary">check_circle</span><span>verified</span></span>`
      : `<span class="inline-flex items-center gap-1.5 bg-white/[0.03] text-on-surface-variant/70 font-label-caps text-label-caps uppercase px-3 py-1 rounded-full shadow-sm"><span class="material-symbols-outlined text-[12px] text-on-surface-variant/60">radio_button_partial</span><span>unverified</span></span>`;
    return `<article class="group relative rounded-[24px] ${dim ? 'bg-white/[0.03] opacity-75 hover:opacity-100' : 'bg-white/[0.04]'} backdrop-blur-2xl p-6 flex flex-col justify-between transition-all duration-300 hover:bg-white/[0.06] hover:shadow-[0_24px_50px_rgba(0,0,0,0.8),inset_0_0_24px_rgba(255,255,255,0.06)]" data-clip="${i}">
      <div class="flex flex-col">
        <div class="relative w-full aspect-[9/14] rounded-2xl overflow-hidden bg-surface-container-lowest mb-5 shadow-inner">
          <video class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700 ease-out brightness-90 contrast-125" src="${esc(c.file)}" controls preload="metadata"></video>
          <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/40 pointer-events-none"></div>
          <div class="absolute top-3.5 left-3.5 px-3 py-1 rounded-full bg-black/70 backdrop-blur-md flex items-center gap-1.5 shadow-lg">
            <span class="font-data-mono text-data-mono text-primary font-semibold tracking-wider">#${String(i + 1).padStart(2, '0')}</span>
            <span class="font-label-caps text-[9px] uppercase tracking-widest text-primary/60">${RANK_LABEL[i] || 'CLIP'}</span>
          </div>
          <div class="absolute top-3.5 right-3.5 w-11 h-11 rounded-full bg-black/75 backdrop-blur-md flex items-center justify-center shadow-lg dial" data-dial>${dial(c.score, dim)}</div>
          <div class="absolute bottom-3 left-3.5 flex items-center gap-2 bg-black/60 backdrop-blur-md px-2.5 py-1 rounded-full text-white/80 font-data-mono text-data-mono">
            <span class="material-symbols-outlined text-[13px] text-primary">play_arrow</span><span>${c.duration}s</span>
          </div>
        </div>
        <div class="flex items-center gap-2 mb-3">${qc}<span class="font-data-mono text-[11px] text-on-surface-variant/40">${esc((job.picker || 'prox').toUpperCase())} // ${fmtTime(c.start)}</span></div>
        <h2 class="font-headline-sm text-headline-sm font-semibold ${dim ? 'text-primary/90' : 'text-primary'} mb-2 leading-snug">${esc(c.meta?.title || c.title)}</h2>
        ${c.hook ? `<p class="font-body-sm text-body-sm italic ${dim ? 'text-on-surface-variant/60' : 'text-on-surface-variant/80'} mb-3 pl-2.5 bg-gradient-to-r from-white/10 to-transparent rounded-l-sm">“${esc(c.hook)}”</p>` : ''}
        ${c.verdict ? `<div class="flex items-start gap-2.5 bg-white/[0.03] p-3 rounded-xl mb-5 text-on-surface-variant/60 font-body-sm text-body-sm leading-relaxed"><span class="text-base select-none mt-0.5">⚖️</span><span class="italic">${esc(c.verdict)}</span></div>` : ''}
        <div class="grid grid-cols-2 gap-x-4 gap-y-2.5 mb-6 pt-1">${factorBars(c.factors, dim)}</div>
      </div>
      <div class="flex flex-col gap-2 pt-2">
        <button data-post="${i}" class="w-full bg-primary text-on-primary font-headline-sm text-body-sm font-semibold py-3 px-4 rounded-full flex items-center justify-center gap-2 hover:bg-white/90 active:scale-[0.98] transition-all shadow-[0_0_24px_rgba(255,255,255,0.35)] cursor-pointer">
          <span class="material-symbols-outlined text-[16px]">play_circle</span><span>Post to YouTube</span>
        </button>
        <div class="flex items-center justify-center gap-3 py-1 text-center font-label-caps text-[10px] tracking-widest text-on-surface-variant/40">
          <button data-download="${i}" class="hover:text-primary transition-colors cursor-pointer uppercase">Download</button><span class="opacity-30">·</span>
          <button data-restyle="${i}" class="hover:text-primary transition-colors cursor-pointer uppercase">Restyle</button><span class="opacity-30">·</span>
          <button data-meta="${i}" class="hover:text-primary transition-colors cursor-pointer uppercase">Edit meta</button>
        </div>
      </div>
    </article>`;
  }).join('');
  host.querySelectorAll('[data-dial]').forEach((d) => animateDial(d));
  host.querySelectorAll('[data-post]').forEach((b) => b.addEventListener('click', () => postClip(parseInt(b.dataset.post, 10))));
  host.querySelectorAll('[data-download]').forEach((b) => b.addEventListener('click', () => {
    const c = currentJob.clips[b.dataset.download];
    const a = document.createElement('a'); a.href = c.file; a.download = `${currentJob.id}_${b.dataset.download + 1}.mp4`; a.click();
  }));
  host.querySelectorAll('[data-restyle]').forEach((b) => b.addEventListener('click', () => restyleClip(parseInt(b.dataset.restyle, 10))));
  host.querySelectorAll('[data-meta]').forEach((b) => b.addEventListener('click', () => editMeta(parseInt(b.dataset.meta, 10))));
}
function postClip(i) {
  const platforms = socialReady ? ['youtube'] : [];
  if (!platforms.length) { toast('YouTube not connected yet — finish OAuth in Connect.', true); showScreen('connect'); return; }
  api('/api/post', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: currentJob.id, index: i, platforms }) })
    .then(() => toast('Queued for YouTube — posting runs in the background.'))
    .catch((e) => toast('Post failed: ' + e.message, true));
}
function restyleClip(i) {
  const c = currentJob.clips[i];
  const style = prompt('Caption style id (available: ' + STYLES.map((s) => s.id).join(', ') + '):', chosen.style);
  if (!style) return;
  api('/api/custom', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: currentJob.id, start: c.start, end: c.end, style }) })
    .then(() => { toast('Restyled clip rendering…'); openJob(currentJob.id); })
    .catch((e) => toast('Restyle failed: ' + e.message, true));
}
function editMeta(i) {
  const c = currentJob.clips[i];
  const title = prompt('Video title:', c.meta?.title || c.title);
  if (title == null) return;
  const description = prompt('Description:', c.meta?.description || '') ?? undefined;
  api(`/api/job/${currentJob.id}/meta/${i}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, description }) })
    .then(() => { currentJob.clips[i].meta = { ...(c.meta || {}), title, description }; renderClips(); toast('Metadata saved.'); })
    .catch((e) => toast('Save failed: ' + e.message, true));
}
$('clips-export').addEventListener('click', () => {
  if (!currentJob) return;
  const text = currentJob.clips.map((c, i) => `#${i + 1} ${c.meta?.title || c.title}\n${c.meta?.description || ''}\n${(c.meta?.hashtags || []).join(' ')}`).join('\n\n');
  navigator.clipboard.writeText(text).then(() => toast('Metadata manifest copied to clipboard.'));
});
$('clips-batch').addEventListener('click', () => {
  if (!currentJob) return;
  if (!socialReady) { toast('Connect YouTube first — one click in Connect.', true); showScreen('connect'); return; }
  currentJob.clips.forEach((_, i) => postClip(i));
});

/* ---------- candidates lab ---------- */
let candFilter = 'all';
document.querySelectorAll('[data-filter]').forEach((b) => b.addEventListener('click', () => {
  candFilter = b.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach((x) => {
    const on = x.dataset.filter === candFilter;
    x.className = on
      ? 'bg-primary text-on-primary font-headline-sm text-[12px] leading-tight px-4 py-1.5 rounded-full shadow-[0_0_20px_rgba(255,255,255,0.3)] transition-all'
      : 'bg-white/[0.04] hover:bg-white/[0.08] text-on-surface font-body-sm text-body-sm px-4 py-1.5 rounded-full transition-all';
  });
  renderCandidates();
}));
function renderCandidates() {
  const host = $('cands');
  const job = currentJob;
  const cands = (job?.candidates || []).map((c, i) => ({ ...c, _idx: i })).filter((c) => !c.selected);
  const renderedCount = 0;
  $('cands-pool').textContent = `PROX-LAB::${job ? job.id.toUpperCase() : 'EMPTY'}`;
  const q = $('cands-queue'); if (q) q.textContent = job ? `POOL ${cands.length} · ${job.clips.length} RENDERED` : 'OPEN A JOB';
  if (!cands.length) {
    host.innerHTML = `<div class="rounded-2xl bg-white/[0.02] border border-dashed border-white/10 p-8 text-center font-body-sm text-body-sm text-on-surface-variant/50">No runner-ups yet — candidates appear here after a run (open a job from the Studio rail first).</div>`;
    return;
  }
  const rows = cands.map((c, i) => {
    const f = c.factors || c.measured || {};
    const score = c.score || Math.round(30 + 69 * ((f.energy || 0.5)));
    const peak = (f.event || 0) >= 0.5;
    if (candFilter === 'verified' && !(c.qc === 'verified')) return '';
    if (candFilter === 'peak' && !peak) return '';
    const dots = [f.hook, f.story, f.event].map((v) => `<span class="w-1.5 h-1.5 rounded-full ${v >= 0.66 ? 'bg-primary' : v >= 0.33 ? 'bg-primary/50' : 'bg-primary/20'}"></span>`).join('');
    return `<div class="group relative rounded-2xl bg-white/[0.02] hover:bg-white/[0.06] p-3 md:px-5 md:py-3.5 transition-all duration-200 flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div class="flex items-center gap-4 min-w-0 flex-1">
        <div class="relative w-24 h-14 rounded-lg overflow-hidden bg-surface-container-lowest shrink-0 shadow-inner flex items-center justify-center">
          <span class="material-symbols-outlined text-white text-[14px]">videocam</span>
        </div>
        <div class="flex flex-col min-w-0">
          <span class="font-body-md text-body-md font-medium text-on-surface truncate">${esc(c.title || c.summary || 'candidate')}</span>
          <div class="flex items-center gap-3 mt-1">
            <span class="font-label-caps text-[10px] text-on-surface-variant uppercase tracking-wider">${peak ? 'Telemetry: peak event inside' : 'Telemetry: measured factors'}</span>
            <div class="flex items-center gap-1.5">${dots}</div>
          </div>
        </div>
      </div>
      <div class="flex items-center justify-between md:justify-end gap-6 shrink-0">
        <div class="flex items-center gap-3">
          <span class="font-data-mono text-data-mono text-on-surface-variant bg-white/[0.05] px-2.5 py-1 rounded-md">${Math.round(c.start)}–${Math.round(c.end)}s</span>
          <div class="relative flex items-center justify-center w-9 h-9 rounded-full bg-surface-container-lowest dial-sm" data-dial-sm data-score="${score}">
            <svg class="w-full h-full -rotate-90" viewbox="0 0 36 36">
              <path class="text-white/10" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="currentColor" stroke-width="3"></path>
              <path class="text-primary" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="currentColor" stroke-dasharray="${score}, 100" stroke-linecap="round" stroke-width="3"></path>
            </svg>
            <span class="absolute font-data-mono text-[11px] font-semibold text-primary">${score}</span>
          </div>
        </div>
        <button data-cand="${i}" class="bg-primary text-on-primary font-headline-sm text-[12px] font-semibold px-4 py-1.5 rounded-full shadow-[0_0_15px_rgba(255,255,255,0.25)] hover:bg-white/90 active:scale-95 transition-all">RENDER</button>
      </div>
    </div>`;
  }).join('');
  host.innerHTML = rows || `<div class="rounded-2xl bg-white/[0.02] border border-dashed border-white/10 p-8 text-center font-body-sm text-body-sm text-on-surface-variant/50">No candidates match this filter.</div>`;
  host.querySelectorAll('[data-cand]').forEach((b) => b.addEventListener('click', () => {
    const idx = cands[parseInt(b.dataset.cand, 10)]._idx;
    api('/api/render', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: currentJob.id, cand_index: idx }) })
      .then(() => { toast('Rendering runner-up…'); openJob(currentJob.id); })
      .catch((e) => toast('Render failed: ' + e.message, true));
  }));
}
$('cands-render-all').addEventListener('click', () => {
  if (!currentJob) { toast('Open a job first.', true); return; }
  const cands = (currentJob.candidates || []).filter((c) => !c.selected).slice(0, 3);
  cands.forEach((c, k) => setTimeout(() =>
    api('/api/render', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: currentJob.id, cand_index: c._idx }) }).catch(() => {}), k * 2500));
  toast(`Rendering ${cands.length} runner-ups…`);
});

/* ---------- transcript ---------- */
let peaksOnly = false;
$('transcript-peaks').addEventListener('click', () => { peaksOnly = !peaksOnly; renderTranscript(); });
$('transcript-search').addEventListener('input', renderTranscript);
$('transcript-custom').addEventListener('click', () => {
  if (!currentJob) { toast('Open a job first.', true); return; }
  const se = prompt(`Custom cut window in seconds (start,end) — video is ${Math.round(currentJob.duration || 0)}s:`, '0,30');
  if (!se) return;
  const [a, b] = se.split(',').map((x) => parseFloat(x.trim()));
  if (!(a >= 0) || !(b > a)) { toast('Give a valid start,end pair.', true); return; }
  api('/api/custom', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: currentJob.id, start: a, end: b, style: chosen.style }) })
    .then(() => { toast('Custom cut rendering…'); openJob(currentJob.id); })
    .catch((e) => toast('Cut failed: ' + e.message, true));
});
$('transcript-srt').addEventListener('click', () => {
  if (!currentJob) { toast('Open a job first.', true); return; }
  const pad = (t) => { const ms = Math.round((t % 1) * 1000); const s = Math.floor(t); return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')},${String(ms).padStart(3, '0')}`; };
  const srt = (currentJob.segments || []).map((s, i) => `${i + 1}\n${pad(s.start)} --> ${pad(s.end)}\n${s.text}\n`).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([srt], { type: 'text/plain' }));
  a.download = `${currentJob.id}.srt`; a.click();
});
function renderTranscript() {
  const host = $('transcript-container');
  const job = currentJob;
  const segs = job?.segments || [];
  $('transcript-count').textContent = segs.length ? `${segs.length} blocks · ${fmtTime(job.duration)}` : 'open a job to read its transcript';
  $('transcript-stt').textContent = (job?.mode || 'stt').split('+')[0].toUpperCase();
  $('transcript-precision').textContent = segs.length ? `Precision: ${segs.length} segments` : '—';
  const spec = $('wave-spec'); if (spec) spec.textContent = '16 kHz · mono';
  const sync = $('transcript-sync'); if (sync) sync.textContent = 'whisper sync';
  if (!segs.length) { host.innerHTML = `<div class="p-6 rounded-xl bg-white/[0.02] border border-dashed border-white/10 text-center font-body-sm text-body-sm text-on-surface-variant/50">No transcript loaded.</div>`; renderWave(); return; }
  const q = $('transcript-search').value.trim().toLowerCase();
  const clipStarts = (job?.clips || []).map((c) => c.start);
  const isPeak = (s) => clipStarts.some((t) => s.start <= t && t < s.end);
  const blocks = segs.map((s, i) => {
    if (q && !(s.text || '').toLowerCase().includes(q)) return '';
    if (peaksOnly && !isPeak(s)) return '';
    const t = fmtTime(s.start);
    if (isPeak(s)) {
      const clip = job.clips.find((c) => s.start <= c.start && c.start < s.end) || job.clips[0];
      return `<div class="p-4 rounded-xl bg-white/[0.08] shadow-[inset_12px_0_24px_-10px_rgba(255,255,255,0.25)] flex items-start gap-4 transition-all relative cursor-pointer" data-seek="${s.start}">
        <div class="absolute left-0 top-0 bottom-0 w-1 bg-primary rounded-l-xl shadow-[0_0_12px_rgba(255,255,255,0.8)]"></div>
        <span class="font-data-mono text-data-mono text-primary font-medium pt-0.5">${t}</span>
        <div class="flex-1 flex flex-col gap-1.5">
          <div class="flex items-center gap-2 flex-wrap">
            <p class="font-headline-sm text-headline-sm text-primary font-semibold leading-snug">${esc(s.text)}</p>
            <span class="font-label-caps text-label-caps uppercase text-primary bg-white/15 px-2.5 py-0.5 rounded-full inline-flex items-center gap-1 shadow-sm"><span class="material-symbols-outlined text-[12px]">local_fire_department</span>peak moment</span>
          </div>
          <div class="flex items-center gap-3 mt-1 flex-wrap">
            <span class="font-data-mono text-data-mono text-on-surface-variant/80">${clip.title}</span>
            <span class="w-1 h-1 rounded-full bg-white/30"></span>
            <span class="font-data-mono text-data-mono text-primary">Score ${clip.score}</span>
          </div>
        </div>
      </div>`;
    }
    return `<div class="p-3 rounded-xl hover:bg-white/[0.03] transition-all cursor-pointer group flex items-start gap-4" data-seek="${s.start}">
      <span class="font-data-mono text-data-mono text-on-surface-variant/60 pt-0.5 group-hover:text-primary">${t}</span>
      <div class="flex-1"><p class="font-body-md text-body-md text-on-surface-variant group-hover:text-on-surface transition-colors">${esc(s.text)}</p></div>
      <span class="font-label-caps text-label-caps text-on-surface-variant/30 uppercase">#${i + 1}</span>
    </div>`;
  }).join('');
  host.innerHTML = blocks || `<div class="p-6 text-center font-body-sm text-body-sm text-on-surface-variant/50">Nothing matches “${esc(q)}”.</div>`;
  $('transcript-flagged').textContent = String(job?.clips?.length || 0);
  renderWave();
  host.querySelectorAll('[data-seek]').forEach((b) => b.addEventListener('click', () => setPlayhead(parseFloat(b.dataset.seek))));
}
function renderWave() {
  const job = currentJob;
  const dur = job?.duration || 0;
  const starts = (job?.clips || []).map((c) => c.start);
  $('wave-now').textContent = dur ? fmtTime(0) : '—';
  const R = $('wave-ruler');
  if (R && dur) R.innerHTML = [0, 0.25, 0.5, 0.75].map((f) => `<span>${fmtTime(dur * f)}</span>`).join('') + `<span id="wave-now" class="text-primary font-semibold">${fmtTime(dur)}</span>`;
  const bars = [];
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const N = 56;
  for (let i = 0; i < N; i++) {
    const t = (i / N) * dur;
    const near = starts.some((s) => Math.abs(s - t) < dur / N);
    const h = 6 + Math.round(rnd() * (near ? 26 : 18));
    bars.push(`<div class="w-1.5 h-${h} ${near ? 'bg-primary shadow-[0_0_8px_rgba(255,255,255,0.7)]' : 'bg-white/25'} rounded-full"></div>`);
  }
  $('wave-bars').innerHTML = bars.join('');
  $('wave-markers').innerHTML = starts.map((s) =>
    `<div class="absolute top-1 bottom-1 w-px bg-white/30 z-10 pointer-events-none" style="left:${dur ? (s / dur) * 100 : 0}%"></div>`).join('');
}
function setPlayhead(t) {
  const dur = currentJob?.duration || 1;
  $('wave-playhead').style.left = `${Math.min(100, (t / dur) * 100)}%`;
  $('wave-now').textContent = `${fmtTime(t)} (NOW)`;
  const clip = (currentJob?.clips || []).find((c) => c.start <= t && t < c.end);
  if (clip) {
    $('wave-title').textContent = clip.meta?.title || clip.title;
    $('wave-desc').textContent = clip.hook || clip.verdict || '';
    $('wave-score').textContent = String(clip.score);
    $('wave-metric').textContent = clip.qc === 'verified' ? 'judge verified' : 'unverified';
  }
}

/* ---------- connect: youtube + keys + diagnostics ---------- */
let socialReady = false;
function loadSocial() {
  api('/api/social/status').then((s) => {
    socialReady = !!(s.youtube && s.youtube.connected && s.youtube.configured);
    $('yt-status').textContent = s.youtube.connected ? `Connected${s.youtube.channel ? ' · ' + s.youtube.channel : ''}` : (s.youtube.configured ? 'Configured — press Connect' : 'Not connected');
  }).catch(() => {});
  fetch('/api/social/youtube/diagnose').then((r) => r.json()).then((d) => {
    const rawSteps = d.steps || {};
    const rows = Array.isArray(rawSteps) ? rawSteps : Object.entries(rawSteps).map(([k, v]) => ({ name: k.replace(/_/g, ' '), ok: !!v.ok, detail: v.detail || '' }));
    const row = (ok, label, value) => `<div class="flex items-center justify-between py-1">
      <div class="flex items-center gap-3"><span class="material-symbols-outlined ${ok ? 'text-primary' : 'text-on-surface-variant/40'} text-[18px]">${ok ? 'check_circle' : 'radio_button_unchecked'}</span>
      <span class="font-body-md text-body-md ${ok ? 'text-on-surface font-medium' : 'text-on-surface-variant'}">${esc(label)}</span></div>
      <span class="font-data-mono text-data-mono ${ok ? 'text-on-surface-variant' : 'text-on-surface-variant/50'}">${esc(value)}</span></div><div class="h-px w-full bg-surface-container-highest/40"></div>`;
    const g = (name) => { const x = rows.find((s) => (s.name || '').toLowerCase().includes(name)); return x ? !!x.ok : false; };
    const detail = (name) => { const x = rows.find((s) => (s.name || '').toLowerCase().includes(name)); return x ? (x.detail || 'READY') : '—'; };
    $('yt-check').innerHTML =
      row(g('env'), 'OAuth client in .env', detail('env')) +
      row(g('consent') || socialReady, 'Consent screen allows your account', socialReady ? 'OK' : 'add test user') +
      row(true, 'Redirect URI matches', location.origin + '/oauth/youtube/callback') +
      row(socialReady, 'Token stored', socialReady ? 'READY' : 'NONE');
  }).catch(() => { $('yt-check').innerHTML = ''; });
  $('yt-redirect').textContent = location.origin + '/oauth/youtube/callback';
}
$('yt-connect').addEventListener('click', () => {
  fetch('/api/social/youtube/start').then(async (r) => {
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'not configured');
    window.open(d.url, '_blank', 'width=520,height=720');
    toast('Google consent opened — finish there, this page updates itself.');
  }).catch((e) => toast(e.message, true));
});
$('yt-diagnose').addEventListener('click', () => {
  fetch('/api/social/youtube/diagnose').then((r) => r.json()).then((d) => {
    const known = d.known_errors || {};
    const rawSteps = d.steps || {};
    const stepRows = Array.isArray(rawSteps) ? rawSteps : Object.entries(rawSteps).map(([k, v]) => ({ name: k.replace(/_/g, ' '), ok: !!v.ok, detail: v.detail || '' }));
    const lines = stepRows.map((s) => `${s.ok ? '✓' : '○'} ${s.name}${s.detail ? ' — ' + s.detail : ''}`);
    const fix = Object.entries(known).map(([k, v]) => `${k}: ${v}`).join('\n');
    $('yt-diag').hidden = false;
    $('yt-diag').innerHTML = `<div class="rounded-2xl bg-surface-container-lowest/80 p-4 font-data-mono text-data-mono text-on-surface-variant whitespace-pre-wrap">${esc(lines.join('\n') + '\n\n' + fix)}</div>`;
  }).catch(() => {});
});
$('yt-redirect-copy').addEventListener('click', () => {
  navigator.clipboard.writeText(location.origin + '/oauth/youtube/callback').then(() => toast('Redirect URI copied.'));
});
/* keys */
const KEY_INPUTS = { groq: ['key-groq'], gemini: ['key-gemini'], youtube: ['key-yt-id', 'key-yt-secret'] };
function renderKeyStatus(st) {
  const set = (name, on, extra) => {
    const el = $('keychip-' + name);
    if (el) el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full ${on ? 'bg-primary animate-pulse' : 'bg-outline'}"></span><span>${extra || (on ? 'SAVED · ONLINE' : 'EMPTY')}</span>`;
  };
  set('groq', st.groq?.set); set('gemini', st.gemini?.set);
  set('youtube', st.yt_client_id?.set && st.yt_client_secret?.set);
  $('stt-model-label').textContent = `STT model: ${st.stt_model || 'whisper-large-v3-turbo'}`;
  if (st.groq?.masked) $('key-groq').placeholder = st.groq.masked;
  if (st.gemini?.masked) $('key-gemini').placeholder = st.gemini.masked;
  if (st.yt_client_id?.masked) $('key-yt-id').placeholder = st.yt_client_id.masked;
  if (st.yt_client_secret?.masked) $('key-yt-secret').placeholder = st.yt_client_secret.masked;
}
function loadKeys() {
  api('/api/keys').then((st) => { renderKeyStatus(st); $('pu-stt') && ($('pu-stt').textContent = `STT ${st.stt_model || '—'}`); }).catch(() => {});
}
document.querySelectorAll('[data-key]').forEach((btn) => btn.addEventListener('click', async () => {
  const which = btn.dataset.key;
  const body = {};
  const ids = KEY_INPUTS[which] || [];
  if (which === 'youtube') {
    if ($('key-yt-id').value.trim()) body.yt_client_id = $('key-yt-id').value.trim();
    if ($('key-yt-secret').value.trim()) body.yt_client_secret = $('key-yt-secret').value.trim();
    if ($('pu-yt-id')?.value.trim()) body.yt_client_id = $('pu-yt-id').value.trim();
    if ($('pu-yt-secret')?.value.trim()) body.yt_client_secret = $('pu-yt-secret').value.trim();
  } else {
    const el = $(ids[0]) || $('pu-' + which);
    const v = (el?.value || '').trim();
    if (!v) { toast('Paste a key first.', true); return; }
    body[which] = v;
  }
  if (!Object.keys(body).length) { toast('Nothing to save — paste a value first.', true); return; }
  btn.disabled = true;
  try {
    const res = await api('/api/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    renderKeyStatus(res.status || {});
    for (const [k, t] of Object.entries(res.tests || {})) {
      const chip = $('keychip-' + (k.startsWith('yt') ? 'youtube' : k));
      if (chip) chip.innerHTML = `<span class="w-1.5 h-1.5 rounded-full ${t.ok ? 'bg-primary' : 'bg-red-400'}"></span><span>${esc(t.detail)}</span>`;
      toast(`${k}: ${t.detail}`, !t.ok);
    }
    ids.forEach((id) => { if ($(id)) $(id).value = ''; });
    refreshCaps();
  } catch (e) { toast('Save failed: ' + e.message, true); }
  btn.disabled = false;
}));
$('pu-master').addEventListener('click', async () => {
  const body = {};
  if ($('pu-groq').value.trim()) body.groq = $('pu-groq').value.trim();
  if ($('pu-gemini').value.trim()) body.gemini = $('pu-gemini').value.trim();
  if ($('pu-yt-id').value.trim()) body.yt_client_id = $('pu-yt-id').value.trim();
  if ($('pu-yt-secret').value.trim()) body.yt_client_secret = $('pu-yt-secret').value.trim();
  if (!Object.keys(body).length) { toast('Paste at least one key.', true); return; }
  try {
    const res = await api('/api/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    for (const [k, t] of Object.entries(res.tests || {})) toast(`${k}: ${t.detail}`, !t.ok);
    ['pu-groq', 'pu-gemini', 'pu-yt-id', 'pu-yt-secret'].forEach((id) => { if ($(id)) $(id).value = ''; });
    refreshCaps().then(() => { if ((lastHealth?.brains || []).length) showScreen('studio'); });
  } catch (e) { toast('Save failed: ' + e.message, true); }
});
$('pu-offline').addEventListener('click', () => showScreen('studio'));

/* ---------- capabilities + diagnostics ---------- */
let lastHealth = null;
function refreshCaps() {
  return fetch('/api/health').then((r) => r.json()).then((h) => {
    lastHealth = h;
    $('engine-status').textContent = h.ok ? (h.brains?.length ? `Engine Online · ${h.brains.join(' + ')}` : 'Engine Online · offline mode') : 'Engine Offline';
    $('diag-ffmpeg').textContent = h.ffmpeg ? '✓' : '✗';
    $('diag-ytdlp').textContent = h.ytdlp ? '✓' : '✗';
    $('diag-judge').textContent = (h.brains || ['none']).join(' + ');
    $('diag-quota').textContent = `stt ${h.stt}`;
    if (!(h.brains || []).length) showScreen('powerup');
    return h;
  }).catch(() => { $('engine-status').textContent = 'Engine Offline'; });
}
$('diag-refresh').addEventListener('click', () => { refreshCaps(); loadKeys(); loadSocial(); toast('Diagnostics refreshed.'); });

/* ---------- header actions: settings + engine status ---------- */
(function wireHeader() {
  const btns = document.querySelectorAll('header button');
  if (btns[0]) btns[0].addEventListener('click', () => showScreen('connect'));
  if (btns[1]) btns[1].addEventListener('click', () => {
    const h = lastHealth;
    toast(h ? `brain: ${(h.brains || ['none']).join('+')} · stt: ${h.stt} · ffmpeg ${h.ffmpeg ? '✓' : '✗'}` : 'Engine unreachable', !h);
  });
  if (btns[2]) btns[2].addEventListener('click', () => showScreen('connect'));
})();

/* ---------- deep links: /?job=<id> · /?screen=<name> ---------- */
const wanted = new URLSearchParams(location.search).get('job');
const wantedScreen = new URLSearchParams(location.search).get('screen');

/* ---------- boot ---------- */
window.__probe = () => {
  const h1 = document.querySelector('#screen-studio h1');
  const cs = h1 ? getComputedStyle(h1) : null;
  const main = document.querySelector('main');
  const mcs = main ? getComputedStyle(main) : null;
  const wrap = document.querySelector('div[class*="pl-[312px]"]');
  return {
    h1FontSize: cs ? cs.fontSize : null, h1Color: cs ? cs.color : null,
    mainPaddingLeft: mcs ? mcs.paddingLeft : null,
    wrapFound: !!wrap, dpr: devicePixelRatio,
    inner: innerWidth + 'x' + innerHeight,
  };
};
(async function boot() {
  try { STYLES = await api('/api/styles'); } catch (e) { STYLES = []; }
  showScreen(wantedScreen && !wanted ? wantedScreen : 'studio');  // every section ships hidden
  refreshCaps();
  loadKeys();
  loadSocial();
  renderRecentJobs();
  if (wanted) openJob(wanted, wantedScreen || undefined);
})();
