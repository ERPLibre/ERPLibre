#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cycle de vie d'un dépôt du manifeste : le retirer, synchroniser son
seul clone, le geler sur un commit.

Manifestes et dépôts git jetables ; repo et le réseau ne sont jamais
lancés.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import manifest_repo as mr  # noqa: E402

IDENTITE = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@exemple.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@exemple.invalid",
}
GEL = "a" * 40

MANIFESTE = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="OCA" fetch="https://github.com/OCA/" />
    <remote name="Seul" fetch="https://github.com/Seul/" />
    <remote name="ERPLibre_origin_OCA" fetch="https://github.com/ERPLibre/" />

    <!-- <project name="vieux.git" path="x" remote="Seul" /> -->
    <project
        name="outil.git"
        revision="18.0"
        freeze-revision="{gel}"
        path="odoo18.0/addons/Seul_outil"
        remote="Seul"
        groups="addons,odoo18.0"
    />
    <project
        name="ai.git"
        revision="18.0_dev"
        freeze-revision="{gel}"
        path="odoo18.0/addons/OCA_ai"
        remote="ERPLibre_origin_OCA"
        fork-upstream-remote="OCA"
        fork-upstream="18.0"
        fork-upstream-freeze-revision="{gel}"
        groups="addons,odoo18.0"
    />
</manifest>
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, IDENTITE)
        patch.start()
        self.addCleanup(patch.stop)
        self.racine = self.tmp.name
        self.manifestes = os.path.join(self.racine, "manifest")
        os.makedirs(self.manifestes)
        self.fichier = os.path.join(
            self.manifestes, "git_manifest_odoo18.0.xml"
        )
        with open(self.fichier, "w") as fh:
            fh.write(MANIFESTE.format(gel=GEL))
        patch = mock.patch.object(mr.repo_upgrade, "DOSSIER", self.manifestes)
        patch.start()
        self.addCleanup(patch.stop)

    def lire(self):
        with open(self.fichier) as fh:
            return fh.read()


class TestRetirer(Base):
    def test_the_project_and_its_now_unused_remote_go(self):
        fichier, projet, remote = mr.retirer_depot("18.0", "Seul_outil")
        texte = self.lire()
        self.assertEqual(remote, "Seul")
        self.assertNotIn('name="outil.git"', texte)
        self.assertNotIn('<remote name="Seul"', texte)
        # Le projet commenté qui nommait Seul n'est pas un usage, et reste.
        self.assertIn('<!-- <project name="vieux.git"', texte)
        self.assertIn('name="ai.git"', texte)
        mr.repo_upgrade.lire_manifestes("18.0", self.manifestes)

    def test_a_remote_still_named_as_upstream_stays(self):
        _f, _p, remote = mr.retirer_depot("18.0", "OCA_ai")
        texte = self.lire()
        self.assertEqual(remote, "ERPLibre_origin_OCA")
        self.assertIn('<remote name="OCA"', texte)
        texte = texte.replace(
            "</manifest>",
            '    <project name="b.git" path="b" remote="OCA" fork-upstream-remote="Seul" />\n</manifest>',
        )
        neuf, remote = mr.retirer_projet(
            texte, "outil.git", "odoo18.0/addons/Seul_outil"
        )
        self.assertIsNone(remote)
        self.assertIn('<remote name="Seul"', neuf)

    def test_an_unknown_path_writes_nothing(self):
        avant = self.lire()
        with self.assertRaises(ValueError):
            mr.retirer_depot("18.0", "absent")
        self.assertEqual(self.lire(), avant)


class TestSynchroniser(Base):
    def local(self, revision):
        chemin = os.path.join(self.racine, mr.MANIFESTE_LOCAL)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w") as fh:
            fh.write(
                f'<manifest><project name="a.git" path="a" revision="{revision}" /></manifest>'
            )

    def test_the_mode_of_the_checkout_is_kept(self):
        self.local(GEL)
        fusion, synchro = mr.commandes_synchro(
            self.racine, "odoo18.0/addons/OCA_ai"
        )
        self.assertIn("--freeze", fusion)
        self.assertEqual(synchro[-1], "odoo18.0/addons/OCA_ai")
        self.local("18.0")
        fusion, _s = mr.commandes_synchro(self.racine, "x")
        self.assertNotIn("--freeze", fusion)

    def test_a_local_sync_of_everything_to_drop_obsolete_clones(self):
        _f, synchro = mr.commandes_synchro(self.racine, local=True)
        self.assertIn("-l", synchro)
        self.assertTrue(synchro[-1].startswith("-j"))

    def test_execution_stops_at_the_first_failure(self):
        with mock.patch.object(
            mr.subprocess, "call", side_effect=[3, 0]
        ) as appel:
            self.assertEqual(mr.executer([["a"], ["b"]], self.racine), 3)
        self.assertEqual(appel.call_count, 1)


class TestRegeler(Base):
    def clone(self, chemin):
        clone = os.path.join(self.racine, chemin)
        os.makedirs(clone)
        for args in (
            ["init", "-q", "-b", "18.0"],
            ["commit", "-q", "--allow-empty", "-m", "x"],
        ):
            subprocess.run(
                ["git", "-C", clone, *args], check=True, capture_output=True
            )
        return (
            clone,
            subprocess.run(
                ["git", "-C", clone, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip(),
        )

    def test_head_is_frozen_and_an_unpushed_commit_flagged(self):
        clone, tete = self.clone("odoo18.0/addons/Seul_outil")
        res = mr.regeler("18.0", "Seul_outil", self.racine)
        self.assertEqual(res["sha"], tete)
        self.assertFalse(res["pousse"])
        self.assertIn(f'freeze-revision="{tete}"', self.lire())
        subprocess.run(
            ["git", "-C", clone, "update-ref", "refs/remotes/Seul/18.0", tete],
            check=True,
        )
        self.assertTrue(
            mr.regeler("18.0", "Seul_outil", self.racine)["pousse"]
        )

    def test_a_fork_gets_its_upstream_base_again(self):
        _c, tete = self.clone("odoo18.0/addons/OCA_ai")
        base = "b" * 40
        with mock.patch(
            "script.git.git_freeze_manifest.base_amont",
            return_value={"base": base, "motif": None},
        ):
            res = mr.regeler("18.0", "OCA_ai", self.racine)
        bloc = self.lire().split('name="ai.git"')[1].split("/>")[0]
        self.assertIn(f'freeze-revision="{tete}"', bloc)
        self.assertIn(f'fork-upstream-freeze-revision="{base}"', bloc)
        self.assertEqual(res["base"], base)

    def test_an_unknown_commit_is_refused(self):
        self.clone("odoo18.0/addons/Seul_outil")
        avant = self.lire()
        with self.assertRaises(ValueError):
            mr.regeler("18.0", "Seul_outil", self.racine, "c" * 40)
        self.assertEqual(self.lire(), avant)


class TestLaLigneDeCommande(Base):
    def test_remove_then_apply_runs_a_local_sync(self):
        with (
            mock.patch.object(mr, "_racine", return_value=self.racine),
            mock.patch.object(mr, "executer", return_value=0) as executer,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(
                mr.main(
                    ["remove", "Seul_outil", "--version", "18.0", "--apply"]
                ),
                0,
            )
        self.assertIn("-l", executer.call_args.args[0][1])
        self.assertNotIn('name="outil.git"', self.lire())

    def test_sync_targets_the_one_path(self):
        with (
            mock.patch.object(mr, "_racine", return_value=self.racine),
            mock.patch.object(mr, "executer", return_value=0) as executer,
        ):
            self.assertEqual(
                mr.main(["sync", "OCA_ai", "--version", "18.0"]), 0
            )
        self.assertEqual(
            executer.call_args.args[0][1][-1], "odoo18.0/addons/OCA_ai"
        )


if __name__ == "__main__":
    unittest.main()
