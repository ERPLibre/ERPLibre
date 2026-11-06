#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/docker/docker_show_odoo_conf.sh devant un faux « docker » (et un
faux « sudo ») qui notent leurs arguments : aucun conteneur ni volume n'est
touché.

Ce que ces tests gardent :

- le volume se trouve par les étiquettes de compose, l'image est celle du
  service ERPLibre ;
- le conteneur jetable lit le volume en lecture seule, sans réseau, avec la
  seule capacité DAC_READ_SEARCH, et ne télécharge rien ;
- sans compose lisible, le nom du volume se dérive du répertoire ;
- un volume ou une image absents arrêtent avant tout « run » ;
- une socket qui refuse le compte fait passer par sudo.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "script" / "docker" / "docker_show_odoo_conf.sh"

# Répond comme un hôte où le projet « essai » a son volume. FAUX_SANS_SOCKET
# fait échouer « info » hors sudo ; FAUX_SANS_COMPOSE, « compose config » ;
# FAUX_VOLUMES liste les volumes qui existent, FAUX_LABEL celui que les
# étiquettes désignent.
FAUX_DOCKER = """#!/usr/bin/env bash
echo "${FAUX_PAR:-}docker $*" >> "${FAUX_JOURNAL}"
case "$1" in
  info) [[ -n "${FAUX_SANS_SOCKET:-}" && -z "${FAUX_PAR:-}" ]] && exit 1; exit 0 ;;
  compose) [[ -n "${FAUX_SANS_COMPOSE:-}" ]] && exit 1; echo "${FAUX_CONFIG}" ;;
  images) echo "technolibre/erplibre:repli" ;;
  volume)
    case "$2" in
      ls) [[ -n "${FAUX_LABEL:-}" ]] && echo "${FAUX_LABEL}"; exit 0 ;;
      inspect) for v in ${FAUX_VOLUMES}; do [[ "$3" == "$v" ]] && exit 0; done; exit 1 ;;
    esac ;;
  image) [[ -z "${FAUX_SANS_IMAGE:-}" ]] ;;
  run) echo "[options]" ;;
esac
"""
FAUX_SUDO = """#!/usr/bin/env bash
FAUX_PAR="sudo " exec "$@"
"""

CONFIG = json.dumps(
    {
        "name": "essai",
        "services": {"ERPLibre": {"image": "technolibre/erplibre:compose"}},
    }
)


def lancer(**faux):
    """Lance une COPIE du script, placée dans un dépôt factice nommé
    « Depot.Essai », comme le script se place à la racine de son dépôt.
    Rend la sortie et les appels reçus."""
    with tempfile.TemporaryDirectory() as dossier:
        bin_ = Path(dossier) / "bin"
        bin_.mkdir()
        for nom, texte in (("docker", FAUX_DOCKER), ("sudo", FAUX_SUDO)):
            (bin_ / nom).write_text(texte, encoding="utf-8")
            (bin_ / nom).chmod(0o755)
        scripts = Path(dossier) / "Depot.Essai" / "script" / "docker"
        scripts.mkdir(parents=True)
        copie = scripts / SCRIPT.name
        shutil.copy2(SCRIPT, copie)
        journal = Path(dossier) / "journal"
        journal.touch()
        env = dict(
            os.environ,
            PATH=f"{bin_}:{os.environ['PATH']}",
            FAUX_JOURNAL=str(journal),
            FAUX_CONFIG=CONFIG,
            FAUX_LABEL="essai_erplibre_conf",
            FAUX_VOLUMES="essai_erplibre_conf",
        )
        env.update({k: str(v) for k, v in faux.items()})
        sortie = subprocess.run(
            [str(copie)],
            cwd=dossier,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return sortie, journal.read_text(encoding="utf-8").splitlines()


def runs(appels):
    return [a for a in appels if " run " in f" {a} " or a.endswith("run")]


class TestShowOdooConf(unittest.TestCase):
    def test_lecture_seule_sans_reseau(self):
        sortie, appels = lancer()
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual("[options]\n", sortie.stdout)
        self.assertEqual(
            [
                "docker run --rm --pull never --network none -u root"
                " --cap-drop ALL --cap-add DAC_READ_SEARCH"
                " --security-opt no-new-privileges:true"
                " -v essai_erplibre_conf:/conf:ro --entrypoint cat"
                " technolibre/erplibre:compose /conf/odoo.conf"
            ],
            runs(appels),
        )

    def test_sans_compose_le_nom_vient_du_repertoire(self):
        sortie, appels = lancer(
            FAUX_SANS_COMPOSE=1,
            FAUX_LABEL="",
            FAUX_VOLUMES="depotessai_erplibre_conf",
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        (run,) = runs(appels)
        self.assertIn("-v depotessai_erplibre_conf:/conf:ro", run)
        self.assertIn("technolibre/erplibre:repli", run)

    def test_volume_absent_arrete_avant_run(self):
        sortie, appels = lancer(FAUX_LABEL="", FAUX_VOLUMES="")
        self.assertEqual(sortie.returncode, 1)
        self.assertIn("essai_erplibre_conf", sortie.stderr)
        self.assertEqual([], runs(appels))

    def test_image_absente_arrete_avant_run(self):
        sortie, appels = lancer(FAUX_SANS_IMAGE=1)
        self.assertEqual(sortie.returncode, 1)
        self.assertIn("nothing is downloaded", sortie.stderr)
        self.assertEqual([], runs(appels))

    def test_socket_refusee_passe_par_sudo(self):
        sortie, appels = lancer(FAUX_SANS_SOCKET=1)
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertIn("sudo", sortie.stderr)
        (run,) = runs(appels)
        self.assertTrue(run.startswith("sudo docker run "), run)


if __name__ == "__main__":
    unittest.main()
