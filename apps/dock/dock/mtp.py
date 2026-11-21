"""Accès à un téléphone Android en « Transfert de fichiers » (MTP), par libusb, sans pilote du
système : macOS ne lit pas le MTP, et en « Transfert de photos » (PTP) certains téléphones
(Xiaomi, MIUI) ne montrent que leurs dossiers à ImageCaptureCore.

MTP est le protocole PTP (ISO 15740) étendu : des transactions « commande, données éventuelles,
réponse » sur deux points d'accès USB. On n'envoie que des opérations de LECTURE :

    GetDeviceInfo, OpenSession, CloseSession, GetStorageIDs, GetObjectHandles,
    GetObjectInfo, GetObject, GetThumb, GetObjectPropValue

Aucune opération d'écriture ou de suppression n'existe dans ce module : OPERATIONS les liste
et `Session.transaction` refuse toute autre.

    AppareilsMTP().demarrer()     surveille l'USB (fil à part, toutes les 2 s)
    .etat()  .fichiers()  .vignette(f)  .copier(f, dossier, nom)  .actualiser()  .arreter()
    (même interface que appareil_mac.AppareilsMac)

Dossiers lus : DCIM, Pictures et Movies de chaque stockage, sous-dossiers compris, sauf les
dossiers cachés (« .thumbnails », « .deleteRecord »…).

Essai (téléphone déverrouillé, « Transfert de fichiers ») :
    .venv/bin/python -m dock.mtp [--copier N --vers DOSSIER]
"""

import ctypes as C
import ctypes.util
import os
import struct
import threading
import time
from datetime import datetime
from pathlib import Path

from .coeur import VIDEO, FichierAppareil, genre
from .importer import ErreurAppareil

ATTENTE, VERROUILLE, LECTURE, PRET, BLOQUE = 'attente', 'verrouille', 'lecture', 'pret', 'bloque'
DOSSIERS = ('DCIM', 'Pictures', 'Movies')
APPLE = 0x05AC
SONDE = 2.0                    # secondes entre deux recherches d'appareil
REESSAI = 30.0                 # un appareil qui n'a pas répondu n'est réessayé qu'après 30 s
DELAI = 30000                  # ms, pour chaque morceau reçu
MORCEAU = 1024 * 1024

# Opérations (toutes en lecture) et réponses
GET_DEVICE_INFO, OPEN_SESSION, CLOSE_SESSION = 0x1001, 0x1002, 0x1003
GET_STORAGE_IDS, GET_OBJECT_HANDLES, GET_OBJECT_INFO = 0x1004, 0x1007, 0x1008
GET_OBJECT, GET_THUMB, GET_OBJECT_PROP_VALUE = 0x1009, 0x100A, 0x9803
OPERATIONS = {GET_DEVICE_INFO, OPEN_SESSION, CLOSE_SESSION, GET_STORAGE_IDS, GET_OBJECT_HANDLES,
              GET_OBJECT_INFO, GET_OBJECT, GET_THUMB, GET_OBJECT_PROP_VALUE}
OK, SESSION_DEJA_OUVERTE = 0x2001, 0x201E
DOSSIER = 0x3001               # format « association » : un dossier
RACINE = 0xFFFFFFFF            # parent des objets à la racine d'un stockage
TOUS = 0xFFFFFFFF
PROP_TAILLE, PROP_DUREE = 0xDC04, 0xDC89
COMMANDE, DONNEES, REPONSE = 1, 2, 3


class ErreurMTP(RuntimeError):
    def __init__(self, message, debranche=False):
        super().__init__(message)
        self.debranche = debranche


# ---------- lecture des structures PTP ----------

def conteneur(code, transaction, params=()):
    """Paquet de commande : longueur, type, code, n° de transaction, paramètres (32 bits)."""
    return struct.pack('<IHHI%dI' % len(params), 12 + 4 * len(params), COMMANDE, code, transaction, *params)


def chaine(d, i):
    """Chaîne PTP (nombre de caractères sur 1 octet, UTF-16, zéro final) ; renvoie (texte, suite)."""
    n = d[i]
    return d[i + 1:i + 1 + 2 * n].decode('utf-16-le', 'replace').rstrip('\0'), i + 1 + 2 * n


def tableau(d, i=0, taille=4):
    n = struct.unpack_from('<I', d, i)[0]
    f = '<%d%s' % (n, 'I' if taille == 4 else 'H')
    return list(struct.unpack_from(f, d, i + 4)), i + 4 + taille * n


def date_ptp(texte):
    """« 20261022T212801 » (suivi parfois de « .0 », « Z » ou d'un décalage) -> datetime local."""
    if len(texte) < 15:
        return None
    try:
        return datetime.strptime(texte[:15], '%Y%m%dT%H%M%S').astimezone()
    except ValueError:
        return None


def info_appareil(d):
    """GetDeviceInfo -> {'fabricant', 'modele', 'serie'}."""
    i = 2 + 4 + 2
    _, i = chaine(d, i)                       # extension du fabricant
    i += 2                                    # mode
    for taille in (2, 2, 2, 2, 2):            # opérations, événements, propriétés, formats
        _, i = tableau(d, i, taille)
    fabricant, i = chaine(d, i)
    modele, i = chaine(d, i)
    _, i = chaine(d, i)                       # version
    serie, i = chaine(d, i)
    return {'fabricant': fabricant, 'modele': modele, 'serie': serie}


def info_objet(d):
    """GetObjectInfo -> {'format', 'taille', 'parent', 'nom', 'date'}."""
    stockage, fmt, _, taille = struct.unpack_from('<IHHI', d, 0)
    parent = struct.unpack_from('<I', d, 38)[0]
    nom, i = chaine(d, 52)
    prise, i = chaine(d, i)
    modif, i = chaine(d, i)
    return {'format': fmt, 'taille': taille, 'parent': parent, 'nom': nom,
            'date': date_ptp(prise) or date_ptp(modif)}


# ---------- libusb ----------

class _Endpoint(C.Structure):
    _fields_ = [('bLength', C.c_uint8), ('bDescriptorType', C.c_uint8), ('bEndpointAddress', C.c_uint8),
                ('bmAttributes', C.c_uint8), ('wMaxPacketSize', C.c_uint16), ('bInterval', C.c_uint8),
                ('bRefresh', C.c_uint8), ('bSynchAddress', C.c_uint8), ('extra', C.c_void_p),
                ('extra_length', C.c_int)]


class _Altsetting(C.Structure):
    _fields_ = [('bLength', C.c_uint8), ('bDescriptorType', C.c_uint8), ('bInterfaceNumber', C.c_uint8),
                ('bAlternateSetting', C.c_uint8), ('bNumEndpoints', C.c_uint8), ('bInterfaceClass', C.c_uint8),
                ('bInterfaceSubClass', C.c_uint8), ('bInterfaceProtocol', C.c_uint8), ('iInterface', C.c_uint8),
                ('endpoint', C.POINTER(_Endpoint)), ('extra', C.c_void_p), ('extra_length', C.c_int)]


class _Interface(C.Structure):
    _fields_ = [('altsetting', C.POINTER(_Altsetting)), ('num_altsetting', C.c_int)]


class _Config(C.Structure):
    _fields_ = [('bLength', C.c_uint8), ('bDescriptorType', C.c_uint8), ('wTotalLength', C.c_uint16),
                ('bNumInterfaces', C.c_uint8), ('bConfigurationValue', C.c_uint8), ('iConfiguration', C.c_uint8),
                ('bmAttributes', C.c_uint8), ('MaxPower', C.c_uint8), ('interface', C.POINTER(_Interface)),
                ('extra', C.c_void_p), ('extra_length', C.c_int)]


class _DescAppareil(C.Structure):
    _fields_ = [('bLength', C.c_uint8), ('bDescriptorType', C.c_uint8), ('bcdUSB', C.c_uint16),
                ('bDeviceClass', C.c_uint8), ('bDeviceSubClass', C.c_uint8), ('bDeviceProtocol', C.c_uint8),
                ('bMaxPacketSize0', C.c_uint8), ('idVendor', C.c_uint16), ('idProduct', C.c_uint16),
                ('bcdDevice', C.c_uint16), ('iManufacturer', C.c_uint8), ('iProduct', C.c_uint8),
                ('iSerialNumber', C.c_uint8), ('bNumConfigurations', C.c_uint8)]


def charger_libusb():
    """libusb : celle du paquet libusb-package si installé, sinon celle du système. None sinon."""
    chemins = []
    try:
        import libusb_package
        chemins.append(str(libusb_package.get_library_path()))
    except Exception:  # noqa: BLE001 — paquet absent
        pass
    trouve = ctypes.util.find_library('usb-1.0')
    if trouve:
        chemins.append(trouve)
    chemins += ['/usr/local/lib/libusb-1.0.dylib', '/opt/homebrew/lib/libusb-1.0.dylib']
    for p in chemins:
        try:
            lib = C.CDLL(p)
        except OSError:
            continue
        _signatures(lib)
        return lib
    return None


def _signatures(lib):
    vp, i, u8, u16 = C.c_void_p, C.c_int, C.c_uint8, C.c_uint16
    lib.libusb_init.argtypes = [C.POINTER(vp)]
    lib.libusb_get_device_list.argtypes = [vp, C.POINTER(C.POINTER(vp))]
    lib.libusb_get_device_list.restype = C.c_ssize_t
    lib.libusb_free_device_list.argtypes = [C.POINTER(vp), i]
    lib.libusb_get_device_descriptor.argtypes = [vp, C.POINTER(_DescAppareil)]
    lib.libusb_get_active_config_descriptor.argtypes = [vp, C.POINTER(C.POINTER(_Config))]
    lib.libusb_free_config_descriptor.argtypes = [C.POINTER(_Config)]
    lib.libusb_get_bus_number.argtypes = [vp]
    lib.libusb_get_bus_number.restype = u8
    lib.libusb_get_port_number.argtypes = [vp]
    lib.libusb_get_port_number.restype = u8
    lib.libusb_get_device_address.argtypes = [vp]
    lib.libusb_get_device_address.restype = u8
    lib.libusb_open.argtypes = [vp, C.POINTER(vp)]
    lib.libusb_close.argtypes = [vp]
    lib.libusb_get_string_descriptor_ascii.argtypes = [vp, u8, C.c_char_p, i]
    for f in ('libusb_claim_interface', 'libusb_release_interface', 'libusb_set_auto_detach_kernel_driver'):
        getattr(lib, f).argtypes = [vp, i]
    lib.libusb_clear_halt.argtypes = [vp, C.c_ubyte]
    lib.libusb_control_transfer.argtypes = [vp, u8, u8, u16, u16, C.c_char_p, u16, C.c_uint]
    lib.libusb_bulk_transfer.argtypes = [vp, C.c_ubyte, C.c_char_p, i, C.POINTER(i), C.c_uint]
    lib.libusb_error_name.argtypes = [i]
    lib.libusb_error_name.restype = C.c_char_p


ERREUR_PAS_D_APPAREIL = -4


class Transport:
    """Une interface MTP réclamée sur un appareil USB ouvert."""

    def __init__(self, lib, poignee, interface, sortie, entree):
        self.lib, self.h, self.interface, self.sortie, self.entree = lib, poignee, interface, sortie, entree
        self._tampon = C.create_string_buffer(MORCEAU)
        self._n = C.c_int()

    def _erreur(self, quoi, r):
        nom = self.lib.libusb_error_name(r).decode()
        return ErreurMTP('%s : %s' % (quoi, nom), debranche=r in (ERREUR_PAS_D_APPAREIL, -1))

    def envoyer(self, octets):
        r = self.lib.libusb_bulk_transfer(self.h, self.sortie, octets, len(octets), C.byref(self._n), 5000)
        if r:
            raise self._erreur('envoi', r)

    def recevoir(self):
        while True:
            r = self.lib.libusb_bulk_transfer(self.h, self.entree, self._tampon, MORCEAU, C.byref(self._n), DELAI)
            if r:
                raise self._erreur('réception', r)
            if self._n.value:                 # un paquet vide termine parfois des données
                return self._tampon.raw[:self._n.value]

    def annuler(self, transaction):
        """Demande d'annulation de la classe « image fixe » (PTP) : le téléphone arrête d'envoyer
        les données d'une transaction en cours au lieu de rester bloqué sur un hôte parti."""
        corps = struct.pack('<HI', 0x4001, transaction)
        self.lib.libusb_control_transfer(self.h, 0x21, 0x64, 0, self.interface, corps, len(corps), 2000)

    def fermer(self):
        self.lib.libusb_release_interface(self.h, self.interface)
        self.lib.libusb_close(self.h)


def chercher(lib, ctx):
    """Appareils MTP branchés (hors Apple) : [(device, interface, sortie, entrée, cle_usb)]."""
    liste = C.POINTER(C.c_void_p)()
    n = lib.libusb_get_device_list(ctx, C.byref(liste))
    trouves = []
    try:
        for k in range(max(n, 0)):
            dev = liste[k]
            desc = _DescAppareil()
            if lib.libusb_get_device_descriptor(dev, C.byref(desc)) or desc.idVendor == APPLE:
                continue
            cfg = C.POINTER(_Config)()
            if lib.libusb_get_active_config_descriptor(dev, C.byref(cfg)):
                continue
            try:
                for j in range(cfg.contents.bNumInterfaces):
                    itf = cfg.contents.interface[j]
                    for a in range(itf.num_altsetting):
                        alt = itf.altsetting[a]
                        eps = [alt.endpoint[e] for e in range(alt.bNumEndpoints)]
                        bulk = [e.bEndpointAddress for e in eps if e.bmAttributes & 3 == 2]
                        # MTP d'Android : classe 255/255/0 ; PTP standard : classe 6
                        mtp = (alt.bInterfaceClass, alt.bInterfaceSubClass) in ((255, 255), (6, 1))
                        if mtp and len(eps) == 3 and len(bulk) == 2:
                            sortie = next(b for b in bulk if not b & 0x80)
                            entree = next(b for b in bulk if b & 0x80)
                            cle = '%d-%d-%d' % (lib.libusb_get_bus_number(dev), lib.libusb_get_port_number(dev),
                                                lib.libusb_get_device_address(dev))
                            trouves.append((C.c_void_p(dev), alt.bInterfaceNumber, sortie, entree, cle, alt.iInterface))
            finally:
                lib.libusb_free_config_descriptor(cfg)
    finally:
        if n > 0:
            lib.libusb_free_device_list(liste, 1)
    return trouves


def ouvrir(lib, trouve):
    """Ouvre et réclame l'interface ; None si elle n'est pas MTP ou si le système la garde (PTP
    sous macOS)."""
    dev, interface, sortie, entree, _cle, i_itf = trouve
    h = C.c_void_p()
    if lib.libusb_open(dev, C.byref(h)):
        return None
    if i_itf:
        nom = C.create_string_buffer(64)
        n = lib.libusb_get_string_descriptor_ascii(h, i_itf, nom, 64)
        if n > 0 and b'MTP' not in nom.value.upper() and b'PTP' not in nom.value.upper():
            lib.libusb_close(h)
            return None
    lib.libusb_set_auto_detach_kernel_driver(h, 1)
    if lib.libusb_claim_interface(h, interface):
        lib.libusb_close(h)
        return None
    return Transport(lib, h, interface, sortie, entree)


# ---------- session MTP ----------

class Session:
    """Transactions MTP en lecture seule sur un transport (réel, ou simulé dans les tests)."""

    def __init__(self, transport):
        self.t = transport
        self._n = 0
        self.en_cours = None                  # n° de la transaction en cours, pour l'annuler

    def transaction(self, code, *params, vers=None):
        """Envoie la commande ; renvoie (code de réponse, données reçues). vers : fichier ouvert
        où écrire les données au fil de l'eau (GetObject), au lieu de les garder en mémoire."""
        if code not in OPERATIONS:
            raise ErreurMTP('opération 0x%04x refusée : lecture seule' % code)
        self._n += 1
        self.en_cours = self._n
        try:
            return self._transaction(code, params, vers)
        finally:
            self.en_cours = None

    def annuler(self):
        n = self.en_cours
        if n is not None and hasattr(self.t, 'annuler'):
            self.t.annuler(n)

    def _transaction(self, code, params, vers):
        self.t.envoyer(conteneur(code, self._n, params))
        donnees = bytearray()
        while True:
            paquet = self.t.recevoir()
            longueur, genre_, rc = struct.unpack_from('<IHH', paquet)
            if genre_ == DONNEES:
                reste = longueur - len(paquet)
                corps = paquet[12:]
                if vers is not None:
                    vers.write(corps)
                else:
                    donnees += corps
                while reste > 0:
                    paquet = self.t.recevoir()
                    reste -= len(paquet)
                    if vers is not None:
                        vers.write(paquet)
                    else:
                        donnees += paquet
            elif genre_ == REPONSE:
                return rc, bytes(donnees)

    def exiger(self, code, *params, vers=None):
        rc, d = self.transaction(code, *params, vers=vers)
        if rc != OK:
            raise ErreurMTP('opération 0x%04x : réponse 0x%04x' % (code, rc))
        return d

    def ouvrir(self):
        info = info_appareil(self.exiger(GET_DEVICE_INFO))
        rc, _ = self.transaction(OPEN_SESSION, 1)
        if rc not in (OK, SESSION_DEJA_OUVERTE):
            raise ErreurMTP('ouverture de session : réponse 0x%04x' % rc)
        return info

    def fermer(self):
        try:
            self.transaction(CLOSE_SESSION)
        except ErreurMTP:
            pass

    def stockages(self):
        """Stockages lisibles ; vide si le téléphone est verrouillé."""
        rc, d = self.transaction(GET_STORAGE_IDS)
        return tableau(d)[0] if rc == OK and d else []

    def enfants(self, stockage, parent):
        rc, d = self.transaction(GET_OBJECT_HANDLES, stockage, 0, parent)
        return tableau(d)[0] if rc == OK and d else []

    def info(self, objet):
        return info_objet(self.exiger(GET_OBJECT_INFO, objet))

    def propriete(self, objet, prop, fmt):
        rc, d = self.transaction(GET_OBJECT_PROP_VALUE, objet, prop)
        return struct.unpack_from(fmt, d)[0] if rc == OK and len(d) >= struct.calcsize(fmt) else None

    def catalogue(self, dossiers=DOSSIERS):
        """[(handle, FichierAppareil)] des photos et vidéos des dossiers voulus, de chaque stockage."""
        sortie = []
        for s in self.stockages():
            a_voir = []
            for o in self.enfants(s, RACINE):
                i = self.info(o)
                if i['format'] == DOSSIER and i['nom'] in dossiers:
                    a_voir.append(o)
            while a_voir:
                for o in self.enfants(s, a_voir.pop()):
                    i = self.info(o)
                    if i['nom'].startswith('.'):
                        continue
                    if i['format'] == DOSSIER:
                        a_voir.append(o)
                        continue
                    g = genre(i['nom'])
                    if g == 'autre':
                        continue
                    taille = i['taille']
                    if taille == 0xFFFFFFFF:             # plus de 4 Go
                        taille = self.propriete(o, PROP_TAILLE, '<Q') or taille
                    duree = None
                    if g == VIDEO:
                        ms = self.propriete(o, PROP_DUREE, '<I')
                        duree = ms / 1000 if ms else None
                    sortie.append((o, FichierAppareil(i['nom'], taille, i['date'], duree=duree)))
        return sortie


# ---------- pilote ----------

class AppareilsMTP:
    def __init__(self, lib=None):
        self._lib = lib or charger_libusb()
        self._ctx = C.c_void_p()
        self._verrou = threading.RLock()        # une transaction USB à la fois
        self._etat_verrou = threading.Lock()
        self._fil = None
        self._fin = threading.Event()
        self._usb = None                        # clé USB de l'appareil ouvert
        self._transport = self._session = None
        self._info = {}
        self._etat = ATTENTE
        self._handles, self._liste = {}, []
        self._relire = False
        self._echecs = {}                      # clé USB -> heure du dernier échec

    @property
    def disponible(self):
        return self._lib is not None

    def demarrer(self):
        if self._lib is None:
            return self
        if self._lib.libusb_init(C.byref(self._ctx)):
            self._lib = None
            return self
        self._fil = threading.Thread(target=self._surveiller, daemon=True, name='mtp')
        self._fil.start()
        return self

    def arreter(self):
        """Ferme la session proprement (aussi avant Quitter et Redémarrer : shared.serveur
        a_la_sortie). Un transfert en cours est annulé : sinon le téléphone reste bloqué au
        milieu de l'envoi et ne répond plus qu'après avoir été débranché."""
        self._fin.set()
        s = self._session
        if s is not None:
            s.annuler()
        if self._verrou.acquire(timeout=5):
            try:
                self._fermer()
            finally:
                self._verrou.release()

    # ---------- surveillance (fil à part) ----------

    def _surveiller(self):
        while not self._fin.is_set():
            try:
                self._un_tour()
            except Exception:  # noqa: BLE001 — appareil retiré en pleine lecture : on recommence
                with self._verrou:
                    self._fermer()
            self._fin.wait(SONDE)

    def _un_tour(self):
        trouves = chercher(self._lib, self._ctx)
        cles = {t[4] for t in trouves}
        with self._verrou:
            if self._usb is not None and self._usb not in cles:
                self._fermer()                  # débranché
            for cle in set(self._echecs) - cles:     # rebranché : on pourra réessayer tout de suite
                del self._echecs[cle]
            if self._etat == BLOQUE and not set(self._echecs) & cles:
                self._poser(ATTENTE)
            if self._usb is None:
                for t in trouves:
                    if time.monotonic() - self._echecs.get(t[4], -REESSAI) < REESSAI:
                        continue
                    tr = ouvrir(self._lib, t)
                    if tr is None:
                        continue
                    s = Session(tr)
                    try:
                        self._info = s.ouvrir()
                    except ErreurMTP:
                        tr.fermer()
                        self._echecs[t[4]] = time.monotonic()
                        self._poser(BLOQUE)       # vu mais muet : à débrancher et rebrancher
                        continue
                    self._transport, self._session, self._usb = tr, s, t[4]
                    self._poser(LECTURE)
                    self._relire = True
                    break
            if self._session is None:
                return
            if self._etat == VERROUILLE or self._relire:
                self._relire = False
                self._lire()

    def _lire(self):
        if not self._session.stockages():
            self._poser(VERROUILLE)
            return
        self._poser(LECTURE)
        objets = self._session.catalogue()
        with self._etat_verrou:
            self._handles = {f.cle: h for h, f in objets}
            self._liste = [f for _, f in objets]
            self._etat = PRET

    def _fermer(self):
        if self._session is not None:
            self._session.fermer()
        if self._transport is not None:
            self._transport.fermer()
        self._transport = self._session = self._usb = None
        self._info = {}
        with self._etat_verrou:
            self._etat, self._handles, self._liste = ATTENTE, {}, []

    def _poser(self, etat):
        with self._etat_verrou:
            self._etat = etat

    # ---------- depuis n'importe quel fil ----------

    def etat(self):
        with self._etat_verrou:
            etat = self._etat
        return {'etat': etat, 'nom': self._info.get('modele', '') if etat not in (ATTENTE, BLOQUE) else '',
                'identifiant': self.identifiant, 'marque': 'autre' if etat != ATTENTE else ''}

    @property
    def identifiant(self):
        i = self._info
        return i.get('serie') or ('%s %s' % (i.get('fabricant', ''), i.get('modele', ''))).strip()

    @property
    def nom(self):
        return self._info.get('modele') or 'Android'

    def fichiers(self):
        with self._etat_verrou:
            return list(self._liste)

    def _handle(self, fichier):
        with self._etat_verrou:
            h = self._handles.get(fichier.cle)
        if h is None:
            raise ErreurAppareil('%s n\'est plus sur l\'appareil' % fichier.nom, debranche=self._session is None)
        return h

    def _appel(self, fn):
        with self._verrou:
            if self._session is None:
                raise ErreurAppareil('appareil débranché', debranche=True)
            try:
                return fn(self._session)
            except ErreurMTP as e:
                if e.debranche:
                    self._fermer()
                raise ErreurAppareil(str(e), debranche=e.debranche) from None

    def vignette(self, fichier, delai=None):
        h = self._handle(fichier)
        return self._appel(lambda s: s.exiger(GET_THUMB, h))

    def copier(self, fichier, dossier, nom, delai=None):
        """Copie l'original dans `dossier` sous `nom` (fichier « .part » renommé à la fin : pas de
        fichier tronqué si le câble est retiré)."""
        h = self._handle(fichier)
        final = Path(dossier) / nom
        partiel = final.with_name(final.name + '.part')

        def lire(s):
            with open(partiel, 'wb') as f:
                s.exiger(GET_OBJECT, h, vers=f)
        try:
            self._appel(lire)
        except BaseException:
            partiel.unlink(missing_ok=True)
            raise
        os.replace(partiel, final)
        return final

    def actualiser(self):
        with self._verrou:
            if self._session is not None:
                self._relire = True
        # la relecture se fait au prochain tour de surveillance (2 s au plus)


# ---------- essai en ligne de commande ----------

def _essai():
    import argparse
    from collections import Counter

    from . import coeur
    from .importer import importer

    p = argparse.ArgumentParser(description='Essai de lecture d\'un Android en MTP (rien n\'est supprimé).')
    p.add_argument('--attendre', type=float, default=60)
    p.add_argument('--copier', type=int, default=0, help='copie les N fichiers les plus récents')
    p.add_argument('--vers', type=Path)
    a = p.parse_args()
    if a.copier and not a.vers:
        p.error('--copier demande --vers')
    pilote = AppareilsMTP()
    if not pilote.disponible:
        print('libusb introuvable')
        return 1
    pilote.demarrer()
    debut = time.monotonic()
    while time.monotonic() - debut < a.attendre and pilote.etat()['etat'] != PRET:
        time.sleep(0.5)
    e = pilote.etat()
    print('État : %s  appareil : %s  (%.1f s)' % (e['etat'], e['nom'] or '-', time.monotonic() - debut))
    if e['etat'] == VERROUILLE:
        print('Déverrouiller le téléphone (et autoriser l\'accès aux données si demandé).')
    if e['etat'] != PRET:
        pilote.arreter()
        return 1
    fichiers = pilote.fichiers()
    entrees = coeur.catalogue(fichiers)
    print('%d photos ou vidéos : %s' % (len(entrees), dict(Counter(x.genre for x in entrees))))
    print('Extensions : %s' % dict(Counter(Path(f.nom).suffix.upper() for f in fichiers)))
    print('Vidéos avec durée : %d / %d' % (sum(1 for f in fichiers if f.duree), sum(1 for x in entrees if x.genre == VIDEO)))
    if entrees:
        print('Du %s au %s' % (entrees[-1].fichier.date, entrees[0].fichier.date))
        t = time.monotonic()
        try:
            v = pilote.vignette(entrees[0].fichier)
            print('Vignette de %s : %d octets, %.2f s' % (entrees[0].fichier.nom, len(v), time.monotonic() - t))
        except ErreurAppareil as err:
            print('Vignette : %s' % err)
    if a.copier:
        registre = coeur.Registre(a.vers / '.registre-essai.json')
        t = time.monotonic()
        r = importer(pilote, entrees[:a.copier], a.vers, registre, nom_seance='essai',
                     progression=lambda i, n, nom: nom and print('  %d/%d %s' % (i + 1, n, nom)))
        duree = time.monotonic() - t
        octets = sum(f.taille for f in coeur.fichiers_a_copier(entrees[:a.copier]))
        print('Importés : %d sur %d en %.1f s (%.1f Mo/s), échecs : %s' % (
            r.importes, r.total, duree, octets / 1e6 / max(duree, 1e-3), r.echecs or 'aucun'))
        print('Dossier : %s' % r.dossier)
    pilote.arreter()
    return 0


if __name__ == '__main__':
    raise SystemExit(_essai())
