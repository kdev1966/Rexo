"""python3 -m shared.modeles [liste|verifier|installer] [groupe ou nom]"""

import sys

from . import dossier, installer, present, selection, verifier


def main(argv):
    action = argv[0] if argv else 'liste'
    cible = argv[1] if len(argv) > 1 else None
    modeles = selection(cible)
    if not modeles:
        print('Aucun modèle pour « %s ».' % cible)
        return 1
    print('Dossier des modèles : %s' % dossier())
    if action == 'liste':
        for m in modeles:
            print('  %-30s %s  %7.1f Mo  %s' % (m['nom'], 'présent' if present(m['nom']) else 'absent ',
                                                m['taille'] / 1e6, m['description']))
        return 0
    if action == 'verifier':
        ok = True
        for m in modeles:
            bon = verifier(m['nom'])
            ok &= bon
            print('  %-30s %s' % (m['nom'], 'vérifié' if bon else 'ABSENT OU ALTÉRÉ'))
        return 0 if ok else 1
    if action == 'installer':
        for m in modeles:
            installer(m['nom'])
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
