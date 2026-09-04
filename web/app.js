/* ClipBlitz v3 front-end — Studio (upload/styles/ProX podium/Candidate Lab/custom cuts)
   + Connect tab. Rendering is surgical: clips animate in once and are then only
   patched (post chips), so video playback, typed metadata and animations survive polls. */
const $ = (id) => document.getElementById(id);
let STYLES = [];
let chosenStyle = 'wordpop';
let currentJob = null;
let pollTimer = null;
let jobFullFetched = false;
let cut = { start: 0, end: 15 };
let lastFailToast = 0;

const esc = (s) => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };

/* ---------- app-shell views ---------- */
const SCREENS = ['studio', 'clips', 'lab', 'transcript', 'connect'];
function showScreen(name) {
  SCREENS.forEach((s) => { $(`screen-${s}`).hidden = s !== name; });
  document.querySelectorAll('.snavbtn').forEach((b) =>
    b.classList.toggle('active', b.dataset.screen === name));
  const titles = { studio: 'Studio', clips: 'Clips', lab: 'Candidates', transcript: 'Transcript', connect: 'Connect' };
  $('jobtitle').textContent = titles[name] || 'ClipBlitz';
  if (name === 'connect') { refreshSocial(); renderQueue(); }
}
document.querySelectorAll('.snavbtn').forEach((b) =>
  b.addEventListener('click', () => showScreen(b.dataset.screen)));
document.querySelectorAll('[data-goto]').forEach((b) =>
  b.addEventListener('click', () => showScreen(b.dataset.goto)));

/* ---------- toasts ---------- */
function toast(msg, err = false) {
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  $('toasts').appendChild(t);
  setTimeout(() => t.classList.add('in'), 10);
  setTimeout(() => { t.classList.remove('in'); setTimeout(() => t.remove(), 400); }, 4200);
}

/* ---------- capabilities (honest connection status) ---------- */
fetch('/api/health').then(r => r.json()).then(h => {
  const caps = [`ProX v5 editor`, `top ${h.top_n}`, `brain: ${(h.brains || ['none']).join('+')}`,
                `ffmpeg ${h.ffmpeg ? '✓' : '✗'}`, `yt-dlp ${h.ytdlp ? '✓' : '✗'}`];
  $('caps').textContent = caps.join('  ·  ');
  $('caps').className = 'chip' + (h.ffmpeg && h.ytdlp ? ' gold' : ' err');
  $('livechip').textContent = h.ai_picker ? 'AI ready' : 'offline mode';
  $('livechip').className = 'chip ' + (h.ai_picker ? 'gold' : 'err');
}).catch(() => { $('caps').textContent = 'server unreachable'; $('caps').className = 'chip err'; });

/* ---------- caption styles ---------- */
fetch('/api/styles').then(r => r.json()).then(styles => {
  STYLES = styles;
  const grid = $('stylegrid');
  grid.innerHTML = styles.map(s => `
    <div class="stylecard ${s.id === chosenStyle ? 'active' : ''}" data-id="${s.id}" title="${esc(s.desc)}">
      <div class="preview" style="background:${s.sample_bg};color:${s.sample_color}">Aa</div>
      <div class="sname">${esc(s.name)}</div>
      <div class="sdesc">${esc(s.desc)}</div>
    </div>`).join('');
  grid.querySelectorAll('.stylecard').forEach(card =>
    card.addEventListener('click', () => {
      chosenStyle = card.dataset.id;
      grid.querySelectorAll('.stylecard').forEach(c => c.classList.toggle('active', c.dataset.id === chosenStyle));
      runPreview();
    }));
  runPreview();
});

/* ---------- upload ---------- */
const dz = $('dropzone');
dz.addEventListener('click', () => $('file').click());
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
  dz.querySelector('.big').textContent = `📼 ${f.name} (${(f.size / 1048576).toFixed(0)} MB)`;
  if (f.size > 300 * 1048576) toast('Big video — ProX will chew through it, longer waits though.', false);
  captureFrame(f);
}

/* ---------- LIVE CAPTION PREVIEW ---------- */
const PV_COLORS = { wordpop: '#fff', goldbold: '#FFD700', minimal: '#fff', karaoke: '#FFD700', neon: '#39FF14', box: '#fff' };
const PV_WORDS = ['Your captions', 'look insane', 'in every style 🔥'];
let pvTimer = null;

function captureFrame(file) {
  const v = document.createElement('video');
  v.src = URL.createObjectURL(file);
  v.muted = true;
  v.onloadedmetadata = () => { v.currentTime = Math.min(2.5, v.duration / 3); };
  v.onseeked = () => {
    const c = $('pv-canvas'), ctx = c.getContext('2d');
    const vr = v.videoWidth / v.videoHeight, cr = c.width / c.height;
    let sx, sy, sw, sh;
    if (vr > cr) { sh = v.videoHeight; sw = sh * cr; sx = (v.videoWidth - sw) / 2; sy = 0; }
    else { sw = v.videoWidth; sh = sw / cr; sx = 0; sy = (v.videoHeight - sh) / 2; }
    ctx.drawImage(v, sx, sy, sw, sh, 0, 0, c.width, c.height);
    $('pv-empty').style.display = 'none';
    URL.revokeObjectURL(v.src);
  };
}

function runPreview() {
  clearInterval(pvTimer);
  const cap = $('pv-caption');
  cap.className = 'pv-caption st-' + chosenStyle;
  cap.style.color = PV_COLORS[chosenStyle] || '#fff';

  if (chosenStyle === 'karaoke') {
    const words = PV_WORDS.join(' ').split(' ');
    cap.innerHTML = words.map(w => `<span class="w">${esc(w)}</span>`).join(' ');
    let idx = 0;
    const spans = cap.querySelectorAll('.w');
    pvTimer = setInterval(() => {
      spans.forEach(s => s.classList.remove('spoken'));
      for (let k = 0; k <= idx % spans.length; k++) spans[k].classList.add('spoken');
      idx++;
    }, 380);
    return;
  }
  const perScreen = 2;
  const screens = [];
  for (let i = 0; i < PV_WORDS.length; i += perScreen) screens.push(PV_WORDS.slice(i, i + perScreen).join(' '));
  let s = 0;
  const show = () => {
    cap.innerHTML = screens[s % screens.length].split(' ').map(w => `<span class="w">${esc(w)}</span>`).join(' ');
    s++;
  };
  show();
  pvTimer = setInterval(show, 1300);
}

function opts() {
  return `style=${encodeURIComponent(chosenStyle)}&position=${$('position').value}` +
         `&scale=${$('scale').value}&auto_post=${$('autopost').value}&privacy=${$('privacy').value}` +
         `&framing=${$('framing').value}`;
}
$('scale').addEventListener('input', () => $('scaleval').textContent = Number($('scale').value).toFixed(2) + '×');

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.status);
  return data;
}

$('upload').addEventListener('click', () => {
  const f = $('file').files[0];
  if (!f) return toast('choose a video file first', true);
  $('error').innerHTML = '';
  $('upload').disabled = true;
  $('job').hidden = false;
  resetClipsUI();
  $('jobname').textContent = f.name;
  setStage('uploading 0%', null);
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
  try {
    const res = await post(`/api/demo?${opts()}`, '{}');
    watch(res.job_id, 'demo_source.mp4 (test video)');
  } catch (e) { showError(String(e.message || e)); }
});

$('fetch').addEventListener('click', async () => {
  const url = $('url').value.trim();
  if (!url) return toast('paste a YouTube or direct video URL first', true);
  $('error').innerHTML = '';
  try {
    const res = await post(`/api/from_url?url=${encodeURIComponent(url)}&${opts()}`, '{}');
    watch(res.job_id, url.length > 60 ? url.slice(0, 60) + '…' : url);
  } catch (e) { showError(String(e.message || e)); }
});

function showError(msg) { $('error').innerHTML = `<div class="error">${esc(msg)}</div>`; }

/* ---------- processing timeline ---------- */
const STEPS = [['ingest', 'Ingest'], ['audio', 'Energy'], ['transcribe', 'Transcribe'], ['prox', 'ProX picks'], ['meta', 'Metadata'], ['render', 'Render'], ['post', 'Post']];
function stageIndex(stage) {
  const s = (stage || '').toLowerCase();
  if (s.includes('upload') || s.includes('download') || s.includes('ingest')) return 0;
  if (s.includes('energy') || s.includes('probe') || s.includes('extract')) return 1;
  if (s.includes('transcri')) return 2;
  if (s.includes('prox') || s.includes('mining') || s.includes('measur')) return 3;
  if (s.includes('title') || s.includes('writing') || s.includes('metadata')) return 4;
  if (s.includes('render')) return 5;
  if (s.includes('post')) return 6;
  if (s.includes('done')) return STEPS.length;
  return 0;
}
function setTimeline(stageStr, status) {
  const tl = $('timeline');
  if (!tl.dataset.built) {
    tl.innerHTML = STEPS.map(([, label]) => `<div class="tstep">${label}</div>`).join('');
    tl.dataset.built = '1';
  }
  const done = status === 'done';
  const active = done ? STEPS.length : stageIndex(stageStr);
  tl.querySelectorAll('.tstep').forEach((el, i) => {
    el.classList.toggle('done', done || i < active);
    el.classList.toggle('active', !done && i === active);
  });
}

function resetClipsUI() {
  $('clips').innerHTML = '';
  $('clips-empty').hidden = true;
  $('labwrap').hidden = true;
  $('labgrid').innerHTML = '';
  $('cutwrap').hidden = true;
  $('transcript').innerHTML = '';
  $('skeletons').hidden = false;
  $('jobdone').hidden = true;
  jobFullFetched = false;
  firstClipReveal = true;
}

let firstClipReveal = true;

function watch(jobId, name) {
  currentJob = jobId;
  showScreen('studio');
  $('job').hidden = false;
  $('jobname').textContent = name;
  $('jobtitle').textContent = name.length > 34 ? name.slice(0, 34) + '…' : name;
  resetClipsUI();
  setStage('queued', null);
  setTimeline('upload', null);
  $('jobbar').style.width = '0%';
  clearInterval(pollTimer);
  pollTimer = setInterval(poll, 1500);
  poll();
}

function setStage(text, cls) {
  $('jobstage').textContent = text;
  $('jobstage').className = 'stage' + (cls ? ' ' + cls : '');
}

async function poll() {
  if (!currentJob) return;
  let job;
  try {
    const res = await fetch(`/api/job/${currentJob}?light=1`);
    if (res.status === 404) {  // server restarted & lost the in-memory job → stop cleanly
      clearInterval(pollTimer);
      setStage('job lost — server restarted', 'err');
      toast('Job no longer in memory (server restarted). Re-run the job.', true);
      return;
    }
    job = await res.json();
  } catch (e) {
    const now = Date.now();
    if (now - lastFailToast > 10000) { lastFailToast = now; toast('server unreachable — retrying…', true); }
    return;  // keep polling; transient outage
  }
  setStage(job.error ? `failed: ${job.error}` : job.stage,
           job.status === 'done' ? 'done' : job.status === 'error' ? 'err' : null);
  setTimeline(job.stage, job.status);
  $('jobbar').style.width = (job.progress || 0) + '%';
  $('jobchip').hidden = false;
  $('jobchip').textContent = `${job.status === 'done' ? '✓' : '⏳'} ${job.status} · ${job.progress || 0}%`;
  $('skeletons').hidden = !(job.status !== 'done' && !(job.clips || []).length);
  renderClipsSurgical(job);
  if (job.status === 'done' || job.status === 'error') {
    clearInterval(pollTimer);
    $('skeletons').hidden = true;
    if (!jobFullFetched) { jobFullFetched = true; loadFull(job); }
    if (job.status === 'done' && (job.clips || []).length) {
      $('jobdone').hidden = false;
      if (document.getElementById('screen-clips').hidden && job.clips.some(c => c._fresh)) {
        showScreen('clips');  // auto-navigate once clips exist
      }
    }
  }
}

async function loadFull(jobLight) {
  try {
    const job = await (await fetch(`/api/job/${currentJob}`)).json();
    fullJobCache = job;
    buildLab(job);
    buildCutbox(job);
    if ((job.clips || []).length) { $('clips-empty').hidden = true; $('lab-empty').hidden = true; $('cut-empty').hidden = true; $('labwrap').hidden = false; $('cutwrap').hidden = false; }
    renderQueue();
    if (firstClipReveal && (job.clips || []).length) {
      firstClipReveal = false;
      showScreen('clips');  // walk the user to the finished podium exactly once
    }
  } catch (e) { /* transcript panel is optional sugar */ }
}

/* ---------- surgical clip rendering ---------- */
const FACTOR_LABEL = { hook: 'Hook', story: 'Story', payoff: 'Payoff', energy: 'Energy', pacing: 'Pacing', event: 'Event' };
const PLATFORM_LABEL = { youtube: '▶️ YouTube', tiktok: '🎵 TikTok', instagram: '📸 Instagram', facebook: '👤 Facebook', x: '𝕏 Post' };
const PLATFORMS = ['youtube', 'tiktok', 'instagram', 'facebook', 'x'];

function postSig(c) {
  return JSON.stringify(PLATFORMS.map(p => c.post?.[p]?.status + (c.post?.[p]?.link || '') + (c.post?.[p]?.note || '')));
}

function renderClipsSurgical(job) {
  const clips = job.clips || [];
  clips.forEach((c, i) => { c._fresh = true; ensureClipCard(job, c, i); });
  const total = $('clips').children.length;
  while (total > clips.length) $('clips').lastChild.remove();
}

function dialSVG(score) {
  const C = 2 * Math.PI * 26;
  return `<svg class="dial" viewBox="0 0 64 64" width="64" height="64">
    <circle cx="32" cy="32" r="26" class="dial-bg"/>
    <circle cx="32" cy="32" r="26" class="dial-fg" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${C.toFixed(1)}" data-target="${score}"/>
    <text x="32" y="37" text-anchor="middle" class="dial-num" data-count="${score}">0</text>
  </svg>`;
}

function clipCardHTML(job, c, i) {
  const factors = c.factors || {};
  const bars = Object.keys(FACTOR_LABEL).map(k => `
    <div class="frow" title="${FACTOR_LABEL[k]}: ${factors[k] ?? 0}/100">
      <span>${FACTOR_LABEL[k]}</span>
      <div class="fbar"><i data-w="${factors[k] ?? 0}"></i></div>
      <b>${factors[k] ?? 0}</b>
    </div>`).join('');
  const laughBar = factors.laughter != null ? `
    <div class="frow" title="Measured audience laughter coverage">
      <span>Laugh</span>
      <div class="fbar"><i data-w="${factors.laughter}"></i></div>
      <b>${factors.laughter}</b>
    </div>` : '';
  const styleOpts = STYLES.map(s => `<option value="${s.id}" ${s.id === (c.style || job.style) ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
  const qc = c.qc === 'verified'
    ? '<span class="qcbadge ok" title="Passed the standalone-story judge">✓ verified</span>'
    : (c.qc ? '<span class="qcbadge warn" title="Did not fully pass the judge — rendered as best available">◐ unverified</span>' : '');
  return `
    <span class="rank">0${c.rank || i + 1}</span>
    <video controls preload="metadata" src="${c.file}"></video>
    <div class="cliphead">
      ${dialSVG(c.score)}
      <div class="cliptop">
        <div class="cliptitle">${esc(c.meta?.title || c.title)}</div>
        ${c.hook ? `<div class="hook">“${esc(c.hook)}”</div>` : ''}
        ${c.topic ? `<span class="topicchip">${esc(c.topic)}</span>` : ''}
        ${qc}
      </div>
    </div>
    <div class="factors">${bars}${laughBar}</div>
    ${c.verdict ? `<div class="judge">⚖️ “${esc(c.verdict)}”</div>` : ''}
    <div class="reason">💡 ${esc(c.reason)}</div>
    <div class="clipmeta">
      <span>${c.duration}s · from ${c.start}s${c.custom ? ' · custom cut' : ''}</span>
      ${c.note ? `<span class="dim">${esc(c.note)}</span>` : ''}
    </div>
    <div class="metabox">
      <div class="metahead">Title</div>
      <input type="text" id="t-${i}" value="${esc(c.meta?.title || '')}" />
      <div class="metahead">Description</div>
      <textarea id="d-${i}">${esc(c.meta?.description || '')}</textarea>
      <div class="metahead">Hashtags</div>
      <input type="text" id="h-${i}" value="${esc((c.meta?.hashtags || []).join(' '))}" />
      <div class="row">
        <button class="btn ghost small" data-save="${i}">💾 Save metadata</button>
        <select class="restyle" data-restyle="${i}" title="re-render this clip in another caption style">${styleOpts}</select>
        <span class="saved" id="saved-${i}"></span>
      </div>
    </div>
    <div class="postrow" id="post-${i}">${postChips(c, i)}</div>`;
}

function ensureClipCard(job, c, i) {
  let el = document.querySelector(`#clips .clipcard[data-clip="${i}"]`);
  if (!el) {
    el = document.createElement('article');
    el.className = 'glass clipcard enter';
    el.dataset.clip = i;
    el.innerHTML = clipCardHTML(job, c, i);
    $('clips').appendChild(el);
    setTimeout(() => el.classList.add('in'), 60);
    bindClipCard(el, job.id);
    animateDial(el, c.score || 0);
    animateBars(el);
  } else {
    const row = el.querySelector('.postrow');
    if (row && row.dataset.sig !== postSig(c)) {
      const before = row.innerHTML;
      row.innerHTML = postChips(c, i);
      row.dataset.sig = postSig(c);
      bindPost(row, job.id);
      if (!before.includes('postchip err') && row.innerHTML.includes('postchip err')) {
        const errChip = row.querySelector('.postchip.err');
        if (errChip) toast(errChip.textContent.trim(), true);
      }
    }
  }
}

function animateDial(el, score) {
  const fg = el.querySelector('.dial-fg'), num = el.querySelector('.dial-num');
  const C = 2 * Math.PI * 26;
  requestAnimationFrame(() => {
    fg.style.strokeDashoffset = (C * (1 - score / 100)).toFixed(1);
  });
  const t0 = performance.now(), dur = 1100;
  let done = false;
  const finish = () => { if (!done) { done = true; num.textContent = score; fg.style.strokeDashoffset = (C * (1 - score / 100)).toFixed(1); } };
  const tick = (t) => {
    const k = Math.min(1, (t - t0) / dur);
    num.textContent = Math.round(score * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(tick); else done = true;
  };
  requestAnimationFrame(tick);
  setTimeout(finish, 1400);  // rAF is throttled in backgrounded tabs — the final value must land regardless
}

function animateBars(el) {
  setTimeout(() => {
    el.querySelectorAll('.fbar i').forEach(b => { b.style.width = (b.dataset.w || 0) + '%'; });
  }, 120);
}

function postChips(clip, i) {
  return PLATFORMS.map(p => {
    const st = clip.post?.[p];
    let cls = '', label = `Post → ${PLATFORM_LABEL[p]}`;
    if (st?.status === 'uploading') { cls = 'busy'; label = `${PLATFORM_LABEL[p]} uploading…`; }
    if (st?.status === 'published') { cls = 'done'; label = `✅ ${PLATFORM_LABEL[p]} published`; }
    if (st?.status === 'assisted_ready') { cls = 'done'; label = `📋 ${PLATFORM_LABEL[p]} ready — caption copied`; }
    if (st?.status === 'error') { cls = 'err'; label = `⚠️ ${PLATFORM_LABEL[p]}: ${st.note || 'failed'}`; }
    const attrs = st ? '' : `data-post="${p}" data-clip="${i}"`;
    const inner = st?.link ? `<a href="${st.link}" target="_blank">${esc(label)}</a>` : esc(label);
    return `<span class="postchip ${cls}" ${attrs}>${inner}</span>`;
  }).join('');
}

function bindClipCard(el, jobId) {
  el.querySelectorAll('[data-save]').forEach(b => b.addEventListener('click', () => saveMeta(jobId, b.dataset.save)));
  el.querySelectorAll('[data-post]').forEach(b => b.addEventListener('click', () => sendPost(jobId, b.dataset.post, b.dataset.clip)));
  el.querySelectorAll('[data-restyle]').forEach(sel => sel.addEventListener('change', () => {
    const i = Number(sel.dataset.restyle);
    const card = el;  // this card
    toast('re-rendering with ' + sel.options[sel.selectedIndex].text + ' captions…');
    post('/api/custom', JSON.stringify({
      job_id: jobId,
      start: currentClip(i)?.start, end: currentClip(i)?.end,
      style: sel.value,
    })).then(() => {
      // poll the freshly appended clip
      clearInterval(pollTimer);
      pollTimer = setInterval(poll, 1500);
      poll();
    }).catch(e => toast(String(e.message || e), true));
  }));
}
const currentClip = (i) => (fullJobCache?.clips || [])[i];
let fullJobCache = null;

function bindPost(row, jobId) {
  row.querySelectorAll('[data-post]').forEach(b => b.addEventListener('click', () => sendPost(jobId, b.dataset.post, b.dataset.clip)));
}

async function saveMeta(jobId, i) {
  const body = {
    title: document.getElementById(`t-${i}`).value,
    description: document.getElementById(`d-${i}`).value,
    hashtags: document.getElementById(`h-${i}`).value.split(/\s+/).filter(Boolean),
  };
  const res = await fetch(`/api/job/${jobId}/meta/${i}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const el = document.getElementById(`saved-${i}`);
  el.textContent = res.ok ? 'saved ✓' : 'save failed';
  toast(res.ok ? 'metadata saved' : 'save failed', !res.ok);
  setTimeout(() => el.textContent = '', 2500);
}

async function sendPost(jobId, platform, clipIndex) {
  await post('/api/post', JSON.stringify({ job_id: jobId, index: Number(clipIndex || 0), platforms: [platform] }));
  toast(`queued for ${PLATFORM_LABEL[platform]} — watch the chip go live`);
  if (jobFullFetched) { clearInterval(pollTimer); pollTimer = setInterval(poll, 1500); jobFullFetched = false; }
  poll();
}

/* ---------- Candidate Lab ---------- */
function buildLab(job) {
  const cands = (job.candidates || []).filter(c => !c.selected);
  const grid = $('labgrid');
  if (!cands.length) { $('labwrap').hidden = true; $('lab-empty').hidden = false; return; }
  $('lab-empty').hidden = true;
  $('labwrap').hidden = false;
  grid.innerHTML = cands.map((c) => `
    <div class="labcards glass" data-cand="${job.candidates.indexOf(c)}">
      <div class="labtop">
        <span class="labscore">${c.score}</span>
        <div>
          <div class="labtitle">${esc(c.title)}</div>
          <div class="labsub">${c.start.toFixed(0)}s → ${c.end.toFixed(0)}s${c.qc === 'verified' ? ' · ✓' : ''}</div>
        </div>
      </div>
      <div class="labmini">
        ${(c.factors ? Object.keys(FACTOR_LABEL).map(f => `<span class="lm ${factorsLevel((c.factors || {})[f])}">${f[0].toUpperCase()}${(c.factors || {})[f] ?? '–'}</span>`).join('') : '')}
      </div>
      <button class="btn ghost small" data-render="${job.candidates.indexOf(c)}">⚡ Render this clip</button>
    </div>`).join('');
  grid.querySelectorAll('[data-render]').forEach(b => b.addEventListener('click', async () => {
    const idx = Number(b.dataset.render);
    b.disabled = true; b.textContent = 'rendering…';
    try {
      await post('/api/render', JSON.stringify({ job_id: currentJob, cand_index: idx, style: chosenStyle }));
      toast('rendering runner-up — it will appear in the podium');
      clearInterval(pollTimer);
      pollTimer = setInterval(poll, 1500);
      jobFullFetched = false;
      poll();
    } catch (e) {
      b.disabled = false; b.textContent = '⚡ Render this clip';
      toast(String(e.message || e), true);
    }
  }));
}
const factorsLevel = (v) => (v ?? 0) >= 75 ? 'hi' : (v ?? 0) >= 45 ? 'mid' : 'lo';

/* ---------- Transcript + custom cuts ---------- */
function buildCutbox(job) {
  const segs = job.segments || [];
  if (!segs.length || !job.src_name) { $('cutwrap').hidden = true; $('cut-empty').hidden = false; return; }
  $('cut-empty').hidden = true;
  $('cutwrap').hidden = false;
  if ($('srcvid').getAttribute('src') !== `/media/${job.src_name}`) {
    $('srcvid').src = `/media/${job.src_name}`;
  }
  const tr = $('transcript');
  tr.innerHTML = segs.filter(s => s.text).map(s =>
    `<span class="seg" data-t="${s.start}"><i>${fmt(s.start)}</i> ${esc(s.text)}</span>`).join('');
  tr.querySelectorAll('.seg').forEach(el => el.addEventListener('click', () => {
    $('srcvid').currentTime = Number(el.dataset.t);
    $('srcvid').play();
  }));
  // moment markers on the cutbar
  const bar = $('cutbar');
  bar.querySelectorAll('.mark').forEach(m => m.remove());
  const dur = job.duration || Math.max(...segs.map(s => s.end), 1);
  bar.dataset.dur = dur;
  (job.clips || []).forEach(c => {
    const m = document.createElement('span');
    m.className = 'mark sel';
    m.style.left = (c.start / dur * 100) + '%';
    m.style.width = Math.max(0.6, (c.end - c.start) / dur * 100) + '%';
    bar.appendChild(m);
  });
  (job.candidates || []).forEach(c => {
    const m = document.createElement('span');
    m.className = 'mark cand';
    m.style.left = (c.start / dur * 100) + '%';
    m.style.width = Math.max(0.5, (c.end - c.start) / dur * 100) + '%';
    bar.appendChild(m);
  });
  setCut(Math.max(0, dur * 0.1), Math.min(dur, dur * 0.1 + 20));
  bindCutDrag(dur);
}

const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;

function setCut(a, b) {
  const dur = Number($('cutbar').dataset.dur || 0);
  if (!dur) return;
  cut.start = Math.max(0, Math.min(a, b - 3));
  cut.end = Math.min(dur, Math.max(b, cut.start + 3));
  $('cutwin').style.left = (cut.start / dur * 100) + '%';
  $('cutwin').style.width = ((cut.end - cut.start) / dur * 100) + '%';
  $('cutrange').textContent = `${fmt(cut.start)} → ${fmt(cut.end)}  (${(cut.end - cut.start).toFixed(1)}s)`;
}

function bindCutDrag(dur) {
  const bar = $('cutbar');
  const drag = (el, which) => {
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const r = bar.getBoundingClientRect();
        const t = Math.max(0, Math.min(dur, (ev.clientX - r.left) / r.width * dur));
        setCut(which === 'l' ? t : cut.start, which === 'r' ? t : cut.end);
      };
      const up = () => {
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
    });
  };
  drag($('hl'), 'l');
  drag($('hr'), 'r');
  bar.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.h') || e.target.closest('.cutwin')) return;
    const r = bar.getBoundingClientRect();
    const t = Math.max(0, Math.min(dur, (e.clientX - r.left) / r.width * dur));
    setCut(t, t + Math.min(20, cut.end - cut.start));
  });
}

$('cutgo').addEventListener('click', async () => {
  if (!currentJob) return;
  $('cutgo').disabled = true;
  try {
    await post('/api/custom', JSON.stringify({ job_id: currentJob, start: cut.start, end: cut.end, style: chosenStyle }));
    toast('cutting your custom clip — it lands in the podium when rendered');
    clearInterval(pollTimer);
    jobFullFetched = false;
    pollTimer = setInterval(poll, 1500);
    poll();
  } catch (e) {
    toast(String(e.message || e), true);
  } finally {
    $('cutgo').disabled = false;
  }
});

/* ---------- Connect tab ---------- */
async function refreshSocial() {
  try {
    const [s, health, diag] = await Promise.all([
      (await fetch('/api/social/status')).json(),
      (await fetch('/api/health')).json(),
      (await fetch('/api/social/youtube/diagnose')).json(),
    ]);
    const yt = s.youtube;
    const configured = yt.configured && !!health.youtube_ready;
    $('yt-redirect').textContent = `${location.origin}/oauth/youtube/callback`;
    renderDiag(diag);
    if (yt.connected) {
      $('yt-status').textContent = yt.channel ? `connected · ${yt.channel}` : 'connected';
      $('yt-status').className = 'chip ok';
      $('yt-detail').innerHTML = '<span class="chip ok">✅ OAuth token verified — auto-upload active</span>';
    } else if (configured) {
      $('yt-status').textContent = 'not connected';
      $('yt-status').className = 'chip';
      $('yt-detail').innerHTML = '<span class="chip">keys loaded → press Connect and finish the Google consent</span>';
    } else {
      $('yt-status').textContent = '❌ OAuth not set up yet';
      $('yt-status').className = 'chip err';
      $('yt-detail').innerHTML = '<span class="chip err">CB_YT_CLIENT_ID/SECRET missing in .env — posting will fail until the 4 steps above are done</span>';
    }
    $('tt-detail').innerHTML = '<span class="chip gold">assisted: caption copied to clipboard on render</span>';
  } catch (e) { /* status is best-effort */ }
}

function renderDiag(diag) {
  const box = $('yt-diag');
  if (!diag || !diag.steps) { box.hidden = true; return; }
  box.hidden = false;
  const rows = Object.entries(diag.steps).map(([name, s]) => `
    <div class="diagrow">
      <span class="diagdot ${s.ok ? 'ok' : 'bad'}">${s.ok ? '✓' : '✗'}</span>
      <div><b>${esc(name.replace(/_/g, ' '))}</b> — ${esc(s.detail)}${s.fix ? `<div class="dim">fix: ${esc(s.fix)}</div>` : ''}</div>
    </div>`).join('');
  const known = (diag.known_errors || []).map(k => `
    <div class="diagrow">
      <span class="diagdot bad">!</span>
      <div><b>${esc(k.error)}</b> — ${esc(k.cause)}<div class="dim">fix: ${esc(k.fix)}</div></div>
    </div>`).join('');
  box.innerHTML = `<div class="diaghead">Auto-post chain — live check</div>${rows}
    ${known ? `<div class="diaghead" style="margin-top:10px">If Google blocked you with one of these</div>${known}` : ''}
    <div class="diagrow"><span class="diagdot ${diag.ready ? 'ok' : 'bad'}">→</span><div><b>next:</b> ${esc(diag.next_action || '—')}</div></div>`;
}

$('yt-diagnose').addEventListener('click', async () => {
  try { renderDiag(await (await fetch('/api/social/youtube/diagnose')).json()); }
  catch (e) { toast(String(e.message || e), true); }
});

$('yt-copy').addEventListener('click', () => {
  navigator.clipboard.writeText($('yt-redirect').textContent).then(() => toast('redirect URI copied'));
});
$('yt-gcloud').addEventListener('click', () => window.open('https://console.cloud.google.com/projectcreate', '_blank'));
$('yt-gapi').addEventListener('click', () => window.open('https://console.cloud.google.com/apis/library/youtube.googleapis.com', '_blank'));
$('yt-gcreds').addEventListener('click', () => window.open('https://console.cloud.google.com/apis/credentials/oauthclient', '_blank'));
$('yt-gredirect').addEventListener('click', () => window.open('https://console.cloud.google.com/apis/credentials/consent', '_blank'));

function renderQueue() {
  const rows = [];
  (fullJobCache?.clips || []).forEach((c, i) => {
    Object.entries(c.post || {}).forEach(([p, st]) => {
      rows.push(`<div class="qrow"><b>#${i + 1}</b> → ${PLATFORM_LABEL[p]} · ${esc(st.status)}${st.link ? ` · <a href="${st.link}" target="_blank">open</a>` : ''}${st.note ? ` · <span class="dim">${esc(st.note)}</span>` : ''}</div>`);
    });
  });
  const total = (fullJobCache?.clips || []).length;
  $('queue-count').textContent = `${total} clip${total === 1 ? '' : 's'} in Studio`;
  $('queue').innerHTML = rows.length ? rows.join('') : 'Nothing queued yet — clips you send to platforms appear here with live status.';
}

$('yt-connect').addEventListener('click', async () => {
  try {
    const { url } = await post('/api/social/youtube/start', '{}');
    if (!url) throw new Error('keys missing — see the diagnose checklist below');
    // open synchronously within the click gesture — popups after `await` get blocked
    const win = window.open('', '_blank');
    if (win) { win.opener = null; win.location = url; }
    else { location.href = url; toast('popup blocked — navigating this tab to Google…', true); }
  } catch (e) { toast(String(e.message || e), true); }
});
$('yt-disconnect').addEventListener('click', async () => {
  await post('/api/social/youtube/disconnect', '{}');
  refreshSocial();
});
$('tt-test').addEventListener('click', () => window.open('https://www.tiktok.com/upload', '_blank'));
$('ig-test').addEventListener('click', () => window.open('https://www.instagram.com/', '_blank'));

/* ---------- deep link: /?job=<id> reopens a persisted job after a refresh ---------- */
const wanted = new URLSearchParams(location.search).get('job');
if (wanted) {
  fetch(`/api/job/${wanted}?light=1`).then((r) => {
    if (!r.ok) throw new Error('unknown job');
    return r.json();
  }).then((job) => {
    watch(job.id, job.name || job.id);
    if ((job.clips || []).length) showScreen('clips');  // deep link straight to the podium
  }).catch(() => toast('that job no longer exists — run a new one', true));
}

/* ---------- Clips screen: offer the most recent finished job, not a blank wall ---------- */
(async function latestJobResume() {
  try {
    const jobs = await (await fetch('/api/jobs')).json();
    const latest = jobs.find(j => j.status === 'done' && j.clips > 0);
    if (!latest) return;
    const empty = document.getElementById('clips-empty');
    if (!empty) return;
    const btn = document.createElement('button');
    btn.className = 'btn small';
    btn.style.marginTop = '4px';
    btn.textContent = `🎞️ Show the latest clips (${latest.name || latest.id})`;
    btn.addEventListener('click', () => {
      fetch(`/api/job/${latest.id}?light=1`).then(r => r.json()).then(job => {
        watch(job.id, job.name || job.id);
        showScreen('clips');
      });
    });
    empty.appendChild(btn);
  } catch { /* best effort */ }
})();
