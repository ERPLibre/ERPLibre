#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Choix d'un ajout de VM à un suivi d'installation ouvert, hors du suivi.

Le tableau de suivi est une App Textual : le formulaire de déploiement, autre
App, ne peut pas s'y ouvrir, et les invites de mot de passe n'y ont pas de
terminal. Ce programme tourne donc dans un processus neuf, terminal rendu par
le suivi : il pose toutes les questions par
`TODO._qemu_collect_spec_for_session`, écrit la spec en JSON, lisible du
seul utilisateur, et rend son verdict par le code de sortie.

    python -m script.todo.qemu_deploy_collect --out spec.json \\
        --monitored vm-a vm-b

Codes de sortie : 0, spec écrite ; 1, annulé ; 2, erreur.
"""

import argparse
import json
import os
import sys

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.append(REPO)

OK, ANNULE, ERREUR = 0, 1, 2


def write_spec(spec, out):
    """Écrit `spec` en JSON dans `out`, en mode 0600.

    La spec nomme des clés SSH et des comptes git : le fichier est créé
    lisible du seul propriétaire, et un fichier déjà présent est ramené à ce
    mode avant d'être réécrit."""
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)
        json.dump(spec, fh, indent=2)


def main(argv=None, todo_factory=None):
    """Rend le code de sortie. `todo_factory` construit l'objet TODO ; par
    défaut, celui du menu, depuis la racine du dépôt où il lit sa
    configuration."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="spec JSON to write")
    parser.add_argument(
        "--monitored",
        nargs="*",
        default=[],
        help="names of the VMs already in the monitor",
    )
    args = parser.parse_args(argv)
    # Résolu avant le chdir : un chemin relatif désigne celui de l'appelant.
    out = os.path.abspath(args.out)
    try:
        if todo_factory is None:
            os.chdir(REPO)
            from script.todo.todo import TODO

            todo_factory = TODO
        spec = todo_factory()._qemu_collect_spec_for_session(args.monitored)
    except (KeyboardInterrupt, EOFError):
        return ANNULE
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return ERREUR
    if spec is None:
        return ANNULE
    try:
        write_spec(spec, out)
    except (OSError, TypeError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return ERREUR
    return OK


if __name__ == "__main__":
    sys.exit(main())
