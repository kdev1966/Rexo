"""Lanceur Windows d'une application web du hub (raccourci du Bureau, voir creer_raccourci.ps1).

    pythonw.exe shared\\lanceur\\lancer.py identite|reveal

Démarre le serveur local (127.0.0.1 seulement) sans fenêtre de console, attend qu'il réponde,
puis ouvre la page dans le navigateur par défaut. Si le serveur tourne déjà, ouvre seulement
la page. Le bouton « Quitter » de la page arrête le serveur. Journal : voir shared.systeme.
Lancé par pythonw (sans console) : une erreur est montrée dans une boîte de dialogue.
"""

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HUB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HUB))

from shared.systeme import dossier_journaux  # noqa: E402

APPLIS = {'identite': ('Rexo ID', 'identite.interface', 8766),
          'reveal': ('Rexo Reveal', 'reveal.interface', 8765)}


def repond(adresse):
    try:
        urllib.request.urlopen(adresse, timeout=1).close()
        return True
    except OSError:
        return False


def erreur(titre, texte):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texte, titre, 0x10)
    else:
        print('%s : %s' % (titre, texte), file=sys.stderr)


def main():
    cle = sys.argv[1] if len(sys.argv) > 1 else ''
    if cle not in APPLIS:
        erreur('Rexo', 'usage : lancer.py identite|reveal')
        return 1
    nom, module, port = APPLIS[cle]
    adresse = 'http://127.0.0.1:%d/' % port
    if not repond(adresse):
        dossier = HUB / 'apps' / cle
        python = dossier / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        if not python.exists():
            erreur(nom, 'Environnement absent : %s\nVoir le README de l\'application.' % python.parent.parent)
            return 1
        journaux = dossier_journaux()
        journaux.mkdir(parents=True, exist_ok=True)
        options = {}
        if sys.platform == 'win32':
            # ni console, ni lien avec ce lanceur, qui se termine aussitôt la page ouverte
            options['creationflags'] = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                                        | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            options['start_new_session'] = True
        with open(journaux / ('%s.log' % cle), 'ab') as log:
            subprocess.Popen([str(python), '-m', module], cwd=str(dossier), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                             env=dict(os.environ, PYTHONIOENCODING='utf-8'), **options)
        fin = time.time() + 30
        while not repond(adresse):
            if time.time() > fin:
                erreur(nom, 'Le serveur ne répond pas. Journal : %s' % (journaux / ('%s.log' % cle)))
                return 1
            time.sleep(0.25)
    webbrowser.open(adresse)
    return 0


if __name__ == '__main__':
    sys.exit(main())
