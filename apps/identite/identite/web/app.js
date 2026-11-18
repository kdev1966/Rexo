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
  $('saveCard').hidden = !r;
  $('removeBtn').hidden = !state.photo;
  if (!state.photo) { $('viewerTitle').textContent = 'Choisissez un portrait'; return; }

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
  // Impression : la planche affichée, ou la planche de 8 photos depuis la photo seule et l'original
  const aImprimer = state.view.startsWith('planche') ? state.view : 'planche_8';
  $('printBtn').querySelector('span').textContent =
    state.view.startsWith('planche') ? 'Imprimer la planche' : 'Imprimer la planche de 8';
  $('printBtn').onclick = () => imprimer(media('resultats', r.fichiers[aImprimer], r.version));
  $('openBtn').onclick = () => api('/api/ouvrir', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fichier: file }),
  }).then(() => toast('Ouvert dans Aperçu : imprimer à 100 %.')).catch((e) => toast(e.message, true));
}

// ---------- impression ----------
// La planche (1772 × 1181 px à 300 dpi) est posée dans un cadre invisible, à sa taille réelle
// de 150 × 100 mm, sur une page de la même taille sans marge : la fenêtre d'impression du
// système s'ouvre, l'échelle reste à 100 %.
function imprimer(url) {
  const ancien = document.querySelector('.print-frame');
  if (ancien) ancien.remove();
  const f = document.createElement('iframe');
  f.className = 'print-frame';
  f.setAttribute('aria-hidden', 'true');
  document.body.appendChild(f);
  const doc = f.contentDocument;
  doc.open();
  doc.write('<!doctype html><html><head><meta charset="utf-8"><title>Planche</title><style>' +
    '@page { size: 150mm 100mm; margin: 0; }' +
    'html, body { margin: 0; padding: 0; background: #fff; }' +
    'img { display: block; width: 150mm; height: 100mm; }' +
    '</style></head><body><img alt=""></body></html>');
  doc.close();
  const img = doc.querySelector('img');
  img.onload = () => {
    toast('Choisir le papier 10 × 15 cm et l\'échelle 100 %.');
    setTimeout(() => { f.contentWindow.focus(); f.contentWindow.print(); }, 50);
  };
  img.onerror = () => toast('Planche introuvable : refaire « Fabriquer les photos ».', true);
  img.src = url;
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

// ---------- quitter : arrête le serveur (et un traitement en cours) ----------
(function quitter() {
  const b = $('quitBtn');
  let arme = null;
  b.onclick = async () => {
    const enCours = state.busy;
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

// ---------- confirmation par second clic (pas de fenêtre bloquante) ----------
function confirmer(bouton, question) {
  if (bouton._arme) {
    clearTimeout(bouton._arme); bouton._arme = null;
    bouton.classList.remove('is-confirm'); bouton.querySelector('span').textContent = bouton._libelle;
    return true;
  }
  const span = bouton.querySelector('span');
  bouton._libelle = span.textContent;
  span.textContent = question; bouton.classList.add('is-confirm');
  bouton._arme = setTimeout(() => {
    bouton._arme = null; bouton.classList.remove('is-confirm'); span.textContent = bouton._libelle;
  }, 4000);
  return false;
}
const jsonPost = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

// ---------- liste de travail : retirer un portrait ----------
$('removeBtn').onclick = async () => {
  if (!state.photo || state.busy) return;
  if (!confirmer($('removeBtn'), 'Mettre à la Corbeille ?')) return;
  try {
    await api('/api/photos/' + encodeURIComponent(state.photo), { method: 'DELETE' });
    toast(state.photo + ' et ses planches sont dans la Corbeille.');
    oublierPhoto();
  } catch (e) { toast(e.message, true); }
};
async function oublierPhoto() {
  state.photo = null; state.result = null; state.view = 'identite';
  history.replaceState(null, '', location.pathname);
  $('applyBtn').disabled = true;
  await loadPhotos();
  render();
}

// ---------- enregistrement pour un client ----------
const save = { client: null, nouveau: false, liens: [] };

function afficherClientChoisi() {
  const c = save.client;
  $('clientPicker').hidden = !!c || save.nouveau;
  $('clientChosen').hidden = !c;
  $('newClientForm').hidden = !save.nouveau;
  if (c) $('clientChosenText').textContent = [c.nom.toUpperCase(), c.prenom].filter(Boolean).join(' ') + (c.telephone ? ' · ' + c.telephone : '');
}
function libelleClient(c) {
  return [c.nom.toUpperCase(), c.prenom].filter(Boolean).join(' ');
}
function listeResultats(ul, clients, onPick, vide) {
  ul.innerHTML = '';
  if (!clients.length) {
    const li = document.createElement('li'); li.className = 'none'; li.textContent = vide; ul.appendChild(li); return;
  }
  for (const c of clients) {
    const li = document.createElement('li');
    const b = document.createElement('strong'); b.textContent = libelleClient(c);
    const sm = document.createElement('small');
    const autres = (c.personnes || []).filter((p) => p !== [c.prenom, c.nom].filter(Boolean).join(' '));
    sm.textContent = [c.telephone, c.nb_photos ? c.nb_photos + ' photo' + (c.nb_photos > 1 ? 's' : '') : '',
      autres.length ? 'pour ' + autres.join(', ') : ''].filter(Boolean).join(' · ');
    li.append(b, sm);
    li.onclick = () => onPick(c);
    ul.appendChild(li);
  }
}
let chercheT = null;
$('clientSearch').oninput = () => {
  clearTimeout(chercheT);
  const q = $('clientSearch').value.trim();
  if (!q) { $('clientHits').hidden = true; return; }
  chercheT = setTimeout(async () => {
    try {
      const res = await api('/api/clients?q=' + encodeURIComponent(q));
      listeResultats($('clientHits'), res, (c) => {
        save.client = c; $('clientHits').hidden = true; $('clientSearch').value = ''; afficherClientChoisi();
      }, 'Aucun client : « + Nouveau client »');
      $('clientHits').hidden = false;
    } catch (e) { toast(e.message, true); }
  }, 200);
};
$('clientSearch').onblur = () => setTimeout(() => { $('clientHits').hidden = true; }, 200);
$('clientChange').onclick = () => { save.client = null; afficherClientChoisi(); $('clientSearch').focus(); };
$('newClientBtn').onclick = () => {
  save.nouveau = true; save.client = null;
  const q = $('clientSearch').value.trim();          // ce qui était cherché pré-remplit le nom ou le téléphone
  if (q && /\d/.test(q)) $('ncTel').value = q; else if (q) $('ncNom').value = q;
  afficherClientChoisi(); $('ncNom').focus();
};
$('newClientCancel').onclick = () => { save.nouveau = false; afficherClientChoisi(); };
$('lien').onchange = () => { $('personFields').hidden = $('lien').value === 'lui-même'; };

async function chargerLiens() {
  const a = await api('/api/archive');
  save.liens = a.liens;
  $('lien').innerHTML = '';
  for (const l of a.liens) {
    const o = document.createElement('option');
    o.value = l; o.textContent = l === 'lui-même' ? 'Le client lui-même' : l.charAt(0).toUpperCase() + l.slice(1);
    $('lien').appendChild(o);
  }
  $('archivePath').textContent = a.dossier;
}

$('saveBtn').onclick = async () => {
  if (!state.photo || !state.result) return;
  const corps = { photo: state.photo, lien: $('lien').value, retirer: $('retirerApres').checked };
  if (save.client) corps.client_id = save.client.id;
  else if (save.nouveau) corps.client = { nom: $('ncNom').value, prenom: $('ncPrenom').value, telephone: $('ncTel').value };
  else { toast('Choisir un client ou en créer un.', true); $('clientSearch').focus(); return; }
  if (corps.lien !== 'lui-même') {
    corps.prenom = $('pPrenom').value; corps.nom = $('pNom').value;
    if (!corps.prenom.trim()) { toast('Prénom de la personne photographiée ?', true); $('pPrenom').focus(); return; }
  }
  $('saveBtn').disabled = true;
  try {
    const r = await api('/api/enregistrer', jsonPost('POST', corps));
    toast('Enregistrée dans l\'archive du client.');
    save.client = null; save.nouveau = false;
    ['ncNom', 'ncPrenom', 'ncTel', 'pPrenom', 'pNom'].forEach((id) => { $(id).value = ''; });
    $('lien').value = 'lui-même'; $('personFields').hidden = true;
    afficherClientChoisi();
    if (r.retire) await oublierPhoto();
  } catch (e) { toast(e.message, true); }
  finally { $('saveBtn').disabled = false; }
};

// ---------- onglets ----------
function montrerOnglet(nom) {
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('is-active', b.dataset.tab === nom));
  $('atelierView').hidden = nom !== 'atelier';
  $('clientsView').hidden = nom !== 'clients';
  if (nom === 'clients') { chercherClients(); $('clientsSearch').focus(); }
}
document.querySelectorAll('#tabs button').forEach((b) => b.onclick = () => montrerOnglet(b.dataset.tab));

// ---------- clients ----------
const vueClients = { id: null };
let clientsT = null;
async function chercherClients() {
  try {
    const res = await api('/api/clients?q=' + encodeURIComponent($('clientsSearch').value.trim()));
    listeResultats($('clientList'), res, (c) => ouvrirClient(c.id),
      $('clientsSearch').value.trim() ? 'Aucun client trouvé.' : 'Aucun client pour l\'instant.');
    [...$('clientList').children].forEach((li, i) => li.classList.toggle('is-active', !!(res[i] && res[i].id === vueClients.id)));
  } catch (e) { toast(e.message, true); }
}
$('clientsSearch').oninput = () => { clearTimeout(clientsT); clientsT = setTimeout(chercherClients, 200); };

const dateFr = (t) => new Date(t * 1000).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });

function bouton(texte, classe, onclick) {
  const b = document.createElement('button');
  b.className = classe; const sp = document.createElement('span'); sp.textContent = texte; b.appendChild(sp);
  b.onclick = onclick; return b;
}

async function ouvrirClient(id) {
  vueClients.id = id;
  let c;
  try { c = await api('/api/clients/' + id); } catch (e) { toast(e.message, true); return; }
  const d = $('clientDetail'); d.innerHTML = '';
  const head = document.createElement('div'); head.className = 'client-head';
  const t = document.createElement('div');
  const h = document.createElement('h2'); h.textContent = libelleClient(c);
  const m = document.createElement('div'); m.className = 'meta';
  m.textContent = [c.telephone || 'pas de téléphone', 'client depuis le ' + dateFr(c.cree_le),
    c.photos.length + ' photo' + (c.photos.length > 1 ? 's' : '')].join(' · ');
  t.append(h, m);
  const act = document.createElement('div'); act.className = 'actions';
  act.append(bouton('Modifier', 'btn btn-small', () => modifierClient(c)));
  const del = bouton('Supprimer le client', 'btn-danger', async () => {
    if (!confirmer(del, 'Fiche et photos à la Corbeille ?')) return;
    try {
      await api('/api/clients/' + c.id, { method: 'DELETE' });
      toast('Client supprimé ; ses photos sont dans la Corbeille.');
      vueClients.id = null;
      $('clientDetail').innerHTML = '<div class="empty"><p>Client supprimé.</p></div>';
      chercherClients();
    } catch (e) { toast(e.message, true); }
  });
  act.append(del);
  head.append(t, act);
  d.appendChild(head);
  const edit = document.createElement('div'); edit.className = 'client-edit'; edit.id = 'clientEdit'; edit.hidden = true;
  d.appendChild(edit);

  const cards = document.createElement('div'); cards.className = 'cards';
  if (!c.photos.length) {
    const p = document.createElement('p'); p.className = 'muted'; p.textContent = 'Aucune photo enregistrée.'; d.appendChild(p);
  }
  for (const p of c.photos) {
    const card = document.createElement('div'); card.className = 'card';
    if (p.present) {
      const img = document.createElement('img'); img.alt = ''; img.loading = 'lazy';
      img.src = `/archive/${p.id}/identite?v=${Math.round(p.cree_le)}`;
      card.appendChild(img);
    } else {
      const miss = document.createElement('div'); miss.className = 'missing';
      miss.textContent = 'Dossier introuvable (déplacé ou supprimé hors de l\'application).';
      card.appendChild(miss);
    }
    const body = document.createElement('div'); body.className = 'card-body';
    const nom = document.createElement('strong'); nom.textContent = [p.prenom, p.nom].filter(Boolean).join(' ');
    const sm = document.createElement('small');
    sm.textContent = (p.lien === 'lui-même' ? 'le client' : p.lien) + ' · ' + dateFr(p.cree_le);
    const ac = document.createElement('div'); ac.className = 'card-actions';
    if (p.present) {
      ac.append(bouton('Imprimer 8', 'btn btn-small', () => imprimer(`/archive/${p.id}/planche_8?v=1`)),
        bouton('Imprimer 4 + portrait', 'btn btn-small', () => imprimer(`/archive/${p.id}/planche_4_portrait?v=1`)),
        bouton('Dossier', 'btn btn-small', () => api('/api/archive/ouvrir', jsonPost('POST', { photo_id: p.id })).catch((e) => toast(e.message, true))));
    }
    const sup = bouton('Supprimer', 'btn-danger', async () => {
      if (!confirmer(sup, 'À la Corbeille ?')) return;
      try {
        await api('/api/archive/photos/' + p.id, { method: 'DELETE' });
        toast('Photo mise à la Corbeille.');
        ouvrirClient(c.id); chercherClients();
      } catch (e) { toast(e.message, true); }
    });
    ac.append(sup);
    body.append(nom, sm, ac);
    card.appendChild(body);
    cards.appendChild(card);
  }
  d.appendChild(cards);
  [...$('clientList').children].forEach((li) => li.classList.remove('is-active'));
  chercherClients();
}

function modifierClient(c) {
  const e = $('clientEdit'); e.innerHTML = ''; e.hidden = false;
  const champ = (val, ph) => { const i = document.createElement('input'); i.className = 'input'; i.value = val; i.placeholder = ph; return i; };
  const n = champ(c.nom, 'Nom'), p = champ(c.prenom, 'Prénom'), t = champ(c.telephone, 'Téléphone : 20 123 456');
  const ok = bouton('Enregistrer', 'btn btn-primary btn-small', async () => {
    try {
      await api('/api/clients/' + c.id, jsonPost('PUT', { nom: n.value, prenom: p.value, telephone: t.value }));
      toast('Fiche mise à jour.'); ouvrirClient(c.id);
    } catch (err) { toast(err.message, true); }
  });
  e.append(n, p, t, ok, bouton('Annuler', 'btn btn-small', () => { e.hidden = true; }));
  n.focus();
}

$('archiveChoose').onclick = async () => {
  toast('Choisissez le dossier dans la fenêtre du Finder.');
  try {
    const r = await api('/api/archive/choisir', jsonPost('POST', {}));
    $('archivePath').textContent = r.dossier;
    if (!r.annule) toast('Les prochaines photos seront rangées dans ' + r.dossier);
  } catch (e) { toast(e.message, true); }
};
$('archiveOpen').onclick = () => api('/api/archive/ouvrir', jsonPost('POST', {})).catch((e) => toast(e.message, true));

chargerLiens().catch((e) => toast(e.message, true));
afficherClientChoisi();
(function ongletDepuisAdresse() {                // #onglet=clients[&client=12] : ouvre la vue Clients
  const q = new URLSearchParams(location.hash.slice(1));
  if (q.get('onglet') === 'clients') {
    montrerOnglet('clients');
    if (/^\d+$/.test(q.get('client') || '')) ouvrirClient(Number(q.get('client')));
  }
})();

// ---------- serveur à jour ? (page relue sur le disque, code Python lu au démarrage) ----------
(function versionServeur() {
  const nom = document.title;
  const bandeau = document.createElement('div');
  bandeau.className = 'update'; bandeau.hidden = true;
  bandeau.innerHTML = '<span></span><button class="update-btn">Redémarrer</button>';
  document.body.appendChild(bandeau);
  const texte = bandeau.querySelector('span'), btn = bandeau.querySelector('button');
  async function etat() {
    try {
      const r = await fetch('/api/version', { cache: 'no-store' });
      if (r.status === 404) return { a_jour: false, ancien: true };     // serveur d'avant ce contrôle
      return await r.json();
    } catch (e) { return null; }
  }
  async function verifier() {
    const r = await etat();
    if (!r || r.a_jour) { bandeau.hidden = true; return; }
    texte.textContent = r.ancien
      ? nom + ' a été mis à jour : cliquez sur Quitter, puis rouvrez ' + nom + ' depuis le Bureau.'
      : nom + ' a été mis à jour. Redémarrez pour utiliser la nouvelle version.';
    btn.hidden = !!r.ancien;
    bandeau.hidden = false;
  }
  btn.onclick = async () => {
    btn.disabled = true; texte.textContent = 'Redémarrage…';
    try {
      await fetch('/api/redemarrer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    } catch (e) { /* le serveur s'arrête déjà */ }
    for (let i = 0; i < 40; i++) {                                    // 20 s au plus
      await new Promise((ok) => setTimeout(ok, 500));
      const r = await etat();
      if (r && r.a_jour) { location.reload(); return; }
    }
    btn.disabled = false; texte.textContent = 'Le redémarrage n\'a pas abouti : cliquez sur Quitter, puis rouvrez ' + nom + '.';
  };
  verifier();
  window.addEventListener('focus', verifier);
})();
