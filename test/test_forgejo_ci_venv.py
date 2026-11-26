#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/forgejo/ci_venv.sh dans un arbre temporaire, sans Python à bâtir.

install_venv.sh et el_pip_install sont des doublures qui notent chaque
construction ; le cache vit dans un dossier temporaire (EL_CI_CACHE).

Propriétés gardées : un venv se bâtit une fois par clé (version de Python
et dépendances), se reprend ensuite, se rebâtit quand son marqueur manque ;
.venv.erplibre est un lien vers lui ; un vrai dossier .venv.erplibre est
refusé sans rien bâtir ; l'élagage garde EL_CI_VENV_KEEP venvs et
n'ôte jamais celui du job.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "script/forgejo/ci_venv.sh"
)
DOUBLURES = {
    "script/install/lib_non_interactive.sh": "el_non_interactive_env() { :; }\n",
    "script/install/lib_pip_provider.sh": (
        'el_pip_install() { echo "pip $*" >> "$JOURNAL"; }\n'
    ),
    "script/install/install_venv.sh": (
        "#!/bin/bash\n"
        'mkdir -p "$2/bin"\n'
        'echo "version = $3" > "$2/pyvenv.cfg"\n'
        "printf '#!/bin/sh\\nexit 0\\n' > \"$2/bin/python\"\n"
        'chmod +x "$2/bin/python"\n'
        'echo "build $2" >> "$JOURNAL"\n'
    ),
    "conf/python-erplibre-venv": ".venv.erplibre\n",
    "conf/python-erplibre-version": "3.12.0\n",
    "requirement/erplibre_require-ments.txt": "click\n",
}


class TestCiVenv(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = pathlib.Path(tmp.name) / "src"
        self.cache = pathlib.Path(tmp.name) / "cache"
        self.journal = pathlib.Path(tmp.name) / "journal"
        self.journal.touch()
        for chemin, contenu in DOUBLURES.items():
            f = self.racine / chemin
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(contenu)
            f.chmod(0o755)
        cible = self.racine / "script/forgejo/ci_venv.sh"
        cible.parent.mkdir(parents=True)
        shutil.copy(SCRIPT, cible)

    def lancer(self, **env):
        return subprocess.run(
            [str(self.racine / "script/forgejo/ci_venv.sh")],
            capture_output=True,
            text=True,
            cwd="/",
            env={
                **os.environ,
                "EL_CI_CACHE": str(self.cache),
                "JOURNAL": str(self.journal),
                **env,
            },
            timeout=60,
        )

    def constructions(self):
        return [
            ligne
            for ligne in self.journal.read_text().splitlines()
            if ligne.startswith("build ")
        ]

    def venvs(self):
        return sorted(
            p.name
            for p in (self.cache / "venv").iterdir()
            if p.is_dir() and (p / ".erplibre-ci-pret").exists()
        )

    def test_built_once_then_reused(self):
        self.assertEqual(self.lancer().returncode, 0)
        res = self.lancer()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.constructions()), 1)
        lien = self.racine / ".venv.erplibre"
        self.assertTrue(lien.is_symlink())
        cible = pathlib.Path(os.readlink(lien))
        self.assertEqual(cible.parent, self.cache / "venv")
        self.assertTrue(cible.name.startswith("3.12.0-"))
        self.assertIn(
            "-r requirement/erplibre_require-ments.txt",
            self.journal.read_text(),
        )

    def test_new_requirements_give_a_new_key(self):
        self.lancer()
        (self.racine / "requirement/erplibre_require-ments.txt").write_text(
            "click\nPyYAML\n"
        )
        self.assertEqual(self.lancer().returncode, 0)
        self.assertEqual(len(self.constructions()), 2)
        self.assertEqual(len(self.venvs()), 2)

    def test_pruning_keeps_the_current_venv(self):
        self.lancer()
        (ancien,) = self.venvs()
        marque = self.cache / "venv" / ancien / ".erplibre-ci-pret"
        os.utime(marque, (1, 1))
        (self.racine / "requirement/erplibre_require-ments.txt").write_text(
            "autre\n"
        )
        self.assertEqual(self.lancer(EL_CI_VENV_KEEP="1").returncode, 0)
        (courant,) = self.venvs()
        self.assertNotEqual(courant, ancien)
        self.assertEqual(
            os.readlink(self.racine / ".venv.erplibre"),
            str(self.cache / "venv" / courant),
        )

    def test_a_missing_marker_rebuilds(self):
        self.lancer()
        (venv,) = self.venvs()
        (self.cache / "venv" / venv / ".erplibre-ci-pret").unlink()
        self.assertEqual(self.lancer().returncode, 0)
        self.assertEqual(len(self.constructions()), 2)

    def test_a_real_venv_directory_is_refused(self):
        (self.racine / ".venv.erplibre").mkdir()
        res = self.lancer()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("lien", res.stderr)
        self.assertEqual(self.constructions(), [])

    def test_keeping_zero_is_refused(self):
        res = self.lancer(EL_CI_VENV_KEEP="0")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("EL_CI_VENV_KEEP", res.stderr)
        self.assertEqual(self.constructions(), [])


if __name__ == "__main__":
    unittest.main()
