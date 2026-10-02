/* ClipBlitz v3.5 front-end — Studio · Clips · Candidates · Transcript · Connect.

   Rendering is SURGICAL: a clip card is built once and afterwards only its post
   chips are patched, so video playback, typed metadata and the score animation all
   survive the 1.5s polls. Nothing here sets `opacity` on an animated element and
   nothing moves an element under the cursor.

   Every number shown is real: scores and factors come from the engine's measurement
   of that exact cut, the waveform is the measured RMS profile of the source audio,
   and the peak markers are the engine's own mined moments. If a value is missing we
   render nothing rather than a plausible-looking placeholder. */

const $ = (id) => document.getElementById(id);
const IC = (n) => '<svg class="ic" aria-hidden="true"><use href="#i-' + n + '"/></svg>';
const esc = (s) => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };
const fmt = (t) => { t = Math.max(0, t || 0); return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`; };

const SCREENS = ['studio', 'clips', 'lab', 'transcript', 'scout', 'connect'];
const TITLES = { studio: 'Studio', clips: 'Clips', lab: 'Candidates', transcript: 'Transcript', scout: 'Scout', connect: 'Connect' };
const FACTOR_LABEL = { hook: 'Hook', story: 'Story', payoff: 'Payoff', energy: 'Energy', pacing: 'Pacing', event: 'Event' };
const PLATFORM_LABEL = { youtube: 'YouTube', tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook', x: 'X Post' };
const PLATFORMS = ['youtube', 'tiktok', 'instagram', 'facebook', 'x'];
const RANK_NAMES = ['ALPHA', 'BRAVO', 'CHARLIE', 'DELTA', 'ECHO', 'FOXTROT'];

let STYLES = [];
let chosenStyle = 'wordpop';
let currentJob = null;
let pollTimer = null;
let jobFullFetched = false;
let fullJobCache = null;
let cut = { start: 0, end: 15 };
let wfDur = 0;
let WF = [];                       /* measured RMS profile, 0..1 per bucket */
let MOMENTS = [];                  /* engine-mined peak regions */
let HEALTH = null;                 /* /api/health cache: engines[], default_engine, hardware */
let ENGINE = localStorage.getItem('cb.engine') || '';   /* per-job engine choice */
let RIGHTS = [];                   /* rights-gate options, served by /api/health */
let RIGHTS_NOTE = '';              /* the honest Content ID line, same source */
let GATE = { enabled: false, mode: 'advisory' };   /* the clearance gate, same source */
let SOCIAL = {};                   /* /api/social/status cache (connected channel) */
let lastFrac = 0;                  /* playhead position, 0..1, for repaints */
let lastFailToast = 0;
let autoJumped = false;            /* the podium walk happens at most once per job */
let userPicked = false;            /* set when the owner clicks a nav button */

/* ============================ app shell ============================ */

function showScreen(name, fromClick) {
  if (!SCREENS.includes(name)) return;
  if (fromClick) userPicked = true;
  SCREENS.forEach((s) => { const el = $(`screen-${s}`); if (el) el.hidden = s !== name; });
  document.querySelectorAll('.snavbtn').forEach((b) => {
    const on = b.dataset.screen === name;
    b.classList.toggle('active', on);
    b.setAttribute('aria-current', on ? 'page' : 'false');
  });
  $('jobtitle').textContent = TITLES[name] || 'ClipBlitz';
  revealCards(name);
  if (name === 'connect') { refreshSocial(); renderQueue(); loadLearning(); }
  if (name === 'studio') loadRecent();
  if (name === 'scout') loadScout();
}

document.querySelectorAll('.snavbtn').forEach((b) =>
  b.addEventListener('click', () => showScreen(b.dataset.screen, true)));
document.querySelectorAll('[data-goto]').forEach((b) =>
  b.addEventListener('click', () => showScreen(b.dataset.goto, true)));

/* staggered entrance — transform-only, resting state is fully visible */
function revealCards(name) {
  const sec = $(`screen-${name}`);
  if (!sec || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  sec.querySelectorAll(':scope > .glass, :scope > * > .glass').forEach((el, i) => {
    el.classList.remove('rvin');
    el.style.setProperty('--i', Math.min(i, 6));
    void el.offsetWidth;
    el.classList.add('rvin');
  });
}

/* cursor halo — a transform-tracked light, never a layout change */
(function startHalo() {
  const g = $('halo');
  if (!g || matchMedia('(prefers-reduced-motion: reduce)').matches || matchMedia('(hover: none)').matches) return;
  let tx = innerWidth / 2, ty = innerHeight / 2, cx = tx, cy = ty, raf = 0;
  addEventListener('mousemove', (e) => {
    tx = e.clientX; ty = e.clientY;
    if (raf) return;
    raf = requestAnimationFrame(function step() {
      cx += (tx - cx) * 0.07; cy += (ty - cy) * 0.07;
      g.style.transform = `translate3d(${cx.toFixed(1)}px, ${cy.toFixed(1)}px, 0)`;
      raf = (Math.abs(tx - cx) > 0.5 || Math.abs(ty - cy) > 0.5) ? requestAnimationFrame(step) : 0;
    });
  }, { passive: true });
})();

/* ============================ toasts ============================ */
function toast(msg, err = false) {
  const box = $('toasts');
  if (!box) return;
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  box.appendChild(t);
  while (box.children.length > 4) box.firstChild.remove();
  setTimeout(() => t.remove(), 4200);
}

function showError(msg) { $('error').innerHTML = `<div class="error">${esc(msg)}</div>`; }

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', body: body || '{}' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || res.status);
    err.status = res.status;
    err.data = data;                  /* the rights gate is a 409 with its own payload */
    throw err;
  }
  return data;
}

/* ============================ capabilities ============================
   Real values only. If ffmpeg or yt-dlp is missing we say so; if a brain is
   configured we name it. No invented telemetry. */
fetch('/api/health').then(r => r.json()).then(h => {
  const caps = $('caps');
  /* Three measured lines, not one long string. A 224px sidebar cannot hold
     the whole readout on one line and letting it wrap broke mid-token
     ("yt-" / "dlp"). Every value here is real; nothing is invented. */
  caps.className = 'chip eng' + (h.ffmpeg && h.ytdlp ? ' gold' : ' err');
  caps.innerHTML = [
    `<span class="erow">${esc(h.engine || 'ProX v5')}<span class="sep">·</span>top ${esc(String(h.top_n))}</span>`,
    `<span class="erow">brain ${esc((h.brains || ['none']).join(' + '))}</span>`,
    `<span class="erow">ffmpeg ${h.ffmpeg ? IC('check') : IC('x')}` +
      `<span class="sep">·</span>yt-dlp ${h.ytdlp ? IC('check') : IC('x')}</span>`
  ].join('');
  const live = $('livechip');
  live.innerHTML = h.ai_picker
    ? IC('signal') + ' AI ready · v' + esc(h.version || '')
    : IC('warn') + ' offline mode';
  live.className = 'chip' + (h.ai_picker ? ' ok' : ' err');
  HEALTH = h;
  RIGHTS = h.rights || [];
  RIGHTS_NOTE = h.rights_note || '';
  GATE = h.gate || GATE;
  renderRightsOptions();
  initSafety();
  initGate();
  initScout();
  renderRightsGate(fullJobCache);   /* the Content ID line arrives with health, not with the job */
  renderSafety(fullJobCache);
  renderGateCard(fullJobCache);
  initEngine(h);
  applyHardware(h.hardware);
  fillMachineCard(h.hardware);
}).catch(() => {
  $('caps').innerHTML = '<span class="erow">server unreachable</span>';
  $('caps').className = 'chip eng err';
  $('livechip').textContent = 'offline';
  $('livechip').className = 'chip err';
});

/* ============================ caption styles ============================ */
fetch('/api/styles').then(r => r.json()).then(styles => {
  STYLES = styles;
  const grid = $('stylegrid');
  grid.innerHTML = styles.map(s => `
    <div class="stylecard ${s.id === chosenStyle ? 'active' : ''}" data-id="${esc(s.id)}" title="${esc(s.desc)}"
         role="button" tabindex="0">
      <div class="preview" style="background:${esc(s.sample_bg)};color:${esc(s.sample_color)}">Aa</div>
      <div class="sname">${esc(s.name)}</div>
      <div class="sdesc">${esc(s.desc)}</div>
    </div>`).join('');
  grid.querySelectorAll('.stylecard').forEach(card => {
    const pick = () => {
      chosenStyle = card.dataset.id;
      grid.querySelectorAll('.stylecard').forEach(c => c.classList.toggle('active', c.dataset.id === chosenStyle));
      runPreview();
    };
    card.addEventListener('click', pick);
    card.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
  });
  runPreview();
});

/* ============================ studio: input ============================ */
const dz = $('dropzone');
dz.addEventListener('click', () => $('file').click());
dz.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('file').click(); } });
dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('drag'); });
dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
dz.addEventListener('drop', (e) => {
  e.preventDefault(); dz.classList.remove('drag');
  if (e.dataTransfer.files[0]) { $('file').files = e.dataTransfer.files; fileChosen(); }
});
$('file').addEventListener('change', fileChosen);

function fileChosen() {
  const f = $('file').files[0];
  if (!f) return;
  dz.querySelector('.big').textContent = `${f.name} · ${(f.size / 1048576).toFixed(0)} MB`;
  dz.querySelector('.sub').textContent = 'ready — press Edit my video';
  if (f.size > 300 * 1048576) toast('Big video — the engine will chew through it, longer waits though.');
  captureFrame(f);
}

/* ============================ live caption preview ============================
   The frame is captured from the owner's OWN file, so the preview is never a
   mock-up; the caption motion is pure CSS on the child spans. */
const PV_COLORS = { wordpop: '#fff', goldbold: '#FFD700', minimal: '#fff', karaoke: '#FFD700', neon: '#39FF14', box: '#fff' };
const PV_WORDS = ['Your captions', 'look insane', 'in every style'];

function captureFrame(file) {
  const v = document.createElement('video');
  const url = URL.createObjectURL(file);
  v.src = url; v.muted = true;
  v.onloadedmetadata = () => { v.currentTime = Math.min(2.5, Math.max(0.1, (v.duration || 5) / 3)); };
  v.onseeked = () => {
    const c = $('pv-canvas'), ctx = c.getContext('2d');
    const vr = v.videoWidth / v.videoHeight, cr = c.width / c.height;
    let sx, sy, sw, sh;
    if (vr > cr) { sh = v.videoHeight; sw = sh * cr; sx = (v.videoWidth - sw) / 2; sy = 0; }
    else { sw = v.videoWidth; sh = sw / cr; sx = 0; sy = (v.videoHeight - sh) / 2; }
    ctx.drawImage(v, sx, sy, sw, sh, 0, 0, c.width, c.height);
    $('pv-empty').hidden = true;
    URL.revokeObjectURL(url);
  };
  v.onerror = () => URL.revokeObjectURL(url);
}

function runPreview() {
  const cap = $('pv-caption');
  cap.className = 'pv-caption st-' + chosenStyle;
  cap.style.color = PV_COLORS[chosenStyle] || '#fff';
  const pos = $('position').value;
  cap.style.top = pos === 'middle' ? '50%' : (pos === 'top' ? '56px' : 'auto');
  cap.style.bottom = pos === 'bottom' ? '68px' : 'auto';
  cap.style.transform = pos === 'middle' ? 'translate(-50%, -50%)' : 'translateX(-50%)';
  const span = (w, i) => `<span class="w" style="--i:${i}">${esc(w)}</span>`;
  const words = PV_WORDS.join(' ').split(' ');
  cap.innerHTML = `<div class="pv-screen">${words.map(span).join(' ')}</div>`;
  if (chosenStyle === 'karaoke') cap.style.setProperty('--kfill', (words.length * 0.32 + 1.6) + 's');
  $('pv-hint').textContent = `Live preview · ${(STYLES.find(s => s.id === chosenStyle) || {}).name || chosenStyle} captions, ${pos} placement.`;
}

function opts() {
  return `style=${encodeURIComponent(chosenStyle)}&position=${$('position').value}` +
         `&scale=${$('scale').value}&auto_post=${$('autopost').value}&privacy=${$('privacy').value}` +
         `&framing=${$('framing').value}&engine=${encodeURIComponent(ENGINE || 'b2')}`;
}
$('scale').addEventListener('input', () => $('scaleval').textContent = Number($('scale').value).toFixed(2) + '×');
$('position').addEventListener('change', runPreview);

/* ============================ engine choice ============================
   One job, one engine choice: ProX v5, B2 Pro X, or Both (one analysis pass,
   both cuts side by side). Persisted; the notes come from the server's own
   engine list so the copy can never drift from the code. */
function engineById(id) {
  return ((HEALTH && HEALTH.engines) || []).find(e => e.id === id);
}

function setEngine(id, persist) {
  ENGINE = id;
  document.querySelectorAll('#engine-seg .segbtn').forEach(b =>
    b.classList.toggle('active', b.dataset.engine === id));
  const e = engineById(id);
  if (e) $('engine-note').textContent = e.note;
  if (persist) {
    localStorage.setItem('cb.engine', id);
    toast(`engine: ${(e && e.name) || id}`);
  }
}

function initEngine(h) {
  if (!h.engines.some(e => e.id === ENGINE)) ENGINE = h.default_engine || 'b2';
  setEngine(ENGINE, false);
}

document.querySelectorAll('#engine-seg .segbtn').forEach(b =>
  b.addEventListener('click', () => setEngine(b.dataset.engine, true)));

/* ============================ hardware (measured) ============================
   The machine running the studio is capability-checked with real numbers. A
   device that cannot render says so before any job starts — never mid-render.
   A phone used as the controller renders nothing itself, so there is nothing
   to check there; rendering already happens on the machine that runs this. */
function applyHardware(hw) {
  if (!hw) return;
  const box = $('hwbox');
  if (hw.render_capable) { box.hidden = true; return; }
  box.hidden = false;
  $('hw-reason').textContent = hw.reason;
  ['upload', 'demo', 'fetch'].forEach(id => { const b = $(id); if (b) b.disabled = true; });
}

function fillMachineCard(hw) {
  const chip = $('hw-chip'), stats = $('hw-stats');
  if (!chip || !hw) return;
  chip.textContent = hw.render_capable ? 'can render' : "can't render";
  chip.className = 'chip ' + (hw.render_capable ? 'ok' : 'err');
  stats.innerHTML = `
    <span class="chip">${IC('bolt')} ${esc(String(hw.cores))} CPU cores</span>
    <span class="chip">${IC('signal')} ${esc(String(hw.ram_gb || '?'))} GB memory</span>
    <span class="chip">ffmpeg ${hw.ffmpeg ? IC('check') : IC('x')}</span>` +
    (hw.render_capable ? '' : `<span class="chip err">${esc(hw.reason)}</span>`);
}

async function loadLan() {
  try {
    const lan = await (await fetch('/api/lan')).json();
    const urls = lan.urls || [];
    $('lan-urls').textContent = urls.length
      ? urls.join('   ·   ')
      : 'no LAN address found — this machine may be offline';
    const chip = $('lan-chip');
    chip.textContent = urls.length ? `reachable on ${urls.length} address${urls.length === 1 ? '' : 'es'}` : 'offline';
    chip.className = 'chip' + (urls.length ? ' ok' : ' err');
  } catch (e) { /* best effort */ }
}

$('lan-copy').addEventListener('click', () => {
  navigator.clipboard.writeText($('lan-urls').textContent)
    .then(() => toast('phone address copied'))
    .catch(() => toast('copy blocked by the browser — select and copy manually', true));
});

/* a phone waking from sleep syncs immediately instead of waiting out the poll */
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  loadLan();
  if (HEALTH) { applyHardware(HEALTH.hardware); fillMachineCard(HEALTH.hardware); }
  if (currentJob) {
    fetch(`/api/job/${currentJob}?light=1`).then(r => r.json()).then(job => {
      if ((job.clips || []).length) renderClipsSurgical(job);
    }).catch(() => {});
  }
});

/* ============================ studio: run ============================ */
$('upload').addEventListener('click', () => {
  const f = $('file').files[0];
  if (!f) return toast('choose a video file first', true);
  $('error').innerHTML = '';
  $('upload').disabled = true;
  $('job').hidden = false;
  resetRunUI();
  $('jobname').textContent = f.name;
  setStage('uploading 0%');
  $('jobbar').style.width = '0%';

  const xhr = new XMLHttpRequest();
  xhr.open('POST', `/api/upload?name=${encodeURIComponent(f.name)}&${opts()}`);
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const pct = Math.round((e.loaded / e.total) * 100);
      setStage(`uploading ${pct}%`);
      $('jobbar').style.width = pct + '%';
    }
  };
  xhr.onload = () => {
    $('upload').disabled = false;
    try {
      const data = JSON.parse(xhr.responseText);
      if (xhr.status >= 300) throw new Error(data.error || xhr.status);
      watch(data.job_id, f.name);
    } catch (e) { showError(String(e.message || e)); }
  };
  xhr.onerror = () => { $('upload').disabled = false; showError('upload failed — is the server running?'); };
  xhr.send(f);
});

$('demo').addEventListener('click', async () => {
  $('error').innerHTML = '';
  $('demo').disabled = true;
  try {
    const res = await post(`/api/demo?${opts()}`);
    watch(res.job_id, 'demo_source.mp4 (generated test video)');
  } catch (e) { showError(String(e.message || e)); }
  finally { $('demo').disabled = false; }
});

$('fetch').addEventListener('click', async () => {
  const url = $('url').value.trim();
  if (!url) return toast('paste a YouTube or direct video URL first', true);
  $('error').innerHTML = '';
  $('fetch').disabled = true;
  try {
    const res = await post(`/api/from_url?url=${encodeURIComponent(url)}&${opts()}`);
    watch(res.job_id, url.length > 60 ? url.slice(0, 60) + '…' : url);
  } catch (e) { showError(String(e.message || e)); }
  finally { $('fetch').disabled = false; }
});

/* ============================ processing timeline ============================ */
const STEPS = [['ingest', 'Ingest'], ['audio', 'Energy'], ['transcribe', 'Transcribe'],
               ['prox', 'ProX picks'], ['meta', 'Metadata'], ['render', 'Render'], ['post', 'Post']];

function stageIndex(stage) {
  const s = (stage || '').toLowerCase();
  if (s.includes('upload') || s.includes('download') || s.includes('ingest')) return 0;
  if (s.includes('energy') || s.includes('probe') || s.includes('extract') || s.includes('laugh')) return 1;
  if (s.includes('transcri')) return 2;
  if (s.includes('prox') || s.includes('mining') || s.includes('measur') || s.includes('peak')) return 3;
  if (s.includes('title') || s.includes('writing') || s.includes('metadata')) return 4;
  if (s.includes('render') || s.includes('judge') || s.includes('qc')) return 5;
  if (s.includes('post')) return 6;
  if (s.includes('done')) return STEPS.length;
  return 0;
}

function setTimeline(stageStr, status) {
  const tl = $('timeline');
  if (!tl.dataset.built) {
    tl.innerHTML = STEPS.map(([, label]) => `<div class="tstep">${esc(label)}</div>`).join('');
    tl.dataset.built = '1';
  }
  const done = status === 'done';
  const active = done ? STEPS.length : stageIndex(stageStr);
  tl.querySelectorAll('.tstep').forEach((el, i) => {
    el.classList.toggle('done', done || i < active);
    el.classList.toggle('active', !done && i === active);
  });
}

function setStage(text, cls) {
  $('jobstage').textContent = text || '';
  $('jobstage').className = 'stage' + (cls ? ' ' + cls : '');
}

function resetRunUI() {
  $('clips').innerHTML = '';
  $('clips-empty').hidden = false;
  $('labwrap').hidden = true;
  $('labgrid').innerHTML = '';
  $('cutwrap').hidden = true;
  $('cut-empty').hidden = false;
  $('transcript').innerHTML = '';
  $('seg-count').textContent = '—';
  $('skeletons').hidden = false;
  $('jobdone').hidden = true;
  jobFullFetched = false;
  fullJobCache = null;
  autoJumped = false;
  userPicked = false;
  WF = []; MOMENTS = []; wfDur = 0;
}

function watch(jobId, name) {
  currentJob = jobId;
  showScreen('studio');
  $('job').hidden = false;
  $('jobname').textContent = name;
  $('jobtitle').textContent = name.length > 34 ? name.slice(0, 34) + '…' : name;
  resetRunUI();
  setStage('queued');
  setTimeline('upload', null);
  $('jobbar').style.width = '0%';
  clearInterval(pollTimer);
  pollTimer = setInterval(poll, 1500);
  poll();
}

async function poll() {
  if (!currentJob) return;
  let job;
  try {
    const res = await fetch(`/api/job/${currentJob}?light=1`);
    if (res.status === 404) {                 /* server restarted → in-memory job is gone */
      clearInterval(pollTimer);
      setStage('job lost — server restarted', 'err');
      toast('Job no longer in memory (the server restarted). Re-run it.', true);
      return;
    }
    job = await res.json();
  } catch (e) {
    const now = Date.now();
    if (now - lastFailToast > 10000) { lastFailToast = now; toast('server unreachable — retrying…', true); }
    return;                                   /* transient outage: keep polling */
  }

  setStage(job.error ? `failed: ${job.error}` : job.stage,
           job.status === 'done' ? 'done' : job.status === 'error' ? 'err' : null);
  setTimeline(job.stage, job.status);
  $('jobbar').style.width = (job.progress || 0) + '%';

  const chip = $('jobchip');
  chip.hidden = false;
  chip.innerHTML = (job.status === 'done' ? IC('check') : IC('repeat')) +
                   ` ${esc(job.status)} · ${job.progress || 0}%`;
  chip.className = 'chip' + (job.status === 'done' ? ' ok' : job.status === 'error' ? ' err' : '');

  $('skeletons').hidden = !(job.status !== 'done' && !(job.clips || []).length);
  renderClipsSurgical(job);
  renderRightsGate(job);
  renderSafety(job);
  renderGateCard(job);
  if (job.rights_hold && !autoJumped && !userPicked) {
    /* the strict gate has a question and its actions live on the Clips screen:
       walk there once instead of leaving the owner staring at "queued" */
    autoJumped = true;
    showScreen('clips');
  }

  if (job.status === 'done' || job.status === 'error') {
    clearInterval(pollTimer);
    $('skeletons').hidden = true;
    if (!jobFullFetched) { jobFullFetched = true; loadFull(); }
    if (job.status === 'done' && (job.clips || []).length) {
      $('jobdone').hidden = false;
      /* walk the owner to the finished podium ONCE, and never yank them away from
         a screen they chose themselves */
      if (!autoJumped && !userPicked) {
        autoJumped = true;
        showScreen('clips');
      }
    }
  }
}

async function loadFull() {
  if (!currentJob) return;
  try {
    const job = await (await fetch(`/api/job/${currentJob}`)).json();
    fullJobCache = job;
    renderRightsGate(job);
    renderSafety(job);
    renderGateCard(job);
    WF = Array.isArray(job.waveform) ? job.waveform : [];
    MOMENTS = Array.isArray(job.moments) ? job.moments : [];
    wfDur = job.duration || 0;
    buildLab(job);
    buildCutbox(job);
    const has = (job.clips || []).length > 0;
    $('clips-empty').hidden = has;
    $('lab-empty').hidden = has;
    $('cut-empty').hidden = has;
    if (has) { $('labwrap').hidden = false; $('cutwrap').hidden = false; }
    renderQueue();
    loadRecent();
  } catch (e) { /* the transcript panel is optional sugar — never block the podium on it */ }
}

/* ============================ podium ============================ */
function postSig(c) {
  return JSON.stringify(PLATFORMS.map(p => [c.post?.[p]?.status, c.post?.[p]?.link || '', c.post?.[p]?.note || '']));
}

function renderClipsSurgical(job) {
  const clips = job.clips || [];
  const box = $('clips');
  if (job.engine_id !== 'both') {
    box.classList.remove('cmp');
    document.querySelectorAll('#clips .cmprow').forEach(el => el.remove());
    clips.forEach((c, i) => ensureClipCard(job, c, i));
    while (box.children.length > clips.length) box.lastChild.remove();
    return;
  }
  /* both: one comparison row per moment — two cards from ONE analysis pass.
     Titles, judge verdicts and scores are shared; only the cut and grade differ. */
  box.classList.add('cmp');
  const mids = [...new Set(clips.map(c => c.moment || 0))].sort((a, b) => a - b);
  mids.forEach(mid => {
    let row = box.querySelector(`.cmprow[data-moment="${mid}"]`);
    if (row) return;
    row = document.createElement('div');
    row.className = 'cmprow';
    row.dataset.moment = mid;
    const first = clips.find(c => (c.moment || 0) === mid) || {};
    row.innerHTML = `
      <div class="cmphead glass">
        <div class="cmpheadrow">
          <div class="cliptitle">${esc(first.meta?.title || first.title || 'Moment ' + mid)}</div>
          <div class="cmpscore">${qcBadge(first)}<span class="chip gold mono">score ${Math.round(first.score || 0)}</span></div>
        </div>
        <div class="cmpnote">one analysis pass, two cuts — same story, same judge verdict and score; the cut timing and the grade differ</div>
      </div>
      <div class="cmpcards"></div>`;
    box.appendChild(row);
  });
  box.querySelectorAll('.cmprow').forEach(r => {
    if (!mids.includes(Number(r.dataset.moment))) r.remove();
  });
  clips.forEach((c, i) => ensureClipCard(job, c, i));
}

function cardHome(job, c) {
  if (job.engine_id === 'both') {
    const row = document.querySelector(`#clips .cmprow[data-moment="${c.moment || 0}"] .cmpcards`);
    if (row) return row;
  }
  return $('clips');
}

function dialSVG(score) {
  const C = 2 * Math.PI * 26;
  return `<svg class="dial" viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">
    <circle cx="32" cy="32" r="26" class="dial-bg"/>
    <circle cx="32" cy="32" r="26" class="dial-fg" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${C.toFixed(1)}"/>
    <text x="32" y="37" text-anchor="middle" class="dial-num">0</text>
  </svg>`;
}

function miniSVG(score) {
  const C = 2 * Math.PI * 22;
  return `<svg class="mini" viewBox="0 0 52 52" width="52" height="52" aria-hidden="true">
    <circle cx="26" cy="26" r="22" class="mini-bg"/>
    <circle cx="26" cy="26" r="22" class="mini-fg" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${C.toFixed(1)}"/>
    <text x="26" y="31" text-anchor="middle" class="mini-num">${Math.round(score || 0)}</text>
  </svg>`;
}

function factorRows(factors) {
  if (!factors) return '';
  const keys = Object.keys(FACTOR_LABEL).filter(k => factors[k] != null);
  if (factors.laughter != null) keys.push('laughter');
  const label = (k) => k === 'laughter' ? 'Laugh' : FACTOR_LABEL[k];
  return keys.map(k => `
    <div class="frow" title="${esc(label(k))}: ${factors[k]}/100">
      <span>${esc(label(k))}</span>
      <div class="fbar"><i data-w="${Number(factors[k]) || 0}"></i></div>
      <b>${Number(factors[k]) || 0}</b>
    </div>`).join('');
}

function qcBadge(c) {
  if (c.qc === 'verified') return `<span class="qcbadge ok">${IC('check')} verified</span>`;
  if (c.qc) return `<span class="qcbadge warn">${IC('warn')} unverified</span>`;
  return '';
}

/* ============================ rights gate ============================
   Consent plus information, asked once per job, before the first upload leaves this
   machine. It is not a detector and it is not an evasion tool: it records what the
   owner says about their own rights. The clip file is never withheld, so posting it
   by hand stays entirely the owner's call. */
function renderRightsOptions() {
  const box = $('rightsopts');
  if (!box) return;
  box.innerHTML = RIGHTS.map(r =>
    `<button class="optbtn" data-right="${esc(r.id)}" type="button">
       <span class="optname">${esc(r.label)}</span>
       <span class="optnote">${esc(r.note)}</span>
     </button>`).join('');
  box.querySelectorAll('[data-right]').forEach(b =>
    b.addEventListener('click', () => answerRights(b.dataset.right)));
}

function showRightsGate(job, why) {
  const bar = $('rightsbar');
  if (!bar) return;
  const state = why || (job && job.rights_pending
    ? 'Auto-post on this job is paused until you answer.'
    : 'Posting waits for this answer. The clip file is yours either way.');
  $('rightsnote').textContent = RIGHTS_NOTE ? RIGHTS_NOTE + ' ' + state : state;
  if (bar.hidden) {
    bar.hidden = false;
    bar.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderRightsGate(job) {
  const bar = $('rightsbar');
  if (!bar) return;
  const held = !!job && !!job.rights_hold;   /* strict gate: held BEFORE it renders */
  const need = !!job && !job.rights_ok && (held || ((job.clips || []).length > 0));
  if (!need) { bar.hidden = true; return; }
  showRightsGate(job, held
    ? 'Strict clearance gate: nothing renders from this source until you answer.'
    : undefined);
}

async function answerRights(answer) {
  if (!currentJob) return toast('run a job first', true);
  try {
    const res = await post(`/api/job/${currentJob}/rights`, JSON.stringify({ answer }));
    toast(res.autopost_resumed
      ? 'rights confirmed — auto-post is running'
      : 'rights confirmed for this job');
    $('rightsbar').hidden = true;
    if (fullJobCache) fullJobCache.rights_ok = res.rights_ok;
    jobFullFetched = false;
    /* the answer changes the safety report (the rights flag clears), so re-read it
       instead of showing the copy fetched before the answer */
    SAFETY_JOB = null;
    SAFETY = null;
    poll();
  } catch (e) { toast(String(e.message || e), true); }
}

/* ============================ clearance gate ============================
   The honest inverse of "make everything uncopyrighted": in strict mode imported
   media is held BEFORE it renders until you answer the rights question or record a
   written override, and the certificate bundles the risk report, the licence, the
   receipt and the sha256 of every file so a third party can re-check it against the
   files themselves. Nothing here clears anything by itself. */
function gateCleared(job) {
  return !!(job && (job.rights_ok ||
    (job.rights_override && job.rights_override.reason)));
}

function renderGateCard(job) {
  const bar = $('gatebar');
  if (!bar) return;
  if (!GATE.enabled || !currentJob || !job) { bar.hidden = true; return; }
  const chip = $('gatechip');
  chip.textContent = GATE.mode === 'strict' ? 'strict' : 'advisory';
  chip.className = 'chip' + (GATE.mode === 'strict' ? ' gold' : '');
  const cleared = gateCleared(job);
  const over = job.rights_override || null;
  const status = $('gatestatus');
  let words, tone;
  if (job.rights_ok) { words = `cleared - rights: ${job.rights_ok}`; tone = 'low'; }
  else if (over) { words = 'override recorded'; tone = 'review'; }
  else if (job.rights_hold) { words = 'holding this render'; tone = 'high'; }
  else { words = 'waiting for your rights answer'; tone = 'review'; }
  status.textContent = words;
  status.className = 'safelev ' + tone;
  let state;
  if (job.rights_ok) {
    state = GATE.mode === 'strict'
      ? 'This source is cleared: it renders, and publishing proceeds under your answer.'
      : 'Answer recorded. Publishing proceeds; rendering is never held in advisory mode.';
  } else if (over) {
    state = `Proceeding on your written override: “${over.reason}”.`;
  } else if (job.rights_hold) {
    state = 'Strict gate: nothing renders from this source until you answer the rights question above or record an override below.';
  } else {
    state = GATE.mode === 'strict'
      ? 'Strict gate: this source is held before it renders - answer above, or record an override below.'
      : 'Advisory gate: measurements only. Renders are never held; publishing waits for your rights answer.';
  }
  $('gatestate').textContent = state;
  $('gatenote').textContent = 'A strict gate holds imported media before the render and before any publish. The certificate bundles the risk report, the licence, the receipt and the sha256 of every file - it proves what was measured, not that a use is safe.';
  $('ovform').hidden = !(GATE.mode === 'strict' && !cleared);
  bar.hidden = false;
}

async function makeCertificate() {
  if (!currentJob) return toast('run a job first', true);
  try {
    const res = await (await fetch(`/api/job/${currentJob}/certificate`)).json();
    if (!res || res.certificate === undefined) {
      return toast((res && res.error) || 'no certificate', true);
    }
    const c = res.certificate;
    const out = $('certout');
    out.hidden = false;
    out.textContent = `certificate written to ${res.written_to || '(not saved)'} · digest ` +
      `${String((c.digest || {}).value || '').slice(0, 16)}… · re-check with ` +
      `scripts/verify_certificate.py against the files`;
    toast('clearance certificate written');
  } catch (e) { toast(String(e.message || e), true); }
}

function initGate() {
  const form = $('ovform');
  if (!form || form.dataset.built) return;
  form.dataset.built = '1';
  $('certbtn').addEventListener('click', makeCertificate);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentJob) return;
    const reason = $('ovreason').value.trim();
    if (reason.length < 8) {
      return toast('write why you are proceeding (at least 8 characters)', true);
    }
    try {
      const res = await post(`/api/job/${currentJob}/override`, JSON.stringify({ reason }));
      toast(res.render_resumed ? 'override recorded - the render is starting'
                               : 'override recorded for this job');
      $('ovreason').value = '';
      jobFullFetched = false;
      SAFETY_JOB = null; SAFETY = null;
      poll();
    } catch (err) { toast(String(err.message || err), true); }
  });
}

/* =================== copyright safety: risk, licence, receipt ==================
   The measured half of the rights conversation. Every line here comes from
   /api/job/<id>/risk, which reads data this pipeline already produced - a span of
   sustained non-speech audio, where the source came from, whether a licence is on
   file, how many transformative layers each clip carries. It never claims a video is
   uncopyrighted and never promises protection from a claim; that is not a thing any
   tool can do, and the note under the flags says so in as many words. */
let SAFETY_JOB = null;         /* which job the panel is currently describing */
let SAFETY = null;             /* last report for that job */

function renderSafety(job) {
  const bar = $('safetybar');
  if (!bar) return;
  const has = !!currentJob && !!((job && job.clips || []).length);
  if (!has) { bar.hidden = true; SAFETY_JOB = null; SAFETY = null; return; }
  if (SAFETY_JOB === currentJob && SAFETY) { paintSafety(SAFETY); return; }
  SAFETY_JOB = currentJob;                 /* claim it before the fetch: one panel per job */
  fetch(`/api/job/${currentJob}/risk`).then(r => r.json()).then(d => {
    if (SAFETY_JOB !== currentJob) return;  /* a newer job landed while this was in flight */
    SAFETY = d;
    paintSafety(d);
  }).catch(() => {});
}

function paintSafety(d) {
  const bar = $('safetybar');
  if (!bar || !d) return;
  const lev = $('safelev');
  const words = { low: 'no flags', review: 'review', high: 'do not publish' };
  lev.textContent = words[d.level] || d.level;
  lev.className = 'safelev ' + (d.level || 'review');
  $('safetysub').textContent = d.headline || '';
  const flags = d.flags || [];
  $('safeflags').innerHTML = flags.map(f =>
    `<li class="safeflag ${esc(f.kind)}">${IC('warn')}<span>${esc(f.text)}</span></li>`).join('');
  $('safeflags').hidden = !flags.length;
  $('receiptbtn').href = `/api/job/${esc(currentJob)}/receipt`;
  $('safetynote').textContent = [d.note, d.rights_note].filter(Boolean).join(' ');
  fillLicence(d);
  bar.hidden = false;
}

function fillLicence(d) {
  const sel = $('lickind');
  if (!sel) return;
  const kinds = d.licence_kinds || {};
  const current = d.licence || {};
  sel.innerHTML = ['<option value="">not stated</option>'].concat(
    Object.keys(kinds).map(k =>
      `<option value="${esc(k)}"${current.kind === k ? ' selected' : ''}>${esc(k)} — ${esc(kinds[k])}</option>`)
  ).join('');
  $('licholder').value = current.holder || '';
  $('licref').value = current.reference || '';
  $('licexp').value = current.expires || '';
  $('licbtn').textContent = current.kind || current.holder
    ? 'Licence on file — edit it' : 'Add licence details';
}

function initSafety() {
  const form = $('licform');
  if (!form || form.dataset.built) return;
  form.dataset.built = '1';
  $('licbtn').addEventListener('click', () => {
    form.hidden = !form.hidden;
    if (!form.hidden) $('licholder').focus();
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentJob) return;
    const body = {
      kind: $('lickind').value,
      holder: $('licholder').value.trim(),
      reference: $('licref').value.trim(),
      expires: $('licexp').value.trim(),
    };
    try {
      const res = await post(`/api/job/${currentJob}/licence`, JSON.stringify(body));
      SAFETY = res.risk;
      paintSafety(res.risk);
      form.hidden = true;
      toast('licence recorded for this job');
    } catch (err) { toast(String(err.message || err), true); }
  });
}

/* ---- source awareness + the transformative-edit badge ---------------------- */
function sourceLine(job) {
  const s = (job && job.source) || {};
  if (s.kind !== 'youtube') return '';
  const who = s.uploader || s.channel || 'unknown channel';
  const connected = SOCIAL.channel || '';
  const mine = connected && who.toLowerCase().includes(String(connected).toLowerCase());
  const flag = !mine;
  return `<div class="srcline${flag ? ' warn' : ''}">
    ${IC(flag ? 'warn' : 'check')}
    <span>source: <b>${esc(who)}</b>${s.video_id ? ` · video ${esc(s.video_id)}` : ''}</span>
    ${flag ? `<span class="srcflag">${connected
        ? `not your connected channel (${esc(connected)}) — make sure you have the rights`
        : 'no channel connected to compare against — make sure you have the rights'}</span>` : ''}
  </div>`;
}

function xLine(c) {
  const layers = c.transformative || [];
  if (!layers.length) return '';
  return `<div class="xline">
    <span class="xbadge">transformative edit</span>
    <span class="xnote">what this render changed: ${esc(layers.join(' · '))}</span>
  </div>`;
}

function clipCardHTML(job, c, i) {
  const styleOpts = STYLES.map(s =>
    `<option value="${esc(s.id)}" ${s.id === (c.style || job.style) ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
  const rank = String(c.rank || i + 1).padStart(2, '0');
  const rankName = RANK_NAMES[i] || `RANK ${rank}`;
  return `
    <span class="rank"><span class="rnum">#${rank}</span><span class="rname">${esc(rankName)}</span></span>
    <video controls preload="metadata" src="${esc(c.file)}" playsinline></video>
    <div class="cliphead">
      ${dialSVG(c.score)}
      <div class="cliptop">
        <div class="cliptitle">${esc(c.meta?.title || c.title || 'Clip')}</div>
        ${c.hook ? `<div class="hook">“${esc(c.hook)}”</div>` : ''}
        ${c.topic ? `<span class="topicchip">${esc(c.topic)}</span>` : ''}
        ${qcBadge(c)}
      </div>
    </div>
    <div class="factors">${factorRows(c.factors)}</div>
    ${c.verdict ? `<div class="judge">${IC('scales')} “${esc(c.verdict)}”</div>` : ''}
    ${c.reason ? `<div class="reason">${IC('bulb')} ${esc(c.reason)}</div>` : ''}
    <div class="clipmeta">
      ${c.engine ? `<span class="engbadge">${esc(c.engine)}</span>` : ''}
      <span>${c.duration}s · from ${fmt(c.start)}${c.custom ? ' · custom cut' : ''}</span>
      ${c.note ? `<span class="dim">${esc(c.note)}</span>` : ''}
    </div>
    ${sourceLine(job)}
    ${xLine(c)}
    <div class="metabox">
      <div class="metahead">Title</div>
      <input type="text" data-f="t-${i}" value="${esc(c.meta?.title || '')}" spellcheck="false" />
      <div class="metahead">Description</div>
      <textarea data-f="d-${i}">${esc(c.meta?.description || '')}</textarea>
      <div class="metahead">Hashtags</div>
      <input type="text" data-f="h-${i}" value="${esc((c.meta?.hashtags || []).join(' '))}" spellcheck="false" />
      <div class="row">
        <button class="btn ghost small" data-save="${i}" type="button">${IC('save')} Save metadata</button>
        <select class="restyle" data-restyle="${i}" title="re-render this clip in another caption style">${styleOpts}</select>
        <span class="saved" data-saved="${i}"></span>
      </div>
    </div>
    <div class="postrow" data-postrow="${i}">${postChips(c, i)}</div>`;
}

function ensureClipCard(job, c, i) {
  let el = document.querySelector(`#clips .clipcard[data-clip="${i}"]`);
  if (!el) {
    el = document.createElement('article');
    el.className = 'glass clipcard rvin';
    el.dataset.clip = i;
    el.style.setProperty('--i', Math.min(i, 6));
    el.innerHTML = clipCardHTML(job, c, i);
    cardHome(job, c).appendChild(el);
    bindClipCard(el, job.id);
    animateDial(el, c.score || 0);
    animateBars(el);
    return;
  }
  /* existing card: patch ONLY the post chips, so playback / typed metadata / the
     score animation are never disturbed by a poll */
  const row = el.querySelector('[data-postrow]');
  if (row && row.dataset.sig !== postSig(c)) {
    const hadErr = !!row.querySelector('.postchip.err');
    row.innerHTML = postChips(c, i);
    row.dataset.sig = postSig(c);
    bindPost(row, job.id);
    const errChip = row.querySelector('.postchip.err');
    if (!hadErr && errChip) toast(errChip.textContent.trim(), true);
  }
}

function animateDial(el, score) {
  const fg = el.querySelector('.dial-fg'), num = el.querySelector('.dial-num');
  if (!fg) return;
  const C = 2 * Math.PI * 26;
  const target = (C * (1 - (score || 0) / 100)).toFixed(1);
  requestAnimationFrame(() => { fg.style.strokeDashoffset = target; });
  const t0 = performance.now(), dur = 1100;
  let done = false;
  const finish = () => { if (!done) { done = true; num.textContent = score; fg.style.strokeDashoffset = target; } };
  const tick = (t) => {
    const k = Math.min(1, (t - t0) / dur);
    num.textContent = Math.round((score || 0) * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(tick); else done = true;
  };
  requestAnimationFrame(tick);
  setTimeout(finish, 1400);   /* rAF is throttled in a backgrounded tab — the real value must still land */
}

function animateBars(el) {
  const bars = el.querySelectorAll('.fbar i');
  setTimeout(() => bars.forEach(b => { b.style.width = (Number(b.dataset.w) || 0) + '%'; }), 120);
}

function postChips(clip, i) {
  return PLATFORMS.map(p => {
    const st = clip.post?.[p];
    const name = esc(PLATFORM_LABEL[p]);
    let cls = '', inner = `Post → ${name}`;
    if (st?.status === 'uploading') { cls = 'busy'; inner = `${name} uploading…`; }
    else if (st?.status === 'published') { cls = 'done'; inner = `${IC('check')} ${name} published`; }
    else if (st?.status === 'assisted_ready') { cls = 'done'; inner = `${IC('list')} ${name} ready — caption copied`; }
    else if (st?.status === 'error') { cls = 'err'; inner = `${IC('warn')} ${name}: ${esc(st.note || 'failed')}`; }
    if (st?.link) inner = `<a href="${esc(st.link)}" target="_blank" rel="noopener">${inner}</a>`;
    const attrs = st ? '' : ` data-post="${p}" data-clip="${i}" role="button" tabindex="0"`;
    return `<span class="postchip ${cls}"${attrs}>${inner}</span>`;
  }).join('');
}

function bindClipCard(el, jobId) {
  el.querySelectorAll('[data-save]').forEach(b =>
    b.addEventListener('click', () => saveMeta(jobId, b.dataset.save)));
  el.querySelectorAll('[data-post]').forEach(b =>
    b.addEventListener('click', () => sendPost(jobId, b.dataset.post, b.dataset.clip)));
  el.querySelectorAll('[data-restyle]').forEach(sel => sel.addEventListener('change', async () => {
    const i = Number(sel.dataset.restyle);
    const c = (fullJobCache?.clips || [])[i];
    if (!c) return toast('that clip is no longer in this job', true);
    sel.disabled = true;
    try {
      /* the same window, re-cut with different captions — /api/custom is exactly that */
      await post('/api/custom', JSON.stringify({ job_id: jobId, start: c.start, end: c.end, style: sel.value }));
      toast(`re-cutting in ${sel.options[sel.selectedIndex].text} captions…`);
      jobFullFetched = false;
      clearInterval(pollTimer);
      pollTimer = setInterval(poll, 1500);
      poll();
    } catch (e) { toast(String(e.message || e), true); }
    finally { sel.disabled = false; }
  }));
  bindPost(el, jobId);
}

function bindPost(row, jobId) {
  row.querySelectorAll('[data-post]').forEach(b => {
    b.addEventListener('click', () => sendPost(jobId, b.dataset.post, b.dataset.clip));
    b.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sendPost(jobId, b.dataset.post, b.dataset.clip); }
    });
  });
}

async function saveMeta(jobId, i) {
  const val = (f) => (document.querySelector(`[data-f="${f}"]`) || {}).value || '';
  const body = {
    title: val(`t-${i}`),
    description: val(`d-${i}`),
    hashtags: val(`h-${i}`).split(/\s+/).filter(Boolean),
  };
  const out = document.querySelector(`[data-saved="${i}"]`);
  try {
    const res = await fetch(`/api/job/${jobId}/meta/${i}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (out) out.textContent = res.ok ? 'saved' : 'save failed';
    toast(res.ok ? 'metadata saved' : 'save failed', !res.ok);
  } catch (e) { toast('save failed — ' + String(e.message || e), true); }
  setTimeout(() => { if (out) out.textContent = ''; }, 2500);
}

async function sendPost(jobId, platform, clipIndex) {
  try {
    await post('/api/post', JSON.stringify({ job_id: jobId, index: Number(clipIndex || 0), platforms: [platform] }));
    toast(`queued for ${PLATFORM_LABEL[platform]} — watch the chip go live`);
    jobFullFetched = false;
    clearInterval(pollTimer);
    pollTimer = setInterval(poll, 1500);
    poll();
  } catch (e) {
    if (e.data && e.data.rights_required) {
      if (Array.isArray(e.data.rights) && e.data.rights.length) {
        RIGHTS = e.data.rights;
        RIGHTS_NOTE = e.data.note || RIGHTS_NOTE;
        renderRightsOptions();
      }
      if (e.data.gate && e.data.gate.mode) {
        GATE = { enabled: !!e.data.gate.enabled, mode: e.data.gate.mode };
      }
      renderGateCard(fullJobCache);
      showRightsGate(fullJobCache, e.data.gate && e.data.gate.mode === 'strict'
        ? 'Strict gate: ' + (e.data.error || 'posting waits for an answer or a written override.')
        : 'Posting waits for this answer.');
      return;
    }
    toast(String(e.message || e), true);
  }
}

/* ============================ candidates ============================ */
const factorsLevel = (v) => (v ?? 0) >= 75 ? 'hi' : (v ?? 0) >= 45 ? 'mid' : 'lo';
let labFilter = 'all';

function candidateRows() {
  return ((fullJobCache?.candidates) || []).map((c, idx) => ({ c, idx })).filter(r => !r.c.selected);
}

function buildLab(job) {
  const cands = candidateRows();
  if (!cands.length) { $('labwrap').hidden = true; $('lab-empty').hidden = false; return; }
  $('lab-empty').hidden = true;
  $('labwrap').hidden = false;
  $('labgrid').innerHTML = cands.map(({ c, idx }) => {
    const f = c.factors || {};
    const mini = Object.keys(FACTOR_LABEL).filter(k => f[k] != null)
      .map(k => `<span class="lm ${factorsLevel(f[k])}">${esc(FACTOR_LABEL[k][0])}${Number(f[k])}</span>`).join('');
    const ev = c.measured?.event ?? 0;
    const peak = ev > 0 ? `<span class="lm hi" title="contains a measured peak event">${IC('signal')} peak</span>` : '';
    return `
      <div class="labcards glass rvin" data-verified="${c.qc === 'verified' ? '1' : '0'}" data-peak="${ev > 0 ? '1' : '0'}">
        <div class="labtop">
          ${miniSVG(c.score)}
          <div>
            <div class="labtitle">${esc(c.title || 'Candidate')}</div>
            <div class="labsub">${fmt(c.start)} → ${fmt(c.end)} · ${Math.round((c.end || 0) - (c.start || 0))}s${c.qc === 'verified' ? ' · verified' : ''}</div>
          </div>
        </div>
        <div class="labmini">${mini}${peak}</div>
        <button class="btn ghost small" data-render="${idx}" type="button">${IC('bolt')} Render this clip</button>
      </div>`;
  }).join('');
  applyLabFilter();
  $('labgrid').querySelectorAll('[data-render]').forEach(b => b.addEventListener('click', async () => {
    const idx = Number(b.dataset.render);
    b.disabled = true;
    b.innerHTML = `${IC('repeat')} rendering…`;
    try {
      await post('/api/render', JSON.stringify({ job_id: currentJob, cand_index: idx, style: chosenStyle }));
      toast('rendering that runner-up — it lands in the podium');
      jobFullFetched = false;
      clearInterval(pollTimer);
      pollTimer = setInterval(poll, 1500);
      poll();
    } catch (e) {
      b.disabled = false;
      b.innerHTML = `${IC('bolt')} Render this clip`;
      toast(String(e.message || e), true);
    }
  }));
}

function applyLabFilter() {
  const cards = $('labgrid').querySelectorAll('.labcards');
  let shown = 0;
  cards.forEach(el => {
    const ok = labFilter === 'all'
      || (labFilter === 'verified' && el.dataset.verified === '1')
      || (labFilter === 'peak' && el.dataset.peak === '1');
    el.hidden = !ok;
    if (ok) shown++;
  });
  $('labnone').hidden = shown > 0 || !cards.length;
}

$('labfilters').addEventListener('click', (e) => {
  const b = e.target.closest('.fbtn');
  if (!b) return;
  labFilter = b.dataset.filter;
  $('labfilters').querySelectorAll('.fbtn').forEach(x => x.classList.toggle('active', x === b));
  applyLabFilter();
});

/* ============================ transcript + timeline ============================ */

/* the waveform: real measured RMS of the source audio, drawn once per width and
   repainted on the playhead. No invented bars. */
function drawWave(progress) {
  const cv = $('wf-canvas');
  if (!cv) return;
  const box = cv.parentElement;
  const w = Math.max(160, box.clientWidth), h = Math.max(40, box.clientHeight);
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  }
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!WF.length) return;
  const bw = 2, gap = 2, step = bw + gap;
  const n = Math.max(1, Math.floor(w / step));
  const mid = h / 2;
  const cutX = progress == null ? -1 : progress * w;
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * WF.length / n);
    const b = Math.max(a + 1, Math.floor((i + 1) * WF.length / n));
    let v = 0;
    for (let j = a; j < b && j < WF.length; j++) v = Math.max(v, WF[j]);
    const bh = Math.max(2, v * (h - 4));
    const x = i * step;
    ctx.fillStyle = x < cutX ? '#ffffff' : 'rgba(255,255,255,.15)';
    ctx.fillRect(x, mid - bh / 2, bw, bh);
  }
}

function buildRuler(dur) {
  const r = $('wf-ruler');
  const target = dur / 10;
  const step = [5, 10, 15, 30, 60, 120, 300, 600, 900].find(s => s >= target) || 900;
  let html = '';
  for (let t = 0; t <= dur; t += step) {
    const pct = (t / dur) * 100;
    html += `<i class="tick" style="left:${pct.toFixed(3)}%"></i>`;
    html += `<span class="tlabel" style="left:${pct.toFixed(3)}%">${fmt(t)}</span>`;
  }
  r.innerHTML = html;
}

function buildMarks(job) {
  const layer = $('wf-marks');
  const dur = wfDur || 1;
  const parts = [];
  (job.candidates || []).forEach(c => {
    parts.push(`<span class="mark cand" style="left:${(c.start / dur * 100).toFixed(3)}%;width:${Math.max(0.5, (c.end - c.start) / dur * 100).toFixed(3)}%"></span>`);
  });
  MOMENTS.forEach(m => {
    parts.push(`<span class="mark peak" title="peak event · roar ${m.roar ?? '—'} · ${m.cuts ?? 0} camera cuts" style="left:${(m.start / dur * 100).toFixed(3)}%;width:${Math.max(0.4, (m.end - m.start) / dur * 100).toFixed(3)}%"></span>`);
  });
  (job.clips || []).forEach(c => {
    parts.push(`<span class="mark sel" style="left:${(c.start / dur * 100).toFixed(3)}%;width:${Math.max(0.6, (c.end - c.start) / dur * 100).toFixed(3)}%"></span>`);
  });
  layer.innerHTML = parts.join('');
}

function setCut(a, b) {
  const dur = wfDur;
  if (!dur) return;
  cut.start = Math.max(0, Math.min(a, b - 3));
  cut.end = Math.min(dur, Math.max(b, cut.start + 3));
  $('cutwin').style.left = (cut.start / dur * 100) + '%';
  $('cutwin').style.width = ((cut.end - cut.start) / dur * 100) + '%';
  $('cutrange').textContent = `${fmt(cut.start)} → ${fmt(cut.end)} · ${(cut.end - cut.start).toFixed(1)}s`;
}

function buildCutbox(job) {
  const segs = job.segments || [];
  if (!segs.length || !job.src_name) {
    $('cutwrap').hidden = true;
    $('cut-empty').hidden = false;
    return;
  }
  $('cut-empty').hidden = true;
  $('cutwrap').hidden = false;

  const src = `/media/${job.src_name}`;
  if ($('srcvid').getAttribute('src') !== src) $('srcvid').src = src;

  $('seg-count').textContent = `${segs.length} blocks · ${MOMENTS.length} peak events`;
  $('wf-dur').textContent = wfDur ? fmt(wfDur) : '';

  const tr = $('transcript');
  tr.innerHTML = segs.filter(s => s.text).map(s => {
    const isPeak = MOMENTS.some(m => s.start < m.end && s.end > m.start);
    return `<span class="seg${isPeak ? ' peak' : ''}" data-t="${s.start}" role="button" tabindex="0" title="${isPeak ? 'inside a measured peak event' : 'click to jump'}"><i>${fmt(s.start)}</i>${esc(s.text)}</span> `;
  }).join('');
  tr.querySelectorAll('.seg').forEach(el => {
    const jump = () => { $('srcvid').currentTime = Number(el.dataset.t); $('srcvid').play().catch(() => {}); };
    el.addEventListener('click', jump);
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); jump(); } });
  });

  buildRuler(wfDur || 1);
  buildMarks(job);
  lastFrac = 0;
  $('wf-head').style.left = '0%';
  drawWave(0);
  setCut(Math.max(0, wfDur * 0.1), Math.min(wfDur, wfDur * 0.1 + 20));
  bindTimeline();
}

function bindTimeline() {
  const wf = $('wf');
  if (wf.dataset.bound) return;      /* binds once; wfDur/cut are read live */
  wf.dataset.bound = '1';
  const vid = $('srcvid');

  const at = (clientX) => {
    const r = $('wf-body').getBoundingClientRect();
    return Math.max(0, Math.min(wfDur, (clientX - r.left) / r.width * wfDur));
  };

  const dragHandle = (el, which) => {
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const t = at(ev.clientX);
        setCut(which === 'l' ? t : cut.start, which === 'r' ? t : cut.end);
      };
      const up = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
    });
  };
  dragHandle($('hl'), 'l');
  dragHandle($('hr'), 'r');

  /* click the ruler = seek · drag the body = move the window · click the body = place it */
  $('wf-ruler').addEventListener('pointerdown', (e) => {
    if (!wfDur) return;
    const t = at(e.clientX);
    vid.currentTime = t;
    drawWave(t / wfDur);
    $('wf-head').style.left = (t / wfDur * 100) + '%';
  });

  $('wf-body').addEventListener('pointerdown', (e) => {
    if (!wfDur || e.target.closest('.h')) return;
    e.preventDefault();
    const len = cut.end - cut.start;
    const t0 = at(e.clientX);
    let moved = false;
    const move = (ev) => {
      moved = true;
      const t = at(ev.clientX);
      const a = Math.max(0, Math.min(wfDur - len, t - (t0 - cut.start)));
      setCut(a, a + len);
    };
    const up = () => {
      if (!moved) { const a = Math.max(0, Math.min(wfDur - len, t0 - len / 2)); setCut(a, a + len); }
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  /* the playhead follows the real player */
  const sync = () => {
    const d = vid.duration || wfDur;
    if (!d) return;
    lastFrac = vid.currentTime / d;
    $('wf-head').style.left = (lastFrac * 100) + '%';
    drawWave(lastFrac);
  };
  vid.addEventListener('timeupdate', sync);
  vid.addEventListener('seeked', sync);
  addEventListener('resize', () => { drawWave(lastFrac); if (wfDur) buildRuler(wfDur); });
}

$('cutgo').addEventListener('click', async () => {
  if (!currentJob) return toast('run a video first', true);
  if (!wfDur) return toast('no timeline for this job', true);
  $('cutgo').disabled = true;
  try {
    await post('/api/custom', JSON.stringify({ job_id: currentJob, start: cut.start, end: cut.end, style: chosenStyle }));
    toast('cutting that window — it lands in the podium when it renders');
    jobFullFetched = false;
    clearInterval(pollTimer);
    pollTimer = setInterval(poll, 1500);
    poll();
  } catch (e) { toast(String(e.message || e), true); }
  finally { $('cutgo').disabled = false; }
});

/* .SRT export — built from the real transcript inside the chosen window, timed
   relative to the cut, exactly like the burned-in captions. */
$('srt').addEventListener('click', () => {
  const segs = ((fullJobCache?.segments) || []).filter(s => s.text && s.end > cut.start && s.start < cut.end);
  if (!segs.length) return toast('nothing in that window to export', true);
  const stamp = (x) => {
    const ms = Math.max(0, Math.round(x * 1000));
    return `${String(Math.floor(ms / 3600000)).padStart(2, '0')}:${String(Math.floor(ms / 60000) % 60).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')},${String(ms % 1000).padStart(3, '0')}`;
  };
  const body = segs.map((s, i) =>
    `${i + 1}\n${stamp(s.start - cut.start)} --> ${stamp(Math.min(s.end, cut.end) - cut.start)}\n${s.text.trim()}\n`).join('\n');
  const url = URL.createObjectURL(new Blob([body], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a');
  const safe = String(fullJobCache?.name || 'clipblitz').replace(/[^\w.-]+/g, '_').slice(0, 40);
  a.href = url;
  a.download = `${safe}_${Math.round(cut.start)}-${Math.round(cut.end)}.srt`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  toast(`exported ${segs.length} subtitle lines`);
});

/* ============================ scout ============================
   Metadata-only discovery plus the judgment queue. Nothing is downloaded until Make,
   judgments are the owner's alone, and both kinds of call (proposal makes/passes and
   clip head-to-heads) are real training evidence: the proposals train the scout's own
   local ranker, the clip pair trains the taste model every choice uses. */
let SCOUT = null;
const SCOUT_FEATURE = { velocity: 'velocity', reach: 'reach', freshness: 'fresh',
  duration_fit: 'length fit', title_signal: 'title pull', channel_fit: 'channel fit' };

function scoutDuration(sec) {
  if (!sec) return '—';
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return `${m}m${String(s).padStart(2, '0')}s`;
}

function scoutAge(p) {
  if (!p || !p.published) return 'age not reported';
  const d = Math.max(0, Math.round((Date.now() / 1000 - p.published) / 86400));
  return `${d}d ago`;
}

async function loadScout() {
  try {
    const data = await (await fetch('/api/scout')).json();
    SCOUT = data;
    renderScout(data);
    loadBench();
  } catch (e) { toast('scout unavailable — retrying…', true); }
}

function renderScout(d) {
  if (!d) return;
  const chip = $('scoutstate');
  if (!d.enabled) {
    chip.textContent = 'off'; chip.className = 'chip err';
    $('scoutstatus').textContent = 'the scout is off (CB_SCOUT=off or CB_LAB=0)';
    $('scoutlist').innerHTML = '';
    $('pairlist').innerHTML = '';
    $('scouttrend').textContent = 'off';
    $('scoutcount').textContent = '—';
    $('paircount').textContent = '—';
    $('scoutmodel').textContent = 'off';
    $('scoutmodel').className = 'chip err';
    $('scoutmodelnote').textContent = '';
    return;
  }
  chip.textContent = d.query ? `last search: ${d.query}` : 'ready';
  chip.className = 'chip';
  renderScoutTrend(d.trend);
  renderScoutModel(d.model || {});
  const rows = d.proposals || [];
  $('scoutcount').textContent = `${rows.length} proposal${rows.length === 1 ? '' : 's'}`;
  $('scoutlist').innerHTML = rows.map(proposalRow).join('') ||
    '<div class="note">No proposals yet — search a niche above. Nothing is downloaded until you press Make.</div>';
  $('scoutlist').querySelectorAll('[data-make],[data-pass]').forEach(b =>
    b.addEventListener('click', () => b.dataset.make
      ? makeProposal(b.dataset.make) : judgeProposal(b.dataset.pass, 'pass')));
  const pairs = d.pairs || [];
  const judged = (d.judged && d.judged.total) || 0;
  $('paircount').textContent = `${pairs.length} pair${pairs.length === 1 ? '' : 's'} · ${judged} proposal call(s)`;
  $('pairlist').innerHTML = pairs.map(pairCard).join('') ||
    '<div class="note">No clip pairs waiting. Run a Both-engines job and its two cuts of the same moment land here for a head-to-head call.</div>';
  $('pairlist').querySelectorAll('[data-judge]').forEach(b =>
    b.addEventListener('click', () => {
      const [job, mine, other] = b.dataset.judge.split('|');
      judgePair(job, Number(mine), Number(other));
    }));
}

function proposalRow(p) {
  const feat = p.features || {};
  const chips = Object.keys(SCOUT_FEATURE).map(k =>
    (feat[k] === null || feat[k] === undefined)
      ? `<span class="fchip off" title="the source did not report this">${esc(SCOUT_FEATURE[k])} —</span>`
      : `<span class="fchip">${esc(SCOUT_FEATURE[k])} ${Math.round(feat[k])}</span>`).join('');
  const verdict = p.verdict
    ? `<span class="chip ${p.verdict === 'make' ? 'ok' : ''}">${esc(p.verdict)}</span>` : '';
  const adjust = p.model_adjust
    ? `<span class="chip">your model ${p.model_adjust > 0 ? '+' : ''}${p.model_adjust}</span>` : '';
  const views = (p.views === null || p.views === undefined)
    ? 'views not reported' : `${Number(p.views).toLocaleString()} views`;
  return `<div class="scoutrow">
    <div class="scouttop">
      <div class="scouttitle">${esc(p.title || p.id)}</div>
      <span class="chip gold">${p.score === null || p.score === undefined ? 'unscored' : p.score}</span>${adjust}${verdict}
    </div>
    <div class="scoutmeta">${esc(p.channel || 'channel not reported')} · ${scoutDuration(p.duration)} · ${views} · ${scoutAge(p)}</div>
    <div class="fchips">${chips}</div>
    <ul class="scoutwhy">${(p.reasons || []).map(r => `<li>${esc(r)}</li>`).join('')}</ul>
    <div class="scoutbtns">
      <button class="btn small" data-make="${esc(p.id)}" type="button">Make this</button>
      <button class="btn ghost small" data-pass="${esc(p.id)}" type="button">Pass</button>
    </div>
  </div>`;
}

function renderScoutTrend(t) {
  const box = $('scouttrend');
  if (!t) { box.className = 'scouttrend dim'; box.textContent = 'no search yet'; return; }
  box.className = 'scouttrend';
  const row = (k, v) => `<div class="trendrow"><span>${esc(k)}</span><b>${v}</b></div>`;
  box.innerHTML = [
    row('results seen', t.results),
    row('median views', (t.median_views === null || t.median_views === undefined)
      ? '—' : Number(t.median_views).toLocaleString()),
    row('median length', scoutDuration(t.median_duration)),
    row('published in 30d', `${Math.round((t.fresh_share || 0) * 100)}%`),
    row('repeating channels', t.repeat_channels && t.repeat_channels.length
      ? t.repeat_channels.map(esc).join(', ') : '—'),
    row('words in titles', t.top_words && t.top_words.length
      ? t.top_words.map(esc).join(', ') : '—'),
    `<div class="safetynote">${esc(t.note || '')}</div>`,
  ].join('');
}

function renderScoutModel(m) {
  const chip = $('scoutmodel');
  if (!m.enabled) {
    chip.textContent = 'off'; chip.className = 'chip err';
    $('scoutmodelnote').textContent = '';
    return;
  }
  chip.textContent = m.active ? `active v${m.version}` : 'warming';
  chip.className = 'chip' + (m.active ? ' ok' : '');
  const last = (m.fits || [])[(m.fits || []).length - 1];
  $('scoutmodelnote').innerHTML = [
    `${m.judgments} call(s) judged · ` + (m.active
      ? `make-beats-pass ${m.holdout} on ${m.holdout_n} held-out pair(s)`
      : `${m.remaining} more ${esc(String(m.waiting_for))} before its first fit`),
    last ? `last attempt: ${esc(last.day)} — ${esc(last.reason || '')}` : '',
    esc(m.note || ''),
  ].filter(Boolean).map(t => `<div class="dim">${t}</div>`).join('');
}

/* --------- clipbench ---------
   One board for every ranking claim this studio makes: the shipped baselines, the taste
   model, the scout model and a fixed one-shot weight set that never learns, all scored
   on the same chronologically held-out pairs. A tie is not a win, so a constant scorer
   is 0.00 and a coin flip is reported as 0.50. Reading the board scores nothing;
   "Run the board" is the one button here, and it writes one line to the log. */
let BENCH = null;

async function loadBench() {
  try {
    const data = await (await fetch('/api/clipbench')).json();
    BENCH = data;
    renderBench(data);
  } catch (e) { /* the scout panel already reports the whole layer being down */ }
}

function benchPct(row) {
  if (!row || row.accuracy === null || row.accuracy === undefined) return '—';
  return row.accuracy.toFixed(2);
}

function benchFamily(name, fam) {
  const rows = Object.keys(fam.contenders || {}).map(k => {
    const c = fam.contenders[k];
    const mark = k === fam.challenger ? ' <span class="dim">model</span>'
      : (k === fam.baseline ? ' <span class="dim">baseline</span>' : '');
    return `<tr><td>${esc(k)}${mark}</td><td>${benchPct(c.holdout)}</td>`
      + `<td class="dim">${benchPct(c.train)}</td></tr>`;
  }).join('');
  return `<div class="benchfam">
    <div class="benchtitle">${esc(name)}
      <span class="dim">${fam.pairs} pair(s) · ${fam.holdout_pairs} held out</span></div>
    <div class="benchverdict${fam.status === 'scored' ? '' : ' dim'}">${esc(fam.verdict || '')}</div>
    <table class="benchtable"><thead><tr><th>contender</th><th>held-out</th><th>train</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <div class="dim">chance ${(fam.chance === undefined ? 0.5 : fam.chance).toFixed(2)}</div>
  </div>`;
}

function renderBench(d) {
  const chip = $('benchchip'), body = $('benchbody'), note = $('benchnote'), when = $('benchwhen');
  if (!chip) return;
  if (!d || !d.enabled) {
    chip.textContent = 'off';
    chip.className = 'chip err';
    body.innerHTML = '';
    note.textContent = 'the scoreboard is off (CB_CLIPBENCH=off or CB_LAB=0)';
    if (when) when.textContent = '';
    return;
  }
  const b = d.board;
  chip.textContent = b ? `v${b.version}` : 'not run';
  chip.className = 'chip' + (b ? ' ok' : '');
  if (when) when.textContent = b ? `${b.day} · run ${d.runs} time(s)` : (d.next || '');
  body.innerHTML = b
    ? ['taste', 'scout'].filter(k => b.families[k])
        .map(k => benchFamily(k, b.families[k])).join('')
    : '<div class="note">No board yet — press Run the board. It scores whatever this install already has and writes one line to the log.</div>';
  note.textContent = (b && b.note) || d.note || '';
}

function pairCard(pp) {
  const side = (s) => `<div class="pairvideo">
    <video controls preload="metadata" src="${esc(s.file || '')}" playsinline></video>
    <div class="dim">${esc(s.engine_name || s.engine || 'cut')} · score ${s.score === null || s.score === undefined ? '—' : s.score} · ${scoutDuration(s.duration)}</div>
  </div>`;
  const a = esc(pp.a.engine_name || 'A'), b = esc(pp.b.engine_name || 'B');
  return `<div class="paircard">
    <div class="pairtop"><b>${esc(pp.job_name || pp.job)}</b><span class="dim">moment ${esc(String(pp.moment))}</span></div>
    <div class="pairvideos">${side(pp.a)}${side(pp.b)}</div>
    <div class="scoutbtns">
      <button class="btn small" data-judge="${esc(pp.job)}|${pp.a.index}|${pp.b.index}" type="button">Keep ${a}, dismiss ${b}</button>
      <button class="btn ghost small" data-judge="${esc(pp.job)}|${pp.b.index}|${pp.a.index}" type="button">Keep ${b}, dismiss ${a}</button>
    </div>
    <div class="dim">${esc(pp.why || '')}</div>
  </div>`;
}

async function judgePair(jobId, mine, other) {
  try {
    const res = await post('/api/judge', JSON.stringify({ job_id: jobId, mine, other }));
    const events = (res.model && res.model.events) || 0;
    toast(`call logged — the taste model now has ${events} real choice(s)`);
    loadScout();
  } catch (e) { toast(String(e.message || e), true); }
}

async function judgeProposal(id, verdict) {
  try {
    const res = await post('/api/scout/judge', JSON.stringify({ proposal: id, verdict }));
    toast(res.fit && res.fit.activated
      ? 'judgment logged — the scout model just activated'
      : 'judgment logged for the scout');
    loadScout();
  } catch (e) { toast(String(e.message || e), true); }
}

async function makeProposal(id) {
  const p = ((SCOUT && SCOUT.proposals) || []).find(r => r.id === id) || {};
  try {
    const res = await post('/api/scout/make', JSON.stringify({ proposal: id }));
    toast(res.gate_mode === 'strict'
      ? 'importing — strict gate: it is held until you answer the rights question'
      : 'importing it now — watch the Studio screen', false);
    jobFullFetched = false;
    watch(res.job_id, p.title || id);
    loadScout();
  } catch (e) { toast(String(e.message || e), true); }
}

function initScout() {
  const benchBtn = $('benchrun');
  if (benchBtn && !benchBtn.dataset.built) {
    benchBtn.dataset.built = '1';
    benchBtn.addEventListener('click', async () => {
      benchBtn.disabled = true;
      try {
        const res = await post('/api/clipbench', JSON.stringify({}));
        const first = ((res.families && res.families.taste) || {}).verdict;
        toast(first || 'board written');
        await loadBench();
      } catch (e) { toast(String(e.message || e), true); }
      finally { benchBtn.disabled = false; }
    });
  }
  const form = $('scoutform');
  if (!form || form.dataset.built) return;
  form.dataset.built = '1';
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = $('scoutq').value.trim();
    if (!q) return toast('type a niche first', true);
    $('scoutstatus').textContent = 'searching — metadata only, nothing downloads…';
    try {
      const res = await post('/api/scout/search', JSON.stringify({
        query: q, limit: Number($('scoutlimit').value) || 10,
      }));
      $('scoutstatus').textContent = `${res.found} result(s) via ${res.method} · ${res.added} new`;
      loadScout();
    } catch (err) {
      $('scoutstatus').textContent = String(err.message || err);
      toast('the search failed — the note above says why', true);
    }
  });
}

/* ============================ connect ============================ */
async function refreshSocial() {
  try {
    const [s, health, diag] = await Promise.all([
      (await fetch('/api/social/status')).json(),
      (await fetch('/api/health')).json(),
      (await fetch('/api/social/youtube/diagnose')).json(),
    ]);
    const yt = s.youtube || {};
    SOCIAL = yt;                       /* the connected channel, for the source check */
    renderRightsGate(fullJobCache);
    const configured = yt.configured && !!health.youtube_ready;
    $('yt-redirect').textContent = `${location.origin}/oauth/youtube/callback`;
    renderDiag(diag);
    const status = $('yt-status');
    if (yt.connected) {
      status.textContent = yt.channel ? `connected · ${yt.channel}` : 'connected';
      status.className = 'chip ok';
      $('yt-detail').innerHTML = `<span class="chip ok">${IC('check')} OAuth token verified — auto-upload active</span>`;
    } else if (configured) {
      status.textContent = 'not connected';
      status.className = 'chip';
      $('yt-detail').innerHTML = `<span class="chip">${IC('key')} keys loaded — press Connect and finish the Google consent</span>`;
    } else {
      status.innerHTML = IC('warn') + ' OAuth not set up yet';
      status.className = 'chip err';
      $('yt-detail').innerHTML = `<span class="chip err">CB_YT_CLIENT_ID / SECRET are empty — do the four steps above, then paste them in the API keys card</span>`;
    }
    $('tt-detail').innerHTML = `<span class="chip">${IC('check')} assisted — the caption package is copied to your clipboard when a render finishes</span>`;
  } catch (e) { /* status is best-effort; never block the screen */ }
}

function renderDiag(diag) {
  const box = $('yt-diag');
  if (!diag || !diag.steps) { box.hidden = true; return; }
  box.hidden = false;
  const rows = Object.entries(diag.steps).map(([name, s]) => `
    <div class="diagrow">
      <span class="diagdot ${s.ok ? 'ok' : 'bad'}">${s.ok ? IC('check') : IC('x')}</span>
      <div><b>${esc(name.replace(/_/g, ' '))}</b> — ${esc(s.detail)}${s.fix ? `<div class="dim">fix: ${esc(s.fix)}</div>` : ''}</div>
    </div>`).join('');
  const known = (diag.known_errors || []).map(k => `
    <div class="diagrow">
      <span class="diagdot bad">${IC('warn')}</span>
      <div><b>${esc(k.error)}</b> — ${esc(k.cause)}<div class="dim">fix: ${esc(k.fix)}</div></div>
    </div>`).join('');
  box.innerHTML = `<div class="diaghead">Auto-post chain — live check</div>${rows}
    ${known ? `<div class="diaghead" style="margin-top:12px">If Google blocked you with one of these</div>${known}` : ''}
    <div class="diagrow"><span class="diagdot ${diag.ready ? 'ok' : 'bad'}">${IC('arrow')}</span>
      <div><b>next:</b> ${esc(diag.next_action || '—')}</div></div>`;
}

$('yt-diagnose').addEventListener('click', async () => {
  try { renderDiag(await (await fetch('/api/social/youtube/diagnose')).json()); toast('re-ran the auto-post check'); }
  catch (e) { toast(String(e.message || e), true); }
});

$('yt-copy').addEventListener('click', () => {
  const txt = $('yt-redirect').textContent;
  (navigator.clipboard?.writeText(txt) || Promise.reject())
    .then(() => toast('redirect URI copied'))
    .catch(() => toast('copy failed — select the text and copy it manually', true));
});
$('yt-gcloud').addEventListener('click', () => window.open('https://console.cloud.google.com/projectcreate', '_blank'));
$('yt-gapi').addEventListener('click', () => window.open('https://console.cloud.google.com/apis/library/youtube.googleapis.com', '_blank'));
$('yt-gcreds').addEventListener('click', () => window.open('https://console.cloud.google.com/apis/credentials/oauthclient', '_blank'));
$('yt-gredirect').addEventListener('click', () => window.open('https://console.cloud.google.com/apis/credentials/consent', '_blank'));
$('tt-test').addEventListener('click', () => window.open('https://www.tiktok.com/upload', '_blank'));
$('ig-test').addEventListener('click', () => window.open('https://www.instagram.com/', '_blank'));

$('learn-reset').addEventListener('click', async () => {
  try {
    renderLearning(await post('/api/learning/reset', '{}'));
    toast('learning reset — the ranking is back on the base weights');
  } catch (e) { toast(String(e.message || e), true); }
});

$('learn-train').addEventListener('click', async () => {
  try {
    const res = await post('/api/train', '{}');
    renderLearning(await (await fetch('/api/learning')).json());
    toast(res.activated
      ? `model v${res.version} activated — kept-beats-sibling ${res.holdout} on real choices`
      : (res.attempted ? `fit done — ${res.reason}` : res.reason));
  } catch (e) { toast(String(e.message || e), true); }
});

/* ============================ learning loop ============================
   Every number on this card is a count, a share or a median of the owner's own
   logged choices. Nothing is estimated, and below 10 choices nothing at all is
   nudged — the ranking is byte-for-byte the base weights. */
async function loadLearning() {
  try { renderLearning(await (await fetch('/api/learning')).json()); }
  catch (e) { /* best effort — never block the screen */ }
}

function renderLearning(L) {
  const chip = $('learn-chip');
  if (!chip || !L) return;
  const stats = $('learn-stats'), note = $('learn-note');
  const model = L.model && L.model.enabled ? L.model : null;
  const trainBtn = $('learn-train');
  if (trainBtn) trainBtn.hidden = !model;
  const n = L.events || 0;
  const min = L.min_events || 10;
  chip.textContent = L.active ? `${n} choices logged` : `${n} of ${min} choices`;
  chip.className = 'chip' + (L.active ? ' ok' : '');
  const kept = Object.entries(L.engines || {}).map(([k, v]) => `${k} ${v}`).join(' · ');
  stats.innerHTML = [
    `<span class="chip">${IC('check')} laugh endings ${L.laugh_ending.count}/${n}</span>`,
    `<span class="chip">${IC('bulb')} question hooks ${L.question_hook.count}/${n}</span>`,
    `<span class="chip">${IC('clock')} median ${L.median_length}s</span>`,
    kept ? `<span class="chip">${IC('film')} kept: ${esc(kept)}</span>` : '',
    model ? `<span class="chip">${IC('bolt')} model ${model.active ? 'v' + model.version : 'warming'}</span>` : '',
  ].join('');
  const bar = $('learn-bar');
  bar.hidden = !n;
  if (n) $('learn-fill').style.width = Math.min(100, Math.round((n / min) * 100)) + '%';
  const moves = Object.entries(L.weights || {})
    .map(([k, v]) => `${k} ${v > 1 ? '+' : ''}${Math.round((v - 1) * 100)}%`);
  const modelLine = !model ? ''
    : (model.active
      ? ` Model v${model.version}: kept-beats-sibling ${model.holdout} on ${model.holdout_n} held-out choices; refits every ${model.refit_every} new ones.`
      : (model.remaining
        ? ` Model: ${model.remaining} more choice${model.remaining === 1 ? '' : 's'} before the next fit.`
        : ' Model: a fit is due on the next logged choice.'));
  note.textContent = (!n
    ? 'No choices logged yet — post, re-render or hand-cut a clip and this fills in from the real decisions.'
    : (L.active
      ? `Active: ranking nudged toward ${moves.length ? moves.join(', ') : 'no single feature yet'} — capped at 10% per factor.`
      : `${L.remaining} more logged choice${L.remaining === 1 ? '' : 's'} before the weights start moving. The ranking is untouched until then.`)) + modelLine;
}

function renderQueue() {
  const rows = [];
  (fullJobCache?.clips || []).forEach((c, i) => {
    Object.entries(c.post || {}).forEach(([p, st]) => {
      rows.push(`<div class="qrow"><b>#${String(i + 1).padStart(2, '0')}</b> → ${esc(PLATFORM_LABEL[p] || p)} · ${esc(st.status)}${st.link ? ` · <a href="${esc(st.link)}" target="_blank" rel="noopener">open</a>` : ''}${st.note ? ` · <span class="dim">${esc(st.note)}</span>` : ''}</div>`);
    });
  });
  const total = (fullJobCache?.clips || []).length;
  $('queue-count').textContent = `${total} clip${total === 1 ? '' : 's'} in this run`;
  $('queue').innerHTML = rows.length ? rows.join('')
    : 'Nothing queued yet — clips you send to a platform appear here with live status.';
}

$('yt-connect').addEventListener('click', async () => {
  /* open the popup INSIDE the click gesture — a window opened after an await is blocked */
  const win = window.open('', '_blank');
  try {
    const { url } = await post('/api/social/youtube/start');
    if (!url) throw new Error('keys missing — see the checklist below');
    if (win) { win.opener = null; win.location = url; }
    else { location.href = url; toast('popup blocked — navigating this tab to Google…', true); }
  } catch (e) {
    if (win) win.close();
    toast(String(e.message || e), true);
  }
});
$('yt-disconnect').addEventListener('click', async () => {
  try { await post('/api/social/youtube/disconnect'); toast('YouTube disconnected'); refreshSocial(); }
  catch (e) { toast(String(e.message || e), true); }
});

/* ---------- API keys ---------- */
function keyState(id, v) {
  const el = $(id);
  if (!el) return;
  el.textContent = v.set ? (v.masked || 'saved') : 'empty';
  el.className = 'keystate' + (v.set ? ' ok' : '');
}

async function loadKeyStates() {
  try {
    const st = await (await fetch('/api/keys')).json();
    keyState('state-groq', st.groq || {});
    keyState('state-gemini', st.gemini || {});
    const ytOk = (st.yt_client_id || {}).set && (st.yt_client_secret || {}).set;
    const yel = $('state-youtube');
    if (yel) { yel.textContent = ytOk ? 'saved' : 'empty'; yel.className = 'keystate' + (ytOk ? ' ok' : ''); }
    if ((st.yt_client_id || {}).masked) $('key-yt-id').placeholder = st.yt_client_id.masked;
    const chip = $('keys-chip');
    if (chip) {
      const brains = st.brains || [];
      chip.textContent = brains.length ? brains.join(' + ') + ' online' : 'paste a key to start';
      chip.className = 'chip' + (brains.length ? ' ok' : '');
    }
  } catch (e) { /* best effort */ }
}

document.querySelectorAll('[data-savekey]').forEach((b) => b.addEventListener('click', async () => {
  const which = b.dataset.savekey;
  const body = {};
  if (which === 'groq') body.groq = $('key-groq').value.trim();
  if (which === 'gemini') body.gemini = $('key-gemini').value.trim();
  if (which === 'youtube') {
    body.yt_client_id = $('key-yt-id').value.trim();
    body.yt_client_secret = $('key-yt-secret').value.trim();
  }
  if (Object.values(body).some((v) => !v)) return toast('Paste the value first.', true);
  b.disabled = true;
  const old = b.textContent;
  b.textContent = 'Testing…';
  try {
    const resp = await fetch('/api/keys', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const r = await resp.json();
    if (!resp.ok) throw new Error(r.error || resp.statusText);
    const tests = r.tests || {};
    const fails = Object.entries(tests).filter(([, t]) => !t.ok).map(([k, t]) => `${k}: ${t.detail || 'failed'}`);
    if (fails.length) toast('Saved, but check — ' + fails.join(' · '), true);
    else {
      const ok = Object.values(tests).map((t) => t.detail).filter(Boolean);
      toast('Saved and tested live' + (ok.length ? ' — ' + ok.join(' · ') : '.'));
    }
    loadKeyStates();
    refreshSocial();
  } catch (e) { toast('Could not save: ' + String(e.message || e), true); }
  b.disabled = false;
  b.textContent = old;
}));

/* ============================ recent jobs ============================ */
async function loadRecent() {
  try {
    const jobs = await (await fetch('/api/jobs')).json();
    const box = $('recent');
    $('recent-count').textContent = `${jobs.length} job${jobs.length === 1 ? '' : 's'}`;
    if (!jobs.length) {
      box.innerHTML = '<div class="note">No runs yet — drop a video above, or press Demo video for a generated end-to-end test.</div>';
      return;
    }
    box.innerHTML = jobs.map(j => `
      <button class="recentrow" data-job="${esc(j.id)}" type="button">
        <span class="rname">${esc(j.name || j.id)}</span>
        <span class="rmeta">${esc(j.status)} · ${j.clips} clip${j.clips === 1 ? '' : 's'}${j.engine ? ' · ' + esc(j.engine === 'both' ? 'both engines' : j.engine === 'prox' ? 'ProX v5' : 'B2 Pro X') : ''}${j.top_score ? ' · best ' + j.top_score : ''}</span>
      </button>`).join('');
    box.querySelectorAll('[data-job]').forEach(b => b.addEventListener('click', () => {
      fetch(`/api/job/${b.dataset.job}?light=1`).then(r => r.json()).then(job => {
        watch(job.id, job.name || job.id);
        if ((job.clips || []).length || job.rights_hold) showScreen('clips', true);
      }).catch(() => toast('that job is gone', true));
    }));
  } catch (e) { /* best effort */ }
}

/* ============================ deep links ============================ */
const params = new URLSearchParams(location.search);
const wantedJob = params.get('job');
const wantedScreen = params.get('screen');

if (wantedJob) {
  fetch(`/api/job/${wantedJob}?light=1`)
    .then((r) => { if (!r.ok) throw new Error('unknown job'); return r.json(); })
    .then((job) => {
      watch(job.id, job.name || job.id);
      autoJumped = true;                 /* an explicit deep link is already the destination */
      if ((job.clips || []).length) showScreen(wantedScreen || 'clips', true);
    })
    .catch(() => toast('that job no longer exists — run a new one', true));
} else {
  loadRecent();
  if (wantedScreen && SCREENS.includes(wantedScreen)) {
    setTimeout(() => showScreen(wantedScreen, true), 40);
  }
}
loadKeyStates();
loadLan();
loadLearning();
