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

const SCREENS = ['studio', 'clips', 'lab', 'transcript', 'connect'];
const TITLES = { studio: 'Studio', clips: 'Clips', lab: 'Candidates', transcript: 'Transcript', connect: 'Connect' };
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
  if (name === 'connect') { refreshSocial(); renderQueue(); }
  if (name === 'studio') loadRecent();
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
  if (!res.ok) throw new Error(data.error || res.status);
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
         `&framing=${$('framing').value}`;
}
$('scale').addEventListener('input', () => $('scaleval').textContent = Number($('scale').value).toFixed(2) + '×');
$('position').addEventListener('change', runPreview);

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
  clips.forEach((c, i) => ensureClipCard(job, c, i));
  const box = $('clips');
  while (box.children.length > clips.length) box.lastChild.remove();
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
      <span>${c.duration}s · from ${fmt(c.start)}${c.custom ? ' · custom cut' : ''}</span>
      ${c.note ? `<span class="dim">${esc(c.note)}</span>` : ''}
    </div>
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
    $('clips').appendChild(el);
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
  } catch (e) { toast(String(e.message || e), true); }
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

/* ============================ connect ============================ */
async function refreshSocial() {
  try {
    const [s, health, diag] = await Promise.all([
      (await fetch('/api/social/status')).json(),
      (await fetch('/api/health')).json(),
      (await fetch('/api/social/youtube/diagnose')).json(),
    ]);
    const yt = s.youtube || {};
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
        <span class="rmeta">${esc(j.status)} · ${j.clips} clip${j.clips === 1 ? '' : 's'}${j.top_score ? ' · best ' + j.top_score : ''}</span>
      </button>`).join('');
    box.querySelectorAll('[data-job]').forEach(b => b.addEventListener('click', () => {
      fetch(`/api/job/${b.dataset.job}?light=1`).then(r => r.json()).then(job => {
        watch(job.id, job.name || job.id);
        if ((job.clips || []).length) showScreen('clips', true);
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
