"""Accès à un iPhone sous macOS par ImageCaptureCore (pyobjc), comme le prototype Import Studio.

ImageCaptureCore répond par des rappels sur le fil principal : celui-ci doit faire tourner la
boucle d'événements (`tourner`). Les autres fils (serveur web) passent leurs demandes par
`vignette` et `copier`, qui sont exécutées sur le fil principal et attendues ici.

    AppareilsMac().demarrer()     cherche les appareils branchés en USB
    .etat()                       {'etat': attente|verrouille|lecture|pret, 'nom', 'identifiant'}
    .fichiers()                   FichierAppareil de l'appareil (photos, vidéos, retouches .AAE)
    .vignette(fichier)            JPEG réduit (octets)
    .copier(fichier, dossier, nom) -> Path      l'original (HEIC, RAW, MOV), jamais converti
    .actualiser()                 relit la liste (l'iPhone ne signale pas toujours les ajouts)

Rien n'est jamais supprimé de l'appareil : aucun appel de suppression n'existe dans ce module.

Essai en ligne de commande (iPhone branché, déverrouillé, « Se fier à cet ordinateur ») :
    .venv/bin/python -m dock.appareil_mac [--copier N --vers DOSSIER]
"""

import queue
import threading
import time
from concurrent.futures import Future, TimeoutError as DelaiDepasse
from datetime import datetime, timezone
from pathlib import Path

import ImageCaptureCore as IC
import objc
from Foundation import NSURL, NSDate, NSDefaultRunLoopMode, NSObject, NSRunLoop, NSThread

from .coeur import VIDEO, FichierAppareil, genre
from .importer import ErreurAppareil

ATTENTE, VERROUILLE, LECTURE, PRET = 'attente', 'verrouille', 'lecture', 'pret'
TAILLE_VIGNETTE = 320          # pixels, côté le plus long
DELAI_RELECTURE = 2.0          # ajouts ou retraits regroupés sur 2 s avant de relire la liste


def _date(nsdate):
    if nsdate is None:
        return None
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970(), timezone.utc).astimezone()


def _texte_erreur(erreur):
    try:
        return str(erreur.localizedDescription())
    except AttributeError:
        return str(erreur)


class _Delegue(NSObject, protocols=[objc.protocolNamed('ICDeviceBrowserDelegate'),
                                    objc.protocolNamed('ICCameraDeviceDelegate')]):
    """Reçoit les rappels d'ImageCaptureCore et les transmet à `self.pilote` (fil principal)."""

    # ICDeviceBrowserDelegate (BOOL codé « c » dans le protocole)
    @objc.typedSelector(b'v@:@@c')
    def deviceBrowser_didAddDevice_moreComing_(self, navigateur, appareil, encore):
        self.pilote._ajoute(appareil)

    @objc.typedSelector(b'v@:@@c')
    def deviceBrowser_didRemoveDevice_moreGoing_(self, navigateur, appareil, encore):
        self.pilote._retire(appareil)

    # ICDeviceDelegate
    def didRemoveDevice_(self, appareil):
        self.pilote._retire(appareil)

    def device_didOpenSessionWithError_(self, appareil, erreur):
        self.pilote._session_ouverte(appareil, erreur)

    def device_didCloseSessionWithError_(self, appareil, erreur):
        self.pilote._session_fermee(appareil)

    # ICCameraDeviceDelegate
    def deviceDidBecomeReadyWithCompleteContentCatalog_(self, appareil):
        self.pilote._lire_catalogue()

    def cameraDeviceDidRemoveAccessRestriction_(self, appareil):
        self.pilote._deverrouille()

    def cameraDeviceDidEnableAccessRestriction_(self, appareil):
        self.pilote._verrouille()

    def cameraDevice_didAddItems_(self, appareil, elements):
        self.pilote._changement()

    def cameraDevice_didRemoveItems_(self, appareil, elements):
        self.pilote._changement()

    # Requises par le protocole, sans usage ici
    def cameraDevice_didRenameItems_(self, appareil, elements):
        pass

    def cameraDeviceDidChangeCapability_(self, appareil):
        pass

    def cameraDevice_didReceivePTPEvent_(self, appareil, donnees):
        pass

    def cameraDevice_didReceiveThumbnail_forItem_error_(self, appareil, vignette, element, erreur):
        pass

    def cameraDevice_didReceiveMetadata_forItem_error_(self, appareil, meta, element, erreur):
        pass


class AppareilsMac:
    def __init__(self):
        self._verrou = threading.Lock()
        self._demandes = queue.Queue()
        self._navigateur = None
        self._delegue = None
        self._camera = None
        self._etat = ATTENTE
        self._fichiers = {}            # clé -> ICCameraFile
        self._liste = []               # FichierAppareil, dans l'ordre de l'appareil
        self._relire_a = None
        self._rouvrir = False

    # ---------- Fil principal ----------

    def demarrer(self):
        self._delegue = _Delegue.alloc().init()
        self._delegue.pilote = self
        self._navigateur = IC.ICDeviceBrowser.alloc().init()
        self._navigateur.setDelegate_(self._delegue)
        self._navigateur.setBrowsedDeviceTypeMask_(IC.ICDeviceTypeMaskCamera | IC.ICDeviceLocationTypeMaskLocal)
        self._navigateur.start()
        return self

    def arreter(self):
        if self._camera is not None:
            self._camera.requestCloseSession()
        if self._navigateur is not None:
            self._navigateur.stop()

    def tourner(self, duree=None, jusqua=None):
        """Fait tourner la boucle d'événements (fil principal) pendant `duree` secondes, ou
        jusqu'à ce que `jusqua()` soit vrai, ou sans fin."""
        fin = None if duree is None else time.monotonic() + duree
        while fin is None or time.monotonic() < fin:
            if jusqua is not None and jusqua():
                return True
            self._un_tour()
        return jusqua() if jusqua is not None else True

    def _un_tour(self, pas=0.05):
        NSRunLoop.currentRunLoop().runMode_beforeDate_(NSDefaultRunLoopMode,
                                                       NSDate.dateWithTimeIntervalSinceNow_(pas))
        while True:
            try:
                action, futur = self._demandes.get_nowait()
            except queue.Empty:
                break
            self._lancer(action, futur)
        if self._relire_a is not None and time.monotonic() >= self._relire_a:
            self._relire_a = None
            if self._etat in (PRET, LECTURE):
                self._lire_catalogue()

    @staticmethod
    def _lancer(action, futur):
        """Exécute `action(futur)` ; elle remplit `futur` elle-même (rappel) ou lève."""
        try:
            action(futur)
        except Exception as e:           # noqa: BLE001 — transmis au fil qui attend
            if not futur.done():
                futur.set_exception(e)

    def _demander(self, action, delai):
        """Exécute `action` sur le fil principal et attend son résultat."""
        futur = Future()
        if NSThread.isMainThread():
            self._lancer(action, futur)
            if not self.tourner(duree=delai, jusqua=futur.done):
                raise ErreurAppareil('pas de réponse de l\'appareil')
            return futur.result()
        self._demandes.put((action, futur))
        try:
            return futur.result(timeout=delai)
        except DelaiDepasse:
            raise ErreurAppareil('pas de réponse de l\'appareil') from None

    def _poser(self, etat):
        with self._verrou:
            self._etat = etat

    def _ajoute(self, appareil):
        if self._camera is not None or not appareil.isKindOfClass_(IC.ICCameraDevice):
            return
        self._camera = appareil
        appareil.setDelegate_(self._delegue)
        # Originaux (HEIC, RAW, MOV), quel que soit le réglage « Transférer vers Mac ou PC » de l'iPhone
        appareil.setMediaPresentation_(IC.ICMediaPresentationOriginalAssets)
        self._poser(LECTURE)
        appareil.requestOpenSession()

    def _retire(self, appareil):
        if self._camera is None or appareil != self._camera:
            return
        self._camera = None
        with self._verrou:
            self._etat, self._fichiers, self._liste = ATTENTE, {}, []

    def _session_ouverte(self, appareil, erreur):
        if erreur is not None or appareil.isAccessRestrictedAppleDevice():
            self._poser(VERROUILLE)

    def _session_fermee(self, appareil):
        if self._rouvrir and appareil == self._camera:
            self._rouvrir = False
            self._camera.requestOpenSession()

    def _deverrouille(self):
        # Le signal « catalogue complet » ne revient pas toujours après un déverrouillage :
        # la liste est relue de toute façon après DELAI_RELECTURE.
        self._poser(LECTURE)
        self._changement()

    def _verrouille(self):
        self._poser(VERROUILLE)

    def _changement(self):
        self._relire_a = time.monotonic() + DELAI_RELECTURE

    def _lire_catalogue(self):
        cam = self._camera
        if cam is None:
            return
        if cam.isAccessRestrictedAppleDevice():
            self._poser(VERROUILLE)
            return
        fichiers, liste = {}, []
        for el in cam.mediaFiles() or []:
            if not el.isKindOfClass_(IC.ICCameraFile):
                continue
            nom = str(el.name() or 'sans-nom')
            f = FichierAppareil(nom, int(el.fileSize()), _date(el.creationDate()),
                                duree=float(el.duration()) if genre(nom) == VIDEO else None,
                                rafale=str(el.burstUUID()) if el.burstUUID() else None)
            fichiers[f.cle] = el
            liste.append(f)
        with self._verrou:
            self._fichiers, self._liste, self._etat = fichiers, liste, PRET

    # ---------- Depuis n'importe quel fil ----------

    def etat(self):
        cam = self._camera
        with self._verrou:
            etat = self._etat
        return {'etat': etat,
                'nom': str(cam.name()) if cam is not None and cam.name() else '',
                'identifiant': self.identifiant}

    @property
    def identifiant(self):
        """Même identifiant que le prototype, pour reprendre son registre."""
        cam = self._camera
        if cam is None:
            return ''
        return str(cam.serialNumberString() or cam.persistentIDString() or cam.name() or 'iphone')

    @property
    def nom(self):
        return self.etat()['nom'] or 'iPhone'

    def fichiers(self):
        with self._verrou:
            return list(self._liste)

    def _element(self, fichier):
        with self._verrou:
            el = self._fichiers.get(fichier.cle)
        if el is None:
            raise ErreurAppareil('%s n\'est plus sur l\'appareil' % fichier.nom, debranche=self._camera is None)
        return el

    def vignette(self, fichier, delai=30):
        el = self._element(fichier)

        def action(futur):
            def fini(donnees, erreur):
                if futur.done():
                    return
                if erreur is not None or donnees is None:
                    futur.set_exception(ErreurAppareil('vignette : %s' % _texte_erreur(erreur)))
                else:
                    futur.set_result(bytes(donnees))
            el.requestThumbnailDataWithOptions_completion_(
                {IC.ICImageSourceThumbnailMaxPixelSize: TAILLE_VIGNETTE}, fini)

        return self._demander(action, delai)

    def copier(self, fichier, dossier, nom, delai=1800):
        el = self._element(fichier)
        dossier = Path(dossier)

        def action(futur):
            def fini(nom_ecrit, erreur):
                if futur.done():
                    return
                if erreur is not None:
                    futur.set_exception(ErreurAppareil(_texte_erreur(erreur), debranche=self._camera is None))
                else:
                    futur.set_result(dossier / str(nom_ecrit or nom))
            options = {IC.ICDownloadsDirectoryURL: NSURL.fileURLWithPath_(str(dossier)),
                       IC.ICSaveAsFilename: nom,
                       IC.ICOverwrite: False}
            el.requestDownloadWithOptions_completion_(options, fini)

        return self._demander(action, delai)

    def actualiser(self):
        """Ferme et rouvre la session, comme un rebranchement du câble."""
        def action(futur):
            if self._camera is not None and self._etat in (PRET, VERROUILLE):
                self._poser(LECTURE)
                self._rouvrir = True
                self._camera.requestCloseSession()
            futur.set_result(None)
        self._demander(action, 10)


# ---------- Essai en ligne de commande ----------

def _essai():
    import argparse
    from collections import Counter

    from . import coeur
    from .importer import importer

    p = argparse.ArgumentParser(description='Essai de lecture d\'un iPhone (rien n\'est supprimé de l\'appareil).')
    p.add_argument('--attendre', type=float, default=60, help='secondes d\'attente de l\'appareil')
    p.add_argument('--copier', type=int, default=0, help='copie les N fichiers les plus récents')
    p.add_argument('--vers', type=Path, help='dossier où copier (registre d\'essai à part)')
    a = p.parse_args()
    if a.copier and not a.vers:
        p.error('--copier demande --vers')

    pilote = AppareilsMac().demarrer()
    print('Recherche d\'un appareil (%d s)…' % a.attendre)
    debut = time.monotonic()
    pilote.tourner(duree=a.attendre, jusqua=lambda: pilote.etat()['etat'] == PRET)
    e = pilote.etat()
    print('État : %s  appareil : %s  (%.1f s)' % (e['etat'], e['nom'] or '-', time.monotonic() - debut))
    if e['etat'] == VERROUILLE:
        print('Déverrouiller l\'iPhone et accepter « Se fier à cet ordinateur », puis relancer.')
    if e['etat'] != PRET:
        pilote.arreter()
        return 1

    fichiers = pilote.fichiers()
    entrees = coeur.catalogue(fichiers)
    print('%d fichiers, %d photos ou vidéos : %s' % (len(fichiers), len(entrees),
                                                      dict(Counter(x.genre for x in entrees))))
    print('Extensions : %s' % dict(Counter(Path(f.nom).suffix.upper() for f in fichiers)))
    print('Rafales : %d photos dans %d rafales' % (sum(1 for f in fichiers if f.rafale),
                                                   len({f.rafale for f in fichiers if f.rafale})))
    if entrees:
        print('Du %s au %s' % (entrees[-1].fichier.date, entrees[0].fichier.date))
        t = time.monotonic()
        v = pilote.vignette(entrees[0].fichier)
        print('Vignette de %s : %d octets, %.2f s' % (entrees[0].fichier.nom, len(v), time.monotonic() - t))

    if a.copier:
        choix = entrees[:a.copier]
        registre = coeur.Registre(a.vers / '.registre-essai.json')
        t = time.monotonic()
        r = importer(pilote, choix, a.vers, registre, nom_seance='essai',
                     progression=lambda i, n, nom: nom and print('  %d/%d %s' % (i + 1, n, nom)))
        duree = time.monotonic() - t
        octets = sum(f.taille for f in coeur.fichiers_a_copier(choix))
        print('Importés : %d sur %d en %.1f s (%.1f Mo/s), échecs : %s' % (
            r.importes, r.total, duree, octets / 1e6 / max(duree, 1e-3), r.echecs or 'aucun'))
        print('Dossier : %s' % r.dossier)
    pilote.arreter()
    return 0


if __name__ == '__main__':
    raise SystemExit(_essai())
