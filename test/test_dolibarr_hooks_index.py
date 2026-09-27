#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'index des hooks et des déclencheurs de Dolibarr, à deux commits.

Un dépôt amont local (file://) porte deux versions ; le checkout épinglé
en est un clone à profondeur 1, comme celui de Google Repo. Ce qui se
garde :
- l'index lit executeHooks, initHooks (littéraux seulement), call_trigger
  et les codes de llx_c_action_trigger.sql, gabarit du ModuleBuilder
  exclu ;
- le commit épinglé se lit dans le checkout sans réseau ; une autre
  version se récupère une fois, à profondeur 1, dans un dépôt d'index à
  part qui emprunte les objets du checkout : le dépôt que gère Google
  Repo n'est jamais touché ;
- le diff dit, par genre, ce qui apparaît et ce qui disparaît.
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import backup, hooks_index  # noqa: E402

V1 = {
    "htdocs/societe/card.php": (
        "<?php\n$hookmanager->initHooks(array('thirdpartycard', 'globalcard'));\n"
        "$reshook = $hookmanager->executeHooks('doActions', $parameters);\n"
        "$result = $object->call_trigger('COMPANY_CREATE', $user);\n"
        "$x = $this->call_trigger(strtoupper($el).'_DELETE', $user);\n"
    ),
    "htdocs/install/mysql/data/llx_c_action_trigger.sql": (
        "insert into llx_c_action_trigger (code,label) values"
        " ('COMPANY_CREATE','Third party created');\n"
    ),
    "htdocs/modulebuilder/template/myobject_card.php": (
        "<?php\n$hookmanager->initHooks(array('myobjectcard'));\n"
    ),
}
V2 = dict(
    V1,
    **{
        "htdocs/societe/card.php": (
            "<?php\n$hookmanager->initHooks(['thirdpartycard', $ctx]);\n"
            '$reshook = $hookmanager->executeHooks("doActions", $p);\n'
            "$reshook = $hookmanager->executeHooks('formObjectOptions', $p);\n"
            "$reshook = $hookmanager->executeHooks('doActions', $p2);\n"
            "$result = $object->call_trigger('COMPANY_CREATE', $user);\n"
            "$result = $object->call_trigger('COMPANY_DELETE', $user);\n"
        ),
        "htdocs/install/mysql/data/llx_c_action_trigger.sql": (
            "insert into llx_c_action_trigger (code,label) values"
            " ('COMPANY_CREATE','Third party created');\n"
            "INSERT INTO llx_c_action_trigger (code,label) VALUES"
            " ('COMPANY_DELETE','Third party deleted');\n"
        ),
    },
)


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def ecrire(racine, fichiers):
    for chemin, texte in fichiers.items():
        p = Path(racine) / chemin
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte)


class Systeme(backup.System):
    """Les vraies commandes, comptées."""

    def __init__(self):
        self.lances = []

    def run(self, argv, env=None, stdin_path=None):
        self.lances.append(list(argv))
        return super().run(argv, env, stdin_path)

    def fetches(self):
        return [a for a in self.lances if "fetch" in a]


class Banc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.amont = base / "amont"
        cls.amont.mkdir()
        git("init", "-q", "-b", "24.0", cwd=cls.amont)
        git(
            "config",
            "uploadpack.allowReachableSHA1InWant",
            "true",
            cwd=cls.amont,
        )
        ecrire(cls.amont, V1)
        git("add", ".", cwd=cls.amont)
        git("commit", "-q", "-m", "v1", cwd=cls.amont)
        git("tag", "24.0.0", cwd=cls.amont)
        cls.v1 = git("rev-parse", "HEAD", cwd=cls.amont)
        ecrire(cls.amont, V2)
        git("add", ".", cwd=cls.amont)
        git("commit", "-q", "-m", "v2", cwd=cls.amont)
        cls.v2 = git("rev-parse", "HEAD", cwd=cls.amont)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name, "erplibre")
        self.url = f"file://{self.amont}"
        checkout = self.racine / "dolibarr" / "dolibarr"
        checkout.parent.mkdir(parents=True)
        subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "--depth",
                "1",
                "-b",
                "24.0",
                self.url,
                str(checkout),
            ],
            check=True,
        )
        self.checkout = checkout
        ecrire(
            self.racine,
            {
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
                    f' revision="{self.v2}" upstream="24.0" groups="dolibarr" />'
                    "</manifest>"
                ),
            },
        )
        self.cache = Path(tmp.name, "index.git")
        self.sys = Systeme()

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = hooks_index.main(
                list(argv),
                root=str(self.racine),
                system=self.sys,
                cache=str(self.cache),
                upstream=self.url,
            )
        return code, sortie.getvalue()


class TestLecture(unittest.TestCase):
    def test_hooks_contexts_and_triggers_from_grep_lines(self):
        lignes = [
            f"abc:{chemin}:{n}:{ligne}"
            for chemin, texte in V2.items()
            if chemin.endswith(".php")
            for n, ligne in enumerate(texte.splitlines(), 1)
        ]
        index = hooks_index.parse_grep(lignes)
        self.assertEqual(
            sorted(index["hook"]), ["doActions", "formObjectOptions"]
        )
        self.assertIn("thirdpartycard", index["context"])
        self.assertIn("myobjectcard", index["context"])  # le filtre est git
        self.assertEqual(
            sorted(index["trigger"]), ["COMPANY_CREATE", "COMPANY_DELETE"]
        )
        self.assertEqual(
            index["hook"]["doActions"], ["htdocs/societe/card.php"]
        )

    def test_agenda_codes_from_the_sql(self):
        self.assertEqual(
            hooks_index.parse_agenda(
                V2["htdocs/install/mysql/data/llx_c_action_trigger.sql"]
            ),
            {"COMPANY_CREATE", "COMPANY_DELETE"},
        )

    def test_the_diff_by_kind(self):
        avant = {"hook": {"a": [], "b": []}, "context": {}}
        apres = {"hook": {"b": [], "c": []}, "context": {"x": []}}
        self.assertEqual(
            hooks_index.diff(avant, apres),
            {"hook": (["c"], ["a"]), "context": (["x"], [])},
        )


class TestIndex(Banc):
    def test_the_pinned_commit_needs_no_network(self):
        code, sortie = self.lancer("list")
        self.assertEqual(code, 0, sortie)
        self.assertEqual(self.sys.fetches(), [])
        for attendu in (
            "hook",
            "formObjectOptions",
            "thirdpartycard",
            "COMPANY_DELETE",
            "agenda",
        ):
            self.assertIn(attendu, sortie)
        self.assertNotIn("myobjectcard", sortie)
        self.assertIn("formObjectOptions  (1)", sortie)
        self.assertNotIn("_DELETE ", sortie.replace("COMPANY_DELETE", ""))

    def test_the_managed_checkout_is_never_written(self):
        avant = git("count-objects", "-v", cwd=self.checkout)
        self.lancer("diff", "--from", "24.0.0")
        self.assertEqual(git("count-objects", "-v", cwd=self.checkout), avant)
        self.assertTrue(
            (self.cache / "objects" / "info" / "alternates").exists()
        )

    def test_diff_from_an_older_tag(self):
        code, sortie = self.lancer("diff", "--from", "24.0.0")
        self.assertEqual(code, 0, sortie)
        lignes = sortie.splitlines()
        for attendu in (
            "+ hook formObjectOptions",
            "- context globalcard",
            "+ trigger COMPANY_DELETE",
            "+ agenda COMPANY_DELETE",
        ):
            self.assertIn(attendu, [ligne.strip() for ligne in lignes])

    def test_a_version_is_fetched_once(self):
        self.lancer("diff", "--from", "24.0.0")
        self.assertEqual(len(self.sys.fetches()), 1)
        self.lancer("diff", "--from", self.v1)
        self.lancer("list", "--at", self.v1)
        self.lancer("list", "--at", "24.0.0")
        self.assertEqual(len(self.sys.fetches()), 1)

    def test_a_commit_is_fetched_by_its_sha(self):
        code, sortie = self.lancer("list", "--at", self.v1, "--kind", "hook")
        self.assertEqual(code, 0, sortie)
        self.assertIn("doActions", sortie)
        self.assertNotIn("formObjectOptions", sortie)
        self.assertNotIn("thirdpartycard", sortie)

    def test_a_branch_is_read_at_its_head(self):
        code, sortie = self.lancer("list", "--at", "24.0", "--kind", "hook")
        self.assertEqual(code, 0, sortie)
        self.assertIn("formObjectOptions", sortie)

    def test_a_grep_that_breaks_is_an_error(self):
        lancer = self.sys.run

        def run(argv, env=None, stdin_path=None):
            if "grep" in argv:
                return 128, "fatal: bad object"
            return lancer(argv, env, stdin_path)

        self.sys.run = run
        code, sortie = self.lancer("list")
        self.assertEqual(code, 2)
        self.assertIn("bad object", sortie)

    def test_the_filter(self):
        code, sortie = self.lancer("list", "--filter", "^COMPANY_D")
        self.assertEqual(code, 0)
        self.assertIn("COMPANY_DELETE", sortie)
        self.assertNotIn("COMPANY_CREATE", sortie)
        self.assertNotIn("doActions", sortie)

    def test_an_unknown_ref_is_said(self):
        code, sortie = self.lancer("diff", "--from", "99.0.0")
        self.assertEqual(code, 2)
        self.assertIn("99.0.0", sortie)

    def test_a_moved_checkout_moves_the_borrowed_shallow_edge(self):
        self.lancer("diff", "--from", "24.0.0")
        bord = (self.cache / "shallow").read_text().split()
        self.assertIn(self.v2, bord)  # emprunté au checkout
        self.assertIn(self.v1, bord)  # récupéré par l'index
        shutil.rmtree(self.checkout)
        subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "--depth",
                "1",
                "-b",
                "24.0.0",
                self.url,
                str(self.checkout),
            ],
            check=True,
        )
        code, _s = self.lancer("list", "--at", "24.0.0")
        self.assertEqual(code, 0)
        bord = (self.cache / "shallow").read_text().split()
        self.assertNotIn(self.v2, bord)
        self.assertIn(self.v1, bord)

    def test_without_checkout_the_pin_is_fetched(self):
        shutil.rmtree(self.checkout)
        code, sortie = self.lancer("list", "--kind", "trigger")
        self.assertEqual(code, 0, sortie)
        self.assertEqual(len(self.sys.fetches()), 1)
        self.assertIn("COMPANY_DELETE", sortie)


if __name__ == "__main__":
    unittest.main()
