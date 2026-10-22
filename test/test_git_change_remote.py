#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un dépôt fautif n'arrête pas le lot, et le bilan le nomme à la fin.

Un checkout de développement porte des répertoires vidés à la main, des
clones interrompus, des `.git` effacés. Ils n'ont rien à voir avec les cent
quarante autres dépôts qui attendent leur nouveau remote, et une trace de
cette longueur noie l'avertissement qui passe au moment où il survient.
"""

import io
import os
import subprocess
import unittest
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory

from script.git.git_change_remote_https_to_git import (
    change_all_remotes,
    print_report,
)
from script.git.git_tool import GitTool

HTTPS = "https://github.com/OCA/web.git"
GIT = "git@github.com:OCA/web.git"


def _depot(chemin, url=HTTPS):
    """Un vrai dépôt git. Rien n'est bouchonné : c'est la lecture et
    l'écriture des remotes par git qu'on vérifie."""
    os.makedirs(chemin, exist_ok=True)
    subprocess.run(["git", "init", "-q", chemin], check=True)
    subprocess.run(
        ["git", "-C", chemin, "remote", "add", "origin", url], check=True
    )
    return chemin


def _url(chemin):
    return subprocess.run(
        ["git", "-C", chemin, "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class UnDepotFautifNArretePasLeLot(unittest.TestCase):
    def _lot(self, racine, noms):
        with redirect_stdout(io.StringIO()) as sortie:
            changed, skipped = change_all_remotes(
                GitTool(), [{"name": n} for n in noms], racine
            )
        return changed, skipped, sortie.getvalue()

    def test_un_repertoire_sans_depot_git_est_ignore(self):
        """Le répertoire existe et ne porte plus de dépôt git :
        `os.path.isdir` passe, l'ouverture du dépôt lève."""
        with TemporaryDirectory() as racine:
            _depot(os.path.join(racine, "addons/Bon"))
            os.makedirs(os.path.join(racine, "addons/Vide"))
            changed, skipped, _ = self._lot(
                racine, ["addons/Bon", "addons/Vide"]
            )
            self.assertEqual(_url(os.path.join(racine, "addons/Bon")), GIT)
        self.assertEqual(changed, 1)
        self.assertEqual(len(skipped), 1)
        self.assertIn("addons/Vide", skipped[0][0])
        self.assertIn("no git repository", skipped[0][1])

    def test_le_lot_continue_apres_le_fautif(self):
        """Le fautif est au MILIEU : ce qui le suit doit être servi."""
        with TemporaryDirectory() as racine:
            os.makedirs(os.path.join(racine, "addons/Vide"))
            _depot(os.path.join(racine, "addons/Apres"))
            changed, skipped, _ = self._lot(
                racine, ["addons/Vide", "addons/Apres"]
            )
            self.assertEqual(_url(os.path.join(racine, "addons/Apres")), GIT)
        self.assertEqual(changed, 1)
        self.assertEqual(len(skipped), 1)

    def test_un_repertoire_absent_est_ignore_aussi(self):
        with TemporaryDirectory() as racine:
            changed, skipped, _ = self._lot(racine, ["addons/Absent"])
        self.assertEqual(changed, 0)
        self.assertEqual(skipped[0][1], "directory is missing")

    def test_rien_a_signaler_ne_signale_rien(self):
        with TemporaryDirectory() as racine:
            _depot(os.path.join(racine, "addons/Bon"))
            changed, skipped, _ = self._lot(racine, ["addons/Bon"])
        self.assertEqual((changed, skipped), (1, []))


class LeBilanSeLitALaFin(unittest.TestCase):
    """Ce que l'humain lit d'un lot long, c'est sa fin."""

    def _bilan(self, total, changed, skipped):
        with redirect_stdout(io.StringIO()) as sortie:
            print_report(total, changed, skipped)
        return sortie.getvalue()

    def test_il_nomme_chaque_depot_ignore_et_sa_raison(self):
        texte = self._bilan(
            3, 1, [("addons/Vide", "no git repository"), ("addons/X", "gone")]
        )
        self.assertIn("3 repo, 1 remote updated, 2 skipped", texte)
        self.assertIn("addons/Vide — no git repository", texte)
        self.assertIn("addons/X — gone", texte)

    def test_sans_incident_il_ne_liste_rien(self):
        texte = self._bilan(2, 2, [])
        self.assertIn("2 repo, 2 remote updated, 0 skipped", texte)
        self.assertNotIn("Skipped", texte)


class LesDepotsDeclaresParERPLibre(unittest.TestCase):
    """Un projet que conf/git_manifest.csv déclare, cloné sur le disque
    hors de Google Repo (les jeux du Stream Deck par l'installateur), est
    traité même absent du manifeste local."""

    MANIFESTE = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n'
        '  <remote name="TechnoLibre" fetch="https://github.com/TechnoLibre/"/>\n'
        '  <project name="jeux.git" path="script/jeux" remote="TechnoLibre"'
        ' revision="main"/>\n'
        '  <project name="absent.git" path="script/absent"'
        ' remote="TechnoLibre"/>\n'
        '  <project name="vide.git" path="script/vide" remote="TechnoLibre"/>\n'
        "</manifest>\n"
    )

    def racine(self, dossier):
        os.makedirs(os.path.join(dossier, "conf"))
        os.makedirs(os.path.join(dossier, "manifest"))
        with open(os.path.join(dossier, "conf/git_manifest.csv"), "w") as f:
            f.write('"filepath"\nmanifest/jeux.xml\n')
        with open(os.path.join(dossier, "manifest/jeux.xml"), "w") as f:
            f.write(self.MANIFESTE)
        _depot(os.path.join(dossier, "script/jeux"))
        os.makedirs(os.path.join(dossier, "script/vide"))
        return dossier

    def test_a_declared_clone_on_disk_is_added_once(self):
        with TemporaryDirectory() as dossier:
            racine = self.racine(dossier)
            deja = [{"name": "", "path": racine}]
            repos = GitTool().add_declared_repos(deja, racine)
            self.assertEqual(["", "script/jeux"], [r["name"] for r in repos])
            (jeux,) = [r for r in repos if r["name"] == "script/jeux"]
            self.assertEqual(
                "git@github.com:TechnoLibre/jeux.git", jeux["url_git"]
            )
            again = GitTool().add_declared_repos(list(repos), racine)
            self.assertEqual(repos, again)

    def test_its_remote_is_then_rewritten(self):
        with TemporaryDirectory() as dossier:
            racine = self.racine(dossier)
            repos = GitTool().add_declared_repos([], racine)
            with redirect_stdout(io.StringIO()):
                changed, skipped = change_all_remotes(GitTool(), repos, racine)
            self.assertEqual((1, []), (changed, skipped))
            self.assertEqual(GIT, _url(os.path.join(racine, "script/jeux")))

    def test_without_the_list_nothing_is_added(self):
        with TemporaryDirectory() as dossier:
            self.assertEqual([], GitTool().add_declared_repos([], dossier))


if __name__ == "__main__":
    unittest.main()
