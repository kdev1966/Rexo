'use strict';

const $ = (id) => document.getElementById(id);
const state = { photos: [], photo: null, mode: 'auto', fond: [214, 214, 214], view: 'identite', result: null, busy: false };
const SVG = 'http://www.w3.org/2000/svg';

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
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 4000);
}
const media = (zone, name, v) => `/media/${zone}/${encodeURIComponent(name)}?v=${v || Date.now()}`;
const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const rgbToHex = (c) => '#' + c.map((x) => x.toString(16).padStart(2, '0')).join('');

// ---------- portraits ----------
async function loadPhotos() {
  state.photos = await api('/api/photos');
  const box = $('thumbs'); box.innerHTML = '';
  for (const p of state.photos) {
    const b = document.createElement('button');
    b.className = 'thumb' + (state.photo === p.name ? ' is-active' : '');
    b.title = p.name;
    b.innerHTML = '<img loading="lazy" alt=""><span></span>';
    b.querySelector('img').src = media('original', p.name, 1);
    b.querySelector('span').textContent = p.name;
    if (p.fait) {
      const d = document.createElement('b'); d.className = 'done'; d.textContent = '✓'; d.title = 'Photos déjà fabriquées';
      b.appendChild(d);
    }
    b.onclick = () => selectPhoto(p.name);
    box.appendChild(b);
  }
}

async function selectPhoto(name, garderVue) {
  state.photo = name;
  document.querySelectorAll('.thumb').forEach((t) => t.classList.toggle('is-active', t.title === name));
  $('viewerTitle').textContent = name;
  $('applyBtn').disabled = state.busy;
  try {
    state.result = await api('/api/resultat?photo=' + encodeURIComponent(name));
  } catch (e) { state.result = null; toast(e.message, true); }
  if (!state.result && state.view !== 'original') state.view = 'original';
  if (state.result && state.view === 'original' && !garderVue) state.view = 'identite';
  render();
}

async function upload(file) {
  const fd = new FormData(); fd.append('photo', file);
  try {
    const r = await api('/api/photos', { method: 'POST', body: fd });
    await loadPhotos();
    await selectPhoto(r.name);
    toast('Portrait ajouté : ' + r.name);
  } catch (e) { toast(e.message, true); }
}

// ---------- affichage ----------
function saveHash() {
  if (!state.photo) return;
  const h = '#photo=' + encodeURIComponent(state.photo) + '&vue=' + state.view;
  if (location.hash !== h) history.replaceState(null, '', h);
}
function readHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  return { photo: q.get('photo'), vue: q.get('vue') };
}

function render() {
  saveHash();
  const r = state.result;
  document.querySelectorAll('#views button').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.view === state.view);
    b.disabled = !state.photo || (b.dataset.view !== 'original' && !r);
  });
  $('empty').hidden = !!state.photo;
  $('shot').hidden = !state.photo;
  $('report').hidden = !r;
  if (!state.photo) return;

  const img = $('shotImg');
  if (state.view === 'original') {
    img.src = media('original', state.photo, 1);
  } else {
    img.src = media('resultats', r.fichiers[state.view], r.version);
  }
  $('shot').classList.toggle('is-sheet', state.view.startsWith('planche'));
  const guides = state.view === 'identite' && r && $('guidesBox').checked;
  $('guides').toggleAttribute('hidden', !guides);     // SVG : pas de propriété .hidden
  $('guidesToggle').hidden = state.view !== 'identite';
  if (guides) drawGuides(r);
  if (r) renderReport(r);
}

function el(tag, attrs, text) {
  const e = document.createElementNS(SVG, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text) e.textContent = text;
  return e;
}

function drawGuides(r) {
  const g = $('guides'); g.innerHTML = '';
  const n = r.norme, c = r.cadrage;
  // Zone où doit tomber le menton : de 32 à 36 mm sous le sommet du crâne
  g.appendChild(el('rect', { class: 'band', x: 0, y: c.crane_mm + n.tete_min, width: n.largeur, height: n.tete_max - n.tete_min }));
  g.appendChild(el('line', { class: 'line axe', x1: n.largeur / 2, y1: 0, x2: n.largeur / 2, y2: n.hauteur }));
  g.appendChild(el('line', { class: 'line crane', x1: 0, y1: c.crane_mm, x2: n.largeur, y2: c.crane_mm }));
  g.appendChild(el('line', { class: 'line menton', x1: 0, y1: c.menton_mm, x2: n.largeur, y2: c.menton_mm }));
  g.appendChild(el('text', { x: 0.6, y: c.crane_mm - 0.5 }, 'sommet du crâne'));
  g.appendChild(el('text', { x: 0.6, y: c.crane_mm + n.tete_min - 0.5 }, `menton : ${n.tete_min} à ${n.tete_max} mm`));
}

function renderReport(r) {
  const w = $('warnings'); w.innerHTML = '';
  const avis = r.avertissements || [];
  if (!avis.length) {
    const li = document.createElement('li'); li.className = 'ok';
    li.textContent = 'Aucun écart détecté. Vérifiez quand même : expression neutre, bouche fermée, regard droit, pas de reflet.';
    w.appendChild(li);
  }
  for (const a of avis) { const li = document.createElement('li'); li.textContent = a; w.appendChild(li); }

  const c = r.cadrage, col = r.couleurs || {};
  const facts = [
    ['Tête (menton → crâne)', `${c.tete_mm} mm`],
    ['Crâne / menton', `${c.crane_mm} / ${c.menton_mm} mm du haut`],
    ['Redressement', `${c.redressement}°`],
    ['Tête tournée', `${Math.round(r.lacet || 0)}°`],
    ['Couleurs', col.methode || '—'],
  ];
  if (col.gains_rvb) facts.push(['Gains R V B', col.gains_rvb.join(' · ')]);
  const dl = $('facts'); dl.innerHTML = '';
  for (const [k, v] of facts) {
    const d = document.createElement('div');
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = v;
    d.append(dt, dd); dl.appendChild(d);
  }
  const file = state.view === 'original' ? r.fichiers.identite : r.fichiers[state.view];
  $('downloadBtn').href = `/media/resultats/${encodeURIComponent(file)}?telecharger=1`;
  $('downloadBtn').textContent = 'Télécharger ' + ({ identite: 'la photo', planche_8: 'la planche', planche_4_portrait: 'la planche' }[state.view] || 'la photo');
  $('openBtn').onclick = () => api('/api/ouvrir', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fichier: file }),
  }).then(() => toast('Ouvert dans Aperçu : imprimer à 100 %.')).catch((e) => toast(e.message, true));
}

// ---------- fabrication ----------
async function fabriquer() {
  if (!state.photo || state.busy) return;
  state.busy = true; $('applyBtn').disabled = true;
  $('progress').hidden = false; $('spinner').className = 'spinner'; $('progressText').textContent = 'Fabrication…';
  const t0 = Date.now();
  const tick = setInterval(() => { $('elapsed').textContent = Math.round((Date.now() - t0) / 1000) + ' s'; }, 250);
  try {
    state.result = await api('/api/fabriquer', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo: state.photo, couleurs: state.mode, fond: state.fond }),
    });
    $('spinner').className = 'spinner done'; $('progressText').textContent = 'Photos prêtes';
    state.view = 'identite';
    await loadPhotos();
    render();
  } catch (e) {
    $('spinner').className = 'spinner fail'; $('progressText').textContent = 'Échec';
    toast(e.message, true);
  } finally {
    clearInterval(tick);
    state.busy = false; $('applyBtn').disabled = !state.photo;
  }
}

function setFond(rgb, source) {
  state.fond = rgb;
  document.querySelectorAll('.swatch').forEach((s) => s.classList.toggle('is-active', s === source));
  const lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
  const ecart = Math.max(...rgb) - Math.min(...rgb);
  const hint = $('fondHint');
  let msg = 'Fond uni et clair ; le blanc est refusé par la norme.', warn = false;
  if (lum > 240) { msg = 'Trop proche du blanc : refusé par la norme.'; warn = true; }
  else if (lum < 170) { msg = 'Trop sombre : la norme demande un fond clair.'; warn = true; }
  else if (ecart > 40) { msg = 'Couleur marquée : la norme demande un fond clair et neutre (gris, bleu clair).'; warn = true; }
  hint.textContent = msg; hint.classList.toggle('is-warn', warn);
}

// ---------- évènements ----------
document.querySelectorAll('#modes .choice').forEach((b) => b.onclick = () => {
  state.mode = b.dataset.mode;
  document.querySelectorAll('#modes .choice').forEach((x) => x.classList.toggle('is-active', x === b));
});
document.querySelectorAll('.swatch[data-rgb]').forEach((s) => s.onclick = () => setFond(s.dataset.rgb.split(',').map(Number), s));
$('customColor').oninput = (e) => setFond(hexToRgb(e.target.value), e.target.closest('.swatch'));
$('customColor').onclick = (e) => setFond(hexToRgb(e.target.value), e.target.closest('.swatch'));
document.querySelectorAll('#views button').forEach((b) => b.onclick = () => { state.view = b.dataset.view; render(); });
$('guidesBox').onchange = render;
$('applyBtn').onclick = fabriquer;
$('fileInput').onchange = (e) => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ''; };
const dz = $('dropzone');
['dragenter', 'dragover'].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add('is-over'); }));
['dragleave', 'drop'].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove('is-over'); }));
dz.addEventListener('drop', (e) => { const f = e.dataTransfer.files[0]; if (f) upload(f); });

$('customColor').value = rgbToHex(state.fond);
loadPhotos().then(() => {
  const h = readHash();                       // #photo=…&vue=… : reprend la photo et la vue affichées
  if (h.photo && state.photos.some((p) => p.name === h.photo)) {
    if (['identite', 'planche_8', 'planche_4_portrait', 'original'].includes(h.vue)) state.view = h.vue;
    selectPhoto(h.photo, true);
  }
}).catch((e) => toast(e.message, true));
