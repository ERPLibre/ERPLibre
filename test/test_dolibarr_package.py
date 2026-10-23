#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'empaquetage d'un module Dolibarr et ses précontrôles DoliStore.

Un module réduit dans custom/ ; le shell et git réels servent l'inventaire
et le cœur, un système simulé joue PHP (descripteur, php -l). Ce qui se
garde :
- le zip porte le nom et le contenu de « Générer le paquet » du
  ModuleBuilder : module_<nom>-<version>.zip dans bin/, le dossier du
  module à la racine, ses exclusions jugées DANS le module ;
- un descripteur illisible, un nom de paquet que Dolibarr refuserait ou
  une erreur de syntaxe PHP empêchent le zip ;
- les règles DoliStore (numéro réservé, en_US complet, inclusions de
  main.inc.php, scripts, copie du cœur) échouent au contrôle, et
  n'empêchent le zip qu'avec --dolistore ;
- la marque « Dolibarr » et un éditeur absent ne sont que des avis.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import package  # noqa: E402

PAGE = (
    "<?php\n$res = 0;\n"
    'if (!$res && file_exists("../main.inc.php")) '
    '{ $res = @include "../main.inc.php"; }\n'
    'if (!$res && file_exists("../../main.inc.php")) '
    '{ $res = @include "../../main.inc.php"; }\n'
)
COEUR = "<?php\nfunction coeur_partage() { return 42; }\n"


def ecrire(racine, fichiers):
    for chemin, texte in fichiers.items():
        p = Path(racine) / chemin
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte)


def git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


class Systeme:
    """Le shell et git réels ; PHP joué : le descripteur rend `faits`,
    php -l rend `lint`."""

    def __init__(self):
        self.appels = []
        self.faits = {
            "version": "1.0",
            "numero": 123456,
            "editor_name": "Ada Lovelace",
            "editor_url": "https://example.org",
        }
        self.lint = ""
        self.code_php = 0
        self.inventaire = None

    def run(self, argv, env=None, stdin_path=None):
        self.appels.append(list(argv))
        texte = " ".join(argv)
        if "ERPLIBRE_PACKAGE" in texte:
            if self.faits is None:
                return 255, "PHP Fatal error: Class not found"
            return self.code_php, (
                "ERPLIBRE_PACKAGE " + json.dumps(self.faits) + "\n"
            )
        if "ERPLIBRE_LINT_DONE" in texte:
            if self.lint is None:
                return 125, "Error: container state improper"
            return 0, self.lint + "ERPLIBRE_LINT_DONE\n"
        if self.inventaire is not None and "ERPLIBRE_MODULES" in texte:
            return 0, self.inventaire
        r = subprocess.run(argv, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def engine(self, moteur):
        return {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.checkout = self.racine / "dolibarr"
        self.htdocs = self.checkout / "htdocs"
        ecrire(
            self.htdocs,
            {
                "core/modules/modProduct.class.php": (
                    "<?php\n$this->numero = 50;\n"
                ),
                "core/lib/partage.lib.php": COEUR,
                "COPYING": "GNU GENERAL PUBLIC LICENSE\n",
            },
        )
        git("init", "-q", cwd=self.checkout)
        git("add", ".", cwd=self.checkout)
        git("commit", "-q", "-m", "coeur", cwd=self.checkout)
        self.module = self.htdocs / "custom" / "zorglub"
        ecrire(
            self.module,
            {
                "core/modules/modZorglub.class.php": (
                    "<?php\nclass modZorglub {\n$this->numero = 123456;\n}\n"
                ),
                "zorglubindex.php": PAGE,
                "admin/setup.php": PAGE,
                "langs/en_US/zorglub.lang": "Module123456Name = Zorglub\nA = a\n",
                "langs/fr_FR/zorglub.lang": "# commentaire\nA = a\n",
                "scripts/zorglub.php": "#!/usr/bin/env php\n<?php\n",
                "test/phpunit/ZorglubTest.php": (
                    '<?php\nrequire "../../main.inc.php";\n'
                ),
                "bin/module_zorglub-0.9.zip": "vieux",
                ".gitignore": "/bin\n",
                ".editorconfig": "root = true\n",
                "notes.old": "x",
                "README.md": "# Zorglub\n",
                "COPYING": "GNU GENERAL PUBLIC LICENSE\n",
            },
        )
        os.symlink("README.md", self.module / "LISEZMOI.md")
        os.symlink("absent.md", self.module / "casse.md")
        (self.racine / "ailleurs").mkdir()
        os.symlink(self.racine / "ailleurs", self.module / "lien_dossier")
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "code_root": str(self.checkout),
            "data_root": str(self.racine / "etat" / "documents"),
            "state_dir": str(self.racine / "etat"),
        }
        self.sys = Systeme()

    def lancer(self, *argv, entree=None):
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True, exist_ok=True)
        registre.write_text(
            json.dumps({"instances": {"erp": entree or self.entree}})
        )
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = package.main(
                list(argv), root=str(self.racine), system=self.sys
            )
        return code, sortie.getvalue()

    def zip(self, version="1.0"):
        return self.module / "bin" / f"module_zorglub-{version}.zip"


class TestNom(unittest.TestCase):
    def test_the_version_is_cut_as_the_modulebuilder_cuts_it(self):
        for version, attendu in (
            ("1.0", "1.0"),
            ("2", "2.0"),
            ("2.3.1", "2.3.1"),
            ("1.0.0", "1.0"),
            ("1.2.3.4", "1.2.3.4"),
        ):
            self.assertEqual(
                package.zip_name("zorglub", version),
                f"module_zorglub-{attendu}.zip",
                version,
            )

    def test_a_word_version_gives_a_name_dolibarr_refuses(self):
        nom = package.zip_name("zorglub", "development")
        self.assertIsNone(package.DEPLOY_NAME.match(nom))
        self.assertIsNotNone(
            package.DEPLOY_NAME.match(package.zip_name("zorglub", "1.2"))
        )


class TestMarque(unittest.TestCase):
    def test_dolibarr_as_a_word_of_the_name_is_flagged(self):
        self.assertEqual(
            package.trademark(["ZorglubDolibarr", "Dolibarr", "Zorglub"]),
            ["ZorglubDolibarr", "Dolibarr"],
        )

    def test_a_preposition_a_mention_or_a_portmanteau_is_allowed(self):
        self.assertEqual(
            package.trademark(
                ["SyncForDolibarr", "Zorglub for Dolibarr", "DoliZorglub"]
                + ["ImportFromDolibarr", "Zorglub Dolibarr (non official)"]
            ),
            [],
        )


class TestCoeur(unittest.TestCase):
    def test_the_modulebuilder_template_is_not_core(self):
        # Le gabarit est fait pour être copié : buildzip.php en sort
        # identique.
        arbre = (
            "100644 blob aaa\thtdocs/core/lib/functions.lib.php\n"
            "100644 blob bbb\thtdocs/modulebuilder/template/build/buildzip.php\n"
            "040000 tree ccc\thtdocs/core\n"
        )
        self.assertEqual(package.core_blobs(arbre), {"aaa"})


class TestContenu(unittest.TestCase):
    def test_exclusions_are_judged_inside_the_module(self):
        # Sur le chemin réel, un dossier parent en .git viderait le zip.
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "depot.git" / "zorglub"
            ecrire(module, {"a.php": "x", "bin/z.zip": "x", "b.back": "x"})
            self.assertEqual(
                [a for a, _p in package.members(str(module))], ["a.php"]
            )


class TestConstruction(Banc):
    def test_build_writes_the_modulebuilder_package(self):
        code, sortie = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub"
        )
        self.assertEqual(code, 0, sortie)
        self.assertIn(str(self.zip()), sortie)
        with zipfile.ZipFile(self.zip()) as z:
            noms = sorted(z.namelist())
            self.assertEqual(z.read("zorglub/LISEZMOI.md"), b"# Zorglub\n")
        self.assertEqual(
            noms,
            [
                "zorglub/.editorconfig",
                "zorglub/COPYING",
                "zorglub/LISEZMOI.md",
                "zorglub/README.md",
                "zorglub/admin/setup.php",
                "zorglub/core/modules/modZorglub.class.php",
                "zorglub/langs/en_US/zorglub.lang",
                "zorglub/langs/fr_FR/zorglub.lang",
                "zorglub/scripts/zorglub.php",
                "zorglub/test/phpunit/ZorglubTest.php",
                "zorglub/zorglubindex.php",
            ],
        )

    def test_a_php_syntax_error_blocks_the_package(self):
        self.sys.lint = "ERPLIBRE_LINT ./admin/setup.php: Parse error\n"
        code, sortie = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub"
        )
        self.assertEqual(code, 1)
        self.assertIn("admin/setup.php", sortie)
        self.assertFalse(self.zip().exists())

    def test_a_word_version_blocks_the_package(self):
        self.sys.faits["version"] = "development"
        code, sortie = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub"
        )
        self.assertEqual(code, 1)
        self.assertFalse(list((self.module / "bin").glob("*development*")))

    def test_an_unreadable_descriptor_blocks_the_package(self):
        self.sys.faits = None
        code, sortie = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub"
        )
        self.assertEqual(code, 1)
        self.assertIn("Class not found", sortie)

    def test_php_failing_after_its_answer_blocks_the_package(self):
        self.sys.code_php = 255
        code, _s = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub"
        )
        self.assertEqual(code, 1)
        self.assertFalse(self.zip().exists())

    def test_a_lint_that_cannot_run_blocks_the_package(self):
        self.sys.lint = None
        code, sortie = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub"
        )
        self.assertEqual(code, 1)
        self.assertIn("container state improper", sortie)
        self.assertFalse(self.zip().exists())

    def test_a_private_id_builds_but_is_not_ready_for_dolistore(self):
        self.sys.faits["numero"] = 500123
        code, sortie = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub"
        )
        self.assertEqual(code, 0, sortie)
        self.assertTrue(self.zip().exists())
        self.assertIn("500123", sortie)
        self.zip().unlink()
        code, _s = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub", "--dolistore"
        )
        self.assertEqual(code, 1)
        self.assertFalse(self.zip().exists())


class TestControle(Banc):
    def controler(self):
        return self.lancer("check", "--instance", "erp", "--name", "Zorglub")

    def test_a_ready_module_passes_and_writes_nothing(self):
        code, sortie = self.controler()
        self.assertEqual(code, 0, sortie)
        self.assertNotIn("✗", sortie)
        self.assertFalse(self.zip().exists())

    def test_the_id_ranges(self):
        for numero, bon in (
            (95000, True),
            (99999, True),
            (100000, True),
            (499999, True),
            (94999, False),
            (500000, False),
        ):
            self.sys.faits["numero"] = numero
            code, sortie = self.controler()
            self.assertEqual(code, 0 if bon else 1, (numero, sortie))

    def test_en_us_must_hold_every_key(self):
        ecrire(self.module, {"langs/fr_FR/zorglub.lang": "A = a\nB = b\n"})
        code, sortie = self.controler()
        self.assertEqual(code, 1)
        self.assertIn("B", sortie.split("en_US", 1)[1])

    def test_en_us_is_mandatory(self):
        (self.module / "langs" / "en_US" / "zorglub.lang").unlink()
        (self.module / "langs" / "fr_FR" / "zorglub.lang").unlink()
        code, sortie = self.controler()
        self.assertEqual(code, 1)
        self.assertIn("en_US", sortie)

    def test_a_page_with_a_single_include_fails(self):
        ecrire(
            self.module,
            {"admin/setup.php": '<?php\nrequire_once "../../main.inc.php";\n'},
        )
        code, sortie = self.controler()
        self.assertEqual(code, 1)
        self.assertIn("admin/setup.php", sortie)
        self.assertNotIn("ZorglubTest.php", sortie)

    def test_a_script_without_its_shebang_fails(self):
        ecrire(self.module, {"scripts/zorglub.php": "<?php\n"})
        code, sortie = self.controler()
        self.assertEqual(code, 1)
        self.assertIn("scripts/zorglub.php", sortie)

    def test_a_copy_of_a_core_file_fails(self):
        ecrire(self.module, {"lib/partage.lib.php": COEUR})
        code, sortie = self.controler()
        self.assertEqual(code, 1)
        self.assertIn("lib/partage.lib.php", sortie)

    def avis(self, sortie):
        return [
            ligne for ligne in sortie.splitlines() if ligne.startswith("  ! ")
        ]

    def test_the_trademark_is_only_a_warning(self):
        ecrire(
            self.module,
            {
                "langs/en_US/zorglub.lang": (
                    "Module123456Name = Zorglub Dolibarr\nA = a\n"
                )
            },
        )
        code, sortie = self.controler()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(len(self.avis(sortie)), 1, sortie)
        self.assertIn("Zorglub Dolibarr", self.avis(sortie)[0])

    def test_an_empty_editor_url_is_only_a_warning(self):
        self.sys.faits["editor_url"] = ""
        code, sortie = self.controler()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(len(self.avis(sortie)), 1, sortie)

    def test_without_a_git_checkout_core_copies_are_not_checked(self):
        shutil.rmtree(self.checkout / ".git")
        ecrire(self.module, {"lib/partage.lib.php": COEUR})
        code, sortie = self.controler()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(len(self.avis(sortie)), 1, sortie)


class TestRefus(Banc):
    def test_production_is_refused(self):
        prod = dict(self.entree, mode="prod", user="dolibarr_erp")
        code, _s = self.lancer(
            "check", "--instance", "erp", "--name", "Zorglub", entree=prod
        )
        self.assertEqual(code, 2)

    def test_an_unknown_module_is_refused(self):
        code, _s = self.lancer("check", "--instance", "erp", "--name", "Rien")
        self.assertEqual(code, 2)

    def test_a_core_module_is_not_packaged(self):
        code, _s = self.lancer(
            "check", "--instance", "erp", "--name", "Product"
        )
        self.assertEqual(code, 2)


class TestConteneur(Banc):
    def test_php_runs_in_the_container_and_the_zip_lands_on_the_host(self):
        custom = self.racine / "etat" / "custom"
        os.makedirs(custom.parent, exist_ok=True)
        os.rename(self.htdocs / "custom", custom)
        self.module = custom / "zorglub"
        self.sys.inventaire = (
            "core\ncustom\nERPLIBRE_MODULES\n"
            "custom/zorglub/core/modules/modZorglub.class.php:numero = 123456\n"
            "ERPLIBRE_END\n"
        )
        entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "containers": ["x-db", "x-web", "x-cron"],
            "state_dir": str(self.racine / "etat"),
            "custom_dir": str(custom),
        }
        code, sortie = self.lancer(
            "build", "--instance", "erp", "--name", "Zorglub", entree=entree
        )
        self.assertEqual(code, 0, sortie)
        self.assertTrue(self.zip().exists())
        php = [a for a in self.sys.appels if "ERPLIBRE_PACKAGE" in " ".join(a)]
        self.assertEqual(
            php[0][:5], ["podman", "exec", "-u", "www-data", "x-web"]
        )
        lint = [
            a for a in self.sys.appels if "ERPLIBRE_LINT_DONE" in " ".join(a)
        ]
        self.assertIn("/var/www/html/custom/zorglub", " ".join(lint[0]))
        # Pas de checkout épinglé ici : la copie du cœur n'est pas vérifiée,
        # et le contrôle le dit.
        self.assertIn("!", sortie)


VRAI = RACINE / "dolibarr" / "dolibarr"


@unittest.skipUnless((VRAI / ".git").exists(), "checkout Dolibarr absent")
class TestGabaritReel(unittest.TestCase):
    def test_a_fresh_modulebuilder_module_raises_no_false_alarm(self):
        from script.dolibarr import module

        r = subprocess.run(
            ["git", "-C", str(VRAI), "ls-tree", "-r", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        blobs = package.core_blobs(r.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "zorglub"
            module.generate(
                str(VRAI / "htdocs" / "modulebuilder" / "template"),
                str(dest),
                "Zorglub",
                module.substitutions(
                    "Zorglub", 123456, "2026", "Ada", "", "1.0", "fa-file"
                ),
            )
            self.assertEqual(package.lang_gaps(str(dest)), {})
            self.assertEqual(package.single_includes(str(dest)), [])
            self.assertEqual(package.bad_scripts(str(dest)), [])
            self.assertEqual(package.core_copies(str(dest), blobs), [])
            self.assertEqual(package.trademark(["Zorglub"]), [])


if __name__ == "__main__":
    unittest.main()
