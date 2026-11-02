#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'image prod clone-t-elle chaque dépôt sur son freeze-revision ?

Le Dockerfile ne choisit pas les révisions : il appelle
script/manifest/update_manifest_local_dev.sh, directement et par
update_env_version.py, et ce script lit EL_FREEZE et EL_FREEZE_STRICT dans
l'environnement. Un ARG est dans l'environnement de chaque RUN qui le suit,
et ne reste pas dans l'image.

Ce que ces tests gardent :

- le gel et le refus d'un projet sans gel sont la règle par défaut, posés
  avant le premier appel au script de manifeste ;
- seul « docker_build.sh --branches » remet les branches ;
- le script de manifeste traduit EL_FREEZE_STRICT en --strict, et s'arrête
  quand la fusion refuse, au lieu de synchroniser l'ancien manifeste local.
"""

import re
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PROD = (RACINE / "docker/Dockerfile.prod.pkg").read_text(encoding="utf-8")
BUILD = (RACINE / "script/docker/docker_build.sh").read_text(encoding="utf-8")
MANIFESTE = RACINE / "script/manifest/update_manifest_local_dev.sh"


class TestDockerfile(unittest.TestCase):
    def test_gel_strict_par_defaut(self):
        self.assertIn("\nARG EL_FREEZE=1\n", PROD)
        self.assertIn("\nARG EL_FREEZE_STRICT=1\n", PROD)

    def test_pose_avant_le_premier_manifeste(self):
        premier = min(
            PROD.index("update_env_version.py"),
            PROD.index("update_manifest_local_dev.sh"),
        )
        self.assertLess(PROD.index("ARG EL_FREEZE=1"), premier)
        self.assertLess(PROD.index("ARG EL_FREEZE_STRICT=1"), premier)

    def test_jamais_en_env(self):
        """Un ENV suivrait le conteneur, où le gel n'a rien à décider."""
        self.assertNotRegex(PROD, r"(?m)^ENV EL_FREEZE")


class TestDockerBuild(unittest.TestCase):
    def test_branches_seulement_sur_demande(self):
        self.assertIn('elif [ "$arg" == "--branches" ]; then', BUILD)
        bloc = BUILD[BUILD.index('if [ "${SUR_BRANCHES}" == true ]; then') :]
        bloc = bloc[: bloc.index("\nfi\n")]
        self.assertIn("--build-arg EL_FREEZE=0", bloc)
        self.assertEqual(1, BUILD.count("EL_FREEZE="))
        self.assertIn("SUR_BRANCHES=false\n", BUILD)


class TestScriptDeManifeste(unittest.TestCase):
    def test_strict_devient_option_de_la_fusion(self):
        texte = MANIFESTE.read_text(encoding="utf-8")
        self.assertIn('if [ "${EL_FREEZE_STRICT:-0}" = "1" ]; then', texte)
        self.assertIn("MERGE_STRICT=(--strict)", texte)
        fusion = next(
            ligne
            for ligne in texte.splitlines()
            if "git_merge_repo_manifest.py" in ligne
            and not ligne.lstrip().startswith("#")
        )
        self.assertIn('"${MERGE_STRICT[@]}"', fusion)
        self.assertTrue(fusion.rstrip().endswith("|| exit 1"), fusion)

    def test_le_refus_de_la_fusion_precede_le_sync(self):
        texte = MANIFESTE.read_text(encoding="utf-8")
        self.assertLess(
            texte.index("git_merge_repo_manifest.py --output"),
            texte.index(".venv.erplibre/bin/repo sync"),
        )

    def test_syntaxe(self):
        sortie = subprocess.run(
            ["bash", "-n", str(MANIFESTE)], capture_output=True, text=True
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)


class TestManifestesCommuns(unittest.TestCase):
    """Les outils et docs communs à toutes les versions sont gelés : en
    mode strict, une image ne se construirait pas sans eux."""

    def test_chaque_projet_commun_porte_un_gel(self):
        for nom in (
            "git_manifest_erplibre_odoo.xml",
            "git_manifest_erplibre_odoo_dev.xml",
        ):
            texte = (RACINE / "manifest" / nom).read_text(encoding="utf-8")
            projets = re.findall(r"<project\b.*?/>", texte, re.S)
            self.assertTrue(projets, nom)
            for projet in projets:
                with self.subTest(fichier=nom, projet=projet.split()[1]):
                    self.assertRegex(projet, r'freeze-revision="[0-9a-f]{40}"')


if __name__ == "__main__":
    unittest.main()
