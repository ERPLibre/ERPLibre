#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""« make docker_volume_clean » efface-t-il seulement après deux oui ?

Le script est lancé pour de vrai devant un faux « docker » qui note ce qu'on
lui demande et répond comme un projet compose : rien n'est jamais effacé ici.

Ce que ces tests gardent :

- rien n'est arrêté ni effacé sans un « y » PUIS le nom du projet retapé ;
  une autre réponse, ou une entrée fermée, annule ;
- sans volume du projet, il n'y a rien à demander ;
- les deux confirmations données, le projet descend avec ses volumes, et un
  volume qui porte encore son nom sans figurer dans docker-compose.yml est
  retiré par son nom.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/docker/docker_volume_clean.sh"
MAKEFILE = (RACINE / "conf/make.docker.Makefile").read_text(encoding="utf-8")

FAUX_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "${FAUX_DOCKER_JOURNAL}"
case "$*" in
  "compose config --format json") echo '{"name": "projet_essai"}' ;;
  "volume ls -q --filter label=com.docker.compose.project=projet_essai")
    if [ -e "${FAUX_DOCKER_JOURNAL}.descendu" ]; then
      for v in ${FAUX_RESTANTS}; do echo "$v"; done
    else
      for v in ${FAUX_VOLUMES}; do echo "$v"; done
    fi ;;
  "compose down -v --remove-orphans") touch "${FAUX_DOCKER_JOURNAL}.descendu" ;;
esac
"""


def lancer(reponses, volumes="projet_essai_db projet_essai_data", restants=""):
    """Lance le script avec ``reponses`` sur son entrée. Rend la sortie et
    les commandes reçues par le faux docker."""
    with tempfile.TemporaryDirectory() as dossier:
        faux = Path(dossier) / "docker"
        faux.write_text(FAUX_DOCKER, encoding="utf-8")
        faux.chmod(0o755)
        journal = Path(dossier) / "journal"
        journal.touch()
        env = dict(
            os.environ,
            PATH=f"{dossier}:{os.environ['PATH']}",
            FAUX_DOCKER_JOURNAL=str(journal),
            FAUX_VOLUMES=volumes,
            FAUX_RESTANTS=restants,
        )
        sortie = subprocess.run(
            [str(SCRIPT)],
            input=reponses,
            env=env,
            capture_output=True,
            text=True,
        )
        return sortie, journal.read_text(encoding="utf-8").splitlines()


def efface(appels):
    return any(
        a.startswith("compose down") or a.startswith("volume rm")
        for a in appels
    )


class TestConfirmation(unittest.TestCase):
    def test_un_non_annule_tout(self):
        sortie, appels = lancer("n\n")
        self.assertEqual(1, sortie.returncode)
        self.assertFalse(efface(appels))
        self.assertIn("nothing was deleted", sortie.stdout)

    def test_un_nom_different_annule_tout(self):
        sortie, appels = lancer("y\nautre_projet\n")
        self.assertEqual(1, sortie.returncode)
        self.assertFalse(efface(appels))

    def test_le_oui_seul_ne_suffit_pas(self):
        """Une entrée fermée après le « y » vaut un refus."""
        sortie, appels = lancer("y\n")
        self.assertEqual(1, sortie.returncode)
        self.assertFalse(efface(appels))

    def test_une_entree_fermee_annule(self):
        sortie, appels = lancer("")
        self.assertEqual(1, sortie.returncode)
        self.assertFalse(efface(appels))

    def test_la_liste_precede_la_question(self):
        sortie, _ = lancer("n\n")
        self.assertIn("  - projet_essai_db", sortie.stdout)
        self.assertIn("  - projet_essai_data", sortie.stdout)


class TestEffacement(unittest.TestCase):
    def test_deux_confirmations_descendent_le_projet_et_ses_volumes(self):
        sortie, appels = lancer("y\nprojet_essai\n")
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        self.assertIn("compose down -v --remove-orphans", appels)
        self.assertFalse(any(a.startswith("volume rm") for a in appels))

    def test_un_volume_hors_du_compose_est_retire_par_son_nom(self):
        sortie, appels = lancer(
            "y\nprojet_essai\n", restants="projet_essai_ancien"
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        self.assertIn("volume rm projet_essai_ancien", appels)

    def test_sans_volume_rien_n_est_demande(self):
        sortie, appels = lancer("", volumes="")
        self.assertEqual(0, sortie.returncode)
        self.assertIn("nothing to delete", sortie.stdout)
        self.assertFalse(efface(appels))


class TestCible(unittest.TestCase):
    def test_la_cible_make_lance_le_script(self):
        bloc = MAKEFILE[MAKEFILE.index("docker_volume_clean:") :]
        self.assertIn(
            "./script/docker/docker_volume_clean.sh", bloc.split("\n")[1]
        )


if __name__ == "__main__":
    unittest.main()
