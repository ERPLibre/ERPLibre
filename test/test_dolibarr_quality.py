#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""phpcs et PHPStan sur un module, depuis le conteneur d'outils épinglé.

Un checkout réduit porte les fichiers d'outillage de Dolibarr (règles
phpcs, configuration et ligne de base PHPStan, flux CI) ; le moteur de
conteneurs est simulé. Ce qui se garde :
- les outils s'installent aux versions dites (PHPStan : celle du CI de
  Dolibarr épinglé ; phpcs : la dernière 3.x) dans un volume dont le nom
  change avec elles ;
- phpcs part de la racine du checkout avec ses règles ; PHPStan prend sa
  configuration, le cœur pour symboles, l'amorce du CI ;
- la ligne de base du gabarit suit le module renommé, fichier par
  fichier ; les inclusions de main.inc.php, qui ne se résolvent pas hors
  de l'arbre, sont tues, les autres non ;
- tout en lecture seule sauf le volume des outils ; un échec
  d'installation n'exécute rien.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import quality  # noqa: E402

IMAGE = "docker.io/library/composer:2@sha256:" + "a" * 64
COMMIT = "c" * 40
LIGNE_DE_BASE = """parameters:
	ignoreErrors:
		-
			message: '#^Negated boolean expression is always true\\.$#'
			identifier: booleanNot.alwaysTrue
			count: 1
			path: ../../../htdocs/modulebuilder/template/admin/setup.php

		-
			message: '#^Path in include\\(\\) "\\.\\./\\.\\./main\\.inc\\.php" is not a file$#'
			identifier: include.fileNotFound
			count: 1
			path: ../../../htdocs/modulebuilder/template/admin/setup.php

		-
			message: '#^Constant MYMODULE_X in MyModule not found\\.$#'
			identifier: constant.notFound
			count: 2
			path: ../../../htdocs/modulebuilder/template/lib/mymodule.lib.php

		-
			message: '#^In the descriptor\\.$#'
			identifier: x.y
			count: 1
			path: ../../../htdocs/modulebuilder/template/core/modules/modMyModule.class.php

		-
			message: '#^Only in the object page\\.$#'
			identifier: x.y
			count: 1
			path: ../../../htdocs/modulebuilder/template/myobject_card.php

		-
			message: '#^In the core\\.$#'
			identifier: x.y
			count: 1
			path: ../../../htdocs/core/lib/functions.lib.php
"""


def ecrire(racine, fichiers):
    for chemin, texte in fichiers.items():
        p = Path(racine) / chemin
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte)


class Systeme:
    """Le moteur simulé : `codes` donne la sortie de chaque outil."""

    def __init__(self):
        self.lances = []  # (genre, argv)
        self.codes = {"install": 0, "phpcs": 0, "phpstan": 0}
        self.config = None

    def _outil(self, argv):
        texte = " ".join(argv)
        for nom in ("composer require", "phpcs", "phpstan"):
            if nom in texte:
                return "install" if nom == "composer require" else nom
        return "?"

    def run(self, argv, env=None, stdin_path=None):
        self.lances.append(("run", list(argv)))
        return self.codes[self._outil(argv)], "sortie d'installation\n"

    def stream(self, argv):
        self.lances.append(("stream", list(argv)))
        outil = self._outil(argv)
        if outil == "phpstan":
            source = [a for a in argv if a.endswith(":/work:ro")][0]
            dossier = source[: -len(":/work:ro")]
            self.config = (Path(dossier) / "phpstan.neon").read_text()
        return self.codes[outil]

    def engine(self, moteur):
        return self.fiches()[0 if moteur == "podman" else 1]

    def fiches(self):
        return [
            {
                "moteur": "podman",
                "sans_sudo": True,
                "avec_sudo": False,
                "rootless": True,
                "docker_host": None,
            },
            {
                "moteur": "docker",
                "sans_sudo": True,
                "avec_sudo": False,
                "rootless": None,
                "docker_host": None,
            },
        ]

    def argv(self, outil):
        return [a for _g, a in self.lances if self._outil(a) == outil]


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        ecrire(
            self.racine,
            {
                "conf/supported_version_dolibarr.json": json.dumps(
                    {
                        "version": "24.0.1",
                        "branch": "24.0",
                        "docker_image": "docker.io/dolibarr/dolibarr:24.0.0",
                        "mariadb_image": "docker.io/library/mariadb:11.4",
                        "tools_image": IMAGE,
                        "php_min": "7.2",
                        "php_max": "8.5",
                    }
                ),
                "manifest/git_manifest_dolibarr.xml": (
                    '<manifest><project name="dolibarr.git"'
                    ' path="dolibarr/dolibarr" remote="Dolibarr"'
                    f' revision="{COMMIT}" upstream="24.0" groups="dolibarr" />'
                    "</manifest>"
                ),
            },
        )
        self.checkout = self.racine / "dolibarr" / "dolibarr"
        ecrire(
            self.checkout,
            {
                "dev/setup/codesniffer/ruleset.xml": "<ruleset/>",
                "phpstan.neon.dist": "parameters:\n\tlevel: 10\n",
                "dev/build/phpstan/bootstrap_action.php": "<?php\n",
                "dev/build/phpstan/phpstan-baseline.neon": LIGNE_DE_BASE,
                ".github/workflows/phpstan.yml": (
                    "          tools: phpstan:2.1.13, cs2pr:1.8.6\n"
                ),
            },
        )
        self.module = self.checkout / "htdocs" / "custom" / "zorglub"
        ecrire(
            self.module,
            {
                "core/modules/modZorglub.class.php": "<?php\n",
                "admin/setup.php": "<?php\n",
                "lib/zorglub.lib.php": "<?php\n",
            },
        )
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "code_root": str(self.checkout),
            "state_dir": str(self.racine / "etat"),
        }
        self.sys = Systeme()

    def lancer(self, *argv, entree=None, nom="Zorglub"):
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True, exist_ok=True)
        registre.write_text(
            json.dumps({"instances": {"erp": entree or self.entree}})
        )
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = quality.main(
                ["--instance", "erp", "--name", nom, *argv],
                root=str(self.racine),
                system=self.sys,
            )
        return code, sortie.getvalue()


class TestVersions(Banc):
    def test_phpstan_follows_the_ci_of_the_pinned_dolibarr(self):
        self.assertEqual(quality.phpstan_version(str(self.checkout)), "2.1.13")
        (self.checkout / ".github" / "workflows" / "phpstan.yml").unlink()
        self.assertEqual(
            quality.phpstan_version(str(self.checkout)), quality.PHPSTAN
        )

    def test_the_volume_changes_with_image_and_versions(self):
        noms = {
            quality.tools_volume(IMAGE, "3.13.6", "2.1.12"),
            quality.tools_volume(IMAGE, "3.13.6", "2.1.13"),
            quality.tools_volume(IMAGE, "3.13.7", "2.1.12"),
            quality.tools_volume(IMAGE + "b", "3.13.6", "2.1.12"),
        }
        self.assertEqual(len(noms), 4)
        self.assertTrue(
            all(n.startswith("erplibre-dolibarr-quality-") for n in noms)
        )


class TestConfiguration(Banc):
    def config(self):
        return quality.phpstan_config(
            LIGNE_DE_BASE, str(self.module), "zorglub", "Zorglub"
        )

    def test_the_template_baseline_follows_the_renamed_module(self):
        texte = self.config()
        self.assertIn("path: /module/zorglub/admin/setup.php", texte)
        self.assertIn("path: /module/zorglub/lib/zorglub.lib.php", texte)
        self.assertIn("Constant ZORGLUB_X in Zorglub not found", texte)
        self.assertIn("count: 2", texte)
        self.assertIn(
            "path: /module/zorglub/core/modules/modZorglub.class.php", texte
        )
        # Absent du module, ou hors du gabarit : pas repris.
        self.assertNotIn("Only in the object page", texte)
        self.assertNotIn("In the core", texte)

    def test_only_main_inc_includes_are_silenced(self):
        texte = self.config()
        self.assertNotIn("../template/admin/setup.php", texte)
        self.assertEqual(texte.count("identifier: include.fileNotFound"), 1)
        self.assertIn("(main|master)", texte)

    def test_the_core_is_scanned_and_the_ci_bootstrap_used(self):
        texte = self.config()
        for attendu in (
            "- /dolibarr/phpstan.neon.dist",
            "tmpDir: /tools/cache/phpstan",
            "- /dolibarr/htdocs",
            "- /dolibarr/dev/build/phpstan/bootstrap_action.php",
        ):
            self.assertIn(attendu, texte)


class TestLancement(Banc):
    def test_both_tools_run_read_only_from_the_pinned_image(self):
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        install = self.sys.argv("install")[0]
        self.assertIn(IMAGE, install)
        self.assertIn("squizlabs/php_codesniffer:3.13.6", " ".join(install))
        self.assertIn("phpstan/phpstan:2.1.13", " ".join(install))
        phpcs = self.sys.argv("phpcs")[0]
        texte = " ".join(phpcs)
        self.assertEqual(phpcs[:3], ["podman", "run", "--rm"])
        self.assertIn(f"{self.checkout}:/dolibarr:ro", phpcs)
        self.assertIn(f"{self.module}:/module/zorglub:ro", phpcs)
        self.assertIn("--standard=dev/setup/codesniffer/ruleset.xml", phpcs)
        self.assertEqual(phpcs[phpcs.index("-w") + 1], "/dolibarr")
        self.assertEqual(phpcs[-1], "/module/zorglub")
        self.assertIn(IMAGE, texte)
        phpstan = self.sys.argv("phpstan")[-1]
        self.assertIn("/work/phpstan.neon", phpstan)
        self.assertEqual(phpstan[-1], "/module/zorglub")
        self.assertIn("path: /module/zorglub/admin/setup.php", self.sys.config)
        volume = [a for a in phpcs if a.endswith(":/tools")][0]
        self.assertTrue(volume.startswith("erplibre-dolibarr-quality-"))

    def test_the_name_case_comes_from_the_descriptor(self):
        # « MonErp » : les jetons du gabarit prennent la casse de la classe,
        # pas celle qu'on devinerait du dossier.
        ecrire(
            self.checkout / "htdocs" / "custom" / "monerp",
            {
                "core/modules/modMonErp.class.php": "<?php\n",
                "lib/monerp.lib.php": "<?php\n",
            },
        )
        code, sortie = self.lancer("--only", "phpstan", nom="monerp")
        self.assertEqual(code, 0, sortie)
        self.assertIn("Constant MONERP_X in MonErp not found", self.sys.config)
        self.assertEqual(self.sys.argv("phpcs"), [])

    def test_findings_give_1_and_both_tools_still_run(self):
        self.sys.codes["phpcs"] = 2
        code, _s = self.lancer()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.sys.argv("phpstan")), 1)
        self.sys.codes.update(phpcs=0, phpstan=1)
        code, _s = self.lancer()
        self.assertEqual(code, 1)

    def test_a_tool_that_breaks_gives_2(self):
        self.sys.codes["phpcs"] = 3
        code, _s = self.lancer()
        self.assertEqual(code, 2)
        self.sys.codes.update(phpcs=0, phpstan=255)
        code, _s = self.lancer()
        self.assertEqual(code, 2)

    def test_a_failed_install_runs_nothing(self):
        self.sys.codes["install"] = 1
        code, sortie = self.lancer()
        self.assertEqual(code, 2)
        self.assertIn("sortie d'installation", sortie)
        self.assertEqual(self.sys.argv("phpcs"), [])

    def test_only_one_tool(self):
        self.lancer("--only", "phpcs")
        self.assertEqual(self.sys.argv("phpstan"), [])
        self.assertEqual(len(self.sys.argv("phpcs")), 1)

    def test_a_linked_module_is_mounted_from_its_real_place(self):
        depot = self.racine / "src" / "zorglub-depot"
        depot.parent.mkdir()
        os.rename(self.module, depot)
        os.symlink(depot, self.module)
        self.lancer("--only", "phpcs")
        self.assertIn(f"{depot}:/module/zorglub:ro", self.sys.argv("phpcs")[0])


class TestConteneur(Banc):
    def test_the_host_custom_and_the_instance_engine(self):
        custom = self.racine / "etat" / "custom"
        custom.parent.mkdir(parents=True)
        os.rename(self.module.parent, custom)
        entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "docker",
            "containers": ["x-db", "x-web", "x-cron"],
            "state_dir": str(self.racine / "etat"),
            "custom_dir": str(custom),
        }
        code, sortie = self.lancer("--only", "phpcs", entree=entree)
        self.assertEqual(code, 0, sortie)
        phpcs = self.sys.argv("phpcs")[0]
        self.assertEqual(phpcs[:2], ["docker", "run"])
        self.assertIn(f"{custom / 'zorglub'}:/module/zorglub:ro", phpcs)
        self.assertIn(f"{self.checkout}:/dolibarr:ro", phpcs)


class TestRefus(Banc):
    def test_production_is_refused(self):
        code, _s = self.lancer(entree=dict(self.entree, mode="prod"))
        self.assertEqual(code, 2)
        self.assertEqual(self.sys.lances, [])

    def test_an_unknown_module_is_refused(self):
        code, _s = self.lancer("--only", "phpcs", entree=dict(self.entree))
        self.assertEqual(code, 0)
        (self.module / "core" / "modules" / "modZorglub.class.php").unlink()
        code, _s = self.lancer()
        self.assertEqual(code, 2)

    def test_a_checkout_without_the_dolibarr_rules_is_refused(self):
        (
            self.checkout / "dev" / "setup" / "codesniffer" / "ruleset.xml"
        ).unlink()
        code, sortie = self.lancer()
        self.assertEqual(code, 2)
        self.assertIn("ruleset.xml", sortie)
        self.assertEqual(self.sys.lances, [])

    def test_no_usable_engine_is_said(self):
        self.sys.fiches = lambda: [
            dict(f, sans_sudo=False) for f in Systeme().fiches()
        ]
        code, _s = self.lancer()
        self.assertEqual(code, 2)
        self.assertEqual(self.sys.lances, [])


if __name__ == "__main__":
    unittest.main()
