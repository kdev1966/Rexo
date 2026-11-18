'use strict';

const $ = (id) => document.getElementById(id);
const state = { photos: [], results: [], photo: null, filtre: 'auto', mode: 'slider', shown: null, job: null, zones: [] };

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
const FILTER_NAMES = { auto: 'Automatique', portrait: 'Portrait', ancienne: 'Photo ancienne', restauration: 'Restauration seule', ameliorer: 'Améliorer', studio: 'Studio', effacer: 'Effacer' };

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
  state.zones = []; renderZones();
  if (state.filtre === 'effacer') {
    document.querySelectorAll('.thumb').forEach((t) => t.classList.toggle('is-active', t.title === name));
    $('applyBtn').disabled = !!(state.job && state.job.etat === 'en cours');
    $('viewerTitle').textContent = name + ' — zones à effacer';
    showSingle(media('original', name));
    return;
  }
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
  $('styleOption').hidden = state.filtre !== 'ameliorer';
  $('studioOptions').hidden = state.filtre !== 'studio';
  studioVisibility();
  $('erasePanel').hidden = state.filtre !== 'effacer';
  if (state.filtre === 'effacer' && state.photo) showSingle(media('original', state.photo));
  eraseVisibility();
});
function studioVisibility() {
  const e = $('studioEffet').value;
  $('couleurOption').hidden = e !== 'fond-uni';
  $('formatOption').hidden = e !== 'recadrage';
}
async function loadStudio() {
  const d = await api('/api/studio');
  for (const e of d.effets) { const o = document.createElement('option'); o.value = e.id; o.textContent = e.nom; $('studioEffet').appendChild(o); }
  for (const f of d.formats) { const o = document.createElement('option'); o.value = f; o.textContent = f; $('studioFormat').appendChild(o); }
  $('studioEffet').onchange = studioVisibility;
  studioVisibility();
}
function hexToRgb(h) { return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)).join(','); }
async function loadStyles() {
  const sel = $('styleSelect');
  for (const s of await api('/api/styles')) {
    const o = document.createElement('option'); o.value = s.id; o.textContent = s.nom; sel.appendChild(o);
  }
}

// ---------- traitement ----------
$('applyBtn').onclick = async () => {
  if (!state.photo) return;
  if (state.filtre === 'effacer' && !state.zones.length) { toast('Tracez au moins une zone à effacer sur la photo.', true); return; }
  try {
    const { id } = await api('/api/traiter', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo: state.photo, filtre: state.filtre,
        style: state.filtre === 'ameliorer' ? $('styleSelect').value : '',
        effet: $('studioEffet').value, couleur: hexToRgb($('studioCouleur').value), format: $('studioFormat').value,
        zones: state.filtre === 'effacer' ? state.zones : undefined }),
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
  eraseVisibility(true);
  $('empty').hidden = true; $('side').hidden = true; $('actions').hidden = true;
  const c = $('compare'); c.hidden = false; c.className = 'compare mode-after';
  $('imgAfter').src = url;
  c.querySelector('.tag-after').textContent = 'Original';
}
function showResult(r) {
  state.shown = r;
  eraseVisibility(false);
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

// ---------- zones à effacer : cadres et clics dessinés sur la photo ----------
function eraseVisibility(single) {
  const on = state.filtre === 'effacer' && (single === undefined ? !state.shown : single);
  $('zonesLayer').hidden = !on;
}
function renderZones() {
  const layer = $('zonesLayer'); layer.innerHTML = '';
  state.zones.forEach((z, i) => {
    let ax = 0, ay = 0;
    if (z.cadre) {
      const [x, y, w, h] = z.cadre, d = document.createElement('div');
      d.className = 'zone-box';
      Object.assign(d.style, { left: x * 100 + '%', top: y * 100 + '%', width: w * 100 + '%', height: h * 100 + '%' });
      layer.appendChild(d); ax = x + w / 2; ay = y;
    }
    for (const p of z.points || []) {
      const d = document.createElement('div');
      d.className = 'zone-pt' + (p[2] === 0 ? ' neg' : '');
      Object.assign(d.style, { left: p[0] * 100 + '%', top: p[1] * 100 + '%' });
      layer.appendChild(d);
      if (!z.cadre && !ax) { ax = p[0]; ay = p[1]; }
    }
    const n = document.createElement('div');
    n.className = 'zone-num'; n.textContent = i + 1;
    Object.assign(n.style, { left: ax * 100 + '%', top: ay * 100 + '%' });
    layer.appendChild(n);
  });
  const c = state.zones.length;
  $('zoneCount').textContent = c ? c + (c > 1 ? ' zones' : ' zone') : 'Aucune zone';
}
(function eraseTool() {
  const layer = $('zonesLayer');
  let start = null, ghost = null;
  const frac = (e) => {
    const r = layer.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };
  layer.addEventListener('pointerdown', (e) => {
    e.preventDefault(); e.stopPropagation();
    layer.setPointerCapture(e.pointerId);
    start = { p: frac(e), alt: e.altKey };
    ghost = document.createElement('div'); ghost.className = 'zone-box'; layer.appendChild(ghost);
  });
  layer.addEventListener('pointermove', (e) => {
    if (!start) return;
    const [x, y] = frac(e), [x0, y0] = start.p;
    Object.assign(ghost.style, { left: Math.min(x, x0) * 100 + '%', top: Math.min(y, y0) * 100 + '%',
      width: Math.abs(x - x0) * 100 + '%', height: Math.abs(y - y0) * 100 + '%' });
  });
  layer.addEventListener('pointerup', (e) => {
    if (!start) return;
    const [x, y] = frac(e), [x0, y0] = start.p;
    const w = Math.abs(x - x0), h = Math.abs(y - y0);
    if (w < 0.01 && h < 0.01) {                       // un clic
      if (start.alt && state.zones.length) {
        const last = state.zones[state.zones.length - 1];
        (last.points = last.points || []).push([x0, y0, 0]);
      } else if (state.zones.length < 20) {
        state.zones.push({ points: [[x0, y0, 1]] });
      }
    } else if (state.zones.length < 20) {             // un cadre
      state.zones.push({ cadre: [Math.min(x, x0), Math.min(y, y0), w, h] });
    }
    start = null; renderZones();
  });
  $('undoZone').onclick = () => { state.zones.pop(); renderZones(); };
  $('clearZones').onclick = () => { state.zones = []; renderZones(); };
})();

$('openPsd').onclick = async () => {
  if (!state.shown || !state.shown.psd) return;
  try { await api('/api/ouvrir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fichier: state.shown.psd }) }); toast('Ouverture dans PhotoCraft…'); }
  catch (e) { toast(e.message, true); }
};

// ---------- démarrage ----------
(async function init() {
  try { await Promise.all([loadPhotos(), loadResults(), loadStyles(), loadStudio()]); }
  catch (e) { toast('Serveur injoignable : ' + e.message, true); return; }
  // lien direct : /?photo=1.jpg&mode=side
  const q = new URLSearchParams(location.search);
  if (q.get('mode')) state.mode = q.get('mode');
  if (q.get('photo') && state.photos.some((p) => p.name === q.get('photo'))) selectPhoto(q.get('photo'));
})();

// ---------- quitter : arrête le serveur (et un traitement en cours) ----------
(function quitter() {
  const b = $('quitBtn');
  let arme = null;
  b.onclick = async () => {
    const enCours = !!(state.job && state.job.etat === 'en cours');
    if (enCours && !arme) {           // un traitement tourne : second clic pour confirmer
      b.classList.add('is-confirm'); b.querySelector('span').textContent = 'Arrêter le traitement ?';
      arme = setTimeout(() => { arme = null; b.classList.remove('is-confirm'); b.querySelector('span').textContent = 'Quitter'; }, 4000);
      return;
    }
    clearTimeout(arme);
    try {
      await fetch('/api/quitter', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    } catch (e) { /* serveur déjà arrêté */ }
    $('stopped').hidden = false;
    window.close();                    // ne ferme que les onglets ouverts par un script ; sinon l'écran reste
  };
})();
