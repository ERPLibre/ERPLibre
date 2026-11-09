#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/docker/docker_exec.sh devant un faux « docker » qui note ses
arguments : aucun conteneur n'est touché.

Ce que ces tests gardent :

- le shell root s'ouvre toujours avec --privileged, qui rend à root les
  capacités qu'apt demande et que le compose retire ;
- le nom de compose v2 (« - ») est préféré, celui de la v1 (« _ ») sert
  quand le premier n'existe pas ;
- un shell quitté sur un code non nul n'ouvre pas de second exec.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "script" / "docker" / "docker_exec.sh"

# « inspect » d'un conteneur, le dernier argument, le dit en marche pour les
# noms de FAUX_EXISTANTS et échoue sinon ; « compose config » ne rend rien,
# et le projet se dérive du répertoire ; « exec » sort avec FAUX_EXEC_RC, le
# code du shell que l'utilisateur quitte.
FAUX_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "${FAUX_DOCKER_JOURNAL}"
case "$1" in
  inspect)
    [[ "$2 $3" == "--type container" ]] || exit 1
    for n in ${FAUX_EXISTANTS}; do [[ "${@: -1}" == "$n" ]] && echo true && exit 0; done
    exit 1 ;;
  exec) exit "${FAUX_EXEC_RC:-0}" ;;
esac
"""


def lancer(existants="projet-ERPLibre-1", exec_rc=0):
    """Lance le script depuis un répertoire « Projet.Essai » — nommé comme
    un checkout dont compose retire le point et passe en minuscules. Rend
    la sortie et les appels reçus par le faux docker."""
    with tempfile.TemporaryDirectory() as dossier:
        faux = Path(dossier) / "bin"
        faux.mkdir()
        (faux / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        (faux / "docker").chmod(0o755)
        projet = Path(dossier) / "Projet.Essai"
        projet.mkdir()
        journal = Path(dossier) / "journal"
        journal.touch()
        env = dict(
            os.environ,
            PATH=f"{faux}:{os.environ['PATH']}",
            FAUX_DOCKER_JOURNAL=str(journal),
            FAUX_EXISTANTS=existants.replace("projet", "projetessai"),
            FAUX_EXEC_RC=str(exec_rc),
        )
        sortie = subprocess.run(
            [str(SCRIPT)],
            cwd=projet,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return sortie, journal.read_text(encoding="utf-8").splitlines()


def execs(appels):
    return [a for a in appels if a.startswith("exec ")]


class TestDockerExec(unittest.TestCase):
    def test_shell_root_privilegie(self):
        sortie, appels = lancer()
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(
            ["exec --privileged -u root -ti projetessai-ERPLibre-1 bash"],
            execs(appels),
        )

    def test_nom_compose_v1_en_repli(self):
        sortie, appels = lancer(existants="projet_ERPLibre_1")
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(
            ["exec --privileged -u root -ti projetessai_ERPLibre_1 bash"],
            execs(appels),
        )

    def test_shell_quitte_en_erreur_un_seul_exec(self):
        sortie, appels = lancer(exec_rc=1)
        self.assertEqual(sortie.returncode, 1)
        self.assertEqual(1, len(execs(appels)))


if __name__ == "__main__":
    unittest.main()
