// Traduction des pages du hub (arabe), commune aux applications. Voir shared/langues.py.
//
// À charger après le catalogue de l'application (/langues/ar.js, qui définit
// window.CATALOGUE_AR) et avant le script de la page :
//   - I18N.langue : 'fr' ou 'ar' (retenue dans le navigateur) ; I18N.locale pour les dates ;
//   - I18N.tr(texte) : traduit un texte français (inchangé s'il n'est pas au catalogue) ;
//   - I18N.entetes(h) : ajoute l'en-tête X-Langue, pour que le serveur traduise ses messages ;
//   - I18N.bouton(el) : fait de `el` le bouton de changement de langue.
// En arabe, la page passe de droite à gauche et chaque texte affiché, y compris ceux ajoutés
// plus tard (messages, fiches…), est traduit s'il figure au catalogue.
(function () {
  'use strict';
  const CLE = 'retohub.langue';
  let langue = 'fr';
  try { langue = localStorage.getItem(CLE) === 'ar' ? 'ar' : 'fr'; } catch (e) { /* stockage indisponible */ }
  const demandee = new URLSearchParams(location.search).get('langue');     // ?langue=ar : marque-page
  if (demandee === 'ar' || demandee === 'fr') {
    langue = demandee;
    try { localStorage.setItem(CLE, langue); } catch (e) { /* stockage indisponible */ }
  }

  const cat = window.CATALOGUE_AR || {};
  const exact = new Map();
  const modeles = [];
  const echapper = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [k, v] of Object.entries(cat)) {
    if (k.includes('{}')) {
      const motif = '^' + k.split('{}').map(echapper).join('([\\s\\S]+?)') + '$';
      modeles.push({ fixe: k.replace(/\{\}/g, '').length, rx: new RegExp(motif), cible: v });
    } else {
      exact.set(k, v);
    }
  }
  modeles.sort((a, b) => b.fixe - a.fixe);       // le modèle le plus précis d'abord

  function remplir(cible, parties) {
    let i = 0;
    return cible.replace(/\{(\d*)\}/g, (m, n) => (n ? parties[Number(n) - 1] : parties[i++]) ?? '');
  }
  function morceau(g, p) {
    const t = traduire(g, p);
    if (t !== g || !g.includes(', ')) return t;
    const ms = g.split(', ').map((x) => traduire(x, p));
    return ms.join('، ');
  }
  function traduire(texte, p = 0) {
    if (langue !== 'ar' || typeof texte !== 'string' || p > 3) return texte;
    const t = texte.trim().replace(/\s+/g, ' ');     // espaces et retours à la ligne du HTML ignorés
    if (!t) return texte;
    const avant = texte.slice(0, texte.length - texte.trimStart().length);
    const apres = texte.slice(texte.trimEnd().length);
    if (exact.has(t)) return avant + exact.get(t) + apres;
    for (const m of modeles) {
      const r = m.rx.exec(t);
      if (r) return avant + remplir(m.cible, r.slice(1).map((g) => morceau(g, p + 1))) + apres;
    }
    return texte;
  }

  const ATTRIBUTS = ['placeholder', 'title', 'aria-label'];
  const IGNORER = new Set(['SCRIPT', 'STYLE', 'CODE', 'TEXTAREA']);
  function noeud(n) {
    if (n.nodeType === 3) {
      const p = n.parentNode;
      if (p && IGNORER.has(p.nodeName)) return;
      const t = traduire(n.nodeValue);
      if (t !== n.nodeValue) n.nodeValue = t;
    } else if (n.nodeType === 1) {
      if (IGNORER.has(n.nodeName)) return;
      for (const a of ATTRIBUTS) {
        if (n.hasAttribute(a)) {
          const v = n.getAttribute(a), t = traduire(v);
          if (t !== v) n.setAttribute(a, t);
        }
      }
      for (const c of n.childNodes) noeud(c);
    }
  }

  const I18N = {
    langue,
    locale: langue === 'ar' ? 'ar-TN' : 'fr-FR',
    tr: (t) => traduire(t),
    liste: (xs) => xs.join(langue === 'ar' ? '، ' : ', '),
    // Isole un nom, un numéro ou un fichier dans une phrase : en arabe, l'algorithme
    // bidirectionnel ne le mélange plus aux mots voisins (caractères invisibles FSI / PDI).
    iso: (s) => '\u2068' + s + '\u2069',
    entetes: (h) => Object.assign({ 'X-Langue': langue }, h || {}),
    changer(l) {
      try { localStorage.setItem(CLE, l); } catch (e) { /* stockage indisponible */ }
      location.reload();                         // tout est recomposé dans la nouvelle langue
    },
    bouton(el) {
      el.textContent = langue === 'ar' ? 'Français' : 'العربية';
      el.lang = langue === 'ar' ? 'fr' : 'ar';
      el.title = langue === 'ar' ? 'Afficher en français' : 'عرض الواجهة بالعربية';
      el.onclick = () => I18N.changer(langue === 'ar' ? 'fr' : 'ar');
    },
  };
  window.I18N = I18N;

  if (langue !== 'ar') return;
  document.documentElement.lang = 'ar';
  document.documentElement.dir = 'rtl';
  document.title = traduire(document.title);
  noeud(document.body);
  new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'characterData') noeud(m.target);
      else if (m.type === 'attributes') noeud(m.target);
      else m.addedNodes.forEach(noeud);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true,
    attributes: true, attributeFilter: ATTRIBUTS });
})();
