#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Modifier le cœur de Dolibarr : branche de travail, contrôle, patchs.

Un dépôt amont local porte la branche 24.0 ; le checkout épinglé en est un
clone à profondeur 1. Ce qui se garde :
- start refuse sans identité git (repo sync remettrait la branche à zéro),
  crée la branche au commit épinglé et approfondit l'historique ;
- status dit la branche, le travail depuis l'épinglé, le risque de sync
  quand aucun commit ne porte l'identité, et si le fork répond ;
- check applique les règles de CONTRIBUTING.md : DCO, mot-clé du titre,
  ChangeLog et langues hors en_US intouchables, une seule correction par
  PR sur une branche stable, structure et bibliothèques à part ;
- patches exporte la série sous private/, jamais dans le checkout ;
- rien n'est poussé.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import backup, core  # noqa: E402

MOI = ("Ada Lovelace", "ada@example.org")


def git(*args, cwd, ident=MOI):
    return subprocess.run(
        ["git", "-c", f"user.name={ident[0]}", "-c", f"user.email={ident[1]}"]
        + list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(depot, chemin, texte, message, ident=MOI):
    p = Path(depot) / chemin
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texte)
    git("add", chemin, cwd=depot)
    git("commit", "-q", "-m", message, cwd=depot, ident=ident)
    return git("rev-parse", "HEAD", cwd=depot)


def signe(titre, ident=MOI, corps=""):
    return f"{titre}\n\n{corps}Signed-off-by: {ident[0]} <{ident[1]}>"


class Systeme(backup.System):
    """Les vraies commandes, sauf le réseau vers GitHub et repo."""

    def __init__(self):
        self.lances = []
        self.fork = False

    def run(self, argv, env=None, stdin_path=None):
        self.lances.append(list(argv))
        if "ls-remote" in argv and any("ERPLibre" in a for a in argv):
            if self.fork:
                return 0, "abc\trefs/heads/24.0_erplibre\n"
            return 128, "fatal: could not read Username"
        return super().run(argv, env, stdin_path)


class Banc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.amont = Path(cls.tmp.name) / "amont"
        cls.amont.mkdir()
        git("init", "-q", "-b", "24.0", cwd=cls.amont)
        for n in range(4):
            cls.pin = commit(
                cls.amont, "htdocs/a.php", f"<?php // {n}\n", f"c{n}"
            )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name, "erplibre")
        self.checkout = self.racine / "dolibarr" / "dolibarr"
        self.checkout.parent.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "-b", "24.0"]
            + [f"file://{self.amont}", str(self.checkout)],
            check=True,
        )
        git("checkout", "-q", "--detach", self.pin, cwd=self.checkout)
        git("config", "user.name", MOI[0], cwd=self.checkout)
        git("config", "user.email", MOI[1], cwd=self.checkout)
        git("remote", "rename", "origin", "Dolibarr", cwd=self.checkout)
        for chemin, texte in {
            "conf/supported_version_dolibarr.json": json.dumps(
                {
                    "version": "24.0.1",
                    "branch": "24.0",
                    "docker_image": "d:1",
                    "mariadb_image": "m:1",
                    "tools_image": "c:2",
                    "php_min": "7.2",
                    "php_max": "8.5",
                }
            ),
            "manifest/git_manifest_dolibarr.xml": (
                '<manifest><project name="dolibarr.git"'
                ' path="dolibarr/dolibarr" remote="Dolibarr"'
                f' revision="{self.pin}" upstream="24.0" groups="dolibarr" />'
                "</manifest>"
            ),
        }.items():
            p = self.racine / chemin
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(texte)
        self.sys = Systeme()

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = core.main(
                list(argv), root=str(self.racine), system=self.sys
            )
        return code, sortie.getvalue()

    def travailler(self, message, chemin="htdocs/a.php", ident=MOI):
        return commit(self.checkout, chemin, message + "\n", message, ident)


class TestTitre(unittest.TestCase):
    def test_keyword_issue_and_description(self):
        self.assertEqual(
            core.parse_title("FIX #456 Rounding of invoice lines"),
            ("FIX", "#456", "Rounding of invoice lines"),
        )
        self.assertEqual(
            core.parse_title("Qual: simpler loop"),
            ("Qual", None, "simpler loop"),
        )
        self.assertEqual(
            core.parse_title("Short description"),
            (None, None, "Short description"),
        )


class TestRegles(unittest.TestCase):
    def commits(self, *titres, signe_par=MOI, auteur=MOI):
        return [
            {
                "sha": f"{i:07d}",
                "author": auteur[0],
                "email": auteur[1],
                "subject": titre,
                "body": f"Signed-off-by: {signe_par[0]} <{signe_par[1]}>\n"
                if signe_par
                else "",
            }
            for i, titre in enumerate(titres)
        ]

    def niveaux(self, resultats):
        return [niveau for niveau, _m in resultats]

    def test_a_clean_fix_passes(self):
        r = core.review(
            self.commits("FIX #12 Wrong total"), ["htdocs/a.php"], "24.0"
        )
        self.assertNotIn(core.FAIL, self.niveaux(r))
        self.assertNotIn(core.WARN, self.niveaux(r))

    def test_a_commit_without_sign_off_fails_the_dco(self):
        r = core.review(self.commits("FIX x", signe_par=None), [], "24.0")
        self.assertIn(core.FAIL, self.niveaux(r))
        self.assertTrue(any("0000000" in m for _n, m in r))

    def test_a_sign_off_by_someone_else_fails(self):
        r = core.review(
            self.commits("FIX x", signe_par=("Autre", "autre@example.org")),
            [],
            "24.0",
        )
        self.assertIn(core.FAIL, self.niveaux(r))

    def test_changelog_and_other_languages_are_refused(self):
        for chemin in ("ChangeLog", "htdocs/langs/fr_FR/main.lang"):
            r = core.review(self.commits("FIX x"), [chemin], "24.0")
            self.assertIn(core.FAIL, self.niveaux(r), chemin)
        r = core.review(
            self.commits("FIX x"), ["htdocs/langs/en_US/main.lang"], "24.0"
        )
        self.assertNotIn(core.FAIL, self.niveaux(r))

    def test_keyword_advice(self):
        for titre in (
            "Fix lowercase keyword",
            "no keyword at all",
            "CLOSE without number",
        ):
            r = core.review(self.commits(titre), [], "develop")
            self.assertIn(core.WARN, self.niveaux(r), titre)
        r = core.review(self.commits("FIX " + "x" * 51), [], "24.0")
        self.assertIn(core.WARN, self.niveaux(r))

    def test_a_stable_branch_takes_one_fix(self):
        r = core.review(self.commits("FIX a", "FIX b"), [], "24.0")
        self.assertIn(core.WARN, self.niveaux(r))
        r = core.review(self.commits("NEW feature"), [], "24.0")
        self.assertIn(core.WARN, self.niveaux(r))
        r = core.review(self.commits("NEW a", "NEW b"), [], "develop")
        self.assertNotIn(core.WARN, self.niveaux(r))

    def test_structure_and_libraries_come_first_alone(self):
        for chemin in (
            "htdocs/install/mysql/tables/llx_x.sql",
            "htdocs/install/mysql/migration/23.0.0-24.0.0.sql",
            "htdocs/includes/lib/x.php",
        ):
            r = core.review(self.commits("NEW x"), [chemin], "develop")
            self.assertIn(core.WARN, self.niveaux(r), chemin)


class TestStart(Banc):
    def test_start_branches_at_the_pin_and_deepens(self):
        code, sortie = self.lancer(
            "start", "--topic", "fix-total", "--deepen", "2"
        )
        self.assertEqual(code, 0, sortie)
        self.assertEqual(
            git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.checkout),
            "fix-total",
        )
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.checkout), self.pin)
        self.assertEqual(
            git("rev-list", "--count", "HEAD", cwd=self.checkout), "3"
        )

    def test_start_without_identity_is_refused(self):
        git("config", "--unset", "user.email", cwd=self.checkout)
        env = {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
        with mock.patch.dict("os.environ", env):
            code, sortie = self.lancer("start", "--topic", "x")
        self.assertEqual(code, 2)
        self.assertEqual(
            git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.checkout), "HEAD"
        )

    def test_a_bad_topic_is_refused(self):
        code, _s = self.lancer("start", "--topic", "a b")
        self.assertEqual(code, 2)


class TestStatus(Banc):
    def test_status_counts_the_work_and_names_the_fork(self):
        self.lancer("start", "--topic", "fix-total", "--deepen", "1")
        self.travailler(signe("FIX Total"))
        (self.checkout / "htdocs" / "b.php").write_text("x")
        code, sortie = self.lancer("status")
        self.assertEqual(code, 0, sortie)
        self.assertIn("fix-total", sortie)
        self.assertIn("1", sortie)
        self.assertIn("ERPLibre/dolibarr", sortie)
        self.sys.fork = True
        _c, avec = self.lancer("status")
        self.assertNotEqual(sortie, avec)

    def test_no_commit_with_the_identity_is_a_sync_risk(self):
        self.lancer("start", "--topic", "fix-total", "--deepen", "1")
        self.travailler(
            signe("FIX Total", ident=("Autre", "autre@example.org")),
            ident=("Autre", "autre@example.org"),
        )
        code, sortie = self.lancer("status")
        self.assertEqual(code, 1)
        self.assertIn(MOI[1], sortie)


class TestCheckEtPatchs(Banc):
    def test_check_reads_the_commits_since_the_pin(self):
        self.lancer("start", "--topic", "fix-total", "--deepen", "1")
        self.travailler(signe("FIX #12 Wrong total"))
        code, sortie = self.lancer("check")
        self.assertEqual(code, 0, sortie)
        self.travailler("FIX unsigned")
        code, sortie = self.lancer("check")
        self.assertEqual(code, 1, sortie)

    def test_a_lone_commit_without_body_is_seen(self):
        # Sans corps, l'enregistrement finit par ses séparateurs \x1f\x1e,
        # que str.strip() prend pour des blancs.
        self.lancer("start", "--topic", "fix-total", "--deepen", "1")
        self.travailler("FIX unsigned")
        code, _s = self.lancer("check")
        self.assertEqual(code, 1)

    def test_check_and_patches_without_work_do_nothing(self):
        for action in ("check", "patches"):
            code, _s = self.lancer(action)
            self.assertEqual(code, 0)
        self.assertFalse([a for a in self.sys.lances if "format-patch" in a])
        self.assertFalse((self.racine / "private").exists())

    def test_patches_go_under_private_never_into_the_checkout(self):
        self.lancer("start", "--topic", "fix-total", "--deepen", "1")
        self.travailler(signe("FIX #12 Wrong total"))
        self.travailler(signe("FIX #13 Other"))
        code, sortie = self.lancer("patches")
        self.assertEqual(code, 0, sortie)
        dossiers = list(
            (self.racine / "private" / "dolibarr" / "patches").iterdir()
        )
        self.assertEqual(len(dossiers), 1)
        self.assertTrue(dossiers[0].name.startswith("fix-total-"))
        self.assertEqual(len(list(dossiers[0].glob("*.patch"))), 2)
        self.assertEqual(git("status", "--porcelain", cwd=self.checkout), "")

    def test_nothing_is_pushed(self):
        self.lancer("start", "--topic", "fix-total", "--deepen", "1")
        self.travailler(signe("FIX #12 Wrong total"))
        for action in (("status",), ("check",), ("patches",)):
            self.lancer(*action)
        self.assertFalse([a for a in self.sys.lances if "push" in a])


if __name__ == "__main__":
    unittest.main()
