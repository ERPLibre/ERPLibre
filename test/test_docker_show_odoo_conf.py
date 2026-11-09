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
  seule capacité DAC_READ_SEARCH, sans pilote de journal qui garderait les
  mots de passe, et ne télécharge rien ;
- sans compose lisible, le nom du volume se dérive du répertoire comme
  compose le dérive ;
- un volume ou une image absents arrêtent avant tout « run » ;
- une socket qui refuse le compte fait passer par sudo, avec le DOCKER_HOST
  posé ;
- toute autre erreur du moteur s'affiche et arrête, sans sudo.
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

# Répond comme un hôte où le projet « essai » a son volume. FAUX_MOTEUR est
# l'erreur de « version » hors sudo ; FAUX_SANS_COMPOSE fait échouer
# « compose config » ; FAUX_VOLUMES liste les volumes qui existent,
# FAUX_LABEL celui que les étiquettes désignent.
FAUX_DOCKER = """#!/usr/bin/env bash
echo "${FAUX_PAR:-}docker $*" >> "${FAUX_JOURNAL}"
case "$1" in
  version)
    if [[ -n "${FAUX_MOTEUR:-}" && -z "${FAUX_PAR:-}" ]]; then
      echo "${FAUX_MOTEUR}" >&2; exit 1
    fi ;;
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
# Note ses options, garde DOCKER_HOST seulement si --preserve-env le nomme,
# comme sudo sous env_reset, puis lance la commande ; échoue avec le message
# FAUX_SUDO_REFUS quand il est posé.
FAUX_SUDO = """#!/usr/bin/env bash
if [[ -n "${FAUX_SUDO_REFUS:-}" ]]; then echo "${FAUX_SUDO_REFUS}" >&2; exit 1; fi
garde=""
while [[ "$1" == -* ]]; do
  [[ "$1" == "--preserve-env=DOCKER_HOST" ]] && garde=1
  echo "sudo-option $1" >> "${FAUX_JOURNAL}"
  shift
done
[[ -z "$garde" ]] && unset DOCKER_HOST
echo "sudo-env DOCKER_HOST=${DOCKER_HOST:-}" >> "${FAUX_JOURNAL}"
FAUX_PAR="sudo " exec "$@"
"""

REFUS = (
    "permission denied while trying to connect to the docker API at"
    " unix:///var/run/docker.sock"
)

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
        shutil.copy2(SCRIPT.parent / "lib_conteneur.sh", scripts)
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
        env.pop("DOCKER_HOST", None)
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
                "docker run --rm --pull never --network none"
                " --log-driver none -u root"
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
        sortie, appels = lancer(FAUX_MOTEUR=REFUS)
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertIn("sudo", sortie.stderr)
        (run,) = runs(appels)
        self.assertTrue(run.startswith("sudo docker run "), run)
        self.assertNotIn("sudo-option --preserve-env=DOCKER_HOST", appels)

    def test_sudo_garde_le_docker_host(self):
        hote = "unix:///run/essai/docker.sock"
        sortie, appels = lancer(FAUX_MOTEUR=REFUS, DOCKER_HOST=hote)
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertIn("sudo-option --preserve-env=DOCKER_HOST", appels)
        self.assertIn(f"sudo-env DOCKER_HOST={hote}", appels)
        (run,) = runs(appels)
        self.assertTrue(run.startswith("sudo docker run "), run)

    def test_sudo_en_echec_arrete_avant_tout_volume(self):
        sortie, appels = lancer(
            FAUX_MOTEUR=REFUS, FAUX_SUDO_REFUS="sudo: a password is required"
        )
        self.assertEqual(sortie.returncode, 1)
        self.assertIn("sudo: a password is required", sortie.stderr)
        self.assertEqual([], [a for a in appels if " volume " in a])
        self.assertEqual([], runs(appels))

    def test_moteur_muet_arrete_sans_sudo(self):
        """Un démon arrêté ou un DOCKER_HOST faux n'est pas un refus de la
        socket : sudo n'y changerait rien, et perdrait le DOCKER_HOST."""
        erreur = "failed to connect to the docker API at unix:///nulle/part"
        sortie, appels = lancer(FAUX_MOTEUR=erreur)
        self.assertEqual(sortie.returncode, 1)
        self.assertIn(erreur, sortie.stderr)
        self.assertEqual([], [a for a in appels if a.startswith("sudo")])
        self.assertEqual([], runs(appels))


if __name__ == "__main__":
    unittest.main()
