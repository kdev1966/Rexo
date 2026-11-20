'use strict';

const $ = (id) => document.getElementById(id);
const tr = (t) => I18N.tr(t);
const state = {
  catalogue: [], filtre: 'nouveaux', sel: new Set(), dernier: null,
  signature: '', importNumero: 0, importEnCours: false, etat: null,
};

// ---------- utilitaires ----------
async function api(url, opts) {
  opts = Object.assign({}, opts);
  opts.headers = I18N.entetes(opts.headers);
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ('Erreur ' + r.status));
  return data;
}
const jsonPost = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
function toast(msg, isErr) {
  const t = $('toast');
  t.textContent = msg; t.className = 'toast' + (isErr ? ' err' : ''); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 4500);
}
const remplir = (modele, ...parties) => { let i = 0; return tr(modele).replace(/\{\}/g, () => parties[i++] ?? ''); };
function taille(o) {
  const u = ['octets', 'Ko', 'Mo', 'Go']; let i = 0;
  while (o >= 1000 && i < u.length - 1) { o /= 1000; i++; }
  return I18N.iso((i ? o.toFixed(1) : Math.round(o)).toLocaleString(I18N.locale)) + ' ' + tr(u[i]);
}
const duree = (s) => { s = Math.round(s || 0); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
const jourDe = (iso) => (iso ? iso.slice(0, 10) : '');
function nomJour(j) {
  if (!j) return tr('Date inconnue');
  const d = new Date(j + 'T12:00:00');
  return d.toLocaleDateString(I18N.locale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}
// Même règle que coeur.nom_dossier_seance
function nomDossier(nom) {
  const d = new Date();
  const jour = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  const propre = nom.replace(/[\/:\\?%*|"<>]/g, '-').trim();
  return propre ? jour + ' ' + propre : jour;
}
// Confirmation par second clic (pas de fenêtre bloquante), comme dans Rexo ID
function confirmer(bouton, question) {
  const span = bouton.querySelector('span');
  if (bouton._arme) {
    clearTimeout(bouton._arme); bouton._arme = null;
    bouton.classList.remove('is-confirm'); span.textContent = bouton._libelle;
    return true;
  }
  bouton._libelle = span.textContent;
  span.textContent = tr(question); bouton.classList.add('is-confirm');
  bouton._arme = setTimeout(() => {
    bouton._arme = null; bouton.classList.remove('is-confirm'); span.textContent = bouton._libelle;
  }, 4000);
  return false;
}

// ---------- état de l'appareil ----------
const TEXTES = {
  attente: ['Aucun appareil', 'Branchez un iPhone', 'Avec son câble USB, sur cet ordinateur.'],
  lecture: ['Lecture de {}…', 'Lecture du téléphone…', 'La liste des photos arrive.'],
  verrouille: ['{} : déverrouillez-le', 'Déverrouillez l\'iPhone', 'Puis touchez « Se fier » sur l\'écran du téléphone si la question s\'affiche.'],
  pret: ['{}', '', ''],
  indisponible: ['Système non pris en charge', 'Pas encore disponible sur ce système', 'Rexo Dock lit pour l\'instant les iPhone sous macOS.'],
};

async function rafraichir() {
  let e;
  try { e = await api('/api/etat'); } catch (err) { return; }
  state.etat = e;
  const a = e.appareil, t = TEXTES[a.etat] || TEXTES.attente;
  $('device').className = 'device ' + a.etat;
  $('deviceText').textContent = remplir(t[0], I18N.iso(a.nom || 'iPhone'));
  if (a.etat !== 'pret') {
    $('videTitre').textContent = tr(t[1]); $('videTexte').textContent = tr(t[2]);
  }
  $('seancesChemin').textContent = I18N.iso(e.seances);
  const mc = $('miroirChemin');
  mc.textContent = e.miroir ? I18N.iso(e.miroir) + (e.miroir_present ? '' : ' — ' + tr('disque débranché')) : tr('aucune');
  mc.classList.toggle('absent', !!e.miroir && !e.miroir_present);
  $('miroirRetirer').hidden = !e.miroir;
  $('miroirChoisir').querySelector('span').textContent = tr(e.miroir ? 'Changer…' : 'Choisir…');

  if (e.signature !== state.signature && !e.import_.en_cours) {   // pas de grille recomposée à chaque fichier
    state.signature = e.signature;
    await chargerCatalogue(a.etat === 'pret');
  }
  suivreImport(e.import_);
}

async function chargerCatalogue(pret) {
  state.catalogue = pret ? await api('/api/catalogue').catch(() => []) : [];
  const cles = new Set(state.catalogue.map((x) => x.cle));
  for (const c of [...state.sel]) if (!cles.has(c)) state.sel.delete(c);
  afficher();
}

// ---------- grille ----------
function visibles() {
  return state.filtre === 'tous' ? state.catalogue : state.catalogue.filter((x) => !x.importe);
}

const observateur = new IntersectionObserver((vues) => {
  for (const v of vues) {
    if (!v.isIntersecting) continue;
    const img = v.target;
    observateur.unobserve(img);
    img.onload = () => img.classList.add('charge');
    img.src = '/vignette?cle=' + encodeURIComponent(img.dataset.cle);
  }
}, { rootMargin: '600px' });

function afficher() {
  const tous = state.catalogue, nouveaux = tous.filter((x) => !x.importe);
  $('nbTous').textContent = tous.length.toLocaleString(I18N.locale);
  $('nbNouveaux').textContent = nouveaux.length.toLocaleString(I18N.locale);
  const liste = visibles();
  const grille = $('grille');
  grille.innerHTML = '';
  observateur.disconnect();
  const pret = state.etat && state.etat.appareil.etat === 'pret';
  $('vide').hidden = pret && liste.length > 0;
  if (pret && !liste.length) {
    $('videTitre').textContent = tr(tous.length ? 'Tout est déjà importé' : 'Aucune photo sur l\'appareil');
    $('videTexte').textContent = tr(tous.length ? 'Choisissez « Tous » pour revoir les photos déjà importées.' : '');
  }
  if (!pret) { resume(); return; }

  const jours = new Map();
  for (const x of liste) {
    const j = jourDe(x.date);
    if (!jours.has(j)) jours.set(j, []);
    jours.get(j).push(x);
  }
  const frag = document.createDocumentFragment();
  for (const [j, items] of jours) {
    const tete = document.createElement('div');
    tete.className = 'jour';
    tete.innerHTML = '<h3></h3><small></small><button class="btn btn-small" type="button"><span></span></button>';
    tete.querySelector('h3').textContent = nomJour(j);
    tete.querySelector('small').textContent = remplir(items.length > 1 ? '{} éléments' : '{} élément', I18N.iso(items.length));
    const bj = tete.querySelector('button');
    bj.querySelector('span').textContent = tr('Choisir ce jour');
    bj.onclick = () => {
      const tousChoisis = items.every((x) => state.sel.has(x.cle));
      for (const x of items) tousChoisis ? state.sel.delete(x.cle) : state.sel.add(x.cle);
      majSelection();
    };
    const bloc = document.createElement('div');
    bloc.className = 'tuiles';
    for (const x of items) bloc.appendChild(tuile(x));
    frag.append(tete, bloc);
  }
  grille.appendChild(frag);
  majSelection();
}

function tuile(x) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'tuile' + (x.importe ? ' importe' : '');
  b.dataset.cle = x.cle;
  b.title = x.nom;
  const img = document.createElement('img');
  img.alt = ''; img.dataset.cle = x.cle;
  observateur.observe(img);
  const coche = document.createElement('span'); coche.className = 'coche';
  const badges = document.createElement('div'); badges.className = 'badges';
  const badge = (txt, cls) => { const s = document.createElement('span'); s.className = 'badge ' + (cls || ''); s.textContent = txt; badges.appendChild(s); };
  if (x.genre === 'video') badge(I18N.iso(duree(x.duree)), 'video');
  if (x.genre === 'raw') badge('RAW');
  if (x.rafale) badge(tr('Rafale'), 'rafale');
  if (x.importe) badge(tr('Déjà importé'), 'ok');
  b.append(img, coche, badges);
  b.onclick = (ev) => choisir(x.cle, ev.shiftKey);
  return b;
}

function choisir(cle, plage) {
  const liste = visibles().map((x) => x.cle);
  if (plage && state.dernier && liste.includes(state.dernier)) {
    const [a, b] = [liste.indexOf(state.dernier), liste.indexOf(cle)].sort((m, n) => m - n);
    const ajouter = !state.sel.has(cle);
    for (const c of liste.slice(a, b + 1)) ajouter ? state.sel.add(c) : state.sel.delete(c);
  } else {
    state.sel.has(cle) ? state.sel.delete(cle) : state.sel.add(cle);
  }
  state.dernier = cle;
  majSelection();
}

function majSelection() {
  for (const el of document.querySelectorAll('.tuile')) el.classList.toggle('is-sel', state.sel.has(el.dataset.cle));
  resume();
}

function resume() {
  const choisis = state.catalogue.filter((x) => state.sel.has(x.cle));
  const n = choisis.length, octets = choisis.reduce((s, x) => s + x.taille, 0);
  const pret = state.etat && state.etat.appareil.etat === 'pret';
  $('selResume').innerHTML = '';
  if (!n) {
    $('selResume').textContent = tr('Aucune photo choisie.');
  } else {
    const deja = choisis.filter((x) => x.importe).length;
    $('selResume').textContent = remplir('{} choisies · {}', I18N.iso(n), taille(octets))
      + (deja ? ' · ' + remplir('dont {} déjà importées', I18N.iso(deja)) : '');
  }
  $('importBtn').disabled = !n || !pret || state.importEnCours;
  $('marquerBtn').disabled = !n || !pret || state.importEnCours;
  $('importBtn').querySelector('span').textContent = n ? remplir('Importer {} éléments', I18N.iso(n)) : tr('Importer la sélection');
}

// ---------- import ----------
function suivreImport(imp) {
  const avant = state.importEnCours;
  state.importEnCours = imp.en_cours;
  $('progress').hidden = !imp.en_cours;
  if (imp.en_cours) {
    const pct = imp.total ? Math.round(100 * imp.fait / imp.total) : 0;
    $('progressBar').style.width = pct + '%';
    $('progressText').textContent = imp.etape === 'miroir'
      ? remplir('Seconde copie… {}', I18N.iso(imp.courant || ''))
      : remplir('{} sur {} · {}', I18N.iso(Math.min(imp.fait + 1, imp.total)), I18N.iso(imp.total), I18N.iso(imp.courant || ''));
  }
  if (avant && !imp.en_cours) afficherResultat(imp);
  if (avant !== imp.en_cours) resume();
}

function afficherResultat(imp) {
  const box = $('result');
  box.hidden = false; box.className = 'result'; box.innerHTML = '';
  const p = (t) => { const el = document.createElement('p'); el.textContent = t; box.appendChild(el); return el; };
  if (imp.erreur) {
    box.classList.add('is-error'); p(imp.erreur); return;
  }
  const r = imp.resultat;
  if (!r) return;
  p(remplir('{} sur {} fichiers importés et vérifiés.', I18N.iso(r.importes), I18N.iso(r.total)));
  p(remplir('Dossier : {}', I18N.iso(r.nom_dossier)));
  if (r.echecs.length) {
    box.classList.add('has-errors');
    p(tr('Restés sur le téléphone, à refaire :'));
    const ul = document.createElement('ul');
    for (const x of r.echecs) { const li = document.createElement('li'); li.textContent = I18N.iso(x.nom) + ' : ' + x.raison; ul.appendChild(li); }
    box.appendChild(ul);
  }
  if (r.miroir) {
    if (r.miroir.absent) { box.classList.add('has-errors'); p(tr('Seconde copie non faite : disque débranché.')); }
    else if (r.miroir.echecs.length) { box.classList.add('has-errors'); p(remplir('Seconde copie : {} fichiers en échec.', I18N.iso(r.miroir.echecs.length))); }
    else p(remplir('Seconde copie faite ({} nouveaux fichiers).', I18N.iso(r.miroir.copies)));
  }
  const b = document.createElement('button');
  b.className = 'btn btn-small'; b.type = 'button'; b.innerHTML = '<span></span>';
  b.querySelector('span').textContent = tr('Ouvrir le dossier');
  b.onclick = () => api('/api/montrer', jsonPost({ seance: r.nom_dossier })).catch((e) => toast(e.message, true));
  box.appendChild(b);
  state.sel.clear();
  state.signature = '';                 // relit le catalogue : les photos importées passent en « déjà importé »
}

$('importBtn').onclick = async () => {
  try {
    $('result').hidden = true;
    await api('/api/importer', jsonPost({ cles: [...state.sel], seance: $('seance').value }));
    state.importEnCours = true; resume();
    $('progress').hidden = false; $('progressBar').style.width = '0';
    $('progressText').textContent = tr('Préparation…');
  } catch (e) { toast(e.message, true); }
};

$('marquerBtn').onclick = async () => {
  const b = $('marquerBtn');
  if (!confirmer(b, 'Confirmer : marquer sans copier ?')) return;
  try {
    const r = await api('/api/marquer', jsonPost({ cles: [...state.sel] }));
    toast(remplir('{} éléments marqués comme déjà importés.', I18N.iso(r.marques)));
    state.sel.clear(); state.signature = '';
    rafraichir();
  } catch (e) { toast(e.message, true); }
};

// ---------- séance et dossiers ----------
function apercu() { $('seanceApercu').textContent = I18N.iso(nomDossier($('seance').value)); }
$('seance').addEventListener('input', apercu);
apercu();

$('seancesOuvrir').onclick = () => api('/api/montrer', jsonPost({})).catch((e) => toast(e.message, true));
$('seancesChoisir').onclick = async () => {
  try { const r = await api('/api/seances/choisir', jsonPost({})); if (r.ok) rafraichir(); } catch (e) { toast(e.message, true); }
};
$('miroirChoisir').onclick = async () => {
  try { const r = await api('/api/miroir/choisir', jsonPost({})); if (r.ok) rafraichir(); } catch (e) { toast(e.message, true); }
};
$('miroirRetirer').onclick = async () => {
  if (!confirmer($('miroirRetirer'), 'Confirmer ?')) return;
  try { await api('/api/miroir/retirer', jsonPost({})); rafraichir(); } catch (e) { toast(e.message, true); }
};

// ---------- barre d'outils ----------
for (const b of document.querySelectorAll('#filtres button')) {
  b.onclick = () => {
    state.filtre = b.dataset.filtre;
    for (const x of document.querySelectorAll('#filtres button')) x.classList.toggle('is-active', x === b);
    afficher();
  };
}
$('toutBtn').onclick = () => { for (const x of visibles()) state.sel.add(x.cle); majSelection(); };
$('rienBtn').onclick = () => { state.sel.clear(); majSelection(); };
$('actualiserBtn').onclick = () => api('/api/actualiser', jsonPost({})).then(() => { state.signature = ''; }).catch((e) => toast(e.message, true));

// ---------- quitter ----------
(function quitter() {
  const b = $('quitBtn');
  b.onclick = async () => {
    if (state.importEnCours && !confirmer(b, 'Arrêter l\'import ?')) return;
    try {
      await fetch('/api/quitter', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    } catch (e) { /* serveur déjà arrêté */ }
    $('stopped').hidden = false;
    window.close();
  };
})();

// ---------- serveur à jour ? (comme dans Rexo ID) ----------
(function versionServeur() {
  const nom = document.title;
  const bandeau = document.createElement('div');
  bandeau.className = 'update'; bandeau.hidden = true;
  bandeau.innerHTML = '<span></span><button class="update-btn">Redémarrer</button>';
  document.body.appendChild(bandeau);
  const texte = bandeau.querySelector('span'), btn = bandeau.querySelector('button');
  async function etat() {
    try { return await (await fetch('/api/version', { cache: 'no-store' })).json(); } catch (e) { return null; }
  }
  async function verifier() {
    const r = await etat();
    if (!r || r.a_jour) { bandeau.hidden = true; return; }
    texte.textContent = nom + ' a été mis à jour. Redémarrez pour utiliser la nouvelle version.';
    bandeau.hidden = false;
  }
  btn.onclick = async () => {
    if (state.importEnCours) { toast(tr('Attendez la fin de l\'import.'), true); return; }
    btn.disabled = true; texte.textContent = 'Redémarrage…';
    try { await fetch('/api/redemarrer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch (e) { /* arrêt */ }
    for (let i = 0; i < 40; i++) {
      await new Promise((ok) => setTimeout(ok, 500));
      const r = await etat();
      if (r && r.a_jour) { location.reload(); return; }
    }
    btn.disabled = false; texte.textContent = 'Le redémarrage n\'a pas abouti : cliquez sur Quitter, puis rouvrez ' + nom + '.';
  };
  verifier();
  window.addEventListener('focus', verifier);
})();

I18N.bouton($('langBtn'));
(async function boucle() {
  await rafraichir();
  setTimeout(boucle, state.importEnCours ? 500 : 1500);
})();
