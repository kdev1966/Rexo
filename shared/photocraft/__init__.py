"""Pilote de PhotoCraft en mode « serve » (une requête JSON par ligne), partagé par les applications.

L'outil en ligne de commande (photocraft-cli) est cherché, dans l'ordre : la variable
d'environnement PHOTOCRAFT_CLI, les emplacements d'installation habituels (macOS :
/Applications/PhotoCraft.app ; Windows : Program Files\\ArtCraft\\PhotoCraft, installé par
le lanceur ArtCraft, ou AppData\\Local\\Programs), puis le PATH.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _candidats():
    if os.environ.get('PHOTOCRAFT_CLI'):
        yield Path(os.environ['PHOTOCRAFT_CLI'])
    if sys.platform == 'win32':
        for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'),
                     os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs')):
            if base:
                for dossier in (os.path.join('ArtCraft', 'PhotoCraft'), 'PhotoCraft'):
                    yield Path(base) / dossier / 'photocraft-cli.exe'
    else:
        for base in (Path('/Applications'), Path.home() / 'Applications'):
            yield base / 'PhotoCraft.app' / 'Contents' / 'MacOS' / 'photocraft-cli'
    trouve = shutil.which('photocraft-cli')
    if trouve:
        yield Path(trouve)


def trouver_cli():
    """Chemin de photocraft-cli, ou None si PhotoCraft n'est pas installé."""
    for p in _candidats():
        if p.is_file():
            return p
    return None


def ouvrir(fichier):
    """Ouvre `fichier` (un PSD) dans PhotoCraft, avec son interface."""
    fichier = str(fichier)
    if sys.platform == 'darwin':
        subprocess.Popen(['open', '-a', 'PhotoCraft', fichier])
        return
    cli = trouver_cli()
    appli = None
    if cli:
        for nom in ('PhotoCraft.exe', 'photocraft.exe'):
            if (cli.parent / nom).is_file():
                appli = cli.parent / nom
    if appli:
        subprocess.Popen([str(appli), fichier])
    elif sys.platform == 'win32':
        os.startfile(fichier)                   # noqa: S606 (application associée aux PSD)
    else:
        subprocess.Popen(['xdg-open', fichier])


class PhotoCraftError(RuntimeError):
    pass


class PhotoCraft:
    """Session PhotoCraft sans interface.

    read_roots : dossiers où PhotoCraft a le droit de lire.
    write_root : dossier (un seul) où il a le droit d'écrire.
    """

    def __init__(self, read_roots, write_root):
        cli = trouver_cli()
        if cli is None:
            raise PhotoCraftError('PhotoCraft introuvable : installer PhotoCraft, ou indiquer le chemin '
                                  'de photocraft-cli dans la variable PHOTOCRAFT_CLI')
        args = [str(cli), 'serve']
        for root in read_roots:
            args += ['--automation-read-root', str(root)]
        args += ['--automation-write-root', str(write_root)]
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                      encoding='utf-8')
        self._next_id = 0

    def call(self, method, **params):
        self._next_id += 1
        request = {'id': self._next_id, 'method': method, 'params': params}
        self._proc.stdin.write(json.dumps(request) + '\n')
        self._proc.stdin.flush()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise PhotoCraftError('PhotoCraft s\'est arrêté pendant « %s »' % method)
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get('id') == self._next_id:
                break
        if not message.get('ok'):
            what = params.get('command', '')
            raise PhotoCraftError('%s %s : %s' % (method, what, message.get('error')))
        return message.get('result')

    def cmd(self, command, **params):
        """Exécute une commande du moteur (voir `photocraft-cli commands`)."""
        return self.call('engine.execute', command=command, params=params)

    def close(self):
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=30)
        except Exception:
            self._proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
