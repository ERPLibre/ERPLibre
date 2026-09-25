#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La version d'Odoo demandée arrive-t-elle jusqu'à l'image ?

« docker_build.sh --odoo_15 » traverse trois étages avant de produire une
image : le catalogue qui donne le triplet de versions, les « --build-arg » du
script, et les « ARG » que le Dockerfile consomme. Un étage muet ne casse
rien — il laisse passer les valeurs du checkout, et l'image porte le nom de la
version demandée tout en contenant une autre.

Ce que ces tests gardent :

- un drapeau de version inconnu ARRÊTE la construction. Le script lisait le
  catalogue sans regarder le code de retour : une sortie vide repartait sur
  les versions du checkout ;
- « ODOO_VERSION » est déclaré en ARG dans la base. ODOO_EXEC_BIN le fige dans
  l'image et l'entrypoint lance ce chemin tel quel ; non déclaré, l'argument
  n'est consommé par personne et toute image pointe sur odoo18.0 ;
- tout « --build-arg » posé par le script trouve un ARG qui l'attend. Docker
  ne fait qu'avertir sur un argument que personne ne lit, et l'avertissement
  se perd dans le journal de construction.
"""

import re
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/docker/docker_build.sh"
TEXTE = SCRIPT.read_text(encoding="utf-8")
BASE = (RACINE / "docker/Dockerfile.base").read_text(encoding="utf-8")
PROD = (RACINE / "docker/Dockerfile.prod.pkg").read_text(encoding="utf-8")
CATALOGUE = RACINE / "conf/supported_version_erplibre.json"


def _versions_odoo():
    """Les versions d'Odoo du catalogue, « 18.0 » puis « 17.0 »…"""
    import json

    with CATALOGUE.open(encoding="utf-8") as fh:
        catalogue = json.load(fh)
    vues = []
    for cle in catalogue:
        odoo = cle.split("_")[0].removeprefix("odoo")
        if odoo not in vues:
            vues.append(odoo)
    return vues


class TestCatalogue(unittest.TestCase):
    def test_chaque_version_donne_un_triplet_complet(self):
        """Le script lit les quatre lignes par leur rang : une manquante
        décale toutes les suivantes."""
        for odoo in _versions_odoo():
            with self.subTest(odoo=odoo):
                sortie = subprocess.run(
                    [
                        "python3",
                        "./script/version/get_version.py",
                        "--odoo_version",
                        odoo,
                    ],
                    cwd=RACINE,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, sortie.returncode, sortie.stderr)
                lignes = sortie.stdout.split()
                self.assertEqual(4, len(lignes), sortie.stdout)
                self.assertEqual(odoo, lignes[0])
                self.assertEqual(f"odoo{odoo}_python{lignes[2]}", lignes[3])


class TestDrapeauInconnu(unittest.TestCase):
    def test_une_version_absente_du_catalogue_arrete_tout(self):
        """Le script sort avant d'avoir rien réécrit ni construit."""
        sortie = subprocess.run(
            [str(SCRIPT), "--odoo_99"],
            cwd=RACINE,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, sortie.returncode)
        self.assertIn("99.0", sortie.stdout + sortie.stderr)

    def test_l_interprete_est_cherche_avant_d_etre_appele(self):
        """« python » nu n'existe pas sur Debian sans python-is-python3."""
        self.assertIn("python3", TEXTE)
        self.assertIn(".venv.erplibre/bin/python", TEXTE)


class TestCommitPublie(unittest.TestCase):
    """Le conteneur CLONE le dépôt public et se place sur le commit qu'on lui
    passe. Un commit encore local n'y existe pas, et la construction s'arrête
    APRÈS le clone sur « fatal: reference is not a tree » — un message qui ne
    nomme ni le commit manquant ni le geste qui manque."""

    def test_la_verification_precede_la_construction(self):
        self.assertIn("verifier_commit_publie", TEXTE)
        self.assertLess(
            TEXTE.index("verifier_commit_publie\n"),
            TEXTE.index("docker build"),
        )

    def test_elle_interroge_le_depot_que_l_image_clone(self):
        """Le dépôt est lu dans le Dockerfile : une seconde source de vérité
        divergerait sans que rien ne le dise."""
        self.assertIn("REPO_MANIFEST_URL", TEXTE)
        self.assertIn("Dockerfile.prod.pkg", TEXTE)
        self.assertIn("git ls-remote", TEXTE)

    def test_elle_nomme_le_geste_qui_manque(self):
        self.assertIn("git push", TEXTE)

    def test_hors_ligne_elle_ne_refuse_pas(self):
        """On ne refuse pas sur une ignorance : un dépôt injoignable ne prouve
        rien sur le commit."""
        bloc = TEXTE[
            TEXTE.index("verifier_commit_publie() {") : TEXTE.index(
                "\nverifier_commit_publie\n"
            )
        ]
        injoignable = bloc.index("Depot injoignable")
        premier_refus = bloc.index("exit 1")
        self.assertLess(injoignable, premier_refus)

    def test_le_commit_passe_a_l_image_est_celui_qu_elle_verifie(self):
        """Vérifier une valeur et en passer une autre ne garderait rien."""
        self.assertIn("--build-arg WORKING_HASH=${EL_HASH}", TEXTE)
        self.assertIn("--build-arg WORKING_BRANCH=${EL_BRANCHE}", TEXTE)


class TestArgumentsDeConstruction(unittest.TestCase):
    def test_tout_build_arg_trouve_un_arg(self):
        poses = set(re.findall(r"--build-arg (\w+)=", TEXTE))
        self.assertTrue(poses)
        declares = set(re.findall(r"^ARG (\w+)", BASE + PROD, re.MULTILINE))
        self.assertEqual(set(), poses - declares)

    def test_la_version_d_odoo_atteint_le_chemin_de_l_executable(self):
        """ODOO_EXEC_BIN est lu à l'exécution : un chemin figé sur une autre
        version ne se voit qu'au démarrage du conteneur."""
        arg = BASE.index("ARG ODOO_VERSION")
        exec_bin = BASE.index("ENV ODOO_EXEC_BIN")
        self.assertLess(arg, exec_bin)
        self.assertIn("ENV ODOO_VERSION=${ODOO_VERSION}", BASE)

    def test_la_prod_ne_redeclare_pas_la_version_d_odoo(self):
        """Un ENV hérité l'emporte sur un ARG de même nom : le redéclarer
        pose une valeur inerte que l'image contredit sans le dire."""
        self.assertNotIn("ARG ODOO_VERSION", PROD)


if __name__ == "__main__":
    unittest.main()
