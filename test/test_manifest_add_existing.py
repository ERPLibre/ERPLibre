#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ajouter un dépôt : au manifeste public ou privé, parmi les versions
installées, sur la branche par défaut que l'hôte annonce, ou depuis un
clone qui existe déjà, puis remis à repo.

Une racine ERPLibre jetable par test : manifest/, private/, .repo/ et de
vrais dépôts git, avec des remotes nus locaux. Rien ne va sur le réseau.
"""

import csv
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import manifest_repo as mr  # noqa: E402
from script.git import repo_upgrade  # noqa: E402
from script.todo import git_fork_menu as gm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from test.test_manifest_repo import GEL, IDENTITE, MANIFESTE  # noqa: E402


def git(chemin, *args):
    return subprocess.run(
        ["git", "-C", chemin, *args],
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ, **IDENTITE),
    ).stdout.strip()


class Racine(unittest.TestCase):
    """Une racine avec manifest/git_manifest_odoo18.0.xml (gelé), le
    manifeste 17.0, et 18.0 seul installé."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, IDENTITE)
        patch.start()
        self.addCleanup(patch.stop)
        self.racine = tmp.name
        self.manifestes = os.path.join(self.racine, "manifest")
        os.makedirs(self.manifestes)
        for version in ("17.0", "18.0"):
            with open(
                os.path.join(
                    self.manifestes, f"git_manifest_odoo{version}.xml"
                ),
                "w",
            ) as fh:
                fh.write(MANIFESTE.format(gel=GEL).replace("18.0", version))
        os.makedirs(os.path.join(self.racine, ".repo"))
        with open(
            os.path.join(self.racine, ".repo", "installed_odoo_version.txt"),
            "w",
        ) as fh:
            fh.write("odoo18.0\n")
        for cible, valeur in ((repo_upgrade, "DOSSIER"),):
            p = mock.patch.object(cible, valeur, self.manifestes)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(
            repo_upgrade, "version_active", return_value="18.0"
        )
        p.start()
        self.addCleanup(p.stop)

    def lire(self, relatif):
        with open(os.path.join(self.racine, relatif), encoding="utf-8") as fh:
            return fh.read()

    def clone(self, relatif, branche="main", pousser=True):
        """Un clone ordinaire à `relatif`, son remote origin nu à côté."""
        nu = os.path.join(
            self.racine, "nus", os.path.basename(relatif) + ".git"
        )
        os.makedirs(os.path.dirname(nu), exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", nu], check=True)
        chemin = os.path.join(self.racine, relatif)
        os.makedirs(chemin)
        git(chemin, "init", "-q", "-b", branche)
        git(chemin, "commit", "-q", "--allow-empty", "-m", "un")
        git(chemin, "remote", "add", "origin", nu)
        if pousser:
            git(chemin, "push", "-q", "-u", "origin", branche)
        return chemin


class TestLHote(unittest.TestCase):
    def test_one_ls_remote_gives_branches_and_default(self):
        sortie = (
            "ref: refs/heads/main\tHEAD\n"
            f"{GEL}\tHEAD\n"
            f"{GEL}\trefs/heads/main\n"
            f"{GEL}\trefs/heads/otp-1\n"
        )
        fait = subprocess.CompletedProcess([], 0, sortie, "")
        with (
            mock.patch.object(
                repo_upgrade.subprocess, "run", return_value=fait
            ) as run,
            mock.patch.object(repo_upgrade.command_echo, "show"),
        ):
            self.assertEqual(
                repo_upgrade.branches_et_defaut("u"),
                ({"main", "otp-1"}, "main"),
            )
        self.assertEqual(
            run.call_args.args[0],
            ["git", "ls-remote", "--symref", "u", "HEAD", "refs/heads/*"],
        )
        refus = subprocess.CompletedProcess([], 128, "", "denied")
        with (
            mock.patch.object(
                repo_upgrade.subprocess, "run", return_value=refus
            ),
            mock.patch.object(repo_upgrade.command_echo, "show"),
        ):
            self.assertIsNone(repo_upgrade.branches_et_defaut("u"))
        self.assertIsNone(repo_upgrade.branches_et_defaut(""))

    def test_the_version_branch_first_then_the_host_default(self):
        self.assertEqual(
            mr.branche_proposee("18.0", {"18.0", "main"}, "main"), "18.0"
        )
        self.assertEqual(mr.branche_proposee("18.0", {"main"}, "main"), "main")
        self.assertEqual(mr.branche_proposee("18.0", None, None), "18.0")

    def test_an_url_off_github_keeps_its_prefix(self):
        self.assertEqual(
            mr.depot_de_l_url("git@gitlab.exemple.invalid:groupe/outils.git"),
            ("groupe", "outils", "git@gitlab.exemple.invalid:groupe/"),
        )
        self.assertEqual(
            mr.depot_de_l_url("git@github.com:Exemple/outils.git"),
            ("Exemple", "outils", "https://github.com/Exemple/"),
        )
        self.assertIsNone(mr.depot_de_l_url("pas-une-url"))


class TestLesVersions(Racine):
    def test_only_installed_versions_with_a_manifest(self):
        self.assertEqual(mr.versions_installees(self.racine), ["18.0"])
        with open(
            os.path.join(self.racine, ".repo", "installed_odoo_version.txt"),
            "w",
        ) as fh:
            fh.write("odoo17.0\nodoo16.0\n")
        self.assertEqual(mr.versions_installees(self.racine), ["17.0", "18.0"])
        os.remove(
            os.path.join(self.racine, ".repo", "installed_odoo_version.txt")
        )
        with mock.patch.object(
            repo_upgrade, "version_active", return_value=""
        ):
            self.assertEqual(
                mr.versions_installees(self.racine), ["17.0", "18.0"]
            )


class TestLePrive(Racine):
    def ajouter(self, url="https://github.com/Exemple/outils", **kw):
        kw.setdefault("disponibles", {"main"})
        with mock.patch.object(mr, "tete", return_value=GEL):
            return mr.ajouter_depot(
                url, "18.0", "main", racine=self.racine, prive=True, **kw
            )

    def test_private_creates_the_file_and_registers_it_once(self):
        public = self.lire("manifest/git_manifest_odoo18.0.xml")
        fichier, plan, gel = self.ajouter()
        self.assertEqual(
            os.path.relpath(fichier, self.racine),
            "private/manifest/git_manifest_private_odoo18.0.xml",
        )
        texte = self.lire("private/manifest/git_manifest_private_odoo18.0.xml")
        self.assertIn('path="odoo18.0/addons/Exemple_outils"', texte)
        self.assertIn(
            '<remote name="Exemple" fetch="https://github.com/Exemple/"', texte
        )
        self.assertEqual(
            gel, GEL, "le manifeste public est gelé : l'ajout suit"
        )
        self.assertEqual(
            self.lire("manifest/git_manifest_odoo18.0.xml"), public
        )
        self.ajouter("https://github.com/Exemple/autre")
        with open(
            os.path.join(self.racine, "private", "default_git_manifest.csv"),
            newline="",
        ) as fh:
            lignes = [r["filepath"] for r in csv.DictReader(fh)]
        self.assertEqual(
            lignes, ["private/manifest/git_manifest_private_odoo18.0.xml"]
        )

    def test_a_repository_of_either_manifest_is_refused_in_the_other(self):
        self.ajouter()
        with self.assertRaises(ValueError):
            with mock.patch.object(mr, "tete", return_value=GEL):
                mr.ajouter_depot(
                    "https://github.com/Exemple/outils",
                    "18.0",
                    "main",
                    racine=self.racine,
                    disponibles={"main"},
                )
        with self.assertRaises(ValueError):
            self.ajouter("https://github.com/OCA/web")

    def test_without_checking_the_host_no_freeze_is_possible(self):
        _f, plan, gel = self.ajouter(verifier=False, disponibles=None)
        self.assertIsNone(gel)
        self.assertEqual(plan["revision"], "main")
        with self.assertRaises(ValueError):
            self.ajouter(
                "https://github.com/Exemple/autre", verifier=False, geler=True
            )


class TestLeClone(Racine):
    def test_read_without_network_tracked_branch_and_pushed(self):
        chemin = self.clone("odoo18.0/addons/addons")
        infos = mr.lire_clone(chemin)
        self.assertEqual(
            (infos["remote"], infos["branche"], infos["pousse"]),
            ("origin", "main", True),
        )
        git(chemin, "commit", "-q", "--allow-empty", "-m", "deux")
        self.assertFalse(mr.lire_clone(chemin)["pousse"])
        git(chemin, "checkout", "-q", "--detach")
        with self.assertRaises(ValueError):
            mr.lire_clone(chemin)
        with self.assertRaises(ValueError):
            mr.lire_clone(os.path.join(chemin, "sous"))

    def test_declared_at_its_path_on_its_branch_frozen_on_head(self):
        chemin = self.clone("odoo18.0/addons/addons")
        fichier, plan, gel, infos = mr.ajouter_existant(
            "odoo18.0/addons/addons", "18.0", racine=self.racine
        )
        self.assertEqual(plan["path"], "odoo18.0/addons/addons")
        self.assertEqual(plan["revision"], "main")
        self.assertEqual(gel, git(chemin, "rev-parse", "HEAD"))
        self.assertTrue(fichier.endswith("manifest/git_manifest_odoo18.0.xml"))
        self.assertEqual(
            plan["fetch"],
            os.path.join(self.racine, "nus") + "/",
            "un remote hors GitHub garde son préfixe",
        )
        with self.assertRaises(ValueError):
            mr.ajouter_existant(
                "odoo18.0/addons/addons", "18.0", racine=self.racine
            )

    def test_an_unpushed_head_is_added_unfrozen_never_frozen(self):
        chemin = self.clone("odoo18.0/addons/addons")
        git(chemin, "commit", "-q", "--allow-empty", "-m", "deux")
        with self.assertRaises(ValueError):
            mr.ajouter_existant(
                "odoo18.0/addons/addons",
                "18.0",
                geler=True,
                racine=self.racine,
            )
        _f, _p, gel, _i = mr.ajouter_existant(
            "odoo18.0/addons/addons", "18.0", prive=True, racine=self.racine
        )
        self.assertIsNone(gel)

    def test_undeclared_clones_only_hidden_and_declared_left_out(self):
        self.clone("odoo18.0/addons/addons")
        self.clone("odoo18.0/addons/OCA_web")
        self.clone("odoo18.0/addons/.cache_x")
        os.makedirs(os.path.join(self.racine, "odoo18.0/addons/vide"))
        self.assertEqual(
            mr.clones_non_declares(self.racine),
            [("18.0", "odoo18.0/addons/addons")],
        )
        mr.ajouter_existant(
            "odoo18.0/addons/addons", "18.0", prive=True, racine=self.racine
        )
        self.assertEqual(mr.clones_non_declares(self.racine), [])


class TestLaMiseDeCote(Racine):
    def test_renamed_kept_and_suffixed(self):
        self.clone("odoo18.0/addons/addons")
        self.assertEqual(
            mr.mettre_de_cote("odoo18.0/addons/addons", self.racine),
            "odoo18.0/addons/.addons.avant_repo",
        )
        self.assertTrue(
            os.path.isdir(
                os.path.join(
                    self.racine, "odoo18.0/addons/.addons.avant_repo/.git"
                )
            )
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.racine, "odoo18.0/addons/addons"))
        )
        os.makedirs(os.path.join(self.racine, "odoo18.0/addons/addons"))
        os.rmdir(os.path.join(self.racine, "odoo18.0/addons/addons"))
        self.clone("odoo18.0/addons/addons")
        self.assertEqual(
            mr.mettre_de_cote("odoo18.0/addons/addons", self.racine),
            "odoo18.0/addons/.addons.avant_repo-2",
        )

    def test_dirty_or_unpushed_work_is_never_moved(self):
        chemin = self.clone("odoo18.0/addons/addons")
        with open(os.path.join(chemin, "x.py"), "w") as fh:
            fh.write("")
        with self.assertRaises(ValueError):
            mr.mettre_de_cote("odoo18.0/addons/addons", self.racine)
        os.remove(os.path.join(chemin, "x.py"))
        git(chemin, "commit", "-q", "--allow-empty", "-m", "deux")
        with self.assertRaises(ValueError):
            mr.mettre_de_cote("odoo18.0/addons/addons", self.racine)
        self.assertTrue(os.path.isdir(chemin))


class TestLeMenu(Racine):
    def setUp(self):
        super().setUp()
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)
        p = mock.patch.object(gm, "RACINE", self.racine)
        p.start()
        self.addCleanup(p.stop)

    def lancer(self, methode, reponses):
        with (
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch("builtins.print") as sortie,
        ):
            code = getattr(self.todo, methode)()
        return code, "\n".join(
            str(c.args[0]) for c in sortie.call_args_list if c.args
        )

    def test_existing_clone_private_frozen_then_set_aside_and_synced(self):
        self.clone("odoo18.0/addons/addons")
        with mock.patch.object(
            gm.manifest_repo, "executer", return_value=0
        ) as executer:
            code, texte = self.lancer(
                "_git_ajouter_existant", ["1", "2", "", "o"]
            )
        self.assertEqual(code, 0)
        self.assertIn("[1] odoo18.0/addons/addons (Odoo 18.0)", texte)
        self.assertIn(
            'freeze-revision="',
            self.lire("private/manifest/git_manifest_private_odoo18.0.xml"),
        )
        self.assertTrue(
            os.path.isdir(
                os.path.join(self.racine, "odoo18.0/addons/.addons.avant_repo")
            )
        )
        commandes = executer.call_args.args[0]
        self.assertEqual(commandes[-1][-1], "odoo18.0/addons/addons")
        self.assertIn("Committez private/.", texte)

    def test_declining_the_set_aside_warns_that_repo_sync_fails(self):
        self.clone("odoo18.0/addons/addons")
        code, texte = self.lancer(
            "_git_ajouter_existant", ["odoo18.0/addons/addons", "1", "n", "n"]
        )
        self.assertEqual(code, 0)
        self.assertIn("D'ici là, repo sync échoue", texte)
        bloc = re.search(
            r"<project[^>]*?path=\"odoo18\.0/addons/addons\"[^>]*?/>",
            self.lire("manifest/git_manifest_odoo18.0.xml"),
            re.S,
        ).group(0)
        self.assertNotIn("freeze-revision", bloc)
        self.assertTrue(
            os.path.isdir(
                os.path.join(self.racine, "odoo18.0/addons/addons/.git")
            )
        )

    def navigateur(self, choix):
        """Un faux navigateur : retient où il s'ouvre et en quel mode, puis
        rend `choix` au rappel, ou rien quand `choix` est None (q)."""
        ouvertures = []

        class Faux:
            def __init__(self, depart, rappel, open_dir=False):
                ouvertures.append((depart, open_dir))
                self.rappel = rappel

            def run_main_frame(self):
                if choix is not None:
                    self.rappel(choix)

        module = types.SimpleNamespace(FileBrowser=Faux)
        p = mock.patch.object(gm, "todo_file_browser", module)
        p.start()
        self.addCleanup(p.stop)
        return ouvertures

    def test_enter_opens_the_browser_on_the_installed_version(self):
        self.clone("odoo18.0/addons/addons")
        ouvertures = self.navigateur(
            os.path.join(self.racine, "odoo18.0/addons/addons")
        )
        code, texte = self.lancer("_git_ajouter_existant", ["", "1", "n", "n"])
        self.assertEqual(code, 0)
        self.assertEqual(
            ouvertures, [(os.path.join(self.racine, "odoo18.0"), True)]
        )
        self.assertIn("Parcourir… (défaut)", texte)
        self.assertIn("choisissez « . »", texte)
        self.assertIn(
            'path="odoo18.0/addons/addons"',
            self.lire("manifest/git_manifest_odoo18.0.xml"),
        )

    def test_cancelling_the_browser_writes_nothing(self):
        self.clone("odoo18.0/addons/addons")
        public = self.lire("manifest/git_manifest_odoo18.0.xml")
        self.navigateur(None)
        code, _texte = self.lancer("_git_ajouter_existant", [""])
        self.assertEqual(code, 0)
        self.assertEqual(
            self.lire("manifest/git_manifest_odoo18.0.xml"), public
        )

    def test_a_directory_outside_the_root_is_refused(self):
        self.navigateur(os.path.dirname(self.racine))
        code, texte = self.lancer("_git_ajouter_existant", [""])
        self.assertEqual(code, 0)
        self.assertIn("Hors de la racine d'ERPLibre", texte)

    def test_without_urwid_enter_cancels(self):
        with mock.patch.object(gm, "todo_file_browser", None):
            code, texte = self.lancer("_git_ajouter_existant", [""])
        self.assertEqual(code, 0)
        self.assertNotIn("Parcourir", texte)
        self.assertNotIn("(défaut)", texte)

    def test_a_number_out_of_range_is_no_path(self):
        self.clone("odoo18.0/addons/addons")
        public = self.lire("manifest/git_manifest_odoo18.0.xml")
        code, texte = self.lancer("_git_ajouter_existant", ["5", "0"])
        self.assertEqual(code, 0)
        self.assertIn("Choix invalide : 5", texte)
        self.assertEqual(
            self.lire("manifest/git_manifest_odoo18.0.xml"), public
        )

    def test_no_visibility_chosen_writes_nothing(self):
        self.clone("odoo18.0/addons/addons")
        public = self.lire("manifest/git_manifest_odoo18.0.xml")
        code, _texte = self.lancer("_git_ajouter_existant", ["1", ""])
        self.assertEqual(code, 0)
        self.assertEqual(
            self.lire("manifest/git_manifest_odoo18.0.xml"), public
        )
        self.assertFalse(os.path.exists(os.path.join(self.racine, "private")))

    def test_add_by_url_proposes_the_host_default_branch(self):
        with (
            mock.patch.object(
                repo_upgrade,
                "branches_et_defaut",
                return_value=({"main", "otp-1"}, "main"),
            ),
            mock.patch.object(mr, "tete", return_value=GEL),
        ):
            code, texte = self.lancer(
                "_git_ajouter_depot",
                ["https://github.com/Exemple/outils", "2", "", ""],
            )
        self.assertEqual(code, 0)
        self.assertIn("Version d'Odoo : 18.0", texte)
        self.assertIn("branche par défaut : main", texte)
        self.assertIn(
            'revision="main"',
            self.lire("private/manifest/git_manifest_private_odoo18.0.xml"),
        )

    def test_an_unreachable_host_can_still_be_added_unchecked(self):
        with mock.patch.object(
            repo_upgrade, "branches_et_defaut", return_value=None
        ):
            code, _texte = self.lancer(
                "_git_ajouter_depot",
                ["git@gitlab.exemple.invalid:groupe/outils.git", "2", "o", ""],
            )
        self.assertEqual(code, 0)
        texte = self.lire("private/manifest/git_manifest_private_odoo18.0.xml")
        self.assertIn('revision="18.0"', texte)
        self.assertNotIn("freeze-revision", texte)


class TestLaLigneDeCommande(Racine):
    def test_add_local_without_set_aside_warns(self):
        self.clone("odoo18.0/addons/addons")
        with (
            mock.patch.object(mr, "_racine", return_value=self.racine),
            mock.patch("builtins.print") as sortie,
        ):
            code = mr.main(
                [
                    "add-local",
                    "odoo18.0/addons/addons",
                    "--private",
                    "--no-freeze",
                ]
            )
        self.assertEqual(code, 0)
        texte = "\n".join(str(c.args[0]) for c in sortie.call_args_list)
        self.assertIn("--set-aside", texte)
        self.assertNotIn(
            "freeze-revision",
            self.lire("private/manifest/git_manifest_private_odoo18.0.xml"),
        )


if __name__ == "__main__":
    unittest.main()
