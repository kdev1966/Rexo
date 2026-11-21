"""Traduction des interfaces du hub (arabe), commune aux applications.

Chaque application fournit un catalogue JSON : les clés sont les textes français tels qu'ils
s'affichent, avec `{}` à la place de chaque partie variable ; les valeurs sont les textes
traduits, où `{}` reprend les parties variables dans l'ordre, et `{1}`, `{2}`… dans un autre
ordre si la phrase l'exige.

    "{} et ses planches sont dans la Corbeille." : "{} وأوراقها في سلة المهملات."

Un texte absent du catalogue reste en français : rien ne casse. Les parties variables sont
elles-mêmes traduites si elles figurent au catalogue (« enfant » dans « Youssef (enfant) »),
y compris une liste séparée par des virgules.

Le même catalogue sert à la page (shared/web/langues.js) et au serveur (ce module), qui
traduit ses messages quand la page envoie l'en-tête « X-Langue: ar ». Il réunit le catalogue
commun du hub (shared/web/ar.json : boutons et messages des outils communs, phrases générales)
et celui de l'application, qui l'emporte pour un même texte.
"""

import json
import re
from pathlib import Path

LANGUES = ('fr', 'ar')
VIRGULE_AR = '، '


def fusionner(chemins):
    """Catalogues réunis dans l'ordre (le dernier l'emporte pour un même texte) ; un catalogue
    absent est ignoré."""
    cat = {}
    for c in chemins:
        c = Path(c)
        if c.is_file():
            cat.update(json.loads(c.read_text(encoding='utf-8')))
    return cat


class Catalogue:
    def __init__(self, chemins):
        self.chemins = [Path(c) for c in (chemins if isinstance(chemins, (list, tuple)) else [chemins])]
        self._exact, self._modeles, self._date = {}, [], None

    def _charger(self):
        date = tuple(c.stat().st_mtime_ns if c.is_file() else 0 for c in self.chemins)
        if date == self._date:
            return
        cat = fusionner(self.chemins)
        self._exact = {k: v for k, v in cat.items() if '{}' not in k}
        modeles = []
        for k, v in cat.items():
            if '{}' in k:
                motif = re.escape(k).replace(re.escape('{}'), '(.+?)')
                fixe = len(k.replace('{}', ''))
                modeles.append((fixe, re.compile(motif, re.S), v))
        modeles.sort(key=lambda m: -m[0])            # le modèle le plus précis d'abord
        self._modeles = [(rx, v) for _, rx, v in modeles]
        self._date = date

    def traduire(self, texte, profondeur=0):
        """Texte français -> arabe ; inchangé s'il n'est pas au catalogue."""
        if not isinstance(texte, str) or not texte.strip() or profondeur > 3:
            return texte
        self._charger()
        t = ' '.join(texte.split())              # espaces et retours à la ligne ignorés
        avant, apres = texte[:len(texte) - len(texte.lstrip())], texte[len(texte.rstrip()):]
        if t in self._exact:
            return avant + self._exact[t] + apres
        for rx, cible in self._modeles:
            m = rx.fullmatch(t)
            if m:
                parties = [self._morceau(g, profondeur + 1) for g in m.groups()]
                return avant + remplir(cible, parties) + apres
        return texte

    def _morceau(self, g, profondeur):
        t = self.traduire(g, profondeur)
        if t != g or ', ' not in g:
            return t
        morceaux = [self.traduire(x, profondeur) for x in g.split(', ')]
        return VIRGULE_AR.join(morceaux) if morceaux != g.split(', ') else g

    def traduire_json(self, obj, cles=('error', 'methode', 'fond', 'avertissements')):
        """Traduit, dans une réponse JSON, les messages destinés à l'utilisateur (jamais les
        noms, chemins ou valeurs)."""
        if isinstance(obj, dict):
            return {k: (self._valeur(v) if k in cles else self.traduire_json(v, cles)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.traduire_json(v, cles) for v in obj]
        return obj

    def _valeur(self, v):
        if isinstance(v, str):
            return self.traduire(v)
        if isinstance(v, list):
            return [self.traduire(x) if isinstance(x, str) else x for x in v]
        return v


def remplir(cible, parties):
    """Place les parties variables : {1}, {2}… par numéro, {} dans l'ordre."""
    def numero(m):
        i = int(m.group(1)) - 1
        return parties[i] if 0 <= i < len(parties) else m.group(0)
    texte = re.sub(r'\{(\d+)\}', numero, cible)
    suite = iter(parties)
    return re.sub(r'\{\}', lambda m: next(suite, ''), texte)
