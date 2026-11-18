"""Base des clients et de leurs photos d'identité (SQLite, fournie avec Python).

Une seule base pour toute l'application, quel que soit le dossier où les photos sont
rangées (donnees/clients.sqlite) ; chaque photo garde le chemin de son dossier.

Un client (nom, prénom, téléphone) a plusieurs photos ; chaque photo a sa personne
photographiée (le client lui-même, un enfant, un conjoint…). La recherche porte sur les
noms et prénoms du client et des personnes photographiées, sans tenir compte des accents
ni des majuscules, ou sur le téléphone, quelle que soit son écriture.

Téléphones au format tunisien : 8 chiffres sans 0 initial (20 123 456), indicatif +216
(ou 00216), enregistrés sous la forme « 20 123 456 ». Un numéro étranger est accepté s'il
commence par + ou 00 ; il est gardé tel quel, espaces normalisés.
"""

import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from pathlib import Path

LIENS = ('lui-même', 'enfant', 'conjoint', 'parent', 'autre')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY,
    nom         TEXT NOT NULL,
    prenom      TEXT NOT NULL DEFAULT '',
    telephone   TEXT NOT NULL DEFAULT '',
    tel_chiffres TEXT NOT NULL DEFAULT '',
    cle         TEXT NOT NULL DEFAULT '',
    cree_le     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY,
    client_id   INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    nom         TEXT NOT NULL,
    prenom      TEXT NOT NULL DEFAULT '',
    lien        TEXT NOT NULL DEFAULT 'lui-même',
    cle         TEXT NOT NULL DEFAULT '',
    dossier     TEXT NOT NULL,
    cree_le     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS photos_client ON photos(client_id);
'''


class BaseError(ValueError):
    pass


def sans_accents(texte):
    t = unicodedata.normalize('NFKD', texte or '')
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def cle(*parties):
    """Texte de recherche : minuscules, sans accents, espaces simples."""
    return ' '.join(sans_accents(' '.join(p for p in parties if p)).split())


INDICATIF = '216'          # Tunisie
CHIFFRES_NATIONAUX = 8


def chiffres_tel(tel):
    """Chiffres du téléphone pour la recherche : numéro national tunisien (8 chiffres) quand
    il est reconnu, +216 et 00216 retirés ; sinon tous les chiffres, sans le 00 initial."""
    brut = (tel or '').strip()
    d = re.sub(r'\D', '', brut)
    if d.startswith('00'):
        d = d[2:]
    if d.startswith(INDICATIF) and len(d) == len(INDICATIF) + CHIFFRES_NATIONAUX:
        return d[len(INDICATIF):]
    return d


def chiffres_recherche(texte):
    """Chiffres cherchés : comme chiffres_tel, et l'indicatif retiré aussi d'un numéro
    incomplet (« +216 20 12 » -> « 2012 »)."""
    brut = (texte or '').strip()
    d = re.sub(r'\D', '', brut)
    international = brut.startswith('+') or d.startswith('00')
    if d.startswith('00'):
        d = d[2:]
    if (international or len(d) > CHIFFRES_NATIONAUX) and d.startswith(INDICATIF):
        return d[len(INDICATIF):]
    return d


def formater_tel(tel):
    """Forme enregistrée : « 20 123 456 » pour un numéro tunisien ; sinon le numéro tel quel
    (espaces normalisés). Lève BaseError si le numéro n'est pas valide."""
    brut = ' '.join((tel or '').split())
    if not brut:
        return ''
    if re.search(r'[^\d\s+().-]', brut):
        raise BaseError('téléphone : chiffres seulement (ex. 20 123 456)')
    d = chiffres_tel(brut)
    international = brut.startswith('+') or re.sub(r'\D', '', brut).startswith('00')
    tunisien = not international or re.sub(r'\D', '', brut).lstrip('0').startswith(INDICATIF)
    if tunisien:
        if len(d) != CHIFFRES_NATIONAUX:
            raise BaseError('numéro tunisien : 8 chiffres (ex. 20 123 456)')
        return '%s %s %s' % (d[:2], d[2:5], d[5:])
    if not 8 <= len(d) <= 15:
        raise BaseError('numéro étranger invalide (indicatif compris, ex. +33 6 12 34 56 78)')
    return brut


def _propre(texte, longueur=80):
    t = ' '.join((texte or '').split())
    if len(t) > longueur:
        raise BaseError('texte trop long (%d caractères au plus)' % longueur)
    return t


class Base:
    def __init__(self, chemin):
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connexion()) as c, c:
            c.executescript(SCHEMA)
            self._remettre_au_format(c)

    @staticmethod
    def _remettre_au_format(c):
        """Fiches enregistrées avant la règle actuelle : téléphone et clé de recherche recalculés."""
        for r in c.execute('SELECT id, telephone, tel_chiffres FROM clients').fetchall():
            try:
                tel = formater_tel(r['telephone'])
            except BaseError:
                tel = r['telephone']                # illisible : gardé tel quel
            if tel != r['telephone'] or chiffres_tel(tel) != r['tel_chiffres']:
                c.execute('UPDATE clients SET telephone=?, tel_chiffres=? WHERE id=?',
                          (tel, chiffres_tel(tel), r['id']))

    def _connexion(self):
        c = sqlite3.connect(str(self.chemin), timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys = ON')
        return c

    # ---------- clients ----------

    def creer_client(self, nom, prenom='', telephone=''):
        nom, prenom, telephone = _propre(nom), _propre(prenom), formater_tel(_propre(telephone, 30))
        if not nom:
            raise BaseError('le nom du client est obligatoire')
        with closing(self._connexion()) as c, c:
            cur = c.execute('INSERT INTO clients (nom, prenom, telephone, tel_chiffres, cle, cree_le) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            (nom, prenom, telephone, chiffres_tel(telephone), cle(nom, prenom), time.time()))
            return cur.lastrowid

    def modifier_client(self, client_id, nom, prenom='', telephone=''):
        nom, prenom, telephone = _propre(nom), _propre(prenom), formater_tel(_propre(telephone, 30))
        if not nom:
            raise BaseError('le nom du client est obligatoire')
        with closing(self._connexion()) as c, c:
            n = c.execute('UPDATE clients SET nom=?, prenom=?, telephone=?, tel_chiffres=?, cle=? WHERE id=?',
                          (nom, prenom, telephone, chiffres_tel(telephone), cle(nom, prenom),
                           client_id)).rowcount
        if not n:
            raise BaseError('client inconnu')

    def client(self, client_id):
        """Fiche du client et ses photos (les plus récentes d'abord), ou None."""
        with closing(self._connexion()) as c:
            r = c.execute('SELECT * FROM clients WHERE id=?', (client_id,)).fetchone()
            if r is None:
                return None
            photos = c.execute('SELECT * FROM photos WHERE client_id=? ORDER BY cree_le DESC',
                               (client_id,)).fetchall()
        fiche = _client(r)
        fiche['photos'] = [_photo(p) for p in photos]
        return fiche

    def chercher(self, texte, limite=50):
        """Clients dont le nom, le prénom, ceux des personnes photographiées ou le téléphone
        correspondent à `texte` ; sans texte, les clients les plus récents."""
        texte = (texte or '').strip()
        chiffres = re.sub(r'\D', '', texte)
        with closing(self._connexion()) as c:
            if not texte:
                rows = c.execute('SELECT * FROM clients ORDER BY cree_le DESC LIMIT ?', (limite,)).fetchall()
            elif len(chiffres) >= 3 and len(chiffres) >= len(re.sub(r'\s', '', texte)) - 1:
                # surtout des chiffres : téléphone (format national, n'importe quelle partie)
                rows = c.execute('SELECT * FROM clients WHERE tel_chiffres LIKE ? ORDER BY nom, prenom LIMIT ?',
                                 ('%' + chiffres_recherche(texte) + '%', limite)).fetchall()
            else:
                mots = cle(texte).split()
                cond = ' AND '.join(['(c.cle LIKE ? OR EXISTS (SELECT 1 FROM photos p '
                                     'WHERE p.client_id = c.id AND p.cle LIKE ?))'] * len(mots))
                args = [a for m in mots for a in ('%' + m + '%',) * 2]
                rows = c.execute('SELECT c.* FROM clients c WHERE ' + cond +
                                 ' ORDER BY c.nom, c.prenom LIMIT ?', args + [limite]).fetchall()
            res = []
            for r in rows:
                f = _client(r)
                ps = c.execute('SELECT prenom, nom, lien FROM photos WHERE client_id=? ORDER BY cree_le DESC',
                               (r['id'],)).fetchall()
                f['nb_photos'] = len(ps)
                f['personnes'] = sorted({' '.join(x for x in (p['prenom'], p['nom']) if x) for p in ps})
                res.append(f)
        return res

    def supprimer_client(self, client_id):
        """Supprime la fiche et ses photos de la base ; renvoie les dossiers des photos."""
        with closing(self._connexion()) as c, c:
            dossiers = [r['dossier'] for r in c.execute('SELECT dossier FROM photos WHERE client_id=?',
                                                           (client_id,))]
            if not c.execute('DELETE FROM clients WHERE id=?', (client_id,)).rowcount:
                raise BaseError('client inconnu')
        return dossiers

    # ---------- photos ----------

    def ajouter_photo(self, client_id, nom, prenom, lien, dossier):
        nom, prenom = _propre(nom), _propre(prenom)
        if lien not in LIENS:
            raise BaseError('lien inconnu : %s' % lien)
        if not nom and not prenom:
            raise BaseError('nom ou prénom de la personne photographiée obligatoire')
        with closing(self._connexion()) as c, c:
            if c.execute('SELECT 1 FROM clients WHERE id=?', (client_id,)).fetchone() is None:
                raise BaseError('client inconnu')
            cur = c.execute('INSERT INTO photos (client_id, nom, prenom, lien, cle, dossier, cree_le) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (client_id, nom, prenom, lien, cle(nom, prenom), str(dossier), time.time()))
            return cur.lastrowid

    def photo(self, photo_id):
        with closing(self._connexion()) as c:
            r = c.execute('SELECT * FROM photos WHERE id=?', (photo_id,)).fetchone()
        return _photo(r) if r else None

    def supprimer_photo(self, photo_id):
        """Supprime la photo de la base ; renvoie son dossier."""
        with closing(self._connexion()) as c, c:
            r = c.execute('SELECT dossier FROM photos WHERE id=?', (photo_id,)).fetchone()
            if r is None:
                raise BaseError('photo inconnue')
            c.execute('DELETE FROM photos WHERE id=?', (photo_id,))
        return r['dossier']


def _client(r):
    return {'id': r['id'], 'nom': r['nom'], 'prenom': r['prenom'], 'telephone': r['telephone'],
            'cree_le': r['cree_le']}


def _photo(r):
    return {'id': r['id'], 'client_id': r['client_id'], 'nom': r['nom'], 'prenom': r['prenom'],
            'lien': r['lien'], 'dossier': r['dossier'], 'cree_le': r['cree_le']}
