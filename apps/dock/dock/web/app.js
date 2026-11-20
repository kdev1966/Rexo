'use strict';

const $ = (id) => document.getElementById(id);
const tr = (t) => I18N.tr(t);
const state = {
  catalogue: [], filtre: 'nouveaux', sel: new Set(), dernier: null,
  signature: '', importNumero: 0, importEnCours: false, etat: null,
  nomsSeances: {},                         // nom tapé pour chaque séance proposée (clé : 1re photo)
  vue: 'telephone', seances: [], seance: null, photosSeance: [], ecartees: [], filtreTri: 'toutes', triVersion: -1,
  selTri: new Set(), dernierTri: null,
};
const ECART_SEANCE = 3 * 3600 * 1000;      // comme coeur.ECART_SEANCE

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
function nomDossier(nom, d) {
  d = d || new Date();
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
  suivreTri(e.tri);
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
    if (img.dataset.photo) nettes.observe(img);
  }
}, { rootMargin: '600px' });

// Vignette nette, tirée de l'original par le serveur (vidéo : image à 1 s) : demandée seulement
// pour les éléments visibles, un à la fois ; la petite vignette du téléphone reste en attendant.
const nettes = new IntersectionObserver((vues) => {
  for (const v of vues) {
    const img = v.target;
    img._visible = v.isIntersecting;
    if (v.isIntersecting) fileNettes.push(img);
  }
  suivanteNette();
}, { rootMargin: '200px' });
const fileNettes = [];
let netteEnCours = false;
function suivanteNette() {
  if (netteEnCours) return;
  let img;
  while ((img = fileNettes.shift()) && (!img.isConnected || !img._visible || img._nette)) { /* plus visible ou déjà nette */ }
  if (!img) return;
  netteEnCours = true;
  const grande = new Image();
  grande.onload = () => { img.src = grande.src; img._nette = true; nettes.unobserve(img); netteEnCours = false; suivanteNette(); };
  grande.onerror = () => { netteEnCours = false; if (!state.importEnCours) suivanteNette(); else fileNettes.unshift(img); };
  grande.src = '/vignette?nette=1&cle=' + encodeURIComponent(img.dataset.cle);
}

function afficher() {
  const tous = state.catalogue, nouveaux = tous.filter((x) => !x.importe);
  $('nbTous').textContent = tous.length.toLocaleString(I18N.locale);
  $('nbNouveaux').textContent = nouveaux.length.toLocaleString(I18N.locale);
  const liste = visibles();
  const grille = $('grille');
  grille.innerHTML = '';
  observateur.disconnect();
  nettes.disconnect(); fileNettes.length = 0;
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
  img.dataset.photo = '1';                  // photos, RAW et vidéos : vignette nette demandée
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
  propositions(choisis);
  $('importBtn').disabled = !n || !pret || state.importEnCours;
  $('marquerBtn').disabled = !n || !pret || state.importEnCours;
  $('importBtn').querySelector('span').textContent = n ? remplir('Importer {} éléments', I18N.iso(n)) : tr('Importer la sélection');
}

// ---------- séances proposées (comme coeur.decouper_seances) ----------
function decouper(choisis) {
  const datees = choisis.filter((x) => x.date).sort((a, b) => new Date(a.date) - new Date(b.date));
  const groupes = [];
  for (const x of datees) {
    const g = groupes[groupes.length - 1];
    if (g && new Date(x.date) - new Date(g[g.length - 1].date) <= ECART_SEANCE) g.push(x); else groupes.push([x]);
  }
  const sansDate = choisis.filter((x) => !x.date);
  if (sansDate.length) groupes.length ? groupes[groupes.length - 1].push(...sansDate) : groupes.push(sansDate);
  return groupes;
}

function propositions(choisis) {
  const box = $('propositions');
  let groupes = decouper(choisis);
  if (state.uneSeule && groupes.length > 1) groupes = [groupes.flat()];
  if (!choisis.length) state.uneSeule = false;
  state.groupes = groupes;
  $('seancesVide').hidden = groupes.length > 0;
  box.innerHTML = '';
  for (const g of groupes) {
    const cle = g[0].cle;
    const debut = g[0].date ? new Date(g[0].date) : new Date();
    const fin = g[g.length - 1].date ? new Date(g[g.length - 1].date) : debut;
    const div = document.createElement('div');
    div.className = 'proposition';
    const heures = (d) => d.toLocaleTimeString(I18N.locale, { hour: '2-digit', minute: '2-digit' });
    const titre = document.createElement('small');
    titre.textContent = nomJour(jourDe(g[0].date)) + ' · ' + I18N.iso(heures(debut) + (fin - debut > 60000 ? ' – ' + heures(fin) : ''))
      + ' · ' + remplir(g.length > 1 ? '{} éléments' : '{} élément', I18N.iso(g.length));
    const input = document.createElement('input');
    input.className = 'input'; input.maxLength = 80; input.autocomplete = 'off';
    input.placeholder = tr('Nom de la séance (facultatif)');
    input.value = state.nomsSeances[cle] || '';
    const dossier = document.createElement('div');
    dossier.className = 'dossier';
    const maj = () => { dossier.innerHTML = ''; dossier.append(tr('Dossier :') + ' '); const s = document.createElement('strong'); s.textContent = I18N.iso(nomDossier(input.value, debut)); dossier.append(s); };
    input.oninput = () => { state.nomsSeances[cle] = input.value; maj(); };
    maj();
    div.append(titre, input, dossier);
    box.appendChild(div);
  }
  if (groupes.length > 1) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'lien';
    b.textContent = remplir('Tout mettre dans une seule séance ({} séances proposées)', I18N.iso(groupes.length));
    b.onclick = () => { state.uneSeule = true; resume(); };
    const actions = document.createElement('div'); actions.className = 'proposition-actions'; actions.appendChild(b);
    box.appendChild(actions);
  }
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
  if (avant && !imp.en_cours) { afficherResultat(imp); suivanteNette(); }
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
  for (const s of r.seances) {
    const ligne = p(remplir('Dossier : {}', I18N.iso(s.nom_dossier)) + (r.seances.length > 1 ? ' (' + I18N.iso(s.importes) + ')' : ''));
    const b = document.createElement('button');
    b.className = 'lien'; b.type = 'button'; b.textContent = tr('Ouvrir');
    b.style.marginInlineStart = '8px';
    b.onclick = () => api('/api/montrer', jsonPost({ seance: s.nom_dossier })).catch((e) => toast(e.message, true));
    ligne.appendChild(b);
    if (s.echecs.length) {
      box.classList.add('has-errors');
      p(tr('Restés sur le téléphone, à refaire :'));
      const ul = document.createElement('ul');
      for (const x of s.echecs) { const li = document.createElement('li'); li.textContent = I18N.iso(x.nom) + ' : ' + x.raison; ul.appendChild(li); }
      box.appendChild(ul);
    }
  }
  if (r.miroir) {
    if (r.miroir.absent) { box.classList.add('has-errors'); p(tr('Seconde copie non faite : disque débranché.')); }
    else if (r.miroir.echecs.length) { box.classList.add('has-errors'); p(remplir('Seconde copie : {} fichiers en échec.', I18N.iso(r.miroir.echecs.length))); }
    else p(remplir('Seconde copie faite ({} nouveaux fichiers).', I18N.iso(r.miroir.copies)));
  }
  if (r.importes) p(tr('L\'aide au tri analyse ces photos en arrière-plan : onglet « Séances ».'));
  state.nomsSeances = {}; state.uneSeule = false;
  state.sel.clear();
  state.signature = '';                 // relit le catalogue : les photos importées passent en « déjà importé »
}

$('importBtn').onclick = async () => {
  try {
    $('result').hidden = true;
    const seances = (state.groupes || []).map((g) => ({ nom: state.nomsSeances[g[0].cle] || '', cles: g.map((x) => x.cle) }));
    await api('/api/importer', jsonPost({ seances }));
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

// ---------- vues : Téléphone / Séances ----------
function montrerVue(v) {
  state.vue = v;
  for (const b of document.querySelectorAll('#tabs button')) b.classList.toggle('is-active', b.dataset.vue === v);
  $('vueTelephone').hidden = v !== 'telephone';
  $('vueSeances').hidden = v !== 'seances';
  if (v === 'seances') chargerSeances();
  try { history.replaceState(null, '', '#vue=' + v); } catch (e) { /* adresse inchangée */ }
}
for (const b of document.querySelectorAll('#tabs button')) b.onclick = () => montrerVue(b.dataset.vue);

// ---------- aide au tri : séances importées ----------
function suivreTri(t) {
  if (!t) return;
  $('trierEtat').textContent = t.en_cours
    ? (t.seance ? remplir('Analyse de « {} » : {} sur {}…', I18N.iso(t.seance), I18N.iso(Math.min(t.fait + 1, t.total || 1)), I18N.iso(t.total || 1)) : tr('Analyse en attente…'))
    : '';
  if (t.version !== state.triVersion) {
    state.triVersion = t.version;
    chargerSeances();
  } else if (t.en_cours && state.vue === 'seances' && t.seance === state.seance && !(state._dernierTri > Date.now() - 4000)) {
    state._dernierTri = Date.now();
    chargerPhotos();                   // résultats de la séance affichée, au fil de l'analyse
  }
}

async function chargerSeances() {
  try { state.seances = await api('/api/seances'); } catch (e) { return; }
  const total = state.seances.reduce((s, x) => s + x.a_trier, 0);
  $('nbATrierTotal').hidden = !total; $('nbATrierTotal').textContent = I18N.iso(total);
  const ul = $('listeSeances'); ul.innerHTML = '';
  if (state.seance && !state.seances.some((s) => s.nom === state.seance)) state.seance = null;
  if (!state.seance && state.seances.length) state.seance = state.seances[0].nom;
  for (const s of state.seances) {
    const li = document.createElement('li');
    const b = document.createElement('button'); b.type = 'button';
    b.className = s.nom === state.seance ? 'is-active' : '';
    const nom = document.createElement('strong'); nom.textContent = I18N.iso(s.nom);
    const info = document.createElement('small');
    info.textContent = remplir(s.photos > 1 ? '{} photos' : '{} photo', I18N.iso(s.photos));
    if (s.analysees < s.photos) info.textContent += ' · ' + remplir('{} à analyser', I18N.iso(s.photos - s.analysees));
    if (s.a_trier) { const bb = document.createElement('b'); bb.textContent = ' · ' + remplir('{} à trier', I18N.iso(s.a_trier)); info.appendChild(bb); }
    b.append(nom, info);
    b.onclick = () => { state.seance = s.nom; state.selTri.clear(); chargerSeances(); };
    li.appendChild(b); ul.appendChild(li);
  }
  $('seanceOuvrir').disabled = $('seanceAnalyser').disabled = !state.seance;
  await chargerPhotos();
}

async function chargerPhotos() {
  if (!state.seance) { state.photosSeance = []; state.ecartees = []; afficherSeance(); return; }
  try {
    const r = await api('/api/seances/photos?seance=' + encodeURIComponent(state.seance));
    state.photosSeance = r.photos; state.ecartees = r.ecartees;
  } catch (e) { state.photosSeance = []; state.ecartees = []; }
  afficherSeance();
}

const ICONE_AGRANDIR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>';
const urlPhoto = (nom, grand, ecartee) => '/seance/vignette?seance=' + encodeURIComponent(state.seance) + '&nom=' + encodeURIComponent(nom)
  + (grand ? '&grand=1' : '') + (ecartee ? '&ecartee=1' : '');

function listeSeance() {
  const f = state.filtreTri;
  if (f === 'ecartees') return (state.ecartees || []).map((x) => Object.assign({ ecartee: true }, x));
  return state.photosSeance.filter((p) => f === 'toutes' || (f === 'a_trier' && p.a_trier) || (f === 'meilleures' && p.meilleure));
}

function badgesDe(p, box) {
  const badge = (txt, cls) => { const s = document.createElement('span'); s.className = 'badge ' + cls; s.textContent = txt; box.appendChild(s); };
  if (p.ecartee) { badge(tr('Écartée'), 'serie'); return; }
  if (p.meilleure) badge('★ ' + tr('Meilleure'), 'meilleure');
  if (p.doublon) badge(remplir('Série {}', I18N.iso(p.serie)), 'serie');
  if (p.floue) badge(tr('Floue'), 'floue');
  if (p.yeux_fermes) badge(tr('Yeux fermés ou plissés'), 'yeux');
  if (p.garde) badge(tr('Gardée'), 'garde');
  if (!p.analysee) badge('…', '');
}

function afficherSeance() {
  const ps = state.photosSeance;
  $('nbToutes').textContent = I18N.iso(ps.length);
  $('nbATrier').textContent = I18N.iso(ps.filter((p) => p.a_trier).length);
  $('nbMeilleures').textContent = I18N.iso(ps.filter((p) => p.meilleure).length);
  $('nbEcartees').textContent = I18N.iso((state.ecartees || []).length);
  const f = state.filtreTri;
  const liste = listeSeance();
  const noms = new Set(liste.map((p) => p.nom));
  for (const n of [...state.selTri]) if (!noms.has(n)) state.selTri.delete(n);
  const grille = $('grilleSeance'); grille.innerHTML = '';
  $('videSeance').hidden = liste.length > 0;
  if (!liste.length) {
    const vide = !state.seances.length ? ['Aucune séance importée', 'Importez des photos depuis l\'onglet « Téléphone ».']
      : f === 'a_trier' ? ['Rien à trier', 'Aucune photo floue, aux yeux fermés ou plissés, ou en double n\'a été trouvée.']
      : f === 'ecartees' ? ['Aucune photo écartée', 'Les photos écartées restent ici, dans le sous-dossier « Écartées » de la séance, jusqu\'à ce que vous les remettiez ou les mettiez à la Corbeille.']
      : ['Aucune photo', ''];
    $('videSeanceTitre').textContent = tr(vide[0]); $('videSeanceTexte').textContent = tr(vide[1]);
  }
  for (const p of liste) {
    const b = document.createElement('div');
    b.className = 'tuile' + (p.a_trier ? ' a-trier' : '');
    b.dataset.nom = p.nom;
    b.title = p.nom + (p.ecartee || p.analysee ? '' : ' · ' + tr('pas encore analysée'));
    const img = document.createElement('img'); img.alt = '';
    img.onload = () => img.classList.add('charge');
    img.loading = 'lazy';
    img.src = urlPhoto(p.nom, false, p.ecartee);
    const coche = document.createElement('span'); coche.className = 'coche';
    const agrandir = document.createElement('button');
    agrandir.type = 'button'; agrandir.className = 'agrandir'; agrandir.innerHTML = ICONE_AGRANDIR;
    agrandir.title = tr(p.serie ? 'Comparer la série' : 'Voir en grand');
    agrandir.onclick = (ev) => { ev.stopPropagation(); comparer(p); };
    const badges = document.createElement('div'); badges.className = 'badges';
    badgesDe(p, badges);
    b.append(img, coche, agrandir, badges);
    b.onclick = (ev) => choisirTri(p.nom, ev.shiftKey);
    grille.appendChild(b);
  }
  majSelTri();
}

function choisirTri(nom, plage) {
  const liste = listeSeance().map((p) => p.nom);
  if (plage && state.dernierTri && liste.includes(state.dernierTri)) {
    const [a, b] = [liste.indexOf(state.dernierTri), liste.indexOf(nom)].sort((m, n) => m - n);
    const ajouter = !state.selTri.has(nom);
    for (const n of liste.slice(a, b + 1)) ajouter ? state.selTri.add(n) : state.selTri.delete(n);
  } else {
    state.selTri.has(nom) ? state.selTri.delete(nom) : state.selTri.add(nom);
  }
  state.dernierTri = nom;
  majSelTri();
}

function majSelTri() {
  for (const el of document.querySelectorAll('#grilleSeance .tuile')) el.classList.toggle('is-sel', state.selTri.has(el.dataset.nom));
  const n = state.selTri.size, ecartees = state.filtreTri === 'ecartees';
  $('actionsTri').hidden = !n;
  $('triSelTexte').textContent = remplir(n > 1 ? '{} photos choisies' : '{} photo choisie', I18N.iso(n));
  for (const b of document.querySelectorAll('#actionsTri [data-action]')) {
    const a = b.dataset.action;
    b.hidden = ecartees ? !(a === 'remettre' || a === 'corbeille') : a === 'remettre';
  }
  const garder = document.querySelector('#actionsTri [data-action="garder"]');
  const tousGardes = n && [...state.selTri].every((nom) => (state.photosSeance.find((p) => p.nom === nom) || {}).garde);
  garder.dataset.inverse = tousGardes ? '1' : '';
  if (!garder._arme) garder.querySelector('span').textContent = tr(tousGardes ? 'Ne plus garder' : 'Garder');
}

async function agir(action, noms, bouton) {
  const ecartees = state.filtreTri === 'ecartees';
  if (action === 'corbeille' && bouton && !confirmer(bouton, noms.length > 1 ? remplir('Confirmer : {} à la Corbeille ?', I18N.iso(noms.length)) : 'Confirmer : à la Corbeille ?')) return false;
  if (action === 'garder' && bouton && bouton.dataset.inverse) action = 'ne_plus_garder';
  try {
    const r = await api('/api/seances/action', jsonPost({ seance: state.seance, noms, action, ecartees }));
    const messages = { garder: '{} gardée(s) : elles sortent de « À trier ».', ne_plus_garder: '{} de nouveau à trier si signalée(s).',
      ecarter: '{} écartée(s) : sous-dossier « Écartées ».', remettre: '{} remise(s) dans la séance.',
      corbeille: '{} dans la Corbeille (récupérable tant qu\'elle n\'est pas vidée).' };
    toast(remplir(messages[action], I18N.iso(r.n)));
    for (const n of noms) state.selTri.delete(n);
    await chargerSeances();
    return true;
  } catch (e) { toast(e.message, true); return false; }
}

for (const b of document.querySelectorAll('#actionsTri [data-action]')) {
  b.onclick = () => agir(b.dataset.action, [...state.selTri], b);
}
$('triAucune').onclick = () => { state.selTri.clear(); majSelTri(); };
$('triTout').onclick = () => { for (const p of listeSeance()) state.selTri.add(p.nom); majSelTri(); };

// ---------- comparer une série (ou voir une photo en grand) ----------
function comparer(p) {
  const serie = p.serie && !p.ecartee ? state.photosSeance.filter((x) => x.serie === p.serie) : [p];
  $('comparerTitre').textContent = serie.length > 1
    ? remplir('Série {} · {} photos presque identiques', I18N.iso(p.serie), I18N.iso(serie.length))
    : I18N.iso(p.nom);
  const g = $('comparerGrille'); g.innerHTML = '';
  for (const x of serie) {
    const c = document.createElement('div');
    c.className = 'carte' + (x.meilleure ? ' meilleure' : '');
    const img = document.createElement('img'); img.alt = ''; img.src = urlPhoto(x.nom, true, x.ecartee);
    const pied = document.createElement('div'); pied.className = 'carte-pied';
    const badges = document.createElement('div'); badges.className = 'badges'; badgesDe(x, badges);
    const nom = document.createElement('small');
    nom.textContent = I18N.iso(x.nom) + (x.nettete != null ? ' · ' + remplir('netteté {}', I18N.iso(Math.round(x.nettete))) : '');
    const actions = document.createElement('div'); actions.className = 'carte-actions';
    const bouton = (libelle, action, cls) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-small ' + (cls || '');
      b.innerHTML = '<span></span>'; b.querySelector('span').textContent = tr(libelle);
      b.onclick = async () => {
        if (action === 'ouvrir') {
          api('/api/seances/ouvrir', jsonPost({ seance: state.seance, nom: x.nom, ecartee: !!x.ecartee })).catch((e) => toast(e.message, true));
          return;
        }
        if (await agir(action, [x.nom], b)) { c.remove(); if (!g.children.length) $('comparer').hidden = true; }
      };
      actions.appendChild(b);
    };
    if (x.ecartee) { bouton('Remettre', 'remettre'); }
    else {
      if (!x.garde && (x.a_trier || x.doublon)) bouton('Garder', 'garder');
      bouton('Écarter', 'ecarter');
    }
    bouton('Corbeille', 'corbeille', 'btn-danger');
    bouton('Ouvrir dans Aperçu', 'ouvrir');
    pied.append(badges, nom, actions);
    c.append(img, pied);
    g.appendChild(c);
  }
  $('comparer').hidden = false;
}
$('comparerFermer').onclick = () => { $('comparer').hidden = true; };
$('comparer').onclick = (ev) => { if (ev.target === $('comparer')) $('comparer').hidden = true; };
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') $('comparer').hidden = true; });

for (const b of document.querySelectorAll('#filtresTri button')) {
  b.onclick = () => {
    state.filtreTri = b.dataset.filtre;
    state.selTri.clear();
    for (const x of document.querySelectorAll('#filtresTri button')) x.classList.toggle('is-active', x === b);
    afficherSeance();
  };
}
$('seanceOuvrir').onclick = () => api('/api/montrer', jsonPost({ seance: state.seance })).catch((e) => toast(e.message, true));
$('seanceAnalyser').onclick = () => api('/api/seances/analyser', jsonPost({ seance: state.seance }))
  .then(() => toast(tr('Analyse demandée.'))).catch((e) => toast(e.message, true));

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
if (location.hash.includes('vue=seances')) montrerVue('seances');
(async function boucle() {
  await rafraichir();
  setTimeout(boucle, state.importEnCours ? 500 : 1500);
})();
