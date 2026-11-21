"""Lecteur MTP (dock.mtp) sur un faux téléphone : structures PTP, parcours des dossiers,
données en plusieurs paquets, lecture seule, copie sans fichier tronqué."""

import struct
import tempfile
import unittest
from pathlib import Path

from dock import mtp
from dock.coeur import VIDEO
from dock.importer import ErreurAppareil


def ch(texte):
    if not texte:
        return b'\x00'
    t = (texte + '\0').encode('utf-16-le')
    return bytes([len(t) // 2]) + t


def tab(valeurs, taille=4):
    return struct.pack('<I%d%s' % (len(valeurs), 'I' if taille == 4 else 'H'), len(valeurs), *valeurs)


def info_appareil(modele='Telephone Test', serie='ABC123'):
    return (struct.pack('<HIH', 100, 6, 100) + ch('microsoft.com: 1.0') + struct.pack('<H', 0)
            + tab([0x1001], 2) + tab([], 2) + tab([], 2) + tab([], 2) + tab([0x3801], 2)
            + ch('Fabricant') + ch(modele) + ch('1.0') + ch(serie))


def info_objet(nom, fmt, taille=0, parent=0, date='20261022T212801'):
    return (struct.pack('<IHHIHIIIIIIIHII', 0x10001, fmt, 0, taille, 0, 0, 0, 0, 0, 0, 0, parent, 0, 0, 0)
            + ch(nom) + ch(date) + ch(date) + ch(''))


class FauxTelephone:
    """Répond aux commandes comme un Android : arborescence {handle: (nom, format, taille, parent)}."""

    def __init__(self, objets, contenu=b'', stockages=(0x10001,), paquet=7):
        self.objets, self.contenu, self.stock, self.paquet = objets, contenu, list(stockages), paquet
        self.commandes, self._file = [], []

    def envoyer(self, octets):
        _, _, code, tid = struct.unpack_from('<IHHI', octets)
        params = struct.unpack_from('<%dI' % ((len(octets) - 12) // 4), octets, 12)
        self.commandes.append(code)
        donnees, rc = self._repondre(code, params)
        if donnees is not None:
            brut = struct.pack('<IHHI', 12 + len(donnees), mtp.DONNEES, code, tid) + donnees
            # en-tête entier dans le premier paquet (USB : 512 octets au moins), puis de petits
            # paquets et un paquet vide, comme sur l'USB
            premier = 12 + self.paquet
            self._file += [brut[:premier]] + [brut[i:i + self.paquet] for i in range(premier, len(brut), self.paquet)] + [b'']
        self._file.append(struct.pack('<IHHI', 12, mtp.REPONSE, rc, tid))

    def recevoir(self):
        while True:
            p = self._file.pop(0)
            if p:
                return p

    def _repondre(self, code, p):
        if code == mtp.GET_DEVICE_INFO:
            return info_appareil(), mtp.OK
        if code in (mtp.OPEN_SESSION, mtp.CLOSE_SESSION):
            return None, mtp.OK
        if code == mtp.GET_STORAGE_IDS:
            return tab(self.stock), mtp.OK
        if code == mtp.GET_OBJECT_HANDLES:
            parent = 0 if p[2] == mtp.RACINE else p[2]
            return tab([h for h, o in self.objets.items() if o[3] == parent]), mtp.OK
        if code == mtp.GET_OBJECT_INFO:
            nom, fmt, taille, parent = self.objets[p[0]]
            return info_objet(nom, fmt, taille, parent), mtp.OK
        if code == mtp.GET_OBJECT_PROP_VALUE:
            if p[1] == mtp.PROP_DUREE:
                return struct.pack('<I', 12500), mtp.OK
            return None, 0x200A
        if code == mtp.GET_OBJECT:
            return self.contenu, mtp.OK
        if code == mtp.GET_THUMB:
            return b'\xff\xd8vignette', mtp.OK
        return None, 0x2005


ARBRE = {
    1: ('DCIM', mtp.DOSSIER, 0, 0),
    2: ('Download', mtp.DOSSIER, 0, 0),
    3: ('Camera', mtp.DOSSIER, 0, 1),
    4: ('IMG_20261022_212801.jpg', 0x3801, 2_000_000, 3),
    5: ('VID_20261022_212900.mp4', 0x300B, 9_000_000, 3),
    6: ('.thumbnails', mtp.DOSSIER, 0, 1),
    7: ('cache.jpg', 0x3801, 10, 6),
    8: ('facture.pdf', 0x3000, 10, 2),
    9: ('.nomedia', 0x3000, 0, 3),
    10: ('Pictures', mtp.DOSSIER, 0, 0),
    11: ('Screenshots', mtp.DOSSIER, 0, 10),
    12: ('Screenshot_1.png', 0x380B, 300_000, 11),
}


class TestStructures(unittest.TestCase):
    def test_info_appareil(self):
        i = mtp.info_appareil(info_appareil('Redmi Note 8', 'XYZ'))
        self.assertEqual((i['modele'], i['serie'], i['fabricant']), ('Redmi Note 8', 'XYZ', 'Fabricant'))

    def test_info_objet(self):
        i = mtp.info_objet(info_objet('IMG_1.jpg', 0x3801, 1234, 3))
        self.assertEqual((i['nom'], i['format'], i['taille'], i['parent']), ('IMG_1.jpg', 0x3801, 1234, 3))
        self.assertEqual(i['date'].strftime('%Y-%m-%d %H:%M:%S'), '2026-10-22 21:28:01')

    def test_dates(self):
        self.assertIsNotNone(mtp.date_ptp('20261022T212801.0Z'))
        self.assertIsNone(mtp.date_ptp(''))
        self.assertIsNone(mtp.date_ptp('2026xxxxT212801'))

    def test_lecture_seule(self):
        s = mtp.Session(FauxTelephone(ARBRE))
        for code in (0x100B, 0x100C, 0x100D, 0x101A):          # DeleteObject, SendObjectInfo, SendObject, MoveObject
            with self.assertRaises(mtp.ErreurMTP):
                s.transaction(code, 1)


class TestCatalogue(unittest.TestCase):
    def test_parcours(self):
        tel = FauxTelephone(ARBRE)
        s = mtp.Session(tel)
        self.assertEqual(s.ouvrir()['modele'], 'Telephone Test')
        objets = dict((f.nom, (h, f)) for h, f in s.catalogue())
        # DCIM et Pictures seulement, sans dossier caché ni fichier qui n'est pas une photo/vidéo
        self.assertEqual(sorted(objets), ['IMG_20261022_212801.jpg', 'Screenshot_1.png', 'VID_20261022_212900.mp4'])
        self.assertEqual(objets['IMG_20261022_212801.jpg'][1].taille, 2_000_000)
        video = objets['VID_20261022_212900.mp4'][1]
        self.assertEqual(video.duree, 12.5)
        self.assertEqual(objets['Screenshot_1.png'][0], 12)

    def test_verrouille(self):
        self.assertEqual(mtp.Session(FauxTelephone(ARBRE, stockages=())).catalogue(), [])


class TestPilote(unittest.TestCase):
    def pilote(self, contenu=b''):
        p = mtp.AppareilsMTP(lib=object())
        p._session = mtp.Session(FauxTelephone(ARBRE, contenu))
        p._info = p._session.ouvrir()
        p._lire()
        return p

    def test_etat(self):
        p = self.pilote()
        e = p.etat()
        self.assertEqual((e['etat'], e['nom'], e['identifiant'], e['marque']), ('pret', 'Telephone Test', 'ABC123', 'autre'))
        self.assertEqual(len(p.fichiers()), 3)

    def test_copier(self):
        contenu = bytes(range(256)) * 100
        p = self.pilote(contenu)
        f = next(x for x in p.fichiers() if x.nom.endswith('.jpg'))
        with tempfile.TemporaryDirectory() as d:
            chemin = p.copier(f, d, 'IMG.jpg')
            self.assertEqual(chemin.read_bytes(), contenu)
            self.assertEqual([x.name for x in Path(d).iterdir()], ['IMG.jpg'])
        self.assertEqual(p.vignette(f)[:2], b'\xff\xd8')

    def test_copie_interrompue(self):
        p = self.pilote(b'x' * 1000)
        f = p.fichiers()[0]

        def coupe():
            raise mtp.ErreurMTP('réception : LIBUSB_ERROR_NO_DEVICE', debranche=True)
        p._session.t.recevoir = coupe
        p._transport = None
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ErreurAppareil) as e:
                p.copier(f, d, 'IMG.jpg')
            self.assertTrue(e.exception.debranche)
            self.assertEqual(list(Path(d).iterdir()), [])         # pas de fichier tronqué
        self.assertEqual(p.etat()['etat'], 'attente')

    def test_genre_video(self):
        p = self.pilote()
        self.assertTrue(any(f.duree for f in p.fichiers() if f.nom.endswith('.mp4')))
        self.assertEqual(VIDEO, 'video')


if __name__ == '__main__':
    unittest.main()
