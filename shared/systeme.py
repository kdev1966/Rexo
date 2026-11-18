"""Ce qui dépend du système (macOS ou Windows), commun aux applications du hub.

Les applications n'appellent jamais `open`, `osascript`, l'Explorateur ou le Finder
directement : elles passent par ce module, qui choisit la bonne façon de faire.

    corbeille(chemin)            fichier ou dossier dans la Corbeille (macOS) ou la Corbeille
                                 de Windows ; récupérable, jamais effacé définitivement
    montrer(chemin)              ouvre un dossier dans le Finder ou l'Explorateur
    ouvrir(chemin, appli=None)   ouvre un fichier avec l'application par défaut (ou `appli`
                                 sur macOS, ex. « Preview »)
    choisir_dossier(titre, depart)   fenêtre de choix d'un dossier ; None si annulée
    dossier_journaux()           ~/Library/Logs/Rexo ou %LOCALAPPDATA%\\Rexo\\Journaux
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

WINDOWS = sys.platform == 'win32'
MACOS = sys.platform == 'darwin'

CORBEILLE_MAC = Path.home() / '.Trash'


class SystemeError(RuntimeError):
    pass


# ---------- Corbeille ----------

def _nom_libre(dossier, p):
    cible = dossier / p.name
    if cible.exists():
        cible = dossier / ('%s %s%s' % (p.stem, time.strftime('%H-%M-%S'), p.suffix))
    n = 2
    while cible.exists():
        cible = dossier / ('%s %d%s' % (p.stem, n, p.suffix))
        n += 1
    return cible


def _corbeille_windows(p):
    """SHFileOperationW avec FOF_ALLOWUNDO : l'élément va dans la Corbeille de Windows."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT),
                    ('pFrom', wintypes.LPCWSTR), ('pTo', wintypes.LPCWSTR),
                    ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', wintypes.BOOL),
                    ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=str(p.resolve()) + '\0',  # double zéro final
                         fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI)
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if r != 0 or op.fAnyOperationsAborted:
        raise SystemeError('Corbeille de Windows : échec (code %d) pour %s' % (r, p.name))


def corbeille(chemin, dossier_mac=None):
    """Met `chemin` dans la Corbeille ; renvoie l'emplacement dans la Corbeille (macOS) ou
    le chemin d'origine (Windows, qui garde lui-même l'emplacement), None s'il n'existe pas.
    `dossier_mac` remplace ~/.Trash (tests)."""
    p = Path(chemin)
    if not p.exists():
        return None
    if WINDOWS and dossier_mac is None:
        _corbeille_windows(p)
        return p
    dossier = Path(dossier_mac or CORBEILLE_MAC)
    dossier.mkdir(exist_ok=True)
    cible = _nom_libre(dossier, p)
    shutil.move(str(p), str(cible))
    return cible


# ---------- ouvrir, montrer ----------

def ouvrir(chemin, appli=None):
    """Ouvre un fichier ou un dossier avec l'application par défaut du système."""
    chemin = str(chemin)
    if WINDOWS:
        os.startfile(chemin)                    # noqa: S606 (chemin interne, jamais saisi)
    elif MACOS:
        subprocess.Popen(['open'] + (['-a', appli] if appli else []) + [chemin])
    else:
        subprocess.Popen(['xdg-open', chemin])


def montrer(dossier):
    """Ouvre un dossier dans le Finder ou l'Explorateur."""
    ouvrir(dossier)


# ---------- choix d'un dossier ----------

_TK = r'''
import sys, tkinter
from tkinter import filedialog
racine = tkinter.Tk()
racine.withdraw()
racine.attributes("-topmost", True)
d = filedialog.askdirectory(parent=racine, title=sys.argv[1], initialdir=sys.argv[2], mustexist=False)
racine.destroy()
sys.stdout.write(d or "")
'''


def choisir_dossier(titre, depart):
    """Fenêtre du système pour choisir un dossier ; renvoie un Path, ou None si annulée."""
    depart = Path(depart) if Path(depart).exists() else Path.home()
    if MACOS:
        script = ('POSIX path of (choose folder with prompt "%s" default location (POSIX file "%s"))'
                  % (titre.replace('"', ''), str(depart).replace('"', '')))
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)
        sortie = r.stdout.strip() if r.returncode == 0 else ''
    else:
        # Tk dans un processus à part : sa fenêtre doit tourner sur le fil principal, ce que
        # n'est pas un fil de requête Flask. Sous Windows, c'est la fenêtre moderne du système.
        r = subprocess.run([sys.executable, '-c', _TK, titre, str(depart)],
                           capture_output=True, text=True, timeout=600, encoding='utf-8')
        sortie = r.stdout.strip() if r.returncode == 0 else ''
    return Path(sortie) if sortie else None


# ---------- emplacements ----------

def dossier_journaux():
    if WINDOWS:
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        return base / 'Rexo' / 'Journaux'
    return Path.home() / 'Library' / 'Logs' / 'Rexo'
