#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les modules d'une instance de développement : créer, lier, activer.

Un gabarit réduit reprend ce que le vrai porte de significatif ; le shell
réel sert l'inventaire en natif, un système simulé joue PHP et le moteur de
conteneurs. Ce qui se garde :
- la création reproduit « Nouveau module » du ModuleBuilder : mêmes
  renommages, mêmes fichiers retirés, mêmes remplacements, dans le même
  ordre, et rien d'autre ;
- le numéro est le premier libre dès 500000, ou celui demandé s'il est
  libre et >= 100000 ;
- un nom pris (module du cœur, dossier de htdocs, dossier de custom/) est
  refusé avant toute écriture ;
- lier pose un lien symbolique nommé d'après le descripteur ;
- activer passe le nom exact de la classe à activateModule ;
- la liste des retraits suit celle du ModuleBuilder épinglé.
"""

import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import module  # noqa: E402

VRAI_HTDOCS = RACINE / "dolibarr" / "dolibarr" / "htdocs"
ANNEE = datetime.date.today().year

DESCRIPTEUR = """<?php
/* Copyright (C) ---Replace with your own copyright and developer email---
 */
class modMyModule extends DolibarrModules
{
	public function __construct($db)
	{
		$this->numero = 500000; // TODO reserve an id
		$this->rights_class = 'mymodule';
		$this->family = "other";
		$this->description = "MyModuleDescription";
		$this->editor_name = 'Editor name';
		$this->editor_url = 'https://www.example.com';
		$this->version = '1.0';
		$this->picto = 'generic';
		$this->module_parts = array('css' => array('/mymodule/css/mymodule.css.php'));
		$this->dirs = array("/mymodule/temp");
		$this->const = array(); // MYMODULE_MYNEWCONST1
		// My module / my module / Mon module / mon module
		// ---Put here your own copyright and developer email--- modulefamily
	}
}
"""


def gabarit(dest):
    """Un gabarit ModuleBuilder réduit : un fichier par règle en jeu."""
    fichiers = {
        "core/modules/modMyModule.class.php": DESCRIPTEUR,
        "core/modules/mymodule/mod_myobject_standard.php": "mymodule",
        "core/triggers/interface_50_modMyModule_MyModuleTriggers.class.php": "x",
        "admin/setup.php": "<?php // mymodule setup",
        "admin/myobject_extrafields.php": "x",
        "ajax/myobject.php": "x",
        "class/actions_mymodule.class.php": "x",
        "class/myobject.class.php": "x",
        "css/mymodule.css.php": "x",
        "lib/mymodule.lib.php": "<?php // MyModule lib",
        "lib/mymodule_myobject.lib.php": "x",
        "mymoduleindex.php": (
            "<?php\n *\t\\file       htdocs/modulebuilder/template/"
            "mymoduleindex.php\n"
        ),
        "myobject_card.php": "x",
        "sql/data.sql": "x",
        "sql/dolibarr_allversions.sql": "-- mymodule",
        "sql/llx_mymodule_myobject.sql": "x",
        "stats/myobject_index.php": "<?php // myobject MyObject",
        "test/phpunit/MyObjectTest.php": "x",
        "test/phpunit/functional/MyModuleFunctionalTest.php": "x",
        "langs/en_US/mymodule.lang": "Module500000Name = MyModule",
        "README.md": "# MyModule FOR DOLIBARR ERP & CRM",
        "COPYING": "mymodule",
        ".tx/config": "[o:dolibarr:p:dolibarr:r:mymodule]",
        ".tx/notes.txt": "mymodule",
        "img/mymodule.png": "mymodule",
    }
    for chemin, texte in fichiers.items():
        p = Path(dest) / chemin
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte)
    os.symlink("README.md", Path(dest) / "lien.md")


def descripteur(chemin, classe, numero):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        f"<?php\nclass {classe} {{\n\tpublic function __construct($db)\n"
        f"\t{{\n\t\t$this->numero = {numero};\n\t}}\n}}\n"
    )


class Systeme:
    """Le shell local pour l'inventaire natif ; PHP, git et le moteur de
    conteneurs sont joués."""

    def __init__(self, gabarit_source=None, inventaire=""):
        self.appels = []
        self.php_sortie = (0, "ERPLIBRE_MODULE_OK\n")
        self.gabarit_source = gabarit_source
        self.inventaire = inventaire
        self.git = {
            "user.name": "Ada Lovelace",
            "user.email": "ada@example.org",
        }

    def run(self, argv, env=None, stdin_path=None):
        self.appels.append(list(argv))
        texte = " ".join(argv)
        if "ERPLIBRE_MODULE_OK" in texte:
            return self.php_sortie
        if argv[:3] == ["git", "config", "--get"]:
            valeur = self.git.get(argv[3], "")
            return (0 if valeur else 1), valeur + ("\n" if valeur else "")
        if argv[:2] == ["podman", "exec"]:
            return 0, self.inventaire
        r = subprocess.run(argv, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def run_to_file(self, argv, path, env=None):
        """`cp <conteneur>:<dossier> -` : le dossier en tar sur la sortie."""
        self.appels.append(list(argv))
        with tarfile.open(path, "w") as tar:
            tar.add(self.gabarit_source, arcname="template")
        return 0, ""

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
        self.htdocs = self.racine / "dolibarr" / "htdocs"
        gabarit(self.htdocs / "modulebuilder" / "template")
        (self.htdocs / "theme").mkdir()
        (self.htdocs / "custom").mkdir()
        descripteur(
            self.htdocs / "core" / "modules" / "modProduct.class.php",
            "modProduct",
            50,
        )
        descripteur(
            self.htdocs / "core" / "modules" / "modHaut.class.php",
            "modHaut",
            500001,
        )
        descripteur(
            self.htdocs
            / "custom"
            / "autre"
            / "core"
            / "modules"
            / "modAutre.class.php",
            "modAutre",
            500000,
        )
        self.custom = self.htdocs / "custom"
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "code_root": str(self.racine / "dolibarr"),
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
            code = module.main(
                list(argv), root=str(self.racine), system=self.sys
            )
        return code, sortie.getvalue()

    def creer(self, *extra):
        return self.lancer(
            "create", "--instance", "erp", "--name", "Zorglub", *extra
        )

    def descripteur(self):
        chemin = self.custom / "zorglub" / "core" / "modules"
        return (chemin / "modZorglub.class.php").read_text()

    def arbre(self, racine):
        return sorted(
            str(p.relative_to(racine))
            for p in Path(racine).rglob("*")
            if p.is_file() or p.is_symlink()
        )

    def php(self):
        """Les appels PHP : en natif, php est dans la commande de sh -c."""
        appels = [" ".join(a) for a in self.sys.appels]
        return [a for a in appels if "ERPLIBRE_MODULE_OK" in a]


class TestNom(unittest.TestCase):
    def test_accents_are_dropped_and_the_first_letter_raised(self):
        self.assertEqual(module.normalize_name("écriture"), "Ecriture")
        self.assertEqual(module.normalize_name("myERP"), "MyERP")

    def test_spaces_and_signs_are_refused(self):
        for nom in ("my module", "foo-bar", "", "a/b", "ß"):
            with self.assertRaises(ValueError, msg=nom):
                module.normalize_name(nom)


class TestCreation(Banc):
    def test_create_keeps_what_the_modulebuilder_keeps(self):
        code, sortie = self.creer("--id", "500123")
        self.assertEqual(code, 0, sortie)
        dest = self.custom / "zorglub"
        self.assertEqual(
            self.arbre(dest),
            [
                ".tx/config",
                ".tx/notes.txt",
                "COPYING",
                "README.md",
                "admin/setup.php",
                "core/modules/modZorglub.class.php",
                "img/zorglub.png",
                "langs/en_US/zorglub.lang",
                "lib/zorglub.lib.php",
                "sql/dolibarr_allversions.sql",
                "stats/myobject_index.php",
                "zorglubindex.php",
            ],
        )
        # Le ModuleBuilder retire « functionnal » : functional/ reste, vide.
        self.assertTrue((dest / "test" / "phpunit" / "functional").is_dir())
        self.assertFalse((dest / "class").exists())

    def test_the_descriptor_gets_names_id_author_and_editor(self):
        self.creer("--id", "500123")
        texte = self.descripteur()
        for attendu in (
            "class modZorglub extends",
            "$this->numero = 500123; // TODO",
            "$this->rights_class = 'zorglub';",
            "'/zorglub/css/zorglub.css.php'",
            "// ZORGLUB_MYNEWCONST1",
            "// Zorglub / zorglub / Zorglub / zorglub",
            f"// {ANNEE}\t\tAda Lovelace\t\t\t\t<ada@example.org> other",
            "$this->editor_name = 'Ada Lovelace';",
            "$this->editor_url = '';",
            "$this->picto = 'fa-file';",
            "$this->version = '1.0';",
            # 31 - 12 caractères, en tabulations de 4 : 4.
            f"Copyright (C) {ANNEE}\t\tAda Lovelace\t\t\t\t<ada@example.org>",
        ):
            self.assertIn(attendu, texte)

    def test_the_template_path_becomes_the_module_path(self):
        self.creer()
        texte = (self.custom / "zorglub" / "zorglubindex.php").read_text()
        self.assertIn("\\file       zorglub/zorglubindex.php", texte)

    def test_hidden_files_and_other_extensions_keep_their_text(self):
        self.creer()
        dest = self.custom / "zorglub"
        self.assertIn("mymodule", (dest / ".tx" / "config").read_text())
        self.assertEqual((dest / ".tx" / "notes.txt").read_text(), "mymodule")
        self.assertEqual((dest / "COPYING").read_text(), "mymodule")
        self.assertEqual(
            (dest / "img" / "zorglub.png").read_text(), "mymodule"
        )
        self.assertIn("Zorglub", (dest / "README.md").read_text())

    def test_template_symlinks_are_not_copied(self):
        self.creer()
        self.assertFalse(os.path.lexists(self.custom / "zorglub" / "lien.md"))

    def test_the_first_free_id_from_500000(self):
        code, sortie = self.creer()
        self.assertEqual(code, 0, sortie)
        texte = self.descripteur()
        self.assertIn("$this->numero = 500002;", texte)
        self.assertIn("500002", sortie)

    def test_an_id_in_use_is_refused(self):
        code, sortie = self.creer("--id", "500000")
        self.assertEqual(code, 2)
        self.assertIn("modAutre", sortie)
        self.assertFalse((self.custom / "zorglub").exists())

    def test_an_id_below_100000_is_refused(self):
        code, _s = self.creer("--id", "99999")
        self.assertEqual(code, 2)
        self.assertFalse((self.custom / "zorglub").exists())

    def test_the_reserved_range_is_taken_with_a_warning(self):
        code, sortie = self.creer("--id", "100000")
        self.assertEqual(code, 0, sortie)
        self.assertIn("wiki", sortie)

    def test_a_name_taken_is_refused_before_any_write(self):
        for nom in ("product", "theme", "Autre", "custom"):
            code, sortie = self.lancer(
                "create", "--instance", "erp", "--name", nom
            )
            self.assertEqual(code, 2, nom)
        self.assertEqual(os.listdir(self.custom), ["autre"])

    def test_a_custom_directory_without_descriptor_is_refused(self):
        (self.custom / "zorglub").mkdir()
        code, sortie = self.creer()
        self.assertEqual(code, 2)
        self.assertEqual(os.listdir(self.custom / "zorglub"), [])

    def test_an_invalid_name_is_refused(self):
        code, _s = self.lancer(
            "create", "--instance", "erp", "--name", "mon module"
        )
        self.assertEqual(code, 2)

    def test_production_is_refused(self):
        prod = dict(self.entree, mode="prod", user="dolibarr_erp")
        code, sortie = self.lancer(
            "create", "--instance", "erp", "--name", "Zorglub", entree=prod
        )
        self.assertEqual(code, 2)
        self.assertFalse((self.custom / "zorglub").exists())

    def test_a_quote_in_the_editor_name_is_escaped(self):
        self.creer("--editor-name", "O'Neil")
        texte = self.descripteur()
        self.assertIn("$this->editor_name = 'O\\'Neil';", texte)

    def test_values_that_would_break_the_php_are_refused(self):
        for extra in (
            ("--version", "1.0'; x"),
            ("--picto", "a'b"),
            ("--editor-url", "javascript:x"),
            ("--author", "Ada */ x"),
            ("--editor-name", "Ada\nx"),
        ):
            code, _s = self.creer(*extra)
            self.assertEqual(code, 2, extra)
        self.assertFalse((self.custom / "zorglub").exists())

    def test_the_version_and_picto_are_written(self):
        self.creer("--version", "2.3.1", "--picto", "fa-star")
        texte = self.descripteur()
        self.assertIn("$this->version = '2.3.1';", texte)
        self.assertIn("$this->picto = 'fa-star';", texte)

    def test_the_author_comes_from_the_option_before_git(self):
        self.creer("--author", "Grace Hopper <grace@example.org>")
        texte = (self.custom / "zorglub" / "admin" / "setup.php").read_text()
        self.assertEqual(texte, "<?php // zorglub setup")
        texte = self.descripteur()
        self.assertIn(
            f"{ANNEE}\t\tGrace Hopper\t\t\t\t<grace@example.org>", texte
        )
        self.assertIn("$this->editor_name = 'Grace Hopper';", texte)

    def test_without_git_identity_the_year_stands_alone(self):
        self.sys.git = {}
        self.creer()
        texte = self.descripteur()
        self.assertIn(f"Copyright (C) {ANNEE}\t\t\n", texte)

    def test_a_failed_copy_leaves_nothing_behind(self):
        copie = shutil.copyfile
        appels = []

        def echoue(src, dst):
            appels.append(dst)
            if len(appels) == 3:
                raise OSError("disque plein")
            return copie(src, dst)

        with mock.patch.object(module.shutil, "copyfile", echoue):
            code, sortie = self.creer()
        self.assertEqual(code, 1)
        self.assertIn("disque plein", sortie)
        self.assertEqual(os.listdir(self.custom), ["autre"])
        code, sortie = self.creer()
        self.assertEqual(code, 0, sortie)

    def test_create_with_enable_turns_it_on(self):
        code, sortie = self.creer("--enable")
        self.assertEqual(code, 0, sortie)
        self.assertIn('activateModule("modZorglub")', self.php()[-1])


class TestConteneur(Banc):
    def setUp(self):
        super().setUp()
        self.custom_hote = self.racine / "etat" / "custom"
        self.custom_hote.mkdir(parents=True)
        self.entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "containers": ["x-db", "x-web", "x-cron"],
            "state_dir": str(self.racine / "etat"),
            "custom_dir": str(self.custom_hote),
        }
        self.sys = Systeme(
            gabarit_source=self.htdocs / "modulebuilder" / "template",
            inventaire=(
                "admin\ncore\ncustom\ntheme\nERPLIBRE_MODULES\n"
                "core/modules/modProduct.class.php:numero = 50\n"
                "ERPLIBRE_END\n"
            ),
        )

    def test_the_template_comes_out_of_the_container_into_custom(self):
        code, sortie = self.creer()
        self.assertEqual(code, 0, sortie)
        cp = [a for a in self.sys.appels if a[:2] == ["podman", "cp"]][0]
        self.assertEqual(
            cp[2:], ["x-web:/var/www/html/modulebuilder/template", "-"]
        )
        descr = (
            self.custom_hote
            / "zorglub"
            / "core"
            / "modules"
            / "modZorglub.class.php"
        )
        self.assertIn("$this->numero = 500000;", descr.read_text())
        inventaire = [
            a for a in self.sys.appels if a[:2] == ["podman", "exec"]
        ]
        self.assertIn("/var/www/html", " ".join(inventaire[0]))

    def test_an_unreachable_container_is_said(self):
        self.sys.inventaire = "Error: container x-web is not running\n"
        code, sortie = self.creer()
        self.assertEqual(code, 1)
        self.assertIn("run.py start", sortie)
        self.assertEqual(os.listdir(self.custom_hote), [])

    def test_link_is_refused_in_a_container(self):
        code, sortie = self.lancer(
            "link", "--instance", "erp", "--path", str(self.racine)
        )
        self.assertEqual(code, 2)
        self.assertIn(str(self.custom_hote), sortie)


class TestLien(Banc):
    def setUp(self):
        super().setUp()
        self.source = self.racine / "src" / "zorglub-git"
        descripteur(
            self.source / "core" / "modules" / "modZorglub.class.php",
            "modZorglub",
            500200,
        )

    def test_link_is_a_symlink_named_after_the_descriptor(self):
        code, sortie = self.lancer(
            "link", "--instance", "erp", "--path", str(self.source)
        )
        self.assertEqual(code, 0, sortie)
        lien = self.custom / "zorglub"
        self.assertTrue(lien.is_symlink())
        self.assertEqual(os.readlink(lien), str(self.source))

    def test_linking_twice_changes_nothing(self):
        self.lancer("link", "--instance", "erp", "--path", str(self.source))
        code, _s = self.lancer(
            "link", "--instance", "erp", "--path", str(self.source)
        )
        self.assertEqual(code, 0)

    def test_a_directory_without_descriptor_is_refused(self):
        vide = self.racine / "vide"
        vide.mkdir()
        code, _s = self.lancer(
            "link", "--instance", "erp", "--path", str(vide)
        )
        self.assertEqual(code, 2)

    def test_a_name_taken_is_refused(self):
        autre = self.racine / "src" / "autre"
        descripteur(
            autre / "core" / "modules" / "modAutre.class.php", "modAutre", 1
        )
        code, _s = self.lancer(
            "link", "--instance", "erp", "--path", str(autre)
        )
        self.assertEqual(code, 2)
        self.assertFalse((self.custom / "autre").is_symlink())


class TestActivation(Banc):
    def test_enable_passes_the_exact_class_name(self):
        self.creer()
        code, sortie = self.lancer(
            "enable", "--instance", "erp", "--name", "zorglub"
        )
        self.assertEqual(code, 0, sortie)
        self.assertIn('activateModule("modZorglub")', self.php()[-1])

    def test_a_core_module_is_found_whatever_its_case(self):
        code, _s = self.lancer(
            "enable", "--instance", "erp", "--name", "PRODUCT"
        )
        self.assertEqual(code, 0)
        self.assertIn('activateModule("modProduct")', self.php()[-1])

    def test_an_unknown_module_is_refused(self):
        code, _s = self.lancer("enable", "--instance", "erp", "--name", "Rien")
        self.assertEqual(code, 2)
        self.assertEqual(self.php(), [])

    def test_php_errors_are_a_failure(self):
        self.sys.php_sortie = (0, 'ERPLIBRE_MODULE_ERRORS ["Needs modX"]\n')
        code, sortie = self.lancer(
            "enable", "--instance", "erp", "--name", "Product"
        )
        self.assertEqual(code, 1)
        self.assertIn("Needs modX", sortie)

    def test_disable_uses_unactivatemodule(self):
        code, _s = self.lancer(
            "disable", "--instance", "erp", "--name", "Product"
        )
        self.assertEqual(code, 0)
        self.assertIn('unActivateModule("modProduct")', self.php()[-1])


def _retraits_du_modulebuilder(index):
    """Les retraits de l'action initmodule, lus dans index.php."""
    texte = index.read_text()
    debut = texte.index("// Delete dir and files that can be generated")
    fin = texte.index("// Edit PHP files", debut)
    genres = {
        "dol_delete_dir_recursive": "tree",
        "dol_delete_file": "file",
        "dol_delete_dir": "empty",
    }
    retraits = []
    lignes = [
        ligne
        for ligne in texte[debut:fin].splitlines()
        if not ligne.strip().startswith("//")
    ]
    for fonction, expression in re.findall(
        r"(dol_delete_\w+)\(\$destdir\.(.+?)(?:, 1)?\);", "\n".join(lignes)
    ):
        expression = expression.replace(
            ".strtolower($modulename)", ".'{lower}'"
        ).replace(".$modulename", ".'{case}'")
        retraits.append(
            (genres[fonction], "".join(re.findall(r"'([^']*)'", expression)))
        )
    return retraits


@unittest.skipUnless(
    (VRAI_HTDOCS / "modulebuilder" / "index.php").exists(),
    "checkout Dolibarr absent",
)
class TestDerive(unittest.TestCase):
    def test_the_removals_follow_the_pinned_modulebuilder(self):
        self.assertEqual(
            list(module.PRUNE),
            _retraits_du_modulebuilder(
                VRAI_HTDOCS / "modulebuilder" / "index.php"
            ),
        )

    def test_the_real_template_leaves_no_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "zorglub"
            module.generate(
                str(VRAI_HTDOCS / "modulebuilder" / "template"),
                str(dest),
                "Zorglub",
                module.substitutions(
                    "Zorglub",
                    500123,
                    module.licence(ANNEE, "Ada", ""),
                    "Ada",
                    "",
                    "1.0",
                    "fa-file",
                ),
            )
            descr = dest / "core" / "modules" / "modZorglub.class.php"
            self.assertIn("$this->numero = 500123;", descr.read_text())
            for p in dest.rglob("*"):
                if not p.is_file() or not module.EDITED.search(p.name):
                    continue
                if any(
                    part.startswith(".") for part in p.relative_to(dest).parts
                ):
                    continue
                if p.name == "myobject_index.php":
                    continue  # le ModuleBuilder le garde tel quel
                texte = p.read_text()
                for jeton in ("mymodule", "MyModule", "MYMODULE"):
                    self.assertNotIn(jeton, texte, str(p))
            if shutil.which("php"):
                for p in dest.rglob("*.php"):
                    r = subprocess.run(
                        ["php", "-l", str(p)], capture_output=True, text=True
                    )
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
