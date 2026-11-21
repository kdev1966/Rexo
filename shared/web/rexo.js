// Outils communs des pages Rexo (Rexo ID, Rexo Reveal, Rexo Dock…), servis sous /commun/rexo.js.
// À charger après le catalogue (/langues/ar.js) et /commun/langues.js, avant le script de la
// page, qui ne les redéfinit pas :
//   $(id)                       élément de la page
//   tr(texte)                   traduction (arabe) d'un texte français, sinon le texte
//   remplir(modele, …parties)   traduit `modele` puis remplace chaque {} par une partie
//   api(url, options)           appel au serveur : JSON renvoyé, Error avec le message (traduit) sinon
//   jsonPost(corps, methode)    options d'un envoi JSON (POST par défaut)
//   toast(message, erreur)      message en bas de la page, quelques secondes
//   confirmer(bouton, question) second clic pour confirmer (pas de fenêtre bloquante) : vrai au second
//   Rexo.quitter({occupe, question})       bouton « Quitter » : arrête le serveur ; un second clic
//                                          est demandé si occupe() (traitement, import en cours)
//   Rexo.versionServeur({occupe})          bandeau « mis à jour : redémarrer »
// Le bouton de langue (#langBtn) est branché ici.
'use strict';

const $ = (id) => document.getElementById(id);
const tr = (t) => I18N.tr(t);
const remplir = (modele, ...parties) => { let i = 0; return tr(modele).replace(/\{\}/g, () => parties[i++] ?? ''); };

async function api(url, opts) {
  opts = Object.assign({}, opts);
  opts.headers = I18N.entetes(opts.headers);     // le serveur traduit ses messages
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ('Erreur ' + r.status));
  return data;
}

const jsonPost = (corps, methode) => ({
  method: methode || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corps || {}),
});

function toast(msg, isErr) {
  const t = $('toast');
  t.textContent = msg; t.className = 'toast' + (isErr ? ' err' : ''); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 4000);
}

// Second clic pour confirmer : le libellé du bouton (son <span>) devient la question 4 s.
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

const Rexo = {
  // Bouton « Quitter » : arrête le serveur (et ses traitements) ; la page affiche #stopped.
  quitter({ occupe = () => false, question = 'Arrêter le traitement ?' } = {}) {
    const b = $('quitBtn');
    b.onclick = async () => {
      if (occupe() && !confirmer(b, question)) return;
      try {
        await fetch('/api/quitter', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      } catch (e) { /* serveur déjà arrêté */ }
      $('stopped').hidden = false;
      window.close();                  // ne ferme que les onglets ouverts par un script ; sinon l'écran reste
    };
  },

  // Serveur à jour ? La page est relue sur le disque, le code Python seulement au démarrage.
  versionServeur({ occupe = () => false } = {}) {
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
      if (occupe()) { toast(tr('Attendez la fin du traitement en cours.'), true); return; }
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
  },
};

if ($('langBtn')) I18N.bouton($('langBtn'));      // العربية / Français
