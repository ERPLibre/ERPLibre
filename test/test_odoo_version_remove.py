#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/version/odoo_version_remove.py sur un faux checkout git-repo : des
dépôts « .repo/projects/odoo<V>/*.git » dont « objects » est un lien vers un
stockage partagé de « .repo/project-objects », et leurs arbres sous
« odoo<V>/ » liés par un « .git » symbolique, comme git-repo les pose.

Le seuil de gain est levé : les dépôts du test pèsent quelques Kio."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from script.version import odoo_version_remove as R  # noqa: E402

ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@example.invalid",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@example.invalid",
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_NOSYSTEM="1",
)


def _git(cwd, *args, gitdir=None):
    cmd = ["git"] + (["--git-dir", gitdir] if gitdir else []) + list(args)
    return subprocess.run(
        cmd, cwd=cwd, check=True, capture_output=True, text=True, env=ENV
    ).stdout.strip()


def _existe(gitdir, sha):
    return (
        subprocess.run(
            ["git", "--git-dir", gitdir, "cat-file", "-e", sha],
            capture_output=True,
            env=ENV,
        ).returncode
        == 0
    )


class Checkout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.r = os.path.join(self.tmp.name, "erplibre")
        os.makedirs(os.path.join(self.r, ".repo", "project-objects"))
        os.makedirs(os.path.join(self.r, "conf"))
        self.ecrire(".odoo-version", "18.0\n")
        self.ecrire(
            ".repo/installed_odoo_version.txt",
            "odoo18.0\nodoo17.0\nodoo16.0\n",
        )
        self.ecrire(
            ".erplibre-state.json",
            json.dumps(
                {
                    "current_odoo_version": "16.0",
                    "odoo_versions": {
                        v: {"installed": True}
                        for v in ("16.0", "17.0", "18.0")
                    },
                }
            ),
        )
        self.ecrire(
            "conf/supported_version_erplibre.json",
            json.dumps(
                {
                    f"odoo{v}_python{p}": {
                        "odoo_version": v,
                        "python_version": p,
                    }
                    for v, p in (
                        ("16.0", "3.10.18"),
                        ("17.0", "3.10.18"),
                        ("18.0", "3.12.10"),
                    )
                }
            ),
        )
        # L'amont : une racine commune, puis une branche par version.
        self.amont = os.path.join(self.tmp.name, "amont")
        os.makedirs(self.amont)
        _git(self.amont, "init", "-q", "-b", "main")
        self.commit(self.amont, "racine")
        self.sha = {}
        for v in ("16.0", "17.0", "18.0"):
            _git(self.amont, "checkout", "-q", "-b", v, "main")
            for i in range(3):
                self.sha[f"{v}-{i}"] = self.commit(self.amont, f"{v}-{i}")
        self.solo = os.path.join(self.tmp.name, "solo")
        os.makedirs(self.solo)
        _git(self.solo, "init", "-q", "-b", "16.0")
        self.sha["solo"] = self.commit(self.solo, "solo")

    def ecrire(self, relatif, texte):
        chemin = os.path.join(self.r, relatif)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w") as fh:
            fh.write(texte)

    def commit(self, depot, message):
        with open(os.path.join(depot, f"{message}.txt"), "w") as fh:
            fh.write(message)
        _git(depot, "add", ".")
        _git(depot, "commit", "-q", "-m", message)
        return _git(depot, "rev-parse", "HEAD")

    def projet(self, version, nom, amont, branche, profondeur=None):
        """Un dépôt git-repo de `version`, au stockage partagé `nom`."""
        stockage = os.path.join(
            self.r, ".repo", "project-objects", f"{nom}.git"
        )
        if not os.path.isdir(stockage):
            _git(self.tmp.name, "init", "-q", "--bare", stockage)
        gitdir = os.path.join(
            self.r, ".repo", "projects", f"odoo{version}", f"addons/{nom}.git"
        )
        os.makedirs(os.path.dirname(gitdir), exist_ok=True)
        _git(self.tmp.name, "init", "-q", "--bare", gitdir)
        subprocess.run(
            ["rm", "-rf", os.path.join(gitdir, "objects")], check=True
        )
        os.symlink(
            os.path.relpath(os.path.join(stockage, "objects"), gitdir),
            os.path.join(gitdir, "objects"),
        )
        _git(None, "config", "core.bare", "false", gitdir=gitdir)
        # Le fetch laisse un pack : le compactage doit retirer des packs.
        _git(None, "config", "fetch.unpackLimit", "1", gitdir=gitdir)
        _git(None, "remote", "add", "origin", amont, gitdir=gitdir)
        fetch = ["fetch", "-q", "origin"]
        if profondeur:
            fetch += [
                f"--depth={profondeur}",
                f"refs/heads/{branche}:refs/remotes/origin/{branche}",
            ]
        _git(None, *fetch, gitdir=gitdir)
        _git(
            None,
            "update-ref",
            "refs/remotes/m/master",
            f"refs/remotes/origin/{branche}",
            gitdir=gitdir,
        )
        arbre = os.path.join(self.r, f"odoo{version}", "addons", nom)
        os.makedirs(arbre)
        os.symlink(os.path.relpath(gitdir, arbre), os.path.join(arbre, ".git"))
        _git(arbre, "checkout", "-q", "--detach", f"origin/{branche}")
        return gitdir, arbre

    def lancer(self, *args, tty=False, reponse=""):
        sortie = io.StringIO()
        with (
            mock.patch.object(R, "SEUIL_GAIN", -1),
            mock.patch.object(sys.stdin, "isatty", return_value=tty),
            mock.patch("builtins.input", return_value=reponse),
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(sortie),
        ):
            code = R.main(["--root", self.r, *args])
        return code, sortie.getvalue()

    def fichiers(self):
        vus = set()
        for dossier, _d, fichiers in os.walk(self.r):
            for nom in fichiers:
                chemin = os.path.join(dossier, nom)
                vus.add((chemin, os.lstat(chemin).st_mtime_ns))
        return vus


class TestVersionDeRef(unittest.TestCase):
    def test_noms(self):
        cas = {
            "refs/remotes/origin/16.0": 16,
            "refs/heads/ERPLibre/16.0_before_refactoring": 16,
            "refs/remotes/OCA/12.0-mig-foo": 12,
            "refs/remotes/o/saas-13.3": 13,
            "refs/remotes/o/tmp.saas-12.4": 12,
            "refs/remotes/o/staging.11.0": 11,
            "refs/remotes/o/master": None,
            "refs/remotes/o/staging.master": None,
            "refs/tags/ERPLibre/v1.5.0": None,
            "refs/remotes/o/2.0": None,
            "refs/heads/test": None,
        }
        for ref, attendu in cas.items():
            self.assertEqual(R.version_de_ref(ref), attendu, ref)


class TestVersionsChoisies(unittest.TestCase):
    CHOIX = ["12.0", "13.0", "14.0", "15.0", "16.0", "17.0"]

    def test_plusieurs_numeros(self):
        self.assertEqual(
            R.versions_choisies("5 1  3 1", self.CHOIX),
            ["12.0", "14.0", "16.0"],
        )

    def test_retour(self):
        self.assertEqual(R.versions_choisies("", self.CHOIX), [])
        self.assertEqual(R.versions_choisies(" 0 ", self.CHOIX), [])

    def test_un_numero_invalide_refuse_tout(self):
        for reponse in ("1 7", "1 0", "1 x", "-1"):
            self.assertIsNone(
                R.versions_choisies(reponse, self.CHOIX), reponse
            )


class TestRetrait(Checkout):
    def setUp(self):
        super().setUp()
        self.g16, self.a16 = self.projet("16.0", "core", self.amont, "16.0")
        self.g17, self.a17 = self.projet(
            "17.0", "core", self.amont, "17.0", profondeur=1
        )
        self.g18, self.a18 = self.projet("18.0", "core", self.amont, "18.0")
        self.gsolo, _ = self.projet("16.0", "solo", self.solo, "16.0")
        # La branche par défaut du remote, vue depuis 18.0, est une version
        # retirée : « origin/HEAD » doit partir avec elle.
        _git(
            None,
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/16.0",
            gitdir=self.g18,
        )

    def test_essai_a_sec_ne_touche_rien(self):
        avant = self.fichiers()
        code, sortie = self.lancer("--version", "16.0", "--dry-run")
        self.assertEqual(code, R.EXIT_OK, sortie)
        self.assertEqual(self.fichiers(), avant)
        self.assertIn("16.0", sortie)
        self.assertIn("Stockages d'objets sans dépôt restant : 1", sortie)

    def test_la_version_active_est_refusee(self):
        code, sortie = self.lancer("--version", "18.0", "--yes")
        self.assertEqual(code, R.EXIT_REFUS)
        self.assertTrue(os.path.isdir(self.a18))

    def test_retrait_d_une_version(self):
        tete18 = _git(self.a18, "rev-parse", "HEAD")
        code, sortie = self.lancer("--version", "16.0", "--yes")
        self.assertEqual(code, R.EXIT_OK, sortie)
        self.assertFalse(os.path.exists(os.path.join(self.r, "odoo16.0")))
        self.assertFalse(
            os.path.exists(
                os.path.join(self.r, ".repo", "projects", "odoo16.0")
            )
        )
        # Le stockage que seul 16.0 utilisait part.
        self.assertFalse(
            os.path.exists(
                os.path.join(self.r, ".repo", "project-objects", "solo.git")
            )
        )
        with open(
            os.path.join(self.r, ".repo", "installed_odoo_version.txt")
        ) as fh:
            self.assertEqual(fh.read(), "odoo18.0\nodoo17.0\n")
        with open(os.path.join(self.r, ".erplibre-state.json")) as fh:
            etat = json.load(fh)
        self.assertNotIn("16.0", etat["odoo_versions"])
        self.assertEqual(etat["current_odoo_version"], "18.0")
        # 18.0 perd la branche 16.0 de l'amont, garde la sienne et 17.0.
        refs = _git(
            None, "for-each-ref", "--format=%(refname)", gitdir=self.g18
        ).split()
        self.assertNotIn("refs/remotes/origin/16.0", refs)
        self.assertFalse(
            os.path.lexists(
                os.path.join(self.g18, "refs", "remotes", "origin", "HEAD")
            )
        )
        self.assertIn("refs/remotes/origin/18.0", refs)
        self.assertIn("refs/remotes/origin/17.0", refs)
        # L'historique propre à 16.0 a quitté le stockage partagé.
        for i in range(3):
            self.assertFalse(_existe(self.g18, self.sha[f"16.0-{i}"]))
            self.assertTrue(_existe(self.g18, self.sha[f"18.0-{i}"]))
        self.assertEqual(_git(self.a18, "rev-parse", "HEAD"), tete18)
        self.assertEqual(_git(self.a18, "status", "--porcelain"), "")
        _git(
            None,
            "fsck",
            "--connectivity-only",
            "--no-dangling",
            gitdir=self.g18,
        )

    def test_un_clone_superficiel_ne_coupe_pas_l_historique_d_un_autre(self):
        """17.0 est superficiel à 1 commit ; 18.0, complet, porte aussi la
        branche 17.0 : son historique entier doit survivre au compactage."""
        code, sortie = self.lancer("--version", "16.0", "--yes")
        self.assertEqual(code, R.EXIT_OK, sortie)
        for i in range(3):
            self.assertTrue(_existe(self.g18, self.sha[f"17.0-{i}"]))
        _git(
            None,
            "fsck",
            "--connectivity-only",
            "--no-dangling",
            gitdir=self.g18,
        )
        _git(
            None,
            "fsck",
            "--connectivity-only",
            "--no-dangling",
            gitdir=self.g17,
        )
        self.assertEqual(_git(self.a17, "status", "--porcelain"), "")

    def test_tout_retirer(self):
        code, sortie = self.lancer("--all", "--yes")
        self.assertEqual(code, R.EXIT_OK, sortie)
        for v in ("16.0", "17.0", "18.0"):
            self.assertFalse(os.path.exists(os.path.join(self.r, f"odoo{v}")))
        self.assertEqual(
            os.listdir(os.path.join(self.r, ".repo", "project-objects")), []
        )
        with open(
            os.path.join(self.r, ".repo", "installed_odoo_version.txt")
        ) as fh:
            self.assertEqual(fh.read(), "")
        with open(os.path.join(self.r, ".erplibre-state.json")) as fh:
            etat = json.load(fh)
        self.assertEqual(etat["odoo_versions"], {})
        self.assertIsNone(etat["current_odoo_version"])


class TestNonSauve(Checkout):
    def setUp(self):
        super().setUp()
        self.g16, self.a16 = self.projet("16.0", "core", self.amont, "16.0")
        self.g18, self.a18 = self.projet("18.0", "core", self.amont, "18.0")
        with open(os.path.join(self.a16, "16.0-0.txt"), "a") as fh:
            fh.write("modifié")
        _git(self.a16, "checkout", "-q", "-b", "travail")
        self.local = self.commit(self.a16, "local")
        self.ecrire("odoo16.0/addons/addons/mon_module/__init__.py", "")

    def test_liste_et_refuse_sans_terminal(self):
        code, sortie = self.lancer("--version", "16.0", "--yes")
        self.assertEqual(code, R.EXIT_REFUS, sortie)
        self.assertIn("commit(s) absent(s) de tout remote", sortie)
        self.assertIn("odoo16.0/addons/addons/", sortie)
        self.assertTrue(os.path.isdir(self.a16))

    def test_le_mot_tape_laisse_effacer(self):
        code, sortie = self.lancer(
            "--version", "16.0", tty=True, reponse=R.MOT_CONFIRMATION
        )
        self.assertEqual(code, R.EXIT_OK, sortie)
        self.assertFalse(os.path.exists(os.path.join(self.r, "odoo16.0")))

    def test_une_autre_reponse_garde_tout(self):
        code, _sortie = self.lancer("--version", "16.0", tty=True, reponse="o")
        self.assertEqual(code, R.EXIT_REFUS)
        self.assertTrue(os.path.isdir(self.a16))


if __name__ == "__main__":
    unittest.main()
