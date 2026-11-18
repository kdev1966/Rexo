"""Pilote de PhotoCraft en mode « serve » (une requête JSON par ligne), partagé par les applications."""

import json
import subprocess

CLI = '/Applications/PhotoCraft.app/Contents/MacOS/photocraft-cli'


class PhotoCraftError(RuntimeError):
    pass


class PhotoCraft:
    """Session PhotoCraft sans interface.

    read_roots : dossiers où PhotoCraft a le droit de lire.
    write_root : dossier (un seul) où il a le droit d'écrire.
    """

    def __init__(self, read_roots, write_root):
        args = [CLI, 'serve']
        for root in read_roots:
            args += ['--automation-read-root', str(root)]
        args += ['--automation-write-root', str(write_root)]
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, bufsize=1)
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
