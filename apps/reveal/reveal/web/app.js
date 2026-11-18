'use strict';

const $ = (id) => document.getElementById(id);
const state = { photos: [], results: [], photo: null, filtre: 'auto', mode: 'slider', shown: null, job: null };

// ---------- utilitaires ----------
async function api(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ('Erreur ' + r.status));
  return data;
}
function toast(msg, isErr) {
  const t = $('toast');
  t.textContent = msg; t.className = 'toast' + (isErr ? ' err' : ''); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 3500);
}
const media = (zone, name) => `/media/${zone}/${encodeURIComponent(name)}?v=${Date.now()}`;
const FILTER_NAMES = { auto: 'Automatique', portrait: 'Portrait', ancienne: 'Photo ancienne', restauration: 'Restauration seule' };

// ---------- bibliothèque ----------
async function loadPhotos() {
  state.photos = await api('/api/photos');
  const box = $('thumbs'); box.innerHTML = '';
  for (const p of state.photos) {
    const b = document.createElement('button');
    b.className = 'thumb' + (state.photo === p.name ? ' is-active' : '');
    b.title = p.name;
    b.innerHTML = `<img loading="lazy" alt=""><span></span>`;
    b.querySelector('img').src = p.url;
    b.querySelector('span').textContent = p.name;
    b.onclick = () => selectPhoto(p.name);
    box.appendChild(b);
  }
}
async function loadResults() {
  state.results = await api('/api/resultats');
  const strip = $('history'); strip.innerHTML = '';
  if (!state.results.length) { strip.innerHTML = '<span class="muted">Aucune pour l\'instant.</span>'; return; }
  for (const r of state.results.slice(0, 30)) {
    const b = document.createElement('button');
    b.className = 'hist';
    b.innerHTML = '<img loading="lazy" alt=""><span></span>';
    b.querySelector('img').src = media('retouche', r.jpg);
    b.querySelector('span').textContent = r.base.replace('_photocraft', ' · retouche');
    b.onclick = () => showResult({ avant: r.avant, apres: r.jpg, psd: r.psd, jpg: r.jpg, photo: r.photo, base: r.base });
    strip.appendChild(b);
  }
}
function selectPhoto(name) {
  state.photo = name;
  document.querySelectorAll('.thumb').forEach((t) => t.classList.toggle('is-active', t.title === name));
  $('applyBtn').disabled = !!(state.job && state.job.etat === 'en cours');
  $('viewerTitle').textContent = name;
  const last = state.results.find((r) => r.photo === name.replace(/\.[^.]+$/, ''));
  if (last) showResult({ avant: last.avant, apres: last.jpg, psd: last.psd, jpg: last.jpg, photo: last.photo, base: last.base });
  else showSingle(media('original', name));
}

// ---------- dépôt de fichier ----------
async function upload(file) {
  const fd = new FormData(); fd.append('photo', file);
  try {
    const r = await api('/api/photos', { method: 'POST', body: fd });
    await loadPhotos(); selectPhoto(r.name); toast('Photo ajoutée : ' + r.name);
  } catch (e) { toast(e.message, true); }
}
const dz = $('dropzone');
$('fileInput').onchange = (e) => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ''; };
['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('is-over'); }));
['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('is-over'); }));
dz.addEventListener('drop', (e) => { const f = e.dataTransfer.files[0]; if (f) upload(f); });

// ---------- filtres ----------
document.querySelectorAll('.filter').forEach((b) => b.onclick = () => {
  state.filtre = b.dataset.filtre;
  document.querySelectorAll('.filter').forEach((x) => x.classList.toggle('is-active', x === b));
});

// ---------- traitement ----------
$('applyBtn').onclick = async () => {
  if (!state.photo) return;
  try {
    const { id } = await api('/api/traiter', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo: state.photo, filtre: state.filtre }),
    });
    state.job = { id, etat: 'en cours' };
    $('applyBtn').disabled = true;
    $('progress').hidden = false; $('spinner').className = 'spinner';
    $('progressTitle').textContent = FILTER_NAMES[state.filtre] + ' : traitement en cours…';
    $('log').innerHTML = '';
    poll(id);
  } catch (e) { toast(e.message, true); }
};
async function poll(id) {
  let job;
  try { job = await api('/api/jobs/' + id); } catch (e) { setTimeout(() => poll(id), 1500); return; }
  state.job = job;
  $('elapsed').textContent = job.ecoule + ' s';
  const log = $('log'); log.innerHTML = '';
  for (const line of job.journal.slice(-40)) {
    const li = document.createElement('li');
    li.textContent = line.replace(/^==\s*/, 'Photo : ').replace(/^->\s*/, 'Enregistré : ');
    if (/ERREUR|impossible/.test(line)) li.className = 'err';
    log.appendChild(li);
  }
  log.scrollTop = log.scrollHeight;
  if (job.etat === 'en cours') { setTimeout(() => poll(id), 1000); return; }
  $('applyBtn').disabled = !state.photo;
  if (job.etat === 'termine') {
    $('spinner').className = 'spinner done';
    $('progressTitle').textContent = 'Terminé en ' + job.ecoule + ' s';
    await loadResults();
    const r = job.resultat;
    showResult({ avant: r.avant, apres: r.apres, psd: r.psd, jpg: r.apres, photo: r.photo, base: r.psd.replace('.psd', ''), type: r.type, duree: r.duree });
  } else {
    $('spinner').className = 'spinner fail';
    $('progressTitle').textContent = 'Le traitement a échoué';
    toast('Le traitement a échoué : voir le journal.', true);
  }
}

// ---------- visionneuse ----------
function showSingle(url) {
  state.shown = null;
  $('empty').hidden = true; $('side').hidden = true; $('actions').hidden = true;
  const c = $('compare'); c.hidden = false; c.className = 'compare mode-after';
  $('imgAfter').src = url;
  c.querySelector('.tag-after').textContent = 'Original';
}
function showResult(r) {
  state.shown = r;
  $('empty').hidden = true;
  $('viewerTitle').textContent = (r.photo || '') + ' — retouche';
  const before = r.avant ? media('retouche', r.avant) : null;
  const after = media('retouche', r.apres);
  $('imgAfter').src = after; $('sideAfter').src = after;
  if (before) { $('imgBefore').src = before; $('sideBefore').src = before; }
  $('compare').querySelector('.tag-after').textContent = 'Après';
  $('dlJpg').href = media('retouche', r.jpg); $('dlJpg').setAttribute('download', r.jpg);
  $('openPsd').hidden = !r.psd;
  const bits = [];
  if (r.type) bits.push('Type : ' + r.type);
  if (r.duree) bits.push(r.duree + ' s');
  bits.push(r.jpg);
  $('meta').textContent = bits.join(' · ');
  $('actions').hidden = false;
  setMode(before ? state.mode : 'after');
}
function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll('#modes button').forEach((b) => b.classList.toggle('is-active', b.dataset.mode === mode));
  if (!state.shown) return;
  const c = $('compare');
  if (mode === 'side') { c.hidden = true; $('side').hidden = false; return; }
  $('side').hidden = true; c.hidden = false;
  c.className = 'compare' + (mode === 'before' ? ' mode-before' : mode === 'after' ? ' mode-after' : '');
}
document.querySelectorAll('#modes button').forEach((b) => b.onclick = () => setMode(b.dataset.mode));

// curseur avant / après : glisser n'importe où sur l'image, ou flèches du clavier
(function slider() {
  const c = $('compare'), h = $('handle');
  let dragging = false;
  const setPos = (pct) => {
    pct = Math.max(0, Math.min(100, pct));
    c.style.setProperty('--pos', pct + '%');
    h.setAttribute('aria-valuenow', Math.round(pct));
  };
  const fromEvent = (e) => { const r = c.getBoundingClientRect(); setPos(((e.clientX - r.left) / r.width) * 100); };
  c.addEventListener('pointerdown', (e) => {
    if (c.classList.contains('mode-before') || c.classList.contains('mode-after')) return;
    dragging = true; c.setPointerCapture(e.pointerId); fromEvent(e);
  });
  c.addEventListener('pointermove', (e) => { if (dragging) fromEvent(e); });
  c.addEventListener('pointerup', () => { dragging = false; });
  h.addEventListener('keydown', (e) => {
    const cur = parseFloat(getComputedStyle(c).getPropertyValue('--pos')) || 50;
    if (e.key === 'ArrowLeft') { setPos(cur - 2); e.preventDefault(); }
    if (e.key === 'ArrowRight') { setPos(cur + 2); e.preventDefault(); }
  });
})();

$('openPsd').onclick = async () => {
  if (!state.shown || !state.shown.psd) return;
  try { await api('/api/ouvrir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fichier: state.shown.psd }) }); toast('Ouverture dans PhotoCraft…'); }
  catch (e) { toast(e.message, true); }
};

// ---------- démarrage ----------
(async function init() {
  try { await Promise.all([loadPhotos(), loadResults()]); }
  catch (e) { toast('Serveur injoignable : ' + e.message, true); return; }
  // lien direct : /?photo=1.jpg&mode=side
  const q = new URLSearchParams(location.search);
  if (q.get('mode')) state.mode = q.get('mode');
  if (q.get('photo') && state.photos.some((p) => p.name === q.get('photo'))) selectPhoto(q.get('photo'));
})();
