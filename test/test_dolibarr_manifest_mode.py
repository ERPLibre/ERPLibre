#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""update_manifest_local_dolibarr.sh garde le mode du checkout.

La fusion qu'il lance réécrit le manifeste local de tous les projets : sans
EL_FREEZE ni --freeze, elle doit regeler un checkout gelé et laisser un
checkout sur les branches les suivre. Le projet Dolibarr, épinglé par sa
source, ne fait pas à lui seul un checkout gelé.

Chaque test tourne dans une racine temporaire : le vrai script et le vrai
code Python (liens vers script/git, script/todo, script/version et le venv),
et un faux update_manifest_local_dev.sh qui écrit l'EL_FREEZE et les
arguments qu'il reçoit au lieu de synchroniser.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = "script/manifest/update_manifest_local_dolibarr.sh"
LOCAL = ".repo/local_manifests/erplibre_manifest.xml"
# Valeur inventée : ce commit n'existe dans aucun dépôt.
COMMIT = "0123456789abcdef0123456789abcdef01234567"
FAUX_DELEGUE = """#!/usr/bin/env bash
echo "EL_FREEZE=${EL_FREEZE:-}"
echo "ARGS=$*"
"""


@unittest.skipUnless(
    (RACINE / ".venv.erplibre/bin/python").exists(), "venv ERPLibre absent"
)
class TestModeGarde(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name)
        manifest = self.racine / "script/manifest"
        manifest.mkdir(parents=True)
        shutil.copy2(RACINE / SCRIPT, self.racine / SCRIPT)
        delegue = manifest / "update_manifest_local_dev.sh"
        delegue.write_text(FAUX_DELEGUE)
        delegue.chmod(0o755)
        (self.racine / "script/__init__.py").write_text("")
        for paquet in ("git", "todo", "version"):
            (self.racine / "script" / paquet).symlink_to(
                RACINE / "script" / paquet
            )
        (self.racine / ".venv.erplibre").symlink_to(RACINE / ".venv.erplibre")
        self.env = {
            k: v for k, v in os.environ.items() if not k.startswith("EL_")
        }

    def tearDown(self):
        self._tmp.cleanup()

    def local(self, *projets):
        chemin = self.racine / LOCAL
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            "<manifest>\n"
            + "".join(
                f'  <project name="{nom}.git" path="{chemin}"'
                f' revision="{revision}"/>\n'
                for nom, chemin, revision in projets
            )
            + "</manifest>\n"
        )

    def lancer(self, *args, **env):
        fait = subprocess.run(
            ["bash", SCRIPT, *args],
            cwd=self.racine,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        return fait.stdout.splitlines()

    def test_un_checkout_gele_le_reste(self):
        self.local(("a", "odooX.0/addons/a", COMMIT))
        self.assertEqual(self.lancer("-q"), ["EL_FREEZE=1", "ARGS=-q"])

    def test_un_checkout_sur_les_branches_les_suit(self):
        self.local(("a", "odooX.0/addons/a", "X.0"))
        self.assertEqual(self.lancer(), ["EL_FREEZE=", "ARGS="])

    def test_sans_manifeste_local_aucun_gel(self):
        self.assertEqual(self.lancer(), ["EL_FREEZE=", "ARGS="])

    def test_le_choix_de_l_appelant_l_emporte(self):
        self.local(("a", "odooX.0/addons/a", COMMIT))
        self.assertEqual(self.lancer(EL_FREEZE="0"), ["EL_FREEZE=0", "ARGS="])

    def test_dolibarr_epingle_ne_gele_pas_le_checkout(self):
        """Le vrai fragment Dolibarr, détecté par son checkout : son commit
        vient de la source et ne fait pas un checkout gelé."""
        for fichier in (
            "conf/git_manifest_dolibarr.csv",
            "manifest/git_manifest_dolibarr.xml",
        ):
            (self.racine / fichier).parent.mkdir(exist_ok=True)
            shutil.copy2(RACINE / fichier, self.racine / fichier)
        (self.racine / "dolibarr/dolibarr").mkdir(parents=True)
        source = (
            self.racine / "manifest/git_manifest_dolibarr.xml"
        ).read_text()
        epingle = source.split('revision="', 1)[1].split('"', 1)[0]
        self.local(
            ("a", "odooX.0/addons/a", "X.0"),
            ("dolibarr", "dolibarr/dolibarr", epingle),
        )
        self.assertEqual(self.lancer(), ["EL_FREEZE=", "ARGS="])


if __name__ == "__main__":
    unittest.main()
