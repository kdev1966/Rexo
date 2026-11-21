"""Le téléphone branché, quel que soit son chemin : l'interface et l'import ne voient qu'un pilote.

    macOS : iPhone (et appareil photo en PTP) par ImageCaptureCore (appareil_mac),
            Android en « Transfert de fichiers » par MTP sur libusb (mtp).

Un seul téléphone à la fois : celui lu en MTP passe d'abord (un Android en « Transfert de
photos » est aussi vu par ImageCaptureCore, mais souvent sans ses photos).
"""

import time

ATTENTE = 'attente'


class Appareils:
    def __init__(self, mac=None, mtp=None):
        self.mac, self.mtp = mac, mtp

    def demarrer(self):
        for p in self._pilotes():
            p.demarrer()
        return self

    def arreter(self):
        for p in self._pilotes():
            p.arreter()

    def tourner(self, duree=None, jusqua=None):
        """Fil principal : boucle d'ImageCaptureCore s'il y a lieu, sinon simple attente."""
        if self.mac is not None:
            return self.mac.tourner(duree, jusqua)
        fin = None if duree is None else time.monotonic() + duree
        while fin is None or time.monotonic() < fin:
            if jusqua is not None and jusqua():
                return True
            time.sleep(0.2)
        return jusqua() if jusqua is not None else True

    def _pilotes(self):
        return [p for p in (self.mtp, self.mac) if p is not None]

    def _actif(self):
        for p in self._pilotes():
            if p.etat()['etat'] != ATTENTE:
                return p
        return self._pilotes()[0] if self._pilotes() else None

    def etat(self):
        p = self._actif()
        return p.etat() if p is not None else {'etat': ATTENTE, 'nom': '', 'identifiant': '', 'marque': ''}

    @property
    def identifiant(self):
        return self._actif().identifiant

    @property
    def nom(self):
        return self._actif().nom

    def fichiers(self):
        return self._actif().fichiers()

    def vignette(self, fichier, delai=30):
        return self._actif().vignette(fichier, delai)

    def copier(self, fichier, dossier, nom, delai=1800):
        return self._actif().copier(fichier, dossier, nom, delai=delai)

    def actualiser(self):
        return self._actif().actualiser()
