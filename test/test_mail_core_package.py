#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le paquet du noyau des règles : son projet installable, ses modules, et
ce que son import ne touche pas — ni le client, ni sa configuration, ni le
`HOME`, sous le Python d'ERPLibre comme sous celui d'Odoo.

N'importe que la bibliothèque standard.
"""

import ast
import importlib
import json
import os
import pkgutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import tomllib

RACINE = Path(__file__).resolve().parent.parent
PROJET = RACINE / "script" / "lib" / "erplibre_mail_core"
PAQUET = PROJET / "erplibre_mail_core"
if str(PROJET) not in sys.path:
    sys.path.insert(0, str(PROJET))

EXPECTED_MODULES = {
    "erplibre_mail_core",
    "erplibre_mail_core.i18n",
    "erplibre_mail_core.catalog",
    "erplibre_mail_core.zone",
    "erplibre_mail_core.charset",
    "erplibre_mail_core.claim",
    "erplibre_mail_core.mailtext",
    "erplibre_mail_core.stats",
    "erplibre_mail_core.smtp",
    "erplibre_mail_core.imap",
    "erplibre_mail_core.rules",
    "erplibre_mail_core.rules.model",
    "erplibre_mail_core.rules.filter",
    "erplibre_mail_core.rules.regex_worker",
    "erplibre_mail_core.rules.guards",
    "erplibre_mail_core.rules.markup",
    "erplibre_mail_core.rules.report",
}
# Les modules que l'import du noyau ne doit jamais charger : le client,
# son interface, son stockage, ses dépendances, et `markdown_it`, chargé à
# l'usage seulement.
INTERDITS = (
    "script",
    "todo_i18n",
    "textual",
    "rich",
    "sqlite3",
    "_sqlite3",
    "cryptography",
    "pykeepass",
    "markdown_it",
)
CLIENT = ("script", "todo_i18n", "textual")
# Le sous-processus qui importe tout le noyau et rapporte, en JSON, les
# modules chargés, les chemins ouverts, listés ou passés à stat, et la
# langue du noyau.
CODE = r"""
import json, os, sys
notes = []
def ecoute(evenement, args):
    if evenement == "open" and args and isinstance(args[0], (str, bytes)):
        notes.append(os.fsdecode(args[0]))
    elif evenement in ("os.listdir", "os.scandir") and args:
        if isinstance(args[0], (str, bytes)):
            notes.append(os.fsdecode(args[0]))
sys.addaudithook(ecoute)
def enveloppe(fonction):
    def note(chemin, *a, **k):
        if isinstance(chemin, (str, bytes, os.PathLike)):
            notes.append(os.fsdecode(chemin))
        return fonction(chemin, *a, **k)
    return note
os.stat = enveloppe(os.stat)
os.lstat = enveloppe(os.lstat)
sys.path.insert(0, sys.argv[1])
import importlib
for nom in json.loads(sys.argv[2]):
    importlib.import_module(nom)
from erplibre_mail_core import i18n
print(json.dumps({
    "modules": sorted(sys.modules),
    "chemins": notes,
    "langue": i18n.current_lang(),
    "texte": i18n.t("mail_rules_err_kind"),
}))
"""


def interpretes_odoo() -> list[Path]:
    return sorted(
        p
        for p in RACINE.glob(".venv.odoo*/bin/python")
        if os.access(p, os.X_OK)
    )


def importe_tout(python: str, test: unittest.TestCase) -> dict:
    """Lance CODE sous `python`, `-I -S -B`, dans un dossier qui porte un
    `env_var.sh` anglais et un `HOME` temporaire ; rend son rapport."""
    with tempfile.TemporaryDirectory() as dossier:
        travail = Path(dossier) / "travail"
        home = Path(dossier) / "home"
        travail.mkdir()
        home.mkdir()
        (travail / "env_var.sh").write_text('EL_LANG="en"\n')
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "EL_LANG": "en",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        sortie = subprocess.run(
            [
                python,
                "-I",
                "-S",
                "-B",
                "-c",
                CODE,
                str(PROJET),
                json.dumps(sorted(EXPECTED_MODULES)),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=travail,
            env=env,
        )
        test.assertEqual(sortie.returncode, 0, sortie.stderr)
        rapport = json.loads(sortie.stdout)
        rapport["home"] = str(home)
        return rapport


def verifie_rapport(test: unittest.TestCase, rapport: dict) -> None:
    for module in rapport["modules"]:
        racine = module.split(".", 1)[0]
        test.assertNotIn(racine, INTERDITS, module)
    for chemin in rapport["chemins"]:
        test.assertFalse(chemin.endswith("env_var.sh"), chemin)
        test.assertFalse(
            os.path.abspath(chemin).startswith(rapport["home"]), chemin
        )
    # L'environnement dit anglais : le noyau ne le lit pas et garde son
    # défaut, le français.
    test.assertEqual(rapport["langue"], "fr")
    from erplibre_mail_core.catalog import CATALOG

    test.assertEqual(rapport["texte"], CATALOG["mail_rules_err_kind"]["fr"])


def imports_de(chemin: Path) -> list[str]:
    noms = []
    for noeud in ast.walk(ast.parse(chemin.read_text(encoding="utf-8"))):
        if isinstance(noeud, ast.Import):
            noms += [alias.name for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            noms.append(noeud.module)
    return noms


class TestPackage(unittest.TestCase):
    def test_pyproject_declares_the_package(self):
        with open(PROJET / "pyproject.toml", "rb") as fichier:
            donnees = tomllib.load(fichier)
        projet = donnees["project"]
        self.assertEqual(projet["name"], "erplibre-mail-core")
        self.assertEqual(projet["requires-python"], ">=3.12")
        self.assertEqual(projet["dependencies"], [])
        self.assertEqual(projet["dynamic"], ["version"])
        outils = donnees["tool"]["setuptools"]
        self.assertEqual(
            outils["dynamic"]["version"],
            {"attr": "erplibre_mail_core.__version__"},
        )
        self.assertEqual(
            outils["packages"]["find"]["include"],
            ["erplibre_mail_core", "erplibre_mail_core.*"],
        )

    def test_every_module_is_listed_and_imports(self):
        import erplibre_mail_core

        trouves = {"erplibre_mail_core"} | {
            info.name
            for info in pkgutil.walk_packages(
                erplibre_mail_core.__path__, "erplibre_mail_core."
            )
        }
        self.assertEqual(trouves, EXPECTED_MODULES)
        for nom in sorted(EXPECTED_MODULES):
            with self.subTest(module=nom):
                importlib.import_module(nom)

    def test_only_the_package_is_importable_at_its_root(self):
        """La racine du projet passe en tête de `sys.path` : un `test.py`
        ou un `setup.py` posé là masquerait la bibliothèque standard."""
        for entree in PROJET.iterdir():
            if entree.name == "erplibre_mail_core":
                continue
            with self.subTest(entree=entree.name):
                self.assertFalse(entree.suffix == ".py", entree)
                self.assertFalse(
                    entree.is_dir() and (entree / "__init__.py").exists(),
                    entree,
                )

    def test_import_loads_nothing_of_the_client(self):
        verifie_rapport(self, importe_tout(sys.executable, self))

    def test_core_imports_name_nothing_of_the_client(self):
        for chemin in sorted(PAQUET.rglob("*.py")):
            for nom in imports_de(chemin):
                with self.subTest(fichier=chemin.name, module=nom):
                    self.assertNotIn(nom.split(".", 1)[0], CLIENT)

    def test_core_tests_import_nothing_of_the_client(self):
        interdits = CLIENT + ("mail_sandbox", "mail_cache_fixtures")
        for chemin in sorted((RACINE / "test").glob("test_mail_core_*.py")):
            if chemin.name == "test_mail_core_bridge.py":
                continue
            for nom in imports_de(chemin):
                with self.subTest(fichier=chemin.name, module=nom):
                    self.assertNotIn(nom.split(".", 1)[0], interdits)


@unittest.skipUnless(interpretes_odoo(), "aucun venv Odoo dans ce checkout")
class OdooPythonCase(unittest.TestCase):
    """Le noyau sous le Python du venv d'Odoo, sans écrire de bytecode."""

    def interpretes(self):
        """Chaque Python d'Odoo assez récent ; un plus ancien que le
        plancher de `requires-python` est sauté avec sa raison."""
        for python in interpretes_odoo():
            version = subprocess.run(
                [
                    str(python),
                    "-I",
                    "-S",
                    "-c",
                    "import sys; print('%d.%d' % sys.version_info[:2])",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout.strip()
            with self.subTest(python=str(python)):
                majeur, mineur = (int(x) for x in version.split("."))
                if (majeur, mineur) < (3, 12):
                    self.skipTest(f"Python {version} : sous requires-python")
                yield python

    def bytecode(self):
        return sorted(str(p) for p in PROJET.rglob("*.cpython-312*.pyc"))

    def test_core_imports_under_the_odoo_python(self):
        for python in self.interpretes():
            avant = self.bytecode()
            verifie_rapport(self, importe_tout(str(python), self))
            self.assertEqual(self.bytecode(), avant)

    def test_core_suite_passes_under_the_odoo_python(self):
        fichiers = [
            p
            for p in sorted((RACINE / "test").glob("test_mail_core_*.py"))
            if p.name
            not in ("test_mail_core_package.py", "test_mail_core_bridge.py")
        ]
        self.assertTrue(fichiers)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("PYTHONPATH", None)
        for python in self.interpretes():
            avant = self.bytecode()
            fin = time.monotonic() + 200
            for fichier in fichiers:
                with self.subTest(fichier=fichier.name):
                    reste = fin - time.monotonic()
                    self.assertGreater(reste, 0, "budget épuisé")
                    sortie = subprocess.run(
                        [str(python), "-B", str(fichier)],
                        capture_output=True,
                        text=True,
                        timeout=reste,
                        cwd=RACINE,
                        env=env,
                    )
                    self.assertEqual(
                        sortie.returncode, 0, sortie.stderr[-2000:]
                    )
            self.assertEqual(self.bytecode(), avant)


if __name__ == "__main__":
    unittest.main()
