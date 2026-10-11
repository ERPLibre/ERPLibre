#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les lecteurs du manifeste local face à un manifeste fusionné avec --freeze.

Gelé, un projet porte le commit dans « revision » et sa branche dans
« dest-branch » et « upstream ». Un lecteur qui prend « revision » pour un
nom de branche crée alors une branche nommée d'après le commit, ou compare
un nom de branche à un commit. Chaque lecteur est éprouvé ici dans les deux
modes : gelé, et le mode qui suit les branches, qui ne doit pas bouger.

Le serveur git local a « git » remplacé par une table de réponses : il
ÉCRIT dans les dépôts. La comparaison au manifeste ne fait que lire, et se
vérifie sur de vrais dépôts jetables.
"""

import asyncio
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from git import Repo

from script.git import git_local_server as server
from script.git import git_show_code_diff_repo_manifest as diff
from script.todo import todo_upgrade
from script.todo.todo_upgrade import TodoUpgrade

SHA = "1234567890abcdef1234567890abcdef12345678"

MANIFESTE = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.invalid/"/>
  <project name="gele" path="addons/gele" remote="origin"
    revision="{SHA}" upstream="18.0_up" dest-branch="18.0_dev"/>
  <project name="amont" path="addons/amont" remote="origin"
    revision="{SHA}" upstream="18.0_up"/>
  <project name="orphelin" path="addons/orphelin" remote="origin"
    revision="{SHA}"/>
  <project name="branche" path="addons/branche" remote="origin"
    revision="refs/heads/18.0"/>
</manifest>
"""


def ecrire_manifeste(dossier):
    chemin = os.path.join(dossier, "erplibre_manifest.xml")
    with open(chemin, "w") as f:
        f.write(MANIFESTE)
    return chemin


class GitSimule:
    """Remplace `_run_git` : note chaque commande, rend un code par verbe."""

    def __init__(self, codes=None):
        self.codes = codes or {}
        self.vues = []

    async def __call__(self, *args, cwd=None, timeout=None):
        commande = list(args[3:]) if args[1] == "-C" else list(args[1:])
        self.vues.append(commande)
        return "", "", self.codes.get(commande[0], 0)

    def verbes(self, verbe):
        return [c for c in self.vues if c[0] == verbe]


class TestParseManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        projets = server.parse_manifest(ecrire_manifeste(self.tmp.name))
        self.par_nom = {p["name"]: p for p in projets}

    def test_le_commit_reste_dans_revision(self):
        self.assertEqual(self.par_nom["gele"]["revision"], SHA)

    def test_la_branche_vient_de_dest_branch_d_abord(self):
        self.assertEqual(self.par_nom["gele"]["branch"], "18.0_dev")

    def test_upstream_sert_de_repli(self):
        self.assertEqual(self.par_nom["amont"]["branch"], "18.0_up")

    def test_un_commit_sans_branche_n_a_pas_de_branche(self):
        self.assertIsNone(self.par_nom["orphelin"]["branch"])

    def test_une_branche_reste_sa_propre_branche(self):
        p = self.par_nom["branche"]
        self.assertEqual(p["revision"], "refs/heads/18.0")
        self.assertEqual(p["branch"], "refs/heads/18.0")


class TestRacineErplibre(unittest.TestCase):
    def _projet(self, sortie):
        rendu = subprocess.CompletedProcess([], 0, stdout=sortie, stderr="")
        with patch.object(server.subprocess, "run", return_value=rendu):
            return server.get_erplibre_root_project("/racine")

    def test_une_tete_detachee_n_est_pas_une_branche(self):
        self.assertIsNone(self._projet("HEAD\n")["branch"])

    def test_la_branche_courante_est_suivie(self):
        self.assertEqual(self._projet("develop\n")["branch"], "develop")


class TestBareHead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "depot.git"))

    def _lancer(self, projet):
        simule = GitSimule()
        with patch.object(server, "_run_git", simule):
            asyncio.run(server._update_bare_head(self.tmp.name, projet))
        return simule

    def test_gele_pointe_sur_la_branche(self):
        simule = self._lancer(
            {"name": "depot", "path": "p", "revision": SHA, "branch": "18.0"}
        )
        self.assertEqual(
            simule.vues, [["symbolic-ref", "HEAD", "refs/heads/18.0"]]
        )

    def test_nom_court_d_une_reference_complete(self):
        simule = self._lancer(
            {
                "name": "depot",
                "path": "p",
                "revision": "refs/heads/18.0",
                "branch": "refs/heads/18.0",
            }
        )
        self.assertEqual(
            simule.vues, [["symbolic-ref", "HEAD", "refs/heads/18.0"]]
        )

    def test_un_commit_sans_branche_ne_touche_pas_head(self):
        with self.assertLogs(server._logger, "INFO"):
            simule = self._lancer(
                {"name": "depot", "path": "p", "revision": SHA, "branch": None}
            )
        self.assertEqual(simule.vues, [])


class TestPushTeteDetachee(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "addons", "p"))

    def _pousser(self, projet, codes=None):
        simule = GitSimule(codes)

        async def detachee(_chemin):
            return True

        with patch.object(server, "_run_git", simule), patch.object(
            server, "_is_detached_head", detachee
        ):
            statut = asyncio.run(
                server._push_single_repo(
                    self.tmp.name,
                    os.path.join(self.tmp.name, "serveur"),
                    projet,
                    "local",
                    False,
                    False,
                    asyncio.Semaphore(1),
                )
            )
        return statut, simule

    def test_gele_cree_la_branche_du_manifeste(self):
        statut, simule = self._pousser(
            {
                "name": "d",
                "path": "addons/p",
                "revision": SHA,
                "branch": "18.0",
            },
            codes={"show-ref": 1},
        )
        self.assertEqual(
            simule.verbes("checkout"), [["checkout", "-b", "18.0"]]
        )
        self.assertEqual(statut, ("pushed", True))

    def test_un_commit_sans_branche_n_est_jamais_une_branche(self):
        with self.assertLogs(server._logger, "WARNING") as journal:
            statut, simule = self._pousser(
                {
                    "name": "d",
                    "path": "addons/p",
                    "revision": SHA,
                    "branch": None,
                }
            )
        self.assertEqual(simule.verbes("checkout"), [])
        self.assertTrue(any("checkout skipped" in m for m in journal.output))
        self.assertFalse(any(SHA in c for c in simule.vues if c[0] != "push"))
        self.assertEqual(statut[1], False)

    def test_sans_revision_reste_une_erreur(self):
        statut, simule = self._pousser(
            {"name": "d", "path": "addons/p", "revision": None, "branch": None}
        )
        self.assertEqual(statut, ("error", False))
        self.assertEqual(simule.verbes("push"), [])


class TestBrancheDuManifesteLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        chemin = ecrire_manifeste(self.tmp.name)
        patcher = patch.object(todo_upgrade, "LOCAL_MANIFEST", chemin)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _branche(self, chemin):
        return TodoUpgrade.get_branch_name_from_local_manifest(
            None, chemin, "19.0"
        )

    def test_gele_rend_la_branche(self):
        self.assertEqual(self._branche("addons/gele"), "18.0_dev")

    def test_gele_sans_dest_branch_rend_upstream(self):
        self.assertEqual(self._branche("addons/amont"), "18.0_up")

    def test_commit_sans_branche_rend_le_defaut(self):
        self.assertEqual(self._branche("addons/orphelin"), "19.0")

    def test_branche_inchangee(self):
        self.assertEqual(self._branche("addons/branche"), "refs/heads/18.0")

    def test_projet_absent_rend_le_defaut(self):
        self.assertEqual(self._branche("addons/inconnu"), "19.0")


def git(depot, *args):
    return subprocess.run(
        ["git", "-C", depot, *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    ).stdout.strip()


class TestComparaisonAuManifeste(unittest.TestCase):
    """Un dépôt de deux commits : « gel », puis « apres » sur 18.0."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.depot = self.tmp.name
        git(d, "init", "-q", "-b", "18.0")
        git(d, "commit", "-q", "--allow-empty", "-m", "gel")
        self.gel = git(d, "rev-parse", "HEAD")
        git(d, "commit", "-q", "--allow-empty", "-m", "apres")
        self.apres = git(d, "rev-parse", "HEAD")

    def _comparer(self, revision, **attrs):
        projet = {"@path": self.depot, "@revision": revision}
        projet.update({f"@{k.replace('_', '-')}": v for k, v in attrs.items()})
        return diff.compare_project(Repo(self.depot), projet, "origin")

    def test_gele_detache_sur_le_commit(self):
        git(self.depot, "checkout", "-q", "--detach", self.gel)
        self.assertEqual(
            self._comparer(self.gel, dest_branch="18.0"),
            ("PASS", diff.PASS_DETACHED),
        )

    def test_gele_sur_sa_branche_au_commit(self):
        git(self.depot, "reset", "-q", "--hard", self.gel)
        self.assertEqual(
            self._comparer(self.gel, dest_branch="18.0"), ("PASS", "")
        )

    def test_gele_sur_sa_branche_en_reference_complete(self):
        git(self.depot, "reset", "-q", "--hard", self.gel)
        self.assertEqual(
            self._comparer(self.gel, upstream="refs/heads/18.0"),
            ("PASS", ""),
        )

    def test_gele_sur_une_autre_branche_au_commit(self):
        git(self.depot, "checkout", "-q", "-b", "travail", self.gel)
        self.assertEqual(
            self._comparer(self.gel, dest_branch="18.0"),
            ("PASS", diff.PASS_OTHER_BRANCH),
        )

    def test_gele_branche_avancee_non_poussee(self):
        niveau, message = self._comparer(self.gel, dest_branch="18.0")
        self.assertEqual(niveau, "ERROR")
        self.assertIn(self.gel, message)
        self.assertIn(self.apres, message)

    def test_gele_branche_avancee_poussee(self):
        git(self.depot, "update-ref", "refs/remotes/origin/18.0", self.apres)
        niveau, message = self._comparer(self.gel, dest_branch="18.0")
        self.assertEqual(niveau, "WARNING")
        self.assertIn(self.gel, message)

    def test_gele_detache_ailleurs(self):
        git(self.depot, "checkout", "-q", "--detach", self.apres)
        niveau, _message = self._comparer(self.gel, dest_branch="18.0")
        self.assertEqual(niveau, "ERROR")

    def test_branche_sur_sa_branche(self):
        self.assertEqual(self._comparer("18.0"), ("PASS", ""))

    def test_branche_detachee_sans_distante(self):
        git(self.depot, "checkout", "-q", "--detach", self.gel)
        niveau, message = self._comparer("18.0")
        self.assertEqual(niveau, "ERROR")
        self.assertIn("manifest revision is 18.0", message)

    def test_branche_detachee_a_jour_de_la_distante(self):
        git(self.depot, "update-ref", "refs/remotes/origin/18.0", self.gel)
        git(self.depot, "checkout", "-q", "--detach", self.gel)
        self.assertEqual(self._comparer("18.0"), ("PASS", diff.PASS_DETACHED))

    def test_branche_autre_branche_sans_distante(self):
        git(self.depot, "checkout", "-q", "-b", "travail", self.gel)
        niveau, message = self._comparer("18.0")
        self.assertEqual(niveau, "ERROR")
        self.assertIn("actual revision is travail", message)


class TestFormatResult(unittest.TestCase):
    def test_niveau_seul(self):
        self.assertEqual(
            diff.format_result("PASS", ""),
            f"{diff.Fore.GREEN}PASS{diff.Style.RESET_ALL}",
        )

    def test_niveau_et_message(self):
        self.assertEqual(
            diff.format_result("ERROR", "x"),
            f"{diff.Fore.RED}ERROR{diff.Style.RESET_ALL} x",
        )


if __name__ == "__main__":
    unittest.main()
