#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le remote amont nommé d'un fork, posé et récupéré sur de vrais dépôts.

Un dossier temporaire tient les amonts nus, les forks nus, leurs clones et
un manifeste qui les décrit ; toutes les URL sont des « file:// » de ce
dossier, seul transport local qui honore « --depth ». La configuration git
de l'hôte n'est pas lue. Tous les noms de dépôts et de remotes sont
inventés.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from script.git import repo_upgrade

VERSION = "X.0"
REMOTE_FORK = "R_origin_U"


def _git(cwd, *args):
    """Lance git dans `cwd`. Rend stdout, sans espaces autour."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class DepotsAvecManifeste(unittest.TestCase):
    """Des forks clonés sous `racine`, décrits par un manifeste.

    `projet` ajoute une ligne au manifeste ; `forker` crée l'amont nu sous
    « amont/ », le fork nu qui en descend et le clone du fork sous
    `racine`, en HEAD détachée comme git-repo le pose.
    """

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        env = patch.dict(
            os.environ,
            {
                "GIT_CEILING_DIRECTORIES": self.dossier,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.racine = os.path.join(self.dossier, "racine")
        self.manifestes = os.path.join(self.dossier, "manifest")
        self.amonts = os.path.join(self.dossier, "amont")
        self.forks = os.path.join(self.dossier, "fork")
        for d in (self.racine, self.manifestes, self.amonts, self.forks):
            os.makedirs(d)
        self.travail = os.path.join(self.dossier, "travail")
        _git(self.dossier, "init", "-q", "-b", "principale", self.travail)
        self.lignes = []

    def url(self, nom):
        return f"file://{self.amonts}/{nom}"

    def commit(self, depot, contenu):
        with open(os.path.join(depot, "a.txt"), "w") as fh:
            fh.write(contenu)
        _git(depot, "add", "a.txt")
        _git(depot, "commit", "-q", "-m", contenu)
        return _git(depot, "rev-parse", "HEAD")

    def forker(self, nom, amont=True, profondeur=None):
        """Amont, fork et clone de `nom`. Rend (chemin relatif, clone).

        Sans `amont`, aucun dépôt amont n'est créé : son URL ne répond
        pas. `profondeur` rend le clone superficiel.
        """
        self.commit(self.travail, f"{nom} un")
        if amont:
            depot = os.path.join(self.amonts, nom)
            _git(self.dossier, "init", "-q", "--bare", depot)
            _git(self.travail, "push", "-q", depot, "HEAD:principale")
            _git(self.travail, "tag", "-f", f"amont-{nom}")
            _git(self.travail, "push", "-q", depot, f"amont-{nom}")
        fork = os.path.join(self.forks, nom)
        _git(self.dossier, "init", "-q", "--bare", fork)
        _git(self.travail, "push", "-q", fork, "HEAD:X.0_dev")
        chemin = f"odooX/addons/R_{nom.replace('.git', '')}"
        clone = os.path.join(self.racine, chemin)
        options = [f"--depth={profondeur}"] if profondeur else []
        _git(
            self.dossier,
            "clone",
            "-q",
            "-o",
            REMOTE_FORK,
            "-b",
            "X.0_dev",
            *options,
            f"file://{fork}",
            clone,
        )
        _git(clone, "checkout", "-q", "--detach")
        return chemin, clone

    def projet(self, nom, chemin, **attrs):
        texte = " ".join(
            f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items()
        )
        self.lignes.append(
            f'  <project name="{nom}" path="{chemin}" remote="{REMOTE_FORK}"'
            f' revision="X.0_dev" {texte}/>'
        )

    def ecrire_manifeste(self):
        with open(
            os.path.join(self.manifestes, f"git_manifest_odoo{VERSION}.xml"),
            "w",
        ) as fh:
            fh.write(
                "<manifest>\n"
                f'  <remote name="{REMOTE_FORK}" fetch="file://{self.forks}/"/>'
                "\n"
                f'  <remote name="U" fetch="file://{self.amonts}/"/>\n'
                + "\n".join(self.lignes)
                + "\n</manifest>\n"
            )

    def amont_declare(self, nom, branche="principale"):
        return {
            "remote": "U",
            "nom": nom,
            "url": self.url(nom),
            "branche": branche,
            "source": "declare",
            "remote_declare": True,
        }


class TestPreparerRemote(DepotsAvecManifeste):
    def setUp(self):
        super().setUp()
        _chemin, self.clone = self.forker("web.git")

    def test_remote_absent_ajoute_sans_tags(self):
        etat, en_place = repo_upgrade.preparer_remote(
            self.clone, self.amont_declare("web.git")
        )
        self.assertEqual((etat, en_place), ("ajoute", None))
        self.assertEqual(
            _git(self.clone, "config", "remote.U.url"), self.url("web.git")
        )
        self.assertEqual(
            _git(self.clone, "config", "remote.U.tagOpt"), "--no-tags"
        )

    def test_le_remote_ajoute_ne_suit_que_la_branche_declaree(self):
        """Un « git fetch U » sans argument n'amène que la branche amont
        déclarée, et le remote d'un clone complet reste dans
        « git fetch --all »."""
        _git(self.travail, "push", "-q", self.url("web.git"), "HEAD:autre")
        repo_upgrade.preparer_remote(self.clone, self.amont_declare("web.git"))
        self.assertEqual(
            _git(self.clone, "config", "--get-all", "remote.U.fetch"),
            "+refs/heads/principale:refs/remotes/U/principale",
        )
        _git(self.clone, "fetch", "-q", "U")
        self.assertEqual(
            _git(
                self.clone,
                "for-each-ref",
                "--format=%(refname)",
                "refs/remotes/U",
            ),
            "refs/remotes/U/principale",
        )
        sortie = subprocess.run(
            ["git", "config", "remote.U.skipFetchAll"],
            cwd=self.clone,
            capture_output=True,
        )
        self.assertEqual(sortie.returncode, 1)

    def test_https_et_ssh_d_un_meme_depot_se_valent(self):
        """La conversion des remotes en ssh réécrit aussi le remote amont :
        il reste le même dépôt, pas une collision."""
        https = "https://forge.example.invalid/Org/web.git"
        ssh = "git@forge.example.invalid:Org/web.git"
        _git(self.clone, "remote", "add", "U", ssh)
        amont = dict(self.amont_declare("web.git"), url=https)
        self.assertEqual(
            repo_upgrade.preparer_remote(self.clone, amont), ("present", ssh)
        )
        self.assertEqual(_git(self.clone, "config", "remote.U.url"), ssh)
        _git(
            self.clone,
            "remote",
            "set-url",
            "U",
            "git@forge.example.invalid:Org/autre.git",
        )
        self.assertEqual(
            repo_upgrade.preparer_remote(self.clone, amont)[0], "autre_url"
        )

    def test_cle_url(self):
        meme = (
            "https://forge.example.invalid/Org/web.git",
            "https://Forge.example.invalid/Org/web/",
            "git@forge.example.invalid:Org/web.git",
            "ssh://git@forge.example.invalid:22/Org/web.git",
        )
        for url in meme:
            self.assertEqual(
                repo_upgrade.cle_url(url),
                ("forge.example.invalid", "Org/web"),
                url,
            )
        self.assertNotEqual(
            repo_upgrade.cle_url("git@forge.example.invalid:Org/web.git"),
            repo_upgrade.cle_url("git@forge.example.invalid:Autre/web.git"),
        )
        self.assertEqual(
            repo_upgrade.cle_url("file:///x/web.git/"), "file:///x/web.git"
        )

    def test_remote_present_a_la_meme_url(self):
        _git(self.clone, "remote", "add", "U", self.url("web.git"))
        self.assertEqual(
            repo_upgrade.preparer_remote(
                self.clone, self.amont_declare("web.git")
            ),
            ("present", self.url("web.git")),
        )

    def test_remote_a_une_autre_url_reste_intact(self):
        ailleurs = "file:///nulle-part/web.git"
        _git(self.clone, "remote", "add", "U", ailleurs)
        self.assertEqual(
            repo_upgrade.preparer_remote(
                self.clone, self.amont_declare("web.git")
            ),
            ("autre_url", ailleurs),
        )
        self.assertEqual(_git(self.clone, "config", "remote.U.url"), ailleurs)

    def test_l_url_se_lit_brute_sans_insteadof(self):
        """Une réécriture « insteadOf » ne fait pas passer une autre URL
        écrite pour l'URL déclarée : c'est l'URL écrite que set-url
        corrige."""
        _git(self.clone, "remote", "add", "U", "ancien:web.git")
        _git(
            self.clone,
            "config",
            f"url.file://{self.amonts}/.insteadOf",
            "ancien:",
        )
        etat, _en_place = repo_upgrade.preparer_remote(
            self.clone, self.amont_declare("web.git")
        )
        self.assertEqual(etat, "autre_url")

    def test_amont_devine_ou_sans_branche_n_a_pas_de_remote(self):
        devine = dict(self.amont_declare("web.git"), source="convention")
        sans_branche = self.amont_declare("web.git", branche=None)
        for amont in (devine, sans_branche, dict(devine, url="")):
            self.assertEqual(
                repo_upgrade.preparer_remote(self.clone, amont), (None, None)
            )
        self.assertEqual(_git(self.clone, "remote"), REMOTE_FORK)

    def test_un_simple_dossier_ne_recoit_rien(self):
        sous = os.path.join(self.clone, "sous")
        os.makedirs(sous)
        self.assertEqual(
            repo_upgrade.preparer_remote(sous, self.amont_declare("web.git")),
            ("non_clone", None),
        )
        self.assertEqual(_git(self.clone, "remote"), REMOTE_FORK)


class TestRecupererParLeRemote(DepotsAvecManifeste):
    def test_la_branche_de_suivi_et_fetch_head_avancent(self):
        _chemin, clone = self.forker("web.git")
        tip = self.commit(self.travail, "amont deux")
        _git(
            self.travail, "push", "-q", self.url("web.git"), "HEAD:principale"
        )
        repo_upgrade.preparer_remote(clone, self.amont_declare("web.git"))
        self.assertTrue(
            repo_upgrade.recuperer_amont(
                clone, self.url("web.git"), "principale", remote="U"
            )
        )
        self.assertEqual(_git(clone, "rev-parse", "U/principale"), tip)
        self.assertEqual(_git(clone, "rev-parse", "FETCH_HEAD"), tip)
        self.assertEqual(_git(clone, "tag", "--list"), "")

    def test_une_refspec_de_remote_restreinte_n_empeche_pas_le_suivi(self):
        _chemin, clone = self.forker("web.git")
        _git(clone, "remote", "add", "-t", "autre", "U", self.url("web.git"))
        self.assertTrue(
            repo_upgrade.recuperer_amont(
                clone, self.url("web.git"), "principale", remote="U"
            )
        )
        self.assertTrue(_git(clone, "rev-parse", "U/principale"))


class TestAjouterRemotes(DepotsAvecManifeste):
    """Chaque issue de `ajouter_remotes` sur un même manifeste."""

    def setUp(self):
        super().setUp()
        amont = {"fork_upstream_remote": "U", "fork_upstream": "principale"}
        chemin, _ = self.forker("ajoute.git")
        self.projet("ajoute.git", chemin, **amont)
        chemin, clone = self.forker("present.git")
        _git(clone, "remote", "add", "U", self.url("present.git"))
        self.projet("present.git", chemin, **amont)
        chemin, clone = self.forker("autre.git")
        _git(clone, "remote", "add", "U", "file:///nulle-part/autre.git")
        self.projet("autre.git", chemin, **amont)
        chemin, _ = self.forker("muet.git", amont=False)
        self.projet("muet.git", chemin, **amont)
        chemin, self.superficiel = self.forker("lourd.git", profondeur=1)
        self.projet("lourd.git", chemin, clone_depth="10", **amont)
        self.projet("manquant.git", "odooX/addons/R_manquant", **amont)
        self.projet("devine.git", "odooX/addons/R_devine")
        self.projet(
            "sans_branche.git",
            "odooX/addons/R_sans_branche",
            fork_upstream_remote="U",
        )
        self.ecrire_manifeste()
        self.lst = repo_upgrade.ajouter_remotes(
            VERSION, self.manifestes, self.racine, parallele=2
        )
        self.par_nom = {x["chemin"].split("R_")[-1]: x for x in self.lst}

    def test_chaque_issue(self):
        self.assertEqual(
            {nom: x["issue"] for nom, x in self.par_nom.items()},
            {
                "ajoute": "ajoute",
                "present": "present",
                "autre": "autre_url",
                "muet": "fetch_echoue",
                "lourd": "superficiel",
                "manquant": "absent",
                "devine": "non_declare",
                "sans_branche": "non_declare",
            },
        )
        self.assertEqual(self.par_nom["ajoute"]["cible"], "U/principale")
        self.assertTrue(self.par_nom["muet"]["remote_ajoute"])
        self.assertFalse(self.par_nom["present"]["remote_ajoute"])

    def test_le_remote_d_un_humain_n_est_pas_touche(self):
        autre = self.par_nom["autre"]
        self.assertEqual(autre["url_en_place"], "file:///nulle-part/autre.git")
        self.assertEqual(
            autre["commande"],
            f"git -C {autre['chemin']} remote set-url U"
            f" {self.url('autre.git')}",
        )
        clone = os.path.join(self.racine, autre["chemin"])
        self.assertEqual(
            _git(clone, "config", "remote.U.url"),
            "file:///nulle-part/autre.git",
        )

    def test_le_clone_superficiel_recoit_le_remote_sans_fetch(self):
        lourd = self.par_nom["lourd"]
        self.assertTrue(lourd["remote_ajoute"])
        self.assertIsNone(lourd["cible"])
        self.assertEqual(
            lourd["commande"],
            f"git -C {lourd['chemin']} fetch --depth=10 U principale",
        )
        self.assertEqual(
            _git(self.superficiel, "for-each-ref", "refs/remotes/U"), ""
        )
        self.assertEqual(
            _git(self.superficiel, "config", "--get-all", "remote.U.fetch"),
            "+refs/heads/principale:refs/remotes/U/principale",
        )
        self.assertEqual(
            _git(self.superficiel, "config", "remote.U.skipFetchAll"), "true"
        )
        _git(self.superficiel, "fetch", "-q", "--all")
        self.assertEqual(
            _git(self.superficiel, "for-each-ref", "refs/remotes/U"), ""
        )

    def test_la_comparaison_des_gels_saute_le_remote_du_clone_superficiel(
        self,
    ):
        """`git_freeze_diff.fetch_commits` saute un remote « skipFetchAll »
        comme « git fetch --all » : le commit amont reste absent."""
        from script.git import git_freeze_diff

        sha = self.commit(self.travail, "amont lourd deux")
        _git(
            self.travail,
            "push",
            "-q",
            self.url("lourd.git"),
            "HEAD:principale",
        )
        self.assertEqual(
            git_freeze_diff.fetch_commits(self.superficiel, [sha]), [sha]
        )
        _git(self.superficiel, "config", "remote.U.skipFetchAll", "false")
        self.assertEqual(
            git_freeze_diff.fetch_commits(self.superficiel, [sha]), []
        )

    def test_les_forks_sautes_disent_pourquoi(self):
        self.assertEqual(
            self.par_nom["devine"]["motif"],
            repo_upgrade.t("no fork-upstream-remote attribute"),
        )
        self.assertEqual(
            self.par_nom["sans_branche"]["motif"],
            repo_upgrade.t("no fork-upstream branch for this version"),
        )

    def test_le_rendu_nomme_chaque_fork(self):
        texte = repo_upgrade.render_remotes(self.lst, VERSION, colour=False)
        for x in self.lst:
            self.assertIn(x["chemin"], texte)
        self.assertIn(
            repo_upgrade.t("Skipped: upstream not declared") + " (2)", texte
        )
        self.assertIn(self.par_nom["autre"]["commande"], texte)
        self.assertIn(self.par_nom["lourd"]["commande"], texte)
        self.assertIn(
            repo_upgrade.t("only this command keeps the clone shallow"), texte
        )
        self.assertIn(f"{repo_upgrade.t('Upstream fetched')} 2", texte)
        self.assertNotIn("\033[", texte)

    def test_la_cli(self):
        import contextlib
        import io
        import json

        sortie = io.StringIO()
        with patch.object(
            repo_upgrade, "ajouter_remotes", side_effect=lambda v, d: self.lst
        ), contextlib.redirect_stdout(sortie):
            code = repo_upgrade.main(
                [
                    "--version",
                    VERSION,
                    "--manifest-dir",
                    self.manifestes,
                    "--add-remotes",
                    "--json",
                ]
            )
        self.assertEqual(code, 1)
        charge = json.loads(sortie.getvalue())
        self.assertEqual(len(charge["remotes"]), len(self.lst))


class TestDiagnostiquerParLeRemote(DepotsAvecManifeste):
    def test_le_diagnostic_pose_le_remote_et_vise_sa_branche(self):
        chemin, clone = self.forker("web.git")
        self.commit(self.travail, "amont deux")
        _git(
            self.travail, "push", "-q", self.url("web.git"), "HEAD:principale"
        )
        constat = {
            "chemin": chemin,
            "amont": self.amont_declare("web.git"),
        }
        res = repo_upgrade.diagnostiquer(constat, racine=self.racine)
        self.assertEqual(res["verdict"], "en_retard")
        self.assertEqual(res["cible"], "U/principale")
        self.assertEqual(res["remote_amont"], "ajoute")
        self.assertEqual(
            _git(clone, "rev-parse", "U/principale"),
            _git(self.travail, "rev-parse", "HEAD"),
        )
        # L'état montré s'épingle : le commit amont et HEAD, en entier.
        self.assertEqual(
            res["cible_sha"], _git(self.travail, "rev-parse", "HEAD")
        )
        self.assertEqual(res["head"], _git(clone, "rev-parse", "HEAD"))


class TestCatalogue(unittest.TestCase):
    def test_les_cles_du_remote_amont_sont_traduites(self):
        from script.todo import todo_i18n

        for cle in (
            "🌐 Add the upstream remotes",
            "Add the upstream remotes",
            "Upstream remotes",
            "Upstream fetched",
            "Upstream remotes added:",
            "no local branch moved, no work tree touched",
            "upstream remote points to another URL",
            "the upstream remote could not be added",
            "no fork-upstream-remote attribute",
            "upstream remote absent from the manifests",
            "no fork-upstream branch for this version",
            "Remote with another URL, left untouched",
            "Remote refused by git",
            "Remote set, upstream unreachable",
            "Shallow clone: remote set, fetch skipped",
            "only this command keeps the clone shallow",
            "Not cloned",
            "Remote added and fetched",
            "Remote already present, fetched",
            "Skipped: upstream not declared",
            "add and fetch the named upstream remote of each fork (network)",
        ):
            self.assertIn(cle, todo_i18n.TRANSLATIONS)
            self.assertTrue(todo_i18n.TRANSLATIONS[cle]["fr"])


class TestToutesLesVersions(unittest.TestCase):
    """Les remotes de chaque version installée, et non de la seule active."""

    def setUp(self):
        self.racine = tempfile.mkdtemp(prefix="el_versions_")
        self.addCleanup(shutil.rmtree, self.racine, True)
        self.manifestes = os.path.join(self.racine, "manifest")
        os.mkdir(self.manifestes)
        # 9.0 et 16.0 : arbre et manifeste ; 15.0 : arbre sans manifeste ;
        # 17.0 : manifeste et un FICHIER à la place de l'arbre.
        for version in ("9.0", "16.0", "15.0"):
            os.mkdir(os.path.join(self.racine, f"odoo{version}"))
        open(os.path.join(self.racine, "odoo17.0"), "w").close()
        for version in ("9.0", "16.0", "17.0"):
            open(
                os.path.join(
                    self.manifestes, f"git_manifest_odoo{version}.xml"
                ),
                "w",
            ).close()

    def test_les_versions_installees_croissantes(self):
        self.assertEqual(
            ["9.0", "16.0"],
            repo_upgrade.versions_installees(self.racine, self.manifestes),
        )

    def test_la_cli_passe_chaque_version(self):
        import contextlib
        import io
        import json

        vues = []

        def ajouter(version, dossier):
            vues.append(version)
            issue = "fetch_echoue" if version == "16.0" else "ajoute"
            return [{"chemin": f"odoo{version}/odoo", "issue": issue}]

        sortie = io.StringIO()
        with patch.object(
            repo_upgrade, "versions_installees", return_value=["9.0", "16.0"]
        ), patch.object(
            repo_upgrade, "ajouter_remotes", side_effect=ajouter
        ), contextlib.redirect_stdout(
            sortie
        ):
            code = repo_upgrade.main(
                [
                    "--manifest-dir",
                    self.manifestes,
                    "--add-remotes",
                    "--all-versions",
                    "--json",
                ]
            )
        self.assertEqual(["9.0", "16.0"], vues)
        self.assertEqual(1, code)
        charge = json.loads(sortie.getvalue())
        self.assertEqual(
            ["9.0", "16.0"], [x["version"] for x in charge["versions"]]
        )

    def test_sans_version_la_cli_sort_en_2(self):
        import contextlib
        import io

        with patch.object(
            repo_upgrade, "versions_installees", return_value=[]
        ), contextlib.redirect_stderr(io.StringIO()):
            code = repo_upgrade.main(
                [
                    "--manifest-dir",
                    self.manifestes,
                    "--add-remotes",
                    "--all-versions",
                ]
            )
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
