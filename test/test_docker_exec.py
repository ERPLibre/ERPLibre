#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/docker/docker_exec.sh devant un faux « docker » qui note ses
arguments : aucun conteneur n'est touché.

Le faux docker exécute LOCALEMENT ce que le script passe à docker exec après
le nom du conteneur, mais remplace le PATH système donné à env -i par un
répertoire qui ne contient que sh et, selon le test, un faux capsh qui note
ses arguments et sort avec le code du shell que l'utilisateur quitte.

Ce que ces tests gardent :

- le shell root ne s'ouvre jamais avec --privileged, et capsh le lance
  avec SETUID et SETGID pour seules capacités, sous no-new-privileges ;
- sans capsh dans le conteneur, aucun shell root ne s'ouvre ;
- il démarre dans « / », sous env -i avec un PATH système, sans profil ni
  bashrc : rien de ce que odoo peut réécrire n'est lu ou trouvé par lui ;
- le nom de compose v2 (« - ») est préféré, celui de la v1 (« _ ») sert
  quand le premier n'existe pas ;
- un seul docker exec, dont le code de sortie est celui du script.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "script" / "docker" / "docker_exec.sh"

# Chaque appel tient sur une ligne du journal. « inspect » d'un conteneur, le
# dernier argument, le dit en marche pour les noms de FAUX_EXISTANTS et
# échoue sinon ; « compose config » ne rend rien, et le projet se dérive du
# répertoire ; « exec » saute ses options et le conteneur, remplace PATH= par
# FAUX_PATH_CONTENEUR et exécute le reste.
FAUX_DOCKER = r"""#!/usr/bin/env bash
appel="$*"
echo "${appel//$'\n'/ }" >> "${FAUX_DOCKER_JOURNAL}"
case "$1" in
  inspect)
    [[ "$2 $3" == "--type container" ]] || exit 1
    for n in ${FAUX_EXISTANTS}; do [[ "${@: -1}" == "$n" ]] && echo true && exit 0; done
    exit 1 ;;
  exec)
    shift
    while [[ "$1" == -* ]]; do
      case "$1" in -u|-w) shift 2 ;; *) shift ;; esac
    done
    shift
    commande=()
    for a in "$@"; do
      [[ "$a" == PATH=* ]] && a="PATH=${FAUX_PATH_CONTENEUR}"
      commande+=("$a")
    done
    exec "${commande[@]}" ;;
esac
"""

# Le faux capsh note ses arguments, un par ligne, dans {args} et sort avec
# {rc} ; les deux sont écrits dans le fichier, env -i effaçant toute variable.
FAUX_CAPSH = """#!/bin/sh
printf '%s\\n' "$@" > '{args}'
exit {rc}
"""


def lancer(existants="projet-ERPLibre-1", exec_rc=0, capsh=True):
    """Lance le script depuis un répertoire « Projet.Essai » — nommé comme
    un checkout dont compose retire le point et passe en minuscules. Rend
    la sortie, les appels reçus par le faux docker et les arguments reçus
    par le faux capsh, None s'il n'a pas été lancé."""
    with tempfile.TemporaryDirectory() as dossier:
        faux = Path(dossier) / "bin"
        faux.mkdir()
        (faux / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        (faux / "docker").chmod(0o755)
        args_capsh = Path(dossier) / "args_capsh"
        conteneur = Path(dossier) / "conteneur"
        conteneur.mkdir()
        (conteneur / "sh").symlink_to("/bin/sh")
        if capsh:
            (conteneur / "capsh").write_text(
                FAUX_CAPSH.format(args=args_capsh, rc=exec_rc),
                encoding="utf-8",
            )
            (conteneur / "capsh").chmod(0o755)
        projet = Path(dossier) / "Projet.Essai"
        projet.mkdir()
        journal = Path(dossier) / "journal"
        journal.touch()
        env = dict(
            os.environ,
            PATH=f"{faux}:{os.environ['PATH']}",
            FAUX_DOCKER_JOURNAL=str(journal),
            FAUX_EXISTANTS=existants.replace("projet", "projetessai"),
            FAUX_PATH_CONTENEUR=str(conteneur),
        )
        sortie = subprocess.run(
            [str(SCRIPT)],
            cwd=projet,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        recus = None
        if args_capsh.exists():
            recus = args_capsh.read_text(encoding="utf-8").splitlines()
        return (
            sortie,
            journal.read_text(encoding="utf-8").splitlines(),
            recus,
        )


DEBUT_EXEC = (
    "exec -u root -w / -ti {} /usr/bin/env -i HOME=/root TERM=xterm"
    " LANG=C.UTF-8"
    " PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    " PS1=\\u@\\h:\\w\\$  sh -c "
)

ARGS_CAPSH = [
    "--no-new-privs",
    "--noamb",
    "--caps=cap_setuid,cap_setgid=ep",
    "--shell=/bin/bash",
    "--",
    "--noprofile",
    "--norc",
]


def execs(appels):
    return [a for a in appels if a.startswith("exec ")]


class TestDockerExec(unittest.TestCase):
    def test_shell_root_par_capsh_environnement_propre(self):
        sortie, appels, recus = lancer()
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(1, len(execs(appels)), appels)
        self.assertTrue(
            execs(appels)[0].startswith(
                DEBUT_EXEC.format("projetessai-ERPLibre-1")
            ),
            execs(appels)[0],
        )
        self.assertNotIn("--privileged", execs(appels)[0])
        self.assertEqual(ARGS_CAPSH, recus)

    def test_nom_compose_v1_en_repli(self):
        sortie, appels, recus = lancer(existants="projet_ERPLibre_1")
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertTrue(
            execs(appels)[0].startswith(
                DEBUT_EXEC.format("projetessai_ERPLibre_1")
            ),
            execs(appels)[0],
        )
        self.assertEqual(ARGS_CAPSH, recus)

    def test_sans_capsh_aucun_shell_root(self):
        sortie, appels, recus = lancer(capsh=False)
        self.assertEqual(sortie.returncode, 1)
        self.assertIn("libcap2-bin", sortie.stderr)
        self.assertIsNone(recus)
        self.assertEqual(1, len(execs(appels)), appels)

    def test_shell_quitte_en_erreur_un_seul_exec(self):
        sortie, appels, recus = lancer(exec_rc=3)
        self.assertEqual(sortie.returncode, 3)
        self.assertEqual(1, len(execs(appels)))
        self.assertEqual(ARGS_CAPSH, recus)


if __name__ == "__main__":
    unittest.main()
