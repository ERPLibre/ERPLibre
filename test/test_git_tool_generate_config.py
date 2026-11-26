#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""GitTool.generate_generate_config : chaque chemin entre une seule fois
dans addons_path.

La ligne d'en-tête porte déjà odoo<V>/addons/addons ; un manifeste qui
déclare ce chemin ne doit pas le réécrire dans la liste des dépôts. Le
fichier réécrit est une copie réduite de script/generate_config.sh, dans un
dossier jetable ; les dépôts viennent d'un get_repo_info remplacé.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.git.git_tool import GitTool  # noqa: E402

GABARIT = """\
printf "addons_path = ancien," >> "${EL_CONFIG_FILE}"

if [[ ${EL_MINIMAL_ADDONS} = "False" ]]; then
    printf "${EL_HOME_ODOO_PROJECT}/addons/ancien," >> "${EL_CONFIG_FILE}"
fi
"""


class Generateur(unittest.TestCase):
    def generer(self, chemins, manifestes=None, **kwargs):
        """Réécrit le gabarit pour les dépôts `chemins` ; rend le
        addons_path que le script écrirait, une entrée par élément.
        `manifestes` : {nom de fichier: chemins de projet} écrits dans
        manifest/."""
        with tempfile.TemporaryDirectory() as racine:
            os.makedirs(os.path.join(racine, "script"))
            os.makedirs(os.path.join(racine, "manifest"))
            for nom, projets in (manifestes or {}).items():
                Path(racine, "manifest", nom).write_text(
                    "<manifest>"
                    + "".join(f'<project path="{c}"/>' for c in projets)
                    + "</manifest>"
                )
            fichier = os.path.join(racine, "script", "generate_config.sh")
            Path(fichier).write_text(GABARIT)
            outil = GitTool.__new__(GitTool)
            with (
                mock.patch.object(
                    GitTool,
                    "odoo_version_long",
                    new_callable=mock.PropertyMock,
                    return_value="odoo18.0",
                ),
                mock.patch.object(
                    GitTool,
                    "get_repo_info",
                    return_value=[{"path": c} for c in chemins],
                ),
                mock.patch("sys.stdout"),
            ):
                outil.generate_generate_config(repo_path=racine, **kwargs)
            texte = Path(fichier).read_text()
        env = {
            "EL_HOME": "/r",
            "EL_ODOO_VERSION": "18.0",
            "EL_HOME_ODOO": "/r/odoo18.0/odoo",
            "EL_HOME_ODOO_PROJECT": "/r/odoo18.0",
        }
        entrees = []
        for ligne in texte.splitlines():
            ligne = ligne.strip()
            if not ligne.startswith('printf "'):
                continue
            valeur = ligne[len('printf "') :].split('"', 1)[0]
            valeur = valeur.replace("addons_path = ", "")
            for nom, chemin in env.items():
                valeur = valeur.replace(f"${{{nom}}}", chemin)
            entrees += [e for e in valeur.split(",") if e]
        return entrees


class TestAddonsPathSansDoublon(Generateur):
    def test_addons_addons_declared_by_a_manifest_appears_once(self):
        entrees = self.generer(
            [
                "odoo18.0/addons/OCA_sign",
                "odoo18.0/addons/addons",
                "odoo18.0/addons/OCA_web",
            ]
        )
        self.assertEqual(entrees.count("/r/odoo18.0/addons/addons"), 1)
        self.assertIn("/r/odoo18.0/addons/OCA_sign", entrees)
        self.assertEqual(len(entrees), len(set(entrees)))

    def test_without_the_odoo_header_the_manifest_path_stays(self):
        entrees = self.generer(
            ["odoo18.0/addons/addons"], ignore_odoo_path=True
        )
        self.assertEqual(entrees, ["/r/odoo18.0/addons/addons"])

    def test_an_extra_path_already_listed_is_not_repeated(self):
        entrees = self.generer(
            ["odoo18.0/addons/OCA_sign"],
            extra_path="/x/extra,/x/extra",
        )
        self.assertEqual(entrees.count("/x/extra"), 1)

    def test_a_repository_listed_twice_appears_once(self):
        entrees = self.generer(
            ["odoo18.0/addons/OCA_sign", "odoo18.0/addons/OCA_sign"]
        )
        self.assertEqual(entrees.count("/r/odoo18.0/addons/OCA_sign"), 1)


class TestLesExtrasRestentHorsDuFichierSuivi(Generateur):
    """Le fichier réécrit est suivi par git : un projet que seul le
    manifeste extra déclare n'y entre pas, même quand le checkout l'a
    synchronisé."""

    MANIFESTES = {
        "git_manifest_odoo18.0.xml": [
            "odoo18.0/addons/OCA_sign",
            "odoo18.0/addons/Exemple_commun",
        ],
        "git_manifest_extra_odoo18.0.xml": [
            "odoo18.0/addons/Exemple_extra",
            "odoo18.0/addons/Exemple_commun",
        ],
    }
    DEPOTS = [
        "odoo18.0/addons/OCA_sign",
        "odoo18.0/addons/Exemple_commun",
        "odoo18.0/addons/Exemple_extra",
    ]

    def test_an_extra_only_project_is_left_out(self):
        entrees = self.generer(self.DEPOTS, manifestes=self.MANIFESTES)
        self.assertNotIn("/r/odoo18.0/addons/Exemple_extra", entrees)
        self.assertIn("/r/odoo18.0/addons/OCA_sign", entrees)

    def test_a_project_of_both_manifests_stays(self):
        entrees = self.generer(self.DEPOTS, manifestes=self.MANIFESTES)
        self.assertIn("/r/odoo18.0/addons/Exemple_commun", entrees)

    def test_an_extra_named_by_add_repos_stays(self):
        entrees = self.generer(
            self.DEPOTS,
            manifestes=self.MANIFESTES,
            whitelist=["odoo18.0/addons/OCA_sign"],
            add_repos=["odoo18.0/addons/Exemple_extra"],
        )
        self.assertIn("/r/odoo18.0/addons/Exemple_extra", entrees)

    def test_without_an_extra_manifest_nothing_is_left_out(self):
        entrees = self.generer(self.DEPOTS)
        self.assertIn("/r/odoo18.0/addons/Exemple_extra", entrees)


if __name__ == "__main__":
    unittest.main()
